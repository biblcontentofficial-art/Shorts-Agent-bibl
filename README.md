# Shorts Agent

**롱폼·원본 영상에서 쇼츠 후보를 찾고, 컷·자막·후킹 제목·모션·효과음·BGM 까지 입혀 세로 쇼츠(1080x1920)로 렌더하는 Claude Code 하네스.**
렌더 엔진은 오픈소스 [HyperFrames](https://github.com/heygen-com/hyperframes)(HTML → MP4). 브랜드 템플릿을 기존 완성본과 픽셀 단위로 맞추고, 자동 검수까지 돌린 뒤 넘깁니다. 전부 맥에서 **로컬 실행**.

> **TL;DR (EN):** A Claude Code harness that turns long-form or raw footage into vertical shorts: clip scouting, word-level transcription, speech-aware cuts, captions, hook titles, motion, SFX/BGM, brand templates, and automatic QA — rendered with HyperFrames. Korean-speech tuned, runs locally on Apple Silicon.

```bash
./shorts.sh ingest 원본.mp4 --name 내프로젝트 --brand bibl-v3     # 단어 전사 + 얼굴·샷 분석
./shorts.sh new    내프로젝트 s1 --in 21.7 --out 64.7 --title "1줄/2줄"
./shorts.sh draft  내프로젝트/s1                                  # 빠른 확인본
./shorts.sh make   내프로젝트/s1                                  # build → 최종 render → qa
```

---

## 무엇을 해 주나

- **쇼츠 발굴** — 전사를 읽고 혼자 성립하는 구간(훅 → 전개 → 마무리)을 점수로 골라 후보표를 만듭니다.
- **말소리 기준 컷** — 단어 시각 + 음량으로 경계를 잡고, 첫·끝 음절이 잘리지 않았는지 **잘라 낸 구간을 다시 받아써서** 확인합니다. 지운 말(`skip`)이 남았는지도 들어서 검사합니다.
- **자막 v3.1** — 의미 단위로 끊고, 2~4프레임만 뜨는 짧은 큐는 이웃과 합쳐 깜빡임을 없앱니다. 강조 단어는 빨강 마커.
- **브랜드 템플릿** — `brands/*.json` 한 파일에 제목 상자·자막·로고·레이아웃·음량·인코딩. 기본 `bibl-v3`: 가운데 둥근 제목 상자 + 붓글씨 로고, B-roll 구간은 위 40% 패널 · 아래 60% 인물 분할.
- **프레이밍** — 얼굴 추적 크롭, 번인 자막 위로만 자르기(`zoom`), **2인 대담 화자 전환**(`focus_map` — 상대가 말할 때 그 사람 얼굴로, 맞장구는 전환 안 함), 사람 전체를 가운데로(`frame_bias`).
- **모션·소리** — 훅 키워드 상자·펀치인·느린 밀기, 마우스 클릭 계열 효과음 자동 배치(2~3초 간격), BGM 을 목소리보다 n dB 아래로.
- **자동 검수(QA)** — 형식·음량(-14 LUFS)·컷 경계 음량·재전사 일치율·얼굴 가림·화면 밖 글자·HyperFrames check. 검수 시트 이미지까지.
- **넘기기만, 발행은 안 함** — `deliver` 는 폴더 복사·SNS 압축본·기록까지. 업로드·예약은 사람이 지시할 때 따로.

## 무엇이 들어 있나

| 경로 | 내용 |
|---|---|
| `shorts.sh` | CLI (`ingest` · `status` · `words` · `new` · `cut` · `build` · `draft` · `render` · `qa` · `make` · `all` · `preview` · `deliver`) |
| `engine/` | `ingest`(전사·얼굴·샷) · `cut`(조각·크롭) · `textproc`(자막) · `compose`(HyperFrames 컴포지션) · `build` · `render` · `qa` · `faces`(Apple Vision) · `deliver` |
| `brands/` | `bibl-v3.json`(현행) · `bibl.json` · `bibl-classic.json` |
| `.claude/agents/` | `shorts-scout`(발굴) · `shorts-editor`(편집) · `shorts-designer`(디자인 목업) · `shorts-qa`(검수) |
| `.claude/skills/` | `shorts-agent`(오케스트레이터) · `shorts-order`(주문서 해석) · `shorts-clip-selection` · `shorts-edit`(short.json 스키마·브랜드 프로필) · `shorts-hook-title` · `shorts-qa` |
| `쇼츠_주문서.md` | 사람이 말로 주문하는 법 (예시 문장·스펙 줄) |

## 요구사항

| | |
|---|---|
| OS | **macOS (Apple Silicon)** — mlx-whisper·Apple Vision(얼굴) 사용 |
| 런타임 | **Node.js 18+** (HyperFrames 0.8.71) · **Python 3.10+** (`numpy`, `Pillow`, `fonttools`, `mlx-whisper`, `pyobjc-framework-Vision`) · **ffmpeg** |
| 폰트 | `assets/fonts/` 에 `Pretendard-Bold.otf` · `NotoSansCJKkr-Bold.otf` · `NotoSansCJKkr-Black.otf` · `Paperlogy-9Black.ttf` · `MaruBuri-SemiBold.otf` (모두 무료 폰트 — 각 배포처에서) |
| 소리 | `assets/bgm/` · `assets/sfx/` — `CREDITS.md` 의 출처에서 받아 같은 이름으로 (라이선스상 재배포하지 않음) |

### 설치

```bash
git clone https://github.com/biblcontentofficial-art/Shorts-Agent-bibl.git
cd Shorts-Agent-bibl
npm install                                   # hyperframes 0.8.71
pip install numpy pillow fonttools mlx-whisper pyobjc-framework-Vision
brew install ffmpeg
npx skills add heygen-com/hyperframes --full-depth   # (선택) HyperFrames 공식 스킬 — skills-lock.json 참고
```

## Claude Code 로 쓰기

이 폴더를 Claude Code 로 열고 `쇼츠_주문서.md` 처럼 말하면 `shorts-agent` 스킬이 발굴 → 편집 → 렌더 → 검수를 이어서 합니다.

- "쇼츠 에이전트로 `원본.mp4` 쇼츠 3개 만들어줘"
- "s2 제목 후보 3개 다시" · "인물을 가운데로" · "동생이 말할 때는 동생 얼굴로"

## 함께 쓰는 저장소

- [YouTube-Broll-bibl](https://github.com/biblcontentofficial-art/YouTube-Broll-bibl) — 쇼츠 분할 패널에 얹는 B-roll 카드(`engine/shorts_cards.py`)
- [Premiere-Pro-edit-bibl](https://github.com/biblcontentofficial-art/Premiere-Pro-edit-bibl) — 롱폼 러프컷·단어 전사

## 저장소에 넣지 않은 것

`projects/`(실제 영상 작업 데이터) · `node_modules/` · `vendor/`(HyperFrames 원본) · HyperFrames 공식 스킬 · 폰트 · BGM/효과음 원본.

## 라이선스

MIT — `LICENSE`. 렌더 엔진 [HyperFrames](https://github.com/heygen-com/hyperframes) 는 Apache-2.0, 애니메이션 런타임 GSAP(`engine/templates/gsap.min.js`)은 GSAP 표준 라이선스를 따릅니다.
