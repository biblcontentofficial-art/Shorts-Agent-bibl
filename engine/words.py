#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""words.py — 단어 시각표 보기(구간 경계·skip·at_word 를 정할 때).

  python3 words.py projects/<p> 65.0 100.0          # 원본 65~100초 단어(교정 적용)
  python3 words.py projects/<p> 65 100 --find "5등급제"   # 구절 위치
출력: 시작–끝 단어  (쉼 0.30초 이상이면 ‖ 표시 = 자르기 좋은 자리)
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json, load_brand
import textproc as TP


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project"); ap.add_argument("t0", type=float); ap.add_argument("t1", type=float)
    ap.add_argument("--find"); ap.add_argument("--brand")
    a = ap.parse_args()
    src = load_json(os.path.join(a.project, "source.json"))
    brand = load_brand(a.brand or src.get("brand", "bibl"))
    corr = brand.get("corrections") or {}
    ws = TP.correct_words(load_json(os.path.join(a.project, "words.json")), corr)
    sel = [(i, w) for i, w in enumerate(ws) if w["end"] >= a.t0 and w["start"] <= a.t1]
    line = []
    for k, (i, w) in enumerate(sel):
        gap = ws[i + 1]["start"] - w["end"] if i + 1 < len(ws) else 9
        line.append(f"{w['start']:.2f}–{w['end']:.2f} {w['text']}" + (f"  ‖{gap:.2f}" if gap >= 0.3 else ""))
    print("\n".join(line))
    if a.find:
        from build import find_phrase
        hit = find_phrase(ws, a.find, 1, a.t0, a.t1)
        print(f"\n'{a.find}':", f"{ws[hit[0]]['start']:.2f}–{ws[hit[1]]['end']:.2f}" if hit else "없음")


if __name__ == "__main__":
    main()
