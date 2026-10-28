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


def test_recommender_excludes_products_with_allergen_in_raw(db, monkeypatch):
    monkeypatch.setenv("FOOD24_ALLERGEN_FILTER", "1")      # 알레르기 제외는 별도 스위치 (기본 꺼짐)
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


# ── 제품 구분자(괄호 안 숫자+단위)·원재료 4필드 모호성 (2026-10-28 교차 검토) ──────────────
def _rec4(no, company, name, raw="", functional="", etc="", capsule=""):
    return upd.row_of("ff", {"prdlstReportNo": no, "lcnsNo": "1", "bsshNm": company, "prdlstNm": name,
                             "totRawmtrlNm": raw, "indivRawmtrlNm": functional, "etcRawmtrlNm": etc,
                             "capRawmtrlNm": capsule, "prdlstDcnm": "프로바이오틱스"})


@pytest.fixture()
def db3(tmp_path, monkeypatch):
    p = tmp_path / "h.sqlite"
    con = sqlite3.connect(p)
    con.executescript(upd.SCHEMA)
    co = "일동바이오사이언스(주)"
    con.executemany("insert into product values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        _rec4("71", co, "비피도박테리움 락티스 아이디씨씨(IDCC) 4301 (100B) <전량수출용>", "프로바이오틱스"),
        _rec4("72", co, "비피도박테리움 락티스 아이디씨씨(IDCC) 4301 (0.1B) <전량수출용>", "프로바이오틱스"),
        _rec4("73", co, "락티플란티바실러스 플란타럼 아이디씨씨(IDCC) 3501 (300B)", "프로바이오틱스"),
        # 주원재료는 같고 기능성·캡슐 원재료만 다른 두 신고 (이름은 정규화하면 같음)
        _rec4("81", "(주)서흥", "루테인 지아잔틴", "마리골드꽃추출물", functional="루테인"),
        _rec4("82", "(주)서흥", "루테인-지아잔틴", "마리골드꽃추출물", functional="루테인,지아잔틴"),
        _rec4("91", "(주)노바렉스", "오메가3 알티지", "정제어유", capsule="젤라틴"),
        _rec4("92", "(주)노바렉스", "오메가3 알티지", "정제어유", capsule="식물성캡슐(카라기난)"),
        _rec4("95", "(주)노바렉스", "비타민C 플러스", "비타민C", etc="결정셀룰로스"),
        _rec4("96", "(주)노바렉스", "비타민C플러스", "비타민C", etc="결정셀룰로스 "),     # 띄어쓰기만 다름
    ])
    con.commit(); con.close()
    monkeypatch.setenv("FOOD24_DB_PATH", str(p))
    monkeypatch.setenv("FOOD24_IN_SERVICE", "1")
    f24.match.cache_clear()
    yield p
    f24.match.cache_clear()


def test_markers_keep_bracketed_distinguishers():
    assert ("100", "b") in f24.markers("락티스 (100B) <전량수출용>")
    assert ("0.1", "b") in f24.markers("락티스 (0.1B)") and ("1000", "iu") in f24.markers("비타민D 1,000IU")
    assert f24.marker_conflict("락티스 (0.1B)", "일동 락티스 (100B) 60정")
    assert not f24.marker_conflict("락티스 (100B)", "일동 락티스 (100B) 60정")
    assert not f24.marker_conflict("락티스 (100B)", "일동 락티스 60정")      # 상품명에 값이 없으면 거부하지 않음


def test_different_distinguisher_is_rejected(db3):
    t = "일동바이오사이언스 비피도박테리움 락티스 아이디씨씨(IDCC) 4301 ({}) <전량수출용> 60정"
    assert f24.match(t.format("100B"))["report_no"] == "71"
    assert f24.match(t.format("0.1B"))["report_no"] == "72"
    assert f24.match(t.format("300B")) is None                              # 300B 신고는 이 이름에 없음
    assert f24.match("일동바이오사이언스 락티플란티바실러스 플란타럼 아이디씨씨(IDCC) 3501 (100B)") is None


def test_ambiguity_compares_all_raw_fields_without_name_norm(db3):
    assert f24.match("서흥 루테인 지아잔틴 30캡슐") is None          # 기능성 원재료가 다름
    assert f24.match("노바렉스 오메가3 알티지 60캡슐") is None        # 캡슐 원재료가 다름
    r = f24.match("노바렉스 비타민C플러스 60정")                      # 띄어쓰기만 다른 같은 원재료 → 단정 가능
    assert r and r["company_matched"] and r["report_no"] in {"95", "96"}
    assert f24._raw_norm("식물성캡슐(카라기난)") != f24._raw_norm("식물성캡슐")   # 괄호 내용을 지우지 않음


