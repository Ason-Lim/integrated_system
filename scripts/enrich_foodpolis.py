#!/usr/bin/env python3
"""Foodpolis 판매순위 JSON(data/foodpolis_raw) 보강 — 내부 참고 자료 전용.

순위 제품명마다 식품안전나라 '식품(첨가물)품목제조보고(원재료)'(C002)를 제품명으로 찾아
제조사·품목유형·원재료·알레르기 성분을 붙인다. (식품정보24 일반식품 API는 114만 건을 10건씩만 줘서 쓰지 않음)

※ 참고 자료 전용: 화면·추천 순위·블로그·GitHub로 내보내지 않는다 (식품정보24 이용약관 제19조②, 원자료 NICE 지니데이터).

입력: data/foodpolis_raw/<최신 날짜>/rankings_all.json
출력: data/foodpolis_enriched/<날짜>/rankings_enriched.json, rankings_enriched.csv (엑셀용)
캐시: data/foodpolis_enriched/lookup_cache.json (제품명별 30일)
실행: venv/bin/python scripts/enrich_foodpolis.py [--date 2026-10-27] [--probe 코카콜라제로]
"""
from __future__ import annotations

import argparse, csv, json, re, sys, time, urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shared.food24_catalog import ALLERGEN_RULES, allergens_in  # noqa: E402

RAW_DIR = ROOT / "data" / "foodpolis_raw"
OUT_DIR = ROOT / "data" / "foodpolis_enriched"
CACHE = OUT_DIR / "lookup_cache.json"
LOCAL_DB = ROOT / "var" / "knowledge" / "c002_rawmtrl.sqlite"   # scripts/import_c002.py 로 만든 전체 C002 (일반식품)
HEALTH_DB = ROOT / "var" / "knowledge" / "i0030_health.sqlite"  # scripts/import_i0030.py 로 만든 전체 I0030 (건강기능식품)
SERVICE = "C002"
CACHE_DAYS = 30
CACHE_VER = 2      # 찾는 방법이 바뀌면 올린다 — 옛 방법으로 '없음'이 난 캐시를 다시 찾게 한다


