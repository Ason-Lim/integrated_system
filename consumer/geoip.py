"""클라이언트 IP → 국가 코드(ISO 3166-1 alpha-2) 조회.

우선순위:
  1) CDN/프록시가 넣어주는 국가 헤더 (기본: CF-IPCountry)
  2) GEOIP_LOOKUP_URL 이 설정된 경우 외부 조회 (예: https://ipapi.co/{ip}/country/)
  3) 실패 시 None

사설/루프백 IP 는 조회하지 않는다. 외부 의존성 없이 동작하도록 표준 라이브러리만 사용.
"""
from __future__ import annotations

import ipaddress
import logging
import os
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

COUNTRY_HEADER = os.getenv("GEOIP_COUNTRY_HEADER", "CF-IPCountry").lower()
LOOKUP_URL = os.getenv("GEOIP_LOOKUP_URL", "").strip()
LOOKUP_TIMEOUT = float(os.getenv("GEOIP_LOOKUP_TIMEOUT", "1.5"))


def _is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_multicast or addr.is_reserved or addr.is_unspecified)


def client_ip(headers: dict, peer: str | None) -> str | None:
    """프록시 헤더를 고려한 클라이언트 IP. 신뢰 경계는 배포 환경에서 설정한다."""
    xff = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    real = headers.get("x-real-ip") or headers.get("X-Real-IP")
    if real:
        return real.strip()
    return peer


def _normalize(code: str | None) -> str | None:
    if not code:
        return None
    c = code.strip().upper()
    if len(c) != 2 or not c.isalpha() or c in {"XX", "T1"}:
        return None
    return c


def lookup(headers: dict, peer: str | None) -> str | None:
    """국가 코드를 반환. 알 수 없으면 None."""
    hdr = _normalize(headers.get(COUNTRY_HEADER))
    if hdr:
        return hdr

    ip = client_ip(headers, peer)
    if not ip or not _is_public(ip):
        return None

    if not LOOKUP_URL:
        return None

    url = LOOKUP_URL.replace("{ip}", ip)
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        log.warning("GEOIP_LOOKUP_URL 형식이 올바르지 않습니다: %s", LOOKUP_URL)
        return None
    try:
        with httpx.Client(timeout=LOOKUP_TIMEOUT) as c:
            r = c.get(url)
            r.raise_for_status()
            body = r.text.strip()
    except Exception as e:
        log.debug("GeoIP 조회 실패 (%s): %s", ip, e)
        return None
    return _normalize(body)
