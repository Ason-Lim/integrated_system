"""근거 저장소 + 판정기.

- 저장: data/b2b_evidence/v2 의 bundle.json 을 그대로 적재 (원문 해시·출처 보존). 기존 업무 DB 는 건드리지 않음.
- 판정: v2 recommend_b2b.evaluate() 의 규칙을 '임직원 선물 입찰' 조건(카테고리·온라인가 하한·영업일 배송·교환)
        으로 일반화. 미확인은 충족으로 간주하지 않는다.
"""
from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from sqlalchemy import JSON, Column, MetaData, String, Table, Text, create_engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from b2b.models import BidRequirement, Candidate, Check, Evaluation
from shared.config import get_settings

DATA = Path(__file__).parent / "data"
meta = MetaData()
t_candidate = Table("b2b_candidate", meta, Column("candidate_id", String(80), primary_key=True),
                    Column("payload", JSON, nullable=False))
t_source = Table("b2b_source", meta, Column("source_id", String(80), primary_key=True),
                 Column("filename", Text), Column("payload", JSON, nullable=False))
t_bid = Table("b2b_bid", meta, Column("bid_id", String(80), primary_key=True), Column("payload", JSON, nullable=False))
t_doc = Table("b2b_document", meta, Column("doc_id", String(80), primary_key=True), Column("kind", String(32)),
              Column("bid_id", String(80)), Column("payload", JSON))

CATEGORY_RULES = [
    ("건강기능식품", ["홍삼", "비타민", "유산균", "프로바이오틱스", "오메가", "루테인", "콜라겐", "건강기능"]),
    ("생활용품", ["수건", "타월", "세제", "샴푸", "텀블러", "치약", "칫솔", "바디", "핸드크림", "주방"]),
    ("식품", ["기름", "참기름", "들기름", "사과", "배", "감귤", "황금향", "딸기", "한우", "우족", "전복", "황새치",
            "가다랑어", "견과", "유정란", "절임배추", "밀키트", "김", "멸치", "곶감", "꿀", "과일", "쿠키", "차"]),
]

# 첨부 HTML(2026-10-12 검토본)에 있던 제한사항·출처 URL — bundle 에 없는 정보만 보강
OVERRIDES = {
    "legacy-20261012-06": dict(url="https://soonsusan.com/", notes=["가격 적용 단위·옵션 금액 미확인", "품절/구매 버튼 동시 노출로 재고 확정 불가"]),
    "legacy-20261012-07": dict(url="https://soonsusan.com/", notes=["가정용 공개 판매가; 도매 견적 아님"]),
    "legacy-20261012-08": dict(url="https://k2b.kr/products/44", notes=["우족·잡뼈·스지 혼합 구성 — 부위 단가 비교 불가", "분산배송 비용 확인 필요"]),
    "legacy-20261012-09": dict(notes=["10/12 공지상 일시품절 — 추천 보류"], stock_status="sold_out_notice"),
    "legacy-20261012-10": dict(notes=["10/12 공지상 우천 출고 지연 2~3일"]),
    "legacy-20261012-11": dict(notes=["신규 오픈 공지 — 상품/옵션 매핑 미완료"]),
    "legacy-20261012-12": dict(url="https://www.noblegochang.com/product/detail.html?product_no=1584",
                               notes=["조합·용량별 실제 금액 미확인", "배송비 3,500원, 40,000원 이상 무료 안내"]),
    "legacy-20261012-13": dict(url="https://najumall.kr/product/detail.html?product_no=1624", origin="국내산",
                               manufacturer="(농)이룸팜스(주)",
                               notes=["쿠폰 기간 2026-08-24~09-23 종료 — 40,000원 할인가 사용 안 함", "일반 안내 3~7일 배송 — 5영업일 확약 불가"]),
}


def infer_category(name: str) -> str | None:
    for cat, words in CATEGORY_RULES:
        if any(w in name for w in words):
            return cat
    return None


@lru_cache
def engine(url: str | None = None):
    eng = create_engine(url or get_settings().b2b_db_url, future=True)
    meta.create_all(eng)
    return eng


def _upsert(conn, table, key: str, row: dict):
    if conn.dialect.name == "sqlite":
        stmt = sqlite_insert(table).values(**row)
        conn.execute(stmt.on_conflict_do_update(index_elements=[key], set_={k: v for k, v in row.items() if k != key}))
    else:  # postgres
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(table).values(**row)
        conn.execute(stmt.on_conflict_do_update(index_elements=[key], set_={k: v for k, v in row.items() if k != key}))


