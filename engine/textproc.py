#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
textproc.py — 단어 전사 → 교정 → 자막 큐.

자막 분절기 두 가지(브랜드 captions.chunker 로 선택)
· "v31"     비블 자막 v3.1(2026-07-24 확정, bibl-shorts-automation/shorts_render.py chunk_captions 이식).
            어절 3~8자 리듬, 강결합(수사+단위·관형형+의존명사·부사+피수식어·V-지+않다·보조용언)만 초과 허용,
            연결어미·관형격에서 끊기, 10자 초과 재분할, 문장부호 전면 제거. 타이밍 = 첫 단어 start ~ 끝 단어 end.
· "meaning" 수학쌤 의미 단위(2026-09-08 확정, 이전클라이언트_쇼츠/_workspace/subsplit.py 이식).
            절·구 경계 점수로 나누고 한 줄 980px(강원교육모두 92px 실측), 넘치면 2줄 큐. 글자수 균형 분할 금지.
            원본은 큐 시간을 글자 폭 비례로 나눴지만 여기서는 **단어 타임스탬프**로 정확히 나눈다.
            알려진 약점 보완: '정말로' 고립(부사 끝 '로'를 조사로 오인), '~하라고 | 강조하거든요' 인용 연결어미 분리.

교정: 브랜드 corrections + 쇼츠 fix 를 **단어 열 전체**에 적용한다(두 어절에 걸친 오인식도 처리, 시각은 보존).
"""
import re
from textfit import width as text_width

HANGUL = re.compile(r"[가-힣]")


# ───────────────────────── 교정 ─────────────────────────
def correct_words(words, corrections):
    """words: [{text,start,end,...}]. corrections: {틀린: 맞는} 또는 [[틀린, 맞는], ...] (긴 패턴 먼저 적용).
    공백으로 이은 문자열에서 치환하고, 치환 구간에 걸친 단어들을 새 어절로 다시 나눠 시각을 배분한다."""
    pairs = list(corrections.items()) if isinstance(corrections, dict) else [tuple(p) for p in corrections]
    pairs.sort(key=lambda p: -len(p[0]))
    ws = [dict(w) for w in words]
    for wrong, right in pairs:
        if not wrong or wrong == right:
            continue
        guard = 0
        while guard < 500:
            guard += 1
            text = " ".join(w["text"] for w in ws)
            k = text.find(wrong)
            if k < 0:
                break
            # 문자 위치 → 단어 인덱스
            pos, spans = 0, []
            for i, w in enumerate(ws):
                spans.append((pos, pos + len(w["text"]))); pos += len(w["text"]) + 1
            i0 = next(i for i, (a, b) in enumerate(spans) if b > k)
            i1 = next(i for i, (a, b) in enumerate(spans) if b >= k + len(wrong))
            head = ws[i0]["text"][: k - spans[i0][0]]
            tail = ws[i1]["text"][k + len(wrong) - spans[i1][0]:]
            new = (head + right + tail).split(" ")
            t0, t1 = ws[i0]["start"], ws[i1]["end"]
            n = len(new)
            if n == i1 - i0 + 1:                        # 어절 수가 같으면 원래 시각 유지
                for j, tx in enumerate(new):
                    ws[i0 + j]["text"] = tx
            else:                                       # 어절 수가 바뀌면 구간을 글자 수 비례로 배분
                tot = sum(max(1, len(x)) for x in new); t = t0; rep = []
                for tx in new:
                    d = (t1 - t0) * max(1, len(tx)) / tot
                    rep.append({**ws[i0], "text": tx, "start": round(t, 3), "end": round(t + d, 3)}); t += d
                ws[i0:i1 + 1] = rep
            if right.find(wrong) >= 0:                  # 치환 결과가 다시 걸리는 무한 반복 방지
                break
    return [w for w in ws if w["text"].strip()]


def filter_hallucinated(words, dur):
    """클립 끝을 넘는 꼬리·0.05초 미만 단어·한글/숫자 없는 단독 토큰 제거."""
    out = []
    for w in words:
        if w["start"] >= dur - 0.05 or w["end"] - w["start"] < 0.02:
            continue
        if not re.search(r"[가-힣0-9A-Za-z]", w["text"]):
            continue
        out.append(w)
    return out


# ───────────────────────── 문장 ─────────────────────────
SENT_END = ("요", "다", "죠", "니다", "네요", "거든", "잖아", "래요", "세요", "까요", "냐", "까")


def is_sent_end(words, i, gap_min=0.30):
    """words[i]가 문장 끝인가: 문장부호 또는 종결어미(다/요/죠/까)+뒤 쉼 0.3초 이상 (bibl is_sent_end)."""
    t = words[i]["text"].rstrip()
    if t.endswith((".", "?", "!")):
        return True
    gap = (words[i + 1]["start"] - words[i]["end"]) if i + 1 < len(words) else 9.9
    return t.rstrip(",").endswith(("다", "요", "죠", "까")) and gap >= gap_min


def sentences(words, pause=0.9):
    """단어 열 → 문장(단어 인덱스 범위) 목록. 문장 끝 또는 긴 쉼(pause초)에서 나눈다."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        gap = (words[i + 1]["start"] - w["end"]) if i + 1 < len(words) else 9.9
        if is_sent_end(words, i) or gap >= pause:
            out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


