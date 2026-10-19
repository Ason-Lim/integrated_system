"""공고 분류 규칙 — gift_trend_analyzer/app.py 의 infer_bid_type · analyze_company_type ·
analyze_qualifications 를 이식하고, 예산 문자열을 원 단위 정수로 바꾸는 파서·시기 분류를 추가했다.

모두 키워드 규칙이다 (AI 판단이 아님). 화면에는 '규칙 분류'로 표시한다.
"""
from __future__ import annotations

import re
from datetime import date

BID_TYPES = ["온누리상품권", "모바일상품권", "선물세트 (육류)", "선물세트 (과일/농산물)", "선물세트 (생선/수산물)",
             "선물세트 (가전제품)", "선물세트 (주방기구/생활용품)", "선물세트 (건강식품/기타)"]
COMPANY_TYPES = ["쿠폰/대행사업자", "온라인쇼핑몰", "직접 생산자", "유통사업자"]
QUALIFICATIONS = ["HACCP/위생인증", "전국 개별 배송망", "CS 전담 고객센터", "공식 수탁/가맹 자격", "신용평가등급 보증"]
INSTITUTION_TYPES = ["공공기관", "지자체 산하기관", "금융기관", "민간기업", "미분류"]
OCCASIONS = ["설", "추석", "창립기념일", "생일·기념일", "연말·동계", "가정의달", "기타"]
BUDGET_BANDS = ["5천만원 미만", "5천만~1억원", "1억~3억원", "3억원 초과", "금액 미기재"]


def bid_type(title: str, text: str = "") -> str:
    c = f"{title} {text}".lower()
    if "온누리" in c:
        return "온누리상품권"
    if any(k in c for k in ("기프티콘", "쿠폰", "모바일 상품권", "모바일형", "기프트카드")):
        return "모바일상품권"
    if any(k in c for k in ("한우", "육류", "갈비", "고기", "돈육")):
        return "선물세트 (육류)"
    if any(k in c for k in ("사과", "농산물", "과일", "곶감", "쌀", "버섯")) or re.search(r"(?<![가-힣])배(?![가-힣]*송)", c):
        return "선물세트 (과일/농산물)"
    if any(k in c for k in ("굴비", "조기", "생선", "수산물", "멸치", "해산물", "전복")) or re.search(r"(?<![가-힣])김(?![가-힣])", c):
        return "선물세트 (생선/수산물)"
    if any(k in c for k in ("청소기", "공기청정기", "가전", "마사지기", "인덕션")):
        return "선물세트 (가전제품)"
    if any(k in c for k in ("냄비", "그릇", "식기", "주방", "생활용품", "침구", "의류", "잡화", "타월")):
        return "선물세트 (주방기구/생활용품)"
    return "선물세트 (건강식품/기타)"


def company_type(title: str, text: str = "") -> str:
    c = f"{title} {text}".lower()
    if any(k in c for k in ("기프티콘", "쿠폰", "모바일 상품권", "상품권 발송", "대행 발송")):
        return "쿠폰/대행사업자"
    if any(k in c for k in ("선택형 복지몰", "복지몰", "쇼핑몰", "폐쇄몰", "모바일몰", "시스템 연동")):
        return "온라인쇼핑몰"
    if any(k in c for k in ("생산 전문", "직접 생산", "제조사", "자체 가공", "농가 협력", "haccp", "해썹")):
        return "직접 생산자"
    return "유통사업자"


def qualifications(title: str, text: str = "") -> list[str]:
    c = f"{title} {text}".lower()
    rules = [
        ("HACCP/위생인증", ("haccp", "해썹", "위생인증", "품질인증", "식품 안전")),
        ("전국 개별 배송망", ("개별 가호", "자택 배송", "개별 배송", "전국 배송망", "택배 배송", "지정 주소 배송")),
        ("CS 전담 고객센터", ("cs", "콜센터", "고객센터", "전담 상담", "민원")),
        ("공식 수탁/가맹 자격", ("공식 지정", "공식 가맹", "수탁 금융", "공식 판매", "조달 자격")),
        ("신용평가등급 보증", ("신용평가", "신용등급", "경영상태", "보증보험")),
    ]
    return [name for name, kws in rules if any(k in c for k in kws)]


def institution_type(name: str | None) -> str:
    n = (name or "").strip()
    if not n:
        return "미분류"
    if any(k in n for k in ("은행", "카드", "보험", "화재", "해상", "증권", "저축", "캐피탈", "금융")):
        return "금융기관"
    regions = ("서울", "부산", "경기", "인천", "대구", "광주", "대전", "울산", "세종", "강원", "충북", "충남",
               "전북", "전남", "경북", "경남", "제주")
    if n.startswith(regions) and any(k in n for k in ("진흥원", "재단", "공사", "공단", "센터", "청")):
        return "지자체 산하기관"
    if n.startswith(("한국", "국민", "국립", "중소벤처", "근로복지", "IBK서비스")) or \
            any(k in n for k in ("공사", "공단", "진흥원", "위원회", "(LH)", "마사회", "조폐")):
        return "공공기관"
    return "민간기업"


def occasion(title: str, text: str = "") -> str:
    c = f"{title} {text}"
    if re.search(r"(?<![가-힣])설(?:날| 명절| 선물|맞이)?(?![가-힣])|설날", c):
        return "설"
    if "추석" in c or "한가위" in c:
        return "추석"
    if "창립" in c:
        return "창립기념일"
    if any(k in c for k in ("생일", "결혼기념", "출산", "기념일")):
        return "생일·기념일"
    if any(k in c for k in ("연말", "동계", "겨울", "송년")):
        return "연말·동계"
    if any(k in c for k in ("가정의달", "가정의 달", "어버이", "어린이날")):
        return "가정의달"
    return "기타"


def parse_budget_won(s: str | int | None) -> int | None:
    """'금 145,000,000원' · '총 1.5억원 내외' · '총 1억 2,000만원' · '7,500만원' → 원. 금액이 없으면 None."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s) or None
    t = str(s).replace(",", "").replace(" ", "")
    if m := re.search(r"(\d+(?:\.\d+)?)억(?:(\d+)만)?", t):
        return int(round(float(m.group(1)) * 100_000_000 + (int(m.group(2)) * 10_000 if m.group(2) else 0)))
    if m := re.search(r"(\d+(?:\.\d+)?)만원", t):
        return int(round(float(m.group(1)) * 10_000))
    if m := re.search(r"(\d{5,})원?", t):
        return int(m.group(1))
    return None


def budget_band(won: int | None) -> str:
    if won is None:
        return BUDGET_BANDS[4]
    if won < 50_000_000:
        return BUDGET_BANDS[0]
    if won <= 100_000_000:
        return BUDGET_BANDS[1]
    if won <= 300_000_000:
        return BUDGET_BANDS[2]
    return BUDGET_BANDS[3]


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    m = re.search(r"(20\d\d)[-./년\s]*(\d{1,2})[-./월\s]*(\d{1,2})", str(s))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def status(deadline: str | None, today: date | None = None, closing_days: int = 3) -> str:
    """마감일 기준 상태 (기존 calculate_bid_status 와 같은 이름: 입찰중 / 마감임박 / 입찰마감)."""
    today = today or date.today()
    if deadline and "마감" in str(deadline) and not parse_date(deadline):
        return "입찰마감"
    d = parse_date(deadline)
    if d is None:
        return "마감일 미확인"
    if d < today:
        return "입찰마감"
    if (d - today).days <= closing_days:
        return "마감임박"
    return "입찰중"
