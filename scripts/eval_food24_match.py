#!/usr/bin/env python3
"""식품정보24 건강기능식품 매칭(shared/food24_catalog.match) 정확성 점검 — 서비스 켜기 전 확인용.

표본: food24_products.sqlite 에서 시드마다 고정으로 뽑은 신고 제품 N건 → 상품명 두 형태로 입력
      full: '<제조사 전체(공장 포함)> <제품명> 60정 1개' / base: '<공장 뗀 회사명> <제품명> 60정 1개'
판정 (매칭 코드의 정규화·제조사 함수를 쓰지 않고 따로 비교한다):
      정답                     연결 신고번호 = 표본 신고번호
      오연결(구분자 다름)      제품명 속 숫자+단위(100B·0.1B·1000IU …)가 다름
      오연결(이름 다름)        띄어쓰기만 무시한 제품명이 다름 ('밀크씨슬+' ↔ '밀크씨슬', '티알에스-α' ↔ '티알에스')
      오연결(제조사 다름)      법인 표기·공장 표기를 뗀 제조사가 다름
      오연결(원재료 다름)      원재료 4필드(주·기능성·기타·캡슐) 중 하나라도 다름
      판단불가(괄호 번역 표기만 다름) 숫자 없는 괄호(영문 번역)만 다르고 제조사·원재료 같음
      판단불가(동일 내용 재신고) 이름·제조사·원재료가 모두 같고 신고번호만 다름 (재신고·수출용·다른 공장)
      미연결                   연결 없음, 또는 제조사 미확인이라 서비스에서 표시하지 않음
FOOD24_IN_SERVICE 는 바꾸지 않는다 — 이 스크립트의 작업 프로세스 안에서만 스위치 확인을 건너뛴다.

실행: venv/bin/python scripts/eval_food24_match.py [--seeds 1-11] [--styles full,base] [--n 40] [--real titles.json]
출력: var/tmp/food24_match_eval.csv + food24_match_eval_manifest.json (코드 버전·DB 식별값·건수)
"""
from __future__ import annotations

import argparse, csv, hashlib, json, random, re, sqlite3, subprocess, sys, unicodedata
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shared import food24_catalog as fc  # noqa: E402

OUT = ROOT / "var" / "tmp"
# 사람 검토 결과는 평가 출력과 따로 둔다 — 재실행해도 지워지지 않는다 (이 스크립트는 읽기만 함)
REVIEW = ROOT / "var" / "review" / "food24_match_real_review.csv"
REVIEW_COLS = ["입력 상품명", "검토 당시 연결 신고번호", "판정(사람 검토)", "검토 메모", "근거", "검토일", "검토자"]


def load_review(path: Path = REVIEW) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["입력 상품명"]: r for r in csv.DictReader(f) if r.get("입력 상품명")}


def merge_review(row: dict, review: dict[str, dict]) -> dict:
    """검토 결과를 붙인다. 검토 당시와 연결 신고번호가 달라졌으면 '재검토 필요'로 표시한다."""
    rv = review.get(row["입력 상품명"])
    if not rv:
        return {**row, "판정(사람 검토)": "", "검토 메모": "", "근거": "", "검토일": "", "재검토 필요": ""}
    changed = (rv.get("검토 당시 연결 신고번호") or "") != (row.get("연결 신고번호") or "")
    return {**row, "판정(사람 검토)": rv.get("판정(사람 검토)", ""), "검토 메모": rv.get("검토 메모", ""),
            "근거": rv.get("근거", ""), "검토일": rv.get("검토일", ""),
            "재검토 필요": "예 — 연결 결과가 검토 당시와 다름" if changed else ""}
RAW_FIELDS = ("raw", "raw_functional", "raw_etc", "raw_capsule")


# ── 판정용 비교 (매칭 코드와 독립) ─────────────────────────────────────────────
def _nf(s: str | None) -> str:
    return unicodedata.normalize("NFKC", s or "").lower()