# ───────────────────────── v3.1 (비블) ─────────────────────────
def kchars(s):
    return len(s.replace(" ", ""))


JOSA_END = set("은는이가을를에도만와과로게며요죠다서든까")
CONN_END_CH = set("야서면며자러고나때")
STANDALONE = {"나는", "저는", "내가", "제가", "우리는", "저희는", "이건", "그건", "저건"}
FWD_ONE = {"그", "이", "저", "안", "못", "왜", "또", "좀", "더", "꼭", "막", "딱", "다", "잘",
           "내", "제", "네", "한", "두", "세", "몇", "각", "첫"}
ADV_FWD = {"정말", "진짜", "너무", "가장", "제일", "아주", "매우", "훨씬", "그냥", "계속",
           "바로", "일단", "특히", "결국", "아직", "이미", "거의", "금방", "방금", "절대",
           "전혀", "별로", "항상", "완전", "완전히", "무조건", "반드시", "굉장히", "충분히"}
DET_FWD = {"이런", "그런", "저런", "어떤", "무슨", "모든", "여러", "몇", "새로운", "같은",
           "많은", "작은", "큰", "좋은", "다른", "진짜로"}
_BIND_SUFF = ("하는", "되는", "있는", "없는", "같은", "보는", "가는", "오는", "아닌",
              "라는", "다는", "려는", "위한", "대한", "관한", "않은", "않는", "드는")
_L_ADNOM = ("할", "될", "낼", "볼", "갈", "올", "않을", "싶을", "있을", "없을")
_DEP_HEAD = ("수", "것", "게", "줄", "만큼", "정도", "때문", "뿐", "중", "등")
_AUX = {"있게", "있습니다", "있어요", "있죠", "없습니다", "없어요", "됩니다", "되죠", "돼요", "되고"}
PUNCT_ALL = ".?!,\"'“”‘’…~"
MIN_CUE = 0.16            # 이보다 짧게 뜨는 자막 큐는 이웃 큐와 합친다(chunk_v31 — 2~4프레임 깜빡임 방지)


def _hard_bind(core, nxt_core):
    if not core:
        return False
    if core in FWD_ONE or core in ADV_FWD or core in DET_FWD:
        return True
    if core.endswith(_BIND_SUFF):
        return True
    if core.endswith(_L_ADNOM) and len(core) >= 2:
        return True
    if core.endswith(","):
        return True
    if core[-1].isdigit() or (len(core) >= 2 and core[-1] in "만억천백" and core[-2].isdigit()):
        return True
    if core.endswith("지") and nxt_core[:1] in "않못말":
        return True
    if core.endswith("게") and nxt_core[:1] in "되됐만":
        return True
    if core == "정도":
        return True
    return False


def _binds_back(core):
    base = core.rstrip(".?!,")
    for h in _DEP_HEAD:
        if base == h or (base.startswith(h) and len(base) <= len(h) + 2):
            return True
    return False


