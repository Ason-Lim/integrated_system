"""오프라인 데모용 예시 카탈로그.

API 키 없이도 화면·대화 흐름을 확인하기 위한 가상 데이터다.
상품명·가격·리뷰 수는 실제 판매 정보가 아니며, 화면에 '예시 데이터' 표시가 붙는다.
SAMPLE_MARKET=0 이면 비활성화.
"""
from __future__ import annotations

from datetime import timedelta

from shared.markets.base import parse_units
from shared.models import Offer, now_utc

# (title, price, ship, orig, rating, reviews, keywords, spec, desc, hours_ago)
_CATALOG = [
    ("오늘제과 수제 두바이 쫀득쿠키 2개입", 9270, 0, 11900, 4.7, 885, "두바이 쫀득쿠키 두쫀쿠 디저트 쿠키 간식",
     None, "피스타치오·카다이프·마시멜로 사용 표기", 3),
    ("달빛베이크 두바이 쫀득 쿠키 1개", 7500, 3500, None, 4.5, 119, "두바이 쫀득쿠키 두쫀쿠 디저트 쿠키",
     None, "피스타치오·카다이프 들어간 수제 스타일", 30),
    ("두바이 쫀득쿠키 미니 20개입", 18900, 0, None, 3.9, 64, "두바이 쫀득쿠키 두쫀쿠 대용량 디저트 쿠키",
     None, "여러 개 나눠 먹기 좋은 구성", 6),
    ("구움과자 공방 두바이 쫀득쿠키 6개입 선물박스", 26800, 3000, 29800, 4.8, 342, "두바이 쫀득쿠키 두쫀쿠 선물 디저트",
     None, "개별 포장, 쇼핑백 동봉 표기", 2),
    ("산들농원 사과배 혼합 선물세트 5kg (사과6+배6)", 49900, 0, None, 4.6, 1210, "사과 배 과일 선물세트 명절 추석 설",
     None, "국내산, 개별 난좌 포장", 5),
    ("햇살과원 부사 사과 가정용 3kg", 21900, 0, None, 4.3, 2840, "사과 과일 가정용 부사",
     None, "흠과 포함 가능 표기", 4),
    ("고창들 참기름·들기름 선물세트 2병", 41900, 0, None, 4.8, 410, "참기름 들기름 기름 선물세트 명절",
     None, "저온압착 표기, 2종 선택", 8),
    ("견과공방 하루견과 선물세트 30봉", 28900, 0, 35000, 4.7, 5320, "견과류 견과 선물세트 하루견과 명절 건강",
     None, "아몬드·호두·캐슈넛 등 6종", 1),
    ("넛츠데이 프리미엄 견과 선물세트 3종", 45000, 0, None, 4.9, 870, "견과류 견과 선물세트 프리미엄 명절",
     None, "마카다미아·피칸 포함", 12),
    ("한우마을 1+등급 불고기·국거리 선물세트 1.2kg", 89000, 0, 99000, 4.7, 650, "한우 소고기 고기 선물세트 명절",
     None, "냉장, 아이스박스 포장", 7),
    ("캠핑그릴 돼지 목살 바베큐 1kg", 16900, 3000, None, 4.6, 2210, "돼지고기 목살 캠핑 바베큐 고기 숯불",
     None, "두께 2.5cm 캠핑용 컷", 3),
    ("캠핑그릴 양념 소갈비 1kg", 29900, 3000, None, 4.4, 980, "소갈비 갈비 캠핑 고기 숯불 양념",
     None, "양념 재움, 냉동", 3),
    ("제주햇귤 극조생 노지감귤 5kg", 18900, 0, None, 4.2, 1530, "감귤 귤 과일 제주",
     None, "로얄과, 산지 직송", 48),
    ("저당연구소 저당 그래놀라 500g", 12900, 0, None, 4.5, 760, "그래놀라 저당 다이어트 건강 시리얼",
     None, "당류 1회분 3g 표기", 10),
    ("한뿌리정 6년근 홍삼정 스틱 30포 선물세트", 45900, 0, 59000, 4.7, 2310, "홍삼 건강기능식품 선물세트 명절 건강",
     None, "건강기능식품 인증 표기, 쇼핑백 포함", 9),
    ("장건강연구 프로바이오틱스 3개월분 선물세트", 42000, 0, None, 4.6, 980, "유산균 프로바이오틱스 건강기능식품 선물세트",
     None, "건강기능식품 표기", 9),
    ("호텔린넨 40수 타월 선물세트 4매", 39800, 0, 45000, 4.8, 3120, "타월 수건 생활용품 선물세트 답례",
     None, "개별 상자 포장", 9),
    ("향기공방 핸드크림·바디워시 선물세트", 41500, 0, None, 4.5, 640, "핸드크림 바디 생활용품 선물세트",
     None, "쇼핑백 포함", 9),
    ("단백한끼 닭가슴살 스테이크 10팩", 19900, 0, 23000, 4.6, 12400, "닭가슴살 단백질 다이어트 닭",
     None, "1팩 100g", 2),
]


class SampleMarketAdapter:
    code = "sample"

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        now = now_utc()
        self._items: list[tuple[Offer, str]] = []
        for i, (t, p, ship, orig, rating, rv, kw, spec, desc, h) in enumerate(_CATALOG):
            unit, weight = parse_units(t)
            self._items.append((Offer(
                mall="sample", mall_label="예시몰", mall_product_id=f"S{i:03d}", title=t,
                price=p, shipping_fee=ship, original_price=orig, rating=rating, review_count=rv,
                url=None, image_url=None, unit_count=unit, weight_g=weight, spec=spec,
                description=desc, observed_at=now - timedelta(hours=h), is_sample=True), kw))

    def search(self, query: str, limit: int = 20) -> list[Offer]:
        if not self.enabled:
            return []
        q = [t for t in query.replace(",", " ").split() if t]
        scored = []
        for offer, kw in self._items:
            hay = offer.title + " " + kw
            hit = sum(1 for t in q if t in hay)
            if hit:
                scored.append((hit, offer))
        scored.sort(key=lambda x: -x[0])
        return [o.model_copy() for _, o in scored[:limit]]
