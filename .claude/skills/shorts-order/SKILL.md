---
name: shorts-order
description: 쇼츠 요청(한 줄 주문·스타일 단어·6칸 주문서·수정 지시)을 short.json 설정으로 정확히 옮기는 규칙 — HyperFrames 공식 Prompt Guide(6파트 뼈대·스펙 다이얼·단어표·편집 동사·반복 원칙)를 쇼츠 편집에 적용한 것. 쇼츠 주문서를 해석할 때, "부드럽게/펀치인/뿅/노래방 자막/마커" 같은 말을 설정으로 바꿀 때, "0.5초 늦게·제목 1줄 바꿔·줌 빼줘·나머지는 그대로" 같은 수정 지시를 반영할 때, 사용자가 프롬프트를 어떻게 써야 하는지 물을 때 반드시 사용한다. shorts-agent·shorts-editor 가 함께 쓴다.
---

# 주문 해석 — Prompt Guide 를 쇼츠에

사용자용 요약은 `쇼츠_주문서.md`, 가이드 장별 근거는 `references/prompt-guide-map.md`. 여기에는 **에이전트가 말을 설정으로 옮기는 규칙**만 둔다.

## 1. 주문의 모양 (Two prompt shapes)
쇼츠는 항상 **warm start**(원본 영상·전사라는 구체적 재료가 있다) — 에이전트가 요약·선택과 제작을 한 흐름으로 한다. 재료 없이 "쇼츠 스타일 영상 만들어줘"(cold start)는 이 하네스가 아니라 `/hyperframes` 워크플로우로 보낸다.

## 2. 6칸 뼈대 → 어디에 들어가나
| 칸 | 가이드 | 들어가는 곳 | 비면 |
|---|---|---|---|
| [경로] | route(slash command) | shorts-agent 진입 | 쇼츠 요청이면 자동 |
| [스펙] | spec(길이·해상도) | 프로젝트 전체 값은 BRIEF.md(브랜드·편수·길이), **그 편만의 값**(이 편 모션 레벨 2)은 short.json `motion` | 인터뷰(추천값 먼저) |
| [구간] | — | `segments[].in/out` (말 기준이면 `./shorts.sh words` 로 초 변환), `skip` | scout 발굴 |
| [연출] | beats(타임스탬프) | `beats[]` — **at_word 우선** | 모션 레벨에 맞춰 editor 가 설계 |
| [문구] | copy(따옴표) | `title.lines`, `beats[].text` — 따옴표 안은 그대로. **사용자가 따옴표로 준 제목 = 승인**(`title.status: approved`) | editor 가 A~D 제안 |
| [기법] | technique | `captions.style/emphasis`, `motion.feel`, `beats[].sfx/enter` | 브랜드 기본 |
| [금지] | negatives | `negatives{}` + 설계 제약 | 브랜드 안전 규칙 |

**연출 한 줄의 5칸** (가이드 beat formula) — 요소·움직임·위치·스타일·시점:
"'3회독' 말할 때(시점) 키워드 카드(요소) "개념원리 3회독"(문구)이 통통 튀며(움직임) 아래쪽에(위치) 빨간 밴드로(스타일)"
→ `{"type":"keyword","at_word":"3회독","text":"개념원리 3회독","feel":"bouncy","enter":"pop"}` (위치·스타일은 브랜드 zone·kw_style 기본). 말하지 않은 칸은 브랜드 기본값 — 기본값이 마음에 안 들 위험이 크면 사용자에게 한 번 확인.

## 3. 스펙 다이얼 — 얼마나 말했나에 따라
1. **분위기 말**("다이내믹하게", "깔끔하게") → 모션 레벨·feel 만 정하고 나머지는 브랜드 기본 + editor 판단.
2. **스타일 토큰**(단어표의 말, 색·크기 수치) → `engine/vocab.json` 매핑 그대로. 해석하지 않는다.
3. **정밀 지시**(초·단어·문구·크기) → 그대로 옮기고, 못 옮기는 값(엔진이 지원 안 함)은 솔직히 말하고 가장 가까운 것을 제안.
밀도가 높을수록 결과가 사용자 머릿속과 가깝다. 밀도가 낮으면 **추측을 보고에 드러낸다**("카드 위치는 브랜드 기본(자막 아래)으로 했습니다").