def chunk_v31(words, max_chars=8, max_line=9, strip=PUNCT_ALL):
    """비블 자막 v3.1. words: [{text,start,end}] (쇼츠 시각) → [{start,end,text,wi:[단어 인덱스]}]"""
    merged = []                                   # 숫자 병합(3 . 5 / 20 만)
    for i, w in enumerate(words):
        t = w["text"]
        if merged:
            p = merged[-1]
            near = w["start"] - p["end"] < 0.35
            if near and (t.startswith((".", "%")) or (p["text"] and p["text"][-1].isdigit() and t[:1].isdigit())):
                merged[-1] = {**p, "end": w["end"], "text": p["text"] + t, "wi": p["wi"] + [i]}; continue
        merged.append({"start": w["start"], "end": w["end"], "text": t, "wi": [i]})
    caps, cur, closed = [], [], False

    def flush():
        nonlocal cur, closed
        if cur:
            caps.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": " ".join(x["text"] for x in cur),
                         "wi": [j for x in cur for j in x["wi"]]})
        cur, closed = [], False

    for k, w in enumerate(merged):
        t = w["text"].strip(); core = t.rstrip(".?!")
        nxt = merged[k + 1]["text"].strip().rstrip(".?!") if k + 1 < len(merged) else ""
        if cur:
            prev = cur[-1]["text"].strip(); prev_core = prev.rstrip(".?!")
            prev_end = prev_core[-1] if prev_core else ""
            comb = kchars(" ".join(x["text"] for x in cur)) + kchars(t)
            attach = False
            if not prev.endswith((".", "?", "!")):
                if _hard_bind(prev_core, core) and comb <= max_line + 3:
                    attach = True
                elif closed:
                    attach = kchars(core) == 1 and core not in FWD_ONE
                elif _binds_back(core) and comb <= max_line + 1:
                    attach = True; closed = True
                elif comb <= max_chars:
                    if kchars(core) == 1 and core not in FWD_ONE:
                        attach = True
                    elif (prev_core not in STANDALONE and len(prev_core) <= 3 and
                          prev_end not in JOSA_END and prev_end not in CONN_END_CH):
                        attach = True
            if attach:
                cur.append(w)
                if core.rstrip(".?!,") in _AUX:
                    closed = True
            else:
                flush(); cur = [w]
        else:
            cur = [w]
        if t.endswith((".", "?", "!")):
            flush()
    flush()
    for _ in range(3):                             # 10자 초과 재분할 — 경계 시각은 단어 경계를 쓴다(원본은 글자 비율 보간)
        out = []
        for c in caps:
            toks = c["text"].split()
            if kchars(c["text"]) <= max_line + 1 or len(toks) < 2:
                out.append(c); continue
            best, score = None, -1e9
            for i in range(1, len(toks)):
                a, b = kchars(" ".join(toks[:i])), kchars(" ".join(toks[i:]))
                if a < 2 or b < 2:
                    continue
                sc = -abs(a - b) - 3 * max(0, max(a, b) - max_line)
                tail = toks[i - 1].rstrip(".?!,")
                if tail[-1:] in JOSA_END or tail[-1:] in CONN_END_CH:
                    sc += 6
                if sc > score:
                    best, score = i, sc
            if not best:
                out.append(c); continue
            wi = c["wi"]
            if len(wi) == len(toks):                   # 토큰 = 단어: 실제 단어 경계 시각
                wa, wb = wi[:best], wi[best:]
                out.append({"start": c["start"], "end": words[wa[-1]]["end"], "text": " ".join(toks[:best]), "wi": wa})
                out.append({"start": words[wb[0]]["start"], "end": c["end"], "text": " ".join(toks[best:]), "wi": wb})
            else:                                       # 숫자 병합이 섞인 경우만 글자 비율 보간
                ratio = sum(len(x) + 1 for x in toks[:best]) / (len(c["text"]) + 1)
                mid = c["start"] + (c["end"] - c["start"]) * ratio
                out.append({"start": c["start"], "end": mid, "text": " ".join(toks[:best]), "wi": wi})
                out.append({"start": mid, "end": c["end"], "text": " ".join(toks[best:]), "wi": wi})
        if [x["text"] for x in out] == [x["text"] for x in caps]:
            caps = out
            break
        caps = out
    # 한 글자 큐 정리(0.2초 안팎 깜빡임): 앞으로 붙는 말(그·안·꼭·나·너 …)은 다음 큐에, 아니면 앞 큐에 붙인다.
    # 합쳐서 max_line+1 자 이내이고 쉼이 0.35초 미만일 때만. (bibl075: '할 / 때', 대명사 '나'를 연결어미로 오인해 혼자 남음)
    fwd = FWD_ONE | {"나", "너", "난", "넌"}
    i = 0
    while i < len(caps):
        c = caps[i]; core = c["text"].strip().rstrip(".?!,")
        if kchars(core) == 1 and len(caps) > 1:
            nx = caps[i + 1] if i + 1 < len(caps) else None
            pv = caps[i - 1] if i > 0 else None
            ok_n = nx is not None and nx["start"] - c["end"] < 0.35 and kchars(c["text"] + nx["text"]) <= max_line + 1 \
                and not c["text"].endswith((".", "?", "!"))
            ok_p = pv is not None and c["start"] - pv["end"] < 0.35 and kchars(pv["text"] + c["text"]) <= max_line + 1 \
                and not pv["text"].endswith((".", "?", "!"))
            if ok_n and (core in fwd or not ok_p):
                caps[i + 1] = {"start": c["start"], "end": nx["end"], "text": c["text"] + " " + nx["text"], "wi": c["wi"] + nx["wi"]}
                del caps[i]; continue
            if ok_p:
                caps[i - 1] = {"start": pv["start"], "end": c["end"], "text": pv["text"] + " " + c["text"], "wi": pv["wi"] + c["wi"]}
                del caps[i]; continue
        i += 1
    # 아주 짧은 큐(MIN_CUE 미만 — 빠른 말의 '그러니까'·'예를' 0.08~0.14초, 2~4프레임 깜빡임)도 같은 식으로 다음 큐에(문장 끝이면 앞 큐에).
    # 합쳐서 max_line+3 자 이내·쉼 0.35초 미만일 때만. (2026-09-30 bibl_daebon d3 '그러니까' 0.08초 ×2)
    i = 0
    while i < len(caps):
        c = caps[i]
        if c["end"] - c["start"] < MIN_CUE and len(caps) > 1:
            nx = caps[i + 1] if i + 1 < len(caps) else None
            pv = caps[i - 1] if i > 0 else None
            ok_n = nx is not None and nx["start"] - c["end"] < 0.35 and kchars(c["text"] + nx["text"]) <= max_line + 3 \
                and not c["text"].endswith((".", "?", "!"))
            ok_p = pv is not None and c["start"] - pv["end"] < 0.35 and kchars(pv["text"] + c["text"]) <= max_line + 3 \
                and not pv["text"].endswith((".", "?", "!"))
            if ok_n:
                caps[i + 1] = {"start": c["start"], "end": nx["end"], "text": c["text"] + " " + nx["text"], "wi": c["wi"] + nx["wi"]}
                del caps[i]; continue
            if ok_p:
                caps[i - 1] = {"start": pv["start"], "end": c["end"], "text": pv["text"] + " " + c["text"], "wi": pv["wi"] + c["wi"]}
                del caps[i]; continue
        i += 1
    res = []
    for c in caps:
        txt = " ".join(strip_punct(tidy_numbers(c["text"]), strip).split())
        if txt:
            res.append({**c, "text": txt, "lines": [txt]})
    return res


