---
name: shorts-edit
description: 쇼츠 한 편을 short.json 으로 편집하고 HyperFrames 로 빌드·렌더하는 방법 — 자막 스타일·강조, 그래픽 비트(키워드 카드·숫자 카운트·비교·체크리스트·인용·플래시), 줌(펀치인·푸시), 효과음, 모션 레벨별 설계 기준, 브랜드 템플릿, Studio 미리보기, 빌드 경고 처리. 쇼츠 편집·"카드 넣어"·"줌 넣어"·"자막 스타일"·"효과음"·"모션 더/덜"·"다시 빌드/렌더"·"draft" 요청과 쇼츠 에이전트 편집 단계에서 반드시 사용(shorts-editor 의 작업 규칙).
---

# 쇼츠 편집 (short.json → HyperFrames)

## 1. 흐름
```
short.json ──build──▶ build/ (base.mp4 + index.html + fonts + sfx)  ──draft──▶ out/<id>_draft.mp4 (빠른 확인)
                         │ lint(오류 0 이어야)                         ──render─▶ out/<name>.mp4 + _sheet.jpg
                         └ captions.auto.json · resolved.json · compose.json(QA 용 글자 상자)
```
- `./shorts.sh build <p>/<id>` — 컷이 안 바뀌면 base.mp4 재사용(몇 초). 컷이 바뀌면 base 다시(원본 4K 기준 30~60초).
- `./shorts.sh draft` 는 확인용(`out/<id>_draft.mp4`·`_draft_sheet.jpg`, QA·납품 대상 아님), `render` 는 최종(브랜드 규격 재인코딩 + 원음 유지, `out/<name>.mp4`·`_sheet.jpg`). 42초 쇼츠 렌더 ≈ 36초.
- 여러 변경을 한꺼번에 받으면: 하나씩 short.json 에 반영하며 **build 로 매번 확인**(수 초)하고, **draft 는 끝에 한 번**(수십 초). 보고는 바꾼 필드 목록.
- `./shorts.sh preview <p>/<id>` — Studio(http://localhost:3002). 사용자가 요소를 클릭하면 `node_modules/.bin/hyperframes preview <build> --selection --json` 로 읽는다. **Studio 에서 고친 값은 short.json 으로 옮긴다** — build 는 손본 index.html 을 덮어쓰기 전에 멈춘다(`--force` 는 버려도 될 때만).
- 스키마 전체: `references/short-schema.md`. 브랜드 필드: `references/brand-profiles.md`. HyperFrames 규칙 요약: `references/hyperframes-notes.md`(깊게 필요하면 공식 스킬 `/hyperframes-core`, `/hyperframes-keyframes`, `/hyperframes-audio`).

## 2. 모션 레벨별 설계 기준 (BRIEF 의 레벨을 넘지 않는다)
| 레벨 | 넣는 것 | 넣지 않는 것 |
|---|---|---|
| 0 기본 | 브랜드 템플릿(제목·자막·시그니처/워터마크)만. 사용자가 콕 집은 연출만 | 스스로 추가하는 그래픽·줌·효과음 |
| 1 은은하게 | 핵심 1~2곳: 결론 키워드 카드 또는 수치 비교 카드, 필요 시 느린 푸시 1회 | 효과음, 펀치인 연타 |
| 2 다이내믹 | 후킹(첫 3초)·반전·결론에 카드/숫자/비교, 펀치인 1~2회, 효과음(뿅·휙·딩), 강조 자막 | 모든 문장에 카드, 같은 효과 반복, 장식용 흔들림 |
공통: **큰 순간은 하나**(보통 결론이나 반전: 카드 + 효과음 + 펀치인 중 둘까지) · 그래픽 사이 최소 0.8초 · 카드 한 장 1.5~3.5초 · 문구는 짧게(한 줄 8자 안팎, 최대 2줄).

## 3. 비트 쓰는 법
- 시각은 **at_word**(그 말을 시작하는 단어, 공백·문장부호 무시, 여러 어절 가능). 같은 말이 여러 번이면 `nth`. 미세 조정은 `offset`(초). 끝은 `dur` 또는 `until_word`.
- `./shorts.sh words <p> <t0> <t1>` 로 실제 표기(전사·교정 후)를 확인하고 쓴다. 못 찾으면 build 가 `!` 로 알린다.
- 유형:
  - `keyword` — 핵심 문구 카드. `text` 에 `/` 로 2줄. 수학쌤=빨간 마커 밴드, 비블=노랑 외곽선(`kw_style` 브랜드 기본).
  - `number` — 카운트업. `from`·`to`·`prefix`·`suffix`·`label`·`decimals`. "~까지"가 기본(형식 맞춘 from).
  - `compare` — 왼쪽 → 오른쪽 전환("4·5·6등급 → 3등급"). `right_word` 에 오른쪽이 나오는 말.
  - `list` — 체크리스트. `items:[{text, at_word}]` 항목마다 그 말에 등장, `hold` 마지막 뒤 유지.
  - `quote` — 따옴표 강조 한 줄. `flash` — 흰 번쩍(0.14초, 전환·강조용 드물게).
  - `zoom` — `style: punch`(1.12, 0.12초 in, 컷으로 복귀) | `push`(1.06, 조각 끝까지). 복귀는 가까운 컷에 자동 정렬.
  - `broll` — **롱폼 B-roll 카드**(2026-09-27): 영상 밴드를 덮는 자료 화면 영상(화자 위·제목·자막 아래 층, 줌 영향 없음). `src`(프로젝트 기준 `broll/<id>.mp4`), `at_src`(원본 초 — 롱폼 plan.json 시각을 그대로), `dur`. 카드는 `유튜브 B-roll/engine/shorts_cards.py <롱폼 프로젝트> cards.json --out projects/<p>/broll` 로 만든다(롱폼 비트를 창 t0~t1 로 잘라 같은 렌더러로 그리고, 실제 그려진 영역을 자막 위 1000x690 자리에 맞게 키움, 검정 바탕 1080x1046 30fps). 그래픽 겹침 규칙(앞 카드 0.08초 전 끊기)에서 빠지므로 이어지는 카드 사이에 화자가 번쩍이지 않는다. 한 편의 30~50%, 말하는 순간에 맞춰 창을 고르고 화자 얼굴 구간을 사이사이 둔다. 브랜드에 `split` 이 있으면(비블 v3) 카드는 **위 패널**(0~`line`, 검정 #0C0C0C, overflow 숨김)로 내려오고 화자는 `#cam-split` 으로 아래로 밀리며 `person_scale` 배로 줄어든다(넓게 자른 base 라 옆이 비지 않음, 얼굴 박스 위 끝 → `face_target`). 제목·자막 층은 `title_shift`·`cap_shift`(+ `title_scale`·`cap_scale`)만큼 움직인다. 2026-09-28 비블 v3 = **위 B-roll 40%(line 768) · 인물 0.70배 · 제목 +174.7(1386–1594) · 자막 +195(1325) · 0.45초 power3.inOut · 패널 아래 그림자(`edge`) · 카드 느린 밀기(`panel_push`, 같은 broll_beat 는 이어서)** — shorts-designer 안 B. 카드는 `--w 1080 --h 768 --area-w 1000 --area-h 580 --top 140 --bg "#0C0C0C"` 로 렌더. 분할 중에는 줌을 넣지 않는다(머리·자막 여유가 한계). **분할은 한 편에 한 구간**(2026-09-28 사용자: '나왔다 사라졌다 반복이라 정신없다, B-roll→전체샷 전환은 1~2회 이내'): 훅은 얼굴로 두고 첫 B-roll 순간에 분할로 들어가 끝까지 가거나, 펀치라인을 얼굴로 주고 싶을 때만 그 직전에 한 번 돌아온다. 화자가 계속 보이므로 30~50% 규칙은 분할 레이아웃에는 적용하지 않는다. 구간 안은 롱폼 비트 경계(스킵 경계 포함)로 카드를 **빈틈없이** 이어 자른다(챕터 표지 비트는 뺀다). 경계는 **다음 카드의 첫 그림이 뜨는 순간** — 롱폼 비트가 첫 요소보다 먼저 시작하면(예: 출연자 c03 첫 요소 +1.48초) 그동안 앞 카드를 유지해 빈 검정 패널이 안 보이게 한다. 스킵(점프컷)으로 한 비트가 두 카드가 되면 cards.json 에 같은 `group`(예 `j8:a24`)을 줘 크기·위치를 고정하고, 비트 중간에서 시작하는 카드는 shorts_cards 가 자동으로 롱폼 그 순간부터 렌더한다(render_from) — 엔진이 이어지는 카드를 한 프레임 겹쳐(build.py) 반올림 틈에 빈 패널이 깜빡이지 않게 하고, 2초 안의 틈은 한 분할로 묶는다(merge_gap, 안전장치).
- 공통 옵션: `enter`(pop|rise|fade|cut), `feel`(vocab), `size`(px), `zone`("alt" 또는 [x0,y0,x1,y1]), `sfx`(vocab 이름).
- 겹치면 엔진이 앞 카드를 다음 시작 0.08초 전에 끊는다(최소 0.8초) — 설계 단계에서 겹치지 않게 두는 게 먼저.

## 4. 자막
- 분할은 브랜드 방식: 수학쌤 `meaning`(의미 단위·한 줄 980px·2줄 큐) / 비블 `v31`(3~8자 리듬·문장부호 제거). 결과는 `captions.auto.json`.
- 한 큐만 고칠 때: `captions.auto.json` 을 `captions.edit.json` 으로 복사해 그 큐의 `lines`·시각만 고친다(있으면 build 가 그것을 쓴다. `captions.auto.json` 은 늘 엔진판으로 남아 비교할 수 있다. build 는 수정본을 처음 쓸 때의 컷을 `captions.edit.key` 에 적어 두고, 이후 컷이 바뀌면 `!` 로 알린다 — 그때는 auto 와 비교해 edit 시각을 다시 맞추고 key 를 지운다).
- 오인식: 반복되는 것은 `brands/<b>.json corrections`, 그 편만의 것은 short.json `fix`.
- 강조: `captions.emphasis` 구절 + `emphasis_mode` color|marker. 키워드만(한 큐에 1~2개). 스타일 `pop`·`karaoke`·`highlight` 는 브랜드 확정 템플릿이 아니므로 사용자가 요청할 때만.
  - 구절은 `{"text": "고성과자", "at": 14.2, "sfx": "ping-t"}` 처럼 쓸 수 있다: `at`(쇼츠 초)·`nth`(몇 번째 등장)이 있으면 **그 큐 하나에만**(같은 말이 여러 번 나올 때), `sfx` 는 그 순간 소리 덮어쓰기("none" = 소리 없음). 브랜드 `captions.marker.chars_only` 면 조사를 빼고 맞은 글자만 칠하고('증거가' → '증거', '99%는' → '99%'), `emph_scale`(1.1)로 그 큐만 조금 크게 튄다. 팝·마커·feel 기본값은 brand `captions.pop`·`marker`·`feel`·`emphasis_mode`.
  - 비블 v3(2026-09-28 '지루하지 않게'): 강조는 3~5초마다·한 문장 하나·연달아 두 큐 금지, 숫자·답·패널 빨강 요소와 같은 순간 = 띵, 결론 차임·긍정 반짝·부정 삑은 편당 한 번. 훅(분할 전 얼굴)은 길이별 — 6초 미만 강조 1~2 + 펀치인 1, 6~12초 첫 문장 push 1.05 + 빨강 키워드 상자 1(+펀치인 1.12), 12초 초과 큰 순간 2. 키워드 상자(`kw_style: box`)는 자막 자리에 자막 대신, 말 그대로 7자 이하.
- **BGM**(short.json `bgm: {file, db_under}` — 목소리 LUFS 보다 db_under(기본 18)dB 아래, 반복·페이드 자동): 유튜브에 올릴 곡은 **Content ID 미등록**이어야 한다 — Pixabay 는 곡 페이지에 'Content ID Registered' 표시가 있으면 무료 라이선스여도 저작권 소유권 주장이 걸릴 수 있으니 제외, AI 생성 표시 곡도 피한다. 받은 곡은 `assets/bgm/` + CREDITS.md(곡·만든 사람·URL·라이선스·확인 날짜). 다운로드는 파일명·출처·크기를 알리고 사용자 허락 뒤에만.
- 효과음 자동(brand `sfx_auto`): 패널 새 그림(short.json `sfx_events` — `make_split_beats.py --events` 가 쇼츠 B-roll 계획에서 뽑음)·분할 진입·카드 바뀜·자막 강조·키워드 상자를 모아 역할 → 소리(map)로 바꾸고 density(최소 0.45초·같은 소리 0.9초·띵 6초·편당 한 번 소리·8초당 4개·끝 0.3초 무음)로 솎는다. short.json `sfx`(손으로)가 먼저·항상 이기고, `"sfx_auto": false` 면 끈다. 결과는 resolved.json `sfx`.

## 5. 빌드 경고 처리
| 경고 | 처리 |
|---|---|
| `! 비트 N 시각을 못 정함` | words 로 실제 표기 확인 → at_word 수정 |
| `! 그래픽: 얼굴과 겹치지 않는 자리를 못 찾음` | 문구·size 줄이기 또는 zone 지정 |
| `! 글꼴 … 에 없는 글자` | 그 글자 빼거나 다른 표기(→ 는 브랜드 글꼴에 없을 수 있음: compare 는 화살표를 도형으로 그림) |
| `경계 a→b` 노트 | 소리 골짜기로 옮긴 결과. 0.3초 넘게 옮겼으면 첫·끝 단어가 의도대로인지 확인 |
| lint 오류 | short.json 값 확인 → 엔진 문제면 보고 |
| lint 경고 20여 개(`nested_structure_needs_subcomposition`·`timeline_track_too_dense`), `FFTM NOT subset` | 정상 — Studio 타임라인 가독성 권고·글꼴 표 하나를 뺀다는 알림. 오류 0 이면 진행 |

## 6. 보고
무엇을 바꿨는지 필드·값으로(예: "beats[1].offset 0 → 0.5, 나머지 그대로"), draft/최종 경로, 시트 경로. 사용자가 판단할 것(제목·큰 순간 위치)은 질문 하나로.
