from __future__ import annotations

from sq_bi_runtime.config import LLMConfig
from sq_bi_runtime.llm_client import OpenAICompatClient, parse_json_payload


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "{\"ok\":true}"}}]}


class _FakeHttpClient:
    instances: list["_FakeHttpClient"] = []

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self.closed = False
        self.posts: list[dict] = []
        self.instances.append(self)

    def post(self, url: str, *, headers: dict, json: dict, timeout: float) -> _FakeResponse:
        self.posts.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _FakeResponse()

    def close(self) -> None:
        self.closed = True


def test_llm_client_reuses_http_client_until_config_changes(monkeypatch) -> None:
    _FakeHttpClient.instances = []
    monkeypatch.setattr("sq_bi_runtime.llm_client.httpx.Client", _FakeHttpClient)

    client = OpenAICompatClient(
        LLMConfig(base_url="https://llm.example.com/v1", api_key="key-1", model="model-a", timeout_seconds=10)
    )

    client.chat("system", "user")
    client.chat("system", "user")

    assert len(_FakeHttpClient.instances) == 1
    assert len(_FakeHttpClient.instances[0].posts) == 2

    client.config = LLMConfig(
        base_url="https://llm-2.example.com/v1",
        api_key="key-2",
        model="model-b",
        timeout_seconds=20,
    )
    client.chat("system", "user")

    assert len(_FakeHttpClient.instances) == 2
    assert _FakeHttpClient.instances[0].closed is True
    assert _FakeHttpClient.instances[1].timeout == 20

    client.close()
    assert _FakeHttpClient.instances[1].closed is True


def test_parse_json_payload_uses_first_valid_json_object() -> None:
    payload = parse_json_payload('{"sql":"select 1 from dual","intent":"query"}\n\n{"extra":true}')

    assert payload == {"sql": "select 1 from dual", "intent": "query"}


def test_parse_json_payload_accepts_markdown_wrapped_json() -> None:
    payload = parse_json_payload('```json\n{"sql":"select 1 from dual"}\n```\n解释：已生成 SQL')

    assert payload == {"sql": "select 1 from dual"}
