#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py — short.json → 컷(base.mp4) → 자막 큐 → 그래픽 시각 해석 → HyperFrames 컴포지션 → lint.

  python3 build.py projects/<p>/shorts/<id> [--cut-only] [--force]

short.json (쇼츠 한 편의 단일 진실 — 스키마는 .claude/skills/shorts-edit/references/short-schema.md)
  segments: [{in, out, (id), (focus auto|left|right|0~1), (zoom), (layout crop|fit), (skip:["아까 말했듯이"]), (in_exact/out_exact)}]
  title:    {lines:["1줄","2줄"], status}
  captions: {style brand|pop|karaoke|highlight|fade, emphasis:[단어], emphasis_mode color|marker}
  motion:   {level 0|1|2, feel smooth|snappy|bouncy|...}
  beats:    [{type keyword|number|compare|list|quote|flash|zoom, at_word|at_src|at, dur|until_word, sfx, ...}]
  sfx:      [{name, at_word|at_src|at}]   fix: {틀린:맞는}   remove: [[a,b]] (원본 초)

시각 지정은 **말한 단어 기준(at_word)** 을 권장한다(HyperFrames 가이드 'VO-paced reveals': 그래픽은 그 말을 하는 순간 뜬다).
구간을 바꿔도 단어 기준 비트는 따라 움직인다.
"""
import os, sys, json, argparse, hashlib, re, shutil, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, load_json, save_json, load_brand, probe, hf, tc
import cut as CUT
import textproc as TP
from compose import compose

DEFAULT_DUR = {"keyword": 2.2, "quote": 3.0, "number": 2.6, "compare": 2.8, "list": 0.0, "flash": 0.14, "zoom": 1.6}


def norm(s):
    return re.sub(r"[\s.,!?~…'\"“”‘’·]", "", s)


def find_phrase(words, phrase, nth=1, t_min=None, t_max=None):
    """단어 열에서 phrase(공백·문장부호 무시)의 nth 번째 등장 → (첫 단어 idx, 끝 단어 idx)."""
    target = norm(phrase)
    if not target:
        return None
    chars, owner = [], []
    for i, w in enumerate(words):
        for ch in norm(w["text"]):
            chars.append(ch); owner.append(i)
    s = "".join(chars); k = -1; found = 0
    while True:
        k = s.find(target, k + 1)
        if k < 0:
            return None
        i0, i1 = owner[k], owner[k + len(target) - 1]
        if (t_min is not None and words[i0]["start"] < t_min) or (t_max is not None and words[i1]["end"] > t_max):
            continue
        found += 1
        if found == nth:
            return i0, i1


_ASR = {}
SKIP_NOTES = []


def _hear(wav, t0, t1):
    """원본 음성 [t0,t1] 을 turbo 로 짧게 전사(공백·문장부호 없이). 말 단위 삭제 경계 확인용."""
    import tempfile, mlx_whisper
    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False); f.close()
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{max(0, t0):.3f}", "-t", f"{t1 - max(0, t0):.3f}", "-i", wav, f.name], check=True)
    r = mlx_whisper.transcribe(f.name, path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="ko",
                               condition_on_previous_text=False)
    os.remove(f.name)
    return norm(r.get("text", ""))


def _dips(rms, t0, t1, thr):
    """[t0,t1] 안의 소리 골·음절 경계 후보(±20ms 국소 최소이면서 thr 아래)."""
    H = CUT.HOP; out = []
    for i in range(max(2, int(t0 / H)), min(len(rms) - 2, int(t1 / H))):
        if rms[i] < thr and rms[i] <= rms[i - 2:i + 3].min():
            out.append(i * H + H / 2)
    return out


def verify_skip(wav, rms, a, b, drop_words, next_word, prev_word):
    """들어낸 말이 잘린 뒤에도 들리면 경계를 다음 음절 경계로 옮긴다(최대 0.45초). 전사 시각 대신 실제로 들어서 확인.
    ncs 규칙 '확정 컷점 서브클립을 다시 전사해 첫·끝 단어 확인'의 자동화."""
    thr = CUT.voice_ref(rms) - 8
    last = norm(drop_words[-1]); first = norm(drop_words[0]); nxt = norm(next_word or ""); prv = norm(prev_word or "")
    log = []
    heard = _hear(wav, b, b + 1.3)
    dips = list(_dips(rms, b + 0.03, b + 0.45, thr))
    # 쉼 없이 이어 말하면 골짜기가 없다 — 0.04초 격자도 들어 본다(2026-09-30 bibl_daebon d3 '그래서만나는')
    grid = [round(b + 0.04 * k, 3) for k in range(1, 12) if not any(abs(b + 0.04 * k - d) < 0.02 for d in dips)]
    tries = [b] + sorted(set(dips + grid))
    b0, ok = b, False
    for t in tries:
        heard = _hear(wav, t, t + 1.3) if t != b0 else heard
        # 지운 말의 끝만 남은 경우뿐 아니라 통째로 남은 경우도(첫 두 글자)
        rem = (last and heard.startswith(last[-2:])) or (first and heard.startswith(first[:2]))
        if rem and not (nxt and heard.startswith(nxt[:2])):
            log.append(f"뒤 {t:.2f}s: '{heard[:8]}' — 지운 말이 남음"); continue
        if nxt and not heard.startswith(nxt[:1]):
            log.append(f"뒤 {t:.2f}s: '{heard[:8]}' — 다음 말 '{next_word}' 첫소리 확인 안 됨"); continue
        b, ok = t, True; break
    if not ok:                                         # 끝내 확인 못 함 — 처음 자리 그대로, 호출한 쪽이 경고로 올린다
        b = b0; log.append("!확인 실패")
    heard_a = _hear(wav, a - 1.3, a)
    for t in [a] + sorted(_dips(rms, a - 0.45, a - 0.03, thr), reverse=True):
        heard_a = _hear(wav, t - 1.3, t) if t != a else heard_a
        if first and heard_a.endswith(first[:2]) and not (prv and heard_a.endswith(prv[-2:])):
            log.append(f"앞 {t:.2f}s: '…{heard_a[-8:]}' — 지운 말이 남음"); continue
        a = t; break
    return a, b, log


def _near(heard, want, at_start=True):
    """첫(끝) 몇 글자가 대략 같은가 — '컨텐츠/콘텐츠' 같은 표기 차이로 오경보하지 않게 글자 절반 이상 일치면 같다고 본다."""
    import difflib
    if not want:
        return True
    h = heard[:len(want) + 1] if at_start else heard[-(len(want) + 1):]
    return difflib.SequenceMatcher(None, h, want).ratio() >= 0.5


def verify_edges(segs, words, rms, wav, notes):
    """구간 시작이 전사 첫 단어보다 0.15초 넘게 늦게 잡혔으면(쉼 없는 이음새 — 폐쇄음 무음을 경계로 착각했을 수 있음)
    그 자리를 다시 전사해 첫 단어가 들리는지 확인하고, 안 들리면 더 이른 음절 경계로 되돌린다. 끝도 같은 방식."""
    thr = CUT.voice_ref(rms) - 8
    for s in segs:
        ins = [w for w in words if s["in"] - 0.6 <= (w["start"] + w["end"]) / 2 <= s["out"] + 0.6]
        fw = next((w for w in words if w["text"] == s.get("first_word") and abs(w["start"] - s["in"]) < 0.8), None)
        lw = next((w for w in reversed(words) if w["text"] == s.get("last_word") and abs(w["end"] - s["out"]) < 0.9), None)
        if fw and not s.get("in_exact") and s["in"] > fw["start"] + 0.15:
            want = norm(fw["text"])[:3]
            heard = _hear(wav, s["in"], s["in"] + 1.6)
            if want and not _near(heard, want):
                cands = [fw["start"] - 0.02] + sorted(_dips(rms, fw["start"] - 0.25, s["in"] - 0.03, thr), reverse=True)
                for t in sorted(set(round(c, 3) for c in cands), reverse=True):
                    if t >= s["in"]:
                        continue
                    h = _hear(wav, t, t + 1.6)
                    if _near(h, want):
                        notes.append(f"{s.get('id', '')}: 시작 {s['in']:.2f} → {t:.2f} — '{fw['text']}' 첫소리가 잘려 되돌림(들어서 확인)")
                        s["in"] = round(t, 3); break
                else:
                    notes.append(f"{s.get('id', '')}: 시작 {s['in']:.2f} 에서 '{fw['text']}' 첫소리 확인 안 됨 — 사람 귀 확인 필요")
        if lw and not s.get("out_exact") and s["out"] < lw["end"] - 0.15:
            want = norm(lw["text"])[-3:]
            heard = _hear(wav, s["out"] - 1.6, s["out"])
            if want and not _near(heard, want, at_start=False):
                for t in sorted(set(round(c, 3) for c in [lw["end"] + 0.03] + _dips(rms, s["out"] + 0.03, lw["end"] + 0.3, thr))):
                    if t <= s["out"]:
                        continue
                    h = _hear(wav, t - 1.6, t)
                    if _near(h, want, at_start=False):
                        notes.append(f"{s.get('id', '')}: 끝 {s['out']:.2f} → {t:.2f} — '{lw['text']}' 끝소리가 잘려 늘림(들어서 확인)")
                        s["out"] = round(t, 3); s["speech_end"] = round(t - 0.02, 3); break
                else:
                    notes.append(f"{s.get('id', '')}: 끝 {s['out']:.2f} 에서 '{lw['text']}' 끝소리 확인 안 됨 — 사람 귀 확인 필요")
    return segs


def apply_skips(segments, words, rms, skipped=None, wav=None):
    """segments 의 skip(말 단위 삭제)·remove(원본 초 삭제)를 구간 분할로 바꾼다. 안쪽 경계는 실측 무음 지점(exact).
    skipped(set)에 들어낸 단어 인덱스를 모은다 — 전사 시각이 이르게 찍혀 컷 앞 조각에 걸쳐 보여도 자막에서 뺀다."""
    out = []
    for s in segments:
        pieces = [dict(s)]
        rms_cuts = []
        for ph in s.get("skip", []) or []:
            hit = find_phrase(words, ph, 1, s["in"] - 0.05, s["out"] + 0.3)
            if not hit:
                print(f"  ! skip '{ph}' 을(를) 구간 {s['in']:.2f}-{s['out']:.2f} 안에서 못 찾음")
                continue
            i0, i1 = hit
            if skipped is not None:
                skipped.update(range(i0, i1 + 1))
            # 앞 단어가 실제로 끝난 직후 ~ 다음 단어가 실제로 시작하기 직전까지 들어낸다(전사 시각이 아니라 음량 골짜기 기준)
            lo_a = words[i0 - 1]["start"] + 0.05 if i0 > 0 else s["in"]
            a, va = CUT.speech_edge(rms, words[i0]["start"], "end", lo=lo_a, hi=words[i0]["end"], tail=0.06)
            if i1 + 1 < len(words):
                b, vb = CUT.speech_edge(rms, words[i1 + 1]["start"], "start", lo=words[i1]["start"] + 0.05,
                                        hi=words[i1 + 1]["end"], lead=0.04)
            else:
                b, vb = s["out"], None
            if b <= a + 0.05:
                print(f"  ! skip '{ph}' 경계 측정 실패({a:.2f}≥{b:.2f}) — 전사 시각으로 대체")
                a, b = words[i0]["start"], words[i1]["end"]
            if wav:                                          # 실제로 들어서 확인(지운 말이 남았으면 다음 음절 경계로)
                a0, b0 = a, b
                a, b, vlog = verify_skip(wav, rms, a, b, [w["text"] for w in words[i0:i1 + 1]],
                                         words[i1 + 1]["text"] if i1 + 1 < len(words) else None,
                                         words[i0 - 1]["text"] if i0 > 0 else None)
                for m in vlog:
                    if m == "!확인 실패":
                        print(f"  ! skip '{ph}' — 지운 뒤 다음 말 첫소리를 들어서 확인하지 못함({b:.2f}s) · 사람 귀 확인 필요")
                        SKIP_NOTES.append(f"skip '{ph}' 경계 {a:.2f}-{b:.2f} — 들어서 확인 실패(지운 말이 남았거나 다음 말이 잘렸을 수 있음), 사람 귀 확인 필요")
                    else:
                        print(f"    · 확인 {m}")
                if (a, b) != (a0, b0):
                    print(f"    · 경계 보정 {a0:.2f}-{b0:.2f} → {a:.2f}-{b:.2f} (확인 권장: 폐쇄음 ㄲ·ㄷ·ㄱ 앞 무음은 단어 경계가 아닐 수 있어 들어서 옮김)")
                    SKIP_NOTES.append(f"skip '{ph}' 경계 {a0:.2f}-{b0:.2f} → {a:.2f}-{b:.2f} — 재전사로 보정, 사람 귀 확인 권장")
            rms_cuts.append((a, b, ph + ("" if va and vb else " (쉼 없음: 최저 음량 지점)")))
        for a, b in s.get("remove", []) or []:
            rms_cuts.append((float(a), float(b), f"remove {a}-{b}"))
        for a, b, why in sorted(rms_cuts):
            nxt = []
            for p in pieces:
                if a >= p["out"] or b <= p["in"]:
                    nxt.append(p); continue
                if a > p["in"] + 0.05:
                    nxt.append({**p, "out": round(a, 3), "out_exact": True, "skip": [], "remove": []})
                if b < p["out"] - 0.05:
                    nxt.append({**p, "in": round(b, 3), "in_exact": True, "skip": [], "remove": [],
                                "id": f"{s.get('id', 'seg')}+"})
            pieces = nxt
            print(f"  · 삭제 {a:.2f}-{b:.2f} ({why})")
        out.extend(pieces)
    return out


def resolve_time(bt, key_prefix, words_s, pieces, default=None):
    """at_word(단어) / at_src(원본 초) / at(쇼츠 초) → 쇼츠 초"""
    if bt.get(f"{key_prefix}word"):
        hit = find_phrase(words_s, bt[f"{key_prefix}word"], int(bt.get("nth", 1)))
        if not hit:
            return None
        return words_s[hit[0]]["start"] + float(bt.get("offset", 0))
    if bt.get(f"{key_prefix}src") is not None:
        t = CUT.to_short(float(bt[f"{key_prefix}src"]), pieces)
        return None if t is None else t + float(bt.get("offset", 0))
    if bt.get(key_prefix.rstrip("_") if key_prefix == "at_" else key_prefix) is not None:
        return float(bt[key_prefix.rstrip("_")]) + float(bt.get("offset", 0))
    return default


def resolve_beats(plan, words_s, pieces, D):
    beats, zooms, sfx, notes = [], [], [], []
    for k, bt in enumerate(plan.get("beats", []) or []):
        typ = bt.get("type")
        t0 = resolve_time(bt, "at_", words_s, pieces)
        if t0 is None:
            notes.append(f"비트 {k}({typ}) 시각을 못 정함: {bt.get('at_word') or bt.get('at_src') or bt.get('at')}"); continue
        if t0 > D - 0.2:
            notes.append(f"비트 {k}({typ}) 시작 {t0:.2f}s 가 쇼츠 끝 근처라 {D - 0.2:.2f}s 로 당김")
        t0 = max(0.0, min(D - 0.2, t0))
        if bt.get("until_word"):
            hit = TP_find(words_s, bt["until_word"], t0)
            t1 = words_s[hit]["end"] + 0.25 if hit is not None else t0 + DEFAULT_DUR.get(typ, 2.0)
        else:
            t1 = t0 + float(bt.get("dur", DEFAULT_DUR.get(typ, 2.0)))
        if t1 > D + 1e-3:
            notes.append(f"비트 {k}({typ}) 끝 {t1:.2f}s 가 쇼츠 끝({D:.2f}s)에서 잘림 — 길이 {max(0, D - t0):.2f}s")
        r = {**bt, "t0": round(t0, 3), "t1": round(min(D, t1), 3), "src_index": k}
        if typ == "list":
            items = []
            for it in bt.get("items", []):
                ti = resolve_time(it, "at_", words_s, pieces, default=None)
                items.append({**it, "t": round(ti if ti is not None else t0 + 0.4 * len(items), 3)})
            r["items"] = items
            r["t0"] = round(min([t0] + [it["t"] for it in items]) - 0.05, 3)
            last = max(it["t"] for it in items) if items else t0
            r["t1"] = round(min(D, max(r["t1"], last + float(bt.get("hold", 1.8)))), 3)
        if typ == "compare":
            tr = resolve_time({"at_word": bt.get("right_word"), "at": bt.get("right_at")}, "at_", words_s, pieces) \
                if (bt.get("right_word") or bt.get("right_at") is not None) else None
            r["t_right"] = round(tr if tr is not None else t0 + 0.7, 3)
        if typ == "zoom":
            if bt.get("style") == "push" and not bt.get("dur") and not bt.get("until_word"):
                ends = [p["t1"] for p in pieces if p["t1"] > t0 + 0.8]
                r["t1"] = round(min(ends) if ends else D, 3)
            else:                                            # 줌 복귀가 컷 근처면 컷에 맞춘다(말 중간 튐 방지)
                ends = [p["t1"] for p in pieces if abs(p["t1"] - r["t1"]) <= 0.8]
                if ends:
                    r["t1"] = round(ends[0], 3)
            zooms.append(r)
        else:
            beats.append(r)
        if bt.get("sfx"):
            sfx.append({"name": bt["sfx"], "t": round(max(0.0, t0 - (0.05 if typ != "flash" else 0.0)), 3)})
    beats.sort(key=lambda b: b["t0"])
    gfx = [b for b in beats if b["type"] != "broll"]       # B-roll 카드는 영상 밴드를 덮는 층이라 그래픽 겹침 규칙에서 뺀다(이어지는 카드 사이 빈틈 방지)
    for a, b in zip(gfx, gfx[1:]):                           # 겹치면 앞 그래픽을 다음 시작 0.08초 전에 끊는다(최소 0.8초)
        if b["type"] != "flash" and a["type"] != "flash" and a["t1"] > b["t0"] - 0.08:
            a["t1"] = round(max(a["t0"] + 0.8, b["t0"] - 0.08), 3)
    for s in plan.get("sfx", []) or []:
        t = resolve_time(s, "at_", words_s, pieces)
        if t is not None:
            sfx.append({"name": s["name"], "t": round(max(0.0, t + float(s.get("offset", 0))), 3), **({"vol": s["vol"]} if "vol" in s else {})})
    return beats, zooms, sfx, notes


def TP_find(words, phrase, t_min):
    hit = find_phrase(words, phrase, 1, t_min=t_min)
    return hit[1] if hit else None


def faces_in_canvas(faces, pieces, src, band):
    """원본 얼굴 박스 → 쇼츠 시각·캔버스 px (조각 크롭 → 밴드 배율)."""
    out = []
    for fr in faces.get("frames", []):
        if not fr["faces"]:
            continue
        for p in pieces:
            if p["in"] <= fr["t"] < p["out"] and not p.get("hold"):   # 멈춤 조각은 원본 그 시각의 샷이 아님
                c = p["crop"]
                sx, sy = band["w"] / c["w"], band["h"] / c["h"]
                cxp = CUT.crop_x_at(p, fr["t"] - p["in"], src["width"])      # 가상 카메라 팬 반영
                # 2인 화면: 이 조각 크롭 안(가운데에 가까운) 얼굴 — faces[0] 이 옆 사람이면 분할 배치·검수가 엉뚱한 얼굴 기준이 됨(2026-09-30)
                mid = cxp + c["w"] / 2
                f = min(fr["faces"], key=lambda q: abs(q["cx"] * src["width"] - mid))
                x0 = ((f["cx"] - f["w"] / 2) * src["width"] - cxp) * sx + band["x"]
                x1 = ((f["cx"] + f["w"] / 2) * src["width"] - cxp) * sx + band["x"]
                y0 = ((f["cy"] - f["h"] / 2) * src["height"] - c["y"]) * sy + band["y"]
                y1 = ((f["cy"] + f["h"] / 2) * src["height"] - c["y"]) * sy + band["y"]
                out.append({"t": round(p["t0"] + fr["t"] - p["in"], 3), "box": [round(x0), round(y0), round(x1), round(y1)]})
                break
    return out


def prepare_bgm(plan, pdir, bdir, D, brand):
    """BGM 파일 → 목소리(브랜드 LUFS)보다 db_under(기본 18dB) 아래로 맞추고, 길이 맞춤(반복)·0.6초 페이드 인·1.2초 페이드 아웃 → build/bgm.m4a.
    가이드 'Media and audio': 음악은 목소리 밑에, 목표 음량을 숫자로."""
    b = plan.get("bgm") or {}
    if not b.get("file"):
        return None
    src = b["file"] if os.path.isabs(b["file"]) else os.path.join(pdir, b["file"])
    if not os.path.exists(src):
        print(f"  ! BGM 파일 없음: {src} — BGM 없이 진행"); return None
    tgt = brand["audio"]["lufs"] - float(b.get("db_under", 18))
    out = os.path.join(bdir, "bgm.m4a")
    af = (f"aloop=loop=-1:size=2e9,atrim=0:{D:.3f},loudnorm=I={tgt}:TP=-6:LRA=11,"
          f"afade=t=in:d=0.6,afade=t=out:st={max(0, D - 1.2):.3f}:d=1.2,aresample=48000")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vn", "-af", af, "-c:a", "aac", "-b:a", "192k", out], check=True)
    print(f"[build] BGM {os.path.basename(src)} → 목소리보다 {b.get('db_under', 18)}dB 아래({tgt} LUFS)")
    return {"file": "bgm.m4a"}


def two_shot_ratio(faces, segs):
    """구간 안 얼굴 프레임 중 '비슷한 크기의 얼굴 둘'이 잡힌 비율 — 2인 대담 판정."""
    fr = [f["faces"] for f in faces.get("frames", []) if f["faces"] and any(s["in"] <= f["t"] < s["out"] for s in segs)]
    if not fr:
        return 0.0
    return sum(1 for ff in fr if len(ff) >= 2 and ff[1]["h"] >= 0.5 * ff[0]["h"]) / len(fr)


def two_shot(pieces, faces, src, layout):
    """2인 대담 구도(비블 2026-08-06 '영상 비율을 깨면서까지 틀을 맞출 필요 없음'): 두 사람(어깨·손·테이블까지)을
    담는 크롭을 조각마다 구하고, 크기는 쇼츠 전체에서 하나로 맞춘다(밴드 높이가 컷마다 튀지 않게). 반환: 밴드 높이."""
    import statistics as st
    Ws, Hs = src["width"], src["height"]
    lim = layout.get("crop", {}).get("bottom_limit", 1.0) * Hs
    regs = []
    for p in pieces:
        if p.get("hold"):                                  # 멈춤 조각은 이웃 조각의 크롭을 따른다(아래)
            regs.append(None); continue
        fr = [f["faces"] for f in faces.get("frames", []) if p["in"] <= f["t"] < p["out"] and f["faces"]]
        twos = [sorted(ff[:2], key=lambda f: f["cx"]) for ff in fr if len(ff) >= 2 and ff[1]["h"] >= 0.5 * ff[0]["h"]]
        if twos and len(twos) >= max(2, 0.4 * len(fr)):
            L = {k: st.median(t[0][k] for t in twos) for k in ("cx", "cy", "w", "h")}
            R = {k: st.median(t[1][k] for t in twos) for k in ("cx", "cy", "w", "h")}
            fw, fh = max(L["w"], R["w"]), max(L["h"], R["h"])
            x0, x1 = (L["cx"] - L["w"] / 2 - 1.1 * fw) * Ws, (R["cx"] + R["w"] / 2 + 1.1 * fw) * Ws
            top = min(L["cy"] - L["h"] / 2, R["cy"] - R["h"] / 2); bot = max(L["cy"] + L["h"] / 2, R["cy"] + R["h"] / 2)
        elif fr:
            one = [ff[0] for ff in fr]
            F = {k: st.median(f[k] for f in one) for k in ("cx", "cy", "w", "h")}
            fw, fh = F["w"], F["h"]
            x0, x1 = (F["cx"] - F["w"] / 2 - 2.2 * fw) * Ws, (F["cx"] + F["w"] / 2 + 2.2 * fw) * Ws
            top, bot = F["cy"] - F["h"] / 2, F["cy"] + F["h"] / 2
        else:
            regs.append(None); continue
        y0, y1 = (top - 0.9 * fh) * Hs, min(lim, (bot + 3.0 * fh) * Hs)
        regs.append([max(0, x0), max(0, y0), min(Ws, x1), y1])
    ok = [r for r in regs if r]
    if not ok:
        return None
    Wr = min(Ws, max(r[2] - r[0] for r in ok)); Hr = min(lim, max(r[3] - r[1] for r in ok))
    nb = layout.get("natural_band", {})
    bh = int(round(1080 * Hr / Wr / 2) * 2)
    bh2 = max(nb.get("min_h", 480), min(nb.get("max_h", 1267), bh))
    if bh2 != bh:                                          # 밴드 한도에 맞춰 크롭 비율 조정(세로 우선 유지)
        Wr = min(Ws, Hr * 1080 / bh2); Hr = Wr * bh2 / 1080; bh = bh2
    even = lambda v: int(round(v / 2) * 2)
    for p, r in zip(pieces, regs):
        if p.get("hold"):
            continue
        cx = (r[0] + r[2]) / 2 if r else Ws / 2
        cy = (r[1] + r[3]) / 2 if r else Hs * 0.45
        x = max(0, min(Ws - Wr, cx - Wr / 2)); y = max(0, min(lim - Hr, cy - Hr / 2))
        p["crop"] = {"x": even(x), "y": even(y), "w": even(Wr), "h": even(Hr)}
        p.pop("track", None); p["frame"] = "two"
    for i, p in enumerate(pieces):
        if p.get("hold"):
            nb = pieces[i + 1] if p["hold"] == "next" else pieces[i - 1]
            p["crop"] = dict(nb["crop"]); p.pop("track", None); p["frame"] = "two"
    return bh


def write_srt(cues, path):
    def ts(t):
        ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    with open(path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            f.write(f"{i}\n{ts(c['start'])} --> {ts(c['end'])}\n" + "\n".join(c["lines"]) + "\n\n")


def link_or_copy(a, b):
    if os.path.exists(b):
        os.remove(b)
    try:
        os.link(a, b)
    except OSError:
        shutil.copy2(a, b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("short_dir"); ap.add_argument("--cut-only", action="store_true"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    sdir = os.path.abspath(a.short_dir)
    pdir = os.path.dirname(os.path.dirname(sdir))
    plan = load_json(os.path.join(sdir, "short.json"))
    if plan is None:
        raise SystemExit(f"short.json 없음: {sdir}")
    source = load_json(os.path.join(pdir, "source.json"))
    brand = load_brand(plan.get("brand") or source.get("brand", "bibl"))
    words = load_json(os.path.join(pdir, "words.json"))
    faces = load_json(os.path.join(pdir, "faces.json"), {"frames": [], "shots": []})
    corr = list((brand.get("corrections") or {}).items()) if isinstance(brand.get("corrections"), dict) else list(brand.get("corrections") or [])
    corr += list((plan.get("fix") or {}).items())
    words = TP.correct_words(words, corr)
    rms = CUT.rms_track(os.path.join(pdir, "audio.wav"))
    D_src = source["duration"]

    skipped = set()
    segs = apply_skips(plan["segments"], words, rms, skipped, wav=os.path.join(pdir, "audio.wav"))
    segs, notes = CUT.refine(segs, words, rms, D_src)
    notes = SKIP_NOTES + notes
    segs = verify_edges(segs, words, rms, os.path.join(pdir, "audio.wav"), notes)
    for n in notes:
        print("  ·", n)
    layout = brand["layout"]; band = layout["band"]
    subs_top = ((faces or {}).get("subs") or {}).get("top")
    if subs_top:                                           # 원본에 구워진 자막: 크롭 아래 한계를 그 위로
        cfg = layout.setdefault("crop", {})
        cfg["bottom_limit"] = round(min(cfg.get("bottom_limit", 1.0), subs_top - 0.012), 4)
        print(f"[build] 번인 자막 감지(가장 높은 줄 {subs_top:.3f}H) → 크롭 아래 한계 {cfg['bottom_limit']:.3f}H")
        need = 1.0 / cfg["bottom_limit"]                   # 크롭 높이 ≤ 아래 한계여야 자막 위만 담긴다
        low = [s.get("id", i) for i, s in enumerate(plan["segments"]) if float(s.get("zoom") or 1.0) < need - 1e-3]
        if layout.get("mode") == "full" and low:
            print(f"  ! 9:16 전체 높이 크롭이라 옛 자막이 화면에 남습니다(구간 {low}) — 클린본을 쓰거나 segments zoom {need:.2f} 이상으로 위만 쓰세요")
    shots = faces.get("shots") or [{"start": 0, "end": D_src, "cx": 0.5, "cy": 0.4, "fh": None}]
    fps = source["fps_str"] if brand["encode"].get("fps", "30") == "source" else str(brand["encode"]["fps"])
    fps_f = eval(fps) if "/" in fps else float(fps)
    src_fps = eval(source["fps_str"]) if "/" in source["fps_str"] else float(source["fps_str"])
    # 조각 경계는 '원본' 프레임 격자에 맞춘다(샷 경계 = 새 샷 첫 프레임). 출력 fps 가 달라도(비블 30) 경계는 원본 기준.
    pieces = CUT.pieces_for(segs, shots, source, layout, faces, fps=src_fps)
    if not pieces:
        raise SystemExit("조각이 없습니다 — segments 를 확인하세요")
    frame = plan.get("frame", "auto")
    if layout.get("mode") == "band" and (frame == "two" or (frame == "auto" and two_shot_ratio(faces, segs) >= 0.6)):
        bh = two_shot(pieces, faces, source, layout)
        if bh:                                             # 원비율 밴드: 높이·자막·워터마크 자리를 다시 잡는다(v2 규칙)
            nb = layout.get("natural_band", {})
            band = layout["band"] = {**band, "h": bh}
            if nb.get("cap_frac") is not None:
                brand["captions"]["y"] = round(band["y"] + nb["cap_frac"] * bh)
            if nb.get("wm") == "bottom_center" and brand.get("watermark"):
                brand["watermark"]["y"] = round((band["y"] + bh + brand["canvas"]["h"]) / 2)
            if brand.get("graphics"):
                gb = band["y"] + bh
                brand["graphics"]["zone"] = [60, gb + 30, 1020, min(brand["canvas"]["h"] - 330, gb + 250)]
            c0 = pieces[0]["crop"]
            print(f"[build] 2인 대담 구도: 크롭 {c0['w']}x{c0['h']} → 영상 밴드 1080x{bh} @y{band['y']} (원비율)")
    D = round(pieces[-1]["t1"], 3)
    bdir = os.path.join(sdir, "build"); os.makedirs(bdir, exist_ok=True)
    sp_ = brand.get("split") or {}
    has_broll = any((b or {}).get("type") == "broll" for b in plan.get("beats", []) or [])
    wide = (1.0 / float(sp_["person_scale"]) + 0.005) if (has_broll and sp_.get("person_scale") and float(sp_["person_scale"]) < 1) else 1.0
    key = hashlib.md5(json.dumps([source["src"], segs[-1].get("speech_end") if segs else None,
                                  [(p["in"], p["out"], p["crop"], p["layout"], p.get("track"), p.get("still_t")) for p in pieces],
                                  band["w"], band["h"], fps, brand["audio"]] + ([round(wide, 4)] if wide > 1 else []),
                                 sort_keys=True).encode()).hexdigest()
    kpath = os.path.join(bdir, "base.key")
    base = os.path.join(bdir, "base.mp4")
    if a.force or not os.path.exists(base) or (open(kpath).read() if os.path.exists(kpath) else "") != key:
        print(f"[build] 컷 {len(pieces)}조각 · {D:.2f}초 → base.mp4 ({band['w']}x{band['h']} @ {fps})", flush=True)
        aud = dict(brand["audio"])
        se = segs[-1].get("speech_end") if segs else None
        if se is not None:
            p_last = pieces[-1]
            aud["speech_end_short"] = round(p_last["t0"] + (se - p_last["in"]), 3)
        info = CUT.build_base(source["src"], pieces, base, fps, band["w"], band["h"], aud, src_fps=src_fps, wide=wide)
        open(kpath, "w").write(key)
        print(f"[build] 음량 {info['input_lufs']:.1f} → {info['target']} LUFS")
    else:
        print("[build] base.mp4 재사용(컷 동일)")
    out_dir = os.path.join(sdir, "out"); os.makedirs(out_dir, exist_ok=True)
    resolved = {"segments": segs, "pieces": pieces, "duration": D, "fps": fps, "notes": notes, "brand": brand["name"]}
    if a.cut_only:
        cp = os.path.join(out_dir, f"{plan.get('id', 'short')}_컷확인.mp4")
        link_or_copy(base, cp)
        save_json(os.path.join(sdir, "resolved.json"), resolved)
        print(f"[build] 컷확인본(자막·제목 없음) → {cp}")
        return

    kept = [w for i, w in enumerate(words) if i not in skipped]
    idx, gen = os.path.join(bdir, "index.html"), os.path.join(bdir, ".generated.md5")
    if os.path.exists(idx) and os.path.exists(gen) and not a.force:
        if hashlib.md5(open(idx, "rb").read()).hexdigest() != open(gen).read().strip():
            raise SystemExit("build/index.html 이 생성 후 손으로(Studio 등) 바뀌었습니다. 바뀐 내용을 short.json/captions.edit.json 에 "
                             "옮긴 뒤 다시 build 하거나, 버려도 되면 --force.  (npx hyperframes timeline --json 으로 차이 확인)")
    ws = TP.filter_hallucinated(CUT.remap_words(kept, pieces, rms), D)
    cap = brand["captions"]
    if cap["chunker"] == "v31":
        cues = TP.chunk_v31(ws, cap.get("max_chars", 8), cap.get("max_line", 9), cap.get("strip", TP.PUNCT_ALL))
        for c in cues:
            c["lines"] = TP.two_lines_v31(c["text"], cap["font"], cap["size"], cap["max_w"] / cap.get("xscale", 1.0))
    else:
        cues = TP.chunk_meaning(ws, cap["font"], cap.get("measure_size", cap["size"]), cap["max_w"], cap.get("strip", "."),
                                segments=load_json(os.path.join(pdir, "segments.json")))
    cues = TP.fill_gaps(cues, float(cap.get("gap_fill", 0.0)), D)
    # auto 는 늘 엔진이 만든 자막(사람 수정본과 비교·재작성용). 예전엔 수정본을 auto 에 덮어써 엔진판이 사라졌다.
    save_json(os.path.join(sdir, "captions.auto.json"), [{"start": round(c["start"], 3), "end": round(c["end"], 3), "lines": c["lines"]} for c in cues])
    edit = load_json(os.path.join(sdir, "captions.edit.json"))
    if edit:                                               # 사람이 고친 자막이 있으면 그대로 쓴다
        cues = TP.fill_gaps([{"start": c["start"], "end": c["end"], "lines": c["lines"], "text": " ".join(c["lines"]), "wi": []}
                             for c in edit], float(cap.get("gap_fill", 0.0)), D)
        print(f"[build] 자막: captions.edit.json 사용({len(cues)}큐)")
        ekp = os.path.join(sdir, "captions.edit.key")       # 수정본을 만든 때의 컷(조각) — 컷이 바뀌면 시각이 어긋난다
        cut_sig = hashlib.md5(json.dumps([(p["in"], p["out"]) for p in pieces]).encode()).hexdigest()
        if not os.path.exists(ekp):
            open(ekp, "w").write(cut_sig)
        elif open(ekp).read().strip() != cut_sig:
            print("  ! captions.edit.json 은 컷이 바뀌기 전에 만든 수정본입니다 — 자막 시각이 어긋날 수 있습니다. "
                  "captions.auto.json 과 비교해 고친 뒤 captions.edit.key 를 지우세요")
    write_srt(cues, os.path.join(out_dir, f"{plan.get('id', 'short')}.srt"))

    fcs = faces_in_canvas(faces, pieces, source, band)
    beats, zooms, sfx, bnotes = resolve_beats(plan, ws, pieces, D)
    if (plan.get("negatives") or {}).get("no_graphics"):  # '그래픽 없음(자막만)': 카드·줌·효과음 전부 뺀다
        if beats or zooms:
            bnotes.append(f"negatives.no_graphics — 그래픽 {len(beats)}·줌 {len(zooms)} 을 넣지 않음")
        beats, zooms, sfx = [], [], []
    for bt in beats:                                         # B-roll 카드: 롱폼 B-roll 을 세로 밴드용으로 렌더한 영상(유튜브 B-roll/engine/shorts_cards.py)
        if bt["type"] != "broll":
            continue
        src = bt.get("src") or ""
        if not os.path.isabs(src):
            src = os.path.join(pdir, src)
        if not os.path.exists(src):
            bnotes.append(f"B-roll 카드 파일 없음: {src}"); bt["type"] = "skip"; continue
        os.makedirs(os.path.join(bdir, "broll"), exist_ok=True)
        dst = os.path.join(bdir, "broll", os.path.basename(src))
        if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
            shutil.copy2(src, dst)
        bt["src_rel"] = "broll/" + os.path.basename(src)
        if not bt.get("dur") and not bt.get("until_word"):     # 길이를 안 적었으면 카드 영상 길이
            r_ = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src], capture_output=True, text=True)
            bt["t1"] = round(min(D, bt["t0"] + float(r_.stdout.strip() or 2.0)), 3)
    beats = [b for b in beats if b["type"] != "skip"]
    brs = sorted([b for b in beats if b["type"] == "broll"], key=lambda b: b["t0"])
    for a_, b_ in zip(brs, brs[1:]):                         # 이어지는 카드(틈 0.1초 미만)는 한 프레임 겹친다 — 반올림 틈에 걸린 프레임이
        if b_["t0"] - a_["t1"] < 0.1:                         # 빈 패널(화자 머리)로 깜빡이지 않게. 뒤 카드가 DOM 뒤라 위에 그려진다
            a_["t1"] = round(min(D, max(a_["t1"], b_["t0"] + 0.04)), 3)
    for n in bnotes:
        print("  !", n)
    if (plan.get("negatives") or {}).get("no_sfx") or (plan.get("negatives") or {}).get("no_audio"):
        sfx = []
    bgm = prepare_bgm(plan, pdir, bdir, D, brand) if not (plan.get("negatives") or {}).get("no_bgm") \
        and not (plan.get("negatives") or {}).get("no_audio") else None
    c_ref = next((p["crop"] for p in pieces if p.get("layout") != "fit"), pieces[0]["crop"])
    ctx = {"duration": D, "fps": fps, "words": ws, "cues": cues, "faces": fcs, "beats": beats, "zooms": zooms, "sfx": sfx,
           "bgm": bgm, "base_w": CUT.wide_out_w(band["w"], c_ref["w"], wide)}      # 넓은 base(분할 인물 축소)면 band 보다 넓다
    sev = []                                                  # 쇼츠 효과음 자동 배치용 사건(패널 새 그림 — make_split_beats 가 적음, 롱폼 초)
    if not ((plan.get("negatives") or {}).get("no_sfx") or (plan.get("negatives") or {}).get("no_audio")):
        for e in plan.get("sfx_events") or []:
            t = resolve_time(e, "at_", ws, pieces)
            if t is not None and 0 <= t < D:
                sev.append({"t": round(t, 3), "role": e["role"]})
    else:
        plan["sfx_auto"] = False
    ctx["sfx_events"] = sev
    man = compose(bdir, brand, plan, ctx)
    sfx = man.get("sfx", sfx)
    resolved.update({"cues": len(cues), "beats": beats, "zooms": zooms, "sfx": sfx, "beat_notes": bnotes,
                     "warnings": man["warnings"], "title": man["title"]})
    save_json(os.path.join(sdir, "resolved.json"), resolved)
    for w in man["warnings"]:
        print("  !", w)
    r = hf(["lint", bdir], cwd=bdir, check=False)
    out = (r.stdout or "") + (r.stderr or "")
    errs = re.findall(r"(\d+)\s+error", out)
    print(f"[build] 자막 {len(cues)}큐 · 그래픽 {len(beats)} · 줌 {len(zooms)} · 효과음 {len(sfx)} · 길이 {D:.2f}초")
    print("[lint] " + (out.strip().splitlines()[-1] if out.strip() else "출력 없음"))
    if r.returncode != 0:
        print(out[-3000:])
        raise SystemExit("lint 실패 — 위 오류를 고친 뒤 다시 build")


if __name__ == "__main__":
    main()
