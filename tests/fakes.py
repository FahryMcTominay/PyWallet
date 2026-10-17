"""HTTP palsu untuk tes: meniru JSON-RPC EVM, Binance, dan API kurs tanpa jaringan."""
from __future__ import annotations

import json
from typing import Any, Callable

from pywallet.httpclient import HttpError
from pywallet.networks import NETWORKS


class FakeHttp:
    def __init__(self):
        self.post_handlers: dict[str, Callable[[Any], Any]] = {}
        self.get_handlers: dict[str, Callable[[str, dict | None], Any]] = {}
        self.calls: list[tuple[str, str]] = []

    def post_json(self, url, payload, timeout=8.0):
        self.calls.append(("POST", url))
        handler = self.post_handlers.get(url)
        if handler is None:
            raise HttpError(f"{url}: down")
        return handler(payload)

    def get_json(self, url, params=None, timeout=8.0):
        self.calls.append(("GET", url))
        for prefix, handler in self.get_handlers.items():
            if url.startswith(prefix):
                return handler(url, params)
        raise HttpError(f"{url}: down")


def make_rpc(native_wei: int = 0, token_raw: dict[str, int] | None = None, batch: bool = True):
    """Handler JSON-RPC. `token_raw` memetakan alamat kontrak (huruf kecil) -> saldo mentah."""
    token_raw = {k.lower(): v for k, v in (token_raw or {}).items()}

    def one(req: dict) -> dict:
        method, params = req["method"], req["params"]
        if method == "eth_getBalance":
            result = hex(native_wei)
        elif method == "eth_call":
            to = params[0]["to"].lower()
            result = hex(token_raw.get(to, 0))
        else:
            return {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32601, "message": "no method"}}
        return {"jsonrpc": "2.0", "id": req["id"], "result": result}

    def handler(payload):
        if isinstance(payload, list):
            if not batch:
                return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "batch not supported"}}
            return [one(r) for r in payload]
        return one(payload)

    return handler


def make_binance(prices: dict[str, tuple[float, float]], usdt_idr: float | None = 16000.0, klines=None):
    """prices: simbol -> (harga, perubahan24jam%)."""

    def handler(url, params):
        path = url.split(".com")[-1].split(".vision")[-1]
        params = params or {}
        if path == "/api/v3/ticker/24hr":
            if "symbols" in params:
                syms = json.loads(params["symbols"])
                if any(s not in prices for s in syms):
                    raise HttpError("400 Invalid symbol")
                return [
                    {"symbol": s, "lastPrice": str(prices[s][0]), "priceChangePercent": str(prices[s][1])}
                    for s in syms
                ]
            s = params["symbol"]
            if s not in prices:
                raise HttpError("400 Invalid symbol")
            return {"symbol": s, "lastPrice": str(prices[s][0]), "priceChangePercent": str(prices[s][1])}
        if path == "/api/v3/ticker/price":
            if params.get("symbol") == "USDTIDR" and usdt_idr:
                return {"symbol": "USDTIDR", "price": str(usdt_idr)}
            raise HttpError("400 Invalid symbol")
        if path == "/api/v3/klines":
            return klines if klines is not None else [[0, "0", "0", "0", str(3000 + i)] for i in range(24)]
        raise HttpError("404")

    return handler


def install_standard(fake: FakeHttp, mode: str = "mainnet", **kwargs):
    """Pasang handler Binance standar pada kedua host."""
    prices = kwargs.get("prices") or {
        "ETHUSDT": (3000.0, 2.0),
        "BTCUSDT": (100000.0, -1.0),
        "USDCUSDT": (1.0, 0.0),
        "LINKUSDT": (15.0, 5.0),
        "UNIUSDT": (8.0, 1.0),
        "AAVEUSDT": (200.0, 3.0),
        "SHIBUSDT": (0.00002, -2.0),
        "PEPEUSDT": (0.00001, 4.0),
    }
    h = make_binance(prices, kwargs.get("usdt_idr", 16000.0), kwargs.get("klines"))
    fake.get_handlers["https://data-api.binance.vision"] = h
    fake.get_handlers["https://api.binance.com"] = h


def rpc_urls(network: str):
    return NETWORKS[network].rpc_urls
