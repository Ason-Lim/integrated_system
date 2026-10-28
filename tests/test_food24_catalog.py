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
    monkeypatch.setenv("FOOD24_IN_SERVICE", "1")
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
    # 원재료가 일부만 공개되므로 '없음'을 근거로 내세우지 않는다
    assert not any("표기 없음" in e for e in ssal.evidence)
    assert "알레르기 성분·교차오염 원문 확인" in ssal.unverified



def test_service_switch_off_by_default(db, monkeypatch):
    monkeypatch.setenv("FOOD24_IN_SERVICE", "0")
    f24.match.cache_clear()
    assert not f24.available() and f24.match("오리온 초코파이") is None   # DB가 있어도 스위치가 꺼져 있으면 쓰지 않음


# ── 매칭 정확성 (2026-10-28 점검에서 찾은 오연결 유형) ───────────────────────────
@pytest.fixture()
def db2(tmp_path, monkeypatch):
    p = tmp_path / "g.sqlite"
    con = sqlite3.connect(p)
    con.executescript(upd.SCHEMA)
    con.executemany("insert into product values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        _rec("11", "ff", "농업회사법인주식회사고려인삼", "고려인삼농축액골드", "인삼농축액"),
        _rec("12", "ff", "고려인삼제조주식회사", "고려인삼농축액골드", "인삼농축액,정제수"),
        _rec("21", "ff", "(주)알피바이오", "알피바이오 알티지 오메가3", "오메가-3"),
        _rec("22", "ff", "(주)알피바이오", "알티지(rTG) 오메가3 브이(V)", "오메가-3,비타민D"),
        _rec("31", "ff", "동서바이오팜(주)", "프로신프로폴리스", "프로폴리스추출물"),
        _rec("32", "ff", "동서바이오팜(주) 안성공장", "프로신프로폴리스", "프로폴리스추출물,비타민E"),
        _rec("41", "ff", "주)팜크로스", "울트라비타민D3 1000", "비타민D3"),
        _rec("51", "ff", "(주)서흥", "밀크씨슬", "밀크씨슬추출물"),
        _rec("52", "ff", "(주)서흥", "밀크씨슬+", "밀크씨슬추출물,비타민B1"),
        _rec("61", "ff", "콜마비앤에이치(주)음성공장", "장건강 유산균", "프로바이오틱스"),
    ])
    con.commit(); con.close()
    monkeypatch.setenv("FOOD24_DB_PATH", str(p))
    monkeypatch.setenv("FOOD24_IN_SERVICE", "1")
    f24.match.cache_clear()
    yield p
    f24.match.cache_clear()


def test_company_inside_product_name_is_not_evidence(db2):
    # '고려인삼' 이 제품명 안에 있어도 제조사 확인 근거가 아니다 → 상품명 앞의 '고려인삼제조' 로 확인
    assert f24.match("고려인삼제조 고려인삼농축액골드 60정")["report_no"] == "12"


def test_brand_prefix_does_not_swallow_longer_name(db2):
    assert f24.match("알피바이오 알티지(rTG) 오메가3 브이(V) 60정")["report_no"] == "22"


def test_factory_suffix_and_punctuation(db2):
    assert f24.match("동서바이오팜안성공장 프로신프로폴리스 60정")["report_no"] == "32"   # 공장까지 같은 쪽
    assert f24.match("팜크로스 울트라비타민D3 1000 60정")["company_matched"]           # '주)팜크로스'
    assert f24.match("콜마비앤에이치 장건강 유산균 30포")["company_matched"]           # 공장 뗀 회사명
    assert f24._company_keys("대상웰라이프(주) 천안2공장")[-1] == "대상웰라이프"
    assert f24._company_keys("주식회사 노바렉스2공장") == ["노바렉스2공장", "노바렉스"]


def test_same_maker_symbol_only_names_with_different_raw_are_not_decided(db2):
    assert f24.match("서흥 밀크씨슬+ 60정") is None          # '+' 는 정규화에서 빠짐 → 원재료가 다른 두 신고
