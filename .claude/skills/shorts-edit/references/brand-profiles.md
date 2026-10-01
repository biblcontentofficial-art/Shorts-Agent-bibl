# 브랜드 프로필 (brands/<b>.json)

HyperFrames 가이드 'Design systems'의 frame.md 역할 — **색·글꼴·템플릿 좌표의 진실**. 편 단위 연출(short.json)은 이 값을 바꾸지 않는다.

| 필드 | 뜻 |
|---|---|
| `extends` | 다른 브랜드를 바탕으로 덮어쓰기(bibl → bibl-classic). dict 는 한 단계 병합 |
| `canvas` | 1080x1920, 배경색(비블 밴드 레이아웃의 검정 여백) |
| `layout.mode` | `full`(영상이 화면 전체) · `band`(비블: 영상 밴드 — 현행 1080x1046@533, 구 1080x1030@532) |
| `layout.crop` | `full_height`(원본 세로 전체 9:16) · `face_scale`(얼굴 높이×3.6, 얼굴 위 36%, 번인 자막 위 bottom_limit) — 원본에 자막이 구워져 있으면 ingest 의 `subs.py` 가 가장 높은 자막 줄을 재서 build 가 bottom_limit 를 그 위로 자동으로 내린다 |
| `layout.natural_band` | 2인 대담 투샷(short.json `frame`) — 두 사람을 원비율로 담는 밴드 높이 `min_h`~`max_h`, 자막 y = 밴드 y + `cap_frac`×밴드 높이, `wm: bottom_center` 면 워터마크를 밴드 아래 검정 여백 가운데로, 그래픽 자리도 밴드 아래로 옮긴다 |
| `title` | font·family·weight, `size_rule`(최장 줄 글자수 → px), `min_size`, `shrink_step`(0=비례 축소), `max_w`, `anchor`(ascender=첫 줄 어센더 선 y / middle=블록 가운데 / first_middle=첫 줄 가운데, 한 줄이면 두 줄 자리 가운데), `y`, `pitch`(줄 간격 배수), `colors`[1줄,2줄], `stroke`, `shadow`, `band`(수학쌤 빨간 마커), `split`(balance=한 줄을 균형 2줄로) |
| `captions` | `chunker`(meaning|v31), font…, `size`(CSS em px), `measure_size`(분할 폭 판정 크기), `anchor`·`y`·`line_pitch`, `max_w`, `strip`(지울 문장부호), `gap_fill`(쉼 메움 초), `style`, `accent` |
| `watermark` / `signature` | 문구·글꼴·크기·색·기울기·위치·그림자(없으면 null) |
| `graphics` | 그래픽 글꼴·text·accent(두 색 규율의 강조색)·ink·card_bg, `zone`(기본 자리)·`alt_zone`, `kw_style`(band|outline, 없으면 제목 밴드 유무로), `default_motion_level` |
| `audio` | `lufs`(-14)·`tp`(-1.5)·`tail_fade`(끝 페이드 최대 초 — 마지막 말이 실제로 끝난 뒤에만 걸리게 build 가 줄인다) |
| `encode` | `fps`("source" 면 원본), `crf`, `bframes`(비블 0), `audio_bitrate`, `hf_crf`(중간본) |
| `clip` | 길이 범위·이상 범위 |
| `glossary` / `corrections` | 전사 초기 프롬프트 용어 / 확정 교정(긴 패턴 먼저 적용, 여러 어절 가능) |
| `deliver` | `folder`(클라이언트 납품 폴더, 승인 후에만), `name`(`{title}` 이면 승인 제목), `sns` |

## 수치 출처 (재현 검증)
- mathclient: `이전클라이언트_쇼츠/_workspace/render_mathclient3.py`(PIL·libass) → 2026-09-24 3편 쇼츠1과 픽셀 대조 일치(제목 y99–329, 자막 윗선 1097·아랫선 1257, 시그니처 1756–1800). ASS 글꼴 크기 92 = 줄 높이 → CSS em 80.35.
- bibl(현행 template-v2): `Premiere Pro/engine/shorts_premiere.py --template-v2`(2026-09-03 레퍼런스) → 최신 비블 쇼츠 작업 `01_비블 BiBl/00_비블 유튜브/999_쇼츠/14_유튜브커뮤니티/프리미어/그래픽`(2026-09-19) PNG 와 대조: 제목 노랑 줄 y288–379·흰 줄 y407–497, 자막 윗선 1304, 워터마크 423–620 — 모두 ±5px(가로는 글자별 PIL 렌더와 브라우저 렌더 차이). 재현 요령: 첫 줄 가운데 앵커, 줄간격 int(100×1.18), 폭 판정은 자간 없이, 크로미움 공백 자간 보정(word-spacing), 워터마크는 PIL 시어 캔버스 탓에 −21px.
- bibl-classic: `bibl-shorts-automation/shorts/shorts_premiere.py` 확정값(2026-07-17 구도·07-24 자막 v3.1). libass 크기 → CSS em 환산(제목 120/114/108 → 101/96/91, 자막 118 → 80, 워터마크 70 → 52). 이 템플릿의 완성본 픽셀 대조는 아직 안 함.

## 새 브랜드 추가
1. 가장 가까운 브랜드를 `extends` 하고 다른 값만 적는다.
2. 글꼴은 `assets/fonts/` 에 두고(또는 ~/Library/Fonts) 파일 이름을 적는다. build 가 쓰는 글자만 woff2 로 잘라 넣는다.
3. 기존 완성본이 있으면 같은 제목 문구로 한 편 만들어 `hyperframes snapshot` 과 원본 프레임을 겹쳐 보고 좌표를 맞춘다(가이드 'Recreating references': 절대값으로 맞추고 상수로 굳힌다).
