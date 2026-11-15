"""Chooses the model provider for an organisation: its saved settings if any, otherwise the environment."""

import asyncio
import hashlib
import importlib
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.config import LLM_PROVIDERS, get_settings
from app.db import tenant_session
from app.llm.anthropic import AnthropicProvider
from app.llm.base import LLMProvider, call_with_retry
from app.llm.egress import validate_base_url
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.pricing import cost_usd
from app.llm.stub import StubProvider
from app.llm.types import LLMResponse, Message, ToolSpec
from app.models.llm import LLMSettings
from app.security.crypto import decrypt

PROVIDERS = LLM_PROVIDERS
OLLAMA_DEFAULT = "http://localhost:11434/v1"
KEY_UNREADABLE = (
    "The saved model key cannot be read with this installation's SECRET_KEY. "
    "Enter the key again under Administration -> Model."
)


class UnreadableKey(ValueError):
    """The organisation's saved provider key was encrypted with a different SECRET_KEY."""


@dataclass
class LLMConfig:
    provider: str
    model: str
    base_url: str = ""
    api_key: str = ""
    fallback_model: str = ""
    price_in: float = 3.0
    price_out: float = 15.0
    source: str = "environment"
    key_error: str = ""  # set only by a tolerant load: why the saved key could not be used


@dataclass
class LLMClient:
    """A provider bound to one organisation's model, fallback and prices."""

    provider: LLMProvider
    config: LLMConfig

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec], max_tokens: int | None = None
    ) -> tuple[LLMResponse, Decimal]:
        response = await call_with_retry(
            self.provider,
            messages,
            tools,
            model=self.config.model,
            max_tokens=max_tokens or get_settings().llm_max_output_tokens,
            fallback_model=self.config.fallback_model or None,
        )
        return response, cost_usd(response.usage, self.config.price_in, self.config.price_out)


_providers: dict[str, LLMProvider] = {}
_override: LLMProvider | None = None


def set_override(provider: LLMProvider | None) -> None:
    """Tests and load runs swap in a stub for every organisation."""
    global _override
    _override = provider


def build_provider(config: LLMConfig) -> LLMProvider:
    """One provider instance (and so one HTTP connection pool) per distinct endpoint and key."""
    fingerprint = hashlib.sha256(f"{config.provider}|{config.base_url}|{config.api_key}".encode()).hexdigest()
    if fingerprint not in _providers:
        if config.provider == "anthropic":
            _providers[fingerprint] = AnthropicProvider(config.api_key, config.base_url)
        elif config.provider == "ollama":
            _providers[fingerprint] = OpenAICompatProvider(config.base_url or OLLAMA_DEFAULT, config.api_key)
        elif config.provider == "openai_compat":
            if not config.base_url:
                raise ValueError("LLM_BASE_URL is required for an OpenAI-compatible provider.")
            _providers[fingerprint] = OpenAICompatProvider(config.base_url, config.api_key)
        else:
            module, _, attribute = get_settings().stub_responder.partition(":")
            _providers[fingerprint] = StubProvider(responder=getattr(importlib.import_module(module), attribute))
    return _providers[fingerprint]


def environment_config() -> LLMConfig:
    s = get_settings()
    return LLMConfig(
        provider=s.llm_provider,  # validated at startup, see app.config
        model=s.llm_model or "stub",
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        fallback_model=s.llm_fallback_model,
        price_in=s.llm_price_input_per_mtok,
        price_out=s.llm_price_output_per_mtok,
    )


async def load_config(org_id: UUID, *, strict: bool = True) -> LLMConfig:
    """The organisation's settings. A saved key that cannot be decrypted raises UnreadableKey, unless `strict` is
    off, in which case the settings are returned without the key and with the reason in `key_error`."""
    async with tenant_session(org_id) as db:
        row = await db.get(LLMSettings, org_id)
    if row is None:
        return environment_config()
    api_key, key_error = "", ""
    if row.api_key_enc:
        try:
            api_key = decrypt(row.api_key_enc)
        except ValueError as exc:
            if strict:
                raise UnreadableKey(KEY_UNREADABLE) from exc
            key_error = KEY_UNREADABLE
    return LLMConfig(
        provider=row.provider,
        model=row.model,
        base_url=row.base_url,
        api_key=api_key,
        key_error=key_error,
        fallback_model=row.fallback_model,
        price_in=float(row.price_input_per_mtok),
        price_out=float(row.price_output_per_mtok),
        source="organisation",
    )


async def get_client(org_id: UUID) -> LLMClient:
    config = await load_config(org_id)
    if _override is not None:
        return LLMClient(_override, config)
    if config.base_url:
        await asyncio.to_thread(validate_base_url, config.base_url)
    return LLMClient(build_provider(config), config)