def test_company_key_must_start_a_word(tmp_path, monkeypatch):
    """'대웅생명과학' 상품명의 '생명과학'은 '(주)생명과학' 제조사 근거가 아니다 (실제 상품명 평가 2026-10-28)"""
    p = tmp_path / "w.sqlite"
    con = sqlite3.connect(p)
    con.executescript(upd.SCHEMA)
    con.executemany("insert into product values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        _rec("1", "ff", "(주)생명과학", "밀크씨슬", "밀크씨슬추출물"),
        _rec("2", "ff", "주식회사 힐링", "영국산 비타민C 3000", "비타민C")])
    con.commit(); con.close()
    monkeypatch.setenv("FOOD24_DB_PATH", str(p))
    monkeypatch.setenv("FOOD24_IN_SERVICE", "1")
    f24.match.cache_clear()
    assert f24.match("대웅생명과학 간건강 눈건강엔 밀크씨슬 루테인, 60정")["company_matched"] is False
    assert f24.match("생명과학 밀크씨슬 60정")["company_matched"] is True
    assert f24.match("아임힐링 영국산 비타민C 3000 100포")["company_matched"] is False
    f24.match.cache_clear()



# ── 2026-10-28 3차: 제조사 끝 경계·검증 별칭, limit 제거, 실제 단계 사유, 겹치는 신고 ──────────────
def _mkdb(tmp_path, monkeypatch, rows, name="z.sqlite"):
    p = tmp_path / name
    con = sqlite3.connect(p)
    con.executescript(upd.SCHEMA)
    con.executemany("insert into product values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit(); con.close()
    monkeypatch.setenv("FOOD24_DB_PATH", str(p))
    monkeypatch.setenv("FOOD24_IN_SERVICE", "1")
    f24.match.cache_clear()
    return p


def test_company_key_must_end_at_word_boundary(tmp_path, monkeypatch):
    _mkdb(tmp_path, monkeypatch, [_rec("1", "ff", "(주)서흥", "퓨어 밀크씨슬", "밀크씨슬추출물")])
    assert f24.match_explain("서흥헬스 퓨어 밀크씨슬 42g")[1] == "company_unconfirmed"   # '서흥헬스' ≠ '서흥'
    assert f24.match_explain("서흥 퓨어 밀크씨슬 42g")[1] == "ok"
    assert f24.match_explain("서흥퓨어 밀크씨슬 42g")[1] == "ok"         # 제조사 바로 뒤가 제품명 시작이면 인정


def test_only_verified_aliases_confirm_company(tmp_path, monkeypatch):
    import json
    _mkdb(tmp_path, monkeypatch, [_rec("1", "ff", "(주)한국인삼공사", "홍삼정 에브리타임", "홍삼농축액")])
    alias = tmp_path / "aliases.json"
    monkeypatch.setenv("FOOD24_ALIAS_FILE", str(alias))
    entry = {"alias": "정관장", "company": "(주)한국인삼공사", "evidence": "포장 표시 확인", "verified_at": "2026-10-28"}
    for status, want in (("proposed", "company_unconfirmed"), ("verified", "ok")):
        alias.write_text(json.dumps({"aliases": [{**entry, "status": status}]}), encoding="utf-8")
        f24._aliases.cache_clear(); f24.match.cache_clear()
        assert f24.match_explain("정관장 홍삼정 에브리타임 30포")[1] == want, status
    alias.write_text(json.dumps({"aliases": [{**entry, "status": "verified", "evidence": ""}]}), encoding="utf-8")
    f24._aliases.cache_clear(); f24.match.cache_clear()
    assert f24.match_explain("정관장 홍삼정 에브리타임 30포")[1] == "company_unconfirmed"   # 근거 없으면 안 씀
    f24._aliases.cache_clear()


def test_no_limit_keeps_correct_candidate_beyond_40(tmp_path, monkeypatch):
    # 같은 이름 '밀크씨슬'을 45개 제조사가 신고, 정답 제조사는 정렬상 맨 뒤 → limit 40 이면 잘려 나간다
    rows = [_rec(f"{i:03d}", "ff", f"가나다{i:02d}바이오", "밀크씨슬", "밀크씨슬추출물") for i in range(45)]
    rows.append(_rec("999", "ff", "하하바이오", "밀크씨슬", "밀크씨슬추출물,비타민B1"))
    _mkdb(tmp_path, monkeypatch, rows)
    r, why = f24.match_explain("하하바이오 밀크씨슬 60정")
    assert r and r["report_no"] == "999" and r["company_matched"], why


def test_no_limit_keeps_conflicting_candidate_beyond_40(tmp_path, monkeypatch):
    # 같은 제조사가 같은 이름으로 41건 신고 — 41번째만 원재료가 다르다 → 잘리면 '단정 가능'으로 잘못 판단
    rows = [_rec(f"{i:03d}", "ff", "(주)서흥", "밀크씨슬", "밀크씨슬추출물") for i in range(41)]
    rows.append(_rec("999", "ff", "(주)서흥", "밀크씨슬", "밀크씨슬추출물,비타민B1"))
    _mkdb(tmp_path, monkeypatch, rows)
    assert f24.match_explain("서흥 밀크씨슬 60정") == (None, "raw_ambiguous")


def test_reasons_come_from_actual_step(tmp_path, monkeypatch):
    _mkdb(tmp_path, monkeypatch, [
        _rec("1", "ff", "가나바이오", "루테인골드", "루테인"), _rec("2", "ff", "다라바이오", "루테인골드", "루테인"),
        _rec("3", "ff", "마바바이오", "유산균 (100B)", "프로바이오틱스")])
    assert f24.match_explain("ab")[1] == "title_too_short"
    assert f24.match_explain("전혀 다른 상품명 60정")[1] == "no_name_in_title"
    assert f24.match_explain("마바바이오 유산균 (300B)")[1] == "distinguisher_conflict"
    assert f24.match_explain("루테인골드 60정")[1] == "same_name_multiple_companies"
    monkeypatch.setenv("FOOD24_IN_SERVICE", "0")
    f24.match.cache_clear()
    assert f24.match_explain("가나바이오 루테인골드")[1] == "service_off"
    f24.match.cache_clear()


def test_sibling_reports_are_not_auto_displayed(tmp_path, monkeypatch):
    # 실제 상품명 평가의 판단불가 유형: 같은 제조사에 이름이 서로 포함되는 신고가 있음
    _mkdb(tmp_path, monkeypatch, [
        _rec("1", "ff", "종근당건강(주)", "락토핏 골드", "프로바이오틱스"),
        _rec("2", "ff", "종근당건강(주)", "락토핏 골드 80포", "프로바이오틱스"),
        _rec("3", "ff", "종근당건강(주)", "아이팜루테인", "루테인")])
    r, why = f24.match_explain("종근당건강 락토핏 골드")
    assert why == "sibling_reports" and r["company_matched"] and not r["display_ok"] and "락토핏 골드 80포" in r["siblings"]
    r, why = f24.match_explain("종근당건강 눈에 좋은 아이팜 루테인, 90정")
    assert why == "ok" and r["display_ok"]


def test_presenter_shows_only_display_ok(tmp_path, monkeypatch):
    from consumer import presenter
    _mkdb(tmp_path, monkeypatch, [_rec("1", "ff", "종근당건강(주)", "락토핏 골드", "프로바이오틱스"),
                                  _rec("2", "ff", "종근당건강(주)", "락토핏 골드 80포", "프로바이오틱스"),
                                  _rec("3", "ff", "종근당건강(주)", "아이팜루테인", "루테인")])
    assert presenter._public_info("종근당건강 락토핏 골드") is None
    assert presenter._public_info("종근당건강 아이팜루테인 90정")["report_no"] == "3"


def test_allergen_filter_has_its_own_switch(db, monkeypatch):
    monkeypatch.delenv("FOOD24_ALLERGEN_FILTER", raising=False)
    assert f24.available() and not f24.allergen_filter_enabled()     # 매칭을 켜도 알레르기 제외는 꺼진 채


def test_translation_only_name_variant_is_sibling(tmp_path, monkeypatch):
    _mkdb(tmp_path, monkeypatch, [_rec("1", "ff", "(주)한국씨엔에스팜", "골든에센셜(Golden Essential)", "오메가3"),
                                  _rec("2", "ff", "(주)한국씨엔에스팜", "골든 에센셜", "오메가3")])
    r, why = f24.match_explain("한국씨엔에스팜 골든에센셜(Golden Essential) 60정")
    assert why == "sibling_reports" and not r["display_ok"]


def test_switch_is_checked_outside_cache_on_off_on(db, monkeypatch):
    """같은 프로세스에서 켬 → 끔 → 켬: 캐시된 결과가 꺼진 상태로 새지 않는다"""
    t = "오리온 초코파이 情 12개입"
    monkeypatch.setenv("FOOD24_IN_SERVICE", "1")
    assert f24.match(t)["report_no"] == "1"                    # 켬: 결과가 캐시에 들어감
    monkeypatch.setenv("FOOD24_IN_SERVICE", "0")
    assert f24.match_explain(t) == (None, "service_off")       # 끔: 캐시를 지우지 않아도 막힘
    assert f24.match(t) is None
    from consumer import presenter
    assert presenter._public_info(t) is None
    monkeypatch.setenv("FOOD24_IN_SERVICE", "1")
    r = f24.match(t)
    assert r["report_no"] == "1"
    r["name"] = "변조"                                          # 호출부가 고쳐도 캐시는 그대로
    assert f24.match(t)["name"] == "초코파이"
