#!/usr/bin/env python3
"""농사로 지역특산물(localSpcprd) · 농가맛집(frmhsTasteHos) → 지역 정보 카탈로그 (표준 라이브러리만 사용).

출력: var/knowledge/local_specialties.json, var/knowledge/farm_restaurants.json
실행: venv/bin/python scripts/update_local_knowledge.py [--probe] [--only spc|frm]
"""
from __future__ import annotations

import argparse, json, os, sys, tempfile, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nongsaro_api as ns  # noqa: E402

ROOT = ns.ROOT
OUT_DIR = Path(os.environ.get("LOCAL_KNOWLEDGE_DIR", ROOT / "var" / "knowledge"))


def save(name: str, key: str, rows: list[dict], source: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / name
    doc = {"generated_at": datetime.now().isoformat(timespec="seconds"), "source": source, "total": len(rows), key: rows}
    fd, tmp = tempfile.mkstemp(dir=OUT_DIR, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, out)
    print(f"  저장: {out} ({len(rows)}건)")


def collect_specialties(key: str) -> list[dict]:
    out, seen = [], set()
    for r in ns.paged("localSpcprd", "localSpcprdLst", key):
        name = ns.text(r.get("cntntsSj"))
        area = " ".join(x.strip() for x in ns.text(r.get("areaNm")).split(">") if x.strip())   # '경상북도 > 영양군' 
        if not name or (name, area) in seen:
            continue
        seen.add((name, area))
        out.append({"id": f"spc-{r.get('cntntsNo')}", "name": name, "region": area,
                    "image": r.get("imgUrl") or None, "link": r.get("linkUrl") or None,
                    "registered": r.get("svcDt") or None})
    print(f"  지역특산물: {len(out)}건")
    return out


def menu_from(text: str) -> str:
    """본문의 '대표 상차림/메뉴' 다음 줄들을 메뉴로 본다."""
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    for i, l in enumerate(lines):
        if "대표" in l and any(w in l for w in ("상차림", "메뉴", "음식")):
            return " ".join(lines[i + 1:i + 3])
    return ""


def collect_restaurants(key: str) -> list[dict]:
    out = []
    for r in ns.paged("frmhsTasteHos", "frmhsTasteHosList", key):
        no = r.get("cntntsNo")
        d = {**r, **ns.first(ns.call("frmhsTasteHos", "frmhsTasteHosDtl", key, cntntsNo=no))}
        name = ns.text(d.get("cntntsSj"))
        if not name:
            continue
        out.append({
            "id": f"frm-{no}", "name": name, "region": ns.text(d.get("adstrdNm")),
            "slogan": ns.text(d.get("slogan")) or None, "summary": ns.text(d.get("smm"))[:300] or None,
            "address": ns.text(d.get("locplc")) or None, "tel": ns.text(d.get("telno")) or None,
            # 대표메뉴 필드는 대개 비어 있어 본문(cn)을 그대로 두고, 메뉴 이름은 서버에서 '대표 상차림' 아래 제목만 뽑는다
            "menu": ns.text(d.get("trtmntMenu"))[:200] or None,
            "detail": ns.text(d.get("cn"))[:1500] or None,
            "hours": ns.text(d.get("bsnTime")) or None,
            "closed": ns.text(d.get("restde")) or None, "program": ns.text(d.get("exprnProgrm"))[:200] or None,
            "url": d.get("url") or None, "image": d.get("imgUrl") or d.get("imgUrl1") or None,
        })
        time.sleep(0.05)
    print(f"  농가맛집: {len(out)}건")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--only", choices=["spc", "frm"])
    a = ap.parse_args()
    key = ns.api_key()
    if not key:
        print("NONGSARO_API_KEY 가 .env 에 없습니다.")
        return 2
    if a.probe:
        print("[지역특산물]")
        ns.probe("localSpcprd", "selectAreaSidoLst", key)
        ns.probe("localSpcprd", "localSpcprdLst", key, pageNo=1, numOfRows=3)
        print("[농가맛집]")
        rows = ns.probe("frmhsTasteHos", "frmhsTasteHosList", key, pageNo=1, numOfRows=3)
        if rows:
            ns.probe("frmhsTasteHos", "frmhsTasteHosDtl", key, cntntsNo=rows[0].get("cntntsNo"))
        print("[향토음식]")
        rows = ns.probe("nvpcFdCkry", "fdNmLst", key, pageNo=1, numOfRows=3)
        if rows:
            ns.probe("nvpcFdCkry", "fdNmDtl", key, cntntsNo=rows[0].get("cntntsNo"))
        print("[종가음식]")
        rows = ns.probe("headFamilyFood", "headFamilyFoodLst", key, pageNo=1, numOfRows=3)
        if rows:
            ns.probe("headFamilyFood", "headFamilyFoodDtl", key, cntntsNo=rows[0].get("cntntsNo"))
        return 0
    print(f"[{datetime.now():%F %T}] 농사로 지역 정보 수집 시작")
    rc = 0
    for code, fn, fname, k, src in (
        ("spc", collect_specialties, "local_specialties.json", "specialties", "농촌진흥청 농사로 지역특산물"),
        ("frm", collect_restaurants, "farm_restaurants.json", "restaurants", "농촌진흥청 농사로 농가맛집"),
    ):
        if a.only and a.only != code:
            continue
        try:
            rows = fn(key)
            if rows:
                save(fname, k, rows, src)
            else:
                print(f"  ! {fname}: 0건 — 기존 파일 유지")
        except Exception as e:  # noqa: BLE001
            rc = 1
            print(f"  ! {code} 수집 실패 (기존 파일 유지): {e}")
    print(f"[{datetime.now():%F %T}] 완료")
    return rc


if __name__ == "__main__":
    sys.exit(main())
