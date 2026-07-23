import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from inspire_flow_backend.services.agent.contracts import (
    AgentToolError,
    AgentToolSettings,
    FetchResponse,
    HostResolver,
)

_ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/xhtml+xml",
    "text/html",
    "text/plain",
}
_ALLOWED_PORTS = {80, 443}
_HTML_CONTENT_TYPES = {"application/xhtml+xml", "text/html"}
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_FETCH_UNAVAILABLE_MESSAGE = "Webpage fetch unavailable"


async def resolve_hostname(hostname: str) -> set[str]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(
        hostname,
        None,
        type=socket.SOCK_STREAM,
    )
    return {record[4][0] for record in records}


async def validate_public_url(
    url: str,
    resolver: HostResolver,
) -> str:
    candidate = url.strip()
    if (
        not candidate
        or "\\" in candidate
        or any(character.isspace() or ord(character) < 32 for character in candidate)
    ):
        raise _invalid_url()

    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise _invalid_url() from error

    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        raise _invalid_url()
    if parsed.username is not None or parsed.password is not None:
        raise _unsafe_url()
    if port is not None and port not in _ALLOWED_PORTS:
        raise _unsafe_url()

    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            addresses = await resolver(hostname)
        except (OSError, TimeoutError) as error:
            raise _fetch_unavailable() from error
    else:
        addresses = {str(literal_address)}

    if not addresses or not _addresses_are_global(addresses):
        raise _unsafe_url()

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.query,
            "",
        )
    )


class WebPageFetcher:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: AgentToolSettings,
        *,
        resolver: HostResolver = resolve_hostname,
    ) -> None:
        self._http_client = http_client
        self._settings = settings
        self._resolver = resolver

    async def fetch(self, url: str) -> FetchResponse:
        current_url = url
        redirect_count = 0

        while True:
            current_url = await validate_public_url(current_url, self._resolver)
            try:
                async with self._http_client.stream(
                    "GET",
                    current_url,
                    headers={"User-Agent": self._settings.user_agent},
                    timeout=self._settings.request_timeout_seconds,
                    follow_redirects=False,
                ) as response:
                    if response.status_code in _REDIRECT_STATUS_CODES:
                        location = response.headers.get("Location")
                        if not location:
                            raise _fetch_unavailable()
                        if redirect_count >= self._settings.max_redirects:
                            raise AgentToolError(
                                "redirect_limit",
                                "Webpage redirect limit exceeded",
                            )
                        redirect_count += 1
                        current_url = urljoin(current_url, location)
                        continue

                    if not response.is_success:
                        raise _fetch_unavailable()

                    content_type = _response_content_type(response)
                    if content_type not in _ALLOWED_CONTENT_TYPES:
                        raise AgentToolError(
                            "unsupported_content_type",
                            "Webpage content type is not supported",
                        )
                    body = await _read_bounded_body(
                        response,
                        self._settings.max_fetch_response_bytes,
                    )
                    encoding = response.charset_encoding or "utf-8"
            except AgentToolError:
                raise
            except httpx.HTTPError as error:
                raise _fetch_unavailable() from error

            text, title = _extract_text(body, content_type, encoding)
            truncated = len(text) > self._settings.max_fetch_output_characters
            if truncated:
                text = text[: self._settings.max_fetch_output_characters]
            return FetchResponse(
                url=current_url,
                content_type=content_type,
                title=title,
                text=text,
                truncated=truncated,
            )


async def _read_bounded_body(
    response: httpx.Response,
    maximum_bytes: int,
) -> bytes:
    chunks: list[bytes] = []
    byte_count = 0
    async for chunk in response.aiter_bytes():
        byte_count += len(chunk)
        if byte_count > maximum_bytes:
            raise AgentToolError(
                "response_too_large",
                "Webpage response is too large",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _addresses_are_global(addresses: set[str]) -> bool:
    try:
        parsed_addresses = [ipaddress.ip_address(address) for address in addresses]
    except ValueError:
        return False
    return all(
        address.is_global
        and not address.is_link_local
        and not address.is_loopback
        and not address.is_multicast
        and not address.is_private
        and not address.is_reserved
        and not address.is_unspecified
        and not getattr(address, "is_site_local", False)
        for address in parsed_addresses
    )


def _response_content_type(response: httpx.Response) -> str:
    return response.headers.get("Content-Type", "").partition(";")[0].strip().lower()


def _extract_text(
    body: bytes,
    content_type: str,
    encoding: str,
) -> tuple[str, str | None]:
    try:
        decoded = body.decode(encoding, errors="replace")
    except LookupError:
        decoded = body.decode("utf-8", errors="replace")
    if content_type not in _HTML_CONTENT_TYPES:
        return decoded.strip(), None

    parser = _ReadableHtmlParser()
    parser.feed(decoded)
    parser.close()
    return _normalize_text("".join(parser.text_parts)), _optional_normalized_text(
        "".join(parser.title_parts)
    )


class _ReadableHtmlParser(HTMLParser):
    _BLOCKED_TAGS = {"noscript", "script", "style", "svg", "template"}
    _SEPARATOR_TAGS = {
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "p",
        "section",
        "td",
        "th",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []
        self._blocked_depth = 0
        self._head_depth = 0
        self._title_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag in self._BLOCKED_TAGS:
            self._blocked_depth += 1
            return
        if self._blocked_depth:
            return
        if tag == "head":
            self._head_depth += 1
        elif tag == "title":
            self._title_depth += 1
        elif not self._head_depth and tag in self._SEPARATOR_TAGS:
            self.text_parts.append(" ")

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCKED_TAGS:
            if self._blocked_depth:
                self._blocked_depth -= 1
            return
        if self._blocked_depth:
            return
        if tag == "title":
            self._title_depth = max(0, self._title_depth - 1)
        elif tag == "head":
            self._head_depth = max(0, self._head_depth - 1)
        elif not self._head_depth and tag in self._SEPARATOR_TAGS:
            self.text_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._blocked_depth:
            return
        if self._title_depth:
            self.title_parts.append(data)
        elif not self._head_depth:
            self.text_parts.append(data)


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _optional_normalized_text(value: str) -> str | None:
    normalized = _normalize_text(value)
    return normalized or None


def _invalid_url() -> AgentToolError:
    return AgentToolError(
        "invalid_url",
        "URL must be an absolute HTTP or HTTPS URL",
    )


def _unsafe_url() -> AgentToolError:
    return AgentToolError(
        "unsafe_url",
        "URL does not target a permitted public address",
    )


def _fetch_unavailable() -> AgentToolError:
    return AgentToolError("fetch_unavailable", _FETCH_UNAVAILABLE_MESSAGE)
