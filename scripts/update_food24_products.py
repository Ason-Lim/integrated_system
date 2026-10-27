#!/usr/bin/env python3
"""식품정보24 오픈 API → 가공식품·건강기능식품 품목제조보고(원재료) 로컬 DB.

API (식품정보24 > 오픈 API, 키: .env FOOD24_API_KEY)
  일반식품_기본     getGfBaseRaw  — 제품명·제조사·분류·품목유형·원재료(totRawmtrlNm)·용법·유통/소비기한(expNm)
  건강기능식품_기본  getFfBaseRaw  — 위 + 기능성(indivRawmtrlNm)·기타(etcRawmtrlNm)·캡슐(capRawmtrlNm) 원재료
  ※ 실제 응답: 목록은 recordset, 인허가번호는 lcnsNo (문서의 lcnso·cap_rawmtrl_nm 과 다름)
  ※ 상세 페이지의 '요청 내용' 주소는 앞부분이 두 번 붙어 있다 (사이트 버그) — 아래 BASE 형식이 맞다.
  ※ 2026-10-27 확인: 일반식품 1,145,153건, 한 페이지 최대 10건, 제품명 검색 없음 → 전체 수집은 비현실적.
     주간 예약에서 뺐고, 원재료 조회는 식품안전나라 C002(제품명 검색)를 쓴다 (scripts/enrich_foodpolis.py).

출력: var/knowledge/food24_products.sqlite  (서버는 이 파일만 읽는다)
실행: venv/bin/python scripts/update_food24_products.py --probe      건수·최대 페이지 크기 확인
      venv/bin/python scripts/update_food24_products.py              전체 수집 (끊기면 이어받기)
      venv/bin/python scripts/update_food24_products.py --only ff --restart
"""
from __future__ import annotations

import argparse, re, sqlite3, sys, time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "var" / "knowledge" / "food24_products.sqlite"
BASE = "https://www.foodpolis.kr/food24/co/api/apVhdService/"
SOURCES = {"gf": ("getGfBaseRaw", "일반식품"), "ff": ("getFfBaseRaw", "건강기능식품")}
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) integrated_system/food24", "Accept": "application/json"}

SCHEMA = """
create table if not exists product (
  report_no text primary key, kind text, lcns_no text, company text, name text, name_norm text,
  class1 text, class2 text, class3 text, class4 text, item_type text,
  raw text, raw_functional text, raw_etc text, raw_capsule text, usage text, expiry text, reported text,
  updated_at text);
create index if not exists ix_name_norm on product(name_norm);
create index if not exists ix_company on product(company);
create table if not exists progress (kind text primary key, page int, total int, rows int, page_size int, updated_at text);
"""


def norm(s: str) -> str:
    """비교용 이름: 괄호 속 영문·공백·기호 제거, 소문자"""
    s = re.sub(r"\([^)]*[A-Za-z][^)]*\)", "", s or "")
    return re.sub(r"[^0-9a-z가-힣]", "", s.lower())


def api_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("FOOD24_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def fetch(op: str, key: str, page: int, rows: int) -> dict:
    last = None
    for n in range(4):
        try:
            r = requests.get(BASE + op, params={"opapiAtkeyCn": key, "type": "json", "numOfRows": rows, "pageNo": page},
                             headers=HEADERS, timeout=60)
            j = r.json()
            code = str(j.get("resultCode", "00"))
            if code != "00":
                raise RuntimeError(f"결과코드 {code} {j.get('resultMsg')} {j.get('resultDc', '')}")
            return j
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (n + 1))
    raise RuntimeError(f"{op} p{page}: {type(last).__name__}: {str(last)[:200]}")


def row_of(kind: str, r: dict) -> tuple:
    g = lambda k: (r.get(k) or "").strip()  # noqa: E731
    return (g("prdlstReportNo"), kind, g("lcnsNo") or g("lcnso"), g("bsshNm"), g("prdlstNm"), norm(g("prdlstNm")),
            g("class1Nm"), g("class2Nm"), g("class3Nm"), g("class4Nm"), g("prdlstDcnm"),
            g("totRawmtrlNm"), g("indivRawmtrlNm"), g("etcRawmtrlNm"), g("capRawmtrlNm") or g("cap_rawmtrl_nm"),
            g("usageNm"), g("expNm"), g("prmsDt"), datetime.now().isoformat(timespec="seconds"))


def probe(key: str) -> None:
    for kind, (op, label) in SOURCES.items():
        try:
            j = fetch(op, key, 1, 10)
            print(f"[{label}] {op}: 전체 {j.get('totalCount')}건")
            rec = (j.get("recordset") or [{}])[0]
            print("   필드:", list(rec.keys()))
        except Exception as e:  # noqa: BLE001
            print(f"[{label}] {op}: 실패 — {e}")
            continue
        for rows in (100, 500, 1000):
            try:
                t = time.time()
                got = len(fetch(op, key, 1, rows).get("recordset") or [])
                print(f"   numOfRows={rows}: {got}건 ({time.time() - t:.1f}초)")
            except Exception as e:  # noqa: BLE001
                print(f"   numOfRows={rows}: 실패 — {e}")


def collect(con: sqlite3.Connection, key: str, kind: str, rows: int, restart: bool, max_pages: int | None) -> None:
    op, label = SOURCES[kind]
    prog = con.execute("select page, total from progress where kind=?", (kind,)).fetchone()
    page = 1 if restart or not prog else prog[0] + 1
    total = None
    done = 0
    while True:
        j = fetch(op, key, page, rows)
        recs = j.get("recordset") or []
        total = int(j.get("totalCount") or 0)
        con.executemany("insert or replace into product values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [row_of(kind, r) for r in recs if r.get("prdlstReportNo")])
        con.execute("insert or replace into progress values (?,?,?,?,?,?)",
                    (kind, page, total, page * rows, rows, datetime.now().isoformat(timespec="seconds")))
        con.commit()
        done += 1
        if page % 20 == 0 or not recs:
            print(f"  {label}: {min(page * rows, total)}/{total}")
        if not recs or page * rows >= total or (max_pages and done >= max_pages):
            break
        page += 1
        time.sleep(0.2)
    if total and page * rows >= total:
        # 다 받았으면 다음 실행은 처음부터 (주간 갱신)
        con.execute("update progress set page=0 where kind=?", (kind,))
        con.commit()
    n = con.execute("select count(*) from product where kind=?", (kind,)).fetchone()[0]
    print(f"  {label}: 저장 {n}건 (API 전체 {total})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--only", choices=list(SOURCES))
    ap.add_argument("--rows", type=int, default=10, help="페이지 크기 (API 최대 10건)")
    ap.add_argument("--restart", action="store_true", help="이어받기 무시하고 1페이지부터")
    ap.add_argument("--max-pages", type=int, help="이번 실행에서 받을 최대 페이지 수 (시험용)")
    a = ap.parse_args()
    key = api_key()
    if not key:
        print(".env 에 FOOD24_API_KEY 가 없습니다.")
        return 2
    if a.probe:
        probe(key)
        return 0
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    print(f"[{datetime.now():%F %T}] 식품정보24 품목 수집 시작 (페이지당 {a.rows}건)")
    rc = 0
    for kind in SOURCES:
        if a.only and a.only != kind:
            continue
        try:
            collect(con, key, kind, a.rows, a.restart, a.max_pages)
        except Exception as e:  # noqa: BLE001
            rc = 1
            print(f"  ! {SOURCES[kind][1]} 수집 중단 (다음 실행 때 이어받음): {e}")
    con.close()
    print(f"[{datetime.now():%F %T}] 완료: {DB}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
