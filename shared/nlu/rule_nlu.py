"""규칙 기반 NLU — LLM 이 없거나 실패할 때도 항상 동작하는 기본 경로.

commerce_ai/intent_analyzer.py(예산·대상·상황·우선순위)와 food-nlu 시스템 프롬프트의
ACTION 우선순위 규칙(몰 → 알레르기 → 최저가 → 레시피 → 영양 → 선물 → 일반)을 코드로 옮겼다.
그 앞에 정보·비교 질문(compare_info: "뭐가 달라?", "차이가 뭐야?")을 추가했다.
슬롯 키는 food-nlu slot_definition 과 동일하게 맞췄다 (mall, product, category, purpose, recipient,
quantity, allergen, taste, diet_goal) + budget_min/budget_max/priority/occasion.
"""
from __future__ import annotations

import re

from shared.models import Intent
from shared.query_expansion import filter_expansion, log_unsupported

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
    # 정보·비교 질문에 붙는 말 — 검색어로 보내면 무관한 상품이 섞인다 (예: "감홍사과 처음 문경 거랑")
    "처음", "사보는데", "뭐가", "뭐야", "달라", "다른", "다르", "차이", "차이가", "차이점", "비교", "비교해줘",
    "어때", "어떻게", "궁금", "궁금해", "나아", "나은", "낫나", "어디", "산지", "지역", "품종", "종류",
    # 보관·손질 질문에 붙는 말 (예: "대봉감 홍시 만들려면 며칠 두고 어떻게 보관해?")
    "보관", "보관해", "보관법", "보관방법", "방법", "손질", "손질법", "며칠", "두고", "고르는", "고르는법", "요령",
    "특산물", "특산품", "명물", "농가맛집", "향토음식", "종가음식",
    # 먹는 법·곁들임 질문에 붙는 말 (예: "과메기 비린내 없이 먹는 법이랑 같이 살 거")
    "비린내", "없이", "같이", "먹는", "먹는법", "법이랑", "법", "곁들일", "곁들여", "사보는", "사봐",
}
# 지역 정보 질문 신호 (특산물·농가맛집·향토음식). '찹쌀떡 맛집'처럼 쇼핑몰 뜻의 '맛집'은 제외
LOCAL_CUES = re.compile(r"특산물|특산품|명물|농가\s*맛집|향토\s*음식|종가\s*음식|가면\s*뭐\s*(?:먹|사)")
# 구매와 함께 묻는 '먹는 법' / '같이 살 거(곁들임)' 신호 — 추천은 그대로 하고 정보 블록을 덧붙인다
EAT_CUES = re.compile(r"먹는\s*법|어떻게\s*먹|먹는\s*방법")
PAIR_CUES = re.compile(r"같이\s*(?:살|사|먹|곁들)|곁들|함께\s*(?:살|사|먹)")
# 보관·손질·고르는 법 질문 신호 (구매가 아닌 식재료 정보 질문)
STORAGE_CUES = re.compile(
    r"보관|손질|세척|씻는\s*법|씻어야|고르는\s*(?:법|방법|요령|지)|구입\s*요령|며칠\s*(?:두|가|보관)|얼려도|냉동해도"
)
# 정보·비교 질문 신호. "다른 사과 추천해줘"처럼 '다른' 단독은 비교가 아니므로 제외한다.
COMPARE_CUES = re.compile(
    r"(뭐가|무엇이|어디가|어떻게|어떤\s*게|어느\s*게)\s*(더\s*)?(달라|다른|다르|틀려|나아|낫|좋아)"
    r"|차이|다른\s*점|다른지|비교하면|\bvs\b|VS"
)
COMPARE_AXIS = {"origin": ["산지", "지역", "어디", "원산지"], "variety": ["품종", "종류"]}
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
        base = re.sub(r"(이랑|랑|에서|으로|에게|한테|을|를|은|는|용|께|에)$", "", tok)
        if len(base) >= 3:
            base = re.sub(r"로$", "", base)
        if len(base) < 2 or base in STOPWORDS or tok in STOPWORDS or base in all_kw:
            continue
        if base not in words:  # "청송 사과랑 문경 사과" → 사과 중복 제거
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
        # SAFE-QE: 규칙 NLU 는 상품 근거를 모르므로 확장어를 요구로 승격하지 않는다.
        # (evidence="" → 모든 확장어가 dropped, 원문 단어만 유지)
        exp = filter_expansion(text, terms.split(), "")
        slots["_expansion"] = exp
        log_unsupported(text, exp, source="rule_nlu")

    if re.search(r"처음\s*(?:사|먹|주문|구매)|입문|맛보기|조금만|소량|1인|혼자", text):
        slots["small_pack"] = True          # 처음 사거나 소량 → 대용량·묶음은 뒤로
    if re.search(r"대량|업소용|식당용|도매|대용량|단체|박스\s*단위|넉넉히", text):
        slots["bulk_ok"] = True             # 대량 구매 의도 → 묶음 상품도 그대로
    if EAT_CUES.search(text):
        slots["want_eat"] = True
    if PAIR_CUES.search(text):
        slots["want_pairing"] = True
    compare = bool(COMPARE_CUES.search(text))
    if compare:
        slots["question"] = "compare"
        axis = _first(COMPARE_AXIS, text)
        if axis:
            slots["compare_axis"] = axis

    # ACTION — 정보·비교 질문을 가장 먼저 본다 (구매 요청이 아니므로 예산을 묻지 않는다).
    # 그 다음은 food-nlu 시스템 프롬프트의 우선순위 그대로 (몰 → 알레르기 → 최저가 → 레시피 → 영양 → 선물 → 일반)
    if compare:
        action = "compare_info"
    elif STORAGE_CUES.search(text):
        action = "storage_info"
    elif LOCAL_CUES.search(text) and not any(w in text for w in ["레시피", "요리법", "만드는"]) and "선물" not in text:
        action = "local_info"
    elif mall:
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
