"""공고 수집기 — 기존 core_crawler.py 를 대체한다.

기존 크롤러는 사이트 접속만 시도하고, 하드코딩된 SIMULATED_NEW_GIFTS 목록을 무작위로 '새 공고'로 넣었다.
여기서는 실제 응답에서 나온 공고만 저장한다. 결과가 없으면 0건이라고 그대로 보고한다.

1) 나라장터 OpenAPI (조달청 입찰공고정보서비스, 공공데이터포털 서비스키 필요)
   https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfo{Thng|Servc}PPSSrch
2) 공고 직접 등록 (URL·제목·본문 붙여넣기)  — 은행·보험사 등 API 가 없는 민간 공고용
3) CSV/JSON 업로드                             — b2b.bids.import_file
4) 기존 smallbiz-monitor DB 가져오기           — legacy_unverified 로 표시
"""
from __future__ import annotations

import io
import re
import sqlite3
import zipfile
from datetime import date, datetime, timedelta

import requests

from b2b import bids as store
from b2b.gift_monitor import classify
from shared.config import get_settings

G2B_BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
G2B_OPS = {"물품": "getBidPblancListInfoThngPPSSrch", "용역": "getBidPblancListInfoServcPPSSrch"}
# 기존 targets.py GIFT_KEYWORDS 를 공고명 검색에 맞게 정리
GIFT_KEYWORDS = ["임직원 선물", "명절 선물", "선물세트", "기념품", "온누리상품권", "모바일상품권", "복지몰", "창립기념"]


class G2BCollector:
    def __init__(self, service_key: str | None = None, base: str | None = None, session=None):
        import os
        self.key = service_key or os.getenv("G2B_SERVICE_KEY") or os.getenv("DATA_GO_KR_SERVICE_KEY")
        self.base = (base or os.getenv("G2B_API_BASE") or G2B_BASE).rstrip("/")
        self.http = session or requests

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def fetch(self, keyword: str, kind: str, start: datetime, end: datetime, rows: int = 100) -> list[dict]:
        params = {
            "ServiceKey": self.key, "type": "json", "numOfRows": rows, "pageNo": 1, "inqryDiv": 1,
            "inqryBgnDt": start.strftime("%Y%m%d%H%M"), "inqryEndDt": end.strftime("%Y%m%d%H%M"),
            "bidNtceNm": keyword,
        }
        r = self.http.get(f"{self.base}/{G2B_OPS[kind]}", params=params, timeout=20)
        r.raise_for_status()
        body = (r.json().get("response") or {}).get("body") or {}
        items = body.get("items") or []
        if isinstance(items, dict):           # XML→JSON 변환형 응답 {"item": [...]}
            items = items.get("item") or []
        if isinstance(items, dict):
            items = [items]
        return items

    @staticmethod
    def to_row(it: dict, kind: str) -> dict:
        no, ordv = it.get("bidNtceNo"), it.get("bidNtceOrd") or "000"
        budget = it.get("asignBdgtAmt") or it.get("presmptPrce")
        return {
            "bid_id": f"G2B-{no}-{ordv}", "title": it.get("bidNtceNm"),
            "agency": it.get("dminsttNm") or it.get("ntceInsttNm"),
            "deadline": it.get("bidClseDt"), "posted": it.get("bidNtceDt"),
            "budget": int(float(budget)) if budget not in (None, "") else None,
            "url": it.get("bidNtceDtlUrl") or it.get("bidNtceUrl"),
            "manager": it.get("ntceInsttOfclNm"), "contact": it.get("ntceInsttOfclTelNo"),
            "summary": " · ".join(x for x in (f"[{kind}]", it.get("ntceInsttNm"), it.get("cntrctCnclsMthdNm"),
                                              it.get("bidMethdNm")) if x),
        }

    def run(self, keywords: list[str] | None = None, days: int = 14, kinds=("물품", "용역"),
            today: datetime | None = None) -> dict:
        log: list[str] = []
        if not self.enabled:
            return {"source": "나라장터 OpenAPI", "new": 0, "updated": 0, "found": 0,
                    "log": ["G2B_SERVICE_KEY 가 설정되지 않아 나라장터 수집을 건너뜁니다. (공공데이터포털에서 '조달청_나라장터 입찰공고정보서비스' 활용신청 후 키를 .env 에 넣으세요)"]}
        end = today or datetime.now()
        start = end - timedelta(days=days)
        new = upd = found = 0
        seen: set[str] = set()
        for kind in kinds:
            for kw in keywords or GIFT_KEYWORDS:
                try:
                    items = self.fetch(kw, kind, start, end)
                except Exception as e:
                    log.append(f"[실패] {kind} '{kw}': {e}")
                    continue
                log.append(f"[조회] {kind} '{kw}': {len(items)}건")
                for it in items:
                    row = self.to_row(it, kind)
                    if row["bid_id"] in seen:
                        continue
                    seen.add(row["bid_id"])
                    found += 1
                    was = store.exists(row["bid_id"])
                    store.save(store.normalize(row, "나라장터 OpenAPI", "verified"))
                    upd += was
                    new += not was
        log.append(f"[완료] 고유 공고 {found}건 · 신규 {new}건 · 갱신 {upd}건 (기간 {start:%Y-%m-%d}~{end:%Y-%m-%d})")
        return {"source": "나라장터 OpenAPI", "new": new, "updated": upd, "found": found, "log": log}


