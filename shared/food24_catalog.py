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
import unicodedata
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


# ── 제품 구분자: 괄호 안 영문이 든 부분은 norm() 이 지우므로 '(100B)'·'(0.1B)'·'(2000IU)' 가 사라진다.
# 숫자+영문 단위는 따로 뽑아 비교한다. 같은 단위의 값이 상품명에 있는데 다르면 다른 제품이다.
_MARK = re.compile(r"(?<![0-9.])(\d+(?:\.\d+)?)\s*([a-z%]+)?")
RAW_FIELDS = ("raw", "raw_functional", "raw_etc", "raw_capsule")


def markers(s: str) -> set[tuple[str, str]]:
    """'... (100B) <전량수출용>' → {('100', 'b')}, '1,000IU' → {('1000', 'iu')} (숫자, 영문 단위; 단위 없으면 '')"""
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)
    return {(n.rstrip("0").rstrip(".") if "." in n else n, u or "") for n, u in _MARK.findall(s)}


def marker_conflict(name: str, title: str) -> bool:
    """신고 제품명의 '숫자+단위'와 같은 단위가 상품명에 있는데 값이 다르면 True ('0.1B' 제품 ↔ '100B' 상품명)"""
    tm = markers(title)
    for n, u in markers(name):
        if not u:
            continue
        same_unit = {x for x in tm if x[1] == u}
        if same_unit and (n, u) not in same_unit:
            return True
    return False


def _word_starts(title: str) -> tuple[str, set[int], set[int]]:
    """norm(title) 과 그 안에서 단어가 시작하는 위치·끝나는 위치 — 제조사 핵심어는 단어 경계에서만 인정한다
    ('대웅생명과학' 속 '생명과학', '아임힐링' 속 '힐링', '서흥헬스' 속 '서흥' 은 제조사 근거가 아님)"""
    t, starts, ends = "", set(), set()
    s = re.sub(r"\([^)]*[A-Za-z][^)]*\)", " ", title or "").lower()
    for w in re.split(r"[^0-9a-z가-힣]+", s):
        if w:
            starts.add(len(t))
            t += w
            ends.add(len(t))
    return t, starts, ends


def _company_at_word_boundary(key: str, t: str, starts: set[int], ends: set[int], span: tuple[int, int]) -> bool:
    """key 가 단어 시작에서 시작하고, 단어 끝(또는 바로 뒤 제품명 시작)에서 끝나며, 제품명 부분 밖에 있을 때만 True"""
    i = t.find(key)
    while i >= 0:
        j = i + len(key)
        if i in starts and (j in ends or j == span[0]) and (j <= span[0] or i >= span[1]):
            return True
        i = t.find(key, i + 1)
    return False


# ── 검증된 판매 브랜드 별칭: 상품명의 브랜드('정관장')를 신고 제조사('한국인삼공사')로 인정 ─────────────
# 별칭은 DB에서 추정하지 않는다 (정관장 신고 19건 중 2건도 위탁생산). 사람이 근거를 확인해 status=verified 로
# 적은 것만 쓴다. 파일: shared/data/company_aliases.json
ALIAS_FILE = ROOT / "shared" / "data" / "company_aliases.json"


@lru_cache(maxsize=1)
def _aliases() -> dict[str, list[str]]:
    import json
    p = Path(os.environ.get("FOOD24_ALIAS_FILE", ALIAS_FILE))
    try:
        items = json.loads(p.read_text(encoding="utf-8")).get("aliases", [])
    except (OSError, ValueError):
        return {}
    out: dict[str, list[str]] = {}
    for a in items:
        if a.get("status") == "verified" and a.get("evidence") and a.get("verified_at"):
            out.setdefault(_company_key(a["company"]), []).append(re.sub(r"[^0-9a-z가-힣]", "", a["alias"].lower()))
    return out


def _company_match_keys(company: str) -> list[str]:
    keys = _company_keys(company)
    base = keys[-1] if keys else ""
    return keys + [a for a in _aliases().get(base, []) if a not in keys]


