#!/usr/bin/env python3
"""입찰 공고 정기 수집 (cron / GitHub Actions 용). 기존 run_crawler.py(시뮬레이션) 대체.

    G2B_SERVICE_KEY=... B2B_DB_URL=... python scripts/collect_bids.py --days 7
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from b2b.gift_monitor.collectors import collect_all  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--keyword", action="append", help="공고명 검색어 (여러 번 지정 가능)")
    a = ap.parse_args()
    res = collect_all(a.days, a.keyword)
    for r in res["results"]:
        print("\n".join(r["log"]))
    print(f"신규 {res['new']}건 / 조회 {res['found']}건")
    if not any("완료" in line for r in res["results"] for line in r["log"]):
        sys.exit(1)   # 수집 자체가 안 됐으면 실패로 표시 (키 미설정 포함)
