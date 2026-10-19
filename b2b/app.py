"""B2B 내부 콘솔 (내부 전용 — 소비자 앱과 별도 프로세스·포트·인증).

실행:  B2B_ACCESS_TOKEN=... uvicorn b2b.app:app --host 127.0.0.1 --port 8100
접속:  http://127.0.0.1:8100/login  (토큰 입력 → 쿠키)

보안 기본값
  - 127.0.0.1 바인딩 권장 (외부 공개 시 VPN/사내망 + 리버스 프록시 인증 추가)
  - 모든 /api, /files 는 토큰 쿠키 또는 X-Access-Token 헤더 필요
  - 외부로 메일·메시지를 보내는 기능 없음 (견적 요청·제안서는 초안 파일만 생성)
"""
from __future__ import annotations

import hmac
import secrets
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from b2b import bids as bidstore
from b2b.gift_monitor import checkpoints, collectors, trends
from b2b.console import DOCS, Console
from shared.config import get_settings

WEB = Path(__file__).parent / "web"
app = FastAPI(title="commerce_ai B2B 내부 콘솔", version="1.0", docs_url=None, redoc_url=None)
console = Console()
COOKIE = "b2b_token"


def _expected() -> str:
    """토큰이 기본값(change-me)이면 실행할 때마다 임시 토큰을 만들어 터미널에 출력한다."""
    global _TEMP
    tok = get_settings().b2b_access_token
    if tok and tok != "change-me":
        return tok
    if not _TEMP:
        _TEMP = secrets.token_urlsafe(18)
        print(f"[b2b] B2B_ACCESS_TOKEN 미설정 — 이번 실행용 임시 토큰: {_TEMP}", flush=True)
    return _TEMP


_TEMP = ""


