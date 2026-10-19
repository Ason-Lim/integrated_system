"""Supplier discovery is separate from supply eligibility and quote validity."""
from datetime import datetime, timezone
from pydantic import BaseModel, Field

class SupplierEvidence(BaseModel):
    supplier_id: str
    name: str
    source_ref: str
    business_status_confirmed: bool = False
    species: list[str] = Field(default_factory=list)
    spec: str | None = None
    quantity: int | None = Field(None, gt=0)
    quote_price: int | None = Field(None, ge=0)
    quote_expires_at: datetime | None = None
    delivery_confirmed: bool = False

    def evaluate(self, now=None):
        now = now or datetime.now(timezone.utc)
        expires = self.quote_expires_at
        if expires and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        checks = {"현재 영업상태": self.business_status_confirmed, "취급 축종": bool(self.species),
                  "규격": bool(self.spec), "수량": self.quantity is not None,
                  "납기": self.delivery_confirmed,
                  "유효 견적": self.quote_price is not None and expires is not None and expires > now}
        return {"status": "READY_FOR_REVIEW" if all(checks.values()) else "DISCOVERY_ONLY",
                "supplier_questions": [k for k, v in checks.items() if not v], "auto_order": False}
