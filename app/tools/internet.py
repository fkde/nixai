from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx


MAX_RESPONSE_CHARS = 120_000
TIMEOUT_SECONDS = 15.0


def fetch_url(url: str) -> dict[str, object]:
    safe_url = _validate_public_url(url)
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = client.get(safe_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ValueError(f"Web request failed: {exc}") from exc

    content_type = response.headers.get("content-type", "")
    text = response.text
    truncated = len(text) > MAX_RESPONSE_CHARS
    if truncated:
        text = text[:MAX_RESPONSE_CHARS].rstrip() + "\n...[response truncated]"

    return {
        "success": True,
        "status_code": response.status_code,
        "url": str(response.url),
        "content_type": content_type,
        "text": text,
        "truncated": truncated,
    }


def check_url(url: str) -> dict[str, object]:
    safe_url = _validate_public_url(url)
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = client.head(safe_url)
            if response.status_code == 405:
                response = client.get(safe_url, headers={"Range": "bytes=0-0"})
    except httpx.HTTPError as exc:
        raise ValueError(f"Web check failed: {exc}") from exc

    return {
        "success": True,
        "status_code": response.status_code,
        "url": str(response.url),
        "content_type": response.headers.get("content-type", ""),
        "content_length": response.headers.get("content-length", ""),
    }


def _validate_public_url(url: str) -> str:
    clean = str(url or "").strip()
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed.")
    if not parsed.hostname:
        raise ValueError("URL host is required.")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed.")

    host = parsed.hostname.strip().lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise ValueError("Localhost URLs are not allowed for internet tools.")

    _reject_private_host(host)
    return clean


def _reject_private_host(host: str) -> None:
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError(f"Could not resolve host: {host}") from exc
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]

    if any(_is_private_address(address) for address in addresses):
        raise ValueError("Private, loopback, link-local, multicast, and reserved addresses are not allowed.")


def _is_private_address(address: Any) -> bool:
    return any(
        [
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        ]
    )
