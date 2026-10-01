#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compose.py — 쇼츠 계획 + 브랜드 → HyperFrames 컴포지션(build/index.html).

화면 구성(아래 → 위)
  #cam(비디오 밴드, 줌 대상 #cam-inner) < 자막(트랙 3) < 그래픽(트랙 4) < 제목(트랙 6) < 워터마크·시그니처(트랙 7)
  오디오: base 음성(트랙 10) · 효과음(트랙 11) · BGM(트랙 12)

글자는 전부 SVG <text> 로 그린다: 기준선 위치를 폰트 실측(hhea)으로 정확히 맞추고, 외곽선(stroke-linejoin round +
paint-order stroke)·그림자(feDropShadow)·수학쌤 빨간 마커 밴드를 기존 확정 템플릿(PIL/libass)과 같은 좌표로 재현한다.
줄바꿈은 파이썬(textproc)이 정한 줄만 쓴다(브라우저 자동 줄바꿈 금지).

HyperFrames 규칙(hyperframes-core): 루트 width/height 100% · 타임라인 하나(paused) · clip 요소 자체는 애니메이션 금지
(안쪽 .inner 를 움직임) · <video muted> + 별도 <audio id> · @font-face 로 로컬 폰트 · fromTo 는 immediateRender:false.
"""
import os, sys, json, html, hashlib, shutil, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, ASSETS, TEMPLATES, load_json, save_json, run
from textfit import width as tw, vmetrics, ink_bounds, find_font, missing_glyphs
from textproc import split2, kchars

HERE = os.path.dirname(os.path.abspath(__file__))
VOCAB = load_json(os.path.join(HERE, "vocab.json"))
SAFE_EXTRA = "0123456789%+-.,:;!?()[]“”‘’\"'·/→←↑↓×=~ "


def esc(s):
    return html.escape(str(s), quote=True)


def f2(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def feel(name, default="smooth"):
    f = VOCAB["feel"].get(name or default) or VOCAB["feel"][default]
    return f["ease"], f["dur"]


class Comp:
    def __init__(self, brand, duration, fps):
        self.b = brand; self.D = duration; self.fps = fps
        self.W, self.H = brand["canvas"]["w"], brand["canvas"]["h"]
        self.defs, self.body, self.js, self.audio = [], [], [], []
        self.under = []          # 영상 밴드 바로 위·자막 아래 층(B-roll 카드 영상)
        self.layer = None        # 지금 만드는 클립이 들어갈 층 이름(분할 레이아웃에서 제목·자막·로고를 통째로 움직이려고)
        self.layers = {}         # 층 이름 → 클립 HTML 목록
        self.fonts = {}          # font file → {"family","weight","chars"}
        self.elements = []       # QA 매니페스트
        self.warnings = []
        self.filters = {}
        self.uid = 0
        self.kw_windows = []     # 자막 대신 나오는 키워드 상자 구간(kw_replaces_caption)
        self.split_edges = []
        self.panel = []          # 분할 위 패널 안 카드 영상(overflow hidden — 패널 밀기가 인물 쪽으로 넘치지 않게)
        self.emph_events = []

    def nid(self, p="e"):
        self.uid += 1
        return f"{p}{self.uid}"

    def use_font(self, st, text):
        ent = self.fonts.setdefault(st["font"], {"family": st["family"], "weight": st.get("weight", 400), "chars": set()})
        ent["chars"].update(text)
        miss = missing_glyphs(st["font"], text)
        if miss:
            self.warnings.append(f"글꼴 {st['font']} 에 없는 글자 {''.join(miss)} — 다른 글꼴로 대체되어 보일 수 있음")

    def shadow(self, sh):
        """feDropShadow 필터(문서 전역 id). sh = {x,y,blur,color}"""
        if not sh:
            return ""
        key = json.dumps(sh, sort_keys=True)
        if key not in self.filters:
            fid = f"sh{len(self.filters) + 1}"
            col, op = sh["color"], 1.0
            m = re.match(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", col)
            if m:
                col = "#%02x%02x%02x" % tuple(int(m.group(i)) for i in (1, 2, 3)); op = float(m.group(4))
            self.defs.append(f'<filter id="{fid}" filterUnits="userSpaceOnUse" x="-200" y="-200" width="{self.W + 400}" height="{self.H + 400}">'
                             f'<feDropShadow dx="{sh["x"]}" dy="{sh["y"]}" stdDeviation="{sh.get("blur", 0)}" flood-color="{col}" flood-opacity="{op}"/></filter>')
            self.filters[key] = fid
        return f' filter="url(#{self.filters[key]})"'

    def blur(self, sigma):
        key = f"blur{sigma}"
        if key not in self.filters:
            fid = f"bl{len(self.filters) + 1}"
            self.defs.append(f'<filter id="{fid}" filterUnits="userSpaceOnUse" x="-200" y="-200" width="{self.W + 400}" height="{self.H + 400}">'
                             f'<feGaussianBlur stdDeviation="{sigma}"/></filter>')
            self.filters[key] = fid
        return f' filter="url(#{self.filters[key]})"'

    # ── 글자 한 줄 ──
    def text(self, txt, cx, baseline, st, fill=None, tspans=None, idattr=""):
        size = st["size"]
        self.use_font(st, txt)
        # 자간: 크로미움 SVG 는 공백에 letter-spacing 을 적용하지 않아(실측 공백당 +4px) word-spacing 으로 같게 맞춘다(PIL 글자별 자간 재현)
        ls = (f"letter-spacing:{f2(st['tracking'] * size)}px;word-spacing:{f2(st['tracking'] * size)}px;"
              if st.get("tracking") else "")
        stroke = ""
        if st.get("stroke"):
            stroke = (f' stroke="{st["stroke"]["color"]}" stroke-width="{f2(2 * st["stroke"]["w"])}"'
                      f' stroke-linejoin="round" paint-order="stroke"')
        body = tspans if tspans is not None else esc(txt)
        t = (f'<text{idattr} x="{f2(cx)}" y="{f2(baseline)}" text-anchor="middle" '
             f'style="font-family:\'{st["family"]}\';font-weight:{st.get("weight", 400)};font-size:{f2(size)}px;{ls}white-space:pre" '
             f'fill="{fill or st.get("color", "#FFFFFF")}"{stroke}>{body}</text>')
        xs = st.get("xscale", 1.0)
        if xs != 1.0:
            t = f'<g transform="translate({f2(cx)} 0) scale({xs} 1) translate({f2(-cx)} 0)">{t}</g>'
        return t

    def line_w(self, txt, st):
        return tw(st["font"], txt, st["size"], st.get("tracking", 0.0)) * st.get("xscale", 1.0)

    def baselines(self, st, n, anchor, y, pitch):
        """앵커 규칙 → 줄별 기준선. ascender: y = 첫 줄 어센더 선. middle: y = 블록(또는 한 줄)의 세로 가운데."""
        A, Dd = vmetrics(st["font"]); s = st["size"]
        if anchor == "ascender":
            return [y + A * s + i * pitch for i in range(n)]
        if anchor == "middle":
            first_center = y - (n - 1) * pitch / 2
            return [first_center + i * pitch + (A - Dd) / 2 * s for i in range(n)]
        if anchor == "first_middle":                 # 비블 v2 제목: y = 첫 줄 가운데, 다음 줄은 +pitch (한 줄이면 두 줄 자리의 가운데)
            centers = [y + pitch / 2] if n == 1 else [y + i * pitch for i in range(n)]
            return [cy + (A - Dd) / 2 * s for cy in centers]
        if anchor == "baseline":
            return [y + i * pitch for i in range(n)]
        raise ValueError(anchor)

    def box(self, txt, cx, baseline, st):
        A, Dd = vmetrics(st["font"]); s = st["size"]; w = self.line_w(txt, st)
        sw = (st.get("stroke") or {}).get("w", 0)
        return [cx - w / 2 - sw, baseline - A * s - sw, cx + w / 2 + sw, baseline + Dd * s + sw]

    def clip(self, cid, start, dur, track, inner, cls="", origin=None, extra=""):
        o = f' style="transform-origin:{f2(origin[0])}px {f2(origin[1])}px"' if origin else ""
        (self.layers.setdefault(self.layer, []) if self.layer else self.body).append(f'<div id="{cid}" class="clip {cls}" data-start="{start:.3f}" data-duration="{max(0.04, dur):.3f}" '
                         f'data-track-index="{track}"{extra}><div class="inner" id="{cid}-i"{o}>'
                         f'<svg class="t" viewBox="0 0 {self.W} {self.H}" width="{self.W}" height="{self.H}">{inner}</svg></div></div>')

    def add_el(self, kind, box, t0, t1, **kw):
        self.elements.append({"kind": kind, "box": [round(v, 1) for v in box], "t": [round(t0, 3), round(t1, 3)], **kw})


# ───────────────────────── 제목 ─────────────────────────
def title_size(c, lines, tcfg):
    longest = max(kchars(l) for l in lines)
    size = next(sz for mx, sz in tcfg["size_rule"] if longest <= mx)
    st = {**tcfg, "size": size}
    step = tcfg.get("shrink_step", 0)
    trk = 0.0 if tcfg.get("fit_ignores_tracking") else tcfg.get("tracking", 0.0)   # v2 원본은 자간 없이 폭을 쟀다
    widest = lambda s: max(c.line_w(l, {**st, "size": s, "tracking": trk}) for l in lines)
    if step:
        while size > tcfg["min_size"] and widest(size) > tcfg["max_w"]:
            size = round(size - step, 1)
        size = max(size, tcfg["min_size"])
    else:
        w = widest(size)
        if w > tcfg["max_w"]:
            size = max(tcfg["min_size"], int(size * tcfg["max_w"] / w))
    return size


def build_title(c, lines, tcfg):
    if not lines:
        return
    if len(lines) == 1 and tcfg.get("split") == "balance":
        lines = split2(lines[0])
    size = title_size(c, lines, tcfg)
    st = {**tcfg, "size": size}
    if tcfg.get("pitch_int"):
        pitch = int(tcfg["pitch"] * size)
    else:
        pitch = tcfg["pitch"] * size if tcfg["anchor"] != "ascender" else round(tcfg["pitch"] * size)
    bl = c.baselines(st, len(lines), tcfg["anchor"], tcfg["y"], pitch)
    cx = c.W / 2
    colors = tcfg.get("colors") or ["#FFFFFF"]
    parts = []
    band = tcfg.get("band")
    if band:                                         # 수학쌤: 마커 밴드 + 퍼짐 그림자 + 1줄 보조 그림자(render_mathclient3 재현)
        li = band.get("line", 1) - 1
        x_left = cx - c.line_w(lines[li], st) / 2
        ix0, itop, ix1, ibot = ink_bounds(st["font"], lines[li], size)
        gtop, gbot = bl[li] + itop, bl[li] + ibot
        bh = int((gbot - gtop) * band["h_ratio"]); by2 = int(gbot + band["below"]); by1 = by2 - bh
        bx0, bx1 = int(x_left + ix0 - band["pad"]), int(x_left + ix1 + band["pad"])
        poly = [(bx0 + 16, by1 + 4), (bx1 - 6, by1), (bx1 + 12, by2 - 5), (bx0 - 5, by2)]
        pts = " ".join(f"{x},{y}" for x, y in poly)
        bcx, bcy = (bx0 + bx1) / 2, (by1 + by2) / 2
        sh = tcfg.get("shadow") or {}
        m = re.match(r"rgba\(\d+,\s*\d+,\s*\d+,\s*([\d.]+)\)", sh.get("color", "rgba(0,0,0,0.7)"))
        op = float(m.group(1)) if m else 0.7
        shadow_txt = "".join(c.text(l, cx, b, {**st, "stroke": None}, fill="#000000") for l, b in zip(lines, bl))
        parts.append(f'<g opacity="{op}"{c.blur(sh.get("blur", 10))} transform="translate({sh.get("x", 5)} {sh.get("y", 5)})">'
                     f'<polygon points="{pts}" fill="#000000"/>{shadow_txt}</g>')
        parts.append(f'<g{c.blur(band.get("blur", 1.6))} transform="rotate({-band.get("rotate", -1.2)} {f2(bcx)} {f2(bcy)})">'
                     f'<polygon points="{pts}" fill="{band["color"]}"/></g>')
        s2 = tcfg.get("shadow2")
        if s2:
            m2 = re.match(r"rgba\(\d+,\s*\d+,\s*\d+,\s*([\d.]+)\)", s2["color"])
            op2 = float(m2.group(1)) if m2 else 0.55
            l2 = s2.get("line", 1) - 1
            parts.append(f'<g opacity="{op2}"{c.blur(s2.get("blur", 5))} transform="translate({s2["x"]} {s2["y"]})">'
                         f'{c.text(lines[l2], cx, bl[l2], {**st, "stroke": None}, fill="#000000")}</g>')
        parts.append("".join(c.text(l, cx, b, st, fill=colors[min(i, len(colors) - 1)]) for i, (l, b) in enumerate(zip(lines, bl))))
    elif tcfg.get("box"):                           # 비블 v3(2026-09-28 레퍼런스 youtube.com/shorts/Yfb2vDAgyZQ): 화면 가운데 떠 있는 둥근 상자 + 진한 글자
        bx = tcfg["box"]; A, Dd = vmetrics(st["font"])
        centers = [b - (A - Dd) / 2 * size for b in bl]
        maxw = max(c.line_w(l, st) for l in lines)
        x0 = cx - maxw / 2 - bx.get("pad_x", 44); x1 = cx + maxw / 2 + bx.get("pad_x", 44)
        y0 = centers[0] - size * bx.get("half", 0.52) - bx.get("pad_y", 30); y1 = centers[-1] + size * bx.get("half", 0.52) + bx.get("pad_y", 30)
        rect = (f'<rect x="{f2(x0)}" y="{f2(y0)}" width="{f2(x1 - x0)}" height="{f2(y1 - y0)}" rx="{bx.get("radius", 20)}" '
                f'fill="{bx.get("fill", "#CAB49D")}"{(" opacity=" + chr(34) + str(bx["opacity"]) + chr(34)) if bx.get("opacity") is not None else ""}/>')
        if bx.get("shadow"):
            rect = f'<g{c.shadow(bx["shadow"])}>{rect}</g>'
        parts.append(rect)
        if bx.get("stroke"):                        # 안쪽 가장자리 선(2026-09-28 디자인 R3: #2C2929 상자가 검정 옷 위에서 묻히지 않게)
            sw = float(bx["stroke"].get("w", 1.5)); rr = max(0.0, float(bx.get("radius", 20)) - sw / 2)
            parts.append(f'<rect x="{f2(x0 + sw / 2)}" y="{f2(y0 + sw / 2)}" width="{f2(x1 - x0 - sw)}" height="{f2(y1 - y0 - sw)}" '
                         f'rx="{f2(rr)}" fill="none" stroke="{bx["stroke"].get("color", "rgba(255,255,255,0.12)")}" stroke-width="{sw}"/>')
        parts.append("".join(c.text(l, cx, b, {**st, "stroke": None}, fill=colors[min(i, len(colors) - 1)]) for i, (l, b) in enumerate(zip(lines, bl))))
        c.add_el("title-box", [x0, y0, x1, y1], 0, c.D, chrome=True)
    else:
        txt = "".join(c.text(l, cx, b, st, fill=colors[min(i, len(colors) - 1)]) for i, (l, b) in enumerate(zip(lines, bl)))
        parts.append(f'<g{c.shadow(tcfg.get("shadow"))}>{txt}</g>')
    c.clip("title", 0.0, c.D, 6, "".join(parts), cls="title")
    for l, b in zip(lines, bl):
        c.add_el("title", c.box(l, cx, b, st), 0, c.D, text=l, size=size)
    return {"lines": lines, "size": size}


# ───────────────────────── 워터마크·시그니처 ─────────────────────────
def build_mark(c, cfg, cid, bdir=None):
    if not cfg:
        return
    if cfg.get("image"):                             # 이미지 로고(비블 v3: 붓글씨 'bibl' 흰색 PNG, assets/brand/)
        src = cfg["image"] if os.path.isabs(cfg["image"]) else os.path.join(ASSETS, "brand", cfg["image"])
        name = os.path.basename(src)
        if bdir:
            os.makedirs(os.path.join(bdir, "brand"), exist_ok=True)
            dst = os.path.join(bdir, "brand", name)
            if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
                shutil.copy2(src, dst)
        from PIL import Image
        iw, ih = Image.open(src).size
        h = float(cfg.get("h", ih)); w = float(cfg.get("w", iw * h / ih))
        x = c.W / 2 - w / 2 + cfg.get("x_offset", 0); y = cfg["y"] - h / 2
        op = cfg.get("opacity")
        img = (f'<image href="brand/{esc(name)}" x="{f2(x)}" y="{f2(y)}" width="{f2(w)}" height="{f2(h)}" preserveAspectRatio="xMidYMid meet"'
               + (f' opacity="{op}"' if op is not None else "") + "/>")
        c.clip(cid, 0.0, c.D, 7, f'<g{c.shadow(cfg.get("shadow"))}>{img}</g>', cls="mark")
        c.add_el(cid, [x, y, x + w, y + h], 0, c.D, text=cfg.get("alt", name), chrome=True)
        return
    st = dict(cfg)
    b = c.baselines(st, 1, cfg.get("anchor", "middle"), cfg["y"], 0)[0]
    cx = c.W / 2 + cfg.get("x_offset", 0)            # 비블 워터마크: 원본 PIL 시어 캔버스 탓에 21px 왼쪽(실측 재현)
    t = c.text(cfg["text"], cx, b, st, fill=cfg.get("color"))
    if cfg.get("skew"):
        A, Dd = vmetrics(st["font"]); mid = b - (A - Dd) / 2 * st["size"]
        t = f'<g transform="translate({f2(cx)} {f2(mid)}) skewX({cfg["skew"]}) translate({f2(-cx)} {f2(-mid)})">{t}</g>'
    c.clip(cid, 0.0, c.D, 7, f'<g{c.shadow(cfg.get("shadow"))}>{t}</g>', cls="mark")
    c.add_el(cid, c.box(cfg["text"], cx, b, st), 0, c.D, text=cfg["text"], chrome=True)


# ───────────────────────── 자막 ─────────────────────────
def build_captions(c, cues, words, ccfg, plan_cap, marker_color=None):
    style = (plan_cap or {}).get("style") or ccfg.get("style", "brand")
    emph_raw = [e for e in (plan_cap or {}).get("emphasis", []) if e]
    # {"text": 구절, "sfx": 소리|"none", "nth": 몇 번째 등장 | "at": 쇼츠 초} 도 허용 — nth/at 이 있으면 그 큐 하나에만(같은 말이 여러 번 나올 때)
    ents = [(e["text"], e) if isinstance(e, dict) else (e, {}) for e in emph_raw]
    emph = [t for t, _ in ents]
    _n = lambda x: re.sub(r"[^0-9A-Za-z가-힣]", "", x)
    emph_only = {}                                                             # 항목 번호 → 허용 큐 번호(없으면 모든 큐) — 같은 말을 두 번 강조해도 각자
    for ei, (t, e) in enumerate(ents):
        if e.get("nth") is None and e.get("at") is None:
            continue
        cnt, hit_cue = 0, -1
        for ci, cu in enumerate(cues):
            if _n(t) and _n(t) in _n("".join(cu["lines"])):
                if e.get("at") is not None:
                    if cu["start"] - 0.6 <= float(e["at"]) <= cu["end"] + 0.6:
                        hit_cue = ci; break
                else:
                    cnt += 1
                    if cnt == int(e["nth"]):
                        hit_cue = ci; break
        emph_only[ei] = hit_cue
        if hit_cue < 0:
            c.warnings.append(f"자막 강조 '{t}' ({'nth ' + str(e.get('nth')) if e.get('nth') is not None else 'at ' + str(e.get('at'))}) 를 못 찾음")
    emode = (plan_cap or {}).get("emphasis_mode") or ccfg.get("emphasis_mode", "color")
    accent = (plan_cap or {}).get("accent") or ccfg.get("accent", "#FFCC22")
    mk = ccfg.get("marker") or {}
    st = {**ccfg}
    cx = c.W / 2
    ease, _ = feel((plan_cap or {}).get("feel") or ccfg.get("feel"), "bouncy")
    pop = ccfg.get("pop") or {}
    c.emph_events = []                                                        # (t, 구절) — 효과음 자동 배치(R11)
    A, Dd = vmetrics(st["font"]); s = st["size"]
    norm = lambda x: re.sub(r"[^0-9A-Za-z가-힣]", "", x)

    def emph_hits(toks):
        """강조 구절(여러 어절 가능)이 걸친 토큰 인덱스 — 공백·문장부호 무시하고 큐 전체에서 찾는다.
        c._emph_rng[토큰] = (원문 글자 시작, 끝, 구절) — 마커를 맞은 글자에만(chars_only) 칠할 때 쓴다."""
        chars, owner, pos = [], [], []
        for k, t in enumerate(toks):
            for ci, ch in enumerate(t):
                if norm(ch):
                    chars.append(ch); owner.append(k); pos.append(ci)
        s_ = "".join(chars); hits = set(); c._emph_rng = {}
        for ei, e in enumerate(emph):
            if ei in emph_only and emph_only[ei] != c._cue_i:
                continue
            ne = norm(e); j = s_.find(ne)
            while ne and j >= 0:
                for q in range(j, j + len(ne)):
                    k = owner[q]; hits.add(k)
                    a0, a1, _ = c._emph_rng.get(k, (pos[q], pos[q] + 1, ei))
                    c._emph_rng[k] = (min(a0, pos[q]), max(a1, pos[q] + 1), ei)
                j = s_.find(ne, j + 1)
        for k, (a0, a1, e) in list(c._emph_rng.items()):          # 맞은 글자 바로 뒤 기호(%, 등)는 함께 칠한다: '99%는' → '99%'
            t = toks[k]
            while a1 < len(t) and not norm(t[a1]) and t[a1] not in " ":
                a1 += 1
            c._emph_rng[k] = (a0, a1, e)
        return hits

    for i, cue in enumerate(cues):
        c._cue_i = i
        lines = cue["lines"]
        n = len(lines)
        all_toks = [t for ln in lines for t in ln.split(" ")]
        hitset = emph_hits(all_toks) if emph else set()
        bl = c.baselines(st, n, ccfg["anchor"], (plan_cap or {}).get("y", ccfg["y"]), ccfg["line_pitch"])
        wi = cue.get("wi", [])
        widx = 0
        under, over = [], []
        for li, (ln, b) in enumerate(zip(lines, bl)):
            toks = ln.split(" ")
            lw = c.line_w(ln, st); x = cx - lw / 2
            spans = []
            for k, tok in enumerate(toks):
                w_id = f"w{i}_{widx}"
                word = words[wi[widx]] if widx < len(wi) and len(wi) >= sum(len(l.split(" ")) for l in lines) else None
                pre = " " if k else ""
                tx0 = x + (c.line_w(" ".join(toks[:k]) + " ", st) if k else 0)
                tw_ = c.line_w(tok, st)
                hit = widx in hitset
                fill = accent if (hit and emode == "color") else None
                spans.append(f'{esc(pre)}<tspan id="{w_id}"' + (f' fill="{fill}"' if fill else "") + f'>{esc(tok)}</tspan>')
                if (hit and emode == "marker") or style == "highlight":
                    ix0, itop, ix1, ibot = ink_bounds(st["font"], tok, s)
                    pad = 0.14 * s
                    rx0, ry0 = tx0 + ix0 - pad, b + itop - pad * 0.8
                    rw, rh = (ix1 - ix0) + 2 * pad, (ibot - itop) + pad * 1.6
                    if hit and emode == "marker" and mk.get("chars_only") and widx in getattr(c, "_emph_rng", {}):
                        a0_, a1_, _ = c._emph_rng[widx]            # 조사 빼고 맞은 글자만(R6): '증거가' → '증거'
                        sub = tok[a0_:a1_]
                        if sub and sub != tok:
                            sx0, _, sx1, _ = ink_bounds(st["font"], sub, s)
                            off = c.line_w(tok[:a0_], st) if a0_ else 0.0
                            rx0, rw = tx0 + off + sx0 - pad, (sx1 - sx0) + 2 * pad
                    rid = f"hb{i}_{widx}"
                    if style == "highlight":
                        under.append(f'<rect id="{rid}" x="{f2(rx0)}" y="{f2(ry0)}" width="{f2(rw)}" height="{f2(rh)}" rx="{f2(pad)}" fill="{accent}" opacity="0"/>')
                        if word:
                            c.js.append(f'tl.set("#{rid}",{{opacity:1}},{max(cue["start"], word["start"]):.3f});'
                                        f'tl.set("#{rid}",{{opacity:0}},{min(cue["end"], word["end"]):.3f});')
                    else:                                  # 마커는 브랜드 기본 강조색(글자는 흰색 유지 — 같은 색 글자가 묻히지 않게)
                        under.append(f'<rect id="{rid}" x="{f2(rx0)}" y="{f2(ry0)}" width="0" height="{f2(rh)}" rx="{f2(pad * 0.5)}" fill="{mk.get("color") or marker_color or accent}"/>')
                        t_on = max(cue["start"], word["start"]) if word else cue["start"]
                        c.js.append(f'tl.fromTo("#{rid}",{{attr:{{width:0}}}},{{attr:{{width:{f2(rw)}}},duration:{float(mk.get("dur", 0.25)):.2f},ease:"{mk.get("ease", "power2.out")}",immediateRender:false}},{t_on:.3f});')
                if hit and widx in getattr(c, "_emph_rng", {}):
                    ei_ = c._emph_rng[widx][2]
                    if not c.emph_events or c.emph_events[-1][2] != i or c.emph_events[-1][4] != ei_:
                        t_ev = max(cue["start"], word["start"]) if word else cue["start"]      # 수정본 자막(단어 연결 없음)은 큐 시작
                        c.emph_events.append((t_ev, ents[ei_][0], i, ents[ei_][1].get("sfx"), ei_))
                if style == "karaoke" and word and not (hit and emode == "marker"):
                    c.js.append(f'tl.set("#{w_id}",{{fill:"{accent}"}},{max(cue["start"], word["start"]):.3f});'
                                f'tl.set("#{w_id}",{{fill:"{fill or st.get("color", "#FFFFFF")}"}},{min(cue["end"], word["end"]):.3f});')
                widx += 1
            over.append(c.text(ln, cx, b, st, tspans="".join(spans)))
            c.add_el("caption", c.box(ln, cx, b, st), cue["start"], cue["end"], text=ln, cue=i)
        inner = "".join(under) + f'<g{c.shadow(st.get("shadow"))}>{"".join(over)}</g>'
        mid_y = (bl[0] - A * s + bl[-1] + Dd * s) / 2
        cid = f"cap{i}"
        c.clip(cid, cue["start"], cue["end"] - cue["start"], 3, inner, cls="cap", origin=(cx, mid_y))
        esc_ = float(ccfg.get("emph_scale", 1.0)) if hitset else 1.0
        if esc_ != 1.0 and max(c.line_w(l, st) for l in lines) * esc_ > ccfg.get("max_w", 960):
            esc_ = 1.0                                         # 넓은 큐는 키우지 않는다(R5)
        if style == "pop" and cue["start"] < 0.05:
            if esc_ != 1.0:
                c.js.append(f'tl.set("#{cid}-i",{{scale:{esc_:.4f}}},0);')
        elif style == "pop":
            if esc_ != 1.0:
                ep = ccfg.get("emph_pop") or {}
                c.js.append(f'tl.fromTo("#{cid}-i",{{scale:{esc_ * float(ep.get("from_scale", 0.86)):.4f},opacity:{float(pop.get("from_opacity", 0.2)):.2f}}},'
                            f'{{scale:{esc_:.4f},opacity:1,duration:{float(ep.get("dur", 0.16)):.2f},ease:"{ep.get("ease", "back.out(1.6)")}",immediateRender:false}},{cue["start"]:.3f});')
            else:
                c.js.append(f'tl.fromTo("#{cid}-i",{{scale:{float(pop.get("from_scale", 0.9)):.3f},opacity:{float(pop.get("from_opacity", 0.2)):.2f}}},'
                            f'{{scale:1,opacity:1,duration:{float(pop.get("dur", 0.14)):.2f},ease:"{pop.get("ease", ease)}",immediateRender:false}},{cue["start"]:.3f});')
        elif esc_ != 1.0:
            c.js.append(f'tl.set("#{cid}-i",{{scale:{esc_:.4f}}},{cue["start"]:.3f});')
        elif style == "fade":
            c.js.append(f'tl.fromTo("#{cid}-i",{{opacity:0}},{{opacity:1,duration:0.2,ease:"sine.out",immediateRender:false}},{cue["start"]:.3f});')


# ───────────────────────── 그래픽 비트 ─────────────────────────
def check_icon(x, y, size, color, kind="check", sw=None):
    sw = sw or size * 0.14
    if kind == "check":
        d = f"M{f2(x)},{f2(y + size * 0.52)} L{f2(x + size * 0.38)},{f2(y + size * 0.86)} L{f2(x + size)},{f2(y + size * 0.14)}"
    elif kind == "x":
        d = f"M{f2(x + size * 0.12)},{f2(y + size * 0.12)} L{f2(x + size * 0.88)},{f2(y + size * 0.88)} M{f2(x + size * 0.88)},{f2(y + size * 0.12)} L{f2(x + size * 0.12)},{f2(y + size * 0.88)}"
    else:   # arrow →
        d = f"M{f2(x)},{f2(y + size / 2)} L{f2(x + size)},{f2(y + size / 2)} M{f2(x + size * 0.58)},{f2(y + size * 0.14)} L{f2(x + size)},{f2(y + size / 2)} L{f2(x + size * 0.58)},{f2(y + size * 0.86)}"
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{f2(sw)}" stroke-linecap="round" stroke-linejoin="round"/>'


def overlaps(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def face_union(faces, t0, t1):
    fs = [f["box"] for f in faces if t0 <= f["t"] <= t1]
    if not fs:
        return None
    return [min(f[0] for f in fs), min(f[1] for f in fs), max(f[2] for f in fs), max(f[3] for f in fs)]


def pick_zone(c, g, t0, t1, faces, need_h, want=None):
    """그래픽 자리: 비트가 zone 을 지정하면("alt" 또는 [x0,y0,x1,y1]) 그 자리, 아니면 기본 → 얼굴과 겹치면 대체 자리."""
    if want == "alt" and g.get("alt_zone"):
        return g["alt_zone"]
    if isinstance(want, list) and len(want) == 4:
        return want
    zones = [g["zone"], g.get("alt_zone")]
    fb = face_union(faces, t0, t1)
    for z in zones:
        if not z:
            continue
        cy = (z[1] + z[3]) / 2
        box = [z[0], cy - need_h / 2, z[2], cy + need_h / 2]
        if not fb or overlaps(box, fb) < 0.05 * (box[2] - box[0]) * (box[3] - box[1]):
            return z
    c.warnings.append(f"그래픽 {t0:.1f}s: 얼굴과 겹치지 않는 자리를 못 찾음 — 기본 자리 사용")
    return g["zone"]


def gfx_style(c, g, size, color=None):
    st = {"font": g["font"], "family": g["family"], "weight": g.get("weight", 900), "size": size, "color": color or g["text"]}
    if g.get("kw_style", "band") == "outline":
        st["stroke"] = {"w": max(4, size * 0.07), "color": g.get("ink", "#0A0A0A")}
    return st


def fit_lines(c, g, lines, max_w, max_size, min_size=52, who=None):
    """size 는 '최대' — 자리 폭을 넘으면 2px 씩 줄인다. 줄였으면 경고(요청 크기와 실제 크기)."""
    size = max_size
    while size > min_size and max(tw(g["font"], l, size) for l in lines) > max_w:
        size -= 2
    if who is not None and size < max_size:
        c.warnings.append(f"{who}: 글자 {max_size}px 가 자리({int(max_w)}px)에 안 들어가 {size}px 로 줄임 — 문구를 줄이면 원래 크기")
    return size


def build_beats(c, beats, faces, g, motion_level, motion_feel=None):
    """beats: 해석이 끝난 비트 목록(시각 확정). keyword·number·compare·list·quote·flash. 줌은 build_camera.
    클립 id gN 의 N = short.json beats 번호(src_index) — Studio 에서 고른 요소를 바로 찾게."""
    accent = g["accent"]
    for i, bt in enumerate(beats):
        t0, t1 = bt["t0"], bt["t1"]; typ = bt["type"]
        ease, edur = feel(bt.get("feel") or motion_feel, "bouncy" if motion_level >= 2 else "smooth")
        i = bt.get("src_index", i)
        cid = f"g{i}"
        if typ == "broll":                                   # compose() 에서 밴드 층으로 따로 넣는다
            continue
        if typ == "flash":
            c.body.append(f'<div id="{cid}" class="clip flash" data-start="{t0:.3f}" data-duration="{max(0.12, t1 - t0):.3f}" data-track-index="5">'
                          f'<div class="inner fl" id="{cid}-i"></div></div>')
            c.js.append(f'tl.fromTo("#{cid}-i",{{opacity:0.85}},{{opacity:0,duration:{max(0.1, t1 - t0 - 0.02):.3f},ease:"power2.out",immediateRender:false}},{t0:.3f});')
            continue
        if typ in ("keyword", "quote"):
            lines = [l.strip() for l in str(bt.get("text", "")).split("/") if l.strip()]
            if typ == "quote":
                lines[0] = "“" + lines[0]; lines[-1] = lines[-1] + "”"
            zone_w = g["zone"][2] - g["zone"][0]
            size = fit_lines(c, g, lines, zone_w - 80, bt.get("size", 96 if typ == "keyword" else 72),
                             who=f"beats[{i}] {typ}" if bt.get("size") else None)
            pitch = size * 1.18
            need_h = pitch * len(lines) + 40
            z = pick_zone(c, g, t0, t1, faces, need_h, bt.get("zone"))
            cx, cy = (z[0] + z[2]) / 2, (z[1] + z[3]) / 2
            st = gfx_style(c, g, size)
            bl = c.baselines(st, len(lines), "middle", cy, pitch)
            parts = []
            if g.get("kw_style") == "box" and typ == "keyword":     # 빨강 둥근 상자 + 흰 글자(2026-09-28 디자인 R7) — 자막 자리, 한 줄
                if len(lines) > 1:
                    c.warnings.append(f"beats[{i}] keyword: box 스타일은 한 줄 — '{' '.join(lines)}' 로 합침")
                    lines = [" ".join(lines)]
                kb = g.get("kw_box") or {}
                size = bt.get("size") or g.get("kw_size", 96)
                while size > g.get("kw_min_size", 72) and tw(g["font"], lines[0], size) > g.get("kw_max_w", 700):
                    size -= 2
                st = gfx_style(c, g, size, g["text"]); st.pop("stroke", None)
                bl = c.baselines(st, 1, "middle", cy, pitch)
                l, b = lines[0], bl[0]
                lw = c.line_w(l, st); ix0, itop, ix1, ibot = ink_bounds(st["font"], l, size)
                x_left = cx - lw / 2
                px, py = float(kb.get("pad_x_em", 0.22)) * size, float(kb.get("pad_y_em", 0.14)) * size
                bx0, bx1 = x_left + ix0 - px, x_left + ix1 + px
                by0, by1 = b + itop - py, b + ibot + py
                rect = (f'<rect x="{f2(bx0)}" y="{f2(by0)}" width="{f2(bx1 - bx0)}" height="{f2(by1 - by0)}" '
                        f'rx="{f2(float(kb.get("radius_em", 0.14)) * size)}" fill="{accent}"/>')
                inner = f'<g{c.shadow(kb.get("shadow") or {"x": 0, "y": 6, "blur": 10, "color": "rgba(0,0,0,0.5)"})}>{rect}{c.text(l, cx, b, st)}</g>'
                c.clip(cid, t0, t1 - t0, 4, inner, cls="gfx", origin=(cx, cy))
                c.add_el("graphic", [bx0, by0, bx1, by1], t0, t1, text=l, beat=i, size=size, replaces_caption=bool(g.get("kw_replaces_caption")))
                if not bt.get("feel"):
                    ease, edur = "back.out(1.6)", 0.22
                if g.get("kw_replaces_caption"):
                    c.kw_windows.append((t0, t1))
            elif g.get("kw_style", "band") == "band":
                for l, b in zip(lines, bl):
                    lw = c.line_w(l, st); ix0, itop, ix1, ibot = ink_bounds(st["font"], l, size)
                    x_left = cx - lw / 2
                    gtop, gbot = b + itop, b + ibot
                    bh = (gbot - gtop) * 0.62; by2 = gbot + 8; by1 = by2 - bh
                    bx0, bx1 = x_left + ix0 - 22, x_left + ix1 + 22
                    pts = f"{f2(bx0 + 12)},{f2(by1 + 3)} {f2(bx1 - 5)},{f2(by1)} {f2(bx1 + 10)},{f2(by2 - 4)} {f2(bx0 - 4)},{f2(by2)}"
                    parts.append(f'<polygon points="{pts}" fill="{accent}"/>')
                txt = "".join(c.text(l, cx, b, st) for l, b in zip(lines, bl))
                inner = f'<g{c.shadow({"x": 4, "y": 5, "blur": 8, "color": "rgba(0,0,0,0.55)"})}>{"".join(parts)}{txt}</g>'
            else:
                txt = "".join(c.text(l, cx, b, {**st, "color": accent if k == len(lines) - 1 else g["text"]}) for k, (l, b) in enumerate(zip(lines, bl)))
                inner = f'<g{c.shadow({"x": 3, "y": 3, "blur": 0, "color": "rgba(0,0,0,0.5)"})}>{txt}</g>'
            if not (g.get("kw_style") == "box" and typ == "keyword"):
                c.clip(cid, t0, t1 - t0, 4, inner, cls="gfx", origin=(cx, cy))
                for l, b in zip(lines, bl):
                    c.add_el("graphic", c.box(l, cx, b, st), t0, t1, text=l, beat=i, size=size)
        elif typ == "number":
            label = bt.get("label", ""); pre, suf = bt.get("prefix", ""), bt.get("suffix", "")
            v0, v1 = bt.get("from", 0), bt["to"]
            dec = int(bt.get("decimals", 0))
            fmt = lambda v: f"{pre}{v:,.{dec}f}{suf}"
            size = fit_lines(c, g, [fmt(v0), fmt(v1)], g["zone"][2] - g["zone"][0] - 120, bt.get("size", 150), 80)
            lab_size = 46
            need_h = size * 1.1 + (lab_size * 1.6 if label else 0) + 60
            z = pick_zone(c, g, t0, t1, faces, need_h, bt.get("zone"))
            cx, cy = (z[0] + z[2]) / 2, (z[1] + z[3]) / 2
            st = gfx_style(c, g, size, accent if g.get("kw_style") == "outline" else g["text"])
            st["size"] = size
            c.use_font(st, fmt(v0) + fmt(v1) + "0123456789,.")
            top = cy - need_h / 2 + 30
            parts = []
            card = [z[0] + 40, cy - need_h / 2, z[2] - 40, cy + need_h / 2]
            parts.append(f'<rect x="{f2(card[0])}" y="{f2(card[1])}" width="{f2(card[2] - card[0])}" height="{f2(card[3] - card[1])}" rx="28" fill="{g["card_bg"]}"/>')
            if label:
                lst = {**gfx_style(c, g, lab_size), "stroke": None}
                lb = c.baselines(lst, 1, "ascender", top, 0)[0]
                parts.append(c.text(label, cx, lb, lst, fill=g["text"]))
                top += lab_size * 1.6
            nb = c.baselines(st, 1, "ascender", top, 0)[0]
            nid = f"{cid}n"
            parts.append(c.text(fmt(v0), cx, nb, st, idattr=f' id="{nid}"'))
            if g.get("kw_style") == "band":            # 두 색 규율: 흰 숫자 + 채널 강조색 밑줄
                uw = max(c.line_w(fmt(v0), st), c.line_w(fmt(v1), st)) * 0.8
                parts.append(f'<rect x="{f2(cx - uw / 2)}" y="{f2(nb + size * 0.12)}" width="{f2(uw)}" height="{f2(max(8, size * 0.07))}" rx="4" fill="{accent}"/>')
            c.clip(cid, t0, t1 - t0, 4, "".join(parts), cls="gfx", origin=(cx, cy))
            cdur = min(1.2, max(0.5, (t1 - t0) * 0.45))
            c.js.append(f'(function(){{var el=document.getElementById("{nid}"),o={{v:{v0}}};'
                        f'tl.fromTo(o,{{v:{v0}}},{{v:{v1},duration:{cdur:.2f},ease:"power2.out",immediateRender:false,'
                        f'onUpdate:function(){{el.textContent="{esc(pre)}"+o.v.toLocaleString("en-US",{{minimumFractionDigits:{dec},maximumFractionDigits:{dec}}})+"{esc(suf)}";}}}},{t0 + 0.15:.3f});}})();')
            c.add_el("graphic", card, t0, t1, text=f"{fmt(v0)}→{fmt(v1)}", beat=i)
        elif typ == "compare":
            left, right = bt["left"], bt["right"]
            size = fit_lines(c, g, [left, right], (g["zone"][2] - g["zone"][0]) / 2 - 110, bt.get("size", 84), 48)
            need_h = size * 1.6 + 70
            z = pick_zone(c, g, t0, t1, faces, need_h, bt.get("zone"))
            cx, cy = (z[0] + z[2]) / 2, (z[1] + z[3]) / 2
            st = gfx_style(c, g, size)
            half = (z[2] - z[0]) / 2
            lx, rx = z[0] + half / 2 + 10, z[2] - half / 2 - 10
            b = c.baselines(st, 1, "middle", cy, 0)[0]
            card = [z[0] + 20, cy - need_h / 2, z[2] - 20, cy + need_h / 2]
            lid, rid, aid = f"{cid}l", f"{cid}r", f"{cid}a"
            t_right = bt.get("t_right", t0 + 0.7)
            parts = [f'<rect x="{f2(card[0])}" y="{f2(card[1])}" width="{f2(card[2] - card[0])}" height="{f2(card[3] - card[1])}" rx="28" fill="{g["card_bg"]}"/>',
                     f'<g id="{lid}">{c.text(left, lx, b, st, fill="#BDBDBD")}</g>',
                     f'<g id="{aid}" opacity="0">{check_icon(cx - 26, cy - 26, 52, g["text"], "arrow", 7)}</g>',
                     f'<g id="{rid}" opacity="0">{c.text(right, rx, b, st, fill=accent if g.get("kw_style") == "outline" else g["text"])}'
                     + (f'<rect x="{f2(rx - c.line_w(right, st) / 2)}" y="{f2(b + 14)}" width="{f2(c.line_w(right, st))}" height="9" rx="4" fill="{accent}"/>' if g.get("kw_style") == "band" else "")
                     + '</g>']
            c.clip(cid, t0, t1 - t0, 4, "".join(parts), cls="gfx", origin=(cx, cy))
            c.js.append(f'tl.fromTo("#{aid}",{{opacity:0}},{{opacity:1,duration:0.15,immediateRender:false}},{t_right - 0.15:.3f});'
                        f'tl.fromTo("#{rid}",{{opacity:0}},{{opacity:1,duration:0.18,immediateRender:false}},{t_right:.3f});'
                        f'tl.fromTo("#{lid}",{{opacity:1}},{{opacity:0.45,duration:0.2,immediateRender:false}},{t_right:.3f});')
            c.add_el("graphic", card, t0, t1, text=f"{left}→{right}", beat=i)
        elif typ == "list":
            items = bt["items"]
            title = bt.get("title")
            isz = fit_lines(c, g, [it["text"] for it in items], g["zone"][2] - g["zone"][0] - 190, bt.get("size", 64), 40)
            row = isz * 1.45
            need_h = row * len(items) + (isz * 1.3 if title else 0) + 60
            base_z = bt["zone"] if isinstance(bt.get("zone"), list) else (g.get("alt_zone") if bt.get("zone") == "alt" else g.get("list_zone") or g["zone"])
            z = [base_z[0], min(base_z[1], base_z[3] - need_h), base_z[2], base_z[3]]
            fb = face_union(faces, t0, t1)
            y0 = z[3] - need_h
            card = [z[0] + 20, y0, z[2] - 20, z[3]]
            if fb and overlaps(card, fb) > 0.05 * (card[2] - card[0]) * (card[3] - card[1]):
                c.warnings.append(f"리스트 {t0:.1f}s: 얼굴과 겹침 — 항목 수·글자 크기를 줄이세요")
            st = {**gfx_style(c, g, isz), "stroke": None}
            parts = [f'<rect x="{f2(card[0])}" y="{f2(card[1])}" width="{f2(card[2] - card[0])}" height="{f2(card[3] - card[1])}" rx="28" fill="{g["card_bg"]}"/>']
            y = y0 + 30
            if title:
                tst = {**st, "size": isz * 0.8}
                parts.append(c.text(title, (card[0] + card[2]) / 2, c.baselines(tst, 1, "ascender", y, 0)[0], tst, fill=accent if g.get("kw_style") == "outline" else "#DDDDDD"))
                y += isz * 1.3
            xl = card[0] + 50
            for k, it in enumerate(items):
                iid = f"{cid}i{k}"
                b = c.baselines(st, 1, "middle", y + row / 2, 0)[0]
                w = c.line_w(it["text"], st)
                tx = xl + isz * 1.25 + w / 2
                parts.append(f'<g id="{iid}" opacity="0">{check_icon(xl, y + row / 2 - isz * 0.42, isz * 0.84, accent, "check", isz * 0.13)}'
                             f'{c.text(it["text"], tx, b, st)}</g>')
                c.js.append(f'tl.fromTo("#{iid}",{{opacity:0,x:-18}},{{opacity:1,x:0,duration:0.22,ease:"power2.out",immediateRender:false}},{it["t"]:.3f});')
                y += row
            c.clip(cid, t0, t1 - t0, 4, "".join(parts), cls="gfx", origin=((card[0] + card[2]) / 2, (card[1] + card[3]) / 2))
            c.add_el("graphic", card, t0, t1, text=" / ".join(it["text"] for it in items), beat=i)
        else:
            c.warnings.append(f"알 수 없는 비트 유형 {typ} — 건너뜀")
            continue
        # 등장·퇴장(컷 모드면 즉시)
        if typ in ("keyword", "quote", "number", "compare", "list") and bt.get("enter", "pop" if motion_level >= 1 else "cut") != "cut":
            enter = bt.get("enter", "pop")
            if enter == "pop":
                c.js.append(f'tl.fromTo("#{cid}-i",{{scale:0.82,opacity:0}},{{scale:1,opacity:1,duration:{edur:.2f},ease:"{ease}",immediateRender:false}},{t0:.3f});')
            elif enter == "rise":
                c.js.append(f'tl.fromTo("#{cid}-i",{{y:40,opacity:0}},{{y:0,opacity:1,duration:{edur:.2f},ease:"{ease}",immediateRender:false}},{t0:.3f});')
            elif enter == "fade":
                c.js.append(f'tl.fromTo("#{cid}-i",{{opacity:0}},{{opacity:1,duration:{edur:.2f},ease:"sine.out",immediateRender:false}},{t0:.3f});')
            if t1 - t0 > 0.6:
                c.js.append(f'tl.fromTo("#{cid}-i",{{opacity:1}},{{opacity:0,duration:0.15,ease:"power1.in",immediateRender:false}},{t1 - 0.15:.3f});')


def build_split(c, beats, faces, sp):
    """분할 레이아웃(비블 v3, 2026-09-28 사용자 지시 · 레퍼런스 instagram.com/reels/DdgX9gCvj8r): B-roll 이 뜨는 동안
    위 패널(0~line, 카드 영상)이 위에서 내려오고, 화자는 #cam-split 으로 아래로 밀리며(person_scale<1 이면 함께 줄어듦 — 넓은
    base 라 옆이 비지 않음) 얼굴 박스 위 끝이 face_target 에 온다. 제목·자막 층은 각자 title_shift·cap_shift 만큼(없으면
    text_shift) 움직이고 title_scale·cap_scale 로 줄일 수 있다(자기 가운데 기준). 로고는 잠깐 사라진다. 끝나면 되돌아간다.
    merge_gap 초 안에 이어지는 카드는 한 번에 묶는다(들락날락 방지). 전환 dur 초 · ease.
    #cam-split 은 줌(#cam-inner scale)과 다른 층이라 분할 중 펀치인도 서로 덮어쓰지 않는다."""
    S = sp["line"]; d0 = float(sp.get("dur", 0.4)); ease = sp.get("ease", "power2.inOut")
    tsh = float(sp.get("text_shift", 0)); fade = float(sp.get("logo_fade", 0.25))
    shifts = {"title": float(sp.get("title_shift", tsh)), "cap": float(sp.get("cap_shift", tsh))}
    scales = {"title": float(sp.get("title_scale", 1.0)), "cap": float(sp.get("cap_scale", 1.0))}
    tb = next((e["box"] for e in c.elements if e["kind"] == "title-box"), None)
    origin_y = {"title": ((tb[1] + tb[3]) / 2) if tb else float(sp.get("title_origin_y", c.H / 2)),
                "cap": float(sp.get("cap_origin_y", c.b["captions"]["y"]))}
    ps = float(sp.get("person_scale", 1.0))
    br = sorted([b for b in beats if b["type"] == "broll"], key=lambda b: b["t0"])
    wins = []
    for b in br:
        if wins and b["t0"] - wins[-1]["t1"] <= float(sp.get("merge_gap", 2.0)):
            wins[-1]["t1"] = max(wins[-1]["t1"], b["t1"]); wins[-1]["cards"].append(b)
        else:
            wins.append({"t0": b["t0"], "t1": b["t1"], "cards": [b]})
    c.js.append(f'tl.set("#cam-split",{{transformOrigin:"{c.W / 2:.1f}px 0px"}},0);')
    for L in ("title", "cap"):
        if c.layers.get(L):
            c.js.append(f'tl.set("#L-{L}",{{transformOrigin:"{c.W / 2:.1f}px {origin_y[L]:.1f}px"}},0);')
    for w in wins:
        a, z = w["t0"], w["t1"]; d = min(d0, max(0.12, (z - a) / 3))
        to_end = z >= c.D - 0.04                         # 카드가 쇼츠 마지막 프레임까지 가면 되돌아가지 않는다(끝 카드 = 펀치라인 유지). 조금이라도 먼저 끝나면 되돌아가야 위 패널이 검게 비지 않는다
        ys = sorted(f["box"][1] for f in faces if a <= f["t"] <= z) or sorted(f["box"][1] for f in faces)
        fy = ys[len(ys) // 2] if ys else float(sp.get("face_top", 465))
        sh = min(float(sp.get("max_shift", 900)), max(float(sp.get("min_shift", 250)), float(sp["face_target"]) - fy * ps))
        sh = max(sh, c.H * (1 - ps))                     # 줄였을 때 인물 영상 아래 끝이 화면 아래에 닿게(바닥이 비지 않게)
        E = f'duration:{d:.3f},ease:"{ease}",immediateRender:false'
        c.js.append(f'tl.fromTo("#cam-split",{{y:0,scale:1}},{{y:{sh:.1f},scale:{ps:.4f},{E}}},{a:.3f});')
        if not to_end:
            c.js.append(f'tl.fromTo("#cam-split",{{y:{sh:.1f},scale:{ps:.4f}}},{{y:0,scale:1,{E}}},{z - d:.3f});')
        for L in ("title", "cap"):
            if c.layers.get(L) and (shifts[L] or scales[L] != 1.0):
                c.js.append(f'tl.fromTo("#L-{L}",{{y:0,scale:1}},{{y:{shifts[L]:.1f},scale:{scales[L]:.4f},{E}}},{a:.3f});')
                if not to_end:
                    c.js.append(f'tl.fromTo("#L-{L}",{{y:{shifts[L]:.1f},scale:{scales[L]:.4f}}},{{y:0,scale:1,{E}}},{z - d:.3f});')
        if c.layers.get("logo") and sp.get("hide_logo", True):
            c.js.append(f'tl.fromTo("#L-logo",{{opacity:1}},{{opacity:0,duration:{fade:.3f},immediateRender:false}},{a:.3f});')
            if not to_end:
                c.js.append(f'tl.fromTo("#L-logo",{{opacity:0}},{{opacity:1,duration:{fade:.3f},immediateRender:false}},{z - fade:.3f});')
        first, last = w["cards"][0], w["cards"][-1]
        c.js.append(f'tl.fromTo("#{first["_vid"]}",{{y:{-S}}},{{y:0,{E}}},{a:.3f});')
        if not to_end:
            c.js.append(f'tl.fromTo("#{last["_vid"]}",{{y:0}},{{y:{-S},{E}}},{z - d:.3f});')
        edge = sp.get("edge") or {}
        if edge.get("kind") == "shadow":                  # 패널 아래 부드러운 그림자(R2) — 패널과 같이 내려오고 올라간다
            k = len(c.split_edges); c.split_edges.append(k)
            px_, al = int(edge.get("px", 32)), float(edge.get("alpha", 0.45))
            c.under.append(f'<div id="sedge{k}" class="clip" data-start="{a:.3f}" data-duration="{z - a:.3f}" data-track-index="2" '
                           f'style="left:0;top:{S}px;width:{c.W}px;height:{px_}px;background:linear-gradient(to bottom,rgba(0,0,0,{al}),rgba(0,0,0,0))"></div>')
            c.js.append(f'tl.fromTo("#sedge{k}",{{y:{-S}}},{{y:0,{E}}},{a:.3f});')
            if not to_end:
                c.js.append(f'tl.fromTo("#sedge{k}",{{y:0}},{{y:{-S},{E}}},{z - d:.3f});')
        pp = sp.get("panel_push") or {}
        if pp:                                            # 카드마다 느린 밀기(R8) — 같은 비트가 점프컷으로 이어지면 배율도 이어서
            ox, oy = (pp.get("origin") or [c.W / 2, S * 0.56])
            prev = None; s0 = 1.0
            for cd in w["cards"]:
                L = max(0.05, cd["t1"] - cd["t0"])
                if prev is None or cd.get("broll_beat") is None or cd.get("broll_beat") != prev.get("broll_beat"):
                    s0 = 1.0
                s1 = min(float(pp.get("max", 1.04)), s0 + float(pp.get("rate_per_s", 0.008)) * L)
                c.js.append(f'tl.set("#{cd["_vid"]}",{{transformOrigin:"{ox:.0f}px {oy:.0f}px"}},0);')
                c.js.append(f'tl.fromTo("#{cd["_vid"]}",{{scale:{s0:.4f}}},{{scale:{s1:.4f},duration:{L:.3f},ease:"{pp.get("ease", "none")}",immediateRender:false}},{cd["t0"]:.3f});')
                prev, s0 = cd, s1
        c.add_el("split", [0, 0, c.W, S], a, z, shift=round(sh, 1), person_scale=ps,
                 title_shift=shifts["title"], cap_shift=shifts["cap"])


def build_camera(c, zooms, band, faces):
    """#cam-inner 스케일 포즈 사다리. 겹치지 않게 순서대로, 매 구간 명시적 from→to(탐색 순서와 무관하게 같은 화면)."""
    last = 1.0
    for z in sorted(zooms, key=lambda z: z["t0"]):
        cam = VOCAB["camera"].get(z.get("style", "punch"), VOCAB["camera"]["punch"])
        sc = float(z.get("scale", cam["scale"]))
        t0, t1 = z["t0"], z["t1"]
        fb = face_union(faces, t0, t1)
        ox = ((fb[0] + fb[2]) / 2 - band["x"]) if fb else band["w"] / 2
        oy = ((fb[1] + fb[3]) / 2 - band["y"]) if fb else band["h"] * 0.4
        c.js.append(f'tl.set("#cam-inner",{{transformOrigin:"{f2(ox)}px {f2(oy)}px"}},{t0:.3f});')
        if cam["in"] == "span":
            c.js.append(f'tl.fromTo("#cam-inner",{{scale:{last}}},{{scale:{sc},duration:{t1 - t0:.3f},ease:"{cam["ease"]}",immediateRender:false}},{t0:.3f});')
        else:
            c.js.append(f'tl.fromTo("#cam-inner",{{scale:{last}}},{{scale:{sc},duration:{cam["in"]},ease:"{cam["ease"]}",immediateRender:false}},{t0:.3f});')
        c.js.append(f'tl.fromTo("#cam-inner",{{scale:{sc}}},{{scale:1,duration:0.001,immediateRender:false}},{t1:.3f});')
        last = 1.0
        c.add_el("zoom", [0, 0, 0, 0], t0, t1, scale=sc)


def subset_fonts(c, bdir):
    os.makedirs(os.path.join(bdir, "fonts"), exist_ok=True)
    from fontTools import subset
    css = []
    for ff, ent in c.fonts.items():
        chars = "".join(sorted(ent["chars"] | set(SAFE_EXTRA)))
        key = hashlib.md5((ff + chars).encode()).hexdigest()[:8]
        out = os.path.join(bdir, "fonts", f"{os.path.splitext(ff)[0]}-{key}.woff2")
        if not os.path.exists(out):
            opts = subset.Options(); opts.flavor = "woff2"; opts.layout_features = ["*"]; opts.notdef_outline = True
            opts.name_IDs = ["*"]; opts.hinting = False
            font = subset.load_font(find_font(ff), opts)
            s = subset.Subsetter(opts); s.populate(text=chars); s.subset(font)
            subset.save_font(font, out, opts)
        css.append(f'@font-face{{font-family:"{ent["family"]}";src:url("fonts/{os.path.basename(out)}") format("woff2");'
                   f'font-weight:{ent["weight"]};font-style:normal;font-display:block}}')
    return "\n".join(css)


SFX_LEN = {}


def sfx_len(path):
    if path not in SFX_LEN:
        r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
        SFX_LEN[path] = float(r.stdout.strip() or 1.0)
    return SFX_LEN[path]


AUTO_PRIO = {"keyword": 10, "caption_hit_accent": 9, "accent": 9, "state_accent": 9, "conclusion": 8, "positive": 7, "negative": 7,
             "split_in": 6, "card_change": 5, "capture": 4, "extra": 4, "trend": 3, "check": 3, "step": 3, "typing": 2,
             "caption_hit": 2, "chip": 1, "minor": 1, "state": 1, "appear": 1, "button": 4}


def auto_sfx(c, ctx, brand, plan):
    """쇼츠 효과음 자동 배치(2026-09-28 디자인 R11): 패널 새 그림(short.json sfx_events — 롱폼 B-roll 역할), 분할 진입, 카드 바뀜,
    자막 강조 단어, 키워드 상자를 모아 brand sfx_auto.map 으로 소리를 정하고 density 규칙(최소 간격·같은 소리 간격·띵 간격·
    편당 1번 소리·8초당 개수·끝 0.3초)으로 우선순위 높은 것부터 솎는다. short.json 의 sfx(손으로 넣은 것)가 먼저·항상 이긴다.
    short.json "sfx_auto": false 면 끈다."""
    cfg = brand.get("sfx_auto") or {}
    if not cfg or plan.get("sfx_auto") is False:
        return ctx["sfx"]
    mp, den, vol = cfg.get("map", {}), cfg.get("density", {}), cfg.get("vol", {})
    banned = set(cfg.get("banned", []))
    sub = cfg.get("substitute") or {}                # 브랜드 소리 바꾸기(예: 띠링 → 딸깍) — 손으로 정한 소리에도
    for s_ in ctx["sfx"]:
        s_["name"] = sub.get(s_["name"], s_["name"])
    ev = [(float(e["t"]), e["role"]) for e in ctx.get("sfx_events") or []]
    for e in c.elements:
        if e["kind"] == "split":
            ev.append((e["t"][0], "split_in"))
    brs = sorted([b for b in ctx["beats"] if b["type"] == "broll"], key=lambda b: b["t0"])
    for a_, b_ in zip(brs, brs[1:]):
        if b_["t0"] - a_["t1"] < 0.2 and b_.get("broll_beat") != a_.get("broll_beat"):
            ev.append((b_["t0"], "card_change"))
    panel_ts = [float(e["t"]) for e in ctx.get("sfx_events") or []]
    for t, ph, _ci, sx, _ei in c.emph_events:
        if sx == "none":
            continue
        role = "caption_hit_accent" if re.search(r"\d", ph) else "caption_hit"
        if not sx and role == "caption_hit" and any(abs(pt - t) < 0.6 for pt in panel_ts):
            continue                                   # 같은 뜻의 패널 그림이 0.6초 안에 뜨면 소리는 패널 것 하나만(디자인 검수 j2)
        ev.append((t, "!" + sx) if sx else (t, role))  # '!' = 편집으로 정한 소리(결론 차임 등) — 패널 소리보다 먼저
    for b in ctx["beats"]:
        if b["type"] == "keyword":
            ev.append((b["t0"], "keyword"))
    mg, sg, pg = float(den.get("min_gap", 0.45)), float(den.get("same_sound_min_gap", 0.9)), float(den.get("ping_min_gap", 6.0))
    once, per8, tail = set(den.get("once_per_short", [])), int(den.get("max_per_8s", 4)), float(den.get("no_sfx_last_s", 0.3))
    kept = [(float(s_["t"]), s_["name"]) for s_ in ctx["sfx"]]
    nman = len(kept)

    def ok(t, name):
        if t < 0 or t > c.D - tail:
            return False
        for kt, kn in kept:
            if abs(kt - t) < mg or (kn == name and abs(kt - t) < sg) or (name == kn == "ping-t" and abs(kt - t) < pg):
                return False
        if name in once and any(kn == name for _, kn in kept):
            return False
        ts = sorted([kt for kt, _ in kept] + [t]); j = 0          # 어느 8초 창에도 per8 개 넘게 들어가지 않게(미끄러지는 창)
        for i in range(len(ts)):
            while ts[i] - ts[j] >= 8.0:
                j += 1
            if i - j + 1 > per8:
                return False
        return True

    def prio(role):
        return 9.5 if role.startswith("!") else AUTO_PRIO.get("extra" if role.startswith("=") else role, 1)

    def sound(role):
        name = role[1:] if role[:1] in ("=", "!") else mp.get(role)
        name = sub.get(name, name)
        return name if name and name not in banned else None

    # 1) 큰 사건(키워드·빨강·편집으로 정한 소리·분할 진입·카드 바뀜)을 먼저
    for t, role in sorted([e for e in ev if prio(e[1]) >= 5], key=lambda e: (-prio(e[1]), e[0])):
        name = sound(role)
        if name and ok(t, name):
            kept.append((t, name))
    # 2) 가장 큰 공백부터, 그 공백 가운데에 가까운 후보(우선순위 높은 것 먼저)로 채운다 — 한쪽에 몰리고 다른 곳이 비지 않게
    fill = float(den.get("fill_gap", 2.6))
    rest = [e for e in ev if prio(e[1]) < 5]
    while True:
        pts = sorted([0.0] + [kt for kt, _ in kept] + [c.D])
        gaps = sorted([(b - a, a, b) for a, b in zip(pts, pts[1:]) if b - a > fill], reverse=True)
        placed = False
        for _g, a, b in gaps:
            mid = (a + b) / 2
            fg = float(den.get("fill_min_gap", 1.0))      # 채우는 소리는 이웃과 1초 이상 — 몰린 소리가 8초 한도를 먼저 써 버리지 않게
            for t, role in sorted([e for e in rest if a + fg <= e[0] <= b - fg or (b >= c.D - 0.01 and a + fg <= e[0])],
                                  key=lambda e: (-prio(e[1]), abs(e[0] - mid))):
                name = sound(role)
                if name and ok(t, name):
                    kept.append((t, name)); rest.remove((t, role)); placed = True
                    break
            if placed:
                break
        if not placed:
            break
    out = [dict(s_) for s_ in ctx["sfx"]]
    for t, name in kept[nman:]:
        out.append({"name": name, "t": round(t, 3), **({"vol": vol[name]} if name in vol else {}), "auto": True})
    return sorted(out, key=lambda s_: s_["t"])


def build_audio(c, bdir, sfx, bgm):
    c.audio.append(f'<audio id="a-base" src="base.mp4" data-start="0" data-duration="{c.D:.3f}" data-track-index="10" data-volume="1"></audio>')
    os.makedirs(os.path.join(bdir, "sfx"), exist_ok=True)
    for k, s in enumerate(sfx):
        spec = VOCAB["sfx"].get(s["name"])
        if not spec:
            c.warnings.append(f"효과음 이름 {s['name']} 없음 — vocab.json sfx 목록 참고"); continue
        src = os.path.join(ASSETS, "sfx", spec["file"])
        dst = os.path.join(bdir, "sfx", spec["file"])
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
        ln = min(sfx_len(src), max(0.1, c.D - s["t"]))
        if s["t"] >= c.D - 0.05:
            continue
        c.audio.append(f'<audio id="sfx{k}" src="sfx/{spec["file"]}" data-start="{s["t"]:.3f}" data-duration="{ln:.3f}" '
                       f'data-track-index="11" data-volume="{s.get("vol", spec["vol"])}"></audio>')
    if bgm and bgm.get("file"):
        c.audio.append(f'<audio id="a-bgm" src="{bgm["file"]}" data-start="0" data-duration="{c.D:.3f}" data-track-index="12" data-volume="1"></audio>')


def compose(bdir, brand, plan, ctx):
    """ctx: duration, fps, words(쇼츠 시각), cues, faces([{t, box}] 캔버스 px), beats, zooms, sfx, bgm"""
    D = ctx["duration"]
    c = Comp(brand, D, ctx["fps"])
    band = brand["layout"]["band"]
    split = brand.get("split") if any(b["type"] == "broll" for b in ctx["beats"]) else None
    c.layer = "title" if split else None
    tcfg_ = {**brand["title"], **({"split": None} if (plan.get("title") or {}).get("one_line") else {})}   # 짧은 구호는 한 줄 그대로(title.one_line)
    title = build_title(c, (plan.get("title") or {}).get("lines") or [], tcfg_)
    c.layer = "logo" if split else None
    build_mark(c, brand.get("watermark"), "watermark", bdir)
    build_mark(c, brand.get("signature"), "signature", bdir)
    g = dict(brand["graphics"]); g.setdefault("kw_style", "band" if brand["title"].get("band") else "outline")
    c.layer = "cap" if split else None
    build_captions(c, ctx["cues"], ctx["words"], brand["captions"], plan.get("captions"), marker_color=g.get("accent"))
    c.layer = None
    # B-roll 카드: 밴드 자리를 덮는 영상(화자 위, 제목·자막 아래). 줌은 #cam 안만 움직여 카드는 그대로.
    # 분할(brand split, 비블 v3 2026-09-28): 카드는 위 패널(0~line)에만, 화자는 아래로 밀리고 제목·자막은 분할선으로 올라간다(build_split)
    rect = (0, 0, c.W, split["line"]) if split else (band["x"], band["y"], band["w"], band["h"])
    for bt in ctx["beats"]:
        if bt["type"] != "broll":
            continue
        k = bt.get("src_index", len(c.under)); bt["_vid"] = f"br{k}"
        (c.panel if split else c.under).append(f'<video id="br{k}" class="broll" src="{esc(bt["src_rel"])}" muted playsinline data-start="{bt["t0"]:.3f}" '
                       f'data-duration="{max(0.04, bt["t1"] - bt["t0"]):.3f}" data-track-index="1" '
                       f'style="position:absolute;left:{rect[0]}px;top:{rect[1]}px;width:{rect[2]}px;height:{rect[3]}px;object-fit:cover;display:block"></video>')
        c.add_el("broll", [rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]], bt["t0"], bt["t1"], text=os.path.basename(bt["src_rel"]))
    if split:
        build_split(c, ctx["beats"], ctx["faces"], split)
    build_beats(c, ctx["beats"], ctx["faces"], g, int(plan.get("motion", {}).get("level", g.get("default_motion_level", 0))),
                (plan.get("motion") or {}).get("feel"))
    for (k0, k1) in c.kw_windows:                     # 키워드 상자가 자막 자리에 뜨는 동안 그 자막은 숨긴다(R7 kw_replaces_caption)
        for i, cue in enumerate(ctx["cues"]):
            if cue["start"] < k1 and cue["end"] > k0:
                c.js.append(f'tl.set("#cap{i}",{{opacity:0}},{max(k0, cue["start"]):.3f});')
                if cue["end"] > k1:
                    c.js.append(f'tl.set("#cap{i}",{{opacity:1}},{k1:.3f});')
    build_camera(c, ctx["zooms"], band, ctx["faces"])
    sfx_all = auto_sfx(c, ctx, brand, plan)
    build_audio(c, bdir, sfx_all, ctx.get("bgm"))
    c.sfx_final = sfx_all
    font_css = subset_fonts(c, bdir)
    os.makedirs(os.path.join(bdir, "vendor"), exist_ok=True)
    if not os.path.exists(os.path.join(bdir, "vendor", "gsap.min.js")):
        shutil.copy2(os.path.join(TEMPLATES, "gsap.min.js"), os.path.join(bdir, "vendor", "gsap.min.js"))
    bg = brand["canvas"].get("bg", "#000000")
    vw = int(ctx.get("base_w") or band["w"]); vx = -(vw - band["w"]) / 2      # 넓은 base(분할 인물 축소용)는 가운데만 보이게
    fps_attr = ctx["fps"] if "/" not in ctx["fps"] else f2(eval(ctx["fps"]))
    doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>{esc(plan.get("id", "short"))}</title>