# ───────────────────────── meaning (수학쌤) ─────────────────────────
NO_SPLIT_BEFORE = ("같은", "같이", "같아", "같습", "같거", "같네", "같죠", "때문", "정도", "위해", "위한", "대한", "대해", "통해", "관한",
                   "라고", "이라고", "라는", "이라는", "있으", "있어", "있거", "있고", "있을", "있는", "있잖", "없으", "없어", "없는", "없거",
                   "보고", "보면", "보는", "볼", "싶", "않", "못하", "말고", "마시고", "마세요", "만큼", "대로")
_DEP_RE = re.compile(r"^(게|것|거|건|걸|수|데|때|뿐|등|중|줄|채|척|듯|지)(은|는|이|가|을|를|도|에|의|에서|으로|로|만|이라도|라도|처럼|이지|만큼|니까|예요|죠|고|야|라면|라고|인데|들|들을|들이|들은|든요|든|잖아요|잖아)?$")
NO_SPLIT_AFTER = {"그", "이", "저", "그런", "이런", "저런", "어떤", "무슨", "몇", "여러", "한", "두", "세", "네", "다섯", "새", "각", "매", "전", "모든",
                  "안", "못", "더", "덜", "잘", "다", "또", "좀", "꼭", "딱", "막", "정말", "진짜", "되게", "너무", "아주", "제일", "가장", "그냥",
                  "계속", "다시", "바로", "조금", "많이", "약간", "거의", "항상", "늘", "자주", "먼저", "이미", "아직", "금방", "곧",
                  "같은", "비슷한", "똑같은", "어려운", "쉬운", "새로운", "틀린", "맞춘", "맞은", "틀렸던", "맞췄던", "틀리는", "보편적인", "수준", "높은",
                  "내", "제", "본인", "자기", "그중에서", "시중에", "내가", "제가", "저는", "나는", "본인이", "자기가", "우리가", "저희가",
                  # 보완(2026-09-24): '-로' 부사를 조사로 오인해 혼자 남던 사례
                  "정말로", "진짜로", "실제로", "완전히", "절대로", "특히", "훨씬", "굉장히", "엄청", "되게끔",
                  "절대", "무조건", "반드시", "완전", "전혀", "별로", "매우", "충분히", "오히려", "비교적"}
