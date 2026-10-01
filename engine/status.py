#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""status.py — 프로젝트 진행 상황(오케스트레이터 Phase 0 컨텍스트 확인용).

  python3 status.py projects/<p>
쇼츠마다: 길이 · 제목(승인 여부) · 단계(기획/컷확인/빌드/렌더/QA/납품) · QA 판정 · 모션 레벨
"""
import os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_json, tc


def main():
    pdir = os.path.abspath(sys.argv[1])
    src = load_json(os.path.join(pdir, "source.json"))
    if not src:
        raise SystemExit(f"프로젝트 없음(ingest 전): {pdir}")
    brief = os.path.exists(os.path.join(pdir, "BRIEF.md"))
    print(f"# {os.path.basename(pdir)} · {os.path.basename(src['src'])} · {tc(src['duration'])} · 브랜드 {src.get('brand')} · BRIEF.md {'있음' if brief else '없음'}")
    for f in ("words.json", "faces.json", "transcript.md", "candidates.md"):
        print(f"  {'✓' if os.path.exists(os.path.join(pdir, f)) else '·'} {f}")
    rows = []
    for sd in sorted(glob.glob(os.path.join(pdir, "shorts", "*", "short.json"))):
        d = os.path.dirname(sd); plan = load_json(sd); sid = plan.get("id", os.path.basename(d))
        res = load_json(os.path.join(d, "resolved.json")) or {}
        qa = load_json(os.path.join(d, "out", f"{sid}_qa.json")) or {}
        dl = load_json(os.path.join(d, "out", f"{sid}_deliver.json"))
        stage = "기획"
        if os.path.exists(os.path.join(d, "build", "base.mp4")):
            stage = "컷"
        if os.path.exists(os.path.join(d, "build", "index.html")):
            stage = "빌드"
        if load_json(os.path.join(d, "out", f"{sid}_render.json")):
            stage = "렌더"
        if qa:
            stage = f"QA {qa.get('verdict')}"
        if dl:
            stage = "납품"
        t = plan.get("title") or {}
        rows.append(f"  {sid:6s} {res.get('duration', 0):6.1f}s  [{stage:8s}]  모션{(plan.get('motion') or {}).get('level', 0)}  "
                    f"제목({t.get('status', '없음')}): {' / '.join(t.get('lines') or [])}")
    print("\n".join(rows) if rows else "  (쇼츠 없음 — 발굴 단계)")


if __name__ == "__main__":
    main()