def _ok(token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(token, _expected())


def auth(request: Request):
    tok = request.cookies.get(COOKIE) or request.headers.get("X-Access-Token")
    if not _ok(tok):
        raise HTTPException(401, "인증 필요")


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>B2B 콘솔 로그인</title><style>body{font-family:system-ui;background:#0f1720;color:#e8edf2;display:grid;place-items:center;height:100vh;margin:0}
form{background:#17212c;padding:28px;border-radius:14px;width:min(360px,90vw)}input,button{width:100%;padding:12px;border-radius:10px;border:1px solid #2b3a4a;
background:#0f1720;color:inherit;font-size:15px;box-sizing:border-box}button{margin-top:10px;background:#e8edf2;color:#0f1720;font-weight:700;cursor:pointer}</style>
<form method=post action=/login><h3 style="margin-top:0">B2B 내부 콘솔</h3><input name=token type=password placeholder="접근 토큰" autofocus><button>들어가기</button></form>"""


@app.post("/login")
def login(token: str = Form(...)):
    if not _ok(token):
        return RedirectResponse("/login", status_code=303)
    r = RedirectResponse("/", status_code=303)
    r.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=60 * 60 * 12)
    return r


@app.get("/")
def index(request: Request):
    if not _ok(request.cookies.get(COOKIE)):
        return RedirectResponse("/login")
    return FileResponse(WEB / "console.html")


class RunIn(BaseModel):
    workspace_id: str | None = None
    prompt: str = Field(..., min_length=1, max_length=8000)
    today: date | None = None


@app.post("/api/run", dependencies=[Depends(auth)])
def run(body: RunIn):
    return console.run(body.workspace_id, body.prompt, body.today)


@app.get("/api/bids", dependencies=[Depends(auth)])
def bids():
    return [b.model_dump(mode="json") for b in bidstore.list_bids()]


@app.post("/api/bids/upload", dependencies=[Depends(auth)])
async def upload(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > 5_000_000:
        raise HTTPException(413, "파일이 너무 큽니다")
    try:
        n = bidstore.import_file(file.filename or "upload.json", content)
    except Exception as e:
        raise HTTPException(400, f"가져오기 실패: {e}")
    return {"imported": n}


@app.get("/files/{name}", dependencies=[Depends(auth)])
def files(name: str):
    p = (DOCS / name).resolve()
    if DOCS.resolve() not in p.parents or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, filename=name if p.suffix == ".docx" else None)


# ── B2B gift-monitor · 트렌드 (smallbiz-monitor /b2b_gift + gift_trend_analyzer 통합) ──────────
@app.get("/monitor")
def monitor_page(request: Request):
    if not _ok(request.cookies.get(COOKIE)):
        return RedirectResponse("/login")
    return FileResponse(WEB / "monitor.html")


def _filtered(status: str, institution_type: str, bid_type: str, keyword: str, scope: str, today: date | None = None):
    out = []
    for b in bidstore.list_bids():
        v = b.view(today)
        if scope == "trusted" and not v["trusted"]:
            continue
        if scope == "default" and b.verification == "legacy_unverified":
            continue
        if status != "전체" and v["status"] != status:
            continue
        if institution_type != "전체" and b.institution_type != institution_type:
            continue
        if bid_type != "전체" and v["bid_type"] != bid_type:
            continue
        if keyword and keyword not in f"{b.title} {b.agency or ''} {b.summary}":
            continue
        out.append(v)
    order = {"마감임박": 0, "입찰중": 1, "마감일 미확인": 2, "입찰마감": 3}
    out.sort(key=lambda r: (order.get(r["status"], 9), r.get("deadline") or ""))
    return out


@app.get("/api/monitor/bids", dependencies=[Depends(auth)])
def monitor_bids(status: str = "전체", institution_type: str = "전체", bid_type: str = "전체",
                 keyword: str = "", scope: str = "default"):
    rows = _filtered(status, institution_type, bid_type, keyword.strip(), scope)
    allv = [b.view() for b in bidstore.list_bids()]
    counts = {k: sum(1 for r in allv if r["verification"] == k) for k in bidstore.VERIFICATION_LABEL}
    return {"rows": rows, "verification_counts": counts}


@app.get("/api/monitor/bids/{bid_id}", dependencies=[Depends(auth)])
def monitor_bid(bid_id: str):
    b = bidstore.get(bid_id)
    if not b:
        raise HTTPException(404, "공고 없음")
    v = b.view()
    v["checkpoints"] = checkpoints.checkpoints(b.title, b.summary)
    v["requirement"] = b.requirement.model_dump(mode="json") if b.requirement else None
    return v


class ManualBid(BaseModel):
    title: str = Field(..., min_length=2, max_length=300)
    agency: str | None = None
    deadline: str | None = None
    url: str | None = None
    budget: str | None = None
    text: str = Field("", max_length=60000)


@app.post("/api/monitor/bids", dependencies=[Depends(auth)])
def monitor_add(body: ManualBid):
    n = collectors.add_manual(body.title, body.agency, body.deadline, body.url, body.text, body.budget)
    return n.view()


@app.post("/api/monitor/bids/{bid_id}/attachments", dependencies=[Depends(auth)])
async def monitor_attach(bid_id: str, file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > 20_000_000:
        raise HTTPException(413, "파일이 너무 큽니다 (20MB 이하)")
    try:
        n = collectors.attach(bid_id, file.filename or "첨부", content)
    except KeyError:
        raise HTTPException(404, "공고 없음")
    except (ValueError, Exception) as e:
        raise HTTPException(400, str(e))
    return n.view()


@app.post("/api/monitor/bids/{bid_id}/verify", dependencies=[Depends(auth)])
def monitor_verify(bid_id: str, note: str = Form("")):
    try:
        return bidstore.mark_verified(bid_id, note).view()
    except KeyError:
        raise HTTPException(404, "공고 없음")
    except ValueError as e:
        raise HTTPException(400, str(e))


class CollectIn(BaseModel):
    days: int = Field(14, ge=1, le=90)
    keywords: list[str] | None = None


@app.post("/api/monitor/collect", dependencies=[Depends(auth)])
def monitor_collect(body: CollectIn):
    return collectors.collect_all(body.days, body.keywords)


@app.get("/api/monitor/trends", dependencies=[Depends(auth)])
def monitor_trends(include_legacy: bool = False, include_unverified: bool = True):
    return trends.analyze(include_unverified=include_unverified, include_legacy=include_legacy)


@app.get("/api/monitor/evaluator", dependencies=[Depends(auth)])
def evaluator_form():
    return checkpoints.eval_form()


class EvalIn(BaseModel):
    answers: dict[str, str]
    weights: dict[str, float] | None = None


@app.post("/api/monitor/evaluator", dependencies=[Depends(auth)])
def evaluator_run(body: EvalIn):
    return checkpoints.evaluate(body.answers, body.weights)


@app.get("/api/monitor/export.xlsx", dependencies=[Depends(auth)])
def monitor_export(status: str = "전체", institution_type: str = "전체", bid_type: str = "전체",
                   keyword: str = "", scope: str = "default"):
    """기존 /download?tab=b2b_gift 엑셀 보고서 대체. 신뢰 등급·출처 열 추가."""
    import io as _io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    rows = _filtered(status, institution_type, bid_type, keyword.strip(), scope)
    wb = Workbook()
    ws = wb.active
    ws.title = "선물입찰"
    head = ["상태", "신뢰 등급", "기관명", "기관 유형", "공고명", "유형(규칙 분류)", "예산(원)", "예산 원문",
            "공고일", "마감일", "담당부서", "담당자", "연락처", "출처", "원문 링크"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="EEF1F4")
    for r in rows:
        ws.append([r["status"], r["verification_label"], r.get("agency"), r.get("institution_type"), r["title"],
                   r["bid_type"], r.get("budget"), r.get("budget_text"), r.get("posted"), r.get("deadline"),
                   r.get("department"), r.get("manager"), r.get("contact"), r.get("source"), r.get("url")])
    for col, w in zip("ABCDEFGHIJKLMNO", (10, 14, 18, 12, 50, 20, 14, 18, 12, 18, 14, 10, 14, 22, 40)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    from urllib.parse import quote
    return Response(buf.read(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote("B2B_선물입찰_모니터.xlsx")})


@app.get("/api/health")
def health():
    return {"status": "ok"}


_expected()  # 시작 시 토큰 확인 (미설정이면 임시 토큰 출력)