def _raw_norm(s: str | None) -> str:
    """원재료 비교용 — 띄어쓰기·전각 문자만 맞추고 괄호·숫자·기호·순서는 그대로 둔다 (제품명용 norm() 을 쓰지 않음)"""
    s = unicodedata.normalize("NFKC", s or "").lower()
    return ",".join(t for t in re.sub(r"\s+", "", s).split(",") if t)


def raw_key(rec) -> tuple[str, ...]:
    return tuple(_raw_norm(rec[k] if k in rec.keys() else None) for k in RAW_FIELDS)


# match_explain() 이 돌려주는 사유 — 매칭 단계에서 실제로 멈춘 곳 (추정하지 않음)
REASONS = {
    "ok": "표시 가능 — 제조사 확인, 같은 제조사에 겹치는 신고 없음",
    "service_off": "서비스 스위치 꺼짐",
    "title_too_short": "상품명이 너무 짧음",
    "no_name_in_title": "상품명 안에 신고 제품명(3글자 이상)이 없음",
    "distinguisher_conflict": "후보 모두 구분자(100B·1000IU 등)가 상품명과 다름",
    "same_name_multiple_companies": "같은 신고명을 여러 제조사가 신고 — 상품명에서 제조사 확인 안 됨",
    "raw_ambiguous": "같은 점수 후보끼리 원재료(4필드)가 달라 단정하지 않음",
    "company_unconfirmed": "신고 제품명은 하나로 정해지지만 상품명에서 제조사 확인 안 됨",
    "sibling_reports": "같은 제조사에 이름이 겹치는 다른 신고가 있어 자동 표시하지 않음",
}


def _siblings(r, con) -> list[str]:
    """같은 제조사(공장 표기 제외)의 다른 신고 중 이름이 서로 포함 관계인 것 — '락토핏 골드' ↔ '락토핏 골드 80포',
    '아이클리어 루테인지아잔틴' ↔ '… 아스타잔틴', 'rTG 오메가3' ↔ '오스틴 rTG 오메가3'"""
    nn, base = r["name_norm"], base_company(r["company"])
    rows = con.execute("select name, name_norm, company from product where report_no != ? and "
                       "(instr(name_norm, ?) > 0 or instr(?, name_norm) > 0) and length(name_norm) >= 3",
                       (r["report_no"], nn, nn)).fetchall()
    same = re.sub(r"\s+", "", r["name"] or "")
    # 정규화하면 같아도 원래 표기가 다르면('골든에센셜(Golden Essential)' ↔ '골든 에센셜') 다른 신고로 본다
    return [x["name"] for x in rows if base_company(x["company"]) == base
            and (x["name_norm"] != nn or re.sub(r"\s+", "", x["name"] or "") != same)]


def match_explain(title: str) -> tuple[dict | None, str]:
    """쇼핑몰 상품명 → (품목제조보고 1건 또는 None, 사유 코드 REASONS).
    record 의 display_ok 가 True 일 때만 자동 표시 대상이다 (company_matched 이고 겹치는 신고 없음).
    서비스 스위치는 캐시 바깥에서 매번 확인한다 — 같은 프로세스에서 켬→끔으로 바꿔도 캐시된 결과가 새지 않게."""
    if not available():
        return None, "service_off"
    rec, reason = _match_cached(title or "", str(_db()))
    return (dict(rec) if rec else None), reason      # 호출부가 고쳐도 캐시가 바뀌지 않게 복사본


