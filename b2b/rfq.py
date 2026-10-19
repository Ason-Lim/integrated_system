"""공급사별 견적 요청서(RFQ) 초안 — 발송하지 않는다 (내부 검토본)."""
from __future__ import annotations

from collections import defaultdict

from b2b.models import BidRequirement, Evaluation

COMMON = [
    "상품비·선물포장·개별배송·도서산간 추가비를 구분하고 포함 항목·VAT 기준을 명시해 주세요.",
    "주문 전달 후 {d}영업일 이내 국내 개별 주소 배송 완료 가능 여부와 제외 지역, 마감 시각, 배송 지연 처리 조건을 알려 주세요.",
    "하자 접수 후 {x}영업일 이내 교환 배송 완료와 반송·재배송 비용 부담 조건을 확인해 주세요.",
    "견적 적용 시작일·종료일, 가격 변경 조건, 재확인 필요 시점, 계절/품절 대체 상품 조건을 명시해 주세요.",
    "상품명·모델·구성·용량이 일치하는 온라인 판매 경로와 가격 확인 자료를 제공해 주세요. 온라인 최저가는 당사가 별도로 검증합니다.",
    "계약 전 샘플 검수와 상세정보 사용 허용 범위, 주문 자료 전달 방식과 송장 회신 방식을 알려 주세요.",
]


def drafts(req: BidRequirement, evals: list[Evaluation], include_excluded: bool = False) -> list[dict]:
    by_sup: dict[str, list[Evaluation]] = defaultdict(list)
    for e in evals:
        if e.decision == "EXCLUDED" and not include_excluded:
            continue
        by_sup[e.candidate.supplier].append(e)
    out = []
    scale = f"전체 예정 인원 {req.headcount:,}명은 과거 사업의 참고 규모이며 당사 확보 주문이 아닙니다. " if req.headcount else ""
    for sup, es in by_sup.items():
        items = [{"name": e.candidate.name, "option": e.candidate.option,
                  "questions": sorted({c.question for c in e.unknown if c.question})} for e in es]
        common = [q.format(d=req.delivery_business_days or "지정", x=req.exchange_business_days or "지정") for q in COMMON]
        body = (f"{sup} 담당자님께,\n\n"
                f"아래 후보 상품에 대해 조건별 공급 가능 여부와 견적을 확인하고자 합니다. "
                f"{scale}상품별 선택 수량은 미정이므로 최소주문량과 수량별 단가 구간, 예상 확보 가능 물량, "
                f"선택 비중 변동 시 대응 조건을 요청드립니다.\n")
        out.append({"supplier": sup, "items": items, "common": common, "body": body,
                    "status": "초안 — 발송 전 검토 필요 (자동 발송 없음)"})
    return out
