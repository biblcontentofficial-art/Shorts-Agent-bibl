#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa.py — 완성 쇼츠 자동 검수(사람 검수 전에 기계가 잡을 수 있는 것을 전부 잡는다).

  python3 qa.py projects/<p>/shorts/<id> [--no-transcribe] [--no-faces] [--no-hf-check]

검사(과거 반려 사유 기반: 1프레임 크롭 오류·음절 잘림·다음 문장 새어 듦·자막 중복·제목 잘림·얼굴 가림)
  format      1080x1920 · fps · 길이(±1프레임) · yuv420p · 오디오 48kHz
  timestamps  첫 영상 PTS < 1프레임, 오디오 시작 [0, 0.05)
  loudness    통합 음량 목표 ±1 LU, 트루피크 ≤ -1.0
  audio_head  첫 1.3초 평균 음량 > -45dB(앞에 무음 끼는 사고)
  cut_edges   컷 지점 음량이 말소리 수준이면 '음절 잘림 의심'
  transcript  완성본을 다시 전사해 자막과 대조 — 첫·끝 단어 누락, 다음 문장 첫소리 유입
  faces       완성본 프레임에서 얼굴이 잡히는지·화면 밖으로 나가는지·글자에 가리는지
  layout      글자 상자가 화면 밖/세이프존 밖, 그래픽-자막 겹침
  hf_check    HyperFrames check(런타임 오류·넘침·겹침)
