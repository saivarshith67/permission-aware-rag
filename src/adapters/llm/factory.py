"""LLM factory — create chat models for OpenAI, OpenRouter, or Gemini."""

from __future__ import annotations

import os
from typing import Any, Optional


class LLMFactory:
    """Build a LangChain chat model from env / explicit args.

    Providers:
      - openai     → ChatOpenAI (default: gpt-4o-mini)
      - openrouter → ChatOpenAI via OpenRouter (default: openai/gpt-4o-mini)
      - gemini     → ChatGoogleGenerativeAI (default: gemini-3.6-flash)
    """

    SUPPORTED = ("openai", "openrouter", "gemini")

    @classmethod
    def create(
        cls,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
        **kwargs: Any,
    ):
        provider = (provider or os.getenv("LLM_PROVIDER", "openai")).strip().lower()
        if provider not in cls.SUPPORTED:
            raise ValueError(
                f"Unsupported LLM provider '{provider}'. Choose one of: {', '.join(cls.SUPPORTED)}"
            )

        if provider == "openai":
            return cls._create_openai(model=model, temperature=temperature, **kwargs)
        if provider == "openrouter":
            return cls._create_openrouter(model=model, temperature=temperature, **kwargs)
        return cls._create_gemini(model=model, temperature=temperature, **kwargs)

    @staticmethod
    def _create_openai(model: Optional[str], temperature: float, **kwargs: Any):
        from langchain_openai import ChatOpenAI

        api_key = kwargs.pop("api_key", None) or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")

        model_name = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            api_key=api_key,
            **kwargs,
        )

    @staticmethod
    def _create_openrouter(model: Optional[str], temperature: float, **kwargs: Any):
        from langchain_openai import ChatOpenAI

        api_key = kwargs.pop("api_key", None) or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter")

        model_name = model or os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
        base_url = kwargs.pop(
            "base_url",
            os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        )

        # Optional OpenRouter attribution headers
        default_headers = {}
        referer = os.getenv("OPENROUTER_HTTP_REFERER")
        app_name = os.getenv("OPENROUTER_APP_NAME", "permission-aware-rag")
        if referer:
            default_headers["HTTP-Referer"] = referer
        if app_name:
            default_headers["X-Title"] = app_name

        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url,
            default_headers=default_headers or None,
            **kwargs,
        )

    @staticmethod
    def _create_gemini(model: Optional[str], temperature: float, **kwargs: Any):
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key = (
            kwargs.pop("api_key", None)
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY (or GEMINI_API_KEY) is required when LLM_PROVIDER=gemini"
            )

        model_name = model or os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=api_key,
            **kwargs,
        )
