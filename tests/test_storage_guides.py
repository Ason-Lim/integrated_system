"""식재료 보관·손질 질문 (2026-10-27 '대봉감 … 어떻게 보관해?'가 상품 추천으로 처리된 문제)."""
import importlib.util
import json
from pathlib import Path

import pytest

from consumer.dialogue import DialogueManager
from shared import storage_guides
from shared.nlu import rule_nlu

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("update_storage_guides", ROOT / "scripts" / "update_storage_guides.py")
collector = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collector)

STRAWBERRY = ("품종특성 구입요령\n■ 품종특성\n- 장미과\n■ 구입요령\n- 광택이 있는 것<br/>- 꼭지가 초록빛인 것\n"
              "보관법 손질법\n■ 보관법\n- 랩을 씌워 보관\n- 상온에서 하루 이상 보존하기 어려움\n■ 손질법\n- 흐르는 물에 빨리 씻는다")


@pytest.fixture()
def guides(tmp_path, monkeypatch):
    def g(no, name, storage, prep=(), purchase=()):
        return {"id": f"nongsaro-{no}", "name": name, "aliases": collector.aliases(name), "storage": list(storage),
                "prep": list(prep), "purchase": list(purchase), "source_name": collector.SOURCE_NAME}
    doc = {"guides": [g(1, "딸기", ["랩을 씌워 보관"], ["흐르는 물에 씻는다"], ["광택이 있는 것"]),
                      g(2, "감(단감·대봉감)", ["홍시는 서늘한 곳에서 후숙"]),
                      g(3, "감자", ["빛이 들지 않는 곳에 보관"]),
                      g(4, "산딸기", ["바로 먹는다"])]}
    p = tmp_path / "storage_guides.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("STORAGE_GUIDE_PATH", str(p))
    monkeypatch.setenv("RECIPE_CATALOG_PATH", str(tmp_path / "no_recipes.json"))
    return p


def test_collector_splits_sections_and_drops_tab_labels():
    sec = collector.parse_detail({"fdmtNm": "딸기", "cn": STRAWBERRY})
    assert sec["storage"] == ["랩을 씌워 보관", "상온에서 하루 이상 보존하기 어려움"]
    assert sec["prep"] == ["흐르는 물에 빨리 씻는다"]
    assert sec["purchase"] == ["광택이 있는 것", "꼭지가 초록빛인 것"]
    # 머리말이 없으면 태그 이름으로 추정
    assert collector.parse_detail({"strgMth": "서늘한 곳"}) == {"storage": ["서늘한 곳"]}


def test_storage_intent():
    assert rule_nlu.parse("대봉감 홍시 만들려면 며칠 두고 어떻게 보관해?").action == "storage_info"
    assert rule_nlu.parse("딸기 고르는 법 알려줘").action == "storage_info"
    assert rule_nlu.parse("냉장 배송되는 소고기 추천해줘").action == "recommend_food"


def test_find_prefers_specific_and_avoids_prefix_collision(guides):
    g, asked = storage_guides.find("대봉감 홍시 만들려면 며칠 두고 어떻게 보관해?")
    assert g["name"] == "감(단감·대봉감)" and asked == "대봉감"
    assert storage_guides.find("감자 보관법")[0]["name"] == "감자"     # '감'으로 잘못 잡지 않음
    assert storage_guides.find("과메기 손질법") is None


def test_chat_answers_from_public_guide(guides):
    r = DialogueManager(persist=False).handle(None, message="딸기 보관 어떻게 해?")
    md = r["blocks"][0]["data"]["md"]
    assert "**보관법**" in md and "- 랩을 씌워 보관" in md and "농사로" in md
    assert all(b["type"] != "product_list" for b in r["blocks"])
    assert {"label": "딸기 상품 보기", "value": "딸기 추천해줘"} in r["blocks"][1]["data"]["items"]


def test_chat_says_not_found_without_inventing(guides):
    r = DialogueManager(persist=False).handle(None, message="과메기 손질 어떻게 해?")
    md = r["blocks"][0]["data"]["md"]
    assert "찾지 못했어요" in md and "과메기" in md


def test_collector_reads_nongsaro_detail_fields():
    f = {"fdmtNm": "딸기", "prchCheatDtl": "<p>- 광택이 있는 것</p>",
         "cstdyMthDtl": "■ 보관법<br>- 랩을 씌워 보관<br>■ 손질법<br>- 흐르는 물에 씻는다",
         "ntkMthDtl": "생과로 먹거나 잼으로", "ntrIrdntEfcyDtl": "비타민C"}
    assert collector.parse_detail(f) == {"storage": ["랩을 씌워 보관"], "prep": ["흐르는 물에 씻는다"],
                                         "purchase": ["광택이 있는 것"], "eat": ["생과로 먹거나 잼으로"]}


def test_collector_ignores_non_text_fields():
    assert collector.parse_detail({"fdmtNm": "쌀", "_month": 10, "cstdyMthDtl": "■ 보관법<br>- 밀봉해 서늘한 곳"}) == \
        {"storage": ["밀봉해 서늘한 곳"]}


def test_exact_name_beats_longer_partial(guides):
    assert storage_guides.find("딸기 고르는 법")[0]["name"] == "딸기"      # '산딸기'가 아니라
    assert storage_guides.find("산딸기 보관")[0]["name"] == "산딸기"