def bundle_to_candidates(bundle: dict) -> list[Candidate]:
    out = []
    for p in bundle.get("products", []):
        ov = OVERRIDES.get(p["product_id"], {})
        out.append(Candidate(
            candidate_id=p["product_id"], supplier=p.get("supplier_name") or "미상", name=p["name"],
            option=p.get("option_raw"), category=infer_category(p["name"]),
            observed_price=p.get("observed_price_krw"), price_kind=p.get("price_kind") or "unknown",
            observed_date=date.fromisoformat(p["observed_date"]) if p.get("observed_date") else None,
            expired_discount_price=p.get("expired_discount_krw"),
            unit_price_quote=p.get("unit_price_krw"),
            stock_status=ov.get("stock_status", p.get("stock_status") or "unknown"),
            quantity_available=p.get("quantity_available"), delivery_days=p.get("delivery_days"),
            quote_valid_until=date.fromisoformat(p["quote_valid_until"]) if p.get("quote_valid_until") else None,
            url=ov.get("url"), origin=ov.get("origin") or p.get("origin"), manufacturer=ov.get("manufacturer"),
            notes=ov.get("notes", []), source="evidence_bundle"))
    return out


def ingest_bundle(path: Path | None = None) -> dict:
    path = path or DATA / "evidence_bundle_v2.json"
    b = json.loads(path.read_text(encoding="utf-8"))
    cands = bundle_to_candidates(b)
    with engine().begin() as c:
        for s in b.get("sources", []):
            _upsert(c, t_source, "source_id", dict(source_id=s["source_id"], filename=s.get("filename"),
                                                  payload={k: s[k] for k in s if k not in ("text", "table_rows", "images", "links")}))
        for cand in cands:
            _upsert(c, t_candidate, "candidate_id", dict(candidate_id=cand.candidate_id, payload=cand.model_dump(mode="json")))
    return {"sources": len(b.get("sources", [])), "candidates": len(cands), "bundle_date": b.get("bundle_date")}


def upsert_candidate(cand: Candidate) -> None:
    with engine().begin() as c:
        _upsert(c, t_candidate, "candidate_id", dict(candidate_id=cand.candidate_id, payload=cand.model_dump(mode="json")))


def all_candidates() -> list[Candidate]:
    with engine().connect() as c:
        rows = c.execute(select(t_candidate.c.payload)).scalars().all()
    if not rows:
        ingest_bundle()
        return all_candidates()
    return [Candidate(**r) for r in rows]


