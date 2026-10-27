"""식품정보24 품목제조보고(원재료) 매칭·알레르기 판정."""
import importlib.util
import sqlite3
from pathlib import Path

import pytest

from shared import food24_catalog as f24
from shared.engines.recommender import Recommender
from shared.markets.registry import MarketRegistry
from shared.models import Intent, Offer

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("upd", ROOT / "scripts" / "update_food24_products.py")
upd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(upd)


def _rec(no, kind, company, name, raw, expiry="제조일로부터 12개월"):
    return upd.row_of(kind, {"prdlstReportNo": no, "lcnsNo": "1", "bsshNm": company, "prdlstNm": name,
                             "totRawmtrlNm": raw, "expNm": expiry, "prdlstDcnm": "과자"})


@pytest.fixture()
def db(tmp_path, monkeypatch):
    p = tmp_path / "f.sqlite"
    con = sqlite3.connect(p)
    con.executescript(upd.SCHEMA)
    con.executemany("insert into product values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        _rec("1", "gf", "(주)오리온", "초코파이", "밀가루(미국산),설탕,전란액,버터"),
        _rec("2", "gf", "롯데웰푸드(주)", "칙촉오리지널", "밀가루,초콜릿,땅콩"),
        _rec("3", "gf", "가나식품", "쌀과자", "쌀,설탕"),
        _rec("4", "gf", "나다식품", "쌀과자", "쌀,우유"),            # 같은 이름, 다른 제조사
        _rec("5", "ff", "(주)일화", "홍삼스틱골드", "홍삼"),
    ])
    con.commit(); con.close()
    monkeypatch.setenv("FOOD24_DB_PATH", str(p))
    f24.match.cache_clear()
    yield p
    f24.match.cache_clear()


def test_allergen_tokens_are_word_based():
    assert f24.allergens_in("밀가루(미국산),설탕,전란액,버터") == {"gluten", "egg", "dairy"}
    assert f24.allergens_in("밀크씨슬,밀납,글리세린") == set()
    assert f24.allergens_in("유청칼슘") == {"dairy"} and f24.allergens_in("보리차") == {"gluten"}
    assert f24.allergens_in("혼합견과(아몬드,호두)") == {"nuts"}


def test_match_requires_company_or_unique_name(db):
    r = f24.match("오리온 초코파이 情 12개입")
    assert r["name"] == "초코파이" and r["company_matched"] and "gluten" in r["allergens"]
    assert f24.match("홍삼스틱골드 30포")["company_matched"] is False   # 이름이 유일하면 매칭은 하되 제조사 미확인
    assert f24.match("바삭 쌀과자 300g") is None                         # 제조사 여럿 → 단정하지 않음
    assert f24.match("가나식품 쌀과자 300g")["report_no"] == "3"


def test_public_info_has_source_and_allergen_labels(db):
    info = f24.public_info(f24.match("오리온 초코파이"))
    assert "식품정보24" in info["source"] and info["expiry"] == "제조일로부터 12개월"
    assert "밀(글루텐)" in info["allergens"]


class _Market:
    code, enabled = "fake", True

    def __init__(self, titles):
        self.titles = titles

    def search(self, query, limit=20):
        return [Offer(mall="fake", mall_product_id=str(i), title=t, price=3000 + i, shipping_fee=0, url="u")
                for i, t in enumerate(self.titles)]


def test_recommender_excludes_products_with_allergen_in_raw(db):
    class _NoEngine:
        available = False
    rec = Recommender(markets=MarketRegistry(adapters=[_Market(["롯데 칙촉 오리지널 과자", "가나식품 쌀과자 과자", "오리온 초코파이 과자"])]),
                      engine=_NoEngine())
    _, items = rec.recommend(Intent(action="allergy", slots={"product": "과자", "allergen": "nuts"}))
    titles = [x.offer.title for x in items]
    assert "롯데 칙촉 오리지널 과자" not in titles   # 제조사 미확인이어도 원재료에 땅콩 → 제외 and rec.last_allergen_excluded == 1
    ssal = next(x for x in items if "쌀과자" in x.offer.title)
    assert any("견과류·땅콩 표기 없음" in e for e in ssal.evidence)
    assert "같은 시설 제조(교차오염) 표시" in ssal.unverified