def strict_name(s: str | None) -> str:
    return re.sub(r"\s+", "", _nf(s))                   # 띄어쓰기만 무시 — 괄호·기호·숫자는 그대로


def unit_markers(s: str | None) -> list[str]:
    t = re.sub(r"(?<=\d),(?=\d{3})", "", _nf(s))
    return sorted(f"{float(n):g}{u}" for n, u in re.findall(r"(?<![0-9.])(\d+(?:\.\d+)?)\s*([a-z%]+)", t))


def maker(s: str | None) -> str:
    c = re.sub(r"\(주\)|㈜|주식회사|\(유\)|\(재\)|유한회사|농업회사법인|영농조합법인|^\s*주\)", " ", _nf(s))   # 법인 표기는 띄어쓰기로 바꿔 뒤의 지역 공장을 떼어 낼 수 있게
    c = re.sub(r"[\s,]*(제?\d+)?공장([\s,]*(제?\d+)?공장)*$", "", c)          # '...2공장', '1공장, 2공장'
    c = re.sub(r"(?<=\S)[\s,]+[가-힣]{2}$", "", c.strip())                               # 띄어 쓴 지역 '동서바이오팜(주) 안성'
    return re.sub(r"[^0-9a-z가-힣]", "", c)


def strip_translation(s: str | None) -> str:
    """숫자가 없는 괄호(영문 번역 등)만 지운 이름 — 숫자가 든 괄호(100B 등)는 남긴다"""
    return strict_name(re.sub(r"\([^)0-9]*\)", "", s or ""))


def raw_tuple(r: dict) -> tuple[str, ...]:
    return tuple(re.sub(r"\s+", "", _nf(r.get(k))) for k in RAW_FIELDS)


def judge(src: dict, rec: dict | None) -> tuple[str, str]:
    if not rec:
        return "미연결", ""
    if not rec.get("company_matched"):
        return "미연결", "제조사 미확인 — 서비스에서 표시 안 함"
    if rec["report_no"] == src["report_no"]:
        return "정답", "신고번호 일치"
    if unit_markers(rec["name"]) != unit_markers(src["name"]):
        return "오연결(구분자 다름)", f"{unit_markers(src['name'])} ↔ {unit_markers(rec['name'])}"
    translit_only = False
    if strict_name(rec["name"]) != strict_name(src["name"]):
        # 숫자 없는 괄호(영문 번역 표기)만 다르면 별도 판정 — '골든에센셜(Golden Essential)' ↔ '골든 에센셜'
        if strip_translation(rec["name"]) != strip_translation(src["name"]):
            return "오연결(이름 다름)", f"'{src['name']}' ↔ '{rec['name']}'"
        translit_only = True
    if maker(rec["company"]) != maker(src["company"]):
        return "오연결(제조사 다름)", f"'{src['company']}' ↔ '{rec['company']}'"
    if raw_tuple(rec) != raw_tuple(src):
        diff = [k for k, a, b in zip(RAW_FIELDS, raw_tuple(src), raw_tuple(rec)) if a != b]
        return "오연결(원재료 다름)", "다른 필드: " + ",".join(diff)
    if translit_only:
        return "판단불가(괄호 번역 표기만 다름)", f"'{src['name']}' ↔ '{rec['name']}' — 제조사·원재료 같음"
    return "판단불가(동일 내용 재신고)", "이름·제조사·원재료 같고 신고번호만 다름"


# ── 병렬 실행 (match 한 건이 DB 3.9만 행을 훑어 0.3초 안팎) ─────────────────────────
def _init():
    fc.in_service = lambda: True          # 작업 프로세스 안에서만