# ── 판정 ─────────────────────────────────────────────────────────
def evaluate(c: Candidate, req: BidRequirement, today: date | None = None, max_age_days: int = 14) -> Evaluation:
    today = today or date.today()
    checks: list[Check] = []

    def add(key, label, status, expected=None, actual=None, note="", question=None):
        checks.append(Check(key=key, label=label, status=status, expected=expected, actual=actual, note=note, question=question))

    # 1 품목 카테고리
    wanted = [x.name for x in req.categories]
    if wanted:
        if c.category is None:
            add("category", "품목 구분", "UNKNOWN", "/".join(wanted), None, "상품 분류 미확인", "상품 분류(식품/건강기능식품/생활용품)를 확인해 주세요.")
        else:
            add("category", "품목 구분", "PASS" if c.category in wanted else "FAIL", "/".join(wanted), c.category)

    # 2 상품 가치 하한 (온라인 기준가)
    if req.min_online_price:
        floor = req.min_online_price
        if c.online_min_price_verified is not None:
            add("online_value", "온라인가 하한", "PASS" if c.online_min_price_verified >= floor else "FAIL",
                f"{floor:,}원 이상", f"{c.online_min_price_verified:,}원 (검증)")
        elif c.observed_price is not None and c.observed_price < floor * 0.8:
            add("online_value", "온라인가 하한", "FAIL", f"{floor:,}원 이상", f"{c.observed_price:,}원 (관측)",
                "관측가가 하한에 크게 못 미침 — 상위 옵션이 있으면 별도 후보로 등록")
        else:
            actual = f"{c.observed_price:,}원 (관측, {c.price_kind})" if c.observed_price else None
            note = "관측가는 하한 이상이나 동일 옵션 시장 최저가는 미검증" if c.observed_price and c.observed_price >= floor \
                else "관측가가 하한 근처/미확인 — 동일 옵션 복수 판매경로 가격 대조 필요"
            if c.expired_discount_price:
                note += f" · 종료된 할인가 {c.expired_discount_price:,}원은 사용하지 않음"
            add("online_value", "온라인가 하한", "UNKNOWN", f"{floor:,}원 이상", actual, note,
                "상품명·모델·구성·용량이 일치하는 온라인 판매 경로와 가격 확인 자료를 제공해 주세요.")

    # 3 옵션·구성 확정
    opt = c.option or ""
    if not opt or any(w in opt for w in ("미확인", "선택", "/")):
        add("spec", "정확한 옵션·구성", "UNKNOWN", "단일 옵션 확정", opt or None, "옵션·용량·구성 확정 필요",
            "정확한 모델/옵션/구성/원산지/제조사/유효 소비기한과 제품 명세를 제공해 주세요.")
    else:
        add("spec", "정확한 옵션·구성", "PASS", "단일 옵션 확정", opt)

    # 4 근거 최신성
    if c.observed_date is None:
        add("freshness", "근거 최신성", "UNKNOWN", f"{max_age_days}일 이내", None, "관측일 없음")
    else:
        age = (today - c.observed_date).days
        add("freshness", "근거 최신성", "PASS" if 0 <= age <= max_age_days else "UNKNOWN",
            f"{max_age_days}일 이내", f"{c.observed_date} ({age}일 전)", "" if age <= max_age_days else "재관측 필요")

    # 5 공급 견적
    if c.unit_price_quote is not None and (c.quote_valid_until is None or c.quote_valid_until >= today):
        add("quote", "공급사 견적", "PASS", "유효 견적", f"{c.unit_price_quote:,}원")
    else:
        add("quote", "공급사 견적", "UNKNOWN", "유효 견적", "공개가만 있음" if c.observed_price else None,
            "공개 판매가는 견적이 아님",
            "상품비·선물포장·개별배송·도서산간 추가비를 구분하고 포함 항목·VAT 기준과 견적 유효기간을 명시해 주세요.")

    # 6 1인 예산 적합
    if req.budget_per_person:
        parts = [c.unit_price_quote, c.packaging_cost, c.shipping_cost]
        if all(v is not None for v in parts):
            total = sum(parts)
            add("budget", "1인 예산 내 공급", "PASS" if total <= req.budget_per_person else "FAIL",
                f"{req.budget_per_person:,}원 이하", f"{total:,}원")
        else:
            add("budget", "1인 예산 내 공급", "UNKNOWN", f"{req.budget_per_person:,}원 이하", None,
                "상품비·포장·배송 중 미확인 항목 있음 (미확인 ≠ 0원)")

    # 7 배송 기한
    if req.delivery_business_days:
        if c.delivery_days is None:
            add("delivery", "배송 기한", "UNKNOWN", f"{req.delivery_business_days}영업일 이내", None,
                "", "주문 전달 후 지정 영업일 이내 국내 개별 주소 배송 완료 가능 여부와 제외 지역·마감 시각을 알려 주세요.")
        else:
            add("delivery", "배송 기한", "PASS" if c.delivery_days <= req.delivery_business_days else "FAIL",
                f"{req.delivery_business_days}영업일 이내", f"{c.delivery_days}영업일")

    # 8 교환 기한
    if req.exchange_business_days:
        if c.exchange_days is None:
            add("exchange", "교환 기한", "UNKNOWN", f"{req.exchange_business_days}영업일 이내", None, "",
                "하자 접수 후 지정 영업일 이내 교환 배송 완료와 반송·재배송 비용 부담 조건을 확인해 주세요.")
        else:
            add("exchange", "교환 기한", "PASS" if c.exchange_days <= req.exchange_business_days else "FAIL",
                f"{req.exchange_business_days}영업일 이내", f"{c.exchange_days}영업일")

    # 9 재고·물량
    if c.stock_status == "sold_out_notice":
        add("stock", "재고·물량", "UNKNOWN", "확보 가능", "품절 공지", "품절 공지 — 재입고 전 추천 보류",
            "재입고 예정일과 확보 가능 물량을 알려 주세요.")
    elif c.stock_status == "confirmed_available" and c.quantity_available is not None:
        need = req.headcount or 1
        add("stock", "재고·물량", "PASS" if c.quantity_available >= need else "FAIL", f"최대 {need:,}건", f"{c.quantity_available:,}건")
    else:
        add("stock", "재고·물량", "UNKNOWN", "확보 가능", None, "상품별 선택 수량 미정 — 균등 배분 가정 안 함",
            "최소주문량, 수량별 단가 구간, 확보 가능 물량, 선택 비중 변동 시 대응 조건을 알려 주세요.")

    decision = "EXCLUDED" if any(x.status == "FAIL" for x in checks) else \
        "HOLD" if any(x.status == "UNKNOWN" for x in checks) else "ELIGIBLE"
    # Merchant Decision Sufficiency: 필수조건 근거 coverage 를 후보에 기록 (shadow)
    required = ("category", "online_value", "spec", "quote", "delivery", "exchange", "stock")
    determinate = [x for x in checks if x.key in required and x.status == "PASS"]
    missing = [x.key for x in checks if x.key in required and x.status != "PASS"]
    c.evidence_coverage = round(len(determinate) / len(required), 3)
    c.missing_terms = missing
    c.rankability = "DETERMINATE" if not missing else \
        "INDETERMINATE" if any(x.status == "FAIL" for x in checks if x.key in required) else "UNKNOWN"
    return Evaluation(candidate=c, decision=decision, checks=checks)


def evaluate_all(req: BidRequirement, cands: list[Candidate] | None = None, today: date | None = None) -> list[Evaluation]:
    cands = cands if cands is not None else all_candidates()
    evs = [evaluate(c, req, today) for c in cands]
    order = {"ELIGIBLE": 0, "HOLD": 1, "EXCLUDED": 2}
    evs.sort(key=lambda e: (order[e.decision], len(e.unknown), -(e.candidate.observed_price or 0)))
    return evs