def collect_all(days: int = 14, keywords: list[str] | None = None) -> dict:
    results = [G2BCollector().run(keywords, days)]
    remote = get_settings().b2b_bid_source_url
    if remote:
        try:
            n = store.fetch_remote(remote)
            results.append({"source": remote, "new": n, "updated": 0, "found": n, "log": [f"[완료] {n}건 (원문 대조 전으로 저장)"]})
        except Exception as e:
            results.append({"source": remote, "new": 0, "updated": 0, "found": 0, "log": [f"[실패] {e}"]})
    return {"results": results, "new": sum(r["new"] for r in results), "found": sum(r["found"] for r in results)}


# ── 직접 등록 ─────────────────────────────────────────────────
def add_manual(title: str, agency: str | None, deadline: str | None, url: str | None, text: str = "",
               budget: str | None = None) -> store.BidNotice:
    if not title.strip():
        raise ValueError("공고명이 필요합니다.")
    row = {"title": title.strip(), "agency": agency, "deadline": deadline, "url": url, "summary": text, "budget": budget}
    n = store.normalize(row, "직접 등록", "unverified")
    store.save(n)
    return n


# ── 첨부 원문 → 텍스트 ───────────────────────────────────────
def extract_text(name: str, content: bytes) -> str:
    low = name.lower()
    if low.endswith(".hwpx"):
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            parts = sorted(p for p in z.namelist() if re.match(r"Contents/section\d+\.xml", p))
            xml = " ".join(z.read(p).decode("utf-8", "ignore") for p in parts)
        xml = re.sub(r"</hp:p>", "\n", xml)
        return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", "", xml)).strip()
    if low.endswith(".docx"):
        from docx import Document
        return "\n".join(p.text for p in Document(io.BytesIO(content)).paragraphs)
    if low.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise ValueError("PDF 텍스트 추출에는 pypdf 설치가 필요합니다 (pip install pypdf).") from e
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(content)).pages)
    if low.endswith(".hwp"):
        raise ValueError("HWP(구형) 는 직접 읽을 수 없습니다. 한글에서 HWPX 또는 PDF 로 저장해 올려 주세요.")
    return content.decode("utf-8-sig", "ignore")


def attach(bid_id: str, name: str, content: bytes) -> store.BidNotice:
    n = store.get(bid_id)
    if not n:
        raise KeyError(bid_id)
    text = extract_text(name, content).strip()
    if not text:
        raise ValueError("문서에서 텍스트를 찾지 못했습니다.")
    n.summary = (n.summary + "\n\n" if n.summary else "") + f"【첨부: {name}】\n" + text[:60000]
    n.attachments.append({"name": name, "chars": len(text), "added": date.today().isoformat()})
    store.reparse(n)
    store.save(n)
    return n


# ── 기존 DB 가져오기 ───────────────────────────────────────────
def import_legacy_db(path: str) -> int:
    """anti_online / gift_trend_analyzer 의 data/smallbiz_programs.db 의 gift_bids 를 가져온다.

    이 테이블은 database.py 의 하드코딩 시드와 core_crawler.py 의 SIMULATED_NEW_GIFTS 로 채워진 데이터라
    legacy_unverified 로 저장한다. 소상공인 지원사업(programs) 테이블은 가져오지 않는다.
    """
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM gift_bids")]
    con.close()
    n = 0
    for r in rows:
        r["bid_id"] = f"legacy-{r.get('id')}"
        b = store.normalize(r, "smallbiz-monitor 기존 DB (시드/시뮬레이션)", "legacy_unverified")
        b.tags = sorted(set(b.tags + ["미검증 기존 데이터"]))
        if b.url and b.url.rstrip("/").count("/") <= 2:
            b.tags.append("링크가 사이트 첫 화면")
        store.save(b)
        n += 1
    return n


def legacy_status_counts(today: date | None = None) -> dict:
    out: dict = {}
    for b in store.list_bids():
        if b.verification == "legacy_unverified":
            s = classify.status(b.deadline, today)
            out[s] = out.get(s, 0) + 1
    return out
