"""규칙 기반 NLU — LLM 이 없거나 실패할 때도 항상 동작하는 기본 경로.

commerce_ai/intent_analyzer.py(예산·대상·상황·우선순위)와 food-nlu 시스템 프롬프트의
ACTION 우선순위 규칙(몰 → 알레르기 → 최저가 → 레시피 → 영양 → 선물 → 일반)을 코드로 옮겼다.
슬롯 키는 food-nlu slot_definition 과 동일하게 맞췄다 (mall, product, category, purpose, recipient,
quantity, allergen, taste, diet_goal) + budget_min/budget_max/priority/occasion.
"""
from __future__ import annotations

import re

from shared.models import Intent
from shared.query_expansion import filter_expansion

MALLS = {
    "coupang": ["쿠팡"], "naver": ["네이버", "스마트스토어"], "emart": ["이마트"],
    "ssg": ["SSG", "쓱", "쓱닷컴"], "marketkurly": ["마켓컬리", "컬리"],
}
RECIPIENTS = {
    "senior": ["부모님", "엄마", "아빠", "어머니", "아버지", "어르신", "시부모"],
    "friends": ["친구", "지인", "동료"],
    "business": ["거래처", "고객사", "상사", "임직원", "직원"],
    "kids": ["아이", "자녀", "초등", "아기"],
    "partner": ["연인", "남자친구", "여자친구", "애인", "와이프", "남편"],
    "self": ["혼자", "자취", "1인"],
}
OCCASIONS = {
    "birthday": ["생일", "생신"], "chuseok": ["추석", "한가위"], "seollal": ["설날", "설 선물", "명절"],
    "thanks": ["감사", "답례"], "housewarming": ["집들이"], "camping": ["캠핑", "숯불", "바베큐"],
    "parents_day": ["어버이날"], "party": ["홈파티", "파티", "손님"],
}
ALLERGENS = {"nuts": ["견과", "땅콩"], "gluten": ["글루텐", "밀가루"], "dairy": ["우유", "유제품"],
             "egg": ["계란", "달걀"], "shellfish": ["갑각류", "새우", "게"]}
DIET = {
    "low_sugar": ["저당", "무설탕", "당 없는", "설탕 없는"],
    "low_sodium": ["저염", "저나트륨", "나트륨 낮은"],
    "organic": ["유기농", "친환경"],
    "vegan": ["비건", "채식"],
}
STOPWORDS = {
    "추천해줘", "추천해", "추천", "알려줘", "보여줘", "해줘", "주세요", "없을까", "있어", "좀", "것", "거",
    "먹을", "만한", "오늘", "이번", "진짜", "너무", "제일", "잘", "아무거나", "골라줘", "꼽아줘",
    "최저가", "가성비", "좋은", "맛있는", "저렴한", "싼", "선물", "선물용", "에서", "살", "수", "있는",
    "이하", "이상", "선물", "생신", "세트", "정도", "사고", "싶어", "중에", "용", "뭐", "어떤", "괜찮은", "할만한",
}
VERBISH = re.compile(r"(는데|인데|워|해서|하고|려고|니까|으면|던|할|갈|먹을|먹기|싶은|드릴|줄)$")
NUM_KR = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}


def parse_budget(text: str) -> tuple[int | None, int | None]:
    t = text.replace(",", "").replace(" ", "")

    def won(num: str, unit: str | None) -> int:
        v = float(num)
        return int(v * 10000) if unit and "만" in unit else int(v)

    # 범위: 2~5만원, 2만~5만원, 2-5만
    m = re.search(r"(\d+(?:\.\d+)?)(만)?원?[~\-](\d+(?:\.\d+)?)(만)?원", t)
    if m:
        lo = won(m.group(1), m.group(2) or m.group(4))
        hi = won(m.group(3), m.group(4))
        return lo, hi

    # 이하/미만/안쪽/까지/이내
    m = re.search(r"(\d+(?:\.\d+)?)(만)?원?(이하|미만|아래|안쪽|내|까지|이내)", t)
    if m:
        return None, won(m.group(1), m.group(2))

    # 이상/넘는/초과/부터
    m = re.search(r"(\d+(?:\.\d+)?)(만)?원?(이상|넘는|초과|부터)", t)
    if m:
        return won(m.group(1), m.group(2)), None

    # ~대: 1만원대, 3만 원대
    m = re.search(r"(\d+(?:\.\d+)?)(만)?원대", t)
    if m:
        v = won(m.group(1), m.group(2))
        step = 10000 if "만" in (m.group(2) or "") else 1000
        return v, v + step - 1

    # 전후/정도/쯤: 대략 3만원 전후, 1.5만 원쯤
    m = re.search(r"(?:대략|약|대충)?\s*(\d+(?:\.\d+)?)(만)?원?\s*(전후|정도|쯤|근처)", t)
    if m:
        v = won(m.group(1), m.group(2))
        margin = int(v * 0.15)  # ±15%
        return max(0, v - margin), v + margin

    # 단순: 예산 3만원, 3만 원
    m = re.search(r"(?:예산|가격)[은는이가]?\s*(\d+(?:\.\d+)?)(만)?원?", t)
    if m:
        return None, won(m.group(1), m.group(2))

    # 숫자만 + 만: 3만
    m = re.search(r"(\d+(?:\.\d+)?)만(?:원)?(?!\d)", t)
    if m:
        return None, int(float(m.group(1)) * 10000)

    return None, None


