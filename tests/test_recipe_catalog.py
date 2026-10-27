"""공공 레시피 DB 로컬 카탈로그 검색·대화 연결 (2026-10-27 '파스타 레시피로 장보기'가 안내문만 내던 문제)."""
import importlib.util
import json
from pathlib import Path

import pytest

from consumer.dialogue import DialogueManager
from shared import recipe_catalog

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("update_recipes", ROOT / "scripts" / "update_recipes.py")
update_recipes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_recipes)


def _r(rid, name, raw, steps=("재료를 손질한다.",), category="일품", method="끓이기"):
    return {"id": rid, "source": "foodsafety", "source_name": "식품안전나라 조리식품 레시피 DB", "name": name,
            "summary": "", "category": category, "method": method, "kcal": "420", "tags": [],
            "ingredients_raw": raw, "ingredients": update_recipes.parse_ingredients(raw, name),
            "steps": [{"text": update_recipes.clean_step(t), "image": None} for t in steps]}


@pytest.fixture()
def catalog(tmp_path, monkeypatch):
    doc = {"generated_at": "2026-10-27T15:00:00", "recipes": [
        _r("fs-385", "먹물 파스타", "홀토마토 200g, 토마토 100g, 다진양파 30g, 다진마늘 20g, 먹물파스타 25g, 치즈 25g\n소금 1g",
           steps=("1. 토마토를 데친다.a", "2. 파스타를 삶는다.b")),
        _r("fs-12", "토마토 크림 파스타", "스파게티면 100g, 토마토 1개, 생크림 50ml"),
        _r("fs-37", "두부된장국", "된장국\n두부 20g(2×2×2cm), 감자 10g(4×3×1cm), 된장 10g", category="국&찌개"),
        _r("fs-90", "감자조림", "감자 200g, 간장 2큰술, 물엿 1큰술", category="반찬", method="조리기"),
    ]}
    p = tmp_path / "recipes.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("RECIPE_CATALOG_PATH", str(p))
    return p


def test_parse_ingredients_drops_title_line_and_keeps_amount():
    got = update_recipes.parse_ingredients("된장국\n두부 20g(2×2×2cm), 감자 10g", "두부된장국")
    assert [(i["name"], i["amount"]) for i in got] == [("두부", "20g(2×2×2cm)"), ("감자", "10g")]
    got = update_recipes.parse_ingredients("●주재료 : 감 1개, 찹쌀가루 50g\n●양념 : 소금 약간", "감찹쌀전")
    assert [i["name"] for i in got] == ["감", "찹쌀가루", "소금"]


def test_terms_strip_recipe_words():
    assert recipe_catalog.terms("파스타 레시피 장보기") == ["파스타"]
    assert recipe_catalog.terms("감자로 해먹을 요리") == ["감자"]


def test_search_by_dish_and_ingredient(catalog):
    assert [r["name"] for r in recipe_catalog.search("파스타 레시피 장보기")] == ["먹물 파스타", "토마토 크림 파스타"]
    assert recipe_catalog.search("감자 요리")[0]["name"] == "감자조림"   # 이름에 있는 쪽이 먼저
    assert "두부된장국" in [r["name"] for r in recipe_catalog.search("감자 요리")]
    assert recipe_catalog.search("과메기") == []


def test_chat_suggests_recipes_then_shows_detail(catalog):
    dm = DialogueManager(persist=False)
    r = dm.handle(None, message="파스타 레시피로 장보기")
    assert r["stage"] == "clarify"
    assert [b["type"] for b in r["blocks"]] == ["text", "chips"]
    assert "먹물 파스타" in r["blocks"][0]["data"]["md"]
    chip = r["blocks"][1]["data"]["items"][0]
    assert chip == {"label": "먹물 파스타", "value": "먹물 파스타 레시피 보기"}

    d = dm.handle(r["session_id"], message=chip["value"])
    md = d["blocks"][0]["data"]["md"]
    assert "**재료**" in md and "- 홀토마토 200g" in md
    assert "- 1) 토마토를 데친다." in md and "데친다.a" not in md   # 원문 끝 알파벳 표식 제거
    assert "식품안전나라" in md
    shop = d["blocks"][-1]["data"]["items"]
    assert {"label": "홀토마토 사러 가기", "value": "홀토마토 추천해줘"} in shop
    assert all("소금" not in c["label"] and "다진마늘" not in c["label"] for c in shop)   # 기본 양념 제외
    assert all(b["type"] != "product_list" for b in d["blocks"])


def test_without_catalog_falls_back_to_asking(tmp_path, monkeypatch):
    monkeypatch.setenv("RECIPE_CATALOG_PATH", str(tmp_path / "none.json"))
    r = DialogueManager(persist=False).handle(None, message="파스타 레시피 알려줘")
    assert r["stage"] == "clarify" and "원문 레시피" in r["blocks"][0]["data"]["md"]


def test_normalize_group_labels_in_ingredient_names():
    n = update_recipes.normalize_name
    assert n("[절임용 소금물] 소금") == "소금"
    assert n("쇠고기 양념장 생강즙") == "생강즙"
    assert n("저나트륨발사믹소스:간장") == "간장"
    assert n("두 가지 색 파프리카") == "두 가지 색 파프리카"


def test_clean_step_joins_source_line_breaks():
    assert update_recipes.clean_step("1. 단호박은 잘라 씨를 제거하고\n찜통에서 찐다.a") == "단호박은 잘라 씨를 제거하고 찜통에서 찐다."
