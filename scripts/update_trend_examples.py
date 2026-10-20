#!/usr/bin/env python3
"""홈 화면 '이렇게 물어보세요' 예시용 트렌드 키워드 JSON 생성 (표준 라이브러리만 사용).

입력: ~/food_recommend/daily_food_data/food_YYYY-MM-DD.csv (네이버 식품 키워드 일간 순위 500)
      ~/food-trend-automation/data/google_food_data/trends_v4_YYYY-MM-DD.csv (구글 트렌드, 보조 신호)
출력: ~/integrated_system/ui_ux/src/data/trend_examples_YYYY-MM-DD.json (실행일 기준)

카테고리별로 '최근 3일 순위 중앙값'이 '14일 전 무렵 3일 중앙값'보다 많이 오른 키워드를 고르고,
키워드에 맞는 사용자 질문 문장을 붙입니다.
실행: /usr/bin/python3 scripts/update_trend_examples.py [--dry-run]
"""
import csv, glob, json, os, re, statistics, sys, tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

HOME = Path.home()
def _base(name):  # Mac: ~/name, 원격 점검 환경: ~/mnt/name
    for p in (HOME / name, HOME / "mnt" / name):
        if p.exists():
            return p
    return HOME / name

NAVER_DIR = Path(os.environ.get("NAVER_DAILY_DIR", _base("food_recommend") / "daily_food_data"))
GOOGLE_DIR = Path(os.environ.get("GOOGLE_DATA_DIR", _base("food-trend-automation") / "data/google_food_data"))
OUT_DIR = Path(os.environ.get("TREND_EXAMPLES_DIR", _base("integrated_system") / "ui_ux/src/data"))

ICONS = {"선물용": "Gift", "간식/디저트": "Cookie", "제철요리": "Utensils", "제철과일": "Leaf"}

MAX_RANK = 200      # 현재 순위가 이보다 낮으면 후보 제외
LOOKBACK = 14       # 비교 기준: 약 2주 전

