"""Bounded requests to public metadata endpoints, never business APIs."""

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, urljoin, urlsplit

import httpx


class FetchError(RuntimeError):
    """A safe-to-log error that excludes credentials and response bodies."""


@dataclass(frozen=True)
class Resource:
    url: str
    content: bytes
    content_type: str
    fetched_at: datetime
    kind: str = "html"

    @property
    def text(self):
        charset = re.search(r"charset=([\w-]+)", self.content_type, re.I)
        encoding = charset.group(1) if charset else "utf-8"
        try:
            return self.content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            return self.content.decode("utf-8", errors="replace")


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        raise FetchError("Unapproved metadata destination")
    host, path = parts.hostname, parts.path
    allowed = False
    if host in {"data.go.kr", "www.data.go.kr"}:
        allowed = bool(
            re.fullmatch(r"/data/\d+/(?:fileData|openapi|standard|linkedData)\.do", path)
        )
        allowed |= path.startswith("/catalog/") or path.startswith("/biz/dcat/metadata/")
        allowed |= path in {
            "/tcs/dss/selectDataSetList.do",
            "/tcs/dss/stdFileList.do",
            "/tcs/dss/selectApiDetailFunction.do",
            "/tcs/dss/selectDpkDetailInfo.do",
            "/tcs/dss/selectHistAndCsvData.do",
        }
    elif host == "api.odcloud.kr":
        allowed = path.startswith("/api/15077093/v1/")
    elif host == "infuser.odcloud.kr":
        allowed = path.startswith("/oas/") or bool(re.fullmatch(r"/api/stages/\d+/api-docs", path))
    if not allowed:
        raise FetchError("Unapproved metadata destination")


class PortalHTTP:
    def __init__(
        self,
        *,
        service_key=None,
        interval=0.5,
        retries=3,
        timeout=30,
        max_bytes=16 * 1024 * 1024,
        transport=None,
        sleep=time.sleep,
    ):
        if interval < 0 or retries < 0 or timeout <= 0 or max_bytes <= 0:
            raise ValueError("Invalid HTTP limits")
        self.service_key = unquote(service_key.strip()) if service_key else None
        self.interval, self.retries, self.max_bytes = interval, retries, max_bytes
        self.sleep = sleep
        self.last_request = None
        self.client = httpx.Client(
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={
                "User-Agent": "OpenDataCatalogCollector/0.1 (public metadata)",
                "Accept": "application/json, text/html, application/xml;q=0.9, */*;q=0.5",
            },
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def _delay(self, retry_after, attempt):
        try:
            delay = float(retry_after)
        except (ValueError, TypeError):
            try:
                date = parsedate_to_datetime(retry_after)
                delay = (date - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                delay = 2**attempt
        self.sleep(min(60.0, max(0.0, delay)))

    def get(self, url, *, auth=False, kind="html"):
        return self.request("GET", url, auth=auth, kind=kind)

    def request(self, method, url, *, auth=False, kind="html", data=None):
        # POST is allowed only for this read-only metadata popup, never portal actions.
        if method != "GET" and not (
            method == "POST"
            and urlsplit(url).path
            in {
                "/tcs/dss/selectDpkDetailInfo.do",
                "/tcs/dss/selectApiDetailFunction.do",
            }
        ):
            raise FetchError("Unapproved metadata method")
        for redirect in range(6):
            validate_url(url)
            if auth and (urlsplit(url).hostname != "api.odcloud.kr" or not self.service_key):
                raise FetchError(
                    "Catalog authentication requires ODP_SERVICE_KEY and official host"
                )
            headers = {"Authorization": f"Infuser {self.service_key}"} if auth else {}
            redirected = False
            for attempt in range(self.retries + 1):
                if self.last_request is not None:
                    delay = self.interval - (time.monotonic() - self.last_request)
                    if delay > 0:
                        self.sleep(delay)
                self.last_request = time.monotonic()
                try:
                    with self.client.stream(method, url, headers=headers, data=data) as response:
                        status = response.status_code
                        if status in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location:
                                raise FetchError("Metadata redirect missing destination")
                            url = urljoin(url, location)
                            # Never forward a key across redirects, even between approved hosts.
                            auth = False
                            redirected = True
                            break
                        if status in {429, 500, 502, 503, 504} and attempt < self.retries:
                            self._delay(response.headers.get("Retry-After"), attempt)
                            continue
                        if not 200 <= status < 300:
                            raise FetchError(f"HTTP {status} from metadata endpoint")
                        chunks, size = [], 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > self.max_bytes:
                                raise FetchError("Metadata response exceeds size limit")
                            chunks.append(chunk)
                        return Resource(
                            str(response.url),
                            b"".join(chunks),
                            response.headers.get("content-type", ""),
                            datetime.now(timezone.utc),
                            kind,
                        )
                except httpx.RequestError:
                    if attempt == self.retries:
                        raise FetchError("Network request failed after retry budget") from None
                    self._delay(None, attempt)
            if not redirected:
                break
        raise FetchError("Too many metadata redirects")
