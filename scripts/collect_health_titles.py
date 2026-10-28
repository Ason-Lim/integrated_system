#!/usr/bin/env python3
"""건강기능식품 실제 판매 상품명 수집 — 식품정보24 매칭 평가용 (scripts/eval_food24_match.py --real).

쿠팡 파트너스 검색 API로 검색어마다 최대 10건의 상품명만 저장한다 (가격·이미지·링크는 저장하지 않음).
상품 페이지는 열지 않는다 (파트너스 약관). 서비스 화면·추천에는 쓰지 않는 내부 평가 자료.

실행 (맥 터미널 — 이 API는 작업 VM에서 막혀 있음):
  cd ~/integrated_system && venv/bin/python scripts/collect_health_titles.py
  중간에 멈추면 다시 실행 — 이미 받은 검색어는 건너뛴다.
출력: var/tmp/health_titles.json
"""
from __future__ import annotations

import json, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import shared.config  # noqa: E402,F401  (.env 로드)
from shared.markets.coupang import CoupangPartnersAdapter  # noqa: E402

OUT = ROOT / "var" / "tmp" / "health_titles.json"
PAUSE = 6.0           # 검색 호출 간격(초) — 호출 제한에 걸리지 않게 천천히

KEYWORDS = [
    # 브랜드 + 제품 (식약처 신고명과 판매 상품명이 다르게 적히는 경우를 보려고)
    "정관장 홍삼정", "정관장 에브리타임", "종근당건강 락토핏", "종근당 아이클리어 루테인", "뉴트리원 루테인",
    "고려은단 비타민C 1000", "일양약품 로열젤리", "한미 밀크씨슬", "안국건강 루테인", "유한양행 오메가3",
    "대웅제약 밀크씨슬", "뉴트리코어 비타민D", "닥터린 크릴오일", "GNM자연의품격 루테인", "에버콜라겐",
    # 기능성 원료 (일반 검색어)
    "프로바이오틱스 유산균", "rTG 알티지 오메가3", "밀크씨슬 실리마린", "루테인 지아잔틴", "비타민D 1000IU",
    "멀티비타민 미네랄", "프로폴리스", "마그네슘", "아연", "쏘팔메토", "가르시니아", "비오틴", "칼슘 마그네슘 비타민D",
    "철분", "엽산", "코엔자임Q10", "글루코사민 MSM", "보스웰리아", "크릴오일", "홍삼스틱", "키즈 유산균",
    "콜라겐 건강기능식품", "혈행개선 오메가3", "장건강 유산균 100억",
]


def main() -> int:
    ad = CoupangPartnersAdapter()
    if not ad.enabled:
        print("쿠팡 파트너스 키(.env COUPANG_ACCESS_KEY/SECRET_KEY/PARTNER_ID)가 없습니다.")
        return 2
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"items": [], "done": []}
    todo = [k for k in KEYWORDS if k not in data["done"]]
    print(f"검색어 {len(KEYWORDS)}개 중 남은 {len(todo)}개 (예상 {len(todo) * PAUSE / 60:.0f}분)")
    for i, kw in enumerate(todo, 1):
        try:
            offers = ad.search(kw, 10)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            print(f"  ! '{kw}': {msg[:120]}")
            if "429" in msg or "Too Many" in msg:
                print("  호출 제한 — 지금까지 받은 것을 저장하고 멈춥니다. 잠시 뒤 다시 실행하세요.")
                break
            continue
        data["items"] += [{"keyword": kw, "mall": "coupang", "title": o.title, "product_id": o.mall_product_id,
                           "category": o.category} for o in offers]
        data["done"].append(kw)
        data["collected_at"] = datetime.now().isoformat(timespec="seconds")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  [{i}/{len(todo)}] {kw}: {len(offers)}건")
        time.sleep(PAUSE)
    print(f"저장: {OUT.relative_to(ROOT)} — 상품명 {len(data['items'])}건, 고유 {len({x['title'] for x in data['items']})}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