LEAD_WORDS = {"그래서", "근데", "그리고", "그러면", "그랬을", "사실", "그냥", "또", "이렇게", "그래도", "하지만", "결국", "그러니까", "일단", "우선", "냉정하게", "저는", "제가"}
CONN_END = ("고", "해서", "어서", "아서", "여서", "라서", "면서", "돼서", "봐서", "와서", "가서", "려서", "져서", "셔서", "서서", "면", "는지", "은지", "을지", "는데", "은데", "인데", "니까", "니깐", "지만", "거나", "든지", "든가", "라고", "다고", "하고",
            "려고", "다가", "도록", "듯이", "길래", "더니", "자마자", "라도", "더라도", "한데", "테니까", "테니", "면은", "다면")
PARTICLE_END = ("은", "는", "이", "가", "을", "를", "에", "에서", "으로", "로", "도", "와", "과", "의", "한테", "에게", "보다", "부터", "까지", "만", "이랑", "랑", "께", "처럼", "마다", "밖에", "조차", "이나")
DEP_NOUN = {"게", "것", "건", "걸", "거", "수", "데", "때", "중", "등", "뿐", "줄", "만큼", "대로"}
NOUN_EXC = {"화면", "측면", "반면", "장면", "라면", "최고", "광고", "재고", "창고", "참고", "사고", "유형서", "개념서", "문제집", "교과서", "참고서", "교재", "정도", "제도", "태도", "속도", "난이도"}
QUOTE_END = ("라고", "다고", "냐고", "자고", "라는", "다는", "이라고")
SAY_HEAD = ("하", "해", "했", "한", "할", "합", "말", "강조", "얘기", "이야기", "생각", "물어", "묻", "부르", "불러", "들었", "들어", "설명", "표현")