@lru_cache(maxsize=2048)
def _match_cached(title: str, db_path: str) -> tuple[dict | None, str]:
    """match_explain 의 본체 (스위치 확인 없음). DB 경로도 캐시 키에 넣는다."""
    t = norm(title or "")
    if len(t) < 3:
        return None, "title_too_short"
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        # limit 을 두지 않는다 — 같은 이름 신고가 40건을 넘으면(밀크씨슬 24개 제조사 등) 정답·충돌 후보가 잘린다
        rows = con.execute("select * from product where length(name_norm) >= 3 and instr(?, name_norm) > 0 "
                           "order by length(name_norm) desc, report_no", (t,)).fetchall()
        if not rows:
            return None, "no_name_in_title"
        rows = [r for r in rows if not marker_conflict(r["name"], title)]   # 구분자(100B·0.1B…)가 다른 신고는 뺀다
        if not rows:
            return None, "distinguisher_conflict"
        tmarks = markers(title)
        tw, starts, ends = _word_starts(title)
        # 제조사는 상품명에서 '제품명 부분 밖'의 '단어 경계'에 있어야 인정한다 — 제조사명이 제품명 속에 든 경우
        # ('고려인삼농축액골드' 속 '고려인삼'), 앞 브랜드가 다른 제품명 일부로 읽히는 경우, 단어 중간('대웅생명과학')을 막는다.
        scored = []
        for r in rows:
            at = tw.find(r["name_norm"])
            span = (at, at + len(r["name_norm"])) if at >= 0 else (0, 0)
            ck = next((k for k in _company_match_keys(r["company"])
                       if _company_at_word_boundary(k, tw, starts, ends, span)), "")
            if ck:
                hits = len({m for m in markers(r["name"]) if m[1]} & tmarks)
                scored.append((len(r["name_norm"]), hits, len(ck), r))
        if scored:
            top_score = max(x[:3] for x in scored)     # 제품명 길이 → 구분자 일치 수 → 제조사 핵심어 길이
            pick, matched = [x[3] for x in scored if x[:3] == top_score], True
        else:
            top = [r for r in rows if len(r["name_norm"]) == len(rows[0]["name_norm"])]
            if len({r["company"] for r in top}) > 1:
                return None, "same_name_multiple_companies"
            pick, matched = top, False
        if len({raw_key(x) for x in pick}) > 1:
            return None, "raw_ambiguous"           # 후보끼리 원재료(주·기능성·기타·캡슐) 중 하나라도 다름
        r = dict(pick[0])
        sib = _siblings(pick[0], con) if matched else []
    finally:
        con.close()
    reason = "ok" if matched and not sib else ("sibling_reports" if matched else "company_unconfirmed")
    r.update(company_matched=matched, display_ok=reason == "ok", reason=reason, siblings=sib[:5])
    r["allergens"] = sorted(allergens_in(" , ".join(filter(None, [r.get("raw"), r.get("raw_functional"),
                                                                    r.get("raw_etc"), r.get("raw_capsule")]))))
    return r, reason


def match(title: str) -> dict | None:
    """쇼핑몰 상품명 → 품목제조보고 1건 (없거나 애매하면 None). 표시 여부는 record['display_ok'] 로 판단."""
    return match_explain(title)[0]


match.cache_clear = _match_cached.cache_clear    # 기존 테스트·호출부 호환
match_explain.cache_clear = _match_cached.cache_clear


def allergen_filter_enabled() -> bool:
    """원재료 기반 알레르기 제외 — 매칭 표시와 따로 켠다 (.env FOOD24_ALLERGEN_FILTER, 기본 꺼짐). 아직 연결 안 함."""
    import shared.config  # noqa: F401
    return available() and os.getenv("FOOD24_ALLERGEN_FILTER", "0").strip().lower() in {"1", "true", "yes", "on"}


def public_info(rec: dict) -> dict:
    """카드·상세에 붙일 요약 (원재료는 길이 제한)"""
    raw = rec.get("raw") or ""
    if rec.get("raw_functional"):
        raw = f"{raw} / 기능성: {rec['raw_functional']}"
    return {"name": rec.get("name"), "company": rec.get("company"), "item_type": rec.get("item_type") or rec.get("class4"),
            "raw": raw[:400], "expiry": rec.get("expiry") or None, "report_no": rec.get("report_no"),
            "allergens": [ALLERGEN_RULES[a]["label"] for a in rec.get("allergens", [])],
            "company_matched": rec.get("company_matched", False), "display_ok": rec.get("display_ok", False),
            "source": SOURCE_NAME}
