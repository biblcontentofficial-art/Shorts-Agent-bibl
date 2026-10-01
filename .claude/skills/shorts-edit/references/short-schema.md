# short.json 스키마 (projects/<p>/shorts/<id>/short.json)

```jsonc
{
  "id": "s3",                         // 폴더 이름과 같게
  "brand": "mathclient",                    // brands/<b>.json (없으면 source.json 의 브랜드)
  "name": "수학쌤4편_쇼츠3",            // 완성 파일명(비블은 deliver 가 승인 제목으로 바꿈)
  "brief": {                          // 스토리보드 요약(가이드 'Storyboards': 메시지·호·대상·분위기)
    "message": "같은 책 두 권으로 … 3등급이 안정된다",
    "arc": {"기": 326.04, "승": 329.72, "전": 348.76, "결": 373.94},   // 원본 초
    "audience": "수학이 어려운 하위권 학생", "mood": "구체적이고 경쾌한"
  },
  "frame": "auto",                    // auto(두 얼굴이 60% 이상 잡히는 대담이면 투샷) | two(투샷 강제) | one(한 사람 크롭)
                                      //  투샷 = 두 사람을 원비율 그대로 담는 밴드(band 레이아웃 브랜드만, 비블 2026-08-06 규칙)
  "segments": [                       // 원본 초. 여러 개면 순서대로 이어 붙임(점프컷)
    {"id": "a", "in": 326.04, "out": 385.06,
     "skip": ["아까 말했듯이"],         // 이 구간 안에서 빼는 말(소리 골짜기에서 자동 컷)
     "remove": [[340.1, 341.3]],       // 원본 초로 빼기(숨소리·말실수)
     "focus": "auto",                  // auto(얼굴·가상 카메라) | left | right | 0~1(가로 위치 고정)
     "focus_map": [[312.08, 313.58, "left"]],   // 구간 안에서 말하는 사람 따라 바꾸기 [원본 from, to, focus] — 2인 대담(2026-09-30)
     "frame_bias": {"right": 0.3, "left": -0.3}, // left/right 크롭 가운데를 얼굴 폭×값만큼(+오른쪽) — 얼굴이 아니라 사람(머리+몸)을 가운데로
     "zoom": 1.0,                      // >1 이면 좁게(얼굴 위 36%)
     "layout": "crop",                 // crop(세로 크롭) | fit(16:9 전체 + 흐린 배경)
     "track": true,                    // false 면 샷 안 가상 카메라 끔(고정 크롭)
     "in_exact": false, "out_exact": false}   // true 면 경계를 소리로 다시 맞추지 않음
  ],
  "title": {"lines": ["1줄", "2줄"], "status": "draft|approved|provisional"},
  "captions": {
    "style": "brand",                 // brand | pop | karaoke | highlight | fade
    "emphasis": ["두 권을", "3등급은"], // 강조 구절(여러 어절 가능)
    "emphasis_mode": "color",         // color | marker
    "accent": "#FF3B3B",              // 없으면 브랜드 captions.accent
    "feel": "bouncy"                  // pop 스타일 이징
  },
  "motion": {"level": 0, "feel": "smooth"},   // BRIEF 의 레벨. feel 은 비트 기본 느낌
  "beats": [                          // 쇼츠 위 그래픽·카메라. 시각은 at_word 권장
    {"type": "keyword", "at_word": "두 권을", "text": "같은 책 두 권", "dur": 2.4, "sfx": "pop"},
    {"type": "number", "at_word": "530등", "from": 530, "to": 1, "suffix": "등", "label": "내신 등수"},
    {"type": "compare", "at_word": "5등급제에서 4,", "left": "4·5·6등급", "right": "3등급",
     "right_word": "3등급 구간으로", "until_word": "묶여버렸거든", "enter": "rise"},
    {"type": "list", "at_word": "첫째", "title": "공부 순서",
     "items": [{"text": "풀고 바로 채점", "at_word": "한 문제 풀고"}, {"text": "혼자 다시 풀기", "at_word": "두 번째 책"}], "hold": 1.8},
    {"type": "quote", "at_word": "포기하지 말라고", "text": "끝까지 버티는 게 실력"},
    {"type": "zoom", "style": "punch", "at_word": "무조건 혼자서", "dur": 1.6, "sfx": "whoosh"},
    {"type": "flash", "at": 12.0}
    // 공통: nth, offset, dur, until_word, enter(pop|rise|fade|cut), feel, size, zone("alt"|[x0,y0,x1,y1]), sfx
  ],
  "sfx": [{"name": "ding", "at_word": "3등급은", "vol": 0.4}],   // 비트와 무관한 효과음
  "bgm": {"file": "music/lofi.mp3", "db_under": 18},   // 프로젝트 폴더 기준 또는 절대경로. build 가 목소리보다 18dB 아래로 맞추고 반복·페이드
  //  음원은 사용 허락된 것만(라이선스 확인). 효과음 라이브러리는 assets/sfx/CREDITS.md
  "negatives": {"no_sfx": false, "no_bgm": false, "no_audio": false},
  "fix": {"후월해질": "수월해질"}      // 이 편만의 전사 교정(반복되면 brands corrections 로)
}
```

시각 해석 순서: `at_word`(쇼츠에 남은 단어에서 찾음) → `at_src`(원본 초 → 쇼츠 초) → `at`(쇼츠 초). 모두 `offset` 적용.

## 기본값과 시각 규칙 (엔진 동작 그대로)
| 유형 | 기본 size(px, 최대값) | 기본 길이 |
|---|---|---|
| keyword | 96 | 2.2초 |
| quote | 72 | 3.0초 |
| number | 150 | 2.6초 |
| compare | 84 | 2.8초 |
| list | 64(항목) | 마지막 항목 + hold 1.8초 |
| flash | — | 0.14초 |
| zoom | — | punch 1.6초 · push 조각 끝까지 |
- **size 는 '최대'다**: 글자가 자리 폭(zone 폭 − 80px)을 넘으면 2px 씩 줄인다(하한 52). 줄였으면 build 가 `!` 로 알리고 실제 크기는 `build/compose.json` elements 의 `size` 에 남는다.
- **offset 은 시작을 민다**: `dur` 이면 끝도 같이 밀린다(길이 유지). `until_word` 면 끝은 그 단어에 고정 → 카드가 그만큼 짧아진다. 시작이 until_word 단어를 지나치면 그 뒤에 나오는 같은 말을 찾고, 없으면 기본 길이.
- **가장자리**: 시작은 쇼츠 길이 − 0.2초, 끝은 쇼츠 길이에서 잘린다(잘리면 build 가 `!` 로 알림).
- **카드 찾기**: `resolved.json` 의 `beats` 는 시각순이고 각 항목의 `src_index` = short.json `beats` 의 번호. Studio 의 그래픽 id `gN` 도 N = `beats[N]`(short.json 순서)이다. 줌은 `zooms` 에 따로.
- 이전 상태(before)는 마지막 build 의 `resolved.json` — 한 번도 build 하지 않은 편이면 먼저 build 해서 기준을 남긴다.
build 산출: `resolved.json`(해석된 구간·조각·비트 시각·경고), `captions.auto.json`, `out/<id>.srt`, `build/compose.json`.
