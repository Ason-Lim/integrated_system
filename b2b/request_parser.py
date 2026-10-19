"""프롬프트·공고문 → BidRequirement.

규칙 추출이 기본이며 모든 값에 원문 발췌(provenance)를 남긴다.
LLM 이 켜져 있으면 규칙이 못 찾은 필드만 보충하고, 그 값은 source='llm' 으로 표시한다.
"""
from __future__ import annotations

import re
from datetime import date

from b2b.models import BidRequirement, CategoryNeed, Provenance
from shared.llm import LLMClient

CATS = ["건강기능식품", "생활용품", "가공식품", "농산물", "수산물", "축산물", "전자제품", "상품권", "주방용품", "식품"]
NUM = r"(\d[\d,]*(?:\.\d+)?)"


def _n(s: str) -> float:
    return float(s.replace(",", ""))


def _won(num: str, man: str | None) -> int:
    return int(round(_n(num) * (10000 if man else 1)))


def _quote(text: str, m: re.Match, pad: int = 12) -> str:
    a, b = max(0, m.start() - pad), min(len(text), m.end() + pad)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def parse(text: str, base: BidRequirement | None = None, source: str = "prompt") -> BidRequirement:
    req = base.model_copy(deep=True) if base else BidRequirement()
    prov: list[Provenance] = []

    def put(field: str, value, m: re.Match):
        setattr(req, field, value)
        prov.append(Provenance(field=field, value=value, quote=_quote(text, m), source=source))

    if m := re.search(r"([A-Za-z가-힣]+)-(\d{6,8})", text):
        put("bid_id", m.group(0), m)
        if not req.agency:
            req.agency = m.group(1)
    if m := re.search(r"(?:발주기관|수요기관|기관명)\s*[:：]?\s*([^\s,·]+)", text):
        put("agency", m.group(1), m)
    if m := re.search(r"(?:사업명|공고명)\s*[:：]?\s*([^\n]+?)(?:\s{2,}|\n|$|,)", text):
        put("title", m.group(1).strip(), m)
    if m := re.search(NUM + r"\s*명", text):
        put("headcount", int(_n(m.group(1))), m)
    if m := re.search(r"(?:1인당|인당)\s*" + NUM + r"\s*(만)?\s*원", text):
        put("budget_per_person", _won(m.group(1), m.group(2)), m)
    if m := re.search(r"(VAT|부가세|부가가치세)\s*(포함|별도)", text):
        put("vat_included", m.group(2) == "포함", m)
    if m := re.search(r"총\s*(?:사업)?예산\s*[:：]?\s*" + NUM + r"\s*(만)?\s*원", text):
        put("total_budget", _won(m.group(1), m.group(2)), m)

    cats = []
    for m in re.finditer("(" + "|".join(CATS) + r")\s*(\d+)\s*종", text):
        cats.append(CategoryNeed(name=m.group(1), count=int(m.group(2))))
        prov.append(Provenance(field="categories", value=f"{m.group(1)} {m.group(2)}종", quote=_quote(text, m), source=source))
    if cats:
        req.categories = cats

    if m := re.search(r"(?:온라인|최저가|시중가)[^\d\n]{0,14}" + NUM + r"\s*(만)?\s*원\s*이상", text):
        put("min_online_price", _won(m.group(1), m.group(2)), m)
    if m := (re.search(r"(?:폐쇄몰|쇼핑몰|구축)[^\d\n]{0,20}(\d+)\s*일\s*이내", text)
             or re.search(r"(\d+)\s*일\s*이내[^\n.]{0,12}(?:폐쇄몰|구축)", text)):
        put("setup_days", int(m.group(1)), m)
    dm = [m for m in re.finditer(r"(\d+)\s*영업일\s*(?:이내)?[^\n.,]{0,20}배송", text)
          if not re.search("교환|반품", m.group(0))]
    if dm:
        put("delivery_business_days", int(dm[0].group(1)), dm[0])
    if m := (re.search(r"(?:교환|반품)[^\d\n]{0,24}(\d+)\s*영업일", text)
             or re.search(r"(\d+)\s*영업일[^\n.]{0,10}교환", text)):
        put("exchange_business_days", int(m.group(1)), m)
    if m := re.search(r"(20\d\d)[-.년\s]+(\d{1,2})[-.월\s]+(\d{1,2})일?\s*(?:까지|마감)", text):
        put("deadline", date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m)
    if m := re.search(r"(실제\s*지급\s*수량[^\n.]{0,10}정산|실\s*지급[^\n.]{0,10}정산)", text):
        put("settlement", "실제 지급수량 기준 정산", m)

    req.provenance = [p for p in req.provenance if p.field not in {x.field for x in prov}] + prov
    return req


LLM_SYSTEM = """너는 기업 임직원 선물 입찰 공고에서 조건을 추출하는 도구다. JSON 하나만 출력한다.
키: headcount(int), budget_per_person(int,원), vat_included(bool), categories([{name,count}]),
min_online_price(int,원), setup_days(int), delivery_business_days(int), exchange_business_days(int).
원문에 없는 값은 null. 추측 금지."""


def parse_with_llm(text: str, base: BidRequirement | None = None) -> BidRequirement:
    req = parse(text, base)
    llm = LLMClient()
    if not llm.enabled or not req.missing():
        return req
    try:
        data = llm.chat_json(LLM_SYSTEM, text[:6000])
    except Exception:
        return req
    for k, v in data.items():
        if v in (None, [], "") or not hasattr(req, k) or getattr(req, k):
            continue
        try:
            if k == "categories":
                v = [CategoryNeed(**c) for c in v]
            setattr(req, k, v)
            req.provenance.append(Provenance(field=k, value=str(v), quote="(LLM 추출 — 원문 대조 필요)", source="llm"))
        except Exception:
            continue
    return req
