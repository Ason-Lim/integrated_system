"""제휴(수수료) 링크 고지 — 공정위 '추천·보증 등에 관한 표시·광고 심사지침'(2024 개정)과 각 제휴 프로그램 정책.

원칙
- 수수료가 발생하는 링크가 포함된 응답은 '첫 부분'에 경제적 이해관계를 명확히 적는다
  ("수수료가 발생할 수 있습니다" 같은 모호한 표현은 쓰지 않는다).
- 쿠팡: 파트너스 API의 상품 링크는 모두 제휴 링크 → 쿠팡 권장 문구를 사용.
- 네이버: 쇼핑 검색 API 링크는 수수료가 없다. 네이버 쇼핑 커넥트 링크를 쓸 때만 NAVER_SHOPPING_CONNECT=1 로 켠다.
- 쿠팡·네이버 로고/BI/CI·캐릭터 이미지는 쓰지 않는다 (판매처 이름은 텍스트로만).
- 수수료 여부는 추천 순위에 반영하지 않는다.
"""
from __future__ import annotations

import os

PROGRAMS = {
    "coupang": "쿠팡 파트너스",
    "naver": "네이버 쇼핑 커넥트",
}
# 운영 취지 문구 — 반드시 함께 표시
SUPPORT_LINE = "받은 수수료는 본 사이트 운영과 무료 서비스 유지에 도움이 됩니다."
RANK_LINE = "수수료 여부는 추천 순위에 반영하지 않습니다."
SITE_NOTICE = ("이 사이트는 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다. "
               "수수료는 본 사이트 운영과 무료 서비스 유지에 도움이 됩니다.")


def is_affiliate(mall: str | None) -> bool:
    if mall == "coupang":
        return os.getenv("COUPANG_AFFILIATE", "1").strip().lower() not in {"0", "false", "no", "off"}
    if mall == "naver":
        return os.getenv("NAVER_SHOPPING_CONNECT", "0").strip().lower() in {"1", "true", "yes", "on"}
    return False


def program(mall: str | None) -> str | None:
    return PROGRAMS.get(mall or "") if is_affiliate(mall) else None


def disclosure(malls: list[str]) -> str | None:
    """응답 첫 부분에 넣을 고지문. 제휴 링크가 없으면 None."""
    progs = [PROGRAMS[m] for m in dict.fromkeys(malls) if m in PROGRAMS and is_affiliate(m)]
    if not progs:
        return None
    lead = "**광고 · 제휴 링크 안내** "
    if progs == ["쿠팡 파트너스"]:
        body = "이 추천은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
    else:
        body = f"이 추천은 {'·'.join(progs)} 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
    return f"{lead}{body} {SUPPORT_LINE} {RANK_LINE}"
