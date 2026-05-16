from __future__ import annotations

import pytest

from app.tools.internet import _normalize_search_result_url, _validate_public_url


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
