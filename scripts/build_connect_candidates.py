#!/usr/bin/env python3
"""네이버 쇼핑커넥트 '링크 발급 후보 목록' 만들기 (표준 라이브러리만 사용).

네이버 쇼핑 검색 API가 2026-07-31 종료되어 네이버 상품을 자동으로 가져올 수 없다.
대신 우리 서비스에서 많이 찾은 키워드 + 오늘의 트렌드 키워드를 뽑아,
사용자가 브랜드커넥트 > 쇼핑커넥트에서 그 키워드로 제휴 상품을 찾아 링크를 발급받도록 돕는다.

출력: var/affiliate/shopping_connect_candidates_YYYY-MM-DD.csv  (엑셀에서 바로 열림)
      var/affiliate/naver_connect_links.csv                    (발급한 링크를 적는 등록부, 없을 때만 생성)
실행: python3 scripts/build_connect_candidates.py [--days 30] [--top 30]
"""
from __future__ import annotations

import argparse, csv, glob, json, os, re, sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("CORE_DB_PATH", ROOT / "var" / "core.sqlite3"))
OUT_DIR = ROOT / "var" / "affiliate"
TREND_DIR = ROOT / "ui_ux" / "src" / "data"
REGISTRY_COLS = ["키워드", "상품명", "스토어명", "판매가", "쇼핑커넥트 링크", "수수료율(%)", "발급일", "링크 확인일",
                 "사용처(블로그/사이트)", "메모"]
DROP = {"추천", "추천해줘", "선물", "세트", "레시피", "장보기", "택배", "같이", "비린내", "없이", "받아도", "굳지"}


def keyword_of(product: str) -> str | None:
    """'과메기 비린내 없이 같이' → '과메기'. 수식어·조건어는 버리고 첫 상품어만."""
    for t in (product or "").split():
        t = re.sub(r"[^\w가-힣]", "", t)
        if len(t) >= 2 and t not in DROP and not t.isdigit():
            return t
    return None


def from_logs(days: int) -> tuple[Counter, dict]:
    searches, sample = Counter(), {}
    if not DB.exists():
        return searches, sample
    con = sqlite3.connect(DB)
    since = (datetime.utcnow() - timedelta(days=days)).isoformat(sep=" ")
    for slots, action in con.execute("select slots, action from search_log where created_at >= ?", (since,)):
        if action and not action.startswith(("recommend", "lowest", "allergy")):
            continue
        try:
            kw = keyword_of((json.loads(slots or "{}") or {}).get("product", ""))
        except ValueError:
            kw = None
        if kw:
            searches[kw] += 1
    # 참고용: 최근 관측된 쿠팡 상품 중 키워드가 들어간 것 (가격 감 잡기용)
    rows = con.execute("select title, price from offer_observation where mall='coupang' order by observed_at desc limit 3000").fetchall()
    for kw in searches:
        hit = next(((t, p) for t, p in rows if kw in (t or "")), None)
        if hit:
            sample[kw] = hit
    clicks = Counter()
    for (title,) in con.execute(
            "select o.title from click_log c join offer_observation o on o.mall_product_id = c.mall_product_id "
            "where c.created_at >= ?", (since,)):
        kw = next((k for k in searches if k in (title or "")), None)
        if kw:
            clicks[kw] += 1
    con.close()
    return searches, {"sample": sample, "clicks": clicks}


def trend_keywords() -> list[str]:
    files = sorted(glob.glob(str(TREND_DIR / "trend_examples_*.json")))
    for f in reversed(files):
        try:
            rows = json.load(open(f, encoding="utf-8"))
            kws = [r.get("keyword") for r in rows if r.get("keyword")]
            if len(set(kws)) == len(kws) and kws:
                return kws
        except ValueError:
            continue
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--top", type=int, default=30)
    a = ap.parse_args()
    searches, extra = from_logs(a.days)
    trends = trend_keywords()
    registered = set()
    reg = OUT_DIR / "naver_connect_links.csv"
    if reg.exists():
        with open(reg, encoding="utf-8-sig") as f:
            registered = {r.get("키워드", "").strip() for r in csv.DictReader(f) if r.get("쇼핑커넥트 링크")}
    keys = list(dict.fromkeys([k for k, _ in searches.most_common()] + trends))
    keys.sort(key=lambda k: (-(searches[k] + 3 * extra["clicks"][k] + (5 if k in trends else 0)), k))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"shopping_connect_candidates_{date.today().isoformat()}.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["순위", "키워드", f"검색 수({a.days}일)", "클릭 수", "오늘 트렌드", "이미 링크 등록", "참고 상품(쿠팡 최근)",
                    "참고 가격", "쇼핑커넥트 상품 있음(Y/N)", "발급 링크", "수수료율(%)", "메모"])
        for i, k in enumerate(keys[:a.top], 1):
            t, p = extra["sample"].get(k, ("", ""))
            w.writerow([i, k, searches[k], extra["clicks"][k], "Y" if k in trends else "", "Y" if k in registered else "",
                        t, p, "", "", "", ""])
    if not reg.exists():
        with open(reg, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(REGISTRY_COLS)
        print(f"등록부 생성: {reg}")
    print(f"저장: {out} (후보 {min(len(keys), a.top)}개, 검색 키워드 {len(searches)}개, 트렌드 {len(trends)}개)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
