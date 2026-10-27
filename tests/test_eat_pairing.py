"""'과메기 처음 사보는데 비린내 없이 먹는 법이랑 같이 살 거 알려줘' (2026-10-27 화면: 상품 0건 + 예산 질문)."""
import json

from consumer import presenter
from consumer.dialogue import DialogueManager
from shared.models import Intent
from shared.nlu import rule_nlu

Q = "과메기 처음 사보는데 비린내 없이 먹는 법이랑 같이 살 거 알려줘"
RECIPE = {"id": "nvpc-1", "name": "과메기", "source": "nongsaro_local", "source_name": "농촌진흥청 농사로 향토음식",
          "ingredients": [{"name": n} for n in ["과메기", "생미역", "실파", "소금", "마늘", "풋고추", "고추장"]],
          "steps": [{"text": "과메기는 뼈를 발라 낸다."}, {"text": "생미역, 마늘편, 실파, 초고추장을 곁들인다."}]}


def test_query_is_clean_and_flags_set():
    i = rule_nlu.parse(Q)
    assert i.action == "recommend_food" and i.slots["product"] == "과메기"
    assert i.slots["want_eat"] and i.slots["want_pairing"]


def test_eat_pairing_block_uses_public_recipe():
    b = presenter.eat_pairing_blocks("과메기", RECIPE, True, True)
    md = b[0].data["md"]
    assert "농사로 향토음식" in md and "- 1) 과메기는 뼈를 발라 낸다." in md
    assert "생미역, 실파, 풋고추, 고추장" in md and "소금" not in md      # 기본 양념 제외
    labels = [c["label"] for c in b[1].data["items"]]
    assert "생미역 사러 가기" in labels and "과메기 레시피 전체" in labels


def test_not_found_has_no_budget_form_but_retry_chip():
    blocks = presenter.recommendation_blocks(Intent(action="recommend_food", slots={"product": "과메기 초장 세트"}),
                                             [], active_malls=["coupang"])
    assert [b.type for b in blocks] == ["text", "chips"]
    assert blocks[1].data["items"][0]["value"] == "과메기 추천해줘"


def test_chat_adds_eat_pairing_after_recommendation(tmp_path, monkeypatch):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"recipes": [RECIPE]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("RECIPE_CATALOG_PATH", str(p))
    r = DialogueManager(persist=False).handle(None, message=Q)
    mds = [b["data"].get("md", "") for b in r["blocks"] if b["type"] == "text"]
    assert any("과메기 먹는 법·곁들임" in m for m in mds)
