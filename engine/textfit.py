#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""textfit.py — 글꼴 파일의 실제 글자 폭(fontTools)으로 텍스트 폭을 재고, 폭 한계에 맞춰 크기를 줄인다.
브라우저 레이아웃에 기대지 않아 렌더가 결정적이고, 파이썬 단계(제목 축소·자막 줄 나눔)에서 미리 판단할 수 있다."""
import os, functools
from fontTools.ttLib import TTFont

FONT_DIRS = [os.path.expanduser("~/Library/Fonts"), "/Library/Fonts", "/System/Library/Fonts",
             os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")]


def find_font(name):
    if os.path.isabs(name) and os.path.exists(name):
        return name
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"글꼴 파일을 찾지 못함: {name} (~/Library/Fonts 또는 assets/fonts 에 두세요)")


@functools.lru_cache(maxsize=16)
def _metrics(path):
    f = TTFont(path, lazy=True)
    cmap = f.getBestCmap(); hmtx = f["hmtx"].metrics; upm = f["head"].unitsPerEm
    space = hmtx.get(cmap.get(32, ""), (upm * 0.25, 0))[0]
    return cmap, hmtx, upm, space


def width(font_file, text, size, tracking_em=0.0):
    cmap, hmtx, upm, space = _metrics(find_font(font_file))
    total = 0
    for ch in text:
        g = cmap.get(ord(ch))
        total += hmtx[g][0] if g in hmtx else (space if ch == " " else upm * 0.9)
    return total * size / upm + max(0, len(text) - 1) * tracking_em * size


@functools.lru_cache(maxsize=16)
def vmetrics(font_file):
    """(ascent, descent) em 비율 — hhea 기준(크로미움 macOS·PIL·libass 가 이 값을 쓴다)."""
    f = TTFont(find_font(font_file), lazy=True)
    upm = f["head"].unitsPerEm; h = f["hhea"]
    return h.ascent / upm, -h.descent / upm


@functools.lru_cache(maxsize=16)
def _glyphset(path):
    f = TTFont(path)
    return f, f.getGlyphSet(), f.getBestCmap(), f["hmtx"].metrics, f["head"].unitsPerEm


def ink_bounds(font_file, text, size):
    """글자 잉크 범위(x0, top, x1, bottom) — 원점 = 줄 시작·기준선, top/bottom 은 기준선 기준 아래쪽 +.
    제목 밴드(수학쌤 빨간 마커)처럼 글리프 실제 모양에 맞춰 그리는 요소에 쓴다."""
    from fontTools.pens.boundsPen import BoundsPen
    f, gs, cmap, hmtx, upm = _glyphset(find_font(font_file))
    x, x0, x1, ymax, ymin = 0.0, None, None, None, None
    for ch in text:
        g = cmap.get(ord(ch))
        if g is None:
            x += upm * 0.9; continue
        if ch != " ":
            bp = BoundsPen(gs); gs[g].draw(bp)
            if bp.bounds:
                a, b, c, d = bp.bounds
                x0 = x + a if x0 is None else min(x0, x + a)
                x1 = x + c if x1 is None else max(x1, x + c)
                ymin = b if ymin is None else min(ymin, b)
                ymax = d if ymax is None else max(ymax, d)
        x += hmtx[g][0]
    if x0 is None:
        return (0, 0, 0, 0)
    s = size / upm
    return (x0 * s, -ymax * s, x1 * s, -ymin * s)


def missing_glyphs(font_file, text):
    cmap = _metrics(find_font(font_file))[0]
    return sorted({ch for ch in text if ch.strip() and ord(ch) not in cmap})


def fit_size(font_file, lines, size, max_w, min_size=None, stroke=0.0):
    """모든 줄이 max_w 안에 들어오는 가장 큰 크기(한 줄이라도 넘치면 전체를 같은 비율로 축소)."""
    widest = max(width(font_file, ln, size) + 2 * stroke for ln in lines) if lines else 0
    if widest <= max_w:
        return size
    s = size * max_w / widest
    return max(min_size or size * 0.55, round(s, 1))