def _run_one(item: tuple[str, str, dict]) -> dict:
    style, seed, s = item
    mk = fc._company_key(s["company"]) if style == "full" else fc.base_company(s["company"])
    title = f"{mk} {s['name']} 60정 1개"
    rec, reason = fc.match_explain(title)
    verdict, basis = judge(s, rec)
    if verdict == "미연결" and not rec:
        basis = fc.REASONS[reason]
    return {"형태": style, "시드": seed, "입력 상품명": title, "표본 신고번호": s["report_no"], "표본 제품명": s["name"],
            "표본 제조사": s["company"], "연결 제품명": (rec or {}).get("name", ""), "연결 제조사": (rec or {}).get("company", ""),
            "연결 신고번호": (rec or {}).get("report_no", ""), "판정": verdict, "근거": basis,
            "매칭 사유": reason, "자동 표시": bool(rec and rec.get("display_ok")),
            "겹치는 신고": " | ".join((rec or {}).get("siblings") or [])}


def _real_one(title: str) -> dict:
    rec, reason = fc.match_explain(title)
    return {"입력 상품명": title, "연결 제품명": (rec or {}).get("name", ""), "연결 제조사": (rec or {}).get("company", ""),
            "연결 신고번호": (rec or {}).get("report_no", ""), "제조사 확인": bool(rec and rec.get("company_matched")),
            "자동 표시": bool(rec and rec.get("display_ok")), "매칭 사유": reason, "사유 설명": fc.REASONS[reason],
            "겹치는 신고": " | ".join((rec or {}).get("siblings") or [])}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def provenance() -> dict:
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()  # noqa: E731
    code = ["shared/food24_catalog.py", "scripts/eval_food24_match.py", "shared/data/company_aliases.json"]
    db = Path(fc._db())
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    prog = con.execute("select kind, total, rows, updated_at from progress").fetchall()
    n = con.execute("select count(*) from product").fetchone()[0]
    con.close()
    return {"run_at": datetime.now().isoformat(timespec="seconds"), "git_head": git("rev-parse", "--short", "HEAD"),
            "uncommitted_code": [c for c in code if git("status", "--porcelain", "--", c)],
            "code_sha256": {c: _sha(ROOT / c)[:16] for c in code},
            "db": {"path": str(db.relative_to(ROOT)), "sha256": _sha(db)[:16], "bytes": db.stat().st_size,
                   "rows": n, "progress": prog}}


