"""Source-supplied recipe workflow. No invented recipe corpus or automatic shopping."""
from pydantic import BaseModel, Field
from shared.recipe_contracts import RecipeEvidence, shortage


class Ingredient(BaseModel):
    name: str
    required: bool = True
    quantity: float | None = Field(None, ge=0)
    unit: str | None = None
    cooking_state: str | None = None
    owned: float | None = Field(None, ge=0)
    owned_unit: str | None = None
    owned_state: str | None = None
    owned_raw: str | None = None          # "조금 있어요", "동전 크기만큼" 등 원문
    evidence: RecipeEvidence


class RecipePlan(BaseModel):
    title: str
    ingredients: list[Ingredient] = Field(default_factory=list, max_length=100)

    def evaluate(self):
        rows = []
        for i in self.ingredients:
            result = shortage(
                i.quantity, i.owned, i.unit, i.owned_unit,
                i.cooking_state, i.owned_state,
                name=i.name, owned_raw=i.owned_raw,
            )
            rows.append({
                "name": i.name,
                "required": i.required,
                **result,
                "evidence": i.evidence.quantities(),
            })

        # 요리 진행 가능 여부 (필수 재료 중 cooking_possible=False 가 있으면 불가)
        can_cook = all(
            r.get("cooking_possible") is not False
            for r in rows if r["required"]
        )
        # 구매 확정 가능한 필수 부족분
        confirmed_missing = [
            r for r in rows
            if r["required"] and r.get("purchase_confirmed") and (r.get("shortage") or 0) > 0
        ]
        # 질문 필요한 항목
        needs_question = [r["name"] for r in rows if r.get("question")]

        return {
            "title": self.title,
            "ingredients": rows,
            "can_cook": can_cook,
            "confirmed_missing": confirmed_missing,
            "needs_question": needs_question,
            "status": "READY" if can_cook and not needs_question else "NEEDS_REVIEW",
            "api_calls": 0,
            "shopping_dispatch": False,
        }