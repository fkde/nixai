from __future__ import annotations

import socket

import httpx
import pytest

from app.config import SearchProviderSettings, Settings
from app.tools import internet
from app.tools.internet import (
    _DuckDuckGoParser,
    _PublicNetworkBackend,
    _normalize_search_result_url,
    _validate_public_url,
    fetch_url,
    search_web,
)


def test_validate_public_url_allows_public_ip_without_dns() -> None:
    assert _validate_public_url("https://8.8.8.8/dns-query") == "https://8.8.8.8/dns-query"


def test_validate_public_url_rejects_local_and_private_targets() -> None:
    blocked = [
        "http://localhost:8765",
        "http://service.localhost/path",
        "http://127.0.0.1",
        "http://10.0.0.5",
        "http://172.16.0.2",
        "http://192.168.1.10",
        "http://169.254.1.1",
        "http://[::1]/",
    ]

    for url in blocked:
        with pytest.raises(ValueError):
            _validate_public_url(url)


def test_validate_public_url_rejects_credentials_and_non_http() -> None:
    for url in ["https://user:pass@example.com", "ftp://example.com", "https:///missing"]:
        with pytest.raises(ValueError):
            _validate_public_url(url)


def test_normalize_search_result_url_unwraps_duckduckgo_redirect() -> None:
    href = "/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs&rut=abc"

    assert _normalize_search_result_url(href) == "https://example.com/docs"
    assert _normalize_search_result_url("mailto:test@example.com") == ""


def test_duckduckgo_parser_extracts_title_url_and_snippet() -> None:
    parser = _DuckDuckGoParser()
    parser.feed(
        """
        <a class="result__a" href="/l/?uddg=http%3A%2F%2F93.184.216.34%2Fdocs"> Example result </a>
        <a class="result__snippet"> Useful summary text. </a>
        """
    )

    assert parser.results == [
        {
            "title": " Example result ",
            "url": "/l/?uddg=http%3A%2F%2F93.184.216.34%2Fdocs",
            "snippet": " Useful summary text. ",
        }
    ]


def test_search_web_uses_duckduckgo_html_provider_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "duckduckgo.com"
        assert request.url.params["q"] == "nix ai"
        html = """
        <a class="result__a" href="/l/?uddg=http%3A%2F%2F93.184.216.34%2Fdocs"> Example result </a>
        <a class="result__snippet"> Useful summary text. </a>
        <a class="result__a" href="http://127.0.0.1/private"> Private result </a>
        """
        return httpx.Response(200, request=request, text=html)

    def make_client() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    monkeypatch.setattr(internet, "_make_public_client", make_client)
    monkeypatch.setattr(internet, "load_settings", lambda: Settings(search_provider=SearchProviderSettings()))

    def fake_resolve_public_ips(host: str) -> list[str]:
        if host == "127.0.0.1":
            raise ValueError("Private, loopback, link-local, multicast, and reserved addresses are not allowed.")
        return ["93.184.216.34"]

    monkeypatch.setattr(internet, "_resolve_public_ips", fake_resolve_public_ips)

    payload = search_web("  nix   ai  ", limit=5)

    assert payload["success"] is True
    assert payload["query"] == "nix ai"
    assert payload["url"] == "https://duckduckgo.com/html/?q=nix+ai"
    assert payload["results"] == [
        {"title": "Example result", "url": "http://93.184.216.34/docs", "snippet": "Useful summary text."}
    ]


def test_search_web_uses_configured_json_api_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://93.184.216.34/search?query=nix+ai&count=2"
        assert request.headers["x-search-key"] == "secret"
        return httpx.Response(
            200,
            request=request,
            json={
                "items": [
                    {"title": "First", "url": "http://93.184.216.34/one", "snippet": "One."},
                    {"name": "Second", "link": "http://93.184.216.34/two", "description": "Two."},
                    {"title": "Private", "url": "http://127.0.0.1/private", "snippet": "Nope."},
                ]
            },
        )

    def make_client() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    settings = Settings(
        search_provider=SearchProviderSettings(
            provider="json_api",
            endpoint_url="https://93.184.216.34/search",
            api_key="secret",
            api_key_header="X-Search-Key",
            query_param="query",
            limit_param="count",
            results_path="items",
        )
    )
    monkeypatch.setattr(internet, "_make_public_client", make_client)
    monkeypatch.setattr(internet, "load_settings", lambda: settings)

    payload = search_web("nix ai", limit=2)

    assert payload["url"] == "https://93.184.216.34/search?query=nix+ai&count=2"
    assert payload["results"] == [
        {"title": "First", "url": "http://93.184.216.34/one", "snippet": "One."},
        {"title": "Second", "url": "http://93.184.216.34/two", "snippet": "Two."},
    ]


def test_fetch_url_rejects_redirect_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    def make_client() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    monkeypatch.setattr(internet, "_make_public_client", make_client)

    with pytest.raises(ValueError, match="Localhost|Private"):
        fetch_url("http://93.184.216.34/start")


def test_fetch_url_rejects_redirect_to_link_local(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        return httpx.Response(301, headers={"location": "http://169.254.169.254/latest/meta-data"})

    def make_client() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    monkeypatch.setattr(internet, "_make_public_client", make_client)

    with pytest.raises(ValueError, match="Private"):
        fetch_url("http://93.184.216.34/start")


def test_public_network_backend_connects_to_validated_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    connected_addresses = []

    class FakeSocket:
        def setsockopt(self, *args: object) -> None:
            return None

    def fake_getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple[object, ...]]:
        assert host == "example.com"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    def fake_create_connection(
        address: tuple[str, int],
        timeout: float | None = None,
        source_address: tuple[str, int] | None = None,
    ) -> FakeSocket:
        connected_addresses.append(address)
        return FakeSocket()

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", fake_create_connection)

    _PublicNetworkBackend().connect_tcp("example.com", 443)

    assert connected_addresses == [("93.184.216.34", 443)]


def test_public_network_backend_rejects_rebound_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple[object, ...]]:
        assert host == "example.com"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    def fake_create_connection(*args: object, **kwargs: object) -> object:
        raise AssertionError("private rebound IP must not be used for a connection")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", fake_create_connection)

    with pytest.raises(ValueError, match="Private"):
        _PublicNetworkBackend().connect_tcp("example.com", 443)
