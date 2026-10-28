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
실행: venv/bin/python scripts/update_food24_products.py --probe      서비스별 응답·건수 확인
      venv/bin/python scripts/update_food24_products.py              건강기능식품(ff)만 수집 (끊기면 이어받기)
      venv/bin/python scripts/update_food24_products.py --only gf    일반식품은 직접 지정할 때만 (114만 건·10건씩)
      venv/bin/python scripts/update_food24_products.py --restart    1페이지부터 다시
※ 수집해도 서비스에는 바로 쓰이지 않는다 — .env FOOD24_IN_SERVICE=1 일 때만 (shared/food24_catalog.py).
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
  report_no text not null, kind text not null, lcns_no text, company text, name text, name_norm text,
  class1 text, class2 text, class3 text, class4 text, item_type text,
  raw text, raw_functional text, raw_etc text, raw_capsule text, usage text, expiry text, reported text,
  updated_at text, primary key (kind, report_no));
create index if not exists ix_name_norm on product(name_norm);
create index if not exists ix_company on product(company);
create table if not exists progress (kind text primary key, page int, total int, rows int, page_size int, updated_at text);
create table if not exists skipped (kind text, page int, idx int, name text, reason text, at text);
"""
DEFAULT_KINDS = ["ff"]     # 일반식품(gf)은 --only gf 로 직접 지정할 때만


class _Transient(Exception):
    """다시 시도할 만한 일시 오류 (HTTP 5xx)"""


def _safe(text, key: str, n: int = 150) -> str:
    """서버가 보낸 안내 문구만, 키가 섞여 있으면 가리고 길이를 자른다"""
    t = str(text or "").replace(key, "<KEY>") if key else str(text or "")
    return re.sub(r"\s+", " ", t).strip()[:n]


def migrate(con: sqlite3.Connection) -> None:
    """예전 DB(report_no 단독 키) → (kind, report_no) 키로 옮긴다."""
    cols = con.execute("pragma table_info(product)").fetchall()
    if not cols:
        return
    pk = [c[1] for c in sorted(cols, key=lambda c: c[5]) if c[5]]
    if pk == ["kind", "report_no"]:
        return
    print("  DB 키를 (kind, report_no)로 바꾸는 중…")
    with con:
        con.execute("alter table product rename to product_old")
        con.execute("drop index if exists ix_name_norm")
        con.execute("drop index if exists ix_company")
        con.executescript(SCHEMA)
        con.execute("insert or replace into product select report_no, kind, lcns_no, company, name, name_norm, class1, "
                    "class2, class3, class4, item_type, raw, raw_functional, raw_etc, raw_capsule, usage, expiry, "
                    "reported, updated_at from product_old")
        con.execute("drop table product_old")


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
    for attempt in range(4):
        try:
            with requests.get(
                BASE + op,
                params={
                    "opapiAtkeyCn": key,
                    "type": "json",
                    "numOfRows": rows,
                    "pageNo": page,
                },
                headers=HEADERS,
                timeout=60,
                allow_redirects=False,
            ) as response:
                if 500 <= response.status_code < 600:
                    raise _Transient(f"HTTP {response.status_code}")
                if response.status_code != 200:
                    raise RuntimeError(
                        f"{op} p{page}: HTTP {response.status_code}"
                    )
                try:
                    data = response.json()
                except ValueError:
                    raise RuntimeError(
                        f"{op} p{page}: JSON 응답이 아닙니다."
                    ) from None

            if not isinstance(data, dict):
                raise RuntimeError(f"{op} p{page}: 응답이 객체가 아닙니다.")

            code = str(data.get("resultCode", ""))
            if code != "00":
                # 요청 URL·예외 문자열은 키 보호를 위해 출력하지 않지만,
                # 서버 안내 문구(resultMsg/resultDc)는 원인 파악에 필요하므로 키를 가리고 잘라서 보여준다.
                safe_code = code if code.isdigit() else "없음/비정상"
                hint = " ".join(x for x in (_safe(data.get("resultMsg"), key), _safe(data.get("resultDc"), key)) if x)
                raise RuntimeError(
                    f"{op} p{page}: API 결과코드 {safe_code}" + (f" — {hint}" if hint else "")
                )

            records = data.get("recordset")
            if not isinstance(records, list):
                raise RuntimeError(f"{op} p{page}: recordset 목록이 없습니다.")
            if any(not isinstance(row, dict) for row in records):
                raise RuntimeError(f"{op} p{page}: 레코드 구조가 잘못되었습니다.")

            try:
                total = int(data["totalCount"])
            except (KeyError, TypeError, ValueError):
                raise RuntimeError(
                    f"{op} p{page}: totalCount가 없거나 잘못되었습니다."
                ) from None

            if total < 0 or len(records) > rows:
                raise RuntimeError(f"{op} p{page}: 건수 응답이 잘못되었습니다.")

            return data

        except (requests.Timeout, requests.ConnectionError, _Transient) as exc:
            if attempt == 3:
                what = str(exc) if isinstance(exc, _Transient) else type(exc).__name__
                raise RuntimeError(
                    f"{op} p{page}: {what} (4회 실패)"
                ) from None
            time.sleep(2 * (attempt + 1))
        except requests.RequestException as exc:
            raise RuntimeError(
                f"{op} p{page}: {type(exc).__name__}"
            ) from None


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
        for rows in (10, 11):        # 한 페이지 최대 10건 — 11건 요청이 거절되는지로 제한이 그대로인지 확인
            try:
                t = time.time()
                got = len(fetch(op, key, 1, rows).get("recordset") or [])
                print(f"   numOfRows={rows}: {got}건 ({time.time() - t:.1f}초)")
            except Exception as e:  # noqa: BLE001
                print(f"   numOfRows={rows}: 실패 — {e}")


def collect(con: sqlite3.Connection, key: str, kind: str, rows: int,
            restart: bool, max_pages: int | None) -> None:
    if not 1 <= rows <= 10:
        raise RuntimeError("--rows는 1~10 범위로 지정하세요.")
    if max_pages is not None and max_pages < 1:
        raise RuntimeError("--max-pages는 1 이상이어야 합니다.")

    op, label = SOURCES[kind]
    prog = con.execute(
        "select page, page_size from progress where kind=?", (kind,)
    ).fetchone()

    if prog and prog[0] > 0 and not restart and prog[1] != rows:
        raise RuntimeError(
            f"기존 페이지 크기는 {prog[1]}입니다. "
            "같은 --rows를 사용하거나 --restart를 지정하세요."
        )

    page = 1 if restart or not prog else prog[0] + 1
    pages_done = 0

    while True:
        data = fetch(op, key, page, rows)
        records = data["recordset"]
        total = int(data["totalCount"])
        offset = (page - 1) * rows

        if not records and offset < total:
            raise RuntimeError(
                f"{op} p{page}: 전체 건수가 남았는데 빈 페이지가 반환됐습니다. "
                "진행 상태를 갱신하지 않습니다."
            )
        if len(records) < rows and offset + len(records) < total:
            raise RuntimeError(
                f"{op} p{page}: 요청 {rows}건 중 {len(records)}건만 반환됐습니다. "
                "누락 방지를 위해 진행 상태를 갱신하지 않습니다."
            )
        # 품목보고번호가 없는 행은 저장하지 않고 skipped 표에 남긴다 (한 행 때문에 수집 전체가 멈추지 않게)
        bad = [(i, r) for i, r in enumerate(records) if not str(r.get("prdlstReportNo") or "").strip()]
        values = [row_of(kind, r) for r in records if str(r.get("prdlstReportNo") or "").strip()]
        finished = offset + len(records) >= total
        now = datetime.now().isoformat(timespec="seconds")

        with con:
            if bad:
                con.executemany("insert into skipped values (?,?,?,?,?,?)",
                                [(kind, page, i, str(r.get("prdlstNm") or "")[:100], "품목보고번호 없음", now)
                                 for i, r in bad])
            con.executemany(
                "insert or replace into product values "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                values,
            )
            con.execute(
                "insert or replace into progress "
                "(kind, page, total, rows, page_size, updated_at) "
                "values (?,?,?,?,?,?)",
                (
                    kind,
                    0 if finished else page,
                    total,
                    offset + len(records),
                    rows,
                    now,
                ),
            )

        pages_done += 1
        if bad or page % 20 == 0 or finished:
            print(
                f"  {label}: p{page}, 반환 {len(records)}건"
                + (f" (번호 없음 {len(bad)}건 건너뜀)" if bad else "")
                + f", 진행 {offset + len(records)}/{total}"
            )

        if finished or (
            max_pages is not None and pages_done >= max_pages
        ):
            break

        page += 1
        time.sleep(0.2)

    count = con.execute(
        "select count(*) from product where kind=?", (kind,)
    ).fetchone()[0]
    print(f"  {label}: 현재 DB 저장 {count}건 (API 전체 {total})")


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
    migrate(con)
    con.executescript(SCHEMA)
    print(f"[{datetime.now():%F %T}] 식품정보24 품목 수집 시작 (페이지당 {a.rows}건)")
    rc = 0
    for kind in ([a.only] if a.only else DEFAULT_KINDS):
        try:
            collect(con, key, kind, a.rows, a.restart, a.max_pages)
        except Exception as e:  # noqa: BLE001
            rc = 1
            print(f"  ! {SOURCES[kind][1]} 수집 중단 (다음 실행 때 이어받음): {e}")
    skipped = con.execute("select count(*) from skipped").fetchone()[0]
    con.close()
    tail = f" (번호 없어 건너뛴 행 누적 {skipped}건 — skipped 표)" if skipped else ""
    if rc:
        print(f"[{datetime.now():%F %T}] 일부 실패 — 위 오류를 확인하세요. 다음 실행 때 이어받습니다: {DB}{tail}")
    else:
        print(f"[{datetime.now():%F %T}] 완료: {DB}{tail}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
