#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
faces.py — 원본 영상의 얼굴 위치 타임라인 + 샷(카메라 컷) 경계.

· 얼굴: macOS Vision(VNDetectFaceRectanglesRequest)을 PyObjC 로 직접 호출한다.
  (bibl-shorts-automation 의 facescan.swift 와 같은 엔진. 이 맥은 Xcode 라이선스 미동의로 swift 실행이 막혀 있어 파이썬 경로를 쓴다)
· 샷: ffmpeg scdet(장면 변화 점수) — 점수가 threshold 이상인 프레임 시각을 컷으로 본다.
· 출력 faces.json:
  {"sample_fps", "src": {width,height,fps,duration},
   "frames": [{"t", "faces": [{"cx","cy","w","h","conf"}]}],      # 정규화 0~1, 원점 좌상단, cx/cy = 얼굴 중심
   "shots":  [{"start","end","cx","cy","fh","n"}]}                 # 샷마다 가장 큰 얼굴의 중앙값(없으면 null)

사용: python3 faces.py <원본영상> <출력 faces.json> [--fps 4] [--scene 10]
"""
import sys, os, json, re, argparse, tempfile, shutil, subprocess, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import probe, save_json


def detect_dir(frames_dir, n):
    import Vision
    from Foundation import NSURL
    out = []
    for i in range(1, n + 1):
        p = os.path.join(frames_dir, f"f_{i:06d}.jpg")
        if not os.path.exists(p):
            out.append([]); continue
        req = Vision.VNDetectFaceRectanglesRequest.alloc().init()
        h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(p), {})
        ok, _ = h.performRequests_error_([req], None)
        faces = []
        for o in (req.results() or []) if ok else []:
            bb = o.boundingBox()
            x, y, w, hh = bb.origin.x, bb.origin.y, bb.size.width, bb.size.height
            faces.append({"cx": round(x + w / 2, 4), "cy": round(1 - (y + hh / 2), 4), "w": round(w, 4), "h": round(hh, 4),
                          "conf": round(float(o.confidence()), 3)})
        faces.sort(key=lambda f: -f["w"] * f["h"])
        out.append(faces)
    return out


def scene_cuts(src, threshold):
    """ffmpeg scdet → 컷 시각 목록(초)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", src, "-an", "-vf",
                        f"scale=320:-2,scdet=threshold={threshold}", "-f", "null", "-"],
                       capture_output=True, text=True)
    cuts = []
    for m in re.finditer(r"lavfi\.scd\.time:\s*([0-9.]+)", r.stderr):
        t = float(m.group(1))
        if not cuts or t - cuts[-1] > 0.3:
            cuts.append(round(t, 3))
    return cuts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--scene", type=float, default=4.0, help="scdet 임계값(0~100). 편집된 클린본의 점프컷은 9 안팎, 움직임은 1.5 미만(2026-09-24 실측) → 4")
    a = ap.parse_args()
    info = probe(a.src)
    tmp = tempfile.mkdtemp(prefix="faces_")
    try:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", a.src, "-vf", f"fps={a.fps},scale=640:-2",
                        "-q:v", "4", os.path.join(tmp, "f_%06d.jpg")], check=True)
        n = len([f for f in os.listdir(tmp) if f.endswith(".jpg")])
        dets = detect_dir(tmp, n)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    frames = [{"t": round((i + 0.5) / a.fps, 3), "faces": d} for i, d in enumerate(dets)]
    cuts = scene_cuts(a.src, a.scene)
    bounds = [0.0] + cuts + [info["duration"]]
    shots = []
    for s, e in zip(bounds[:-1], bounds[1:]):
        fs = [f["faces"][0] for f in frames if s + 0.15 <= f["t"] < e - 0.15 and f["faces"]]
        shot = {"start": round(s, 3), "end": round(e, 3), "n": len(fs), "cx": None, "cy": None, "fh": None}
        if fs:
            shot.update(cx=round(statistics.median(f["cx"] for f in fs), 4), cy=round(statistics.median(f["cy"] for f in fs), 4),
                        fh=round(statistics.median(f["h"] for f in fs), 4))
        shots.append(shot)
    save_json(a.out, {"sample_fps": a.fps, "src": info, "frames": frames, "shots": shots})
    found = sum(1 for f in frames if f["faces"])
    print(f"[faces] 프레임 {len(frames)}개 중 얼굴 {found}개 · 샷 {len(shots)}개 → {a.out}")


if __name__ == "__main__":
    main()