## 4. 단어표 → 설정 (`engine/vocab.json` 이 원본)
- 움직임 느낌 `motion.feel` / `beats[].feel`: 부드럽게 smooth(power2.out) · 스냅 snappy(power4.out) · 통통 bouncy(back.out) · 탄력 springy · 극적 dramatic(expo.out) · 잔잔 dreamy(sine.inOut)
- 모션 레벨 `motion.level`: 0 템플릿 그대로 / 1 핵심 1~2곳·효과음 없음 / 2 후킹·반전·결론에 줌·카드·효과음
- 카메라 `beats[type=zoom].style`: 펀치인 punch(1.12, 0.12초) · 천천히 밀기 push(1.06, 조각 끝까지)
- 자막 `captions.style`: 기본 brand · 팝 pop · 노래방 karaoke · 하이라이트 박스 highlight · 페이드 fade
- 강조 `captions.emphasis` + `emphasis_mode`: 색 color · 마커 marker (구절 가능: "두 권을")
- 그래픽 `beats[].type`: keyword · number · compare · list · quote · flash
- 효과음 `beats[].sfx` / `sfx[]`: 뿅 pop · 휙 whoosh · 딩 ding · 쿵 impact · 딸깍 click · 반짝 sparkle · 뚜둥 riser …
- 금지 `negatives`: `no_sfx` · `no_audio`(소리 전부) · `no_bgm` · `no_graphics` · 사진 금지(원래 규칙)
없는 이름을 만들지 않는다(가이드: "Don't invent names"). 표에 없는 말은 가장 가까운 항목을 제안하고 확인.

## 5. 가이드의 '자주 고치는 문장' — 쇼츠판
| 이렇게 오면 | 이렇게 옮긴다 | 이유 |
|---|---|---|
| "4초에 카드 사라지고 숫자 등장" | 앞 카드 t1 = 다음 t0 − 0.08 | 같은 시각 두 사건은 겹친다(엔진도 자동 보정) |
| "카드 계속 떠 있게" | dur 을 그 말이 끝날 때까지(`until_word`), 무한 금지 | 멈춘 화면은 싸 보인다 — 말이 끝나면 내린다 |
| "0에서 530등까지 올라가게" | `number` 기본은 "~까지"(from 0 또는 자리수가 같은 값). 사용자가 from 을 정확히 말하면 그대로. 단위가 숫자에 붙으면 `suffix`("10문제"), 숫자 위 작은 설명이면 `label` | 형식이 안 맞는 숫자는 어색하게 시작 |
| 따옴표 없는 문구 | 다듬어도 되는 초안으로 보고 제안, 확정 전 확인 | 따옴표 = 그대로, 없음 = 작성 요청 |
| "외부 소스 쓰지 마" | "사진·스톡 이미지 안 씀"으로 해석하고 확인 | 모호한 금지 |
| "나레이션 없이" | 쇼츠는 화자 음성이 본체 — "BGM·효과음 없이"인지 확인 | '나레이션 없음' ≠ '무음' |

