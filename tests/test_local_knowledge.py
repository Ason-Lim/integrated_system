"""지역특산물·농가맛집·향토음식 (농사로) 검색과 대화 연결."""
import json

import pytest

from consumer import presenter
from consumer.dialogue import DialogueManager
from shared import local_knowledge
from shared.nlu import rule_nlu


@pytest.fixture()
def local(tmp_path, monkeypatch):
    (tmp_path / "local_specialties.json").write_text(json.dumps({"specialties": [
        {"id": "spc-1", "name": "문경사과", "region": "경상북도 문경시"},
        {"id": "spc-2", "name": "오미자", "region": "경상북도 문경시"},
        {"id": "spc-3", "name": "안동 간고등어", "region": "경상북도 안동시"},
        {"id": "spc-4", "name": "한라봉", "region": "제주특별자치도 서귀포시"},
    ]}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "farm_restaurants.json").write_text(json.dumps({"restaurants": [
        {"id": "frm-1", "name": "산골밥상", "region": "경상북도 문경시", "address": "문경시 문경읍 1",
         "menu": "오미자 비빔밥", "tel": "054-000-0000"},
    ]}, ensure_ascii=False), encoding="utf-8")
    recipes = tmp_path / "recipes.json"
    recipes.write_text(json.dumps({"recipes": [
        {"id": "clsrc-7", "source": "nongsaro_head", "name": "건진국수", "region": "경상북도 안동시", "house": "학봉종가",
         "ingredients": [], "steps": [{"text": "삶는다."}], "tags": ["종가음식"]},
    ]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("LOCAL_KNOWLEDGE_DIR", str(tmp_path))
    monkeypatch.setenv("RECIPE_CATALOG_PATH", str(recipes))
    return tmp_path


def test_local_intent_excludes_shop_slang():
    assert rule_nlu.parse("문경 특산물 뭐 있어?").action == "local_info"
    assert rule_nlu.parse("안동 농가맛집 알려줘").action == "local_info"
    assert rule_nlu.parse("택배로 받아도 굳지 않는 찹쌀떡 맛집 추천해 줘").action == "recommend_food"
    assert rule_nlu.parse("안동 향토음식 레시피").action == "recipe"


def test_region_keys_and_find_region(local):
    assert {"경북", "경상북도", "문경", "문경시"} <= local_knowledge.region_keys("경상북도 문경시")
    assert local_knowledge.find_region("문경 특산물 뭐 있어?") == "문경"
    assert local_knowledge.find_region("사과 추천해줘") is None


def test_specialty_needs_region_and_item(local):
    assert local_knowledge.specialty_for("문경 감홍사과")["name"] == "문경사과"
    assert local_knowledge.specialty_for("감홍사과") is None          # 지역 없으면 특산물이라 말하지 않음
    assert local_knowledge.specialty_for("문경 배") is None            # 지역만 맞고 품목이 다르면 아님


def test_chat_local_info_lists_specialties_restaurants_and_recipes(local):
    r = DialogueManager(persist=False).handle(None, message="문경 특산물이랑 농가맛집 알려줘")
    md = r["blocks"][0]["data"]["md"]
    assert "- 문경사과 (경상북도 문경시)" in md and "- 오미자 (경상북도 문경시)" in md
    assert "**산골밥상**" in md and "오미자 비빔밥" in md and "농사로" in md
    assert "한라봉" not in md
    chips = r["blocks"][1]["data"]["items"]
    assert {"label": "문경사과 사러 가기", "value": "문경 문경사과 추천해줘"} in chips


def test_chat_local_info_includes_head_family_recipes(local):
    r = DialogueManager(persist=False).handle(None, message="안동 특산물 뭐 있어?")
    md = r["blocks"][0]["data"]["md"]
    assert "안동 간고등어" in md and "건진국수 (학봉종가)" in md


def test_chat_local_info_asks_region_when_missing(local):
    r = DialogueManager(persist=False).handle(None, message="특산물 뭐 있어?")
    assert "어느 지역" in r["blocks"][0]["data"]["md"]
    assert r["blocks"][1]["data"]["items"] == presenter.ASK_REGIONS


def test_menu_names_and_non_food_filter():
    r = {"detail": "농가맛집 대표 상차림\n저염식으로 건강한 음식을 추구한다.\n안골반상\n뽕잎밥과 된장찌개가 차려진다.\n숲속반상\n농가맛집의 또다른 매력\n체험"}
    assert local_knowledge.menu_names(r) == ["안골반상", "숲속반상"]
    assert not local_knowledge.is_food({"name": "짚공예"}) and local_knowledge.is_food({"name": "오미자"})
