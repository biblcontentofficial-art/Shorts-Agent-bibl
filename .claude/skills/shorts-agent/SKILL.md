---
name: shorts-agent
description: 쇼츠 에이전트(HyperFrames 기반 세로 쇼츠 편집 하네스)의 진입점 오케스트레이터. 원본·롱폼 영상으로 쇼츠 만들기, 쇼츠 편집, 숏폼·릴스 자르기, 쇼츠 자막·후킹 제목·모션그래픽·줌·효과음 넣기, 쇼츠 렌더·검수·넘기기, "쇼츠 에이전트로", "하이퍼프레임으로 쇼츠", 쇼츠 주문서(6칸) 요청이면 반드시 이 스킬로 시작한다. 후속 요청 — "2번 쇼츠 제목 바꿔줘", "다시 렌더", "자막 수정", "줌 빼줘", "이어서 해줘", "결과 개선", "나머지 편도" — 도 여기서 처리한다. 비블(bibl)·수학 채널(클라이언트)(mathclient) 브랜드 템플릿 지원. 쇼츠가 아닌 새 영상(제품 홍보·설명 영상)은 /hyperframes, 롱폼 B-roll 은 broll-pipeline, 수학 문제풀이 분할화면은 math-split-screen, 수학쌤 쇼츠의 업로드·예약·SNS 발행 운영은 ncs-shorts-orchestrator 로.
---

# 쇼츠 에이전트 — 오케스트레이터

원본 → 발굴 → 컷확인 → 제목 → 편집 → 렌더 → 검수 → 넘기기. 사람 체크포인트는 **후보 선택 · 맥락 확인 · 제목 승인** 세 곳이다.
엔진 명령은 전부 `./shorts.sh` (이 폴더 루트). 사용자 말을 설정으로 옮기는 규칙은 `shorts-order` 스킬 — 요청을 받으면 먼저 그 스킬로 해석한다.

