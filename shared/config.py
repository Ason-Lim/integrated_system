"""공통 설정 — 환경변수 한 곳에서 읽는다.

두 앱(consumer, b2b)이 같은 Settings를 쓰되, B2B 전용 값(B2B_*)은 consumer에서 읽지 않는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv 는 선택
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[1]


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # ── 데이터 ─────────────────────────────────────────
    # 개발: SQLite 파일 2개(core / b2b). 운영: 같은 Postgres 의 다른 schema 권장.
    core_db_url: str = field(default_factory=lambda: os.getenv(
        "CORE_DB_URL", f"sqlite:///{ROOT / 'var' / 'core.sqlite3'}"))
    b2b_db_url: str = field(default_factory=lambda: os.getenv(
        "B2B_DB_URL", f"sqlite:///{ROOT / 'var' / 'b2b.sqlite3'}"))

    # ── LLM (none | ollama | openai | anthropic) ──────
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "none").lower())
    ollama_base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen2.5:7b"))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"))

    # ── 마켓 ───────────────────────────────────────────
    naver_enabled: bool = field(default_factory=lambda: _bool("NAVER_ENABLED"))
    sample_market_enabled: bool = field(default_factory=lambda: _bool("SAMPLE_MARKET", True))

    # ── commerce_ai 엔진 연결 ───────────────────────────
    # commerce_ai_generator 저장소 경로. 설정되어 있고 import 가능하면 랭킹을 그 엔진에 위임.
    commerce_ai_path: str | None = field(default_factory=lambda: os.getenv("COMMERCE_AI_PATH"))
    # food-nlu 폴더 경로 + DATABASE_URL(사전 DB)이 있으면 LLM NLU 사용
    food_nlu_path: str | None = field(default_factory=lambda: os.getenv("FOOD_NLU_PATH"))

    # ── B2B 내부 콘솔 ───────────────────────────────────
    b2b_access_token: str = field(default_factory=lambda: os.getenv("B2B_ACCESS_TOKEN", "change-me"))
    b2b_bid_source_url: str | None = field(default_factory=lambda: os.getenv(
        "B2B_BID_SOURCE_URL"))  # 예: https://smallbiz-monitor.onrender.com/api/b2b_gift (JSON)
    company_profile_path: str = field(default_factory=lambda: os.getenv(
        "COMPANY_PROFILE", str(ROOT / "b2b" / "data" / "company_profile.json")))


def get_settings() -> Settings:
    return Settings()
