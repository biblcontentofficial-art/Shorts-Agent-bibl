#!/bin/bash
# 쇼츠 에이전트 CLI — HyperFrames(HTML→MP4) 기반 세로 쇼츠 편집
#
#   ./shorts.sh ingest  <원본영상> --name <p> --brand mathclient|bibl|bibl-v2   전사(단어)+얼굴·샷 분석 → projects/<p>/
#   ./shorts.sh status  <p>                                             진행 상황(쇼츠별 단계·QA·제목 승인)
#   ./shorts.sh words   <p> <시작초> <끝초> [--find 구절]                 단어 시각표(경계·skip·at_word 정할 때)
#   ./shorts.sh new     <p> <id> --in 21.7 --out 64.7 [--title "1줄/2줄"] short.json 뼈대
#   ./shorts.sh cut     <p>/<id>      컷확인본(자막·제목 없는 순수 컷) — 맥락 승인용
#   ./shorts.sh build   <p>/<id>      short.json → 컷 + 자막 + 그래픽 → HyperFrames 컴포지션(lint)
#   ./shorts.sh draft   <p>/<id>      빠른 확인 렌더(draft 품질)
#   ./shorts.sh render  <p>/<id>      최종 렌더(브랜드 규격) + 검수 시트
#   ./shorts.sh qa      <p>/<id>      자동 검수(형식·음량·컷 음절·재전사·얼굴·레이아웃·HyperFrames check)
#   ./shorts.sh make    <p>/<id>      build → render → qa 한 번에
#   ./shorts.sh all     <p>           프로젝트의 모든 쇼츠 make
#   ./shorts.sh preview <p>/<id>      HyperFrames Studio 미리보기(백그라운드, http://localhost:3002)
#   ./shorts.sh deliver <p>/<id> [--to-folder] [--sns]   승인본 넘기기(업로드·발행 안 함)
#   <p>/<id> 는 projects/<p>/shorts/<id> 의 줄임(전체 경로도 됨)
set -e
cd "$(dirname "$0")"
export HYPERFRAMES_NO_TELEMETRY=1
export PRODUCER_BROWSER_GPU_MODE=hardware
export PYTHONDONTWRITEBYTECODE=1
PY="caffeinate -dimsu python3"
cmd="$1"; shift || true

sd() {   # 쇼츠 폴더 해석: 경로 그대로 / <p>/<id>
  if [ -d "$1" ]; then echo "$1"; return; fi
  local p="${1%%/*}" id="${1#*/}"
  if [ -d "projects/$p/shorts/$id" ]; then echo "projects/$p/shorts/$id"; return; fi
  echo "쇼츠 폴더를 찾지 못함: $1" >&2; exit 1
}
pd() { if [ -d "$1" ]; then echo "$1"; elif [ -d "projects/$1" ]; then echo "projects/$1"; else echo "프로젝트 없음: $1" >&2; exit 1; fi; }

case "$cmd" in
  ingest)  $PY engine/ingest.py "$@" ;;
  status)  python3 engine/status.py "$(pd "$1")" ;;
  words)   p="$(pd "$1")"; shift; python3 engine/words.py "$p" "$@" ;;
  new)     p="$(pd "$1")"; shift; python3 engine/new.py "$p" "$@" ;;
  cut)     s="$(sd "$1")"; shift; $PY engine/build.py "$s" --cut-only "$@" ;;
  build)   s="$(sd "$1")"; shift; $PY engine/build.py "$s" "$@" ;;
  draft)   s="$(sd "$1")"; shift; $PY engine/render.py "$s" --draft "$@" ;;
  render)  s="$(sd "$1")"; shift; $PY engine/render.py "$s" "$@" ;;
  qa)      s="$(sd "$1")"; shift; $PY engine/qa.py "$s" "$@" ;;
  make)    s="$(sd "$1")"; shift; $PY engine/build.py "$s" "$@" && $PY engine/render.py "$s" && $PY engine/qa.py "$s" ;;
  all)     p="$(pd "$1")"; for s in "$p"/shorts/*/; do [ -f "$s/short.json" ] || continue; case "$(basename "$s")" in _*) continue;; esac
             echo "=== $(basename "$s")"; $PY engine/build.py "$s" && $PY engine/render.py "$s" && $PY engine/qa.py "$s" || echo "!!! $(basename "$s") 실패 — 계속"; done ;;
  preview) s="$(sd "$1")"; H="$PWD/node_modules/.bin/hyperframes"
           (cd "$s/build" && "$H" preview --background --no-open "${@:2}") ;;
  deliver) s="$(sd "$1")"; shift; python3 engine/deliver.py "$s" "$@" ;;
  brands)  ls brands | sed 's/\.json$//' ;;
  *) sed -n '2,19p' "$0"; exit 1 ;;
esac
