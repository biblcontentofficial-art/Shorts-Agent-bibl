#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deliver.py — 승인된 완성본 넘기기(복사·SNS 압축본·기록). 업로드·발행은 하지 않는다.

  python3 deliver.py projects/<p>/shorts/<id>                 # projects/<p>/deliver/ 에 복사
  python3 deliver.py projects/<p>/shorts/<id> --to-folder     # 브랜드 납품 폴더(brands/<b>.json deliver.folder)로 복사
  python3 deliver.py ... --sns                                 # 10MB 이하 SNS 압축본(2패스)도 만든다

안전장치: QA 판정이 FAIL 이면 거부, 납품 폴더 복사는 제목 status 가 approved 일 때만(--force 로 무시).
같은 이름 파일이 이미 있으면 덮어쓰지 않고 _v2, _v3 를 붙인다(업로드 대기 중인 파일을 바꿔치기하는 사고 방지).
"""
import os, sys, json, argparse, shutil, subprocess, datetime, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json, save_json, load_brand, probe


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]', "", s).strip()


def unique(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path); k = 2
    while os.path.exists(f"{base}_v{k}{ext}"):
        k += 1
    return f"{base}_v{k}{ext}"


def sns_version(src, dst, target_bytes=9.2e6, limit_bytes=9.7e6):
    """SNS(인스타·틱톡 등) 10MB 제한용 2패스 H.264. 십진 MB 기준으로 9.2MB 를 노리고, 넘치면 비트레이트를 줄여 한 번 더."""
    dur = probe(src)["duration"]
    vf = "scale=720:1280" if dur > 50 else "scale=1080:1920"
    log = dst + ".2pass"
    kbps = int(target_bytes * 8 / dur / 1000) - 128
    for attempt in range(3):
        for p in (1, 2):
            cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-vf", vf, "-c:v", "libx264", "-b:v", f"{kbps}k",
                   "-maxrate", f"{int(kbps * 1.3)}k", "-bufsize", f"{kbps * 2}k", "-profile:v", "high", "-pix_fmt", "yuv420p",
                   "-pass", str(p), "-passlogfile", log]
            cmd += (["-an", "-f", "mp4", os.devnull] if p == 1 else ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst])
            subprocess.run(cmd, check=True)
        if os.path.getsize(dst) <= limit_bytes:
            break
        kbps = int(kbps * 0.9)
    for f in os.listdir(os.path.dirname(dst)):
        if f.startswith(os.path.basename(log)):
            os.remove(os.path.join(os.path.dirname(dst), f))
    return os.path.getsize(dst) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("short_dir"); ap.add_argument("--to-folder", action="store_true")
    ap.add_argument("--sns", action="store_true"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    sdir = os.path.abspath(a.short_dir); pdir = os.path.dirname(os.path.dirname(sdir))
    plan = load_json(os.path.join(sdir, "short.json")); res = load_json(os.path.join(sdir, "resolved.json"))
    brand = load_brand(plan.get("brand") or res.get("brand"))
    sid = plan.get("id", "short")
    qa = load_json(os.path.join(sdir, "out", f"{sid}_qa.json"))
    if not qa:
        raise SystemExit("QA 결과 없음 — ./shorts.sh qa 먼저")
    if qa["verdict"] == "FAIL" and not a.force:
        raise SystemExit("QA 판정 FAIL — 고친 뒤 다시(무시하려면 --force)")
    final = qa["final"]
    if "_draft" in os.path.basename(final) or not os.path.exists(final):
        raise SystemExit(f"납품 대상이 최종본이 아님: {final} — ./shorts.sh render 후 qa 다시")
    title = plan.get("title") or {}
    if a.to_folder and title.get("status") != "approved" and not a.force:
        raise SystemExit("제목이 아직 승인 전(title.status != approved) — 사용자 승인 후 납품 폴더로 보낸다")
    dcfg = brand.get("deliver") or {}
    name = plan.get("name") or sid
    if dcfg.get("name") == "{title}" and title.get("lines"):
        name = safe_name(" ".join(title["lines"]))
    dest_dir = dcfg.get("folder") if (a.to_folder and dcfg.get("folder")) else os.path.join(pdir, "deliver")
    if a.to_folder and not dcfg.get("folder"):
        print("  ! 브랜드 납품 폴더가 비어 있어 projects/<p>/deliver/ 에 둔다(brands/<b>.json deliver.folder 지정 필요)")
    if not os.path.isdir(dest_dir):
        if a.to_folder and dcfg.get("folder"):
            raise SystemExit(f"납품 폴더가 없음: {dest_dir}")
        os.makedirs(dest_dir, exist_ok=True)
    dst = unique(os.path.join(dest_dir, f"{name}.mp4"))
    shutil.copy2(final, dst)
    srt = os.path.join(sdir, "out", f"{sid}.srt")
    out = {"file": dst, "duration": round(probe(dst)["duration"], 2), "qa": qa["verdict"], "title": title.get("lines")}
    if os.path.exists(srt):                             # 자막 SRT 는 작업 폴더에만(클라이언트 납품 폴더에는 mp4 만)
        os.makedirs(os.path.join(pdir, "deliver"), exist_ok=True)
        shutil.copy2(srt, os.path.join(pdir, "deliver", f"{name}.srt"))
    if a.sns or (a.to_folder and dcfg.get("sns")):
        sdst = unique(os.path.join(pdir, "deliver", "sns", f"{name}_sns.mp4"))
        os.makedirs(os.path.dirname(sdst), exist_ok=True)
        out["sns"] = sdst; out["sns_mb"] = round(sns_version(final, sdst), 2)
    logp = os.path.join(pdir, "deliver", "deliver_log.md")
    os.makedirs(os.path.dirname(logp), exist_ok=True)
    new = not os.path.exists(logp)
    with open(logp, "a", encoding="utf-8") as f:
        if new:
            f.write("| 시각 | 쇼츠 | 제목 | 길이 | QA | 파일 |\n|---|---|---|---|---|---|\n")
        f.write(f"| {datetime.datetime.now():%Y-%m-%d %H:%M} | {sid} | {' / '.join(title.get('lines') or [])} | {out['duration']}s | {qa['verdict']} | {dst} |\n")
    save_json(os.path.join(sdir, "out", f"{sid}_deliver.json"), out)
    print(f"[deliver] {dst}" + (f" · SNS {out['sns_mb']}MB(십진)" if out.get("sns") else ""))
    print("[deliver] 업로드·발행은 하지 않았다(발행은 사용자가 그 턴에 명시 지시할 때 업로드 담당이 한다).")


if __name__ == "__main__":
    main()