def _first(table: dict[str, list[str]], text: str) -> str | None:
    for code, words in table.items():
        if any(w in text for w in words):
            return code
    return None


def parse_quantity(text: str) -> int | None:
    m = re.search(r"(\d+)\s*(?:개|가지)만", text)
    if m:
        return int(m.group(1))
    for k, v in NUM_KR.items():
        if re.search(k + r"\s*(?:개|가지)만", text):
            return v
    return None


def product_terms(text: str) -> str:
    cleaned = re.sub(r"\d+(?:\.\d+)?\s*만?\s*원?\s*[~\-]\s*\d+(?:\.\d+)?\s*만?\s*원?\S*", " ", text)
    cleaned = re.sub(r"\d+(?:\.\d+)?\s*만?\s*원\S*", " ", cleaned)
    cleaned = re.sub(r"\d+(?:\.\d+)?\s*만\S*", " ", cleaned)
    cleaned = re.sub(r"(\d+|" + "|".join(NUM_KR) + r")\s*(개|가지)만?", " ", cleaned)
    cleaned = re.sub(r"[^\w가-힣\s]", " ", cleaned)
    words = []
    all_kw = {w for ws in list(MALLS.values()) + list(RECIPIENTS.values()) + list(OCCASIONS.values()) for w in ws}
    for tok in cleaned.split():
        if VERBISH.search(tok):
            continue
        base = re.sub(r"(에서|으로|에게|한테|을|를|은|는|용|께|에)$", "", tok)
        if len(base) >= 3:
            base = re.sub(r"로$", "", base)
        if len(base) < 2 or base in STOPWORDS or tok in STOPWORDS or base in all_kw:
            continue
        words.append(base)
    return " ".join(words[:4])


def parse(text: str) -> Intent:
    slots: dict = {}
    mall = _first(MALLS, text)
    if mall:
        slots["mall"] = mall
    lo, hi = parse_budget(text)
    if lo:
        slots["budget_min"] = lo
    if hi:
        slots["budget_max"] = hi
    rec = _first(RECIPIENTS, text)
    if rec:
        slots["recipient"] = rec
    occ = _first(OCCASIONS, text)
    if occ:
        slots["occasion"] = occ
    q = parse_quantity(text)
    if q:
        slots["quantity"] = q
    if any(w in text for w in ["최저가", "제일 싸", "가장 싼", "싼 거", "저렴", "싸게", "너무 비싸지", "비싸지 않게", "부담 없"]):
        slots["priority"] = "price"
    elif any(w in text for w in ["가성비", "합리", "적당한 가격"]):
        slots["priority"] = "value"
    elif any(w in text for w in ["프리미엄", "고급", "품질", "고당도", "좋은 거"]):
        slots["priority"] = "quality"
    if any(w in text for w in ["신뢰", "후기", "리뷰", "믿을", "인기"]):
        slots.setdefault("priority", "trust")
    if "선물" in text:
        slots["purpose"] = "gift"
    # 알레르기 / 식이 조건 (복합 조건 지원)
    allergen = _first(ALLERGENS, text) if any(w in text for w in ["알레르기", "못 먹", "빼고", "없는", "제외", "프리", "프리이면서"]) else None
    if allergen:
        slots["allergen"] = allergen
    diet = _first(DIET, text)
    if diet:
        slots["diet"] = diet
    terms = product_terms(text)
    if occ == "camping" and terms and "캠핑" not in terms:
        terms = "캠핑 " + terms
    if terms:
        slots["product"] = terms
        # SAFE-QE: 원문에 없는 속성 확장은 요구로 승격하지 않는다 (shadow 지표만 기록)
        slots["_expansion"] = filter_expansion(text, terms.split(), text)

    # ACTION — food-nlu 시스템 프롬프트의 우선순위 그대로
    if mall:
        action = "recommend_in_mall"
    elif allergen:
        action = "allergy"
        if slots.get("product"):
            drop = set(ALLERGENS.get(allergen, []))
            slots["product"] = " ".join(t for t in slots["product"].split() if t not in drop) or slots["product"]
    elif slots.get("priority") == "price":
        action = "lowest_price"
    elif any(w in text for w in ["만들 수 있는", "해먹을", "요리법", "레시피"]):
        action = "recipe"
    elif any(w in text for w in ["영양", "칼로리", "성분", "나트륨"]):
        action = "nutrition"
    elif "선물" in text or rec in {"senior", "business", "partner"} or occ in {"chuseok", "seollal", "thanks", "birthday", "parents_day"}:
        action = "recommend_gift"
        slots.setdefault("purpose", "gift")
    else:
        action = "recommend_food"

    context = {"camping": "situation_camping", "party": "situation_party"}.get(occ or "") or \
        {"kids": "situation_family_kids", "senior": "situation_family_senior", "self": "situation_solo"}.get(rec or "")
    conf = 0.55 + 0.1 * min(len(slots), 4)
    return Intent(action=action, context=context, slots=slots, confidence=round(min(conf, 0.9), 2), source="rule")
