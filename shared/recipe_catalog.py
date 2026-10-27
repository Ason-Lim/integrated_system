"""로컬 레시피 카탈로그 (var/recipes/recipes.json) 검색.

scripts/update_recipes.py 가 공공 레시피 DB(식품안전나라·농식품정보누리)를 내려받아 만든 파일만 읽는다.
대화 중에는 외부 API를 부르지 않으며, 레시피 내용은 출처 원문 그대로 보여준다(생성·보정하지 않음).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "var" / "recipes" / "recipes.json"

# 검색어에서 뺄 말 — 요리 이름/재료만 남긴다
STOP = {
    "레시피", "레시피로", "요리", "요리법", "만드는", "만드는법", "만들기", "만들", "만들어", "방법", "법",
    "장보기", "장보기로", "알려줘", "알려", "추천", "추천해줘", "해줘", "해먹을", "해먹기", "해먹", "먹을", "있는",
    "수", "좀", "보기", "어떻게", "간단한", "쉬운", "맛있는", "집에서", "오늘", "저녁", "점심", "아침",
}


def _path() -> Path:
    return Path(os.environ.get("RECIPE_CATALOG_PATH", DEFAULT_PATH))


_cache: dict = {"mtime": None, "path": None, "recipes": [], "meta": {}}


def _load() -> list[dict]:
    p = _path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        _cache.update(mtime=None, path=None, recipes=[], meta={})
        return []
    if _cache["mtime"] != mtime or _cache["path"] != str(p):
        doc = json.loads(p.read_text(encoding="utf-8"))
        _cache.update(mtime=mtime, path=str(p), recipes=doc.get("recipes", []),
                      meta={k: v for k, v in doc.items() if k != "recipes"})
    return _cache["recipes"]


def available() -> bool:
    return bool(_load())


def meta() -> dict:
    _load()
    return dict(_cache["meta"])


def _flat(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def terms(query: str) -> list[str]:
    """'파스타 레시피 장보기' → ['파스타'], '감자로 해먹을 요리' → ['감자']"""
    out = []
    for tok in re.split(r"[\s,./]+", query or ""):
        if tok in STOP:
            continue
        tok = re.sub(r"(으로|이랑|랑|로|를|을|은|는|이|가|에|와|과|도)$", "", tok) if len(tok) > 2 else tok
        if tok and tok not in STOP and tok not in out:
            out.append(tok)
    return out


def _score(r: dict, ts: list[str], phrase: str) -> int:
    name = _flat(r.get("name", ""))
    ings = [_flat(i.get("name", "")) for i in r.get("ingredients", [])]
    tags = _flat(" ".join(r.get("tags", [])) + (r.get("category") or ""))
    score = 0
    if phrase and name == phrase:
        score += 60
    elif phrase and len(phrase) >= 2 and phrase in name:
        score += 30
    for t in ts:
        ft = _flat(t)
        if ft in name:
            score += 12
        if any(ft == i for i in ings):
            score += 6
        elif any(ft in i for i in ings):
            score += 3
        if ft in tags:
            score += 2
    if score and r.get("steps"):
        score += 2
    return score


def search(query: str, limit: int = 3) -> list[dict]:
    recipes = _load()
    ts = terms(query)
    if not recipes or not ts:
        return []
    phrase = _flat("".join(ts))
    scored = [(s, r) for r in recipes if (s := _score(r, ts, phrase)) > 0]
    # 모든 검색어가 이름이나 재료에 들어있는 레시피를 우선
    def covers(r: dict) -> bool:
        hay = _flat(r.get("name", "")) + "|" + "|".join(_flat(i.get("name", "")) for i in r.get("ingredients", []))
        return all(_flat(t) in hay for t in ts)
    scored.sort(key=lambda x: (covers(x[1]), x[0], -len(x[1].get("name", ""))), reverse=True)
    out, names = [], set()
    for _, r in scored:
        if r["name"] in names:
            continue
        names.add(r["name"])
        out.append(r)
        if len(out) >= limit:
            break
    return out


def find(name_or_id: str) -> dict | None:
    key = _flat(name_or_id)
    for r in _load():
        if r.get("id") == name_or_id or _flat(r.get("name", "")) == key:
            return r
    return None
