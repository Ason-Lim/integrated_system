#!/usr/bin/env python3
"""식품안전나라 C002 '식품(첨가물)품목제조보고(원재료)' 전체 CSV → 로컬 SQLite (표준 라이브러리만 사용).

입력: data/source/C002_csv.gz  (식품안전나라에서 내려받은 전체 파일, UTF-8 BOM, 약 108만 건)
      열: LCNS_NO, BSSH_NM, PRDLST_REPORT_NO, PRMS_DT, PRDLST_NM, PRDLST_DCNM, RAWMTRL_NM, RAWMTRL_ORDNO, CHNG_DT, ETQTY_XPORT_PRDLST_YN
출력: var/knowledge/c002_rawmtrl.sqlite  (shared/food24_catalog.py 와 같은 product 스키마)
실행: python3 scripts/import_c002.py [--src 경로]
"""
from __future__ import annotations

import argparse, csv, gzip, io, os, sqlite3, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shared.food24_catalog import norm  # noqa: E402

SRC = ROOT / "data" / "source" / "C002_csv.gz"
OUT = ROOT / "var" / "knowledge" / "c002_rawmtrl.sqlite"
SCHEMA = """
create table product (
  report_no text primary key, kind text, lcns_no text, company text, name text, name_norm text,
  class1 text, class2 text, class3 text, class4 text, item_type text,
  raw text, raw_functional text, raw_etc text, raw_capsule text, usage text, expiry text, reported text,
  updated_at text);
create table meta (k text primary key, v text);
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SRC))
    a = ap.parse_args()
    src = Path(a.src)
    if not src.exists():
        print(f"원본이 없습니다: {src}")
        return 2
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # 빠른 디스크(임시 폴더)에서 만든 뒤 옮긴다 — 연결 폴더·외장 디스크에 직접 쓰면 매우 느릴 수 있다
    import shutil, tempfile
    tmp = Path(tempfile.gettempdir()) / "c002_rawmtrl.building"
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript("pragma journal_mode=off; pragma synchronous=off;" + SCHEMA)
    t0, n, batch = time.time(), 0, []
    opener = gzip.open if src.suffix == ".gz" else open
    with opener(src, "rt", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            no = (r.get("PRDLST_REPORT_NO") or "").strip()
            name = (r.get("PRDLST_NM") or "").strip()
            if not no or not name:
                continue
            batch.append((no, "c002", r.get("LCNS_NO", "").strip(), (r.get("BSSH_NM") or "").strip(), name, norm(name),
                          "", "", "", "", (r.get("PRDLST_DCNM") or "").strip(), (r.get("RAWMTRL_NM") or "").strip(),
                          "", "", "", "", "", (r.get("PRMS_DT") or "").strip(), (r.get("CHNG_DT") or "").strip()))
            if len(batch) >= 20000:
                con.executemany("insert or replace into product values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                n += len(batch); batch = []
                if n % 200000 == 0:
                    print(f"  {n:,}건 ({time.time() - t0:.0f}초)", flush=True)
    if batch:
        con.executemany("insert or replace into product values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        n += len(batch)
    con.execute("create index ix_name_norm on product(name_norm)")
    con.execute("create index ix_company on product(company)")
    total = con.execute("select count(*) from product").fetchone()[0]
    con.executemany("insert into meta values (?,?)", [("source", "식품안전나라 C002 식품(첨가물)품목제조보고(원재료)"),
                                                      ("src_file", src.name), ("rows", str(total)),
                                                      ("built_at", time.strftime("%Y-%m-%dT%H:%M:%S"))])
    con.commit(); con.close()
    shutil.move(str(tmp), str(OUT))
    print(f"저장: {OUT} ({total:,}건, {OUT.stat().st_size / 1e6:.0f}MB, {time.time() - t0:.0f}초)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