## 실행 모드: 서브 에이전트 (파이프라인 + 생성-검증)
단계 사이에 사람 확인이 끼므로 팀 동시 협업보다 **파일 인계**가 맞다. 각 단계에서 `Agent` 도구로 전문 에이전트를 부르고(반드시 `model: "opus"`), 산출물은 약속된 경로에 남긴다.
| 에이전트 | 맡는 단계 | 스킬 |
|---|---|---|
| `shorts-scout` | 발굴·컷확인 | shorts-clip-selection |
| `shorts-editor` | 제목·편집·렌더·수정 | shorts-hook-title, shorts-edit, shorts-order |
| `shorts-qa` | 최종 검수·수정 지시 | shorts-qa |
| `shorts-designer` | 템플릿 화면 디자인(비율·제목 상자·자막 위치·타이포 효과·색·전환·효과음 밀도 규칙) 설계 — 실제 프레임 목업 2~3안 비교 → design_spec.json, draft 시트 검수 | shorts-edit(엔진 필드), brands/*.json |
간단한 단일 작업(자막 한 줄 수정, 재렌더)은 에이전트를 부르지 않고 직접 해도 된다.
사용자가 **화면 구성·색·비율·'자연스럽게'·'지루하지 않게'** 를 말하면 먼저 `shorts-designer`(목업·스펙) → 엔진·brand 반영 → 한 편 draft 를 designer 가 검수 → 나머지 편. 롱폼 B-roll 카드가 쇼츠 패널에서 오래 멈추면 B-roll 하네스의 `broll-planner` 로 편별 보강(`유튜브 B-roll/projects/<p>_쇼츠/parts/`, 2026-09-28 bibl_ex1 선례).

## Phase 0: 컨텍스트 확인 (항상 먼저)
1. 어떤 원본/프로젝트인지 확인: `ls projects/` · `./shorts.sh status <p>`.
2. 실행 모드 판정
   - `projects/<p>/` 없음 → **초기 실행** (Phase 1부터)
   - 있음 + 사용자가 부분 수정 요청("2번 제목", "줌 빼줘") → **부분 재실행**: 해당 쇼츠 폴더만, 해당 단계만 (Phase 6/7)
   - 있음 + 새 원본 → **새 실행**: 새 프로젝트 이름(`<브랜드><편>`, 예 `mathclient5`)으로 시작, 기존 프로젝트는 건드리지 않음
3. `BRIEF.md` 가 있으면 그 답을 쓰고 다시 묻지 않는다. 바뀐 답은 BRIEF.md 에 반영.

## Phase 1: 인터뷰 → BRIEF.md
HyperFrames 가이드의 '인터뷰' 방식: 꼭 필요한 질문만, **추천 답을 먼저** 두어 번호로 답하게 한다(AskUserQuestion 사용 가능, 한 번에 최대 4문항).
1. 브랜드 — 수학쌤(mathclient) / 비블(bibl = 현행 template-v2) / 비블 구 템플릿(bibl-classic) / 기타(새 브랜드 JSON 필요)
2. 편수 — "기준 통과한 것 전부(추천)" / N편
3. 모션 레벨 — 0 기본 템플릿 / 1 은은하게 / 2 다이내믹 (브랜드 기본: 수학쌤 0, 비블 0)
4. 컷확인 단계 — 한다(추천: 첫 원본·클라이언트) / 건너뛴다
사용자가 "묻지 말고 바로"라고 하면 추천값으로 진행하고, 무엇을 골랐는지 첫 보고에 적는다.
BRIEF.md 는 `references/brief-template.md` 형식으로 쓴다.

## Phase 2: 분석
`./shorts.sh ingest <원본> --name <p> --brand <b>` (전사 large-v3-turbo + 얼굴·카메라 컷). 8분 영상 기준 약 2~3분.
끝나면 `transcript.md` 를 확인해 환각·오인식이 많으면 사용자에게 알리고 `--model large-v3 --redo` 를 제안.

## Phase 3: 발굴 → 체크포인트 ①
`shorts-scout` 호출 → `candidates.md` + 추천 순위. 사용자에게 후보표(구간·길이·기승전결·점수·위험)를 보여주고 고르게 한다. "알아서" → 점수 순 BRIEF 편수만큼.
고른 후보마다 scout 가 `short.json` 초안을 만든다.

## Phase 4: 컷확인 → 체크포인트 ② (BRIEF 에서 한다고 했을 때)
`./shorts.sh cut <p>/<id>` 로 자막·제목 없는 순수 컷본. 사용자가 맥락을 재구성하면("'냉정하게'부터") scout 가 segments 만 고친다.

## Phase 5: 제목 → 체크포인트 ③
`shorts-editor` 가 `shorts-hook-title` 규칙으로 편당 A~D → `shorts/<id>/titles.md`. 응답 형식 "1. B / 2. 직접: ○○/○○ / 3. 삭제". **승인 전에는 최종 렌더하지 않는다**(draft 는 가제로 가능). 사용자가 쓴 문구는 띄어쓰기까지 그대로, `title.status: approved`.

## Phase 6: 편집 → draft
`shorts-editor` 가 BRIEF 의 모션 레벨·사용자 연출 지시로 beats 설계 → `./shorts.sh build` → `./shorts.sh draft`. 사용자가 직접 보고 싶어 하면 `./shorts.sh preview <p>/<id>` (Studio, http://localhost:3002) — 사용자가 요소를 클릭하고 "이거" 라고 하면 `node_modules/.bin/hyperframes preview <build> --selection --json` 으로 그 요소를 읽는다.

## Phase 7: 최종 렌더 + 검수
`./shorts.sh render <p>/<id>` → `shorts-qa` 호출(qa.py + 시트 + 규칙 대조 → review.md). FAIL/WARN 의 수정 지시를 editor 가 반영 → 다시 render·qa. **루프는 최대 2회**, 그래도 남으면 사용자에게 그대로 보고.
보고할 때 검수 시트(`out/<id>_sheet.jpg`)와 완성본 경로를 함께 준다(SendUserFile 로 시트 전송 가능).

## Phase 8: 넘기기 (사용자가 "넘겨줘"라고 할 때만)
`./shorts.sh deliver <p>/<id> [--to-folder] [--sns]`. 클라이언트 폴더(`--to-folder`)는 제목 승인 + QA 비FAIL 일 때만 엔진이 허용한다. **업로드·예약·발행은 하지 않는다** — 수학쌤은 ncs 업로더, 비블은 upload 엔진이 사용자의 그 턴 명시 지시로 한다.

## 데이터 흐름
| 파일 | 만든 쪽 | 쓰는 쪽 |
|---|---|---|
| `projects/<p>/BRIEF.md` | 오케스트레이터(인터뷰) | 모두 |
| `source.json · words.json · segments.json · faces.json · transcript.md` | ingest | scout, build |
| `candidates.md` | scout | 오케스트레이터(체크포인트 ①) |
| `shorts/<id>/short.json` | scout(구간) → editor(제목·연출) | build |
| `shorts/<id>/titles.md` | editor | 체크포인트 ③ |
| `shorts/<id>/resolved.json · captions.auto.json · build/` | build | render, qa |
| `shorts/<id>/out/<name>.mp4 · _sheet.jpg · _qa.json · _review.md` | render · qa · shorts-qa | 사용자, deliver |
| `projects/<p>/deliver/` | deliver | 업로드 담당(별도 하네스) |

## 에러 핸들링
| 상황 | 처리 |
|---|---|
| 전사 환각·오인식 다수 | large-v3 재전사 제안, 확정 교정만 brands corrections 에 추가 |
| build lint 오류 | short.json 값 확인 → 엔진 문제면 재현 경로와 함께 보고(추측 수정 금지) |
| `!` 비트 시각 못 찾음 | `./shorts.sh words` 로 실제 구절 확인 후 at_word 수정 |
| Studio 수정 흔적으로 build 정지 | 바뀐 값을 short.json 으로 옮긴 뒤 build(버려도 되는 경우만 --force) |
| 렌더 실패 | 1회 재시도(`--workers 2`), 재실패 시 로그 보고 |
| QA FAIL(형식·타임스탬프) | 인코딩 문제 — render 재실행, 반복되면 보고 |
| QA WARN(음절·얼굴·겹침) | 수정 루프 최대 2회 |
| 에이전트 실패 | 1회 재시도, 재실패 시 그 결과 없이 진행하고 보고에 누락 명시 |

## 후속 요청
- "2번 쇼츠 ○○ 고쳐줘" → Phase 0 부분 재실행 → shorts-order 편집 동사표로 short.json 최소 변경 → build → draft(또는 render) → 필요 시 qa.
- "나머지 편도 해줘" → candidates.md 에서 남은 후보로 Phase 3 이후 반복.
- 실행이 끝나면 한 줄로 피드백 기회를 준다("결과·흐름에서 바꾸고 싶은 점이 있으면 말해 주세요"). 같은 지적이 2번 나오면 스킬·브랜드 JSON 에 반영하고 CLAUDE.md 변경 이력에 기록.

## 테스트 시나리오
**정상**: "쇼츠 에이전트로 ~/Downloads/수학쌤 4편.mp4 쇼츠 3개, 모션 레벨 1" → BRIEF.md(mathclient, 3편, 레벨1) → ingest → scout 후보 5개 중 사용자 "1,2,4" → 컷확인 → 제목 A~D → "1.A 2.B 4.직접" → build·draft → render → qa PASS → "넘겨줘" → deliver --to-folder --sns.
**에러**: 제목 승인 전 "넘겨줘" → deliver 가 거부(title.status) → 제목 승인부터 요청. / at_word "3회독" 을 못 찾음 → words 로 실제 표기("삼회독") 확인 후 수정.
**2026-09-24 실측**: 수학쌤 4편 원본(8분·4K 한 샷)으로 3편 — 템플릿 재현(모션0)·비교 카드(모션1)·말 단위 삭제+키워드·펀치인·효과음(모션2), QA 9종 전부 PASS. 렌더 42초 영상 36초.
