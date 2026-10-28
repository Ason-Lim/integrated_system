"""Foodpolis 순위 보강(참고 전용) — 제품명 매칭 판정."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("enrich", ROOT / "scripts" / "enrich_foodpolis.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def row(name, company, raw="정제수,설탕"):
    return {"PRDLST_NM": name, "BSSH_NM": company, "PRDLST_REPORT_NO": "1", "PRDLST_DCNM": "탄산음료", "RAWMTRL_NM": raw}


def test_exact_beats_partial():
    kind, picked = m.best("코카콜라제로", [row("코카-콜라 제로", "A"), row("코카콜라제로 슈거", "B")])
    assert kind == "exact" and picked[0]["BSSH_NM"] == "A"


def test_partial_and_none():
    assert m.best("상쾌환스틱", [row("상쾌환스틱ZERO", "C")])[0] == "partial"
    assert m.best("새로운제품", [row("다른것", "D")]) == ("none", [])


def test_summary_flags_allergens_from_raw():
    s = m.summarize(row("초코파이", "오리온", "밀가루,전란액,버터"))
    assert s["company"] == "오리온" and "밀(글루텐)" in s["allergens"] and "달걀(난류)" in s["allergens"]


def test_query_name_strips_brand_prefix_and_pack_count():
    assert m.query_name("오리온)단백질바미니") == ("단백질바미니", "오리온")
    assert m.query_name("뉴케어올프로틴(16입)") == ("뉴케어올프로틴", None)
    assert m.query_name("포스트*단백질바")[0] == "포스트 단백질바"


def test_service_errors_are_not_per_product():
    assert "INFO-110" in m.SERVICE_CODES and issubclass(m.ServiceError, RuntimeError)


def test_variants_never_shrink_the_name():
    """끝을 줄여 찾지 않는다 — '박카스에프'→'박카스에'→'박카스에이' 오연결 (2026-10-28)"""
    names = [v for v, _ in m.variants("박카스F")]
    assert names == ["박카스F", "박카스에프"]
    assert [v for v, _ in m.variants("테이크핏초코")] == ["테이크핏초코"]
    assert m.variants("코카콜라+스프라이트")[-1] == ("코카콜라", False)    # 묶음의 첫 제품은 '유사'만


# ── 로컬 DB로 실제 찾기 (C002·I0030과 같은 표 구조의 작은 DB) ─────────────────────────
import sqlite3  # noqa: E402

import pytest  # noqa: E402

SCHEMA = ("create table product (report_no text, kind text, company text, name text, name_norm text, "
          "item_type text, raw text, raw_functional text, primary key (kind, report_no))")


def _db(path, rows):
    con = sqlite3.connect(path)
    con.execute(SCHEMA)
    con.execute("create index ix_name_norm on product(name_norm)")
    for i, (name, company, item_type) in enumerate(rows):
        con.execute("insert into product values (?,?,?,?,?,?,?,?)",
                    (str(i), "c002", company, name, m.norm(name), item_type, "정제수", ""))
    con.commit()
    con.close()


@pytest.fixture
def local(tmp_path, monkeypatch):
    def make(general, health=()):
        _db(tmp_path / "c002.sqlite", general)
        _db(tmp_path / "i0030.sqlite", health)
        monkeypatch.setattr(m, "LOCAL_DB", tmp_path / "c002.sqlite")
        monkeypatch.setattr(m, "HEALTH_DB", tmp_path / "i0030.sqlite")
    return make


def test_bacchus_f_is_not_linked_to_bacchus_a(local):
    local([("박카스에이", "동아에코팩 주식회사", "혼합음료")])
    for prod in ("박카스F", "박카스F20입", "동아)박카스F"):
        assert m.lookup_local(prod)[0] == "none", prod


def test_short_prefix_is_not_partial(local):
    local([("몬스터킹", "(주)휴온스엔", "기타가공품")])
    assert m.lookup_local("몬스터355")[0] == "none"


def test_number_in_name_is_kept(local):
    local([("비타", "(주)네추럴웨이", "캔디류"), ("비타500", "광동제약주식회사", "혼합음료")])
    kind, picked, how = m.lookup_local("광동)비타500")
    assert kind == "exact" and picked[0]["PRDLST_NM"] == "비타500" and how == "with_number"


def test_brand_mismatch(local):
    local([("알사탕캔디", "다산식품", "캔디류"), ("단백질바 미니", "(주)삼아인터내셔날", "기타가공품")])
    assert m.lookup_local("해태)알사탕")[0] == "none"                 # 이름만 비슷 + 제조사 다름 → 버림
    assert m.lookup_local("오리온)단백질바미니")[0] == "uncertain"     # 이름 같음 + 제조사 다름 → 판단불가


def test_brand_glued_to_name_and_health_db(local):
    local([("홍삼원골드", "(주)한국인삼공사", "인삼.홍삼음료")], [("홍삼진본", "(주)한국인삼공사", "홍삼")])
    assert m.lookup_local("정관장홍삼원골드60포")[0] == "exact"
    kind, picked, how = m.lookup_local("정관장홍삼진본")
    assert kind == "exact" and picked[0]["SOURCE"] == "I0030 건강기능식품" and how == "brand_stripped"


def test_split_needs_both_parts(local):
    local([("테이크핏 맥스 초코맛", "(주)서울에프엔비", "혼합음료"), ("테이크핏 맥스 딸기맛", "(주)서울에프엔비", "혼합음료")])
    kind, picked, how = m.lookup_local("테이크핏초코")
    assert (kind, how) == ("partial", "split") and all("초코" in r["PRDLST_NM"] for r in picked)


def test_one_letter_prefix(local):
    local([("갈아만든 배", "오케이에프음료 주식회사", "과.채음료"), ("갈아만든배", "해태에이치티비주식회사", "과.채음료")])
    kind, picked, _ = m.lookup_local("해)갈아만든배")              # '해)' = 해태
    assert kind == "exact" and "해태" in picked[0]["BSSH_NM"]
    assert m.query_name("신)보해복분자")[1] == "신" and m.BRAND_ABBR.get("신") is None   # '신'은 신제품 표시


def test_category_conflict():
    jelly = {"item_type": "캔디류"}
    assert m.check_category("partial", [jelly], "주류") == ("none", [])            # new복분자 → 복분자제리
    assert m.check_category("exact", [jelly], "음료류")[0] == "uncertain"           # 비타병 → 캔디류
    assert m.check_category("partial", [{"item_type": "과실주"}], "주류")[0] == "partial"