def _verbal_seo(w):
    if len(w) < 2 or not w.endswith("서"):
        return False
    c = ord(w[-2]) - 0xAC00
    if c < 0 or c > 11171:
        return False
    return (c // 28) % 21 in {0, 4, 6, 1, 5, 9, 14, 10, 15, 11, 16}


def _vowel_before(w, k=1):
    """w[-1-k] 음절의 중성 번호(없으면 None)"""
    if len(w) < k + 1:
        return None
    c = ord(w[-1 - k]) - 0xAC00
    return (c // 28) % 21 if 0 <= c <= 11171 else None


VERBAL_DO = ("어도", "아도", "해도", "와도", "워도", "봐도", "돼도", "져도", "쳐도", "려도", "여도", "줘도", "둬도", "러도")


def _verbal_do(w):
    """-아도/-어도/-해도 (연결어미 '도')인가. 받침 있는 명사+조사(성취감도·정도·속도)는 아니다 → 흔한 어미 꼴만 인정."""
    return len(w) >= 3 and w.endswith(VERBAL_DO) and w not in NOUN_EXC


ADNOMINAL = ("하는", "되는", "있는", "없는", "했던", "하던", "되던", "힘든", "중요한", "필요한", "다른", "많은", "좋은", "싫은",
             "나쁜", "적은", "큰", "작은", "쉬운", "어려운", "비슷한", "똑같은", "새로운", "놀라운", "대단한", "이런", "그런")
BANMAL_END = ("같아", "싶어", "많아", "있어", "없어", "몰라", "알아", "좋아", "싫어", "했어", "됐어", "거야", "이야", "잖아",
              "거든", "하지", "했지", "있지", "겠지", "는걸", "할게", "줄게", "볼게", "해", "봐", "돼", "래", "네")


def score_break(prev, nxt):
    """prev|nxt 사이에서 끊는 선호도. 0=금지 1=약 2=구 3=절 4=문장"""
    p = prev.rstrip(",.!?")
    if prev in NO_SPLIT_AFTER or p in NO_SPLIT_AFTER:
        return 0
    if nxt.startswith(NO_SPLIT_BEFORE) or _DEP_RE.match(nxt.rstrip(",.!?")):
        return 0
    if p.endswith(("을", "를")) and nxt.startswith(("하", "해", "할", "했", "합")):
        return 0
    if p.endswith(QUOTE_END) and nxt.startswith(SAY_HEAD):       # 보완: 인용 연결어미 + 말하기 동사
        return 0
    if nxt.startswith(("하고", "하며", "하면서", "하는", "하니", "하던", "하길", "하면")) and p.endswith(("다", "나", "까", "지", "야", "래", "자", "네")):
        return 0                                                  # 보완: '안 되나 보다 | 하고' 인용형(생각·말)
    if p.endswith("지") and nxt[:1] in "않못말마":                  # 보완: V-지 않다/못하다/말다(포기하지 | 말라고)
        return 0
    if p.endswith("게") and nxt.startswith(("되", "됐", "돼", "만들", "해", "하")):
        return 0                                                  # -게 되다/하다
    if p.replace(",", "").isdigit():                               # 숫자 + 단위
        return 0
    if p.endswith(ADNOMINAL) and len(p) >= 2:                      # 보완: 관형형(힘든·중요한·하는) + 꾸밈받는 말
        return 0
    if prev.endswith((".", "!", "?")):
        return 4
    if prev.endswith(","):
        if p.replace(".", "").isdigit() or (p[:1].isdigit() and nxt[:1].isdigit()):
            return 0                                              # "2, 3등급" · "5등급, 6등급은" 숫자 나열은 한 덩어리
        return 3
    if p in LEAD_WORDS:
        return 1
    if p in DEP_NOUN:
        return 2
    if p.endswith(("에서", "로써", "으로서", "에게서")):
        return 2
    if p.endswith(("는데", "인데", "은데")):
        return 3
    if p.endswith(SENT_END):
        return 4
    if p.endswith(BANMAL_END) and len(p) >= 2:                   # 보완: 반말 종결(같아·싶어·거야…) — 화자가 반말인 편
        return 3
    if p.endswith("수록") or _verbal_do(p):                        # 보완: -ㄹ수록 · -아도/-어도 연결
        return 3
    if (p.endswith(CONN_END) or _verbal_seo(p)) and p not in NOUN_EXC:
        return 3
    if p.endswith(PARTICLE_END):
        return 2
    if len(p) <= 1:
        return 0
    return 1


class MeaningSplitter:
    """subsplit.py 알고리즘을 단어 인덱스 단위로 재구성. 폭은 브랜드 자막 폰트로 실측."""

    def __init__(self, font, size, line_max, short_px=260):
        self.font, self.size, self.line_max, self.short_px = font, size, line_max, short_px

    def w(self, toks):
        return text_width(self.font, " ".join(toks), self.size)

    def fits(self, toks):
        return self.w(toks) <= self.line_max

    def units(self, toks, min_score):
        out, cur = [], []
        for i, t in enumerate(toks):
            cur.append(i)
            if i + 1 < len(toks) and score_break(toks[i], toks[i + 1]) >= min_score:
                out.append(cur); cur = []
        if cur:
            out.append(cur)
        return out

    def merge_short(self, toks, units):
        res, i = [], 0
        units = [list(u) for u in units]
        while i < len(units):
            u = units[i]; ut = [toks[j] for j in u]
            if len(u) == 1 and ut[0].rstrip(",.!?") in LEAD_WORDS and i + 1 < len(units):
                units[i + 1] = u + units[i + 1]; i += 1; continue           # 접속어는 다음 절 머리로
            if res and self.w(ut) < self.short_px:
                res[-1] = res[-1] + u; i += 1; continue                     # 짧은 꼬리(없고·해서)는 앞 절에
            if len(u) == 1 and self.w(ut) < self.short_px and i + 1 < len(units):
                units[i + 1] = u + units[i + 1]; i += 1; continue
            res.append(u); i += 1
        return res

    def best_inner(self, toks, idx, need_fit=True):
        best, bs, bimb = None, -1, 9e9
        for k in range(1, len(idx)):
            s = score_break(toks[idx[k - 1]], toks[idx[k]])
            if s == 0:
                continue
            a = [toks[j] for j in idx[:k]]; b = [toks[j] for j in idx[k:]]
            if need_fit and not (self.fits(a) and self.fits(b)):
                continue
            imb = abs(self.w(a) - self.w(b))
            if s > bs or (s == bs and imb < bimb):
                best, bs, bimb = k, s, imb
        return best

    def split_unit(self, toks, idx):
        """→ [[줄1 인덱스, (줄2 인덱스)], ...] 큐 목록"""
        if self.fits([toks[j] for j in idx]):
            return [[idx]]
        k = self.best_inner(toks, idx, True)
        if k is not None:
            return [[idx[:k], idx[k:]]]
        k = self.best_inner(toks, idx, False)
        if k is None:
            return [[idx]]
        return self.split_unit(toks, idx[:k]) + self.split_unit(toks, idx[k:])

    def split(self, toks):
        idx = list(range(len(toks)))
        if not toks:
            return []
        if self.fits(toks):
            return [[idx]]
        units = self.merge_short(toks, self.units(toks, 3))
        pieces = []
        for u in units:
            pieces.extend(self.split_unit(toks, u))
        out = []
        for pc in pieces:                          # 같은 문장 안 1줄 조각 둘 → 2줄 큐
            if out and len(out[-1]) == 1 and len(pc) == 1:
                last = [toks[j] for j in out[-1][0]]; cur = [toks[j] for j in pc[0]]
                if (self.fits(last) and self.fits(cur) and not last[-1].rstrip(",").endswith(SENT_END)
                        and not last[-1].endswith((".", "!", "?"))):
                    out[-1] = [out[-1][0], pc[0]]; continue
            out.append(pc)
        return out


DANGLE = LEAD_WORDS | {"결국에", "결국", "왜냐하면", "그러면", "그럼", "그니까", "그러니까", "아니면", "또는", "근데", "그런데"}


def phrase_units(words, segments):
    """단어 → 말 묶음(전사 문장 = Whisper 구간). 수학쌤 확정 파이프라인은 SRT 큐(=전사 구간)를 단위로 나눴다.
    한 구간에 문장이 둘이면 문장 끝에서 더 나누고, 구간이 없으면 문장 단위로 대체."""
    if not segments:
        return sentences(words)
    segs = [s for s in segments if not s.get("drop")]
    def seg_of(w):
        t = w.get("src_start", w["start"]) + 0.02
        for k, s in enumerate(segs):
            if s["start"] - 0.05 <= t < s["end"] + 0.02:
                return k
        return None
    units, cur, cur_k = [], [], "∅"
    for i, w in enumerate(words):
        k = seg_of(w)
        if cur and (k != cur_k or (cur and "piece" in w and words[cur[-1]].get("piece") != w.get("piece")
                                   and words[cur[-1]]["end"] < w["start"] - 0.25)):
            units.append(cur); cur = []
        cur.append(i); cur_k = k
        if is_sent_end(words, i) and i + 1 < len(words):
            units.append(cur); cur = []; cur_k = "∅"
    if cur:
        units.append(cur)
    return [u for u in units if u]


def chunk_meaning(words, font, size, line_max, strip_end=".", segments=None):
    """수학쌤 의미 단위. 말 묶음마다 분할기를 돌리고 큐 시각은 단어 타임스탬프로 정한다.
    후처리: 큐 끝에 매달린 접속어(결국에·그래서…)는 다음 큐 머리로, 2음절 이하 외톨이 큐는 이웃과 합친다."""
    sp = MeaningSplitter(font, size, line_max)
    groups = []                                            # 큐 = 단어 인덱스 목록
    for unit in phrase_units(words, segments):
        toks = [words[i]["text"] for i in unit]
        for cue in sp.split(toks):
            groups.append([unit[j] for ln in cue for j in ln])
    core = lambda i: words[i]["text"].rstrip(",.!?")
    for k in range(len(groups) - 1):                      # 매달린 접속어 → 다음 큐
        g = groups[k]
        if len(g) > 1 and core(g[-1]) in DANGLE and not words[g[-1]]["text"].endswith((".", "?", "!")):
            groups[k + 1] = [g[-1]] + groups[k + 1]; groups[k] = g[:-1]
    merged = []
    for g in groups:                                      # 외톨이 큐(2음절 이하·한 단어) 합치기
        txt = "".join(core(i) for i in g)
        if merged and (len(txt) <= 2 or (len(g) == 1 and sp.w([words[g[0]]["text"]]) < 200)) \
                and not words[merged[-1][-1]]["text"].endswith((".", "?", "!")):
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    if len(merged) > 1 and len("".join(core(i) for i in merged[0])) <= 2:
        merged[1] = merged[0] + merged[1]; merged = merged[1:]
    fits2 = lambda g: len(sp.split([words[i]["text"] for i in g])) == 1   # 합쳐도 한 큐(최대 2줄)에 들어가나
    k = 0
    while k < len(merged):                                # 한 단어짜리 큐: 앞 큐나 뒤 큐에 붙여 2줄 안에 들어가면 합친다
        g = merged[k]
        if len(g) == 1 and len(merged) > 1:
            fin = words[g[0]]["text"].endswith((".", "?", "!"))
            if k > 0 and not words[merged[k - 1][-1]]["text"].endswith((".", "?", "!")) and fits2(merged[k - 1] + g):
                merged[k - 1] = merged[k - 1] + g; merged.pop(k); continue
            if not fin and k + 1 < len(merged) and fits2(g + merged[k + 1]):
                merged[k + 1] = g + merged[k + 1]; merged.pop(k); continue
        k += 1
    cues = []
    for g in merged:
        toks = [words[i]["text"] for i in g]
        for cue in sp.split(toks):                         # 합친 뒤 2줄을 넘으면 다시 나눈다
            wi = [g[j] for ln in cue for j in ln]
            lines = []
            for ln in cue:
                t = tidy_numbers(" ".join(toks[j] for j in ln))
                lines.append(t.rstrip(strip_end).strip() if strip_end else t)
            lines = [l for l in lines if l]
            if lines:
                cues.append({"start": words[wi[0]]["start"], "end": words[wi[-1]]["end"], "lines": lines,
                             "text": " ".join(lines), "wi": wi})
    return cues


# ───────────────────────── 공통 후처리 ─────────────────────────
def tidy_numbers(t):
    """전사 토큰 사이 공백 정리: '5 %' → '5%', '8 .1' → '8.1', '1 ,000' → '1,000'."""
    t = re.sub(r"(\d)\s+%", r"\1%", t)
    t = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", t)
    return re.sub(r"(\d)\s*,\s*(\d{3})(?!\d)", r"\1,\2", t)


def strip_punct(t, chars):
    """문장부호 제거 — 단, 숫자 사이의 소수점·천 단위 쉼표는 남긴다('8.1%'가 '81%'가 되던 사고)."""
    keep = {}
    def hold(m):
        k = f"\x00{len(keep)}\x00"; keep[k] = m.group(0); return k
    t = re.sub(r"\d[.,]\d", hold, t)
    t = t.translate(str.maketrans("", "", chars))
    for k, v in keep.items():
        t = t.replace(k, v)
    return t
def two_lines_v31(text, font, size, max_w, josa_bonus=200):
    """v3.1 렌더 규칙: 폭 max_w 이하이거나 공백 없으면 1줄, 넘으면 폭 차 최소 + 조사 끝 보너스로 2줄."""
    if text_width(font, text, size) <= max_w or " " not in text:
        return [text]
    toks = text.split(); best, diff = 1, 1e9
    for i in range(1, len(toks)):
        a, b = " ".join(toks[:i]), " ".join(toks[i:])
        d = abs(text_width(font, a, size) - text_width(font, b, size))
        if toks[i - 1].rstrip(".?!,")[-1:] in "은는이가을를에도로와과의":
            d -= josa_bonus
        if d < diff:
            best, diff = i, d
    return [" ".join(toks[:best]), " ".join(toks[best:])]


def fill_gaps(cues, max_gap, total):
    """쉼이 max_gap 이하면 앞 큐를 다음 큐 시작까지 늘린다(깜빡임 방지). max_gap=0 이면 그대로(v3.1)."""
    for a, b in zip(cues, cues[1:]):
        if 0 < b["start"] - a["end"] <= max_gap:
            a["end"] = b["start"]
        if a["end"] > b["start"]:
            a["end"] = b["start"]
    if cues:
        cues[-1]["end"] = min(total, cues[-1]["end"])
    return cues


def split2(hook):
    """제목 한 줄 → 균형 2줄(비블 split2: 비공백 글자수 차 최소, 동점이면 앞쪽)."""
    if " " not in hook.strip():
        return [hook.strip()]
    ws = hook.split(); best = None
    for i in range(1, len(ws)):
        a, b = " ".join(ws[:i]), " ".join(ws[i:]); d = abs(kchars(a) - kchars(b))
        if best is None or d < best[0]:
            best = (d, a, b)
    return [best[1], best[2]]
