#!/usr/bin/env python3
"""식품정보24 건강기능식품 매칭(shared/food24_catalog.match) 정확성 점검 — 서비스 켜기 전 확인용.

표본: food24_products.sqlite 에서 고정 시드로 뽑은 신고 제품 N건 → 판매처 상품명 형태로 만든 입력
      '<제조사 핵심어> <제품명> 60정 1개' (예전 40건 점검과 같은 형식)
판정: 정답 = 연결된 신고번호가 표본 신고번호와 같음
      판단불가 = 신고번호는 다르지만 제품명·제조사가 같음 (같은 제품의 재신고·수출용 등)
      오연결 = 다른 제품명 또는 다른 제조사
FOOD24_IN_SERVICE 는 바꾸지 않는다 — 이 스크립트 안에서만 match()의 스위치 확인을 건너뛴다.

실행: venv/bin/python scripts/eval_food24_match.py [--n 40] [--seed 7] [--titles var/core.sqlite3]
출력: var/tmp/food24_match_eval_<seed>.csv
"""
from __future__ import annotations

import argparse, csv, random, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shared import food24_catalog as fc  # noqa: E402


def judge(src: dict, rec: dict | None) -> tuple[str, str]:
    if not rec:
        return "미연결", ""
    if not rec.get("company_matched"):
        return "미연결", "제조사가 상품명에 없어 서비스에서 표시 안 함"
    if rec["report_no"] == src["report_no"]:
        return "정답", "신고번호 일치"
    if fc.norm(rec["name"]) == fc.norm(src["name"]) and fc.base_company(rec["company"]) == fc.base_company(src["company"]):
        same_raw = fc.norm(rec.get("raw") or "") == fc.norm(src.get("raw") or "")
        return "판단불가", ("제품명·제조사(공장 제외) 같고 신고번호 다름 — 재신고·수출용·다른 공장 / 원재료 "
                         + ("같음" if same_raw else "다름"))
    return "오연결", "다른 제품"


def why_missed(title: str, src: dict) -> str:
    """미연결 원인: match() 의 단계를 그대로 다시 밟아 어디서 떨어졌는지 본다."""
    t = fc.norm(title)
    con = sqlite3.connect(f"file:{fc._db()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("select * from product where length(name_norm) >= 3 and instr(?, name_norm) > 0 "
                       "order by length(name_norm) desc limit 40", (t,)).fetchall()
    con.close()
    if len(fc.norm(src["name"])) < 3:
        return f"신고 제품명이 {len(fc.norm(src['name']))}글자('{fc.norm(src['name'])}') — 오연결 방지로 3글자 미만은 잇지 않음"
    if not rows:
        return f"제품명 정규화 불일치 (상품명 '{t[:30]}' 안에 신고 제품명 '{fc.norm(src['name'])}' 없음)"
    top = [r for r in rows if len(r["name_norm"]) == len(rows[0]["name_norm"])]
    comps = sorted({r["company"] for r in top})
    ck = fc._company_key(src["company"])
    if len(comps) > 1:
        return f"같은 이름을 {len(comps)}개 제조사가 신고 + 제조사 핵심어 '{ck}' 가 상품명에서 확인 안 됨"
    return f"가장 긴 일치 '{top[0]['name']}' 의 제조사 확인 실패 (핵심어 '{ck}')"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--style", choices=["full", "base"], default="full",
                    help="full: 제조사 전체('노바렉스2공장') / base: 공장 뗀 회사명('노바렉스') — 판매처 표기에 가까움")
    ap.add_argument("--titles", help="실제 판매처 상품명이 든 core.sqlite3 (offer_observation.title)")
    a = ap.parse_args()
    fc.in_service = lambda: True          # 이 점검 안에서만. .env 의 FOOD24_IN_SERVICE 는 그대로
    con = sqlite3.connect(f"file:{fc._db()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    ids = [r[0] for r in con.execute("select rowid from product where length(name) >= 4 order by rowid")]
    pick = random.Random(a.seed).sample(ids, a.n)
    srcs = [dict(con.execute("select * from product where rowid = ?", (i,)).fetchone()) for i in pick]
    con.close()
    out = []
    for s in srcs:
        maker = fc._company_key(s["company"]) if a.style == "full" else fc.base_company(s["company"])
        title = f"{maker} {s['name']} 60정 1개"
        rec = fc.match(title)
        verdict, basis = judge(s, rec)
        if verdict == "미연결" and not rec:
            basis = why_missed(title, s)
        out.append({"입력 상품명": title, "표본 신고번호": s["report_no"], "표본 제품명": s["name"], "표본 제조사": s["company"],
                    "연결 제품명": (rec or {}).get("name", ""), "연결 제조사": (rec or {}).get("company", ""),
                    "연결 신고번호": (rec or {}).get("report_no", ""), "매칭 근거": basis, "판정": verdict})
    dst = ROOT / "var" / "tmp" / f"food24_match_eval_{a.style}_{a.seed}.csv"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    n = len(out)
    linked = [o for o in out if o["판정"] != "미연결"]
    ok = sum(o["판정"] == "정답" for o in linked)
    bad = sum(o["판정"] == "오연결" for o in linked)
    unk = sum(o["판정"] == "판단불가" for o in linked)
    print(f"표본 {n}건: 연결 {len(linked)} ({len(linked) / n:.0%}), 미연결 {n - len(linked)}")
    print(f"연결된 것 중 정답 {ok}, 오연결 {bad}, 판단불가 {unk} — 정확도 {ok / max(1, len(linked)):.0%} "
          f"(판단불가 제외 {ok / max(1, ok + bad):.0%})")
    print(f"저장: {dst.relative_to(ROOT)}")
    if a.titles:
        tc = sqlite3.connect(f"file:{a.titles}?mode=ro", uri=True)
        titles = sorted({r[0] for r in tc.execute("select title from offer_observation where title is not null")})
        hits = [(t, fc.match(t)) for t in titles]
        hits = [(t, r) for t, r in hits if r]
        print(f"\n실제 판매처 상품명 {len(titles)}건 중 match() 결과 있음 {len(hits)}건 "
              f"(서비스 표시 조건인 제조사 확인 {sum(bool(r['company_matched']) for _, r in hits)}건)")
        for t, r in hits:
            print(f"  - {t[:60]} → {r['name']} / {r['company']} (제조사 확인 {r['company_matched']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
