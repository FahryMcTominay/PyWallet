"""Klien JSON-RPC EVM: batch + failover antar endpoint, dan pembacaan saldo."""
from __future__ import annotations

from typing import Any, Sequence

from .httpclient import HttpClient, HttpError
from .tokens import Token

BALANCE_OF_SELECTOR = "0x70a08231"


class RpcError(Exception):
    pass


def encode_balance_of(address: str) -> str:
    return BALANCE_OF_SELECTOR + address.lower().removeprefix("0x").rjust(64, "0")


def parse_uint(value: Any) -> int:
    if value in (None, "0x", ""):
        return 0
    if not isinstance(value, str):
        raise RpcError("Respons saldo tidak valid.")
    try:
        return int(value, 16)
    except ValueError as exc:
        raise RpcError("Respons saldo tidak valid.") from exc


class RpcClient:
    def __init__(self, http: HttpClient, urls: Sequence[str], timeout: float = 8.0):
        self.http = http
        self.urls = tuple(urls)
        self.timeout = timeout

    def _post(self, payload: Any) -> Any:
        """Coba tiap endpoint berurutan; kembalikan respons pertama yang berhasil."""
        last: Exception | None = None
        for url in self.urls:
            try:
                return self.http.post_json(url, payload, self.timeout)
            except HttpError as exc:
                last = exc
        raise RpcError(f"Semua endpoint RPC gagal: {last}")

    @staticmethod
    def _error_text(item: dict) -> str:
        err = item.get("error")
        return err.get("message", "galat RPC") if isinstance(err, dict) else str(err)

    def call(self, method: str, params: list) -> Any:
        resp = self._post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if not isinstance(resp, dict):
            raise RpcError("Respons RPC tidak valid.")
        if "error" in resp:
            raise RpcError(self._error_text(resp))
        return resp.get("result")

    def batch(self, calls: Sequence[tuple[str, list]]) -> list[Any]:
        """Hasil berurutan sesuai `calls`; tiap elemen berupa nilai atau instance RpcError."""
        payload = [
            {"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)
        ]
        try:
            resp = self._post(payload)
        except RpcError as exc:       # tidak ada endpoint yang merespons -> jangan buang waktu
            return [exc] * len(calls)
        if isinstance(resp, list):
            by_id = {it.get("id"): it for it in resp if isinstance(it, dict)}
            out: list[Any] = []
            for i in range(len(calls)):
                item = by_id.get(i)
                if item is None:
                    out.append(RpcError("Tidak ada respons untuk permintaan ini."))
                elif "error" in item:
                    out.append(RpcError(self._error_text(item)))
                else:
                    out.append(item.get("result"))
            return out
        # Endpoint tidak mendukung batch: kirim satu per satu.
        out = []
        for method, params in calls:
            try:
                out.append(self.call(method, params))
            except RpcError as exc:
                out.append(exc)
        return out


def fetch_balances(rpc: RpcClient, address: str, tokens: Sequence[Token]) -> dict[str, int | RpcError]:
    """Saldo mentah (satuan terkecil) per token. Kegagalan satu token tidak menggagalkan yang lain."""
    calls: list[tuple[str, list]] = []
    for t in tokens:
        if t.address is None:
            calls.append(("eth_getBalance", [address, "latest"]))
        else:
            calls.append(("eth_call", [{"to": t.address, "data": encode_balance_of(address)}, "latest"]))
    results = rpc.batch(calls)
    out: dict[str, int | RpcError] = {}
    for t, res in zip(tokens, results):
        if isinstance(res, RpcError):
            out[t.key] = res
            continue
        try:
            out[t.key] = parse_uint(res)
        except RpcError as exc:
            out[t.key] = exc
    return out
