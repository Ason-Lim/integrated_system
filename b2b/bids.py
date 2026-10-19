"""입찰 공고 저장소 — B2B gift-monitor 의 공고 데이터가 여기로 통합된다.

출처별 신뢰 등급 (verification)
  verified           원천 확인: 나라장터 OpenAPI 응답, 또는 사람이 원문 URL·첨부를 대조하고 확인 처리한 공고
  document_provided  사용자가 제공한 원문 문서(제안요청서 등)에서 추출
  unverified         수동 입력·파일 업로드 등 원문 대조 전
  legacy_unverified  기존 smallbiz-monitor DB 에서 가져온 공고 — 코드에 하드코딩된 시드/시뮬레이션 데이터였음

트렌드 통계는 기본적으로 legacy_unverified 를 제외한다.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date

import requests
from pydantic import BaseModel, Field
from sqlalchemy import select

from b2b.evidence import _upsert, engine, t_bid
from b2b.gift_monitor import classify
from b2b.models import BidRequirement
from b2b.request_parser import parse

VERIFICATION_LABEL = {
    "verified": "원천 확인", "document_provided": "제공 문서", "unverified": "원문 대조 전",
    "legacy_unverified": "미검증 기존 데이터",
}
TRUSTED = {"verified", "document_provided"}

KEYMAP = {
    "bid_id": ["bid_id", "공고번호", "bid_no", "notice_no", "bidNtceNo"],
    "title": ["title", "공고명", "사업명", "name", "bidNtceNm"],
    "agency": ["agency", "institution", "발주기관", "수요기관", "기관명", "기관", "org", "organization", "ntceInsttNm"],
    "deadline": ["deadline", "마감일", "입찰 마감일", "마감", "close_date", "end_date", "bidClseDt"],
    "budget": ["budget", "예산", "예산규모", "사업예산", "총예산", "amount"],
    "url": ["url", "link", "원본 링크", "공고링크", "detail_url", "bidNtceDtlUrl"],
    "summary": ["summary", "hwpx_parsed_text", "요약", "내용", "description", "body", "text"],
    "posted": ["posted", "announcement_date", "공고일", "게시일", "등록일", "created_at", "bidNtceDt"],
    "department": ["department", "담당부서"],
    "manager": ["manager", "담당자", "ntceInsttOfclNm"],
    "contact": ["contact", "연락처", "ntceInsttOfclTelNo"],
    "institution_type": ["institution_type", "기관유형"],
}


class BidNotice(BaseModel):
    bid_id: str
    title: str = ""
    agency: str | None = None
    institution_type: str = "미분류"
    deadline: str | None = None
    budget: int | None = None               # 원 단위 (모르면 None)
    budget_text: str | None = None          # 원문 표기 ("총 1.5억원 내외")
    url: str | None = None
    summary: str = ""                       # 공고 본문/요약 텍스트
    posted: str | None = None
    department: str | None = None
    manager: str | None = None
    contact: str | None = None
    source: str = "manual"
    verification: str = "unverified"
    attachments: list[dict] = Field(default_factory=list)   # {name, chars, added}
    requirement: BidRequirement | None = None
    tags: list[str] = Field(default_factory=list)

    # ── 파생값 (저장하지 않고 매번 계산) ──
    def status(self, today: date | None = None) -> str:
        return classify.status(self.deadline, today)

    def derived(self, today: date | None = None) -> dict:
        text = self.summary or ""
        return {
            "status": self.status(today),
            "bid_type": classify.bid_type(self.title, text),
            "company_type": classify.company_type(self.title, text),
            "qualifications": classify.qualifications(self.title, text),
            "occasion": classify.occasion(self.title, text),
            "budget_band": classify.budget_band(self.budget),
            "verification_label": VERIFICATION_LABEL.get(self.verification, self.verification),
            "trusted": self.verification in TRUSTED,
        }

    def view(self, today: date | None = None) -> dict:
        d = self.model_dump(mode="json", exclude={"requirement"})
        d.update(self.derived(today))
        d["headcount"] = self.requirement.headcount if self.requirement else None
        return d


def _pick(row: dict, field: str):
    for k in KEYMAP[field]:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def make_id(*parts) -> str:
    return "bid-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def normalize(row: dict, source: str, verification: str = "unverified") -> BidNotice:
    title = str(_pick(row, "title") or "")
    agency = _pick(row, "agency")
    bid_id = str(_pick(row, "bid_id") or make_id(agency, title, _pick(row, "deadline")))[:80]
    budget_raw = _pick(row, "budget")
    n = BidNotice(
        bid_id=bid_id, title=title, agency=agency,
        institution_type=_pick(row, "institution_type") or classify.institution_type(agency),
        deadline=str(_pick(row, "deadline") or "") or None,
        budget=classify.parse_budget_won(budget_raw),
        budget_text=str(budget_raw) if budget_raw not in (None, "") else None,
        url=_pick(row, "url"), summary=str(_pick(row, "summary") or ""),
        posted=str(_pick(row, "posted") or "") or None,
        department=_pick(row, "department"), manager=_pick(row, "manager"), contact=_pick(row, "contact"),
        source=source, verification=verification)
    reparse(n)
    return n


def reparse(n: BidNotice) -> BidNotice:
    """공고 텍스트(본문+첨부)에서 입찰 조건을 다시 추출한다."""
    src = "bid_notice" if n.verification in TRUSTED else "unverified_notice"
    req = parse(f"{n.bid_id} {n.title}\n{n.summary}", source=src)
    req.bid_id = n.bid_id
    req.title = n.title or req.title
    req.agency = n.agency or req.agency
    if n.budget and not req.total_budget:
        req.total_budget = n.budget
    n.requirement = req
    return n


def save(n: BidNotice) -> None:
    with engine().begin() as c:
        _upsert(c, t_bid, "bid_id", dict(bid_id=n.bid_id, payload=n.model_dump(mode="json")))


def list_bids() -> list[BidNotice]:
    with engine().connect() as c:
        rows = c.execute(select(t_bid.c.payload)).scalars().all()
    bids = [BidNotice(**r) for r in rows]
    bids.sort(key=lambda b: (classify.parse_date(b.deadline) or date.min), reverse=True)
    return bids


def get(bid_id: str) -> BidNotice | None:
    with engine().connect() as c:
        r = c.execute(select(t_bid.c.payload).where(t_bid.c.bid_id == bid_id)).scalar()
    return BidNotice(**r) if r else None


def exists(bid_id: str) -> bool:
    return get(bid_id) is not None


def import_rows(rows: list[dict], source: str, verification: str = "unverified") -> int:
    n = 0
    for r in rows:
        try:
            save(normalize(r, source, verification))
            n += 1
        except Exception:
            continue
    return n


def _rows(data) -> list[dict]:
    return data if isinstance(data, list) else data.get("items") or data.get("data") or data.get("bids") or []


def import_file(name: str, content: bytes) -> int:
    text = content.decode("utf-8-sig")
    if name.lower().endswith(".csv"):
        return import_rows(list(csv.DictReader(io.StringIO(text))), f"file:{name}")
    return import_rows(_rows(json.loads(text)), f"file:{name}")


def fetch_remote(url: str) -> int:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return import_rows(_rows(r.json()), url)


def mark_verified(bid_id: str, note: str = "") -> BidNotice:
    """사람이 원문(URL·첨부)을 대조한 뒤 호출. 원문 URL 이나 첨부가 없으면 거부."""
    n = get(bid_id)
    if not n:
        raise KeyError(bid_id)
    if not (n.url and n.url.rstrip("/").count("/") > 2) and not n.attachments:
        raise ValueError("공고 상세 URL(홈페이지 첫 화면 제외) 또는 원문 첨부가 있어야 확인 처리할 수 있습니다.")
    n.verification = "verified"
    if note:
        n.tags = sorted(set(n.tags + [f"확인: {note}"]))
    reparse(n)
    save(n)
    return n


SEED = {
    "bid_id": "IBK서비스-2026008",
    "title": "IBK서비스 임직원 선물 공급 (사후 모의 검증용)",
    "agency": "IBK서비스",
    "deadline": "마감",
    "summary": ("예정 인원 2,090명, 1인당 44,000원(VAT 포함), 총예산 91,960,000원. "
                "식품 2종·건강기능식품 2종·생활용품 2종 구성, 온라인 기준 최저가 40,000원 이상. "
                "계약일로부터 5일 이내 폐쇄몰 구축·등재, 직원 선택일부터 5영업일 이내 국내 지정 주소 배송, "
                "반품 접수일부터 7영업일 이내 교환 배송. 실제 지급수량 정산."),
    "posted": "2026-10-12",
    "budget": "91,960,000원",
}


def ensure_seed() -> None:
    if not get(SEED["bid_id"]):
        n = normalize(SEED, "사용자 제공 제안요청서.hwp 요약 (2026-10-12 검토본)", "document_provided")
        n.tags = ["사후 모의 검증"]
        save(n)
