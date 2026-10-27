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
SERVICE = "C002"
CACHE_DAYS = 30


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
    m = re.match(r"^\s*([^)\s]{1,6})\)\s*(.+)$", prod or "")
    if m:
        brand, prod = m.group(1), m.group(2)
    prod = re.sub(r"[*_+]", " ", prod)
    prod = re.sub(r"\(\d+입\)|\d+(입|T|포|개)$", "", prod).strip()
    return prod, brand


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
            "item_type": g(r, "PRDLST_DCNM"), "raw": raw[:500],
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
    if not key:
        print(".env 에 FOODSAFETY_API_KEY 가 없습니다.")
        return 2
    if a.probe:
        try:
            rows = search(key, query_name(a.probe)[0], 5)
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
            if not hit or hit.get("at", "") < fresh:
                q, brand = query_name(prod)
                try:
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
                calls += 1
                if brand:   # 브랜드 표기가 있으면 제조사명에 그 글자가 든 행을 앞으로
                    rows.sort(key=lambda x: brand not in g(x, "BSSH_NM"))
                kind, picked = best(q, rows)
                hit = cache[k] = {"at": datetime.now().isoformat(timespec="seconds"), "match": kind,
                                  "candidates": [summarize(x) for x in picked]}
                time.sleep(0.3)
            out.append({"yyyymm": r.get("yyyymm") or e.get("yyyymm"), "channel": e.get("channel"),
                        "class2": e.get("class2Nm"), "class3": e.get("class3Nm"), "rank": r.get("rank"),
                        "product": prod, "match": hit["match"], "candidates": hit["candidates"]})
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    day = src.parent.name
    d = OUT_DIR / day
    d.mkdir(parents=True, exist_ok=True)
    doc = {"reference_only": True,
           "note": "내부 참고 자료 — 화면·추천·블로그·외부 게시 금지 (식품정보24 이용약관, 원자료 NICE 지니데이터)",
           "source_rankings": str(src.relative_to(ROOT)), "enriched_with": "식품안전나라 C002 품목제조보고(원재료)",
           "generated_at": datetime.now().isoformat(timespec="seconds"), "rows": out}
    (d / "rankings_enriched.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(d / "rankings_enriched.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["기준월", "채널", "중분류", "소분류", "순위", "제품명", "매칭", "제조사", "품목유형", "알레르기(원재료 기준)", "원재료(앞부분)"])
        for o in out:
            c = (o["candidates"] or [{}])[0]
            w.writerow([o["yyyymm"], o["channel"], o["class2"], o["class3"], o["rank"], o["product"],
                        {"exact": "일치", "partial": "유사(확인 필요)", "none": "없음"}[o["match"]],
                        c.get("company", ""), c.get("item_type", ""), ", ".join(c.get("allergens", [])),
                        (c.get("raw") or "")[:80]])
    stat = {m: sum(1 for o in out if o["match"] == m) for m in ("exact", "partial", "none")}
    print(f"저장: {d} (순위 {len(out)}건 — 일치 {stat['exact']}, 유사 {stat['partial']}, 없음 {stat['none']} / API 호출 {calls}회)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
