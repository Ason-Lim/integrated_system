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
