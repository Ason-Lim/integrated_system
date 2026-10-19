import io
import sqlite3
import zipfile
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from b2b import bids as store
from b2b.gift_monitor import checkpoints, classify, collectors, trends

H = {"X-Access-Token": "test-token"}


class FakeResp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeSession:
    """나라장터 응답 형식(response.body.items) 흉내 — 물품/용역 각각 호출됨."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if "Thng" in url and params["bidNtceNm"] == "선물세트":
            return FakeResp({"response": {"body": {"items": [{
                "bidNtceNo": "R26BK00000001", "bidNtceOrd": "000", "bidNtceNm": "2026년 설 명절 임직원 선물세트 구매",
                "ntceInsttNm": "한국테스트공사", "dminsttNm": "한국테스트공사", "bidNtceDt": "2026-10-10 10:00:00",
                "bidClseDt": "2026-10-30 18:00:00", "asignBdgtAmt": "95000000",
                "bidNtceDtlUrl": "https://www.g2b.go.kr/link/R26BK00000001", "ntceInsttOfclNm": "홍길동",
                "ntceInsttOfclTelNo": "02-000-0000"}]}}})
        return FakeResp({"response": {"body": {"items": []}}})


def test_classify_rules():
    assert classify.bid_type("추석 한우 선물세트") == "선물세트 (육류)"
    assert classify.bid_type("온누리상품권 구매") == "온누리상품권"
    assert classify.parse_budget_won("총 1억 2,000만원 내외") == 120_000_000
    assert classify.parse_budget_won("약 6,500세트 분량") is None
    assert classify.status("2026-10-17", date(2026, 10, 16)) == "마감임박"
    assert classify.status("2026-10-01", date(2026, 10, 16)) == "입찰마감"
    assert classify.status(None) == "마감일 미확인"
    assert classify.institution_type("KB국민은행") == "금융기관"
    assert classify.institution_type("서울교통공사") == "지자체 산하기관"


def test_g2b_collector_saves_only_real_response_items():
    s = FakeSession()
    res = collectors.G2BCollector("KEY", session=s).run(["선물세트", "기념품"], days=7, today=datetime(2026, 10, 16))
    assert res["found"] == 1 and res["new"] == 1
    assert "/ad/BidPublicInfoService/getBidPblancListInfoThngPPSSrch" in s.calls[0][0]
    assert s.calls[0][1]["inqryBgnDt"] == "202610090000"
    b = store.get("G2B-R26BK00000001-000")
    assert b.verification == "verified" and b.budget == 95_000_000 and b.agency == "한국테스트공사"
    # 같은 공고 재수집은 갱신
    again = collectors.G2BCollector("KEY", session=FakeSession()).run(["선물세트"], days=7, today=datetime(2026, 10, 16))
    assert again["new"] == 0 and again["updated"] == 1


def test_collector_without_key_reports_zero():
    res = collectors.G2BCollector(service_key="").run()
    assert res["new"] == 0 and "건너뜁니다" in res["log"][0]


def test_legacy_import_flagged_and_excluded_from_trends(tmp_path):
    db = tmp_path / "legacy.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE gift_bids (id INTEGER, institution TEXT, title TEXT, announcement_date TEXT, deadline TEXT,"
                " department TEXT, manager TEXT, contact TEXT, budget TEXT, link TEXT, hwpx_parsed_text TEXT, status TEXT, institution_type TEXT)")
    con.execute("CREATE TABLE programs (id INTEGER, title TEXT)")
    con.execute("INSERT INTO gift_bids VALUES (1,'가상기관','추석 온누리상품권 구매','2026-07-01','2026-07-20','총무','김가상','02-1','금 80,000,000원','https://www.g2b.go.kr','본문','입찰중','공공기관')")
    con.execute("INSERT INTO programs VALUES (1,'소상공인 지원사업')")
    con.commit()
    con.close()
    assert collectors.import_legacy_db(str(db)) == 1
    b = store.get("legacy-1")
    assert b.verification == "legacy_unverified" and "링크가 사이트 첫 화면" in b.tags
    with pytest.raises(ValueError):           # 홈페이지 링크만으로는 확인 처리 불가
        store.mark_verified("legacy-1")
    t = trends.analyze(include_legacy=False)
    assert t["excluded"]["legacy"] >= 1
    t2 = trends.analyze(include_legacy=True)
    assert t2["total"] > t["total"]


def test_manual_add_attach_hwpx_and_verify():
    n = collectors.add_manual("2026 설 명절 임직원 선물 공급", "테스트재단", "2026-12-20",
                              "https://example.org/notice/123", "")
    assert n.verification == "unverified"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Contents/section0.xml", "<hs:sec><hp:p><hp:t>예정 인원 500명, 1인당 50,000원(VAT 포함), 식품 2종</hp:t></hp:p></hs:sec>")
    after = collectors.attach(n.bid_id, "rfp.hwpx", buf.getvalue())
    assert after.requirement.headcount == 500 and after.requirement.budget_per_person == 50000
    assert store.mark_verified(n.bid_id).verification == "verified"


def test_evaluator_unanswered_not_zero():
    r = checkpoints.evaluate({"credit": "A 이상"})
    assert r["pct"] == 100 and "미응답" in r["grade"] and len(r["missing"]) == 7


def test_monitor_api_and_export():
    from b2b.app import app
    c = TestClient(app)
    assert c.get("/api/monitor/bids").status_code == 401
    d = c.get("/api/monitor/bids", headers=H).json()
    assert all(r["verification"] != "legacy_unverified" for r in d["rows"])
    d_all = c.get("/api/monitor/bids?scope=all", headers=H).json()
    assert len(d_all["rows"]) >= len(d["rows"])
    x = c.get("/api/monitor/export.xlsx", headers=H)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    t = c.get("/api/monitor/trends", headers=H).json()
    assert "bid_types" in t and t["report"]


def test_console_legacy_bid_warns_and_trends():
    from b2b.app import app
    c = TestClient(app)
    r = c.post("/api/run", json={"prompt": "legacy-1 분석해줘"}, headers=H).json()
    types = [b["type"] for b in r["blocks"]]
    assert "bid_card" in types and "checkpoints" in types
    assert any(b["type"] == "notice" and "시드" in b["md"] for b in r["blocks"])
    t = c.post("/api/run", json={"prompt": "입찰 트렌드 분석해줘"}, headers=H).json()
    assert t["action"] == "trends"
    col = c.post("/api/run", json={"prompt": "나라장터 공고 수집해줘"}, headers=H).json()
    assert col["action"] == "collect"