def env(name: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


class ServiceError(RuntimeError):
    """키·서비스 권한 문제 — 제품마다 반복해도 같은 결과라 즉시 멈춘다."""


# 인증·권한·서비스 단위 오류 (제품과 무관)
SERVICE_CODES = {"INFO-100", "INFO-110", "INFO-120", "INFO-300", "INFO-400", "ERROR-300", "ERROR-310", "ERROR-500"}


def query_name(prod: str) -> tuple[str, str | None]:
    """'오리온)단백질바미니' → ('단백질바미니', '오리온'), '포스트*단백질바' → ('포스트 단백질바', None)"""
    brand = None
    m = re.match(r"^\s*([^)/\s]{1,6})[)/]\s*(.+)$", prod or "")      # '정관장)홍삼원', '정관장/홍삼원'
    if m:
        brand, prod = m.group(1), m.group(2)
    prod = re.sub(r"[*_]", " ", prod)
    prod = re.sub(r"\((?:\d+입|고소한맛|[^)]*맛)\)", "", prod)            # '(16입)', '(고소한맛)'
    for _ in range(2):                                                    # 끝의 용량·포장 표기 (두 번까지)
        prod = re.sub(r"\s*(\d+(?:\.\d+)?\s*(?:ml|m|l|g|kg|입|T|포|개|병|캔|팩|EA)?|케이스|박스|병|캔)$", "", prod,
                      flags=re.I).strip()
    return prod, brand


# 품목제조보고에 한글로 적힌 표기 (영문 약어 → 한글)
SPELL = [("F", "에프"), ("ZERO", "제로"), ("Zero", "제로"), ("new", "뉴"), ("NEW", "뉴"), ("Big", "빅")]


# 순위표에서 제품명 앞에 붙여 쓰는 브랜드 → 품목제조보고의 제조·판매사 (브랜드를 떼고 찾을 때 제조사로 확인)
BRAND_COMPANY = {"정관장": "한국인삼공사", "한삼인": "농협홍삼", "종근당": "종근당", "광동": "광동", "롯데": "롯데",
                 "동원": "동원", "오뚜기": "오뚜기", "농심": "농심", "오리온": "오리온", "빙그레": "빙그레",
                 "해태": "해태", "크라운": "크라운", "남양": "남양", "매일": "매일", "풀무원": "풀무원", "CJ": "씨제이"}


def strip_brand(q: str) -> tuple[str, str | None]:
    """'정관장홍삼진본' → ('홍삼진본', '정관장'). 남는 이름이 너무 짧으면 떼지 않는다."""
    k = q.strip()
    for b in sorted(BRAND_COMPANY, key=len, reverse=True):
        if k.startswith(b) and len(norm(k[len(b):])) >= 3:
            return k[len(b):].strip(), b
    return q, None


def variants(q: str) -> list[str]:
    """검색 후보: 원래 이름 → 영문 약어를 한글로 → '+' 묶음은 첫 제품 → 끝에서 한 글자씩 줄이기(75%까지)"""
    out = [q]
    k = q
    for a, b in SPELL:
        k = re.sub(rf"(?<![A-Za-z]){a}(?![A-Za-z])", b, k)
    out.append(k)
    if "+" in q:
        out.append(q.split("+")[0])
    # 끝을 줄이는 건 원래 길이의 75%까지만 — 더 줄이면 맛·종류가 다른 제품이 잡힌다 ('테이크핏초코'→'딸기맛')
    base = norm(out[-1])
    floor = max(4, -(-len(base) * 3 // 4))
    for n in range(len(base) - 1, floor - 1, -1):
        out.append(base[:n])
    return list(dict.fromkeys(x for x in out if x))


def norm(s: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", (s or "").lower())


def g(row: dict, *keys: str) -> str:
    for k in keys:
        if row.get(k):
            return str(row[k]).strip()
    return ""


def search(key: str, name: str, n: int = 30) -> list[dict]:
    url = (f"http://openapi.foodsafetykorea.go.kr/api/{key}/{SERVICE}/json/1/{n}/"
           f"PRDLST_NM={urllib.parse.quote(name)}")
    for i in range(3):
        try:
            j = requests.get(url, timeout=30).json()
            body = j.get(SERVICE) or {}
            code = (body.get("RESULT") or {}).get("CODE", "")
            if code and code not in ("INFO-000", "INFO-200"):
                msg = f"{code} {(body.get('RESULT') or {}).get('MSG')}"
                raise (ServiceError if code in SERVICE_CODES else RuntimeError)(msg)
            return body.get("row") or []
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (i + 1))
    return []


def search_local(name: str, n: int = 30, contains: bool = True) -> list[dict]:
    """로컬 C002(일반식품) + I0030(건강기능식품) DB에서 이름 검색. 출처(SOURCE)를 붙여 돌려준다."""
    out = []
    for db, src in ((LOCAL_DB, "C002 일반식품"), (HEALTH_DB, "I0030 건강기능식품")):
        if db.exists():
            out += [{**r, "SOURCE": src} for r in _search_db(db, name, n, contains)]
    return out


def search_split(name: str, n: int = 10) -> list[dict]:
    """붙여 쓴 이름을 앞·뒤로 나눠 찾기: '테이크핏초코' → 앞부분 '테이크핏%' 이면서 '초코' 포함.
    앞부분이 긴 쪽부터 시도하고 처음 찾은 것을 돌려준다 (결과는 '유사'로만 본다)."""
    import sqlite3
    key = norm(name)
    out = []
    for db, src in ((LOCAL_DB, "C002 일반식품"), (HEALTH_DB, "I0030 건강기능식품")):
        if not db.exists():
            continue
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.execute("pragma case_sensitive_like = on")
        try:
            for cut in range(len(key) - 2, 2, -1):
                head, rest = key[:cut], key[cut:]
                rows = con.execute("select name, company, report_no, item_type, " + RAW_SQL + " from product "
                                   "where name_norm like ? and name_norm like ? order by length(name_norm) limit ?",
                                   (f"{head}%", f"%{rest}%", n)).fetchall()
                if rows:
                    out += [{"PRDLST_NM": a, "BSSH_NM": b, "PRDLST_REPORT_NO": c, "PRDLST_DCNM": d,
                             "RAWMTRL_NM": e, "SOURCE": src} for a, b, c, d, e in rows]
                    break
        finally:
            con.close()
    return out


# 건강기능식품(I0030)은 기능성 원재료가 따로 있어 함께 보여준다 (C002는 빈 칸이라 그대로)
RAW_SQL = "raw || case when coalesce(raw_functional, '') != '' then ' / 기능성: ' || raw_functional else '' end"


def _search_db(db: Path, name: str, n: int, contains: bool) -> list[dict]:
    """한 DB에서 이름 검색 (정확히 같은 이름 → 앞부분 일치 → 중간 포함). API와 같은 필드명으로 돌려준다."""
    import sqlite3
    key = norm(name)
    if len(key) < 2:
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.execute("pragma case_sensitive_like = on")      # 'x%' 앞부분 일치에 색인(ix_name_norm)을 쓰게 한다
    try:
        rows = con.execute("select name, company, report_no, item_type, " + RAW_SQL + " from product where name_norm = ? limit ?",
                           (key, n)).fetchall()
        like = key.replace("%", "").replace("_", "")
        if len(rows) < n:     # 앞부분 일치 (색인 사용, 빠름)
            rows += con.execute("select name, company, report_no, item_type, " + RAW_SQL + " from product "
                                "where name_norm like ? and name_norm != ? order by length(name_norm) limit ?",
                                (f"{like}%", key, n - len(rows))).fetchall()
        if contains and not rows:   # 중간 포함 (전체 훑기, 느림 — 원래 이름에만)
            rows += con.execute("select name, company, report_no, item_type, " + RAW_SQL + " from product "
                                "where name_norm like ? order by length(name_norm) limit ?",
                                (f"%{like}%", n)).fetchall()
    finally:
        con.close()
    return [{"PRDLST_NM": a, "BSSH_NM": b, "PRDLST_REPORT_NO": c, "PRDLST_DCNM": d, "RAWMTRL_NM": e}
            for a, b, c, d, e in rows]


def best_split(product: str, rows: list[dict]) -> tuple[str, list[dict]]:
    """search_split 결과: 이름을 나눠 찾은 것이라 '유사'. 원래 이름 길이에 가까운 것을 앞으로."""
    p = norm(product)
    rows = sorted(rows, key=lambda r: abs(len(norm(g(r, "PRDLST_NM"))) - len(p)))
    return ("partial", rows[:3]) if rows else ("none", [])


def best(product: str, rows: list[dict]) -> tuple[str, list[dict]]:
    """정확히 같은 이름 > 이름이 포함 > 없음. 같은 수준이면 최대 3건을 '후보'로 남긴다."""
    p = norm(product)
    exact = [r for r in rows if norm(g(r, "PRDLST_NM")) == p]
    if exact:
        return "exact", exact[:3]
    part = [r for r in rows if p and (p in norm(g(r, "PRDLST_NM")) or norm(g(r, "PRDLST_NM")) in p)]
    part.sort(key=lambda r: abs(len(norm(g(r, "PRDLST_NM"))) - len(p)))
    return ("partial", part[:3]) if part else ("none", [])


def summarize(r: dict) -> dict:
    raw = g(r, "RAWMTRL_NM", "RAWMTRL_NM_LIST", "IRDNT_NM")
    return {"name": g(r, "PRDLST_NM"), "company": g(r, "BSSH_NM"), "report_no": g(r, "PRDLST_REPORT_NO"),
            "item_type": g(r, "PRDLST_DCNM"), "raw": raw[:500], "source": g(r, "SOURCE") or "C002 일반식품",
            "allergens": [ALLERGEN_RULES[a]["label"] for a in sorted(allergens_in(raw))]}


def latest_raw(date: str | None) -> Path:
    if date:
        return RAW_DIR / date / "rankings_all.json"
    dirs = sorted(p for p in RAW_DIR.iterdir() if p.is_dir() and (p / "rankings_all.json").exists())
    if not dirs:
        raise SystemExit(f"{RAW_DIR} 에 수집 결과가 없습니다.")
    return dirs[-1] / "rankings_all.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--probe", help="제품명 하나로 C002 응답 구조 확인")
    a = ap.parse_args()
    key = env("FOODSAFETY_API_KEY")
    if not key and not LOCAL_DB.exists():
        print("로컬 C002 DB(scripts/import_c002.py)도, .env 의 FOODSAFETY_API_KEY 도 없습니다.")
        return 2
    if a.probe:
        try:
            q = query_name(a.probe)[0]
            rows = search_local(q, 5) if (LOCAL_DB.exists() or HEALTH_DB.exists()) else search(key, q, 5)
        except ServiceError as err:
            print(f"중단: {err}\n  식품안전나라 > 데이터활용서비스 > Open API 에서 '{SERVICE}' 활용신청(승인 반영) 후 다시 실행하세요.")
            return 3
        print(f"{SERVICE} '{a.probe}': {len(rows)}건")
        if rows:
            print("필드:", list(rows[0].keys()))
            print("첫 행:", {k: str(v)[:60] for k, v in rows[0].items()})
            print("판정:", best(a.probe, rows)[0])
        return 0

    src = latest_raw(a.date)
    data = json.loads(src.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    fresh = (datetime.now() - timedelta(days=CACHE_DAYS)).isoformat()
    out, calls = [], 0
    for e in data:
        for r in e.get("rankings") or []:
            prod = (r.get("prodNm") or "").strip()
            if not prod:
                continue
            k = norm(prod)
            hit = cache.get(k)
            if not hit or hit.get("at", "") < fresh or hit.get("v") != CACHE_VER:
                q, brand = query_name(prod)
                try:
                    shortened = split = False
                    if LOCAL_DB.exists() or HEALTH_DB.exists():
                        rows = []
                        q0 = q
                        nb, b2 = strip_brand(q)
                        cands = variants(q) + (variants(nb) if b2 else [])
                        for i, v in enumerate(cands):
                            rows = search_local(v, contains=(i == 0))
                            if rows:
                                if b2 and v in variants(nb) and v not in variants(q0):
                                    # 브랜드를 떼고 찾음: 제조사가 브랜드와 맞는 행만 남긴다
                                    rows = [x for x in rows if BRAND_COMPANY[b2] in g(x, "BSSH_NM")] or rows
                                    brand = brand or BRAND_COMPANY[b2]
                                    shortened = v != variants(nb)[0] or not any(
                                        BRAND_COMPANY[b2] in g(x, "BSSH_NM") for x in rows)
                                else:
                                    shortened = i >= 2   # 이름을 줄이거나 묶음을 나눠 찾은 것은 '유사'로만 본다
                                q = v
                                break
                        if not rows:      # 마지막: 붙여 쓴 이름을 앞·뒤로 나눠 찾기
                            rows, split = search_split(nb if b2 else q0), True
                    else:
                        rows = search(key, q)
                except ServiceError as err:
                    # 권한·키 문제는 제품마다 같은 결과 → 캐시에 남기지 않고 바로 멈춘다
                    print(f"중단: {err}\n  식품안전나라 > 데이터활용서비스 > Open API 에서 '{SERVICE}' 활용신청 후 다시 실행하세요.")
                    return 3
                except RuntimeError as err:
                    print(f"  ! {prod}: {err}")      # 일시 오류는 캐시하지 않고 다음 실행 때 다시
                    out.append({"yyyymm": r.get("yyyymm") or e.get("yyyymm"), "channel": e.get("channel"),
                                "class2": e.get("class2Nm"), "class3": e.get("class3Nm"), "rank": r.get("rank"),
                                "product": prod, "match": "none", "candidates": []})
                    continue
                calls += 0 if LOCAL_DB.exists() else 1
                if brand:   # 브랜드 표기가 있으면 제조사명에 그 글자가 든 행을 앞으로
                    rows.sort(key=lambda x: brand not in g(x, "BSSH_NM"))
                kind, picked = best_split(q, rows) if split else best(q, rows)
                if shortened and kind == "exact":
                    kind = "partial"
                hit = cache[k] = {"at": datetime.now().isoformat(timespec="seconds"), "v": CACHE_VER, "match": kind,
                                  "candidates": [summarize(x) for x in picked]}
                if not LOCAL_DB.exists():
                    time.sleep(0.3)
            out.append({"yyyymm": r.get("yyyymm") or e.get("yyyymm"), "channel": e.get("channel"),
                        "class2": e.get("class2Nm"), "class3": e.get("class3Nm"), "rank": r.get("rank"),
                        "product": prod, "match": hit["match"], "candidates": hit["candidates"]})
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    day = src.parent.name
    d = OUT_DIR / day
    d.mkdir(parents=True, exist_ok=True)
    doc = {"reference_only": True,
           "note": "내부 참고 자료 — 화면·추천·블로그·외부 게시 금지 (식품정보24 이용약관, 원자료 NICE 지니데이터). "
                   "C002 원재료는 일부만 공개(복합원재료는 '음료베이스' 등으로 표기)되므로 알레르기 '없음'은 판단할 수 없음.",
           "source_rankings": str(src.relative_to(ROOT)),
           "enriched_with": "식품안전나라 C002 일반식품 품목제조보고(원재료) + I0030 건강기능식품 품목제조신고"
                            + (" — 로컬 전체 파일" if LOCAL_DB.exists() else " — Open API"),
           "generated_at": datetime.now().isoformat(timespec="seconds"), "rows": out}
    (d / "rankings_enriched.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(d / "rankings_enriched.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["기준월", "채널", "중분류", "소분류", "순위", "제품명", "매칭", "후보 수", "품목명(품목제조보고)", "제조사",
                    "품목유형", "알레르기(공개 원재료에서 확인된 것만)", "원재료(앞부분)", "출처"])
        for o in out:
            c = (o["candidates"] or [{}])[0]
            w.writerow([o["yyyymm"], o["channel"], o["class2"], o["class3"], o["rank"], o["product"],
                        {"exact": "일치", "partial": "유사(확인 필요)", "none": "없음"}[o["match"]],
                        len(o["candidates"]), c.get("name", ""),
                        c.get("company", ""), c.get("item_type", ""), ", ".join(c.get("allergens", [])),
                        (c.get("raw") or "")[:80], c.get("source", "") if c else ""])
    stat = {m: sum(1 for o in out if o["match"] == m) for m in ("exact", "partial", "none")}
    print(f"저장: {d} (순위 {len(out)}건 — 일치 {stat['exact']}, 유사 {stat['partial']}, 없음 {stat['none']} / API 호출 {calls}회)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
