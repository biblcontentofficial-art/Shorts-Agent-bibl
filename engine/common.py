#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.py — 쇼츠 에이전트 공용: 경로·브랜드·ffprobe·HyperFrames CLI 호출."""
import json, os, subprocess, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BRANDS = os.path.join(ROOT, "brands")
ASSETS = os.path.join(ROOT, "assets")
TEMPLATES = os.path.join(HERE, "templates")
W, H = 1080, 1920                      # 쇼츠 캔버스


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_json(p, obj):
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def load_brand(name):
    """brands/<name>.json. `extends` 가 있으면 그 브랜드 위에 덮어쓴다(얕은 병합, 한 단계 더 깊은 dict 는 병합)."""
    b = load_json(os.path.join(BRANDS, f"{name}.json"))
    if b is None:
        raise SystemExit(f"브랜드 없음: brands/{name}.json")
    if b.get("extends"):
        base = load_brand(b["extends"])
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k] = {**base[k], **v}
            else:
                base[k] = v
        b = base
    b["name"] = name
    return b


def run(cmd, check=True, capture=True, env=None):
    r = subprocess.run(cmd, capture_output=capture, text=True, env={**os.environ, **(env or {})})
    if check and r.returncode != 0:
        raise RuntimeError(f"명령 실패: {' '.join(map(str, cmd))[:300]}\n{(r.stderr or '')[-1500:]}")
    return r


def probe(path):
    """→ {width, height, fps(float), fps_str, duration, has_audio}"""
    r = run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate",
             "-show_entries", "format=duration", "-of", "json", path])
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s.get("codec_type") == "video"), {})
    num, den = (v.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den or 1)
    return {"width": v.get("width"), "height": v.get("height"), "fps": fps, "fps_str": v.get("r_frame_rate", "30/1"),
            "duration": float(d["format"].get("duration", 0)),
            "has_audio": any(s.get("codec_type") == "audio" for s in d["streams"])}


def hf(args, cwd, check=True):
    """npx hyperframes <args> — 이 하네스의 고정 버전(package.json)을 쓴다. 통계 전송 끔·GPU 캡처."""
    env = {"HYPERFRAMES_NO_TELEMETRY": "1", "PRODUCER_BROWSER_GPU_MODE": "hardware"}
    local = os.path.join(ROOT, "node_modules", ".bin", "hyperframes")
    cmd = [local] if os.path.exists(local) else [shutil.which("npx") or "npx", "hyperframes"]
    r = subprocess.run([*cmd, *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, **env})
    if check and r.returncode != 0:
        raise RuntimeError(f"hyperframes {' '.join(args)} 실패\n{(r.stdout or '')[-2000:]}\n{(r.stderr or '')[-2000:]}")
    return r


def tc(sec):
    """초 → mm:ss.s"""
    sec = max(0.0, float(sec)); m = int(sec // 60)
    return f"{m:02d}:{sec - m * 60:04.1f}"
