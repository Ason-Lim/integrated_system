"""식품정보24 수집기 보완 (2026-10-28 검토 반영) — 가짜 응답으로 확인, 실제 API 호출 없음."""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("u24", ROOT / "scripts" / "update_food24_products.py")
u = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u)
KEY = "abcd1234-0000-0000-0000-secretkey000"


class Resp:
    def __init__(self, status, data):
        self.status_code, self._d = status, data

    def json(self):
        return self._d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def rec(no, name="제품"):
    return {"prdlstReportNo": no, "prdlstNm": name, "bsshNm": "회사", "lcnsNo": "1"}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(u.time, "sleep", lambda *_: None)


def test_5xx_is_retried(monkeypatch):
    seq = [Resp(500, {}), Resp(503, {}), Resp(200, {"resultCode": "00", "recordset": [rec("1")], "totalCount": 1})]
    monkeypatch.setattr(u.requests, "get", lambda *a, **k: seq.pop(0))
    assert u.fetch("getFfBaseRaw", KEY, 1, 10)["totalCount"] == 1


def test_error_shows_server_message_but_never_key(monkeypatch):
    body = {"resultCode": "10", "resultMsg": "INVALID_REQUEST_PARAMETER_ERROR",
            "resultDc": f"한페이지 최대결과수는 10 입니다. key={KEY}"}
    monkeypatch.setattr(u.requests, "get", lambda *a, **k: Resp(200, body))
    with pytest.raises(RuntimeError) as e:
        u.fetch("getGfBaseRaw", KEY, 1, 100)
    msg = str(e.value)
    assert "최대결과수는 10" in msg and KEY not in msg and "<KEY>" in msg


def test_rows_without_report_no_are_skipped_and_logged(tmp_path, monkeypatch):
    con = sqlite3.connect(tmp_path / "d.sqlite")
    con.executescript(u.SCHEMA)
    page = {"resultCode": "00", "totalCount": 3, "recordset": [rec("1"), {"prdlstNm": "번호없음"}, rec("3")]}
    monkeypatch.setattr(u.requests, "get", lambda *a, **k: Resp(200, page))
    u.collect(con, KEY, "ff", 10, True, None)
    assert con.execute("select count(*) from product").fetchone()[0] == 2
    assert con.execute("select name, reason from skipped").fetchall() == [("번호없음", "품목보고번호 없음")]
    assert con.execute("select page from progress where kind='ff'").fetchone()[0] == 0   # 끝까지 받음


def test_same_report_no_in_two_kinds_kept_separately(tmp_path):
    con = sqlite3.connect(tmp_path / "d.sqlite")
    con.executescript(u.SCHEMA)
    con.execute("insert into product values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", u.row_of("gf", rec("9", "A")))
    con.execute("insert or replace into product values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", u.row_of("ff", rec("9", "B")))
    assert con.execute("select count(*) from product").fetchone()[0] == 2


def test_default_target_is_health_food_only():
    assert u.DEFAULT_KINDS == ["ff"]
