#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
subs.py — 원본에 **구워진(번인) 자막**이 있는지, 있다면 가장 높이 올라오는 줄의 위치를 잰다 → faces.json "subs".

완성본 롱폼(자막이 영상에 박힌 파일)으로 쇼츠를 만들면 크롭 아래쪽에 옛 자막이 걸려 쇼츠 자막과 겹친다.
비블 파이프라인은 이 높이를 사람이 재서 --sub-top 으로 넣었다(자동화). 초당 1프레임, 화면 아래 35% 에서
'흰 글자 + 어두운 외곽선' 줄을 찾고(흰 배경 UI 는 줄의 흰 비율이 커서 제외), 2줄 자막까지 포함한 최고점을 쓴다.

  python3 subs.py <원본> <faces.json>        → faces.json 에 {"subs": {"top": 0.86, "p_frames": .., "tops": [[t, top]..]}} 추가
"""
import sys, os, json, subprocess
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json, save_json

W, H = 640, 360


def scan(src, fps=1.0):
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", src, "-vf", f"fps={fps},scale={W}:{H},format=rgb24",
                          "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    tops, n = [], 0
    y0 = int(H * 0.65)
    while True:
        b = p.stdout.read(W * H * 3)
        if len(b) < W * H * 3:
            break
        a = np.frombuffer(b, np.uint8).reshape(H, W, 3)[y0:].astype(np.int16)
        white = (a[:, :, 0] > 232) & (a[:, :, 1] > 232) & (a[:, :, 2] > 232)
        dark = (a.max(axis=2) < 60)
        wc = white.sum(axis=1); dc = dark.sum(axis=1)
        rows = np.nonzero((wc >= 4) & (wc <= W * 0.25) & (dc >= 4))[0]   # 글자 줄: 흰 글자 조금 + 외곽선
        top = None
        if len(rows) >= 3:
            top = round((y0 + int(rows.min())) / H, 4)
        tops.append([round((n + 0.5) / fps, 2), top]); n += 1
    p.wait()
    vals = sorted(t for _, t in tops if t is not None)
    share = len(vals) / max(1, len(tops))
    top = None
    if share >= 0.3 and vals:                                  # 영상 대부분에 자막이 있을 때만 '번인 자막'으로 본다
        top = float(vals[max(0, int(len(vals) * 0.01) - 1)])   # 하위 1% (가끔 튀는 흰 물체 제외)
    return {"top": top, "share": round(share, 3), "fps": fps, "tops": tops}


def main():
    src, fpath = sys.argv[1], sys.argv[2]
    f = load_json(fpath, {})
    r = scan(src)
    f["subs"] = r
    save_json(fpath, f)
    print(f"[subs] 번인 자막 {'있음' if r['top'] else '없음'} · 최고점 {r['top']} · 자막 있는 프레임 {r['share'] * 100:.0f}%")


if __name__ == "__main__":
    main()
