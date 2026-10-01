#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cut.py — 쇼츠 베이스 영상(ffmpeg): 구간 경계 음성 실측 → 샷별 크롭 → 이어 붙이기 → 음량 정규화.

원칙(기존 쇼츠 파이프라인에서 실제로 깨졌던 것들)
· 전사 시각을 그대로 믿지 않는다(0.2~0.8초 오차). 단어 경계 근처에서 **실제 음량이 떨어지는 지점**으로 컷한다.
  끝은 마지막 단어 end 뒤 최대 0.45초(다음 발화 0.08초 전까지) 안의 첫 조용한 지점 = 스마트 테일(비블).
· 크롭은 식으로 샷마다 바꾸지 않는다. **샷 경계에서 조각을 나눠 각 조각을 자기 크롭으로 따로 자른다**
  → 새 샷 첫 프레임이 이전 크롭으로 잘리던 1프레임 오류가 구조적으로 생기지 않는다(ncs 0.012초 보정의 근본 해결).
· 조각 경계마다 10ms 오디오 페이드(클릭 방지). 음량은 2패스 loudnorm(-14 LUFS, TP -1.5), 끝 페이드아웃.
· crop→scale 뒤 setsar=1(얼굴 찌그러짐 사고). 편집 중간물은 PCM. 최종 base.mp4 는 GOP = fps(HyperFrames 탐색 안정).
"""
import os, sys, json, wave, statistics, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import run, probe

HOP = 0.01   # 음량 창 10ms


def rms_track(wav):
    with wave.open(wav, "rb") as f:
        sr = f.getframerate(); n = f.getnframes(); ch = f.getnchannels()
        a = np.frombuffer(f.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    hop = int(sr * HOP)
    m = len(a) // hop
    r = np.sqrt((a[: m * hop].reshape(m, hop) ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(r + 1e-9)          # dBFS


def level_at(rms, t0, t1):
    i0, i1 = max(0, int(t0 / HOP)), min(len(rms), max(int(t0 / HOP) + 1, int(t1 / HOP)))
    return float(rms[i0:i1].max()) if i1 > i0 else -120.0


def _quiet_edge(rms, t0, t1, from_end):
    """[t0,t1] 안에서 '가장 조용한 값 + 6dB' 이하인 지점 중 from_end 면 가장 늦은(말 시작 직전), 아니면 가장 이른(말 끝 직후) 시각."""
    i0, i1 = max(0, int(t0 / HOP)), min(len(rms) - 1, int(t1 / HOP))
    if i1 <= i0:
        return t0 if not from_end else t1
    seg = rms[i0:i1 + 1]; thr = float(seg.min()) + 6.0
    idx = np.nonzero(seg <= thr)[0]
    k = int(idx[-1] if from_end else idx[0])
    return (i0 + k) * HOP + HOP / 2


_REF = {}


def voice_ref(rms):
    """화자 음성 기준 레벨(유성 구간 RMS 중앙값). 조용함 판정은 이 값 - 24dB (녹음마다 바닥 잡음이 달라 절대값을 쓰지 않는다)."""
    k = id(rms)
    if k not in _REF:
        v = rms[rms > -60]
        _REF[k] = float(np.median(v)) if len(v) else -25.0
    return _REF[k]


def valleys(rms, t0, t1, thr, min_len=0.04):
    """[t0,t1] 안에서 시작하거나 걸친 '조용한 구간'들 [(a,b)] — 창 밖으로 이어지면 실제 끝까지 늘린다."""
    n = len(rms)
    i0, i1 = max(0, int(t0 / HOP)), min(n, int(t1 / HOP) + 1)
    q = rms < thr
    out, i = [], i0
    while i < i1:
        if q[i]:
            j = i
            while j < n and q[j]:
                j += 1
            a = i
            while a > 0 and q[a - 1]:
                a -= 1
            if (j - a) * HOP >= min_len:
                out.append((a * HOP, j * HOP))
            i = j
        else:
            i += 1
    return out


def speech_edge(rms, T, kind, lo=None, hi=None, lead=0.05, tail=0.08):
    """전사 단어 경계 T 근처의 실제 컷 지점.
    kind='start' → 그 단어 발화 시작 직전(골짜기 끝 - lead), kind='end' → 발화가 끝난 직후(골짜기 시작 + tail).
    Whisper 단어 시각은 이어 붙어 있고 0.2~0.8초 이르게 찍히는 일이 잦다 → 늦은 쪽으로 넓게 찾는다."""
    ref = voice_ref(rms)
    w0 = T - 0.30 if lo is None else max(lo, T - 0.30)
    w1 = T + (0.55 if kind == "start" else 0.70)
    if hi is not None:
        w1 = min(w1, hi)
    # 1차: 뚜렷한 쉼(기준 -24dB). 2차: 없으면 '약한 쉼'(기준 -10dB, 60ms 이상 — 숨·끌림·잡음 큰 녹음).
    # 2차가 없던 때는 단어 안의 20ms 골을 골라 첫 음절(너의 → 의)을 자르는 일이 있었다(bibl075 b2).
    for thr, ml in ((ref - 24, 0.04), (ref - 10, 0.06)):
        best, bs = None, -9e9
        for a, b in valleys(rms, w0, w1, thr, min_len=ml):
            d = 0.0 if a <= T <= b else min(abs(T - a), abs(T - b))
            sc = min(b - a, 0.30) - 0.6 * d
            if kind == "end" and b < T - 0.02:
                sc -= 0.08          # 전사상 단어 끝 전에 말이 다시 시작 = 단어 안 폐쇄음 골(있-다 의 ㄷ) → 끝 음절을 자르지 않게
            if sc > bs:
                best, bs = (a, b), sc
        if best:
            a, b = best
            return (b - min(lead, (b - a) / 2)) if kind == "start" else (a + min(tail, (b - a) / 2)), best
    i0, i1 = max(0, int((T - 0.10) / HOP)), min(len(rms) - 1, int((T + 0.20) / HOP))    # 쉼이 없으면 가장 낮은 지점
    k = i0 + int(np.argmin(rms[i0:i1 + 1])) if i1 > i0 else i0
    return k * HOP + HOP / 2, None


def refine(segments, words, rms, dur, lead=0.05, tail=0.08):
    """segments: [{in,out,...}] (원본 초). 구간 첫 단어의 실제 발화 시작 직전 / 끝 단어의 실제 발화 끝 직후로 경계를 옮긴다.
    in_exact/out_exact 가 true 면 그 경계는 지정 값을 그대로 쓴다(말 단위 삭제로 이미 실측한 안쪽 경계)."""
    out, notes = [], []
    for s in segments:
        a, b = float(s["in"]), float(s["out"])
        # 구간 안 단어 = 단어 중점이 [a-0.05, b+0.05] 안(끝 = '마지막 단어 end'로 줘도 다음 짧은 말을 끌어오지 않게)
        inside = [w for w in words if a - 0.05 <= (w["start"] + w["end"]) / 2 <= b + 0.05]
        if inside:
            first, last = inside[0], inside[-1]
            i_first, i_last = words.index(first), words.index(last)
            prev_start = words[i_first - 1]["start"] if i_first > 0 else 0.0
            next_end = words[i_last + 1]["end"] if i_last + 1 < len(words) else dur
            a2 = a if s.get("in_exact") else speech_edge(rms, first["start"], "start", lo=prev_start + 0.05,
                                                          hi=first["end"] - 0.05, lead=lead)[0]
            if s.get("out_exact"):
                b2, sp_end = b, None
            else:
                b2, vb = speech_edge(rms, last["end"], "end", lo=last["start"] + 0.05, hi=next_end - 0.05, tail=tail)
                sp_end = vb[0] if vb else b2                  # 실제 말이 끝난 시각(끝 페이드는 이 뒤에서만)
            s = {**s, "speech_end": round(sp_end, 3) if sp_end else None}
            if abs(a2 - a) > 0.3 or abs(b2 - b) > 0.5:
                notes.append(f"{s.get('id', '')}: 경계 {a:.2f}-{b:.2f} → {a2:.2f}-{b2:.2f}")
            a, b = a2, b2
            s = {**s, "first_word": first["text"], "last_word": last["text"]}
        else:
            notes.append(f"{s.get('id', '')}: 구간 안에 단어 없음 — 경계 그대로 {a:.2f}-{b:.2f}")
        out.append({**s, "in": round(max(0.0, a), 3), "out": round(min(dur, b), 3)})
    return out, notes


def crop_box(src_w, src_h, face, layout, zoom=1.0):
    """레이아웃 비율의 크롭 박스(원본 픽셀). face = {cx,cy,fh}(0~1, 없으면 None).
    full_height: 원본 세로 전체(zoom>1 이면 좁혀서 얼굴을 위 36%에), 얼굴 x 중앙.
    face_scale : 비블 와이드 구도 — 크롭 높이 = 얼굴높이×mult(원본 높이 min_h~max_h), 얼굴 중심이 크롭 위 face_y."""
    band = layout["band"]; aspect = band["w"] / band["h"]
    cfg = layout.get("crop", {"mode": "full_height"})
    cx = face.get("cx") if face else None
    cy = face.get("cy") if face else None
    fh = face.get("fh") if face else None
    cx = 0.5 if cx is None else cx
    if cfg.get("mode") == "face_scale":
        lim = cfg.get("bottom_limit", 1.0) * src_h
        if fh:
            ch = fh * src_h * cfg.get("face_h_mult", 3.6)
            ch = max(cfg.get("min_h", 0.667) * src_h, min(cfg.get("max_h", 0.894) * src_h, ch))
        else:
            ch = cfg.get("max_h", 0.894) * src_h
        ch = min(ch / zoom, lim)
        cw = ch * aspect
        if cw > src_w:
            cw = src_w; ch = cw / aspect
        fy = cfg.get("face_y", 0.36)
        y = (cy if cy is not None else 0.4) * src_h - fy * ch
        y = max(0.0, min(min(src_h, lim) - ch, y))
    else:
        ch = src_h / zoom
        cw = ch * aspect
        if cw > src_w:
            cw = src_w; ch = cw / aspect
        y = 0.0
        if ch < src_h:
            y = max(0.0, min(src_h - ch, (cy if cy is not None else 0.4) * src_h - ch * 0.36))
            lim = cfg.get("bottom_limit", 1.0) * src_h     # 번인 자막 위까지만(2026-09-30 — 얼굴이 낮은 조각에서 자막 윗줄이 비치지 않게)
            if lim < src_h:
                y = max(0.0, min(y, lim - ch))
    x = cx * src_w - cw / 2
    x = max(0.0, min(src_w - cw, x))
    even = lambda v: int(round(v / 2) * 2)
    return {"x": even(x), "y": even(y), "w": even(cw), "h": even(ch)}


def camera_path(faces, pa, pb, cw_frac, dead=0.17, min_pan=0.8, max_pan=1.2, speed=0.15, lead=0.3):
    """샷 안에서 화자가 움직일 때의 가상 카메라(원본 폭 비율 cx 키프레임).
    얼굴 중심이 크롭 중앙 ±dead(크롭 폭 비율) 안이면 가만히 있고, 벗어나면 부드럽게(스무스스텝) 다시 가운데로 민다.
    원칙: 정지가 기본, 움직임은 필요할 때만(수학 분할화면 학습과 같은 취향). → [(t_rel, cx)] 두 점 이상이면 팬."""
    fr = [(f["t"] - pa, f["faces"][0]["cx"]) for f in faces.get("frames", []) if pa <= f["t"] < pb and f["faces"]]
    if len(fr) < 4:
        return None
    xs = [c for _, c in fr]
    sm = [statistics.median(xs[max(0, i - 2): i + 3]) for i in range(len(xs))]      # 1.25초 중앙값 필터(떨림 제거)
    head = [c for (t, _), c in zip(fr, sm) if t < 2.0] or sm[:3]
    cam = statistics.median(head)
    keys = [(0.0, cam)]
    busy_until = -1.0
    for (t, _), c in zip(fr, sm):
        if t < busy_until:
            continue
        if abs(c - cam) > dead * cw_frac:
            dur = max(min_pan, min(max_pan, abs(c - cam) / speed))
            ts = max(keys[-1][0] + 0.05, t - lead)                    # 감지 지연(중앙값 필터) 보정: 0.3초 먼저 출발
            keys.append((round(ts, 3), cam)); keys.append((round(ts + dur, 3), c))
            cam = c; busy_until = ts + dur + 0.8                      # 옮긴 뒤 최소 0.8초는 다시 안 움직인다
    return keys if len(keys) > 1 else None


def crop_x_expr(keys, src_w, cw):
    """[(t, cx)] → ffmpeg crop x 식(구간별 정지/스무스스텝 팬). t 는 조각 시작 기준 초."""
    px = lambda c: max(0.0, min(src_w - cw, c * src_w - cw / 2))
    pts = [(t, px(c)) for t, c in keys]
    expr = f"{pts[-1][1]:.1f}"
    for (ta, xa), (tb, xb) in reversed(list(zip(pts, pts[1:]))):
        if abs(xb - xa) < 0.5 or tb - ta < 1e-3:
            seg = f"{xa:.1f}"
        else:
            u = f"(t-{ta:.3f})/{tb - ta:.3f}"
            seg = f"({xa:.1f}+({xb - xa:.1f})*(3*pow({u},2)-2*pow({u},3)))"
        expr = f"if(lt(t,{tb:.3f}),{seg},{expr})"
    return f"if(lt(t,{pts[0][0]:.3f}),{pts[0][1]:.1f},{expr})"


def crop_x_at(p, t_rel, src_w):
    keys = p.get("track")
    if not keys:
        return p["crop"]["x"]
    cw = p["crop"]["w"]
    px = lambda c: max(0.0, min(src_w - cw, c * src_w - cw / 2))
    if t_rel <= keys[0][0]:
        return px(keys[0][1])
    for (ta, ca), (tb, cb) in zip(keys, keys[1:]):
        if t_rel < tb:
            u = (t_rel - ta) / max(1e-3, tb - ta)
            return px(ca + (cb - ca) * (3 * u * u - 2 * u * u * u))
    return px(keys[-1][1])


def _side_face(faces, pa, pb, side):
    """두 얼굴이 잡힌 프레임에서 왼쪽/오른쪽 사람 얼굴의 중앙값 {cx, cy, w, h} (프레임마다 가로 위치로 정렬). 없으면 None.
    2026-09-30: 예전엔 cy·크기를 faces[0](큰 얼굴 — 두 사람이 섞임)에서 가져와 세로 위치가 다른 사람 기준이 되기도 했다."""
    fs = [sorted(fr["faces"][:2], key=lambda f: f["cx"]) for fr in faces["frames"] if pa <= fr["t"] < pb and len(fr["faces"]) >= 2]
    if not fs:
        return None
    k = 0 if side == "left" else -1
    return {key: statistics.median(ff[k][key] for ff in fs) for key in ("cx", "cy", "w", "h")}


def _two_face_x(faces, pa, pb, side):
    f = _side_face(faces, pa, pb, side)
    return f["cx"] if f else None


def _focus_spans(pa, pb, fmap, default, min_len=0.25):
    """[pa, pb) 를 focus_map([[from, to, focus], …] 원본 초)으로 나눈 [(a, b, focus)]. min_len 보다 짧은 조각은 이웃에 붙인다."""
    cuts = sorted({pa, pb} | {float(x) for m in fmap for x in m[:2] if pa + min_len <= float(x) <= pb - min_len})
    out = []
    for a, b in zip(cuts, cuts[1:]):
        mid = (a + b) / 2
        f = next((m[2] for m in fmap if float(m[0]) <= mid < float(m[1])), default)
        if out and (out[-1][2] == f or b - a < min_len):
            out[-1] = (out[-1][0], b, out[-1][2])
        else:
            out.append((a, b, f))
    return out


HOLD = 0.35     # 구간 첫·끝에 이보다 짧게 걸친 다른 샷 조각은 화면만 이웃 샷 프레임으로 멈춤


def pieces_for(segments, shots, src, layout, faces=None, fps=None):
    """구간 ∩ 샷 → 조각. 각 조각은 자기 크롭(조각 동안의 얼굴 중앙값, 구간의 focus/zoom/layout 지정 우선).
    fps 를 주면 경계를 원본 프레임 격자에 맞춘다 — 같은 구간 안 이웃 조각은 경계 프레임을 공유(빈틈·겹침 0)."""
    ps = []
    for si, s in enumerate(segments):
        a, b = s["in"], s["out"]
        cuts = [sh for sh in shots if sh["end"] > a + 1e-3 and sh["start"] < b - 1e-3] or \
               [{"start": a, "end": b, "cx": 0.5, "cy": 0.4, "fh": None}]
        spans = []
        for sh in cuts:
            qa, qb = max(a, sh["start"]), min(b, sh["end"])
            if qb - qa < 0.08:                              # 샷 경계 바로 앞뒤 2~3프레임은 버린다(다음 샷이 비치는 사고 방지)
                continue
            # 2026-09-30 focus_map: 한 구간 안에서 말하는 사람을 따라 화면을 바꾼다(2인 대담 — 동생이 말할 때 동생 얼굴)
            for pa, pb, f in _focus_spans(qa, qb, s.get("focus_map") or [], s.get("focus", "auto")):
                spans.append((sh, pa, pb, f))
        for sh, pa, pb, f in spans:
            face = {"cx": sh.get("cx"), "cy": sh.get("cy"), "fh": sh.get("fh")}
            own = [fr["faces"][0] for fr in (faces or {}).get("frames", []) if pa <= fr["t"] < pb and fr["faces"]]
            if len(own) >= 3:                                # 샷 전체가 아니라 이 조각 동안의 얼굴 위치
                face = {"cx": statistics.median(x["cx"] for x in own), "cy": statistics.median(x["cy"] for x in own),
                        "fh": statistics.median(x["h"] for x in own)}
            if isinstance(f, (int, float)):
                face["cx"] = float(f)
            elif f in ("left", "right") and faces:
                sf = _side_face(faces, pa, pb, f)
                if sf is not None:
                    face = {"cx": sf["cx"], "cy": sf["cy"], "fh": sf["h"]}
                    bias = (s.get("frame_bias") or {}).get(f)      # 얼굴 폭 단위(+ 오른쪽) — 얼굴이 아니라 사람(머리+몸)을 가운데로
                    if bias:
                        face["cx"] += float(bias) * sf["w"]
            crop = crop_box(src["width"], src["height"], face if face["cx"] is not None else None, layout, float(s.get("zoom", 1.0)))
            piece = {"seg": s.get("id"), "seg_index": si, "in": round(pa, 4), "out": round(pb, 4), "layout": s.get("layout", "crop"),
                     "face": face, "crop": crop}
            if f == "auto" and piece["layout"] == "crop" and faces and s.get("track", True):
                keys = camera_path(faces, pa, pb, crop["w"] / src["width"])
                if keys:                                   # 화자가 움직이는 샷: 가상 카메라가 따라간다
                    piece["track"] = keys
                    piece["crop"] = {**crop, "x": int(round(crop_x_at(piece, 0.0, src["width"]) / 2) * 2)}
            ps.append(piece)
    # 구간 첫·끝이 샷 경계 바로 앞뒤에 걸려 생긴 짧은 조각(HOLD 미만)은 그 샷을 보여주지 않는다 —
    # 소리는 그대로 두고(첫·끝 음절 보존) 화면만 이웃 조각의 첫(끝) 프레임을 멈춰 보여준다.
    # (bibl075 b2: 첫소리 '너'를 살리려 시작을 0.2초 당기자 앞 샷(화면공유) 6프레임이 맨 앞에 비침)
    for si in sorted(set(p["seg_index"] for p in ps)):
        grp = [p for p in ps if p["seg_index"] == si]
        if len(grp) < 2:
            continue
        for p, nb, side in ((grp[0], grp[1], "next"), (grp[-1], grp[-2], "prev")):
            if p["out"] - p["in"] < HOLD and not nb.get("hold"):
                x = crop_x_at(nb, 0.0 if side == "next" else nb["out"] - nb["in"], src["width"]) if nb.get("track") \
                    else nb["crop"]["x"]
                p.update(hold=side, face=nb["face"], layout=nb["layout"], crop={**nb["crop"], "x": int(round(x / 2) * 2)})
                p.pop("track", None)
    if fps:
        for p in ps:
            fa = int(round(p["in"] * fps)); fb = max(fa + 1, int(round(p["out"] * fps)))
            p.update(fa=fa, fb=fb, frames=fb - fa, **{"in": round(fa / fps, 5), "out": round(fb / fps, 5)})
        for i, p in enumerate(ps):                       # 멈춤 화면 = 이웃 조각의 첫 프레임(앞) / 마지막 프레임(끝)
            if p.get("hold"):
                p["still_t"] = round((ps[i + 1]["fa"] if p["hold"] == "next" else ps[i - 1]["fb"] - 1) / fps, 5)
        return quantize(ps, fps)
    for i, p in enumerate(ps):
        if p.get("hold"):
            p["still_t"] = ps[i + 1]["in"] if p["hold"] == "next" else round(ps[i - 1]["out"] - 0.04, 3)
    t = 0.0
    for p in ps:
        p["t0"] = round(t, 3); t += p["out"] - p["in"]; p["t1"] = round(t, 3)
    return ps


def remap_words(words, ps, rms=None):
    """원본 단어 → 쇼츠 시각. 컷이 전사 단어 구간 안쪽에 걸리는 일이 흔하므로(전사 시각이 이르게 찍힘)
    단어 길이의 절반 이상 또는 0.15초 이상 조각과 겹치면 그 조각의 단어로 보고 경계로 자른다.
    rms 를 주면 컷에 걸친 단어는 조각 안쪽 부분에 실제 말소리(기준 -12dB 넘는 소리)가 있을 때만 넣는다 —
    다음 말 첫 단어('근데')가 전사상 쉼 속에서 시작해 컷 앞에 걸치면 들리지 않는 말이 자막에 남던 사고(bibl075 b6)."""
    thr = voice_ref(rms) - 12 if rms is not None else None
    out = []
    for w in words:
        dw = max(0.01, w["end"] - w["start"])
        for p in ps:
            po = p.get("out_q", p["out"])
            ov = min(w["end"], po) - max(w["start"], p["in"])
            if ov >= min(0.15, dw * 0.5) - 1e-6:
                if thr is not None and (w["end"] > po + 0.05 or w["start"] < p["in"] - 0.05):
                    i0, i1 = int(max(w["start"], p["in"]) / HOP), int(math.ceil(min(w["end"], po) / HOP))
                    if i1 <= i0 or float(np.max(rms[i0:i1])) <= thr:
                        continue
                d = p["t0"] - p["in"]
                out.append({**w, "start": round(max(p["t0"], w["start"] + d), 3), "end": round(min(p["t1"], w["end"] + d), 3),
                            "src_start": w["start"], "piece": ps.index(p)})
                break
    return out


def to_short(t_src, ps):
    """원본 시각 → 쇼츠 시각(해당 조각이 없으면 None)."""
    for p in ps:
        if p["in"] - 1e-3 <= t_src <= p.get("out_q", p["out"]) + 1e-3:
            return round(p["t0"] + (t_src - p["in"]), 3)
    return None


def frames_of(p, fps):
    """조각 프레임 수 — 끝 경계(컷) 직전 프레임까지만(내림). 다음 샷 첫 프레임이 끼는 사고를 막는다."""
    return max(1, int(math.floor((p["out"] - p["in"]) * fps + 0.01)))


def quantize(ps, fps):
    """조각 길이를 프레임 단위로 맞추고 쇼츠 시각 t0/t1 을 다시 계산(자막·그래픽 시각이 실제 프레임과 일치)."""
    t = 0.0
    for p in ps:
        p["frames"] = p.get("frames") or frames_of(p, fps)
        p["t0"] = round(t, 4); t += p["frames"] / fps; p["t1"] = round(t, 4)
        p["out_q"] = round(p["in"] + p["frames"] / fps, 5)
    return ps


def runs_of(ps):
    """소리가 이어지는 조각 묶음(같은 구간·경계 프레임 공유). 오디오는 묶음 단위로 한 번에 자른다."""
    runs = []
    for i, p in enumerate(ps):
        if runs and p.get("seg_index") == ps[i - 1].get("seg_index") and p.get("fa") is not None \
                and p.get("fa") == ps[i - 1].get("fb"):
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def wide_out_w(out_w, crop_w, wide):
    """넓은 base 폭: out_w*wide 근처에서 (크롭 폭 = 출력 폭 / 배율)이 짝수 정수가 되는 짝수 폭(가운데 정렬이 반 픽셀로 어긋나지 않게)."""
    if wide <= 1.0:
        return out_w
    s = out_w / crop_w
    for d in range(0, 400, 2):
        W = int(round(out_w * wide / 2)) * 2 + d
        cw = W / s
        if abs(cw - round(cw)) < 1e-6 and int(round(cw)) % 2 == 0:
            return W
    return int(round(out_w * wide / 2)) * 2


def build_base(src_path, ps, out, fps_str, out_w, out_h, audio, src_fps=None, wide=1.0):
    """조각들을 잘라 out_w x out_h 로 이어 붙인 base.mp4 (H.264 CRF 12, GOP=fps, AAC 256k, loudnorm 2패스, 끝 페이드).
    영상: 조각마다 trim=end_frame 으로 정확히 N 프레임(자기 크롭). 소리: 이어지는 조각 묶음마다 한 번에 잘라 샷 경계에서
    끊김·빈틈이 없게 하고, 페이드(10ms)는 원본 시각이 실제로 건너뛰는 편집점에만 준다.
    wide>1(분할 때 인물 축소, 2026-09-28): 같은 가운데·같은 배율로 좌우를 더 넓게 자른 영상(폭 wide_out_w) — 화면에 놓을 때
    가운데 out_w 만 보이면 전과 똑같고, 축소하면 원본 옆 부분이 드러나 가장자리가 비지 않는다."""
    num, den = fps_str.split("/") if "/" in fps_str else (fps_str, "1")
    gop = max(1, round(float(num) / float(den)))
    fps = src_fps or float(num) / float(den)        # 조각 프레임 수·길이는 원본 프레임 기준(출력 fps 변환은 fps 필터가)
    src_w = probe(src_path)["width"]
    runs = runs_of(ps)
    run_first = {r[0]: r for r in runs}
    args = ["ffmpeg", "-loglevel", "error", "-y"]
    for i, p in enumerate(ps):
        span = sum((ps[j].get("frames") or frames_of(ps[j], fps)) for j in run_first[i]) / fps if i in run_first \
            else (p.get("frames") or frames_of(p, fps)) / fps
        args += ["-ss", f"{max(0.0, p['in'] - 0.001):.4f}", "-t", f"{span + 0.5:.3f}", "-i", src_path]
    stills = [i for i, p in enumerate(ps) if p.get("still_t") is not None]
    for i in stills:                                 # 멈춤 화면용 입력(이웃 샷의 한 프레임)
        args += ["-ss", f"{max(0.0, ps[i]['still_t'] - 0.001):.4f}", "-t", "0.5", "-i", src_path]
    fc, vcat, acat = [], "", ""
    c_ref = next((q["crop"] for q in ps if q.get("layout") != "fit"), ps[0]["crop"])
    ow = wide_out_w(out_w, c_ref["w"], wide)             # 넓은 base 폭(wide=1 이면 out_w)
    for i, p in enumerate(ps):
        n = p.get("frames") or frames_of(p, fps)
        c = p["crop"]
        vin = (f"[{len(ps) + stills.index(i)}:v]trim=end_frame=1,setpts=PTS-STARTPTS,tpad=stop={n - 1}:stop_mode=clone"
               if i in stills else f"[{i}:v]trim=end_frame={n},setpts=PTS-STARTPTS")
        if p["layout"] == "fit":         # 16:9 전체를 가로 폭에 맞추고 위아래는 같은 화면을 흐리게 채움(1/8 해상도 블러)
            fc.append(f"{vin},split=2[f{i}][g{i}];[g{i}]scale={ow // 8}:{out_h // 8}:force_original_aspect_ratio=increase,"
                      f"crop={ow // 8}:{out_h // 8},gblur=sigma=5,scale={ow}:{out_h},eq=brightness=-0.08[bg{i}];"
                      f"[f{i}]scale={out_w}:-2:flags=lanczos[fg{i}];[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,fps={fps_str},setsar=1[v{i}]")
        else:
            cw = c["w"] if ow == out_w else min(src_w, int(round(ow * c["w"] / out_w / 2)) * 2)
            if p.get("track"):
                cx_expr = crop_x_expr(p["track"], src_w, cw)     # 가운데 기준 식이라 넓은 폭도 같은 가운데
            else:
                cx_expr = str(c["x"]) if cw == c["w"] else str(int(max(0, min(src_w - cw, c["x"] + c["w"] / 2 - cw / 2))))
            fc.append(f"{vin},crop=w={cw}:h={c['h']}:x='{cx_expr}':y={c['y']}:exact=1,scale={ow}:{out_h}:flags=lanczos,"
                      f"fps={fps_str},setsar=1[v{i}]")
        vcat += f"[v{i}]"
    for k, r in enumerate(runs):
        d = sum((ps[j].get("frames") or frames_of(ps[j], fps)) for j in r) / fps
        fc.append(f"[{r[0]}:a]atrim=duration={d:.6f},asetpts=PTS-STARTPTS,aresample=48000,afade=t=in:d=0.01,"
                  f"afade=t=out:st={max(0, d - 0.012):.4f}:d=0.012[a{k}]")
        acat += f"[a{k}]"
    fc.append(f"{vcat}concat=n={len(ps)}:v=1:a=0[v]")
    fc.append(f"{acat}concat=n={len(runs)}:v=0:a=1[a]")
    pre = out[:-4] + "_pre.mov"
    run(args + ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "12", "-preset", "medium",
                "-g", str(gop), "-keyint_min", str(gop), "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", pre])
    total = sum((p.get("frames") or frames_of(p, fps)) / fps for p in ps)
    lufs, tp, tf = audio.get("lufs", -14.0), audio.get("tp", -1.5), audio.get("tail_fade", 0.2)
    if audio.get("speech_end_short") is not None:        # 마지막 말이 끝난 뒤에만 페이드(말 끝 음절이 묻히던 사고)
        tf = max(0.03, min(tf, total - audio["speech_end_short"] - 0.01))
    m = run(["ffmpeg", "-hide_banner", "-i", pre, "-af", f"loudnorm=I={lufs}:TP={tp}:LRA=11:print_format=json", "-f", "null", "-"])
    js = json.loads(m.stderr[m.stderr.rfind("{"): m.stderr.rfind("}") + 1])
    ln = (f"loudnorm=I={lufs}:TP={tp}:LRA=11:measured_I={js['input_i']}:measured_TP={js['input_tp']}:measured_LRA={js['input_lra']}"
          f":measured_thresh={js['input_thresh']}:offset={js['target_offset']}:linear=true,aresample=48000")
    if tf:
        ln += f",afade=t=out:st={max(0.0, total - tf):.3f}:d={tf:.3f}"
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", pre, "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-af", ln,
         "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out])
    os.remove(pre)
    return {"input_lufs": float(js["input_i"]), "target": lufs, "duration": round(total, 3), "width": ow}
