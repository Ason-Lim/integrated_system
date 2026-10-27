#!/usr/bin/env python3
"""식품정보24(foodpolis) 오픈 API 점검 — 키는 출력하지 않는다.

키: .env 의 FOOD24_API_KEY  (식품정보24 > 오픈 API > 활용신청 승인 후 발급)
실행: venv/bin/python scripts/check_food24_api.py

요청 형식 (식품정보24 오픈 API 상세 페이지 기준):
  https://www.foodpolis.kr/food24/co/api/apVhdService/{오퍼레이션}?opapiAtkeyCn=키&type=json&numOfRows=10&pageNo=1
에러코드: 10 잘못된 파라미터 / 12 서비스 없음·폐기 / 30 등록되지 않은 키 / 31 기한만료 키 / 99 기타
※ 'AI추천키워드_상세'는 아직 개발 미완료(2026-10-27 진흥원 답변) — 목록에 잘못 공지됨.
"""
from __future__ import annotations

import json, sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://www.foodpolis.kr/food24/co/api/apVhdService/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) integrated_system-check", "Accept": "application/json, */*"}
PAGED = {"numOfRows": 3, "pageNo": 1}
CHECKS = [
    ("일반식품_기본", "getGfBaseRaw", PAGED),
    ("건강기능식품_기본", "getFfBaseRaw", PAGED),
    ("교육지원서비스_목록", "getEnsEdu", PAGED),
    ("일반사업공고_목록", "getEnsSprtPbanc", PAGED),
    # AI추천키워드_상세: 2026-10-27 진흥원 답변 — 아직 개발 미완료, 목록 공지가 잘못 게시됨. 개통되면 추가.
]


def key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("FOOD24_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def main() -> int:
    k = key()
    if not k:
        print(".env 에 FOOD24_API_KEY 가 없습니다.")
        return 2
    print(f"키 길이 {len(k)}자 (앞뒤 공백·따옴표 제거 후)")
    for name, op, extra in CHECKS:
        for typ in ("json",):
            try:
                r = requests.get(BASE + op, params={"opapiAtkeyCn": k, "type": typ, **extra}, headers=HEADERS, timeout=20)
                body = r.text.replace(k, "<KEY>")
                summary = body[:250].replace("\n", " ")
                try:
                    j = r.json()
                    summary = json.dumps(j, ensure_ascii=False)[:250]
                except ValueError:
                    pass
                print(f"\n[{name}] {op} → HTTP {r.status_code} ({r.headers.get('content-type', '')})\n  {summary}")
            except Exception as e:  # noqa: BLE001
                print(f"\n[{name}] {op} → 연결 실패: {type(e).__name__}: {str(e).replace(k, '<KEY>')[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
