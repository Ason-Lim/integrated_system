"""LLM 클라이언트 — food-nlu 의 Ollama/OpenAI 스위치를 확장(anthropic 추가)하고,
LLM_PROVIDER=none 이면 호출하지 않는다. 모든 호출부는 LLM 없이도 동작하는 규칙 경로를 가진다.
"""
from __future__ import annotations

import json
import re
from typing import Any

import requests

from shared.config import Settings, get_settings


class LLMUnavailable(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self.s.llm_provider in {"ollama", "openai", "anthropic"}

    def chat(self, system: str, user: str, *, json_mode: bool = False,
             temperature: float = 0.0, max_tokens: int = 2000) -> str:
        p = self.s.llm_provider
        if p == "ollama":
            body: dict[str, Any] = {
                "model": self.s.ollama_model, "stream": False,
                "options": {"temperature": temperature},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
            }
            if json_mode:
                body["format"] = "json"
            r = requests.post(self.s.ollama_base_url + "/api/chat", json=body, timeout=120)
            r.raise_for_status()
            return r.json()["message"]["content"]
        if p == "openai":
            from openai import OpenAI  # 지연 import

            kw: dict[str, Any] = {}
            if json_mode:
                kw["response_format"] = {"type": "json_object"}
            resp = OpenAI().chat.completions.create(
                model=self.s.openai_model, temperature=temperature, max_tokens=max_tokens,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}], **kw)
            return resp.choices[0].message.content or ""
        if p == "anthropic":
            import anthropic  # 지연 import

            msg = anthropic.Anthropic().messages.create(
                model=self.s.anthropic_model, max_tokens=max_tokens, temperature=temperature,
                system=system + ("\n반드시 JSON 하나만 출력." if json_mode else ""),
                messages=[{"role": "user", "content": user}])
            return "".join(getattr(b, "text", "") for b in msg.content)
        raise LLMUnavailable("LLM_PROVIDER=none")

    def chat_json(self, system: str, user: str, **kw) -> dict:
        return safe_json(self.chat(system, user, json_mode=True, **kw))


def safe_json(raw: str) -> dict:
    """코드블록·설명이 붙어도 첫 JSON 객체만 추출 (food-nlu 에서 이식)."""
    if not raw:
        raise ValueError("빈 응답")
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"JSON 없음: {raw[:200]}")
    return json.loads(m.group(0))
