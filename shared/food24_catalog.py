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


def in_service() -> bool:
    """수집한 품목제조보고를 서비스(알레르기 제외·상세 원재료)에 쓸지 — .env FOOD24_IN_SERVICE (기본 꺼짐).
    DB 파일이 생겼다고 저절로 서비스 동작이 바뀌지 않게 한다 (2026-10-28)."""
    import shared.config  # noqa: F401  (.env 로드)
    return os.getenv("FOOD24_IN_SERVICE", "0").strip().lower() in {"1", "true", "yes", "on"}


def available() -> bool:
    return in_service() and _db().exists()


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
    c = re.sub(r"\(주\)|주식회사|㈜|\(유\)|\(재\)|유한회사|농업회사법인|영농조합법인|^\s*주\)|\(주\s*$", "", company or "")
    return re.sub(r"[^0-9a-z가-힣]", "", c.lower())        # '주)팜크로스' → '팜크로스', 'A,B' 의 쉼표 등


# 제조사명 뒤 공장 지역 (품목제조신고에 자주 나오는 시·군 두 글자)
FACTORY_REGIONS = set("음성 안성 포천 천안 세종 익산 금산 청주 오송 오창 진천 충주 제천 원주 춘천 횡성 홍천 평택 화성 이천 "
                      "김포 파주 양주 용인 광주 대전 대구 부산 울산 인천 수원 아산 공주 논산 당진 서산 예산 진안 완주 정읍 "
                      "김제 군산 전주 나주 목포 순천 여수 광양 경산 구미 김천 상주 안동 영천 칠곡 창원 김해 양산 밀양 함안 "
                      "제주 장성 영암 강화 장수 남원 문경 홍성 보은 옥천 영동 괴산 증평 안산 시흥 부천 의왕 오산 하남 "
                      "여주 연천 가평 양평 철원 강릉 속초 삼척 영월 정선 평창".split())


def _company_keys(company: str) -> list[str]:
    """제조사 확인에 쓸 핵심어 (긴 것부터). 공장 표기는 판매처 상품명에 거의 안 나오므로 뗀 것도 쓴다.
    '콜마비앤에이치(주)음성공장' → ['콜마비앤에이치음성공장', '콜마비앤에이치음성', '콜마비앤에이치']
    '노바렉스2공장' → ['노바렉스2공장', '노바렉스'] / '쎌바이오텍 1공장, 2공장' → [..., '쎌바이오텍']"""
    full = _company_key(company)
    keys = [full]
    k1 = re.sub(r"(?:제?\d+)?공장(?:(?:제?\d+)?공장|\d)*$", "", full)
    if k1 != full:
        keys.append(k1)
        if k1[-2:] in FACTORY_REGIONS and len(k1) - 2 >= 2:
            keys.append(k1[:-2])        # '음성공장'·'포천제2공장' 같은 지역+공장
    return [k for k in dict.fromkeys(keys) if len(k) >= 2]


def base_company(company: str) -> str:
    """공장 표기를 뗀 제조사 — 같은 회사의 다른 공장인지 비교할 때"""
    return _company_keys(company)[-1] if _company_keys(company) else ""


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
    # 제조사는 상품명에서 '제품명 부분을 뺀 나머지'에 있어야 인정한다 — 제조사명이 제품명 속에 들어 있는 경우
    # ('고려인삼농축액골드' 속 '고려인삼')나, 앞의 브랜드가 다른 제품명의 일부로 읽히는 경우를 막는다.
    scored = []
    for r in rows:
        rest = t.replace(r["name_norm"], " ", 1)
        ck = next((k for k in _company_keys(r["company"]) if k in rest), "")
        if ck:
            scored.append((len(r["name_norm"]), len(ck), r))
    if scored:
        top_score = max(x[:2] for x in scored)     # 제품명이 긴 것 → 제조사 핵심어가 긴 것
        pick, matched = [x[2] for x in scored if x[:2] == top_score], True
    else:
        best_len = len(rows[0]["name_norm"])
        top = [r for r in rows if len(r["name_norm"]) == best_len]
        pick, matched = (top if len({r["company"] for r in top}) == 1 else []), False
    if not pick:
        return None          # 같은 이름을 여러 제조사가 쓰면 어느 제품인지 단정하지 않는다
    if len({norm(x["raw"] or "") for x in pick}) > 1:
        return None          # 같은 제조사가 기호만 다른 이름('밀크씨슬'/'밀크씨슬+')으로 원재료가 다른 제품을 신고 — 단정하지 않는다
    r = dict(pick[0])
    r["company_matched"] = matched
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
