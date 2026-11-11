"""LLM Client abstraction for IncidentForge."""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from .models import Incident, GenerationTask


@dataclass
class LLMConfig:
    """Configuration for LLM client."""

    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    timeout: float = 60.0
    max_retries: int = 3
    temperature: float = 0.7
    top_p: float = 0.95
    max_tokens: int = 4000
    use_structured_output: bool = True  # Use response_format if supported


class LLMResponse(BaseModel):
    """Response from LLM."""

    content: str
    usage: dict[str, int] | None = None
    model: str | None = None
    finish_reason: str | None = None


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_format: dict | None = None,
        **kwargs
    ) -> LLMResponse:
        """Generate a response from the LLM."""
        pass

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        system_prompt: str | None,
        schema: dict,
        **kwargs
    ) -> LLMResponse:
        """Generate a structured response conforming to JSON schema."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the client."""
        pass


class OpenAICompatibleClient(LLMClient):
    """OpenAI-compatible client using the official SDK."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        """Lazy-initialize the client."""
        if self._client is None:
            api_key = self.config.api_key or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError(
                    "API key not provided. Set OPENAI_API_KEY environment variable "
                    "or pass api_key in config."
                )
            self._client = AsyncOpenAI(
                base_url=self.config.base_url,
                api_key=api_key,
                timeout=self.config.timeout,
                max_retries=self.config.max_retries,
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_format: dict | None = None,
        **kwargs
    ) -> LLMResponse:
        """Generate a response from the LLM."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        params = {
            "model": self.config.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }

        if response_format and self.config.use_structured_output:
            params["response_format"] = response_format

        response = await self.client.chat.completions.create(**params)

        choice = response.choices[0]
        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=choice.message.content or "",
            usage=usage,
            model=response.model,
            finish_reason=choice.finish_reason,
        )

    async def generate_structured(
        self,
        prompt: str,
        system_prompt: str | None,
        schema: dict,
        **kwargs
    ) -> LLMResponse:
        """Generate a structured response using JSON schema."""
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "incident",
                "schema": schema,
                "strict": True,
            },
        }
        return await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            response_format=response_format,
            **kwargs
        )

    async def close(self) -> None:
        """Close the client."""
        if self._client:
            await self._client.close()
            self._client = None


class HTTPXClient(LLMClient):
    """Fallback client using httpx for non-OpenAI-compatible endpoints."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-initialize the client."""
        if self._client is None:
            api_key = self.config.api_key or os.getenv("OPENAI_API_KEY")
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers=headers,
                timeout=self.config.timeout,
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_format: dict | None = None,
        **kwargs
    ) -> LLMResponse:
        """Generate a response using raw HTTP."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "top_p": kwargs.get("top_p", self.config.top_p),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "stream": False,
        }

        if response_format and self.config.use_structured_output:
            payload["response_format"] = response_format

        response = await self.client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        usage = data.get("usage")

        return LLMResponse(
            content=choice["message"]["content"] or "",
            usage=usage,
            model=data.get("model"),
            finish_reason=choice.get("finish_reason"),
        )

    async def generate_structured(
        self,
        prompt: str,
        system_prompt: str | None,
        schema: dict,
        **kwargs
    ) -> LLMResponse:
        """Generate structured response with JSON schema."""
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "incident",
                "schema": schema,
                "strict": True,
            },
        }
        return await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            response_format=response_format,
            **kwargs
        )

    async def close(self) -> None:
        """Close the client."""
        if self._client:
            await self._client.aclose()
            self._client = None


class TolerantJSONParser:
    """Parse JSON from LLM responses tolerantly."""

    @staticmethod
    def extract_json(text: str) -> dict | None:
        """
        Extract JSON from text, handling code fences and extra text.

        Args:
            text: Raw text from LLM.

        Returns:
            Parsed JSON dict or None if extraction fails.
        """
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON in code fences
        code_fence_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
        matches = re.findall(code_fence_pattern, text, re.DOTALL)
        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

        # Try to find JSON object in text
        # Look for first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # Try to find JSON array
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        return None

    @staticmethod
    def parse_incident(text: str) -> Incident | None:
        """
        Parse incident from LLM response text.

        Args:
            text: Raw LLM response.

        Returns:
            Incident object or None if parsing fails.
        """
        data = TolerantJSONParser.extract_json(text)
        if data is None:
            return None

        try:
            return Incident.model_validate(data)
        except Exception:
            return None


def create_llm_client(config: LLMConfig) -> LLMClient:
    """
    Factory function to create LLM client.

    Args:
        config: LLM configuration.

    Returns:
        LLMClient instance.
    """
    # Use OpenAI SDK for OpenAI-compatible endpoints
    return OpenAICompatibleClient(config)


async def generate_incident(
    client: LLMClient,
    task: GenerationTask,
    prompt: str,
    system_prompt: str | None,
    schema: dict,
    use_structured: bool = True,
) -> tuple[Incident | None, LLMResponse | None, str | None]:
    """
    Generate an incident using the LLM client.

    Args:
        client: LLM client.
        task: Generation task.
        prompt: User prompt.
        system_prompt: System prompt.
        schema: JSON schema for structured output.
        use_structured: Whether to use structured output.

    Returns:
        Tuple of (Incident or None, LLMResponse or None, error message or None).
    """
    try:
        if use_structured:
            response = await client.generate_structured(
                prompt=prompt,
                system_prompt=system_prompt,
                schema=schema,
            )
        else:
            response = await client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
            )

        # Parse response
        incident = TolerantJSONParser.parse_incident(response.content)
        if incident is None:
            return None, response, "Failed to parse JSON from response"

        return incident, response, None

    except Exception as e:
        return None, None, str(e)


if __name__ == "__main__":
    import asyncio

    async def test():
        config = LLMConfig(
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
        )
        client = create_llm_client(config)

        try:
            response = await client.generate(
                prompt="Say hello in JSON format with a 'message' field",
                system_prompt="You are a helpful assistant that responds in JSON.",
            )
            print(f"Response: {response.content}")
            print(f"Usage: {response.usage}")
        finally:
            await client.close()

    asyncio.run(test())