"""지역특산물·농가맛집 카탈로그 (var/knowledge/*.json) 검색.

scripts/update_local_knowledge.py 가 농사로 Open API에서 만든 파일만 읽는다.
특산물이라는 표시는 '지역 + 품목'이 공공 자료와 함께 맞을 때만 붙인다 (지역 없는 '사과'에는 붙이지 않음).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "var" / "knowledge"
SIDO = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시", "광주": "광주광역시",
    "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시", "경기": "경기도", "강원": "강원",
    "충북": "충청북도", "충남": "충청남도", "전북": "전라북도", "전남": "전라남도", "경북": "경상북도",
    "경남": "경상남도", "제주": "제주",
}
_PARTICLE = re.compile(r"(에서|으로|이랑|랑|로|를|을|은|는|이|가|에|와|과|도|의)$")
_cache: dict = {}


def _dir() -> Path:
    return Path(os.environ.get("LOCAL_KNOWLEDGE_DIR", DEFAULT_DIR))


def _load(name: str, key: str) -> list[dict]:
    p = _dir() / name
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return []
    c = _cache.get(str(p))
    if not c or c[0] != mtime:
        _cache[str(p)] = c = (mtime, json.loads(p.read_text(encoding="utf-8")).get(key, []))
    return c[1]


def specialties() -> list[dict]:
    return _load("local_specialties.json", "specialties")


def restaurants() -> list[dict]:
    return _load("farm_restaurants.json", "restaurants")


def available() -> bool:
    return bool(specialties() or restaurants())


def region_keys(area: str) -> set[str]:
    """'경상북도 문경시' → {'경상북도','경북','문경시','문경'}"""
    keys = set()
    for w in re.split(r"[\s,/·>]+", area or ""):
        if not w:
            continue
        keys.add(w)
        if len(w) > 2 and w[-1] in "시군구도":
            keys.add(w[:-1])
        for short, full in SIDO.items():
            if w.startswith(full) or w == short or (len(w) > 3 and w.startswith(short) and w.endswith(("도", "시"))):
                keys.update({short, full})
    return keys


def tokens(text: str) -> list[str]:
    out = []
    for t in re.split(r"[^\w]+", text or ""):
        t = _PARTICLE.sub("", t) if len(t) > 2 else t
        if t:
            out.append(t)
    return out


def find_region(text: str) -> str | None:
    """질문 속 지역 단어 (데이터에 있는 지역만). 시군구 단위가 시도보다 우선."""
    known: set[str] = set()
    for row in specialties() + restaurants():
        known |= region_keys(row.get("region", ""))
    toks = tokens(text)
    hits = [t for t in toks if t in known] + [t for t in toks if t in SIDO and t not in known]
    if not hits:
        return None
    return sorted(hits, key=lambda t: (t not in SIDO, len(t)), reverse=True)[0]


def in_region(rows: list[dict], region: str) -> list[dict]:
    return [r for r in rows if region in region_keys(r.get("region", ""))]


def specialty_for(product_text: str) -> dict | None:
    """'문경 감홍사과' → 문경시 '사과' 특산물. 지역과 품목이 모두 맞아야 한다."""
    region = find_region(product_text)
    if not region:
        return None
    flat = re.sub(r"\s+", "", product_text or "")
    best = None
    for r in in_region(specialties(), region):
        name = re.sub(r"\s+", "", r.get("name", ""))
        # 특산물 이름에서 지역명을 뺀 품목어 ('문경사과' → '사과')
        item = name
        for k in sorted(region_keys(r.get("region", "")), key=len, reverse=True):
            item = item.replace(k, "")
        item = item or name
        if len(item) >= 2 and item in flat:
            if best is None or len(item) > best[0]:
                best = (len(item), r)
    return best[1] if best else None


NON_FOOD = re.compile(r"공예|도자기|한지|목공|죽세|체험|축제|관광|숙박|화훼|분재|가구|옹기|섬유|원목")


def is_food(row: dict) -> bool:
    return not NON_FOOD.search(row.get("name", ""))


def menu_names(rest: dict) -> list[str]:
    """농가맛집 본문에서 '대표 상차림' 아래의 짧은 메뉴 제목들만 ('안골반상', '숲속반상')"""
    lines = [l.strip(" :：") for l in (rest.get("detail") or "").split("\n") if l.strip()]
    start = next((i for i, l in enumerate(lines) if "대표" in l and any(w in l for w in ("상차림", "메뉴"))), None)
    if start is None:
        return []
    out = []
    for l in lines[start + 1:]:
        if any(w in l for w in ("매력", "이야기", "찾아오", "체험", "대표가")):
            break
        if 2 <= len(l) <= 15 and not l.endswith(("다", ".")):
            out.append(l)
    return out[:4]
