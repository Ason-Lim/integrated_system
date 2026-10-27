"""B안 블로그 초안·쇼핑커넥트 발급 후보 (네이버 쇼핑 검색 API 2026-07-31 종료 대응)."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_blog_draft_has_disclosure_first_and_no_links_or_prices(tmp_path, monkeypatch):
    monkeypatch.setenv("RECIPE_CATALOG_PATH", str(tmp_path / "none.json"))
    monkeypatch.setenv("STORAGE_GUIDE_PATH", str(tmp_path / "none.json"))
    m = _load("make_blog_draft")
    title, tags, body = m.build("대봉감", ["대봉감 홍시 10kg"])
    assert title.startswith("[광고]")
    first = body.split("\n")[0]
    assert "쇼핑 커넥트 활동의 일환" in first and "수수료" in first and "운영에 도움" in first
    assert "쇼핑커넥트'로 상품 삽입: 대봉감 홍시 10kg" in body
    assert "http" not in body and "원" not in body.replace("원문", "")


def test_josa_ro():
    m = _load("make_blog_draft")
    assert (m.ro("대봉감"), m.ro("배"), m.ro("쌀")) == ("대봉감으로", "배로", "쌀로")


def test_candidate_keyword_strips_conditions():
    m = _load("build_connect_candidates")
    assert m.keyword_of("과메기 비린내 없이 같이") == "과메기"
    assert m.keyword_of("택배 받아도 굳지 찹쌀떡") == "찹쌀떡"
