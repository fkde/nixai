from __future__ import annotations

from html.parser import HTMLParser
import ipaddress
import socket
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx


MAX_RESPONSE_CHARS = 120_000
TIMEOUT_SECONDS = 15.0
USER_AGENT = "NixAI/0.1 local research tool"


def fetch_url(url: str) -> dict[str, object]:
    safe_url = _validate_public_url(url)
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
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
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
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


def search_web(query: str, limit: int = 5) -> dict[str, object]:
    clean_query = " ".join(str(query or "").strip().split())
    if not clean_query:
        raise ValueError("Search query is required.")

    safe_limit = max(1, min(int(limit or 5), 10))
    search_url = "https://duckduckgo.com/html/?" + urlencode({"q": clean_query})
    safe_url = _validate_public_url(search_url)
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(safe_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ValueError(f"Web search failed: {exc}") from exc

    parser = _DuckDuckGoParser()
    parser.feed(response.text)
    results = []
    seen: set[str] = set()
    for item in parser.results:
        url = _normalize_search_result_url(item.get("url", ""))
        title = " ".join(str(item.get("title") or "").split())
        snippet = " ".join(str(item.get("snippet") or "").split())
        if not url or not title or url in seen:
            continue
        seen.add(url)
        result = {"title": title[:220], "url": url}
        if snippet:
            result["snippet"] = snippet[:500]
        results.append(result)
        if len(results) >= safe_limit:
            break

    return {
        "success": True,
        "query": clean_query,
        "url": str(response.url),
        "results": results,
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


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._active_href = ""
        self._active_kind = ""
        self._active_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        class_name = values.get("class", "")
        if tag == "a" and ("result__a" in class_name or "result-link" in class_name):
            self._active_href = values.get("href", "")
            self._active_kind = "title"
            self._active_text = []
        elif "result__snippet" in class_name:
            self._active_href = ""
            self._active_kind = "snippet"
            self._active_text = []

    def handle_data(self, data: str) -> None:
        if self._active_kind:
            self._active_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._active_kind == "title" and tag == "a" and self._active_href:
            self.results.append({"title": "".join(self._active_text), "url": self._active_href, "snippet": ""})
            self._active_href = ""
            self._active_kind = ""
            self._active_text = []
            return
        if self._active_kind == "snippet" and tag in {"div", "a"}:
            if self.results:
                self.results[-1]["snippet"] = "".join(self._active_text)
            self._active_kind = ""
            self._active_text = []


def _normalize_search_result_url(href: str) -> str:
    clean = str(href or "").strip()
    if not clean:
        return ""
    if clean.startswith("//"):
        clean = "https:" + clean
    elif clean.startswith("/"):
        clean = urljoin("https://duckduckgo.com", clean)

    parsed = urlparse(clean)
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        clean = query["uddg"][0]
    if urlparse(clean).scheme not in {"http", "https"}:
        return ""
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
