"""Provider adapters propagate outages; hosted calls never fall back to fake success."""

import abc
import logging
import time

import httpx
from app.core.config import settings
from worker.core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)
provider_circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout_seconds=60)


class ModelUnavailable(RuntimeError):
    pass


class ModelAdapter(abc.ABC):
    @abc.abstractmethod
    async def generate_response(self, messages, tools=None, temperature=0):
        pass


async def request_completion(url, payload, headers, provider, timeout):
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            if not isinstance(message.get("content"), str) or not message["content"].strip():
                raise ValueError("Empty completion")
            usage = data.get("usage", {})
            return dict(
                content=message["content"],
                tool_calls=message.get("tool_calls"),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                duration_seconds=time.monotonic() - start,
                provider=provider,
            )
    except Exception as exc:
        # Exception text/provider bodies can contain private prompt data or credentials.
        logger.warning("Model call unavailable (%s)", type(exc).__name__)
        raise ModelUnavailable(
            "Model service unavailable; no automated determination was generated."
        ) from None


class DelayedStubAdapter(ModelAdapter):
    def __init__(self, stub_url=None, delay_seconds=None):
        self.stub_url = stub_url or settings.STUB_SERVICE_URL
        self.delay_seconds = settings.STUB_DELAY_SECONDS if delay_seconds is None else delay_seconds

    async def generate_response(self, messages, tools=None, temperature=0):
        return await request_completion(
            f"{self.stub_url}/chat/completions",
            dict(messages=messages, tools=tools, temperature=temperature),
            {},
            "delayed-stub",
            self.delay_seconds + 5,
        )


class HostedProviderAdapter(ModelAdapter):
    def __init__(self, api_key=None, base_url=None, model_name=None):
        self.api_key = api_key or settings.LLM_API_KEY
        self.base_url = base_url or settings.LLM_BASE_URL
        self.model_name = model_name or settings.LLM_MODEL_NAME

    async def generate_response(self, messages, tools=None, temperature=0):
        if not all((self.api_key, self.base_url, self.model_name)):
            raise ModelUnavailable("Hosted model configuration is incomplete.")
        provider_circuit_breaker.check_state()
        payload = dict(model=self.model_name, messages=messages, temperature=temperature)
        if tools:
            payload["tools"] = tools
        try:
            result = await request_completion(
                f"{self.base_url.rstrip('/')}/chat/completions",
                payload,
                {"Authorization": f"Bearer {self.api_key}"},
                "hosted-provider",
                12,
            )
        except ModelUnavailable:
            provider_circuit_breaker.record_failure()
            raise
        provider_circuit_breaker.record_success()
        return result


class OllamaAdapter(ModelAdapter):
    """Use local Ollama's native JSON chat API without hosted credentials."""

    def __init__(self, base_url=None, model_name=None):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model_name = model_name or settings.LLM_MODEL_NAME

    async def generate_response(self, messages, tools=None, temperature=0, response_schema=None):
        if not self.model_name:
            raise ModelUnavailable("Configure LLM_MODEL_NAME with an installed Ollama model.")
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "think": settings.OLLAMA_THINK,
            "format": response_schema or "json",
            "options": {
                "temperature": temperature,
                "num_predict": settings.OLLAMA_MAX_OUTPUT_TOKENS,
                "num_ctx": settings.OLLAMA_CONTEXT_TOKENS,
            },
            "keep_alive": "5m",
        }
        if tools:
            payload["tools"] = tools
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=settings.OLLAMA_TIMEOUT_SECONDS) as client:
                response = await client.post(f"{self.base_url.rstrip('/')}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
            content = data["message"]["content"]
            if (
                data.get("prompt_eval_count", 0)
                >= settings.OLLAMA_CONTEXT_TOKENS - settings.OLLAMA_MAX_OUTPUT_TOKENS - 256
            ):
                raise ValueError("Evidence context may have been truncated")
            if data.get("done") is not True or not isinstance(content, str) or not content.strip():
                raise ValueError("Incomplete local model response")
            return {
                "content": content,
                "tool_calls": data["message"].get("tool_calls"),
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "duration_seconds": time.monotonic() - start,
                "provider": "ollama-local",
            }
        except Exception as exc:
            logger.warning("Local Ollama unavailable (%s)", type(exc).__name__)
            raise ModelUnavailable(
                "Local Ollama is unavailable or the model could not finish. Check Ollama and the installed model."
            ) from None


def get_model_adapter():
    if settings.LLM_PROVIDER == "ollama":
        return OllamaAdapter()
    if settings.LLM_PROVIDER == "hosted":
        return HostedProviderAdapter()
    if settings.LLM_PROVIDER == "stub":
        return DelayedStubAdapter()
    raise ModelUnavailable("Unknown model provider configuration.")
