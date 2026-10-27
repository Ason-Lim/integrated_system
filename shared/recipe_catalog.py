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
    "음식", "전통", "지역",
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
    tags = _flat(" ".join(r.get("tags", [])) + (r.get("category") or "") + (r.get("region") or "") + (r.get("house") or ""))
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
            score += 4 if ft in _flat((r.get("region") or "") + (r.get("house") or "")) else 2
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
        hay = (_flat(r.get("name", "")) + "|" + "|".join(_flat(i.get("name", "")) for i in r.get("ingredients", []))
               + "|" + _flat((r.get("region") or "") + (r.get("house") or "") + " ".join(r.get("tags", []))))
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


def by_region(region: str, limit: int = 3) -> list[dict]:
    """향토·종가음식 중 지역(시도/시군구 단어)이 맞는 레시피"""
    key = _flat(region)
    out = [r for r in _load() if r.get("region") and key in _flat(r["region"])]
    out.sort(key=lambda r: (r.get("source") != "nongsaro_head", not r.get("steps")))
    return out[:limit]


def by_ingredient(names: list[str], limit: int = 3) -> list[dict]:
    """재료 이름으로 찾기 ('감' → 감·단감·곶감·대봉감 재료). 한 글자 품목은 재료명 끝이 일치하는 짧은 이름만."""
    keys = [_flat(n) for n in names if n]
    def hit(ing: str) -> bool:
        ing = _flat(ing)
        return any(ing == k or (len(k) >= 2 and k in ing) or (len(k) == 1 and len(ing) <= 3 and ing.endswith(k))
                   for k in keys)
    def pos(r: dict) -> int:   # 해당 재료가 앞쪽(주재료)에 있을수록 우선
        return next((n for n, i in enumerate(r.get("ingredients", [])) if hit(i.get("name", ""))), 99)
    cands = [r for r in _load() if pos(r) < 99]
    cands.sort(key=lambda r: (not r.get("steps"), pos(r), r.get("source") not in ("foodsafety", "epis")))
    out, seen = [], set()
    for r in cands:
        base = re.sub(r"\s*[\[(].*?[\])]\s*", "", r.get("name", "")).strip()   # '감식초 [방법1]' → '감식초'
        if base in seen:
            continue
        seen.add(base)
        out.append(r)
        if len(out) >= limit:
            break
    return out
