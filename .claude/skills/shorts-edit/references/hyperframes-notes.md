# HyperFrames 요점 (이 엔진이 지키는 것)

공식 원문은 설치된 스킬 `/hyperframes-core`(구성 계약), `/hyperframes-cli`(명령), `/hyperframes-keyframes`(줌·팬), `/hyperframes-audio`(믹스), `/hyperframes-animation`(모션)과 `vendor/hyperframes/docs/`.

- 구성: `index.html` 하나. 루트 `<div id="root" data-composition-id="main" data-duration data-fps data-width=1080 data-height=1920>`, 루트 크기는 100%(px 하드코딩 금지).
- 시간 요소는 `class="clip"` + `data-start`·`data-duration`·`data-track-index`. **clip 자체는 GSAP 로 움직이지 않는다** — 안쪽 `.inner` 를 움직인다.
- 영상: `<video muted playsinline data-start …>` + 같은 파일의 `<audio id=… data-volume>`(id 없으면 믹서가 못 잡아 무음). 영상의 조상에 data-start 를 또 두지 않는다. 줌은 영상을 감싼 **시간 없는** 래퍼(`#cam-inner`)에 scale.
- 타임라인: `gsap.timeline({paused:true})` 하나를 `window.__timelines["main"]` 에. 시계·무작위·네트워크 금지(결정적 렌더).
- `fromTo` 는 시작 전에도 from 상태를 그린다 → 이 엔진은 모두 `immediateRender:false`. 같은 속성을 여러 트윈이 동시에 쓰지 않는다(줌 포즈는 순서대로 명시적 from→to).
- 글꼴은 `@font-face` 로 로컬 파일(엔진이 쓰는 글자만 woff2 로 잘라 넣음). 이름만 쓴 font-family 는 lint 오류.
- 원본 탐색이 느린 영상(키프레임 드문 소스)은 화면이 멈출 수 있다 → base.mp4 는 GOP=fps.
- 게이트: `lint`(build 마다) + `check`(qa 가 --no-contrast 로 실행). 통과는 필요조건일 뿐 — 시트로 눈 검수.
- 렌더: `render -o out.mp4 --fps 30000/1001 --crf 12`(중간본) → ffmpeg 로 브랜드 규격 재인코딩. draft 는 `--quality draft`.
- 미리보기: `hyperframes preview --background --no-open` (포트 3002). `--selection --json` 으로 사용자가 클릭한 요소, `--stop` 으로 종료.
- lint 경고 `nested_structure_needs_subcomposition`·`timeline_track_too_dense` 는 Studio 타임라인 가독성 권고다(렌더에는 영향 없음). 자막 큐가 많아 생긴다.
