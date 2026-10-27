"""제휴 수수료 고지 (공정위 추천·보증 심사지침 2024 개정 / 쿠팡 파트너스 정책)."""
from pathlib import Path

from consumer import presenter
from shared import affiliate
from shared.models import Block, text_block

ROOT = Path(__file__).resolve().parents[1]


def _list(*malls):
    return Block(type="product_list", data={"items": [{"mall": m, "url": f"https://x/{m}", "title": m} for m in malls]})


def test_coupang_disclosure_is_explicit_and_keeps_support_line():
    t = affiliate.disclosure(["coupang"])
    assert "쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다." in t
    assert "본 사이트 운영" in t and "무료 서비스" in t      # 운영 취지 문구는 반드시 유지
    assert "추천 순위에 반영하지 않습니다" in t
    assert "발생할 수 있" not in t                           # 모호한 표현 금지


def test_naver_search_links_are_not_affiliate_unless_shopping_connect(monkeypatch):
    monkeypatch.delenv("NAVER_SHOPPING_CONNECT", raising=False)
    assert affiliate.disclosure(["naver"]) is None
    monkeypatch.setenv("NAVER_SHOPPING_CONNECT", "1")
    assert "네이버 쇼핑 커넥트" in affiliate.disclosure(["naver"])
    assert "쿠팡 파트너스·네이버 쇼핑 커넥트" in affiliate.disclosure(["coupang", "naver"])


def test_disclosure_goes_first_once():
    blocks = presenter.with_disclosure([text_block("추천해요"), _list("coupang", "naver")])
    assert blocks[0].type == "notice" and blocks[0].data["affiliate"] is True
    assert len(presenter.with_disclosure(blocks)) == len(blocks)        # 중복으로 붙이지 않음


def test_nested_comparison_pair_cards_are_detected():
    b = Block(type="comparison_pair", data={"pairs": [{"cards": [{"mall": "coupang", "url": "u", "title": "a"}]}]})
    assert presenter.with_disclosure([b])[0].data.get("affiliate")


def test_no_disclosure_without_affiliate_links():
    assert presenter.with_disclosure([text_block("레시피"), _list("sample")])[0].type == "text"
    blk = Block(type="product_list", data={"items": [{"mall": "coupang", "url": None, "title": "x"}]})
    assert presenter.with_disclosure([blk])[0].type == "product_list"     # 링크 없으면 수수료도 없음


def test_old_vague_bottom_notice_removed():
    src = (ROOT / "consumer" / "presenter.py").read_text(encoding="utf-8")
    assert "수수료가 발생할 수 있으며" not in src
