"""I0030 전체 파일 가져오기 — 샘플 응답과 같은 열 이름의 작은 CSV로 확인."""
import csv
import gzip
import importlib.util
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("i0030", ROOT / "scripts" / "import_i0030.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

COLS = ["PRDLST_REPORT_NO", "LCNS_NO", "BSSH_NM", "PRDLST_NM", "PRDLST_CDNM", "RAWMTRL_NM", "INDIV_RAWMTRL_NM",
        "ETC_RAWMTRL_NM", "CAP_RAWMTRL_NM", "PRIMARY_FNCLTY", "NTK_MTHD", "IFTKN_ATNT_MATR_CN", "POG_DAYCNT",
        "CSTDY_MTHD", "PRMS_DT", "LAST_UPDT_DTM", "PRDT_SHAP_CD_NM"]


def test_import_builds_db(tmp_path, monkeypatch):
    src = tmp_path / "I0030_csv.gz"
    with gzip.open(src, "wt", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerow({"PRDLST_REPORT_NO": "201100200015", "BSSH_NM": "주식회사 성윤", "PRDLST_NM": "6년근 고려홍삼정 PREMIUM",
                    "PRDLST_CDNM": "홍삼", "RAWMTRL_NM": "홍삼제품", "INDIV_RAWMTRL_NM": "홍삼추출 농축액",
                    "PRIMARY_FNCLTY": "면역력 증진", "POG_DAYCNT": "제조일로부터 24개월", "CSTDY_MTHD": "서늘한 곳"})
        w.writerow({"PRDLST_REPORT_NO": "", "PRDLST_NM": "번호없음"})
    out = tmp_path / "o.sqlite"
    monkeypatch.setattr(sys, "argv", ["x", "--src", str(src), "--out", str(out)])
    monkeypatch.setattr(m.tempfile, "gettempdir", lambda: str(tmp_path))
    assert m.main() == 0
    con = sqlite3.connect(out)
    r = con.execute("select name, company, item_type, raw_functional, expiry, primary_function, storage from product").fetchall()
    assert r == [("6년근 고려홍삼정 PREMIUM", "주식회사 성윤", "홍삼", "홍삼추출 농축액", "제조일로부터 24개월", "면역력 증진", "서늘한 곳")]
    assert dict(con.execute("select k, v from meta").fetchall())["skipped"] == "1"


def test_wrong_header_is_reported(tmp_path, monkeypatch):
    src = tmp_path / "x.csv"
    src.write_text("A,B\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["x", "--src", str(src), "--out", str(tmp_path / "o.sqlite")])
    monkeypatch.setattr(m.tempfile, "gettempdir", lambda: str(tmp_path))
    assert m.main() == 3
