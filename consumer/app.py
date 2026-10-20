"""소비자용 추천 앱 (공개).

실행:  uvicorn consumer.app:app --port 8000
화면:  http://127.0.0.1:8000/
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from consumer import geoip
from consumer.dialogue import DialogueManager
from consumer.recipes import RecipePlan
from shared import store
from shared.decision_ledger import refresh_needed

WEB = Path(__file__).parent / "web"
# 프론트엔드(Vite) 빌드 결과물. `npm run build` 후 ui_ux/dist 에 생성된다.
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "ui_ux" / "dist"
app = FastAPI(title="commerce_ai — 대화형 추천", version="1.0")
dm = DialogueManager()

# 개발 중 프론트엔드(Vite dev server)에서 API 를 호출할 수 있도록 허용한다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GeoIPMiddleware(BaseHTTPMiddleware):
    """요청마다 국가 코드를 조회해 request.state.country_code 에 저장한다.

    세션 ID 헤더(x-session-id)가 이미 존재하면 해당 세션에도 국가 코드를 반영한다.
    """

    async def dispatch(self, request: Request, call_next):
        code = geoip.lookup(dict(request.headers), request.client.host if request.client else None)
        request.state.country_code = code
        sid = request.headers.get("x-session-id")
        if sid and sid in dm.sessions:
            dm.sessions[sid].country_code = code
        return await call_next(request)


app.add_middleware(GeoIPMiddleware)


class ChatIn(BaseModel):
    session_id: str | None = None
    message: str | None = Field(None, max_length=500)
    answers: dict[str, str] | None = None
    chip: str | None = None


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    code = getattr(request.state, "country_code", None)
    return dm.handle(body.session_id, message=body.message, answers=body.answers, chip=body.chip,
                     country_code=code)


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


@app.get("/api/decision/ledger/{sid}")
def decision_ledger(sid: str):
    """세션의 Decision Freshness Ledger 조회 (shadow).

    현재 세션의 last_items 와 스냅샷을 비교해 결제 직전 재검토 필요 여부를 함께 돌려준다.
    """
    s = dm.sessions.get(sid)
    if not s or not s.ledger:
        return {"session_id": sid, "ledger": None, "refresh_needed": False}
    rn = refresh_needed(s.ledger, [x.offer for x in s.last_items])
    return {"session_id": sid, "ledger": s.ledger.to_dict(), "refresh_needed": rn["needed"],
            "expired": rn["expired"], "changed": rn["changed"]}


@app.post("/api/recipe/plan")
def recipe_plan(body: "RecipePlan"):
    return body.evaluate()


# 프론트엔드 빌드 결과물이 있으면 루트(/)에서 서빙한다.
# (빌드 전에는 디렉터리가 없으므로 마운트하지 않고, 기존 web/index.html 로 폴백한다.)
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:
    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")
