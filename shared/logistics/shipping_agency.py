"""배송대행지(몰티즈·큐익스프레스 등) API 연동 인터페이스와 최종 견적 산출.

설계 원칙
  - 각 대행지는 `ShippingAgency` Protocol 을 구현한다 (shared/markets/base.py 와 동일한 패턴).
  - 실 API 키가 없으면 `enabled=False` 로 두고, 호출 시 `AgencyUnavailable` 을 던진다.
    (예시 데이터를 실제 견적처럼 섞지 않는다 — shared/markets/registry.py 의 원칙과 동일)
  - `total_landed_cost()` 는 상품가 + 국제 배송비 + 구매대행 수수료 + 관세/부가세(추정)를
    환율로 원화 환산해 합산한다. 세부 세율·수수료는 설정값으로 주입 가능하게 둔다.

환경변수
  MALTESE_API_KEY / MALTESE_API_BASE
  QXPRESS_API_KEY / QXPRESS_API_BASE
  FX_KRW_PER_USD            (기본 1350)
  AGENCY_FEE_RATE           (구매대행 수수료율, 기본 0.10)
  CUSTOMS_DUTY_RATE         (관세율, 기본 0.08)
  CUSTOMS_VAT_RATE          (부가세율, 기본 0.10)
  CUSTOMS_DE_MINIMIS_USD    (면세 한도, 기본 150 USD)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

log = logging.getLogger(__name__)


class AgencyUnavailable(RuntimeError):
    """대행지 API 키 미설정 또는 호출 실패."""


# ── 요청/응답 모델 ────────────────────────────────────────────────
@dataclass
class ShippingRequest:
    """배송대행지에 견적을 요청할 때 필요한 최소 정보."""
    origin_country: str            # 예: "US"
    dest_country: str = "KR"
    weight_kg: float = 0.0
    length_cm: float = 0.0
    width_cm: float = 0.0
    height_cm: float = 0.0
    declared_value_usd: float = 0.0
    item_category: str | None = None   # 통관 카테고리 힌트 (예: "electronics")

    @property
    def volumetric_kg(self) -> float:
        """부피 무게(kg). 항공 표준 6000 cm³/kg 기준."""
        if not (self.length_cm and self.width_cm and self.height_cm):
            return 0.0
        return (self.length_cm * self.width_cm * self.height_cm) / 6000.0

    @property
    def chargeable_kg(self) -> float:
        """청구 무게 = max(실무게, 부피무게)."""
        return max(self.weight_kg, self.volumetric_kg)


@dataclass
class AgencyQuote:
    """대행지가 돌려주는 원시 견적 (USD 기준)."""
    agency: str
    shipping_usd: float
    eta_days_min: int
    eta_days_max: int
    currency: str = "USD"
    raw: dict = field(default_factory=dict)


# ── 대행지 어댑터 인터페이스 ──────────────────────────────────────
@runtime_checkable
class ShippingAgency(Protocol):
    code: str
    label: str

    @property
    def enabled(self) -> bool: ...

    def quote(self, req: ShippingRequest) -> AgencyQuote: ...


class _HttpAgency:
    """공통 HTTP 호출 로직. 하위 클래스가 엔드포인트/파싱만 구현한다."""

    code: str = ""
    label: str = ""
    env_key: str = ""
    env_base: str = ""
    default_base: str = ""

    def __init__(self, api_key: str | None = None, base: str | None = None, session=None):
        self.key = api_key or os.getenv(self.env_key, "")
        self.base = (base or os.getenv(self.env_base) or self.default_base).rstrip("/")
        self._session = session

    @property
    def enabled(self) -> bool:
        return bool(self.key and self.base)

    def _client(self) -> httpx.Client:
        return self._session or httpx.Client(timeout=10.0)

    def quote(self, req: ShippingRequest) -> AgencyQuote:
        if not self.enabled:
            raise AgencyUnavailable(f"{self.code}: API 키/베이스 URL 미설정")
        payload = self._payload(req)
        try:
            with self._client() as c:
                r = c.post(f"{self.base}/quote", json=payload,
                           headers={"Authorization": f"Bearer {self.key}"})
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            log.warning("%s 견적 조회 실패: %s", self.code, e)
            raise AgencyUnavailable(f"{self.code}: {e}") from e
        return self._parse(data)

    # 하위 클래스 구현 지점
    def _payload(self, req: ShippingRequest) -> dict:
        raise NotImplementedError

    def _parse(self, data: dict) -> AgencyQuote:
        raise NotImplementedError


class MalteseAdapter(_HttpAgency):
    """몰티즈(Maltese) 배송대행지 — 엔드포인트/응답 스키마는 계약 확정 후 채운다."""
    code = "maltese"
    label = "몰티즈"
    env_key = "MALTESE_API_KEY"
    env_base = "MALTESE_API_BASE"
    default_base = "https://api.maltese.example"

    def _payload(self, req: ShippingRequest) -> dict:
        return {
            "origin": req.origin_country, "dest": req.dest_country,
            "weight_kg": req.chargeable_kg,
            "dims_cm": [req.length_cm, req.width_cm, req.height_cm],
            "declared_value_usd": req.declared_value_usd,
            "category": req.item_category,
        }

    def _parse(self, data: dict) -> AgencyQuote:
        # TODO: 실제 응답 스키마 확정 시 매핑
        return AgencyQuote(
            agency=self.code,
            shipping_usd=float(data.get("shipping_usd", 0)),
            eta_days_min=int(data.get("eta_days_min", 0)),
            eta_days_max=int(data.get("eta_days_max", 0)),
            raw=data,
        )


class QxpressAdapter(_HttpAgency):
    """큐익스프레스(Qxpress) — 엔드포인트/응답 스키마는 계약 확정 후 채운다."""
    code = "qxpress"
    label = "큐익스프레스"
    env_key = "QXPRESS_API_KEY"
    env_base = "QXPRESS_API_BASE"
    default_base = "https://api.qxpress.example"

    def _payload(self, req: ShippingRequest) -> dict:
        return {
            "from_country": req.origin_country, "to_country": req.dest_country,
            "weight": req.chargeable_kg,
            "volume": req.length_cm * req.width_cm * req.height_cm,
            "value_usd": req.declared_value_usd,
        }

    def _parse(self, data: dict) -> AgencyQuote:
        # TODO: 실제 응답 스키마 확정 시 매핑
        return AgencyQuote(
            agency=self.code,
            shipping_usd=float(data.get("fee_usd", 0)),
            eta_days_min=int(data.get("min_days", 0)),
            eta_days_max=int(data.get("max_days", 0)),
            raw=data,
        )


_REGISTRY: dict[str, type[_HttpAgency]] = {
    MalteseAdapter.code: MalteseAdapter,
    QxpressAdapter.code: QxpressAdapter,
}


def list_agencies() -> list[str]:
    return list(_REGISTRY)


def get_agency(code: str, **kw) -> ShippingAgency:
    try:
        cls = _REGISTRY[code]
    except KeyError:
        raise AgencyUnavailable(f"알 수 없는 대행지: {code}") from None
    return cls(**kw)


# ── 최종 견적(landed cost) ────────────────────────────────────────
@dataclass
class LandedCost:
    """원화 기준 최종 견적. 각 항목은 KRW."""
    product_krw: int
    shipping_krw: int
    agency_fee_krw: int
    duty_krw: int
    vat_krw: int
    total_krw: int
    eta_days_min: int
    eta_days_max: int
    agency: str
    fx_krw_per_usd: float
    notes: list[str] = field(default_factory=list)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def total_landed_cost(
    *,
    product_usd: float,
    req: ShippingRequest,
    agency: ShippingAgency | None = None,
    agency_code: str = "maltese",
    fx_krw_per_usd: float | None = None,
    agency_fee_rate: float | None = None,
    duty_rate: float | None = None,
    vat_rate: float | None = None,
    de_minimis_usd: float | None = None,
) -> LandedCost:
    """상품가 + 국제 배송비 + 구매대행 수수료 + 관세/부가세를 원화로 합산.

    - 관세/부가세는 신고가 + 배송비가 면세 한도(기본 150 USD)를 넘을 때만 부과(단순화).
    - 실제 통관은 품목별 세율·FTA 등에 따라 달라질 수 있으므로 `notes` 에 경고를 남긴다.
    """
    fx = fx_krw_per_usd if fx_krw_per_usd is not None else _env_float("FX_KRW_PER_USD", 1350.0)
    fee_rate = agency_fee_rate if agency_fee_rate is not None else _env_float("AGENCY_FEE_RATE", 0.10)
    duty = duty_rate if duty_rate is not None else _env_float("CUSTOMS_DUTY_RATE", 0.08)
    vat = vat_rate if vat_rate is not None else _env_float("CUSTOMS_VAT_RATE", 0.10)
    limit = de_minimis_usd if de_minimis_usd is not None else _env_float("CUSTOMS_DE_MINIMIS_USD", 150.0)

    ag = agency or get_agency(agency_code)
    q = ag.quote(req)

    product_krw = round(product_usd * fx)
    shipping_krw = round(q.shipping_usd * fx)
    agency_fee_krw = round(product_krw * fee_rate)

    notes: list[str] = []
    customs_base_usd = product_usd + q.shipping_usd
    if customs_base_usd > limit:
        duty_krw = round(customs_base_usd * fx * duty)
        vat_krw = round((customs_base_usd * fx + duty_krw) * vat)
        notes.append(f"신고가+배송비가 면세 한도({limit:.0f} USD)를 초과해 관세·부가세를 추정 반영했습니다.")
    else:
        duty_krw = vat_krw = 0
        notes.append(f"면세 한도({limit:.0f} USD) 이내로 관세·부가세를 반영하지 않았습니다.")

    total = product_krw + shipping_krw + agency_fee_krw + duty_krw + vat_krw
    notes.append("환율·세율은 추정치이며 실제 청구 금액과 다를 수 있습니다.")

    return LandedCost(
        product_krw=product_krw,
        shipping_krw=shipping_krw,
        agency_fee_krw=agency_fee_krw,
        duty_krw=duty_krw,
        vat_krw=vat_krw,
        total_krw=total,
        eta_days_min=q.eta_days_min,
        eta_days_max=q.eta_days_max,
        agency=q.agency,
        fx_krw_per_usd=fx,
        notes=notes,
    )
