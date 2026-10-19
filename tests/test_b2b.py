from datetime import date

from fastapi.testclient import TestClient

from b2b import costing, evidence, proposal
from b2b.models import BidRequirement, Candidate, CategoryNeed
from b2b.request_parser import parse

TODAY = date(2026, 10, 16)
IBK = ("IBK서비스-2026008 예정 인원 2,090명, 1인당 44,000원(VAT 포함), 총예산 91,960,000원. "
       "식품 2종·건강기능식품 2종·생활용품 2종 구성, 온라인 기준 최저가 40,000원 이상. "
       "계약일로부터 5일 이내 폐쇄몰 구축·등재, 직원 선택일부터 5영업일 이내 국내 지정 주소 배송, "
       "반품 접수일부터 7영업일 이내 교환 배송.")


def test_parser_extracts_with_quotes():
    r = parse(IBK)
    assert (r.headcount, r.budget_per_person, r.min_online_price) == (2090, 44000, 40000)
    assert (r.delivery_business_days, r.exchange_business_days, r.setup_days) == (5, 7, 5)
    assert [c.name for c in r.categories] == ["식품", "건강기능식품", "생활용품"]
    assert all(p.quote for p in r.provenance)


def _full(**kw):
    base = dict(candidate_id="t", supplier="s", name="참기름 선물세트", option="300ml 2병", category="식품",
                online_min_price_verified=45000, observed_date=TODAY, unit_price_quote=36000,
                quote_valid_until=date(2026, 12, 31), packaging_cost=1000, shipping_cost=3000,
                delivery_days=3, exchange_days=5, stock_status="confirmed_available", quantity_available=5000)
    base.update(kw)
    return Candidate(**base)


def test_unknown_is_never_eligible():
    req = parse(IBK)
    assert evidence.evaluate(_full(), req, TODAY).decision == "ELIGIBLE"
    assert evidence.evaluate(_full(shipping_cost=None), req, TODAY).decision == "HOLD"
    assert evidence.evaluate(_full(delivery_days=9), req, TODAY).decision == "EXCLUDED"
    assert evidence.evaluate(_full(category="생활용품", name="x"), parse("식품 2종"), TODAY).decision == "EXCLUDED"


def test_real_bundle_items_all_hold_or_excluded():
    evs = evidence.evaluate_all(parse(IBK), evidence.bundle_to_candidates(
        __import__("json").loads((evidence.DATA / "evidence_bundle_v2.json").read_text())), TODAY)
    assert evs and all(e.decision != "ELIGIBLE" for e in evs)


def test_cost_unknown_is_not_zero():
    req = BidRequirement(budget_per_person=44000, headcount=2090)
    a = costing.analyze(req, {"supply": 36000})
    assert a.residual is None and len(a.unknown) == 5
    b = costing.analyze(req, dict(supply=36000, packaging=1500, shipping=3500, ops_cs=800, other=0), mall_build_total=3_000_000)
    assert b.residual == 44000 - 36000 - 1500 - 3500 - 800 - round(3_000_000 / 2090)


def test_external_proposal_has_no_internal_appendix():
    req = parse(IBK)
    evs = [evidence.evaluate(_full(), req, TODAY)]
    cost = costing.analyze(req, {"supply": 36000})
    ext = proposal.build(req, evs, profile={}, cost=cost, mode="external", today=TODAY)
    html = proposal.to_html(ext)
    assert not any(s.internal_only for s in ext.sections)
    assert "36,000" not in html            # 원가 비노출
    assert "[확인 필요: 제안사명]" in html  # 미확인은 지어내지 않음
    internal = proposal.build(req, evs, profile={}, cost=cost, mode="internal", today=TODAY)
    assert any(s.internal_only for s in internal.sections)


def test_docx_export(tmp_path):
    req = parse(IBK)
    p = proposal.build(req, [], profile={}, mode="external", today=TODAY)
    out = proposal.to_docx(p, tmp_path / "p.docx")
    assert out.stat().st_size > 5000


def test_console_requires_token_and_runs():
    from b2b.app import app
    c = TestClient(app)
    assert c.post("/api/run", json={"prompt": "공고 목록"}).status_code == 401
    h = {"X-Access-Token": "test-token"}
    r = c.post("/api/run", json={"prompt": "IBK서비스-2026008 분석해줘", "today": "2026-10-16"}, headers=h).json()
    assert r["action"] == "analyze" and any(b["type"] == "candidates" for b in r["blocks"])
    r2 = c.post("/api/run", json={"workspace_id": r["workspace_id"], "prompt": "제안서 작성해줘"}, headers=h).json()
    docs = next(b for b in r2["blocks"] if b["type"] == "docs")["items"]
    assert c.get(docs[0]["href"], headers=h).status_code == 200
    assert c.get("/files/..%2Fcore.sqlite3", headers=h).status_code == 404


def test_polish_rejects_new_numbers(monkeypatch):
    class Fake:
        enabled = True

        def chat_json(self, *a, **k):
            return {"lines": ["2,090명 대상, 업계 1위 10년 실적"]}
    monkeypatch.setattr(proposal, "LLMClient", lambda: Fake())
    assert proposal._polish(["2,090명 대상"]) == ["2,090명 대상"]


def test_category_need_model():
    assert CategoryNeed(name="식품", count=2).count == 2
