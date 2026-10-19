"""소비자용 추천 앱 (공개).

실행:  uvicorn consumer.app:app --port 8000
화면:  http://127.0.0.1:8000/
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from consumer.dialogue import DialogueManager
from consumer.recipes import RecipePlan
from shared import store

WEB = Path(__file__).parent / "web"
app = FastAPI(title="commerce_ai — 대화형 추천", version="1.0")
dm = DialogueManager()


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str | None = Field(None, max_length=500)
    answers: dict[str, str] | None = None
    chip: str | None = None


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.post("/api/chat")
def chat(body: ChatIn):
    return dm.handle(body.session_id, message=body.message, answers=body.answers, chip=body.chip)


@app.get("/go/{sid}/{rank}")
def go(sid: str, rank: int):
    """클릭 로그 후 상품 페이지로 이동. 세션의 직전 추천 결과에 있는 URL 로만 이동한다."""
    s = dm.sessions.get(sid)
    if not s or not (1 <= rank <= len(s.last_items)):
        return RedirectResponse("/")
    so = s.last_items[rank - 1]
    try:
        store.log_click(sid, so.offer.mall, so.offer.mall_product_id or "", rank, so.score)
    except Exception:
        pass
    url = so.offer.url or "/"
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password:
        url = "/"
    return RedirectResponse(url)


@app.get("/api/health")
def health():
    return {"status": "ok", "nlu": dm.nlu.mode, "engine": dm.rec.mode, "markets": dm.rec.markets.active}


@app.post("/api/recipe/plan")
def recipe_plan(body: "RecipePlan"):
    return body.evaluate()
