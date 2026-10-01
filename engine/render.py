#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render.py — HyperFrames 렌더 → 납품 규격으로 마무리 → 검수 시트.

  python3 render.py projects/<p>/shorts/<id>            # 최종(브랜드 규격)
  python3 render.py projects/<p>/shorts/<id> --draft    # 빠른 확인용(HyperFrames draft 품질, 마무리 인코딩 생략)

HyperFrames 가이드 'Rendering and output': 고치는 동안은 draft, 컷이 확정되면 최종 한 번. 쇼츠에 4K·60fps 는 쓰지 않는다.
마무리: 영상은 브랜드 CRF(비블 CRF19 -bf 0 / 수학쌤 CRF18)로 다시 인코딩, 소리는
  효과음·BGM 이 없으면 base.mp4 음성을 그대로(음량 정규화된 원음), 있으면 HyperFrames 믹스를 목표 음량으로 맞춘다.
"""
import os, sys, json, argparse, subprocess, shutil, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json, save_json, load_brand, hf, run, probe


def loudness(path):
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"], check=False)
    I = TP = None
    for line in r.stderr.splitlines()[::-1]:
        line = line.strip()
        if line.startswith("I:") and I is None:
            I = float(line.split()[1])
        if line.startswith("Peak:") and TP is None:
            TP = float(line.split()[1])
    return I, TP


def contact_sheet(video, times, out, labels=None, cols=4, w=270):
    import tempfile
    from PIL import Image, ImageDraw, ImageFont
    from common import ASSETS
    try:
        font = ImageFont.truetype(os.path.join(ASSETS, "fonts", "Pretendard-Bold.otf"), 15)
    except Exception:
        font = None
    tmp = tempfile.mkdtemp(prefix="sheet_")
    tiles = []
    for k, t in enumerate(times):
        p = os.path.join(tmp, f"{k:03d}.png")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{max(0, t):.3f}", "-i", video, "-frames:v", "1",
                        "-vf", f"scale={w}:-2", p], check=False)
        if os.path.exists(p):
            im = Image.open(p).convert("RGB")
            d = ImageDraw.Draw(im)
            lab = (labels[k] if labels else "") + f" {t:.2f}s"
            d.rectangle([0, 0, im.width, 22], fill=(0, 0, 0))
            d.text((6, 3), lab, fill=(255, 255, 0), font=font)
            tiles.append(im)
    shutil.rmtree(tmp, ignore_errors=True)
    if not tiles:
        return None
    rows = (len(tiles) + cols - 1) // cols
    th = tiles[0].height
    sheet = Image.new("RGB", (cols * w + (cols + 1) * 6, rows * th + (rows + 1) * 6), (30, 30, 30))
    for k, im in enumerate(tiles):
        r, c = divmod(k, cols)
        sheet.paste(im, (6 + c * (w + 6), 6 + r * (th + 6)))
    sheet.save(out, quality=88)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("short_dir"); ap.add_argument("--draft", action="store_true")
    ap.add_argument("--workers", default=None)
    a = ap.parse_args()
    sdir = os.path.abspath(a.short_dir)
    plan = load_json(os.path.join(sdir, "short.json"))
    res = load_json(os.path.join(sdir, "resolved.json"))
    if not res or not os.path.exists(os.path.join(sdir, "build", "index.html")):
        raise SystemExit("build 를 먼저 실행하세요 (./shorts.sh build ...)")
    brand = load_brand(plan.get("brand") or res.get("brand"))
    bdir = os.path.join(sdir, "build"); odir = os.path.join(sdir, "out"); os.makedirs(odir, exist_ok=True)
    sid = plan.get("id", "short"); name = plan.get("name") or sid
    fps = res["fps"]; D = res["duration"]
    hf_out = os.path.join(odir, f"{sid}_{'draft' if a.draft else 'hf'}.mp4")
    args = ["render", bdir, "-o", hf_out, "--fps", fps]
    args += ["--quality", "draft"] if a.draft else ["--crf", str(brand["encode"].get("hf_crf", 12))]
    if a.workers:
        args += ["--workers", str(a.workers)]
    t0 = time.time()
    print(f"[render] HyperFrames {'draft' if a.draft else 'master'} {D:.1f}초 → {os.path.basename(hf_out)}", flush=True)
    r = hf(args, cwd=bdir, check=False)
    if r.returncode != 0 or not os.path.exists(hf_out):
        print((r.stdout or "")[-3000:], (r.stderr or "")[-3000:])
        raise SystemExit("렌더 실패")
    print(f"[render] {time.time() - t0:.0f}초 걸림")
    final = hf_out
    if not a.draft:
        final = os.path.join(odir, f"{name}.mp4")
        enc = brand["encode"]
        gop = max(1, round(eval(fps) if "/" in fps else float(fps)))
        vargs = ["-c:v", "libx264", "-crf", str(enc.get("crf", 18)), "-preset", "medium", "-pix_fmt", "yuv420p",
                 "-profile:v", "high", "-g", str(gop * 2)]
        if enc.get("bframes") == 0:
            vargs += ["-bf", "0"]
        mixed = bool(res.get("sfx")) or os.path.exists(os.path.join(bdir, "bgm.m4a")) and bool((plan.get("bgm") or {}).get("file"))
        base = os.path.join(bdir, "base.mp4")
        if mixed:                                    # 효과음·BGM 이 섞인 HyperFrames 믹스를 목표 음량으로
            I, TP = loudness(hf_out)
            tgt = brand["audio"]["lufs"]
            chain = []
            # 트루피크 여유: AAC 인코딩이 피크를 0.2~0.4dB 올린다(2026-09-28 j5 -1.1 → 최종 -0.9) → 목표 +0.2 부터 보정
            if I is not None and (abs(I - tgt) > 0.7 or (TP or -9) > brand["audio"]["tp"] + 0.2):
                chain.append(f"loudnorm=I={tgt}:TP={brand['audio']['tp']}:LRA=11")
            # 마지막에 항상 봉우리 제한(−2dBFS): 효과음이 말소리 위에 겹친 순간 0dB 를 넘던 것(2026-09-29 BGM 뺀 j5 +1.2dBTP)
            chain += ["alimiter=limit=0.79:attack=2:release=60:level=disabled", "aresample=48000"]
            af = ["-af", ",".join(chain)]
            print(f"[render] 믹스 음량 {I} LUFS · 트루피크 {TP} dBTP → {'음량 보정 + ' if len(chain) > 2 else ''}봉우리 제한", flush=True)
            cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", hf_out, "-map", "0:v", "-map", "0:a"] + vargs + af + \
                  ["-c:a", "aac", "-b:a", enc.get("audio_bitrate", "192k"), "-ar", "48000"]
        else:                                        # 원음(정규화된 base 음성)을 그대로
            cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", hf_out, "-i", base, "-map", "0:v", "-map", "1:a"] + vargs + \
                  ["-c:a", "copy"]
        cmd += ["-t", f"{D:.3f}", "-movflags", "+faststart", final]
        subprocess.run(cmd, check=True)
        print(f"[render] 최종 → {final}")
        if os.path.exists(final) and os.path.getsize(final) > 0:
            os.remove(hf_out)                       # 중간본(CRF12, 수십~백 MB)은 최종본이 생기면 지운다
            hf_out = None
    # 검수 시트: 시작 0.3초 · 컷 이음새 앞뒤 · 그래픽·줌 순간 · 25/50/75% · 끝 0.3초 전
    marks = [(0.3, "시작")]
    for p in res["pieces"][1:]:
        marks += [(p["t0"] - 0.1, "컷 전"), (p["t0"] + 0.1, "컷 후")]
    for b in res.get("beats", []):
        marks.append((min(D - 0.05, b["t0"] + (0.12 if b["type"] == "flash" else 0.6)), f"{b['type']}[{b.get('src_index', '')}]"))
    for z in res.get("zooms", []):
        marks.append((min(D - 0.05, z["t0"] + 0.4), f"zoom[{z.get('src_index', '')}]"))
    for f in (0.25, 0.5, 0.75):
        marks.append((D * f, f"{int(f * 100)}%"))
    marks.append((max(0, D - 0.3), "끝"))
    marks.sort(key=lambda m: m[0])
    tag = "_draft" if a.draft else ""
    sheet = contact_sheet(final, [m[0] for m in marks], os.path.join(odir, f"{sid}{tag}_sheet.jpg"), [m[1] for m in marks])
    info = probe(final)
    # draft 는 별도 기록 — 최종 기록(<id>_render.json)은 QA·납품이 읽으므로 draft 가 덮어쓰면 안 된다
    save_json(os.path.join(odir, f"{sid}_draft.json" if a.draft else f"{sid}_render.json"),
              {"final": final, "hf": hf_out, "draft": a.draft, "probe": info, "sheet": sheet, "seconds": round(time.time() - t0, 1)})
    print(f"[render] {info['width']}x{info['height']} {info['fps']:.3f}fps {info['duration']:.2f}초 · 시트 {sheet}")


if __name__ == "__main__":
    main()
