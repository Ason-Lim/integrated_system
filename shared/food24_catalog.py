"""식품정보24 품목제조보고 DB(var/knowledge/food24_products.sqlite) 조회와 원재료 알레르기 판정.

- 쇼핑몰 상품명과 품목명을 맞출 때는 보수적으로: 품목명(3자 이상)이 상품명에 들어 있고,
  제조사가 상품명에 있거나 같은 이름의 품목이 하나뿐일 때만 '같은 제품'으로 본다.
- 알레르기는 원재료를 쉼표·괄호 단위로 나눠 단어 기준으로 판정한다 ('밀크씨슬'·'밀납' ≠ 밀).
- 품목제조보고에는 '같은 시설에서 제조' 같은 교차오염 표시가 없으므로 그 부분은 계속 확인 필요로 둔다.
- 원재료는 일부만 공개된다(예: 아몬드 음료의 원재료가 '음료베이스'로만 표기). 그래서 성분이 '있음'은
  제외 근거로 쓰지만, '없음'은 근거로 쓰지 않는다 (2026-10-27 C002 전체 파일로 확인).
"""
from __future__ import annotations

import os
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "var" / "knowledge" / "food24_products.sqlite"
SOURCE_NAME = "식품의약품안전처 품목제조보고 (식품정보24 제공)"

# 알레르기 → 원재료 단어 규칙 (단어 전체 일치 ^…$ 또는 시작/포함 패턴)
ALLERGEN_RULES: dict[str, dict] = {
    "nuts": {"label": "견과류·땅콩", "exact": {"땅콩", "호두", "잣", "아몬드", "캐슈넛", "피스타치오", "헤이즐넛",
                                              "마카다미아", "피칸", "브라질너트", "견과", "견과류"},
             "prefix": ("땅콩", "호두", "아몬드", "캐슈", "피스타치오", "헤이즐넛", "마카다미아", "피칸", "잣가루", "혼합견과")},
    "gluten": {"label": "밀(글루텐)", "exact": {"밀", "소맥", "소맥분", "통밀", "호밀", "보리"},
               "prefix": ("밀가루", "소맥", "통밀", "밀전분", "밀글루텐", "밀단백", "호밀", "보리", "맥아"),
               "contains": ("글루텐",)},
    "dairy": {"label": "우유·유제품", "exact": {"우유", "버터", "치즈", "연유", "유당", "유청", "분유", "생크림", "요구르트"},
              "prefix": ("우유", "유청", "유당", "탈지분유", "전지분유", "조제분유", "가공버터", "버터", "치즈", "카제인",
                         "연유", "요구르트", "발효유", "유크림", "유단백", "크림치즈"),
              "contains": ("분유", "유청단백", "우유단백")},
    "egg": {"label": "달걀(난류)", "exact": {"계란", "달걀", "전란", "난백", "난황", "난류"},
            "prefix": ("계란", "달걀", "전란", "난백", "난황", "전란액", "건조난")},
    "shellfish": {"label": "갑각류(새우·게)", "exact": {"새우", "게", "꽃게", "대게", "킹크랩", "랍스터", "갑각류"},
                  "prefix": ("새우", "꽃게", "대게", "게살", "게맛", "크랩", "랍스터", "크릴")},
}


def _db() -> Path:
    return Path(os.environ.get("FOOD24_DB_PATH", DEFAULT_DB))


def available() -> bool:
    return _db().exists()


def norm(s: str) -> str:
    s = re.sub(r"\([^)]*[A-Za-z][^)]*\)", "", s or "")
    return re.sub(r"[^0-9a-z가-힣]", "", s.lower())


def ingredients(raw: str) -> list[str]:
    """'밀가루(미국산),설탕,전란액(국산)' → ['밀가루', '미국산', '설탕', '전란액', '국산'] (괄호 안도 단어로)"""
    toks = re.split(r"[,，()\[\]{}/·:;]|\s+및\s+", raw or "")
    return [re.sub(r"[\d.%]+$", "", t).strip() for t in toks if t and t.strip()]


def allergens_in(raw: str) -> set[str]:
    found = set()
    for tok in ingredients(raw):
        t = tok.replace(" ", "")
        for key, rule in ALLERGEN_RULES.items():
            if t in rule.get("exact", ()) or t.startswith(tuple(rule.get("prefix", ()))) \
                    or any(c in t for c in rule.get("contains", ())):
                found.add(key)
    return found


def _company_key(company: str) -> str:
    c = re.sub(r"\(주\)|주식회사|㈜|\(유\)|유한회사|농업회사법인|영농조합법인|\s", "", company or "")
    return c.lower()


@lru_cache(maxsize=2048)
def match(title: str) -> dict | None:
    """쇼핑몰 상품명 → 같은 제품으로 볼 수 있는 품목제조보고 1건 (없거나 애매하면 None)"""
    if not available() or not title:
        return None
    t = norm(title)
    if len(t) < 3:
        return None
    con = sqlite3.connect(f"file:{_db()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "select * from product where length(name_norm) >= 3 and instr(?, name_norm) > 0 "
            "order by length(name_norm) desc limit 40", (t,)).fetchall()
    finally:
        con.close()
    if not rows:
        return None
    best_len = len(rows[0]["name_norm"])
    top = [r for r in rows if len(r["name_norm"]) == best_len]
    with_company = [r for r in top if (ck := _company_key(r["company"])) and len(ck) >= 2 and ck in t]
    pick = with_company or (top if len({r["company"] for r in top}) == 1 else [])
    if not pick:
        return None          # 같은 이름을 여러 제조사가 쓰면 어느 제품인지 단정하지 않는다
    r = dict(pick[0])
    r["company_matched"] = bool(with_company)
    r["allergens"] = sorted(allergens_in(" , ".join(filter(None, [r.get("raw"), r.get("raw_functional"),
                                                                    r.get("raw_etc"), r.get("raw_capsule")]))))
    return r


def public_info(rec: dict) -> dict:
    """카드·상세에 붙일 요약 (원재료는 길이 제한)"""
    raw = rec.get("raw") or ""
    if rec.get("raw_functional"):
        raw = f"{raw} / 기능성: {rec['raw_functional']}"
    return {"name": rec.get("name"), "company": rec.get("company"), "item_type": rec.get("item_type") or rec.get("class4"),
            "raw": raw[:400], "expiry": rec.get("expiry") or None, "report_no": rec.get("report_no"),
            "allergens": [ALLERGEN_RULES[a]["label"] for a in rec.get("allergens", [])],
            "company_matched": rec.get("company_matched", False), "source": SOURCE_NAME}