## 6. 수정 지시 → 최소 변경 (편집 동사표)
| 말 | 바꾸는 필드 | 절대값으로 |
|---|---|---|
| "'냉정하게'부터 시작" | `segments[0].in` (단어 시각표의 그 단어 start) | refine 이 소리 골짜기로 다시 맞춤 |
| "끝을 '좋겠어'까지" | `segments[-1].out` | 〃 |
| "'아까 말했듯이' 빼줘" | `segments[k].skip += ["아까 말했듯이"]` | 소리 골짜기에서 자동 컷 |
| "제목 1줄 \"…\"" | `title.lines[0]` 그대로 | status 는 사용자가 확정하면 approved |
| "카드 0.5초 늦게 / 2초 더" | `beats[k].offset += 0.5` / `dur` | 초 단위. until_word 카드는 끝이 고정이라 짧아짐 — 길이도 유지하려면 dur 로 바꿔 보고 |
| "카드 글자 110px / 위로" | `beats[k].size` / `zone: "alt"` | px. size 는 최대값 — 자리보다 길면 엔진이 줄이고 `!` 로 알림, 그땐 문구를 줄이자고 제안 |
| "자막 '후월' → '수월'" | `fix` 에 추가(편 한정) 또는 brands corrections(반복 오인식) | 교정은 사전에 쌓는다 |
| "3번째 자막 줄바꿈 이상" | `captions.edit.json` 로 복사해 그 큐만 수정 | 이후 build 는 edit 우선 |
| "줌 빼줘" | 그 beat 삭제 | — |
| "더 스냅있게" | 그 비트 `feel: snappy` 하나만 | 한 장면씩 |
| "나머지는 그대로" | 다른 필드 절대 변경 금지 | freeze clause |
**규칙**: 한 번에 한 가지(여러 개면 순서대로 반영하며 build 로 각각 확인, draft 는 마지막 한 번, 목록 보고) · 상대 표현("조금")은 수치로 바꾸고 보고에 적는다 · 잘 된 것은 건드리지 않는다 · 계속 틀어지면 그 요소를 가장 단순하게 되돌렸다가 하나씩 다시 얹는다(strip, then re-layer).

## 7. 좋은 움직임의 기준 (가이드 'Motion that reads premium'·'Storyboards')
- **움직임은 주장이다**: 숫자가 실제로 바뀌면 카운트, 반전이면 펀치인, 목록을 말하면 하나씩. 이유 없는 흔들림·장식 금지 — 장식 넷보다 이유 있는 하나.
- **말하는 순간에 뜬다**(VO-paced): 비트는 at_word. 화자가 그 말을 하기 전에 먼저 보이면 스포일러.
- **에너지 대비**: 한 쇼츠에 '큰 순간'(펀치인+효과음+카드)은 하나 — 보통 결론이나 반전. 나머지는 조용히.
- **두 색 규율**: 브랜드 강조색 하나. 더 강조하려면 크기·굵기.
- **숨 쉴 틈**: 그래픽 사이 최소 0.8초 빈 화면(모션 2 도 동일).

## 8. 렌더 말 (가이드 'Rendering and output')
"빨리 보여줘/확인용" → `./shorts.sh draft` · "최종/납품" → `render` 한 번. 4K·60fps 요청은 쇼츠에 이득이 없다고 설명(플랫폼이 재인코딩) — 그래도 원하면 따른다.

## 9. 소리 말 (가이드 'Audio effects')
증상으로 받는다: "소리가 작아" → 음량(LUFS) 확인, "효과음이 시끄러워" → 그 효과음 vol, "BGM 이 목소리를 덮어" → BGM 을 목소리보다 18dB 아래(목표값을 말하고 적용). 없는 기능(디에서 등)은 없다고 말한다.

## 10. Studio 에서 가리키기
사용자가 Studio(`./shorts.sh preview`)에서 요소를 클릭하고 "이거"라고 하면 `node_modules/.bin/hyperframes preview <build 폴더> --selection --json` 으로 선택 요소 id 를 읽는다: `title`→제목, `capN`→N번째 자막(captions.auto.json 순서), `gN`→short.json `beats[N]`, `v-base`→영상. 그 필드를 short.json 에서 고친다.

## 11. 같은 스타일로 여러 편 (가이드 'Variables and templating')
"나머지도 같은 스타일로" → 첫 편 short.json 의 captions·motion·beats 규칙을 템플릿으로 삼아 구간·문구만 바꾼 새 short.json 을 만들고 `./shorts.sh all <p>` 로 일괄. 브랜드 템플릿(brands/*.json)은 가이드의 frame.md 처럼 색·글꼴의 진실이고, 배치는 영상에 맞게 에이전트가 짠다.