# 카테고리: (UI 태그, 키워드 → 질문 문장(없으면 템플릿), 정규식 보조 규칙, 기본 템플릿들)
CATEGORIES = [
    ("선물용", "선물", {
        "답례품": "돌잔치 하객 답례품으로 1만 원대에 받는 사람이 좋아할 만한 먹거리 추천해 줘",
        "결혼식답례품": "결혼식 답례품으로 100명분, 개당 1만 원 안쪽 먹거리 뭐가 좋을까?",
        "결혼답례품": "결혼 답례품으로 실용적인 먹거리 세트 1만 원대로 추천해 줘",
        "곶감": "어르신 선물용 곶감 세트, 5만 원 안쪽으로 포장 깔끔한 거 추천해 줘",
        "정관장": "부모님께 드릴 정관장 홍삼, 10만 원 안쪽에서 뭐가 좋을까?",
        "홍삼": "부모님 선물로 홍삼 제품 10만 원 안쪽에서 비교해 줘",
        "홍삼스틱100포": "홍삼스틱 100포 선물용으로 가성비 좋은 거 2~3개 비교해 줘",
        "산양삼": "어르신 생신 선물로 산양삼 사려는데 몇 뿌리, 얼마짜리가 적당해?",
        "공진단": "부모님 선물용 공진단, 가격대별로 어떤 차이가 있는지 알려줘",
        "경옥고": "부모님 건강 선물로 경옥고 10만 원 안쪽 추천해 줘",
        "침향환": "어르신 선물로 침향환 사려는데 가격대별로 비교해 줘",
        "한우선물세트": "거래처 선물로 한우 선물세트 15만 원 안쪽 추천해 줘",
        "과일선물세트": "집들이 선물로 과일 선물세트 5만 원 안쪽 추천해 줘",
        "빼빼로": "빼빼로데이에 회사 동료 20명한테 돌릴 과자 선물 추천해 줘",
    }, r"선물|답례", [
        "{kw} 선물하려는데 받는 분이 좋아할 만한 구성으로 5만 원 안쪽 추천해 줘",
        "부모님 선물로 {kw} 보내려는데 포장 깔끔한 거 2~3개 비교해 줘",
    ]),
    ("간식/디저트", "간식", {
        "고구마말랭이": "설탕 안 넣은 고구마말랭이 중에 쫀득하고 아이 간식으로 괜찮은 거 있을까?",
        "하루견과": "매일 먹을 하루견과, 30봉 기준으로 가성비 좋은 거 비교해 줘",
        "견과류": "다이어트 중에 먹을 무염 견과류 추천해 줘",
        "그릭요거트": "단백질 많은 그릭요거트 중에 꾸덕하고 덜 신 거 추천해 줘",
        "찹쌀떡": "택배로 받아도 굳지 않는 찹쌀떡 맛집 추천해 줘",
        "피자설기": "요즘 많이 찾는 피자설기, 어디 것이 맛있어?",
        "백년화편": "백년화편 선물용이랑 집에서 먹을 용으로 뭐가 달라?",
        "화과자": "차랑 같이 먹기 좋은 화과자 세트 추천해 줘",
        "약과": "너무 달지 않은 약과 중에 쫀득한 거 추천해 줘",
        "한과": "어르신 간식으로 부드러운 한과 추천해 줘",
        "촉촉한황치즈칩": "촉촉한황치즈칩 어디서 사는 게 제일 싸?",
        "찹쌀누룽지과자": "아이 간식으로 찹쌀누룽지과자 덜 짠 거 추천해 줘",
        "오란다": "수제 오란다 중에 딱딱하지 않은 거 추천해 줘",
        "다크초콜릿": "카카오 70% 이상 다크초콜릿 중에 쓴맛 덜한 거 추천해 줘",
        "도라지정과": "도라지정과 선물용으로 괜찮은 거 비교해 줘",
        "송편": "택배로 시켜 먹을 송편, 굳지 않게 오는 곳 추천해 줘",
        "모시송편": "영광 모시송편 냉동으로 사도 맛있는 곳 알려줘",
        "창억떡": "창억떡 중에 제일 인기 많은 메뉴가 뭐야?",
        "명가삼대떡집": "명가삼대떡집 떡 중에 아침 식사 대용으로 좋은 거 추천해 줘",
        "이대명과": "이대명과 과자 중에 선물용으로 좋은 구성 알려줘",
        "육포": "맥주 안주로 덜 짠 육포 추천해 줘",
        "약단밤": "까먹기 편한 약단밤 간식용으로 추천해 줘",
        "구운계란": "다이어트 간식으로 구운계란 30구 가성비 좋은 거 찾아줘",
        "땅콩버터": "무가당 땅콩버터 중에 꾸덕한 거 추천해 줘",
        "트러플하몽크래커": "트러플하몽크래커 어디서 사는 게 싸?",
    }, r"과자|쿠키|떡$|말랭이|초콜릿|견과|크래커|정과|설기|화편", [
        "{kw} 중에 너무 달지 않고 아이랑 같이 먹기 좋은 거 추천해 줘",
        "요즘 인기 있는 {kw}, 가성비 좋은 거 2~3개 비교해 줘",
    ]),
    ("제철요리", "제철요리", {
        "과메기": "과메기 처음 사보는데 비린내 없이 먹는 법이랑 같이 살 거 알려줘",
        "전어": "가을 제철 전어로 집에서 구이랑 회무침 맛있게 하는 법 알려줘",
        "꽃게": "제철 꽃게로 꽃게탕 4인분 끓이려면 몇 마리랑 재료 뭐 사야 해?",
        "활꽃게": "가을 활꽃게 쪄 먹으려면 손질이랑 찌는 시간 어떻게 해?",
        "톱밥꽃게": "톱밥꽃게 받으면 어떻게 손질해서 쪄 먹어?",
        "대하": "제철 대하 소금구이 하려는데 1kg이면 몇 명이 먹어?",
        "생새우": "가을 생새우로 새우장 담그려면 재료 뭐 사야 해?",
        "활새우": "활새우 소금구이 집에서 하는 법 알려줘",
        "간장게장": "제철 꽃게로 간장게장 직접 담그려면 간장 비율 어떻게 해?",
        "새우젓": "김장할 때 절임배추 20kg에 새우젓은 얼마나 넣어야 해?",
        "절임배추": "절임배추 20kg으로 김장하려면 양념 재료 뭐뭐 사야 해?",
        "절임배추20kg": "절임배추 20kg 김장 양념 비율이랑 필요한 재료 알려줘",
        "배추": "가을배추로 겉절이 만들려면 재료 뭐 사야 해?",
        "고춧가루": "김장용 햇고춧가루 몇 근 사야 하고 어떤 걸 골라야 해?",
        "총각김치": "총각무 제철인데 총각김치 담그려면 재료 뭐 사야 해?",
        "고들빼기": "고들빼기 김치 담그려면 재료 뭐 사야 해?",
        "굴": "제철 굴로 굴전이랑 굴국밥 하려면 몇 kg 사야 해?",
        "가리비": "제철 가리비 찜 하려면 1kg에 몇 명 먹고 뭐 같이 사야 해?",
        "홍게": "홍게 쪄 먹으려면 몇 분 찌고 어떻게 손질해?",
        "대게": "대게 집에서 찌는 법이랑 게딱지 볶음밥 하는 법 알려줘",
        "무늬오징어": "가을 무늬오징어 회로 먹으려면 손질 어떻게 해?",
        "갑오징어": "갑오징어 숙회 데치는 시간이랑 손질법 알려줘",
        "문어": "문어 숙회 삶는 시간이랑 손질법 알려줘",
        "전복": "전복 버터구이 하려면 손질부터 어떻게 해?",
        "고등어": "가을 고등어로 조림 비린내 안 나게 하는 법이랑 재료 알려줘",
        "갈치": "가을 제철 갈치로 조림 4인분 하려면 재료 뭐 사야 해?",
        "삼치": "제철 삼치구이 맛있게 굽는 법 알려줘",
        "방어": "방어 제철인데 대방어 회 몇 kg이면 4명이 먹어?",
        "꼬막": "꼬막 해감하고 꼬막무침 만드는 법 알려줘",
        "송이버섯": "송이버섯 향 살려서 먹는 법이랑 보관법 알려줘",
        "자연산송이버섯": "자연산 송이버섯으로 송이밥 짓는 법 알려줘",
        "능이버섯": "가을 능이버섯으로 백숙 하려면 재료 뭐 사야 해?",
        "참송이버섯": "참송이버섯 구워 먹는 법이랑 어울리는 재료 알려줘",
        "표고버섯": "가을 표고버섯으로 만들 수 있는 반찬 추천해 줘",
        "단호박": "제철 단호박으로 만들 수 있는 쉬운 요리 알려줘",
        "더덕": "더덕구이 양념이랑 손질법 알려줘",
        "도라지": "도라지 쓴맛 빼고 무침 만드는 법 알려줘",
        "연근": "제철 연근으로 연근조림 쫀득하게 만드는 법 알려줘",
        "우엉": "우엉조림 만들려면 손질부터 어떻게 해?",
        "햅쌀": "햅쌀로 밥 맛있게 지으려면 물 양을 어떻게 맞춰?",
        "햇밤": "햇밤으로 밤밥 지으려면 껍질 쉽게 까는 법도 알려줘",
        "밤": "가을 밤으로 밤조림이나 밤밥 만드는 법 알려줘",
    }, r"게$|새우|오징어|김장|절임|버섯|^굴|조개", [
        "가을 제철 {kw}로 집에서 만들기 좋은 요리랑 필요한 재료 알려줘",
        "제철 {kw}로 4인분 저녁 메뉴 만들려면 뭐 사야 해?",
    ]),
    ("제철과일", "제철과일", {
        "귤": "요즘 나오는 조생귤 중에 껍질 얇고 달콤한 건 어떻게 골라?",
        "귤10kg": "귤 10kg 박스로 사려는데 크기(로얄과/소과)별로 뭐가 맛있어?",
        "청귤": "청귤청 담그려면 청귤 몇 kg이랑 설탕 얼마나 필요해?",
        "단감": "아삭한 단감 고르는 법이랑 5kg에 몇 개 들어있는지 알려줘",
        "태추단감": "태추단감은 일반 단감이랑 뭐가 달라? 맛있는 거 추천해 줘",
        "대봉감": "대봉감 홍시 만들려면 며칠 두고 어떻게 보관해?",
        "청도반시": "청도반시 홍시로 먹으려면 언제 사야 해?",
        "감홍사과": "감홍사과 처음 사보는데 문경 거랑 다른 산지랑 뭐가 달라?",
        "문경감홍사과": "문경 감홍사과 5kg 선물용으로 괜찮은 곳 추천해 줘",
        "홍옥사과": "새콤한 홍옥사과 지금 사도 맛있어? 고르는 법 알려줘",
        "시나노골드사과": "시나노골드 사과 맛이 어떤지, 어디서 사면 좋은지 알려줘",
        "홍로사과": "홍로사과 지금 사도 맛있어? 보관법도 알려줘",
        "사과": "요즘 제철 사과 품종 중에 아삭하고 단 건 뭐야?",
        "배": "요즘 나오는 배 중에 당도 높은 품종 추천해 줘",
        "나주배": "나주배 7.5kg 선물용으로 크기 몇 과가 적당해?",
        "샤인머스켓": "샤인머스켓 당도 높은 거 고르는 법 알려줘",
        "무화과": "무화과 지금 끝물이야? 맛있는 거 고르는 법 알려줘",
        "청무화과": "청무화과는 일반 무화과랑 맛이 어떻게 달라?",
        "사과대추": "사과대추 생으로 먹기 좋은 거 고르는 법 알려줘",
        "유자": "유자청 담그려면 유자 몇 kg이랑 설탕 얼마나 필요해?",
        "포도": "요즘 맛있는 포도 품종 추천해 줘",
        "딸기": "딸기 언제부터 맛있어? 품종별 차이 알려줘",
    }, r"사과$|감$|귤|배$|포도|머스켓|무화과|대추$", [
        "요즘 제철 {kw} 맛있는 거 고르는 법이랑 산지 추천해 줘",
        "{kw} 5kg 사려는데 크기별로 뭐가 맛있어?",
    ]),
]