def parse_seeds(s: str) -> list[int]:
    out = []
    for part in s.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seeds", default="1-11")
    ap.add_argument("--styles", default="full,base")
    ap.add_argument("--real", help="실제 판매 상품명 JSON (scripts/collect_health_titles.py 결과)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="", help="출력 파일 이름 뒤에 붙일 표시 (나눠 실행할 때)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    meta = provenance()

    if a.real:
        src = json.loads(Path(a.real).read_text(encoding="utf-8"))
        titles = list(dict.fromkeys(x["title"] for x in src["items"]))
        with ProcessPoolExecutor(a.workers, initializer=_init) as ex:
            out = list(ex.map(_real_one, titles, chunksize=4))
        kw = {x["title"]: x for x in src["items"]}
        review = load_review()
        for o in out:
            o.update({"검색어": kw[o["입력 상품명"]].get("keyword", ""), "판매처": kw[o["입력 상품명"]].get("mall", "")})
        out = [merge_review(o, review) for o in out]
        dst = OUT / "food24_match_real.csv"
        with open(dst, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0]))
            w.writeheader(); w.writerows(out)
        per_kw = {}
        for x in src["items"]:
            d = per_kw.setdefault(x["keyword"], {"items": 0, "titles": set(), "ids": set()})
            d["items"] += 1; d["titles"].add(x["title"]); d["ids"].add(x.get("product_id"))
        meta["per_keyword"] = {k: {"items": v["items"], "unique_titles": len(v["titles"]), "unique_ids": len(v["ids"])}
                               for k, v in per_kw.items()}
        meta.update({"real_source": a.real, "real_titles": len(titles), "real_items": len(src["items"]),
                     "real_unique_product_ids": len({x.get("product_id") for x in src["items"]}),
                     "reasons": {k: sum(o["매칭 사유"] == k for o in out) for k in sorted({o["매칭 사유"] for o in out})},
                     "auto_display": sum(o["자동 표시"] for o in out),
                     "linked": sum(bool(o["연결 신고번호"]) for o in out),
                     "company_confirmed": sum(o["제조사 확인"] for o in out),
                     "review_file": str(REVIEW.relative_to(ROOT)), "reviewed": sum(bool(o["판정(사람 검토)"]) for o in out),
                     "review_stale": sum(bool(o["재검토 필요"]) for o in out)})
        (OUT / "food24_match_real_manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"실제 상품명 {len(titles)}건(고유) — 연결 {meta['linked']}, 제조사 확인 {meta['company_confirmed']}, "
              f"자동 표시 {meta['auto_display']} / 사람 검토 {meta['reviewed']}건(재검토 필요 {meta['review_stale']}) / 사유 {meta['reasons']}")
        print(f"저장: {dst.relative_to(ROOT)}")
        return 0

    con = sqlite3.connect(f"file:{fc._db()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    ids = [r[0] for r in con.execute("select rowid from product where length(name) >= 4 order by rowid")]
    items = []
    for seed in parse_seeds(a.seeds):
        srcs = [dict(con.execute("select * from product where rowid = ?", (i,)).fetchone())
                for i in random.Random(seed).sample(ids, a.n)]
        for style in a.styles.split(","):
            items += [(style, str(seed), s) for s in srcs]
    con.close()
    with ProcessPoolExecutor(a.workers, initializer=_init) as ex:
        out = list(ex.map(_run_one, items, chunksize=8))
    dst = OUT / f"food24_match_eval{a.tag}.csv"
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader(); w.writerows(out)

    def stat(rows):
        n = len(rows)
        c = {}
        for o in rows:
            c[o["판정"]] = c.get(o["판정"], 0) + 1
        linked = n - c.get("미연결", 0)
        wrong = sum(v for k, v in c.items() if k.startswith("오연결"))
        return {"inputs": n, "unique_products": len({o["표본 신고번호"] for o in rows}),
                "unique_titles": len({o["입력 상품명"] for o in rows}), "linked": linked,
                "link_rate": round(linked / n, 4), "correct": c.get("정답", 0), "wrong": wrong,
                "undecidable": sum(v for k, v in c.items() if k.startswith("판단불가")),
                "accuracy_of_linked": round(c.get("정답", 0) / max(1, linked), 4),
                "wrong_rate_of_linked": round(wrong / max(1, linked), 4), "by_verdict": c,
                "auto_display": sum(o["자동 표시"] for o in rows),
                "auto_display_correct": sum(o["자동 표시"] and o["판정"] == "정답" for o in rows),
                "reasons": {k: sum(o["매칭 사유"] == k for o in rows) for k in sorted({o["매칭 사유"] for o in rows})}}
    meta["params"] = {"n": a.n, "seeds": a.seeds, "styles": a.styles}
    meta["result"] = {"all": stat(out), **{st: stat([o for o in out if o["형태"] == st]) for st in a.styles.split(",")}}
    (OUT / f"food24_match_eval{a.tag}_manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in meta["result"].items():
        print(f"[{k}] 입력 {v['inputs']} (고유 제품 {v['unique_products']}, 고유 상품명 {v['unique_titles']}) — "
              f"연결 {v['linked']} ({v['link_rate']:.1%}), 정답 {v['correct']}, 오연결 {v['wrong']}, "
              f"판단불가 {v['undecidable']} → 정확도 {v['accuracy_of_linked']:.1%} / 자동 표시 {v['auto_display']} "
              f"(정답 {v['auto_display_correct']})  {v['reasons']}")
    print(f"저장: {dst.relative_to(ROOT)}  /  코드 {meta['git_head']} + 미커밋 {meta['uncommitted_code']}  /  "
          f"DB sha256 {meta['db']['sha256']} ({meta['db']['rows']}행)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
