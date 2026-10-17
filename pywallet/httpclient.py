"""Klien HTTP JSON minimal (stdlib saja) agar mudah diganti dengan versi palsu saat tes."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

from .config import APP_VERSION

MAX_RESPONSE_BYTES = 4_000_000


class HttpError(Exception):
    """Permintaan gagal (jaringan, HTTP error, atau respons bukan JSON)."""


class HttpClient(Protocol):
    def get_json(self, url: str, params: dict[str, str] | None = None, timeout: float = 8.0) -> Any: ...
    def post_json(self, url: str, payload: Any, timeout: float = 8.0) -> Any: ...


class UrllibClient:
    _HEADERS = {
        "User-Agent": f"PyWallet/{APP_VERSION}",
        "Accept": "application/json",
    }

    def _send(self, req: urllib.request.Request, timeout: float) -> Any:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HttpError(f"{req.full_url}: {exc}") from exc
        if len(body) > MAX_RESPONSE_BYTES:
            raise HttpError(f"{req.full_url}: respons terlalu besar")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpError(f"{req.full_url}: respons bukan JSON") from exc

    def get_json(self, url: str, params: dict[str, str] | None = None, timeout: float = 8.0) -> Any:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return self._send(urllib.request.Request(url, headers=self._HEADERS), timeout)

    def post_json(self, url: str, payload: Any, timeout: float = 8.0) -> Any:
        headers = {**self._HEADERS, "Content-Type": "application/json"}
        data = json.dumps(payload).encode("utf-8")
        return self._send(urllib.request.Request(url, data=data, headers=headers, method="POST"), timeout)