<style>
{font_css}
html,body{{margin:0;padding:0;background:{bg};overflow:hidden}}
#root{{position:relative;width:100%;height:100%;overflow:hidden;background:{bg}}}
#cam{{position:absolute;left:{band['x']}px;top:{band['y']}px;width:{band['w']}px;height:{band['h']}px;overflow:hidden;background:#000}}
#cam-split,#cam-inner{{position:absolute;left:0;top:0;width:100%;height:100%}}
#v-base{{position:absolute;left:{vx}px;top:0;width:{vw}px;height:100%;object-fit:cover;display:block}}
.clip{{position:absolute;left:0;top:0;width:{c.W}px;height:{c.H}px;pointer-events:none}}
.layer{{position:absolute;left:0;top:0;width:{c.W}px;height:{c.H}px;pointer-events:none}}
.inner{{position:absolute;left:0;top:0;width:{c.W}px;height:{c.H}px}}
svg.t{{position:absolute;left:0;top:0;overflow:visible}}
.fl{{background:#FFFFFF;opacity:0}}
</style></head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{D:.3f}" data-fps="{fps_attr}" data-width="{c.W}" data-height="{c.H}">
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>{"".join(c.defs)}</defs></svg>
<div id="cam"><div id="cam-split"><div id="cam-inner"><video id="v-base" src="base.mp4" muted playsinline data-start="0" data-duration="{D:.3f}" data-track-index="0"></video></div></div></div>
{(f'<div id="panel" style="position:absolute;left:0;top:0;width:{c.W}px;height:{split["line"]}px;overflow:hidden">' + chr(10).join(c.panel) + '</div>') if c.panel else ""}
{chr(10).join(c.under)}
{"".join(f'<div id="L-{n}" class="layer">' + chr(10).join(c.layers[n]) + '</div>' + chr(10) for n in ("title", "logo", "cap") if c.layers.get(n))}
{chr(10).join(c.body)}
{chr(10).join(c.audio)}
</div>
<script src="vendor/gsap.min.js"></script>
<script>
const tl = gsap.timeline({{paused: true}});
{chr(10).join(c.js)}
window.__timelines["main"] = tl;
</script>
</body></html>
"""
    with open(os.path.join(bdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(doc)
    with open(os.path.join(bdir, ".generated.md5"), "w") as f:      # Studio 에서 손본 흔적을 build 가 알아채도록
        f.write(hashlib.md5(doc.encode("utf-8")).hexdigest())
    manifest = {"duration": D, "title": title, "elements": c.elements, "faces": ctx["faces"][::2], "warnings": c.warnings,
                "sfx": getattr(c, "sfx_final", ctx["sfx"]),
                "band": band, "canvas": [c.W, c.H]}
    save_json(os.path.join(bdir, "compose.json"), manifest)
    return manifest
