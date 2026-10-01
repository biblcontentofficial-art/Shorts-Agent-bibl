# HyperFrames Prompt Guide → 쇼츠 에이전트 적용표

원문: https://hyperframes.heygen.com/prompting/overview (2026-09-24 전체 34장 확인. 로컬 사본 `vendor/hyperframes/docs/prompting/`)
표의 '적용'은 이 하네스에서 실제로 구현·규칙화한 것이다.

| 장 | 핵심 | 쇼츠 에이전트 적용 |
|---|---|---|
| [Prompt Guide 개요](https://hyperframes.heygen.com/prompting/overview) | 스킬 설치·프로젝트·미리보기 3종 준비, cold/warm 두 모양, 인터뷰 → BRIEF.md, lint+check 게이트 | 공식 스킬 28종 설치, 쇼츠 = warm start, 인터뷰 결과 `projects/<p>/BRIEF.md`, build 마다 lint·qa 에 check 포함, `./shorts.sh preview` |
| [Anatomy](https://hyperframes.heygen.com/prompting/anatomy) | route·spec·beats·copy·technique·negatives 6파트, beat formula 5칸, 자주 고치는 문장 | `쇼츠_주문서.md` 6칸, shorts-order §2·§5 |
| [Specification dial](https://hyperframes.heygen.com/prompting/specification-dial) | 분위기 말 → 스타일 토큰 → 전체 스펙, 밀도는 결과의 거리 | 주문서 ①한 줄 ②스타일 단어 ③정밀 6칸, shorts-order §3 |
| [Vocabulary](https://hyperframes.heygen.com/prompting/vocabulary) | 형용사 → 이징·카메라·페이싱·자막 톤·마커 | `engine/vocab.json`(한국어 말 포함), compose 가 그대로 해석 |
| [Iterating](https://hyperframes.heygen.com/prompting/iterating) | 편집자처럼 짧게, 한 번에 하나, 절대값, 잘 된 것 잠그기, 게이트 통과 ≠ 좋은 영상 | 주문서 §4, shorts-order §6, qa 뒤 사람 눈 검수 시트 필수 |
| [Editing existing videos](https://hyperframes.heygen.com/prompting/editing-existing-videos) | NLE 동사 → data-* 속성 표, Studio 선택 요소 문맥 | 편집 동사 → short.json 필드 표, `preview --selection --json` |
| [Captions & talking heads](https://hyperframes.heygen.com/prompting/captions-and-talking-heads) | 푸티지는 편집기에서 먼저 다듬고 그 위에 자막·카드, 레일 vs 엠베드 | 컷·리프레이밍은 ffmpeg(base.mp4), HyperFrames 는 그 위 레이어. 엠베드(인물 뒤 글자)는 `/embedded-captions` 선택지로 남김 |
| [Caption styles](https://hyperframes.heygen.com/prompting/captions-catalog) | 톤으로 고르기, 강조는 키워드만, 한 구간 한 스타일, 없는 이름 금지 | captions.style 5종 + emphasis(키워드만) + 브랜드 기본 |
| [Overlays & lower thirds](https://hyperframes.heygen.com/prompting/overlays-and-lower-thirds) | 시각·문구(따옴표)·트랙 위, 카드 vs 카드 없음 | beats 는 at_word + 따옴표 문구, 그래픽 트랙 4(자막 위) |
| [Motion that reads premium](https://hyperframes.heygen.com/prompting/motion) | 움직임은 주장, 장식 금지, 에너지 대비, 겹치는 등장 | shorts-edit 모션 문법, 한 쇼츠 '큰 순간' 하나 |
| [Storyboards](https://hyperframes.heygen.com/prompting/storyboards) | 메시지·호·대상·분위기를 한 번에, VO-paced reveals, 브레더 하나, 금지 목록 | short.json `brief`(message·arc·audience·mood), 비트 at_word, 두 색 규율 |
| [Media & audio](https://hyperframes.heygen.com/prompting/media-and-audio) · [Audio effects](https://hyperframes.heygen.com/prompting/audio-effects) | 음량 목표를 말한다, 증상으로 말한다, '나레이션 없음' ≠ '무음' | -14 LUFS 정규화·QA, 효과음 vocab, BGM 은 목소리 −18dB, negatives |
| [Design systems](https://hyperframes.heygen.com/prompting/design-systems) | 브랜드 진실의 원천(frame.md), 색·글꼴은 엄격 레이아웃은 위임 | `brands/<b>.json` = 색·글꼴·템플릿 좌표의 진실 |
| [Variables & templating](https://hyperframes.heygen.com/prompting/variables-and-templating) | 바뀌는 칸을 변수로, 한 구성 여러 렌더 | 한 브랜드 템플릿 + 편마다 short.json, `./shorts.sh all` |
| [Data & maps](https://hyperframes.heygen.com/prompting/data-and-maps) | 카운트업은 "~까지", 형식 맞춘 숫자 | beats `number`(from→to 자리수 주의) |
| [Rendering & output](https://hyperframes.heygen.com/prompting/rendering-and-output) | draft 로 반복 → 최종 한 번, 4K/60fps 과잉 금지 | `draft` / `render` 분리, 브랜드 규격 마무리 인코딩 |
| [Rules & anti-patterns](https://hyperframes.heygen.com/prompting/rules-and-anti-patterns) | 타임라인 등록·muted video·결정성·clip 규칙, fromTo 이른 표시·cold seek | compose: 타임라인 하나, video muted+audio id, fromTo immediateRender:false, clip 은 .inner 만 움직임 |
| [Recreating references](https://hyperframes.heygen.com/prompting/recreating-references) | 레퍼런스는 모션을 받아 적고 절대값으로 맞추고 상수로 굳힌다 | 브랜드 템플릿을 기존 완성본과 픽셀 대조해 상수로 굳힘(수학쌤 제목·자막·시그니처 좌표 일치) |

쓰지 않은 장(쇼츠와 무관): product-launch, explainers, code-and-prs, code-blocks, music-and-slideshows, generated-artwork, color-grading, vfx-and-liquid-glass, runtimes-and-3d, transitions(쇼츠는 컷 중심), remotion-migration, capstone, examples(참고만).
