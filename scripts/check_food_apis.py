#!/usr/bin/env python3
"""레시피·보관법 후보 공공데이터 API 응답 점검 (표준 라이브러리만 사용, 키는 출력하지 않음).

실행: venv/bin/python scripts/check_food_apis.py
"""
import json, re, urllib.parse, urllib.request
from pathlib import Path

ENV = {}
for line in (Path(__file__).resolve().parent.parent / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        ENV[k.strip()] = v.strip().strip("'\"")


def call(name, url):
    print(f"\n## {name}")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print(f"  실패: {type(e).__name__}: {e}")
        return
    body = re.sub(r"[0-9A-Za-z]{30,}", "<KEY>", body)
    try:
        data = json.loads(body)
        root = next(iter(data.values())) if isinstance(data, dict) else data
        rows = root.get("row", []) if isinstance(root, dict) else []
        print("  결과코드:", (root.get("RESULT") if isinstance(root, dict) else None))
        print("  총건수:", root.get("total_count") or root.get("totalCnt") if isinstance(root, dict) else "?")
        if rows:
            print("  필드:", ", ".join(rows[0].keys()))
            first = {k: (str(v)[:80]) for k, v in list(rows[0].items())[:12]}
            print("  첫 행:", json.dumps(first, ensure_ascii=False))
        else:
            print("  응답 앞부분:", body[:400])
    except ValueError:
        print("  응답 앞부분:", body[:400])


q = urllib.parse.quote
fs = ENV.get("FOODSAFETY_API_KEY", "")
svc = ENV.get("FOODSAFETY_RECIPE_SERVICE_ID", "COOKRCP01")
call("식품안전나라 레시피 (파스타)", f"http://openapi.foodsafetykorea.go.kr/api/{fs}/{svc}/json/1/3/RCP_NM={q('파스타')}")
call("식품안전나라 레시피 (감)", f"http://openapi.foodsafetykorea.go.kr/api/{fs}/{svc}/json/1/3/RCP_PARTS_DTLS={q('감')}")

base = ENV.get("EPIS_RECIPE_API_BASE_URL", "http://211.237.50.150:7080/openapi")
ek = ENV.get("EPIS_RECIPE_API_KEY", "")
call("농식품정보누리 레시피 기본정보", f"{base}/{ek}/json/Grid_20150827000000000226_1/1/3")

nk = ENV.get("AFDC_NUTRITION_EFFICACY_API_KEY", "")
call("농산물 영양·효능 (" + ENV.get("AFDC_NUTRITION_EFFICACY_API_NO", "") + ")",
     f"{base}/{nk}/json/Grid_20171128000000000572_1/1/3")
