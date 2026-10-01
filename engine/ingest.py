#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest.py — 원본 영상 분석: 단어 전사 + 얼굴·샷 타임라인 → projects/<p>/

  source.json     원본 경로·해상도·fps·길이·브랜드
  audio.wav       16kHz 모노(전사·음성 경계 측정용)
  words.json      단어 [{text,start,end,p}] — **원문 그대로**(문장부호 유지, 교정 전). 교정은 build 에서 브랜드 corrections + 쇼츠 fix 로.
  segments.json   Whisper 문장(시각·신뢰도) + 환각 필터 사유(drop)
  faces.json      faces.py 결과(얼굴 위치·샷)
  transcript.md   발굴용 시각표: 문장 + 카메라 컷(▌) + 얼굴 없는 구간 표시 + 교정 미리보기

전사: mlx-whisper(로컬) large-v3-turbo 기본(--model large-v3 는 정확도 우선). 초기 프롬프트 = 브랜드 glossary.
환각 필터: 한글 없는 문장·정형 환각 문구·같은 어절 반복·압축비 과다·무음 추정 문장을 버리고 사유를 남긴다.

사용: python3 ingest.py <원본영상> --name <프로젝트> [--brand mathclient] [--model large-v3-turbo] [--skip-faces] [--redo]
"""
import sys, os, re, json, argparse, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, probe, save_json, load_json, load_brand, tc

HALLU = ["시청해주셔서 감사합니다", "시청해 주셔서 감사합니다", "구독과 좋아요", "좋아요와 구독", "구독 부탁", "알림 설정",
         "MBC 뉴스", "KBS 뉴스", "SBS 뉴스", "자막 제공", "자막 by", "한글자막", "다음 영상에서 만나요", "소개해 드립니다",
         "소개해드립니다", "감사합니다. 감사합니다", "Thank you for watching"]
HANGUL = re.compile(r"[가-힣]")
# mlx-community 실제 저장소 이름(2026-09-24 확인). large-v3 는 첫 사용 때 약 3GB 를 받는다.
MODELS = {"large-v3-turbo": "mlx-community/whisper-large-v3-turbo", "large-v3": "mlx-community/whisper-large-v3-mlx",
          "medium": "mlx-community/whisper-medium-mlx", "small": "mlx-community/whisper-small-mlx"}


def repeated(toks, k=4):
    run = 1
    for a, b in zip(toks, toks[1:]):
        run = run + 1 if a == b else 1
        if run >= k:
            return True
    return False


def seg_reject(seg, lang):
    t = seg["text"].strip()
    if not t:
        return "빈 문장"
    if lang == "ko" and not HANGUL.search(t):
        return "한글 없음"
    for h in HALLU:
        if h.replace(" ", "") == t.replace(" ", "").rstrip(".") or (len(t) < 40 and h.replace(" ", "") in t.replace(" ", "")):
            return f"환각 문구({h})"
    toks = [w["word"].strip() for w in seg.get("words", [])]
    if repeated(toks):
        return "같은 어절 반복"
    if seg.get("compression_ratio", 0) > 2.6:
        return "압축비 과다(반복)"
    if seg.get("no_speech_prob", 0) > 0.6 and seg.get("avg_logprob", 0) < -0.8:
        return "무음 추정"
    return None


def write_transcript(pdir, info, segs, faces, brand):
    """발굴용 시각표. 카메라 컷은 ▌, 얼굴이 절반 넘게 안 잡힌 문장은 [얼굴없음](화면공유·B롤 가능성)."""
    from textproc import correct_words
    cuts = [s["start"] for s in (faces or {}).get("shots", [])[1:]]
    frames = (faces or {}).get("frames", [])
    corr = brand.get("corrections") or {}
    with open(os.path.join(pdir, "transcript.md"), "w", encoding="utf-8") as f:
        f.write(f"# {os.path.basename(info['src'])} · {tc(info['duration'])} · {info['width']}x{info['height']} {info['fps']:.3f}fps\n\n")
        f.write("표기: ▌=카메라 컷(샷 경계) · [얼굴없음]=그 문장 동안 얼굴이 절반 넘게 안 잡힘(화면공유·자료 화면일 수 있음) · ~~버림~~=환각 필터\n\n")
        ci = 0
        for s in segs:
            while ci < len(cuts) and cuts[ci] <= s["start"]:
                f.write(f"▌ {tc(cuts[ci])} 카메라 컷\n"); ci += 1
            flag = ""
            if frames:
                fr = [x for x in frames if s["start"] <= x["t"] <= s["end"]]
                if fr and sum(1 for x in fr if x["faces"]) < len(fr) / 2:
                    flag = " [얼굴없음]"
            text = s["text"]
            if corr and not s["drop"]:
                fixed = " ".join(w["text"] for w in correct_words([{"text": t, "start": 0, "end": 0} for t in text.split()], corr))
                text = fixed
            mark = f"  ~~(버림: {s['drop']})~~" if s["drop"] else ""
            f.write(f"[{tc(s['start'])}–{tc(s['end'])}] {text}{flag}{mark}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("--name", required=True)
    ap.add_argument("--brand", default="bibl"); ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--lang", default="ko"); ap.add_argument("--skip-faces", action="store_true")
    ap.add_argument("--redo", action="store_true", help="이미 있는 전사·얼굴 결과도 다시 만든다")
    a = ap.parse_args()
    src = os.path.abspath(a.src)
    if not os.path.exists(src):
        raise SystemExit(f"원본 없음: {src}")
    brand = load_brand(a.brand)
    pdir = os.path.join(ROOT, "projects", a.name); os.makedirs(pdir, exist_ok=True)
    info = probe(src)
    save_json(os.path.join(pdir, "source.json"), {"src": src, "brand": a.brand, **info})
    wav = os.path.join(pdir, "audio.wav")
    if not os.path.exists(wav) or a.redo:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", wav], check=True)

    wpath, spath = os.path.join(pdir, "words.json"), os.path.join(pdir, "segments.json")
    if os.path.exists(wpath) and os.path.exists(spath) and not a.redo:
        print("[ingest] 전사 재사용(words.json 있음, --redo 로 다시)")
        segs = load_json(spath)
    else:
        import mlx_whisper
        gl = brand.get("glossary") or []
        prompt = (", ".join(gl[:60]) + ".") if gl else None
        repo = MODELS.get(a.model, a.model if "/" in a.model else f"mlx-community/whisper-{a.model}")
        print(f"[ingest] 전사 중: {repo} (용어 {len(gl)}개)", flush=True)
        r = mlx_whisper.transcribe(wav, path_or_hf_repo=repo, language=a.lang,
                                   word_timestamps=True, condition_on_previous_text=False, initial_prompt=prompt)
        words, segs = [], []
        for s in r["segments"]:
            why = seg_reject(s, a.lang)
            segs.append({"start": round(s["start"], 3), "end": round(s["end"], 3), "text": s["text"].strip(),
                         "logprob": round(s.get("avg_logprob", 0), 3), "no_speech": round(s.get("no_speech_prob", 0), 3),
                         "drop": why})
            if why:
                continue
            for w in s.get("words", []):
                txt = w["word"].strip()
                if txt:
                    words.append({"text": txt, "start": round(w["start"], 3), "end": round(w["end"], 3),
                                  "p": round(w.get("probability", 1.0), 3)})
        save_json(wpath, words); save_json(spath, segs)
        kept = [s for s in segs if not s["drop"]]
        print(f"[ingest] 문장 {len(kept)}/{len(segs)} · 단어 {len(words)}")
    fpath = os.path.join(pdir, "faces.json")
    if not a.skip_faces and (not os.path.exists(fpath) or a.redo):
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "faces.py"), src, fpath], check=True)
    fj = load_json(fpath)
    if fj is not None and "subs" not in fj:               # 구워진 자막 높이(크롭 아래 한계용)
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "subs.py"), src, fpath], check=True)
    write_transcript(pdir, {"src": src, **info}, segs, load_json(fpath), brand)
    print(f"[ingest] → {pdir}/transcript.md")


if __name__ == "__main__":
    main()
