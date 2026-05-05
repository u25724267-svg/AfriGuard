"""
AfriGuard — Generation: ModelRouter

Abstraction layer over multiple LLM providers.
Primary: OpenAI (GPT-5.4)
Secondary: Anthropic, Google (configured via models.yaml)

Implements retry with exponential backoff via tenacity.
Tracks token usage for cost management.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import yaml
import structlog
from tenacity import (
    retry,
    RetryCallState,
    retry_if_exception_type,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.config.env import load_project_env

load_project_env()
logger = structlog.get_logger(__name__)

_MODELS_PATH = Path(__file__).parent.parent.parent / "configs" / "models.yaml"

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------
_MAX_ATTEMPTS = 5
_WAIT_MIN_SECONDS = 2
_WAIT_MAX_SECONDS = 60


def _load_model_configs() -> dict[str, Any]:
    with open(_MODELS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("models", {})


def _is_gpt5_family(model_name: str) -> bool:
    return model_name.startswith("gpt-5")


def _is_retryable_exception(exc: BaseException) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {400, 401, 403, 404}:
        return False
    return True


def _log_retry(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "model_router.retrying",
        attempt=retry_state.attempt_number,
        error=str(exc) if exc else None,
    )


class LLMResponse:
    """Standardized response object returned by all providers."""

    def __init__(
        self,
        text: str,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        raw: Any = None,
    ):
        self.text = text
        self.model_id = model_id
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.cost_usd = cost_usd
        self.raw = raw


class ModelRouter:
    """
    Routes generation requests to the appropriate LLM provider.

    Usage:
        router = ModelRouter()
        response = router.generate(
            model_id="gpt-5.4",
            system_prompt="...",
            user_message="...",
        )
    """

    def __init__(self, models_path: Path = _MODELS_PATH):
        self._configs = _load_model_configs()
        self._openai_client = None
        self._anthropic_client = None

    def _get_openai(self):
        if self._openai_client is None:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            except ImportError:
                raise ImportError("Install openai: pip install openai")
        return self._openai_client

    def _get_anthropic(self):
        if self._anthropic_client is None:
            try:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(
                    api_key=os.environ.get("ANTHROPIC_API_KEY")
                )
            except ImportError:
                raise ImportError("Install anthropic: pip install anthropic")
        return self._anthropic_client

    def generate(
        self,
        model_id: str,
        system_prompt: str,
        user_message: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Generate a completion from the specified model.

        Args:
            model_id:      Model identifier from models.yaml
            system_prompt: System prompt string
            user_message:  User turn message
            temperature:   Override model default temperature
            max_tokens:    Override model default max_tokens

        Returns:
            LLMResponse with text, token counts, and cost.
        """
        config = self._configs.get(model_id)
        if config is None:
            raise ValueError(f"Unknown model_id: {model_id}. Check configs/models.yaml.")

        provider = config["provider"]
        actual_temp = temperature if temperature is not None else config.get("temperature", 0.9)
        actual_max = max_tokens if max_tokens is not None else config.get("max_tokens", 1024)

        logger.debug("model_router.generating", model=model_id, provider=provider)

        if provider == "openai":
            return self._generate_openai(config, model_id, system_prompt, user_message, actual_temp, actual_max)
        elif provider == "anthropic":
            return self._generate_anthropic(config, model_id, system_prompt, user_message, actual_temp, actual_max)
        elif provider == "google":
            return self._generate_google(config, model_id, system_prompt, user_message, actual_temp, actual_max)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def _compute_cost(self, config: dict, prompt_tokens: int, completion_tokens: int) -> float:
        input_cost = config.get("cost_per_1k_input_tokens", 0.0) * prompt_tokens / 1000
        output_cost = config.get("cost_per_1k_output_tokens", 0.0) * completion_tokens / 1000
        return round(input_cost + output_cost, 6)

    @retry(
        retry=retry_if_exception(_is_retryable_exception),
        wait=wait_exponential(multiplier=1, min=_WAIT_MIN_SECONDS, max=_WAIT_MAX_SECONDS),
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        before_sleep=_log_retry,
        reraise=True,
    )
    def _generate_openai(
        self,
        config: dict,
        model_id: str,
        system_prompt: str,
        user_message: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        client = self._get_openai()
        api_model = config["model_id"]
        messages = [
            {"role": "developer" if _is_gpt5_family(api_model) else "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        request: dict[str, Any] = {
            "model": api_model,
            "messages": messages,
        }
        if _is_gpt5_family(api_model):
            request["max_completion_tokens"] = max_tokens
            if config.get("reasoning_effort"):
                request["reasoning_effort"] = config["reasoning_effort"]
        else:
            request.update(
                {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "frequency_penalty": config.get("frequency_penalty", 0.3),
                }
            )

        try:
            response = client.chat.completions.create(**request)
        except Exception as e:
            logger.error(
                "model_router.openai_error",
                model=model_id,
                api_model=api_model,
                status_code=getattr(e, "status_code", None),
                error=str(e),
            )
            raise
        text = response.choices[0].message.content or ""
        pt = response.usage.prompt_tokens if response.usage else 0
        ct = response.usage.completion_tokens if response.usage else 0
        cost = self._compute_cost(config, pt, ct)

        logger.debug(
            "model_router.openai_response",
            model=model_id,
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_usd=cost,
        )
        return LLMResponse(
            text=text.strip(),
            model_id=model_id,
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_usd=cost,
            raw=response,
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=_WAIT_MIN_SECONDS, max=_WAIT_MAX_SECONDS),
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        reraise=True,
    )
    def _generate_anthropic(
        self,
        config: dict,
        model_id: str,
        system_prompt: str,
        user_message: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        client = self._get_anthropic()
        response = client.messages.create(
            model=config["model_id"],
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        text = response.content[0].text if response.content else ""
        pt = response.usage.input_tokens if response.usage else 0
        ct = response.usage.output_tokens if response.usage else 0
        cost = self._compute_cost(config, pt, ct)
        return LLMResponse(text=text.strip(), model_id=model_id, prompt_tokens=pt, completion_tokens=ct, cost_usd=cost)

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=_WAIT_MIN_SECONDS, max=_WAIT_MAX_SECONDS),
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        reraise=True,
    )
    def _generate_google(
        self,
        config: dict,
        model_id: str,
        system_prompt: str,
        user_message: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("Install google-generativeai: pip install google-generativeai")

        genai.configure(api_key=os.environ.get("GOOGLE_API_KEY", ""))
        model = genai.GenerativeModel(
            model_name=config["model_id"],
            system_instruction=system_prompt,
        )
        gen_config = genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        response = model.generate_content(user_message, generation_config=gen_config)
        text = response.text or ""
        # Google doesn't always expose token counts; estimate
        pt = getattr(response.usage_metadata, "prompt_token_count", 0)
        ct = getattr(response.usage_metadata, "candidates_token_count", 0)
        cost = self._compute_cost(config, pt, ct)
        return LLMResponse(text=text.strip(), model_id=model_id, prompt_tokens=pt, completion_tokens=ct, cost_usd=cost)