def load_naver():
    files = sorted(f for f in glob.glob(str(NAVER_DIR / "food_????-??-??.csv")))
    data = {}
    for f in files[-(LOOKBACK + 10):]:
        d = date.fromisoformat(Path(f).stem[5:])
        with open(f, encoding="utf-8-sig") as fh:
            data[d] = {r["keyword"].strip(): int(r["rank"]) for r in csv.DictReader(fh) if r.get("rank", "").isdigit()}
    return data

def load_google_terms(days=7):
    terms = set()
    for f in sorted(glob.glob(str(GOOGLE_DIR / "trends_v4_????-??-??.csv")))[-days:]:
        with open(f, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                terms.add(r.get("query", "").strip())
    return terms

def median_rank(data, dates, kw):
    return statistics.median(data[d].get(kw, 501) for d in dates)

def classify(kw):
    for i, (_, _, lex, pat, _) in enumerate(CATEGORIES):
        if kw in lex:
            return i
    for i, (_, _, _, pat, _) in enumerate(CATEGORIES):
        if re.search(pat, kw):
            return i
    return None

def main(dry=False):
    data = load_naver()
    if len(data) < 4:
        sys.exit(f"네이버 순위 파일이 부족합니다: {NAVER_DIR}")
    dates = sorted(data)
    latest = dates[-1]
    recent = dates[-3:]
    target = latest - timedelta(days=LOOKBACK)
    past_pool = sorted(dates, key=lambda d: abs((d - target).days))[:3]
    gterms = load_google_terms()

    picks = []
    for i, (cat, tag, lex, pat, templates) in enumerate(CATEGORIES):
        cands = []
        for kw in data[latest]:
            if classify(kw) != i:
                continue
            now = median_rank(data, recent, kw)
            if now > MAX_RANK:
                continue
            before = median_rank(data, past_pool, kw)
            rise = before - now
            score = rise / (now ** 0.5) + (3 if kw in gterms else 0) + (1 if kw in lex else 0)
            cands.append((score, kw, int(now), int(before), rise))
        if not cands:
            continue
        rising = [c for c in cands if c[4] > 0]
        score, kw, now, before, rise = max(rising or cands)
        text = lex.get(kw) or templates[latest.toordinal() % len(templates)].format(kw=kw)
        picks.append({
            "category": cat, "icon": ICONS[cat], "keyword": kw, "question": text,
        })
        print(f"  {cat}: {kw} (순위 {before if before <= 500 else '밖'} → {now}){' +구글' if kw in gterms else ''}", file=sys.stderr)

    out = picks
    txt = json.dumps(out, ensure_ascii=False, indent=2)
    if dry:
        print(txt); return
    OUT = OUT_DIR / f"trend_examples_{date.today().isoformat()}.json"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=OUT_DIR, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(txt + "\n")
    os.replace(tmp, OUT)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 저장: {OUT} (순위 데이터 {latest}, {len(picks)}개)")

if __name__ == "__main__":
    main(dry="--dry-run" in sys.argv)
