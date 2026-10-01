#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""new.py — 쇼츠 한 편의 short.json 뼈대 만들기(손으로 JSON 을 처음부터 쓰지 않게).

  python3 new.py projects/<p> s1 --in 21.7 --out 64.7 [--title "1줄/2줄"] [--motion 0] [--skip "아까 말했듯이"] [--name 수학쌤4편_쇼츠1]
이미 있으면 덮어쓰지 않는다(--force 로만).
"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json, save_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project"); ap.add_argument("id")
    ap.add_argument("--in", dest="t_in", type=float, required=True); ap.add_argument("--out", dest="t_out", type=float, required=True)
    ap.add_argument("--title", default=""); ap.add_argument("--motion", type=int, default=None)
    ap.add_argument("--skip", action="append", default=[]); ap.add_argument("--name"); ap.add_argument("--brand")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    pdir = os.path.abspath(a.project)
    src = load_json(os.path.join(pdir, "source.json"))
    if not src:
        raise SystemExit("ingest 먼저")
    sdir = os.path.join(pdir, "shorts", a.id)
    path = os.path.join(sdir, "short.json")
    if os.path.exists(path) and not a.force:
        raise SystemExit(f"이미 있음: {path} (--force 로 덮어쓰기)")
    seg = {"id": "a", "in": a.t_in, "out": a.t_out}
    if a.skip:
        seg["skip"] = a.skip
    plan = {"id": a.id, "brand": a.brand or src.get("brand"), "name": a.name or a.id,
            "brief": {"message": "", "arc": {}, "audience": "", "mood": ""},
            "segments": [seg],
            "title": {"lines": [l.strip() for l in a.title.split("/") if l.strip()], "status": "draft"},
            "captions": {"style": "brand"},
            "motion": {"level": a.motion if a.motion is not None else 0},
            "beats": []}
    save_json(path, plan)
    print(f"[new] {path}")


if __name__ == "__main__":
    main()
