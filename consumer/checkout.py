"""결제 프로세스 — 국내 PG 와 해외 Stripe/PayPal 로 분기되는 인터페이스 뼈대.

흐름
  1) Cart 를 국내/해외로 분리 (Cart.split)
  2) 각 그룹에 맞는 PaymentProvider 를 선택 (route_provider)
  3) 그룹별로 PaymentIntent 를 생성하고, 클라이언트가 완료하면 confirm
  4) 모든 그룹이 성공하면 CheckoutResult.status = "paid"

실 API 키가 없으면 각 어댑터는 enabled=False 이며, 호출 시 PaymentUnavailable 을 던진다.
(shared/logistics/shipping_agency.py 와 동일한 원칙 — 예시 데이터를 실제 결제처럼 섞지 않는다)
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

import httpx

from consumer.cart import Cart, CartItem

log = logging.getLogger(__name__)


class PaymentUnavailable(RuntimeError):
    """PG/결제대행 API 키 미설정 또는 호출 실패."""


class PaymentStatus(str, Enum):
    PENDING = "pending"
    REQUIRES_ACTION = "requires_action"   # 3DS, PayPal 리다이렉트 등
    PAID = "paid"
    FAILED = "failed"
    CANCELED = "canceled"


class Region(str, Enum):
    DOMESTIC = "domestic"
    OVERSEAS = "overseas"


@dataclass
class PaymentIntent:
    """결제 시도 1건. provider 별 id 를 그대로 보관한다."""
    id: str
    provider: str
    region: Region
    amount_krw: int
    currency: str = "KRW"
    status: PaymentStatus = PaymentStatus.PENDING
    client_secret: str | None = None   # Stripe 등 클라이언트 SDK 용
    redirect_url: str | None = None    # PayPal 등 리다이렉트 용
    raw: dict = field(default_factory=dict)


@dataclass
class CheckoutResult:
    cart_id: str
    status: PaymentStatus
    intents: list[PaymentIntent] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ── 결제 제공자 인터페이스 ────────────────────────────────────────
@runtime_checkable
class PaymentProvider(Protocol):
    code: str
    region: Region

    @property
    def enabled(self) -> bool: ...

    def create_intent(self, items: list[CartItem], amount_krw: int,
                      *, idempotency_key: str | None = None) -> PaymentIntent: ...

    def confirm(self, intent: PaymentIntent, *, payload: dict | None = None) -> PaymentIntent: ...


class _HttpProvider:
    """공통 HTTP 호출 로직. 하위 클래스가 엔드포인트/파싱만 구현한다."""

    code: str = ""
    region: Region = Region.DOMESTIC
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
        return self._session or httpx.Client(timeout=15.0)

    def _post(self, path: str, payload: dict, headers: dict | None = None) -> dict:
        if not self.enabled:
            raise PaymentUnavailable(f"{self.code}: API 키/베이스 URL 미설정")
        h = {"Authorization": f"Bearer {self.key}"}
        if headers:
            h.update(headers)
        try:
            with self._client() as c:
                r = c.post(f"{self.base}{path}", json=payload, headers=h)
                r.raise_for_status()
                return r.json()
        except Exception as e:
            log.warning("%s 결제 호출 실패: %s", self.code, e)
            raise PaymentUnavailable(f"{self.code}: {e}") from e

    # 하위 클래스 구현 지점
    def create_intent(self, items: list[CartItem], amount_krw: int,
                      *, idempotency_key: str | None = None) -> PaymentIntent:
        raise NotImplementedError

    def confirm(self, intent: PaymentIntent, *, payload: dict | None = None) -> PaymentIntent:
        raise NotImplementedError


class TossPaymentsAdapter(_HttpProvider):
    """국내 PG — 토스페이먼츠. 엔드포인트/응답 스키마는 계약 확정 후 채운다."""
    code = "toss"
    region = Region.DOMESTIC
    env_key = "TOSS_SECRET_KEY"
    env_base = "TOSS_API_BASE"
    default_base = "https://api.tosspayments.com"

    def create_intent(self, items: list[CartItem], amount_krw: int,
                      *, idempotency_key: str | None = None) -> PaymentIntent:
        data = self._post("/v1/payments", {
            "amount": amount_krw,
            "orderId": idempotency_key or uuid.uuid4().hex,
            "orderName": _order_name(items),
            "currency": "KRW",
        })
        return PaymentIntent(
            id=data.get("paymentKey", ""), provider=self.code, region=self.region,
            amount_krw=amount_krw, status=_map_status(data.get("status")),
            client_secret=data.get("checkout", {}).get("url"), raw=data,
        )

    def confirm(self, intent: PaymentIntent, *, payload: dict | None = None) -> PaymentIntent:
        data = self._post(f"/v1/payments/{intent.id}/confirm", payload or {})
        intent.status = _map_status(data.get("status"))
        intent.raw = data
        return intent


class StripeAdapter(_HttpProvider):
    """해외 카드 결제 — Stripe. PaymentIntent 생성/확인."""
    code = "stripe"
    region = Region.OVERSEAS
    env_key = "STRIPE_SECRET_KEY"
    env_base = "STRIPE_API_BASE"
    default_base = "https://api.stripe.com"

    def create_intent(self, items: list[CartItem], amount_krw: int,
                      *, idempotency_key: str | None = None) -> PaymentIntent:
        # TODO: KRW → 결제 통화 변환 정책 확정 필요 (현재는 KRW 그대로 전송)
        data = self._post("/v1/payment_intents", {
            "amount": amount_krw,
            "currency": "krw",
            "description": _order_name(items),
            "automatic_payment_methods[enabled]": "true",
        }, headers={"Idempotency-Key": idempotency_key} if idempotency_key else None)
        return PaymentIntent(
            id=data.get("id", ""), provider=self.code, region=self.region,
            amount_krw=amount_krw, status=_map_status(data.get("status")),
            client_secret=data.get("client_secret"), raw=data,
        )

    def confirm(self, intent: PaymentIntent, *, payload: dict | None = None) -> PaymentIntent:
        data = self._post(f"/v1/payment_intents/{intent.id}/confirm", payload or {})
        intent.status = _map_status(data.get("status"))
        intent.raw = data
        return intent


class PayPalAdapter(_HttpProvider):
    """해외 결제 — PayPal. 주문 생성 후 승인 리다이렉트."""
    code = "paypal"
    region = Region.OVERSEAS
    env_key = "PAYPAL_CLIENT_SECRET"
    env_base = "PAYPAL_API_BASE"
    default_base = "https://api-m.paypal.com"

    def create_intent(self, items: list[CartItem], amount_krw: int,
                      *, idempotency_key: str | None = None) -> PaymentIntent:
        # TODO: KRW → USD 등 결제 통화 변환 정책 확정 필요
        data = self._post("/v2/checkout/orders", {
            "intent": "CAPTURE",
            "purchase_units": [{
                "amount": {"currency_code": "KRW", "value": f"{amount_krw:.2f}"},
                "description": _order_name(items),
            }],
        })
        links = {l.get("rel"): l.get("href") for l in data.get("links", [])}
        return PaymentIntent(
            id=data.get("id", ""), provider=self.code, region=self.region,
            amount_krw=amount_krw, status=_map_status(data.get("status")),
            redirect_url=links.get("approve"), raw=data,
        )

    def confirm(self, intent: PaymentIntent, *, payload: dict | None = None) -> PaymentIntent:
        data = self._post(f"/v2/checkout/orders/{intent.id}/capture", payload or {})
        intent.status = _map_status(data.get("status"))
        intent.raw = data
        return intent


_PROVIDERS: dict[str, type[_HttpProvider]] = {
    TossPaymentsAdapter.code: TossPaymentsAdapter,
    StripeAdapter.code: StripeAdapter,
    PayPalAdapter.code: PayPalAdapter,
}


def get_provider(code: str, **kw) -> PaymentProvider:
    try:
        cls = _PROVIDERS[code]
    except KeyError:
        raise PaymentUnavailable(f"알 수 없는 결제 제공자: {code}") from None
    return cls(**kw)


def route_provider(region: Region, *, preferred: str | None = None) -> PaymentProvider:
    """지역에 맞는 결제 제공자를 선택한다.

    - 국내: 기본 toss
    - 해외: preferred(stripe|paypal) 우선, 없으면 stripe
    """
    if region is Region.DOMESTIC:
        return get_provider(preferred or "toss")
    if preferred in ("stripe", "paypal"):
        return get_provider(preferred)
    return get_provider("stripe")


# ── 오케스트레이션 ────────────────────────────────────────────────
def checkout(cart: Cart, *, preferred_overseas: str | None = None,
             idempotency_key: str | None = None) -> CheckoutResult:
    """장바구니를 국내/해외로 나눠 각각 결제 인텐트를 만든다.

    실제 승인(confirm)은 클라이언트가 3DS/리다이렉트를 마친 뒤 별도 호출로 수행한다.
    """
    if not cart.items:
        return CheckoutResult(cart_id=cart.id, status=PaymentStatus.FAILED,
                              notes=["장바구니가 비어 있습니다."])

    domestic, overseas = cart.split()
    intents: list[PaymentIntent] = []
    notes: list[str] = []

    for region, items in ((Region.DOMESTIC, domestic), (Region.OVERSEAS, overseas)):
        if not items:
            continue
        amount = sum(x.line_total or 0 for x in items)
        if any(x.line_total is None for x in items):
            notes.append(f"{region.value}: 가격 미확인 항목이 있어 결제를 진행할 수 없습니다.")
            return CheckoutResult(cart_id=cart.id, status=PaymentStatus.FAILED,
                                  intents=intents, notes=notes)
        provider = route_provider(region, preferred=preferred_overseas)
        try:
            intent = provider.create_intent(items, amount, idempotency_key=idempotency_key)
        except PaymentUnavailable as e:
            notes.append(f"{region.value}: {e}")
            return CheckoutResult(cart_id=cart.id, status=PaymentStatus.FAILED,
                                  intents=intents, notes=notes)
        intents.append(intent)

    status = (PaymentStatus.PAID if all(i.status is PaymentStatus.PAID for i in intents)
              else PaymentStatus.REQUIRES_ACTION)
    return CheckoutResult(cart_id=cart.id, status=status, intents=intents, notes=notes)


# ── 헬퍼 ──────────────────────────────────────────────────────────
def _order_name(items: list[CartItem]) -> str:
    if not items:
        return "주문"
    first = items[0].offer.title
    return first if len(items) == 1 else f"{first} 외 {len(items) - 1}건"


def _map_status(raw: str | None) -> PaymentStatus:
    """제공자별 상태 문자열을 공통 PaymentStatus 로 매핑."""
    s = (raw or "").lower()
    if s in {"paid", "succeeded", "captured", "completed", "done"}:
        return PaymentStatus.PAID
    if s in {"requires_action", "requires_confirmation", "requires_capture", "approved"}:
        return PaymentStatus.REQUIRES_ACTION
    if s in {"failed", "declined", "error"}:
        return PaymentStatus.FAILED
    if s in {"canceled", "cancelled", "voided"}:
        return PaymentStatus.CANCELED
    return PaymentStatus.PENDING
