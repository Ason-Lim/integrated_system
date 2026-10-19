"""core 저장소 — 관측 가격 이력과 검색 로그 (food-nlu schema_products.sql 의 축소판).

consumer 앱은 쓰기, b2b 앱은 읽기 전용으로 사용한다 (B2B 후보 발굴 시 소비자 쪽 관측 가격 재사용).
SQLAlchemy Core 로 작성해 SQLite(개발) ↔ Postgres(운영) 둘 다 동작.
"""
from __future__ import annotations

import json
from functools import lru_cache

from sqlalchemy import (JSON, Column, DateTime, Float, Integer, MetaData, String, Table, Text,
                        create_engine, func, insert, select)

from shared.config import get_settings
from shared.models import Intent, Offer, now_utc

meta = MetaData()

offer_observation = Table(
    "offer_observation", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("mall", String(32), nullable=False),
    Column("mall_product_id", String(128)),
    Column("title", Text, nullable=False),
    Column("price", Integer),
    Column("shipping_fee", Integer),          # NULL = 미확인
    Column("url", Text),
    Column("is_sample", Integer, default=0),
    Column("observed_at", DateTime(timezone=True), default=now_utc),
)

search_log = Table(
    "search_log", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64)),
    Column("query", Text),
    Column("action", String(64)),
    Column("context", String(64)),
    Column("slots", JSON),
    Column("result_count", Integer),
    Column("engine", String(32)),
    Column("created_at", DateTime(timezone=True), default=now_utc),
)

click_log = Table(
    "click_log", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("session_id", String(64)),
    Column("mall", String(32)),
    Column("mall_product_id", String(128)),
    Column("rank", Integer),
    Column("score", Float),
    Column("created_at", DateTime(timezone=True), default=now_utc),
)


@lru_cache
def engine(url: str | None = None):
    url = url or get_settings().core_db_url
    eng = create_engine(url, future=True)
    meta.create_all(eng)
    return eng


def record_offers(offers: list[Offer]) -> None:
    rows = [dict(mall=o.mall, mall_product_id=o.mall_product_id, title=o.title, price=o.price,
                 shipping_fee=o.shipping_fee, url=o.url, is_sample=int(o.is_sample), observed_at=o.observed_at)
            for o in offers]
    if rows:
        with engine().begin() as c:
            c.execute(insert(offer_observation), rows)


def log_search(session_id: str, query: str, intent: Intent, count: int, engine_name: str) -> None:
    with engine().begin() as c:
        c.execute(insert(search_log).values(
            session_id=session_id, query=query, action=intent.action, context=intent.context,
            slots=json.loads(json.dumps(intent.slots, ensure_ascii=False)), result_count=count, engine=engine_name))


def log_click(session_id: str, mall: str, pid: str, rank: int, score: float) -> None:
    with engine().begin() as c:
        c.execute(insert(click_log).values(session_id=session_id, mall=mall, mall_product_id=pid, rank=rank, score=score))


def recent_observations(keyword: str, limit: int = 20, include_sample: bool = False) -> list[dict]:
    """B2B 가 읽기 전용으로 사용: 키워드가 들어간 최근 관측 가격."""
    q = select(offer_observation).where(offer_observation.c.title.contains(keyword))
    if not include_sample:
        q = q.where(offer_observation.c.is_sample == 0)
    q = q.order_by(offer_observation.c.observed_at.desc()).limit(limit)
    with engine().connect() as c:
        return [dict(r._mapping) for r in c.execute(q)]


def stats() -> dict:
    with engine().connect() as c:
        return {"observations": c.execute(select(func.count()).select_from(offer_observation)).scalar(),
                "searches": c.execute(select(func.count()).select_from(search_log)).scalar()}
