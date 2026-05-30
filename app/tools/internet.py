from __future__ import annotations

from abc import ABC, abstractmethod
from html.parser import HTMLParser
import ipaddress
import socket
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx
import httpcore
from httpcore._backends.sync import ConnectError, ConnectTimeout, SyncStream, map_exceptions

from app.config import SearchProviderSettings, load_settings


MAX_RESPONSE_CHARS = 120_000
MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 15.0
USER_AGENT = "NixAI/0.1 local research tool"


def fetch_url(url: str) -> dict[str, object]:
    try:
        with _make_public_client() as client:
            response = _request_public_url(client, "GET", url)
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
    try:
        with _make_public_client() as client:
            response = _request_public_url(client, "HEAD", url)
            if response.status_code == 405:
                response = _request_public_url(client, "GET", url, headers={"Range": "bytes=0-0"})
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
    try:
        with _make_public_client() as client:
            provider = _search_provider_from_settings(load_settings().search_provider, client)
            results = provider.search(clean_query, safe_limit)
    except httpx.HTTPError as exc:
        raise ValueError(f"Web search failed: {exc}") from exc

    return {"success": True, "query": clean_query, "url": provider.last_url, "results": results}


class SearchProvider(ABC):
    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.last_url = ""

    @abstractmethod
    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        raise NotImplementedError


class DuckDuckGoHtmlSearchProvider(SearchProvider):
    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        search_url = "https://duckduckgo.com/html/?" + urlencode({"q": query})
        response = _request_public_url(self.client, "GET", search_url)
        response.raise_for_status()
        self.last_url = str(response.url)

        parser = _DuckDuckGoParser()
        parser.feed(response.text)
        return _clean_search_results(parser.results, limit)


class JsonApiSearchProvider(SearchProvider):
    def __init__(self, client: httpx.Client, settings: SearchProviderSettings) -> None:
        super().__init__(client)
        self.settings = settings

    def search(self, query: str, limit: int) -> list[dict[str, str]]:
        if not self.settings.endpoint_url:
            raise ValueError("Search provider endpoint_url is required for json_api.")

        query_param = self.settings.query_param.strip() or "q"
        limit_param = self.settings.limit_param.strip() or "limit"
        params = {
            query_param: query,
            limit_param: str(limit),
        }
        api_key = self.settings.api_key.strip()
        api_key_param = self.settings.api_key_param.strip()
        api_key_header = self.settings.api_key_header.strip()
        if api_key and api_key_param:
            params[api_key_param] = api_key
        separator = "&" if urlparse(self.settings.endpoint_url).query else "?"
        url = self.settings.endpoint_url + separator + urlencode(params)
        headers = {}
        if api_key and api_key_header:
            headers[api_key_header] = api_key

        response = _request_public_url(self.client, "GET", url, headers=headers or None)
        response.raise_for_status()
        self.last_url = str(response.url)
        payload = response.json()
        raw_results = _extract_json_results(payload, self.settings.results_path.strip() or "results")
        return _clean_search_results(raw_results, limit)


def _search_provider_from_settings(settings: SearchProviderSettings, client: httpx.Client) -> SearchProvider:
    if settings.provider.strip().lower() == "json_api":
        return JsonApiSearchProvider(client, settings)
    return DuckDuckGoHtmlSearchProvider(client)


def _clean_search_results(items: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        url = _normalize_search_result_url(str(item.get("url", "")))
        try:
            url = _validate_public_url(url)
        except ValueError:
            continue
        title = " ".join(str(item.get("title") or "").split())
        snippet = " ".join(str(item.get("snippet") or "").split())
        if not url or not title or url in seen:
            continue
        seen.add(url)
        result: dict[str, str] = {"title": title[:220], "url": url}
        if snippet:
            result["snippet"] = snippet[:500]
        results.append(result)
        if len(results) >= limit:
            break
    return results


def _extract_json_results(payload: object, results_path: str) -> list[dict[str, str]]:
    current = payload
    for part in [item for item in results_path.split(".") if item]:
        if isinstance(current, dict):
            current = current.get(part, [])
        else:
            current = []
            break
    if isinstance(current, dict):
        current = current.get("results", [])
    if not isinstance(current, list):
        return []

    results = []
    for item in current:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": str(item.get("title") or item.get("name") or ""),
                "url": str(item.get("url") or item.get("link") or ""),
                "snippet": str(item.get("snippet") or item.get("description") or item.get("content") or ""),
            }
        )
    return results


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


def _make_public_client() -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
        transport=_PublicHTTPTransport(),
    )


def _request_public_url(
    client: httpx.Client, method: str, url: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    safe_url = _validate_public_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        response = client.request(method, safe_url, headers=headers)
        if not response.is_redirect:
            return response

        location = response.headers.get("location")
        if not location:
            return response

        redirect_url = urljoin(str(response.url), location)
        safe_url = _validate_public_url(redirect_url)

    raise ValueError(f"Too many redirects; maximum is {MAX_REDIRECTS}.")


class _PublicHTTPTransport(httpx.HTTPTransport):
    def __init__(self) -> None:
        ssl_context = httpx.create_ssl_context()
        limits = httpx.Limits()
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl_context,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_PublicNetworkBackend(),
        )


class _PublicNetworkBackend(httpcore.SyncBackend):
    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.NetworkStream:
        if socket_options is None:
            socket_options = []
        address = (_resolve_public_ips(host)[0], port)
        source_address = None if local_address is None else (local_address, 0)
        exc_map = {socket.timeout: ConnectTimeout, OSError: ConnectError}

        with map_exceptions(exc_map):
            sock = socket.create_connection(address, timeout, source_address=source_address)
            for option in socket_options:
                sock.setsockopt(*option)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return SyncStream(sock)


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
    _resolve_public_ips(host)


def _resolve_public_ips(host: str) -> list[str]:
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
    return [str(address) for address in addresses]


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
