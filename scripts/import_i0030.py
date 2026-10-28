#!/usr/bin/env python3
"""식품안전나라 I0030 '건강기능식품 품목제조신고(원재료)' 전체 CSV → 로컬 SQLite (표준 라이브러리만 사용).

식품정보24 건강기능식품 API(39,771건, 한 번에 10건)를 4천 번 부르는 대신, 식품안전나라에서 받은 전체 파일을 한 번에 넣는다.
I0030 은 46,070건(2026-10-28 샘플 기준)이고 기능성·섭취방법·주의사항·보관방법까지 담고 있다.

입력: data/source/I0030_csv.gz (또는 .csv) — 열 이름은 API와 같다
      PRDLST_REPORT_NO, LCNS_NO, BSSH_NM, PRDLST_NM, PRDLST_CDNM, RAWMTRL_NM, INDIV_RAWMTRL_NM, ETC_RAWMTRL_NM,
      CAP_RAWMTRL_NM, PRIMARY_FNCLTY, NTK_MTHD, IFTKN_ATNT_MATR_CN, POG_DAYCNT, CSTDY_MTHD, PRMS_DT, LAST_UPDT_DTM …
출력: var/knowledge/i0030_health.sqlite  (shared/food24_catalog.py 의 product 스키마 + 기능성·주의·보관 열)
실행: python3 scripts/import_i0030.py [--src 경로]
※ 서비스에는 바로 쓰이지 않는다 — 쓰려면 .env FOOD24_IN_SERVICE=1, FOOD24_DB_PATH=var/knowledge/i0030_health.sqlite
"""
from __future__ import annotations

import argparse, csv, gzip, shutil, sqlite3, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shared.food24_catalog import norm  # noqa: E402

SRC_CANDIDATES = [ROOT / "data" / "source" / "I0030_csv.gz", ROOT / "data" / "source" / "I0030.csv"]
OUT = ROOT / "var" / "knowledge" / "i0030_health.sqlite"
SCHEMA = """
create table product (
  report_no text not null, kind text not null, lcns_no text, company text, name text, name_norm text,
  class1 text, class2 text, class3 text, class4 text, item_type text,
  raw text, raw_functional text, raw_etc text, raw_capsule text, usage text, expiry text, reported text,
  updated_at text, primary_function text, caution text, storage text, shape text,
  primary key (kind, report_no));
create table meta (k text primary key, v text);
"""
COLS = 23


def g(r: dict, k: str) -> str:
    return (r.get(k) or "").strip()


def row_of(r: dict) -> tuple | None:
    no, name = g(r, "PRDLST_REPORT_NO"), g(r, "PRDLST_NM")
    if not no or not name:
        return None
    return (no, "i0030", g(r, "LCNS_NO"), g(r, "BSSH_NM"), name, norm(name),
            "가공식품", "건강식품", "건강기능식품", g(r, "PRDLST_CDNM"), g(r, "PRDLST_CDNM"),
            g(r, "RAWMTRL_NM"), g(r, "INDIV_RAWMTRL_NM"), g(r, "ETC_RAWMTRL_NM"), g(r, "CAP_RAWMTRL_NM"),
            g(r, "NTK_MTHD"), g(r, "POG_DAYCNT"), g(r, "PRMS_DT"), g(r, "LAST_UPDT_DTM"),
            g(r, "PRIMARY_FNCLTY"), g(r, "IFTKN_ATNT_MATR_CN"), g(r, "CSTDY_MTHD"), g(r, "PRDT_SHAP_CD_NM"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    src = Path(a.src) if a.src else next((p for p in SRC_CANDIDATES if p.exists()), None)
    if not src or not src.exists():
        print("원본이 없습니다. 식품안전나라에서 I0030 전체 파일을 받아 data/source/I0030_csv.gz 로 두세요.")
        return 2
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.gettempdir()) / "i0030_health.building"     # 빠른 임시 디스크에서 만든 뒤 옮긴다
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript("pragma journal_mode=off; pragma synchronous=off;" + SCHEMA)
    t0, n, skipped, batch = time.time(), 0, 0, []
    opener = gzip.open if src.suffix == ".gz" else open
    with opener(src, "rt", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = {"PRDLST_REPORT_NO", "PRDLST_NM", "RAWMTRL_NM"} - set(reader.fieldnames or [])
        if missing:
            print(f"열 이름이 다릅니다 (없음: {sorted(missing)}). 받은 파일의 머리글: {reader.fieldnames}")
            con.close(); tmp.unlink(missing_ok=True)
            return 3
        for r in reader:
            row = row_of(r)
            if row is None:
                skipped += 1
                continue
            batch.append(row)
            if len(batch) >= 10000:
                con.executemany(f"insert or replace into product values ({','.join('?' * COLS)})", batch)
                n += len(batch); batch = []
    if batch:
        con.executemany(f"insert or replace into product values ({','.join('?' * COLS)})", batch)
        n += len(batch)
    con.execute("create index ix_name_norm on product(name_norm)")
    con.execute("create index ix_company on product(company)")
    total = con.execute("select count(*) from product").fetchone()[0]
    con.executemany("insert into meta values (?,?)", [("source", "식품안전나라 I0030 건강기능식품 품목제조신고(원재료)"),
                                                      ("src_file", src.name), ("rows", str(total)),
                                                      ("skipped", str(skipped)),
                                                      ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S"))])
    con.commit(); con.close()
    shutil.move(str(tmp), str(out))
    print(f"저장: {out} ({total:,}건, 번호·이름 없어 건너뜀 {skipped}건, {time.time() - t0:.0f}초)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
