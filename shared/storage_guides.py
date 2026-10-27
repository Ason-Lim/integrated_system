"""식재료 보관·손질·고르는 법 카탈로그 (var/knowledge/storage_guides.json) 검색.

scripts/update_storage_guides.py 가 농촌진흥청 농사로 '이달의 식재료' Open API에서 만든 파일만 읽는다.
공공 자료에 없는 식재료는 '찾지 못함'으로 답하고, 보관 기간 등을 지어내지 않는다.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "var" / "knowledge" / "storage_guides.json"
_PARTICLE = re.compile(r"(으로|이랑|랑|로|를|을|은|는|이|가|에|와|과|도|의)$")
_cache: dict = {"mtime": None, "path": None, "guides": []}


def _path() -> Path:
    return Path(os.environ.get("STORAGE_GUIDE_PATH", DEFAULT_PATH))


def _load() -> list[dict]:
    p = _path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        _cache.update(mtime=None, path=None, guides=[])
        return []
    if _cache["mtime"] != mtime or _cache["path"] != str(p):
        _cache.update(mtime=mtime, path=str(p),
                      guides=json.loads(p.read_text(encoding="utf-8")).get("guides", []))
    return _cache["guides"]


def available() -> bool:
    return bool(_load())


def tokens(text: str) -> list[str]:
    out = []
    for t in re.split(r"[^\w]+", text or ""):
        t = _PARTICLE.sub("", t) if len(t) > 2 else t
        if t:
            out.append(t)
    return out


def _hit(name: str, tok: str) -> bool:
    if tok == name:
        return True
    if len(name) >= 2 and name in tok:          # '설향딸기' ⊃ '딸기'
        return True
    if len(name) == 1 and len(tok) <= 4 and tok.endswith(name):   # '대봉감'·'단감' → '감' ('감자'는 제외)
        return True
    return len(tok) >= 2 and tok in name        # '딸기' ⊂ '딸기(설향)'


def find(text: str) -> tuple[dict, str] | None:
    """질문 문장에서 식재료를 찾아 (안내, 질문 속 단어)를 돌려준다."""
    best = None
    toks = tokens(text)
    for g in _load():
        for name in [g.get("name", "")] + list(g.get("aliases") or []):
            name = name.strip()
            if not name:
                continue
            for tok in toks:
                if _hit(name, tok):
                    # 정확히 같은 이름 > 질문 단어에 포함된 이름(긴 것 우선) > 이름에 포함된 질문 단어(짧은 것 우선)
                    rank = 2 if tok == name else 1 if name in tok else 0
                    score = (rank, len(name) if rank else -len(name))
                    if best is None or score > best[0]:
                        best = (score, g, tok)
    return (best[1], best[2]) if best else None