판정: FAIL(하나라도 error) / WARN(warn 만) / PASS
"""
import os, sys, json, argparse, subprocess, re, tempfile, shutil, difflib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json, save_json, load_brand, probe, run, hf
from render import loudness
import cut as CUT

CHK = []


def add(name, level, msg, **kw):
    CHK.append({"check": name, "level": level, "msg": msg, **kw})
    icon = {"ok": "✓", "warn": "△", "error": "✗"}[level]
    print(f"  {icon} {name}: {msg}")


def norm(s):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("short_dir"); ap.add_argument("--no-transcribe", action="store_true")
    ap.add_argument("--no-faces", action="store_true"); ap.add_argument("--no-hf-check", action="store_true")
    a = ap.parse_args()
    sdir = os.path.abspath(a.short_dir); pdir = os.path.dirname(os.path.dirname(sdir))
    plan = load_json(os.path.join(sdir, "short.json")); res = load_json(os.path.join(sdir, "resolved.json"))
    brand = load_brand(plan.get("brand") or res.get("brand"))
    sid = plan.get("id", "short"); name = plan.get("name") or sid
    rinfo = load_json(os.path.join(sdir, "out", f"{sid}_render.json"))     # 최종 render 기록만(draft 는 QA 대상 아님)
    final = rinfo["final"] if rinfo else os.path.join(sdir, "out", f"{name}.mp4")
    if not os.path.exists(final) or (rinfo or {}).get("draft"):
        raise SystemExit(f"최종 완성본 없음: {final} — ./shorts.sh render 먼저(draft 는 검수·납품 대상이 아님)")
    man = load_json(os.path.join(sdir, "build", "compose.json"))
    D = res["duration"]; fps_s = res["fps"]
    fps = eval(fps_s) if "/" in fps_s else float(fps_s)
    print(f"[qa] {os.path.basename(final)}")

    # format
    info = probe(final)
    r = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,pix_fmt,sample_rate,start_time", "-of", "json", final])
    st = json.loads(r.stdout)["streams"]
    v = next(s for s in st if s["codec_type"] == "video"); au = next((s for s in st if s["codec_type"] == "audio"), None)
    probs = []
    if (info["width"], info["height"]) != (1080, 1920):
        probs.append(f"해상도 {info['width']}x{info['height']}")
    if abs(info["fps"] - fps) > 0.01:
        probs.append(f"fps {info['fps']:.3f}≠{fps:.3f}")
    if abs(info["duration"] - D) > 1.5 / fps:
        probs.append(f"길이 {info['duration']:.3f}≠{D:.3f}")
    if v.get("pix_fmt") != "yuv420p":
        probs.append(f"pix_fmt {v.get('pix_fmt')}")
    if not au or au.get("sample_rate") != "48000":
        probs.append("오디오 48kHz 아님/없음")
    add("format", "error" if probs else "ok", "; ".join(probs) or f"1080x1920 · {info['fps']:.3f}fps · {info['duration']:.2f}초 · yuv420p · 48kHz")

    # timestamps
    r = run(["ffprobe", "-v", "error", "-select_streams", "v", "-read_intervals", "%+#1", "-show_entries", "frame=pts_time", "-of", "csv=p=0", final])
    vp = float(((r.stdout.strip().splitlines() or ["0"])[0].strip(", ") or 0))
    ast = float(au.get("start_time", 0) or 0) if au else 0
    lvl = "ok" if vp < 1 / fps and -0.001 <= ast < 0.05 else "error"
    add("timestamps", lvl, f"첫 영상 PTS {vp:.3f} · 오디오 시작 {ast:.3f}")

    # loudness
    I, TP = loudness(final)
    tgt = brand["audio"]["lufs"]
    lvl = "ok" if I is not None and abs(I - tgt) <= 1.0 and (TP is None or TP <= -1.0) else "warn"
    add("loudness", lvl, f"{I} LUFS (목표 {tgt}) · 트루피크 {TP} dBTP")

    # audio head
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-t", "1.3", "-i", final, "-af", "volumedetect", "-f", "null", "-"], check=False)
    m = re.search(r"mean_volume:\s*(-?[\d.]+)", r.stderr)
    mv = float(m.group(1)) if m else -99
    add("audio_head", "ok" if mv > -45 else "error", f"첫 1.3초 평균 {mv} dB")

    # cut edges (원본 음성 실측)
    rms = CUT.rms_track(os.path.join(pdir, "audio.wav"))
    ref = CUT.voice_ref(rms)
    thr = ref - 10
    bad, n_edges = [], 0
    ps = res["pieces"]
    for k, p in enumerate(ps):
        end = p.get("out_q", p["out"])
        # 소리가 실제로 끊기는 경계만: 맨 앞·맨 뒤, 그리고 원본 시각이 건너뛰는 이음새(샷 경계로만 나뉜 연속 구간은 제외)
        cut_in = k == 0 or abs(ps[k - 1].get("out_q", ps[k - 1]["out"]) - p["in"]) > 0.02
        cut_out = k == len(ps) - 1 or abs(ps[k + 1]["in"] - end) > 0.02
        if cut_in:
            n_edges += 1
            lin = CUT.level_at(rms, p["in"], p["in"] + 0.03)
            if lin > thr:
                bad.append(f"조각{k} 시작 {p['in']:.2f}s 음량 {lin:.0f}dB(기준 {thr:.0f}dB 초과)")
        if cut_out:
            n_edges += 1
            lout = CUT.level_at(rms, end - 0.03, end)
            if lout > thr:
                bad.append(f"조각{k} 끝 {end:.2f}s 음량 {lout:.0f}dB(기준 {thr:.0f}dB 초과)")
    add("cut_edges", "warn" if bad else "ok", "; ".join(bad) or f"소리가 끊기는 컷 {n_edges}곳 모두 {thr:.0f}dB 아래(말소리 중앙값 {ref:.0f}dB − 10)")

    # transcript
    if not a.no_transcribe:
        import mlx_whisper
        tmp = tempfile.mkdtemp(prefix="qa_")
        wav = os.path.join(tmp, "a.wav")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", final, "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
        rr = mlx_whisper.transcribe(wav, path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="ko",
                                    word_timestamps=True, condition_on_previous_text=False)
        shutil.rmtree(tmp, ignore_errors=True)
        heard = [w["word"].strip() for s in rr["segments"] for w in s.get("words", []) if w["word"].strip()]
        from textproc import tidy_numbers                  # '5 %를'·'8 .1' 같은 숫자 띄어쓰기는 차이로 세지 않는다
        heard = tidy_numbers(" ".join(heard)).split()
        cues = load_json(os.path.join(sdir, "captions.edit.json")) or load_json(os.path.join(sdir, "captions.auto.json"))
        expected = " ".join(" ".join(c["lines"]) for c in cues).split()
        hn, en = norm("".join(heard)), norm("".join(expected))
        ratio = difflib.SequenceMatcher(None, hn, en).ratio()
        msgs, lvl = [], "ok"
        # 첫소리: 앞 3글자 중 같은 자리 2글자 이상 — 표기 한 글자 차이(컨텐츠/콘텐츠)는 넘기고, 첫 음절이
        # 통째로 빠져 글자가 밀린 경우(너의→의)는 잡는다.
        # 끝소리: 끝 2글자가 같아야 한다(끝 음절이 잘리면 Whisper 가 '있다'를 '있죠'로 적기도 해서 느슨하게 보지 않는다).
        # 다만 Whisper 가 반말을 존댓말로 적는 버릇(거야→거예요, 있어→있어요, 거지→거죠)은 양쪽을 같은 꼴로 되돌려 비교한다.
        def ending(x):
            x = x[:-1] if x.endswith("요") and len(x) > 2 else x
            x = x[:-1] + "야" if x[-1:] in ("예", "에") else x
            return x[:-1] + "지" if x.endswith("죠") else x
        def same(a, b):
            n = min(3, len(a), len(b))
            return n == 0 or sum(1 for x, y in zip(a[:n], b[:n]) if x == y) >= max(1, n - 1)
        if not same(hn, en):
            msgs.append(f"첫소리 다름: 들림 '{' '.join(heard[:3])}' / 자막 '{' '.join(expected[:3])}'"); lvl = "warn"
        if ending(hn)[-2:] != ending(en)[-2:]:
            msgs.append(f"끝소리 다름: 들림 '{' '.join(heard[-3:])}' / 자막 '{' '.join(expected[-3:])}'"); lvl = "warn"
        if ratio < 0.85:
            lvl = "warn"
        # 어절 단위 차이 — 전사 오인식(예: 시험 문제를 ↔ 쉬운 문제를)은 사람 귀로 확인할 후보로 보여준다
        hw = [norm(x) for x in heard]; ew = [norm(x) for x in expected]
        diffs = []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ew, hw, autojunk=False).get_opcodes():
            if op != "equal":
                diffs.append(f"자막 '{' '.join(expected[i1:i2]) or '∅'}' ↔ 들림 '{' '.join(heard[j1:j2]) or '∅'}'")
        if diffs:
            msgs.append(f"어절 차이 {len(diffs)}곳(확인 후보): " + " / ".join(diffs[:5]))
        add("transcript", lvl, f"완성본 재전사 일치율 {ratio:.2f}" + ("; " + "; ".join(msgs) if msgs else ""),
            heard_head=" ".join(heard[:6]), heard_tail=" ".join(heard[-6:]), diffs=diffs)

    # faces (완성본에서 직접)
    if not a.no_faces:
        from faces import detect_dir
        tmp = tempfile.mkdtemp(prefix="qaf_")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", final, "-vf", "fps=2,scale=540:-2", "-q:v", "4",
                        os.path.join(tmp, "f_%06d.jpg")], check=True)
        n = len([f for f in os.listdir(tmp) if f.endswith(".jpg")])
        dets = detect_dir(tmp, n)
        shutil.rmtree(tmp, ignore_errors=True)
        band = man["band"]; W, H = man["canvas"]
        missing, edge, covered = [], [], []
        texts = [e for e in man["elements"] if e["kind"] in ("title", "caption", "graphic", "watermark", "signature")]
        splits = [e for e in man["elements"] if e["kind"] == "split"]

        def placed(e, t):
            """분할 구간이면 제목·자막 층이 실제로 옮겨 간 자리(split title_shift·cap_shift), 로고는 숨김 — 매니페스트는 옮기기 전 자리"""
            b = e["box"]
            for sp_ in splits:
                if sp_["t"][0] <= t <= sp_["t"][1]:
                    if e["kind"] in ("watermark", "signature"):
                        return None
                    dy = sp_.get("title_shift", 0) if e["kind"] == "title" else sp_.get("cap_shift", 0) if e["kind"] == "caption" else 0
                    return [b[0], b[1] + dy, b[2], b[3] + dy]
            return b
        in_move = lambda t: any(sp_["t"][0] <= t <= sp_["t"][0] + 0.5 or sp_["t"][1] - 0.5 <= t <= sp_["t"][1] + 0.05 for sp_ in splits)
        for i, faces in enumerate(dets):
            t = (i + 0.5) / 2
            if not faces:
                missing.append(round(t, 1)); continue
            f = faces[0]
            fb = [(f["cx"] - f["w"] / 2) * W, (f["cy"] - f["h"] / 2) * H, (f["cx"] + f["w"] / 2) * W, (f["cy"] + f["h"] / 2) * H]
            if fb[0] < band["x"] + 4 or fb[2] > band["x"] + band["w"] - 4 or fb[1] < band["y"] + 2 or fb[3] > band["y"] + band["h"] - 2:
                edge.append(round(t, 1))
            area = (fb[2] - fb[0]) * (fb[3] - fb[1])
            for e in texts:
                if e["t"][0] <= t <= e["t"][1] and not in_move(t):
                    b = placed(e, t)
                    if b is None:
                        continue
                    ov = max(0, min(b[2], fb[2]) - max(b[0], fb[0])) * max(0, min(b[3], fb[3]) - max(b[1], fb[1]))
                    if ov > 0.12 * area:
                        covered.append(f"{t:.1f}s {e['kind']}")
                        break
        lvl = "ok"
        msg = [f"프레임 {n}장 중 얼굴 {n - len(missing)}장"]
        if len(missing) > max(1, n * 0.1):
            lvl = "warn"; msg.append(f"얼굴 안 잡힘 {missing[:8]}")
        if edge:
            lvl = "warn"; msg.append(f"얼굴이 화면 가장자리에 걸림 {edge[:8]}")
        if covered:
            lvl = "warn"; msg.append(f"글자가 얼굴 가림 {covered[:6]}")
        add("faces", lvl, " · ".join(msg))

    # layout (compose 매니페스트)
    W, H = man["canvas"]
    out_box = [e for e in man["elements"] if e["box"][0] < 0 or e["box"][2] > W or e["box"][1] < 0 or e["box"][3] > H]
    wide = [e for e in man["elements"] if e["kind"] == "caption" and (e["box"][2] - e["box"][0]) > 1060]
    clash = []
    gs = [e for e in man["elements"] if e["kind"] == "graphic"]
    for g in gs:
        if g.get("replaces_caption"):                   # 키워드 상자는 그동안 자막을 숨기고 자막 자리에 뜬다(설계)
            continue
        for c in (e for e in man["elements"] if e["kind"] == "caption"):
            if g["t"][0] < c["t"][1] and c["t"][0] < g["t"][1]:
                b1, b2 = g["box"], c["box"]
                if min(b1[2], b2[2]) > max(b1[0], b2[0]) and min(b1[3], b2[3]) > max(b1[1], b2[1]):
                    clash.append(f"{g['t'][0]:.1f}s '{g.get('text', '')}'"); break
    msgs = []
    if out_box:
        msgs.append("화면 밖 " + ", ".join(f"{e['kind']}:{e.get('text', '')}" for e in out_box[:4]))
    if wide:
        msgs.append("자막 폭 초과 " + ", ".join(e["text"] for e in wide[:4]))
    if clash:
        msgs.append("그래픽-자막 겹침 " + ", ".join(clash[:4]))
    for w in man.get("warnings", []):
        msgs.append(w)
    add("layout", "error" if out_box else ("warn" if msgs else "ok"), "; ".join(msgs) or f"글자 {len(man['elements'])}개 모두 화면 안")

    # HyperFrames check
    if not a.no_hf_check:
        r = hf(["check", os.path.join(sdir, "build"), "--json", "--samples", "7", "--no-contrast"], cwd=os.path.join(sdir, "build"), check=False)
        try:
            js = json.loads(r.stdout[r.stdout.find("{"):])
            finds = js.get("findings") or js.get("issues") or []
            errs = [f for f in finds if str(f.get("severity", "")).lower() == "error"]
            lvl = "error" if errs else ("warn" if finds else "ok")
            add("hf_check", lvl, f"오류 {len(errs)} · 전체 {len(finds)}" + (" — " + "; ".join(f"{f.get('code')}:{f.get('selector', '')}" for f in finds[:5]) if finds else ""))
        except Exception:
            tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-3:]
            add("hf_check", "warn" if r.returncode == 0 else "error", "출력 해석 실패: " + " | ".join(tail))

    verdict = "FAIL" if any(c["level"] == "error" for c in CHK) else ("WARN" if any(c["level"] == "warn" for c in CHK) else "PASS")
    save_json(os.path.join(sdir, "out", f"{sid}_qa.json"), {"final": final, "verdict": verdict, "checks": CHK})
    print(f"[qa] 판정 {verdict} → out/{sid}_qa.json · 눈 검수: out/{sid}_sheet.jpg")


if __name__ == "__main__":
    main()
