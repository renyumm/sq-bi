from __future__ import annotations

import json
from time import sleep
from threading import Lock
from typing import Any

import httpx

from .config import LLMConfig


class OpenAICompatClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self._client: httpx.Client | None = None
        self._client_key: tuple[str, float] | None = None
        self._client_lock = Lock()

    def _config_key(self) -> tuple[str, float]:
        return (self.config.base_url, float(self.config.timeout_seconds))

    def _get_client(self) -> httpx.Client:
        key = self._config_key()
        if self._client is not None and self._client_key == key:
            return self._client
        with self._client_lock:
            if self._client is not None and self._client_key == key:
                return self._client
            if self._client is not None:
                self._client.close()
            self._client = httpx.Client(timeout=self.config.timeout_seconds)
            self._client_key = key
            return self._client

    def close(self) -> None:
        with self._client_lock:
            if self._client is not None:
                self._client.close()
            self._client = None
            self._client_key = None

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_format: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        url = f"{self.config.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if response_format is None:
            response_format = {"type": "json_object"}
        if response_format:
            payload["response_format"] = response_format
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(2):
            try:
                response = self._get_client().post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=timeout_seconds or self.config.timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
            except (httpx.ConnectError, httpx.RemoteProtocolError):
                if attempt == 1:
                    raise
                self.close()
                sleep(0.15)
            except httpx.HTTPStatusError as exc:
                if attempt == 1 or exc.response.status_code not in {429, 502, 503, 504}:
                    raise
                sleep(0.2)
        raise RuntimeError("LLM request retry loop ended unexpectedly.")


def parse_json_payload(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(payload, dict):
            raise ValueError("LLM JSON response must be an object.")
        return payload
    if last_error is not None:
        raise last_error
    raise json.JSONDecodeError("No JSON object found", text, 0)
