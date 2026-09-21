"""
LLM Provider abstraction.

Provides a clean, testable interface for calling an LLM without coupling
the rest of the application to any specific provider SDK.

Supported providers (selected via LLM_PROVIDER env var):
  - "openai"  → OpenAI Chat Completions (GPT-4o-mini or user-specified)
  - "gemini"  → Google Gemini via langchain-google-genai
  - "none"    → No LLM; always returns None so callers use their fallback

Design constraints
------------------
* The LLM is NEVER used for arithmetic, account lookups, or status decisions.
* It is ONLY used to produce natural-language explanations after all
  deterministic validation has completed.
* If the LLM is unavailable (no API key, network error, rate limit) the
  system MUST continue to work using the deterministic fallback explanation.
* API keys are read from environment variables — never hardcoded.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class LLMProvider:
    """
    Thin wrapper that normalises LLM calls across providers.

    Usage
    -----
    provider = LLMProvider.from_env()
    text = provider.complete(system_prompt, user_prompt)
    # text is None when provider == "none" or call fails
    """

    def __init__(self, provider: str, model: str) -> None:
        """
        Parameters
        ----------
        provider : str
            "openai", "gemini", or "none"
        model : str
            Model identifier, e.g. "gpt-4o-mini" or "gemini-2.0-flash"
        """
        self._provider = provider.strip().lower()
        self._model = model
        self._client = self._build_client()

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "LLMProvider":
        """
        Build a provider from environment variables.

        Reads:
          LLM_PROVIDER   (default "none")
          OPENAI_MODEL   (default "gpt-4o-mini")
          GEMINI_MODEL   (default "gemini-2.0-flash")
        """
        provider = os.getenv("LLM_PROVIDER", "none").strip().lower()

        if provider == "openai":
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        elif provider == "gemini":
            model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        else:
            provider = "none"
            model = "none"

        logger.info("LLM provider: %s / model: %s", provider, model)
        return cls(provider=provider, model=model)

    # ------------------------------------------------------------------
    # Client construction
    # ------------------------------------------------------------------

    def _build_client(self) -> object | None:
        if self._provider == "openai":
            return self._build_openai()
        if self._provider == "gemini":
            return self._build_gemini()
        return None  # "none" provider

    def _build_openai(self) -> object | None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            logger.warning(
                "LLM_PROVIDER=openai but OPENAI_API_KEY is not set. "
                "Falling back to deterministic explanations."
            )
            return None
        try:
            from openai import OpenAI  # type: ignore[import]
            return OpenAI(api_key=api_key)
        except ImportError:
            logger.warning("openai package not installed. pip install openai")
            return None

    def _build_gemini(self) -> object | None:
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            logger.warning(
                "LLM_PROVIDER=gemini but GOOGLE_API_KEY is not set. "
                "Falling back to deterministic explanations."
            )
            return None
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore[import]
            return ChatGoogleGenerativeAI(
                model=self._model,
                temperature=0.2,
                google_api_key=api_key,
            )
        except ImportError:
            logger.warning(
                "langchain-google-genai package not installed. "
                "pip install langchain-google-genai"
            )
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True if a live LLM client was successfully initialised."""
        return self._client is not None

    def complete(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        Send a chat completion request and return the response text.

        Returns None when:
          - provider == "none"
          - client failed to initialise
          - an API/network error occurs (logged as a warning)

        Callers should treat None as a signal to use their fallback.
        """
        if self._client is None:
            return None

        try:
            if self._provider == "openai":
                return self._call_openai(system_prompt, user_prompt)
            if self._provider == "gemini":
                return self._call_gemini(system_prompt, user_prompt)
        except Exception as exc:
            logger.warning("LLM call failed (%s): %s", self._provider, exc)

        return None

    # ------------------------------------------------------------------
    # Provider-specific call helpers
    # ------------------------------------------------------------------

    def _call_openai(self, system_prompt: str, user_prompt: str) -> str:
        from openai import OpenAI  # type: ignore[import]
        client: OpenAI = self._client  # type: ignore[assignment]
        response = client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=600,
        )
        return response.choices[0].message.content or ""

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        # langchain ChatGoogleGenerativeAI uses .invoke()
        llm = self._client
        messages = [
            ("system", system_prompt),
            ("human", user_prompt),
        ]
        result = llm.invoke(messages)  # type: ignore[union-attr]
        content = getattr(result, "content", str(result))
        return content or ""
