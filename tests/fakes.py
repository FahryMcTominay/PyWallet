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
        "CAKEUSDT": (2.5, 1.5),
        "AAVEUSDT": (200.0, 3.0),
        "SHIBUSDT": (0.00002, -2.0),
        "PEPEUSDT": (0.00001, 4.0),
    }
    h = make_binance(prices, kwargs.get("usdt_idr", 16000.0), kwargs.get("klines"))
    fake.get_handlers["https://data-api.binance.vision"] = h
    fake.get_handlers["https://api.binance.com"] = h


def rpc_urls(network: str):
    return NETWORKS[network].rpc_urls


# --------------------------------------------------------------------------
# Blockchain palsu dengan kontrak token ERC-20 (name / symbol / decimals / balanceOf)
# --------------------------------------------------------------------------
def abi_string(text: str) -> str:
    raw = text.encode()
    padded = raw + b"\x00" * (-len(raw) % 32)
    return "0x" + (32).to_bytes(32, "big").hex() + len(raw).to_bytes(32, "big").hex() + padded.hex()


def abi_bytes32(text: str) -> str:
    return "0x" + text.encode().ljust(32, b"\x00").hex()


def make_chain(contracts: dict[str, dict], native_wei: int = 0, balances: dict[str, int] | None = None):
    """contracts: alamat -> {"name", "symbol", "decimals", "bytes32": bool, "broken": bool}.
    balances: alamat kontrak -> saldo mentah milik siapa pun yang ditanya."""
    contracts = {k.lower(): v for k, v in contracts.items()}
    balances = {k.lower(): v for k, v in (balances or {}).items()}

    def one(req: dict) -> dict:
        method, params = req["method"], req["params"]
        ok = lambda result: {"jsonrpc": "2.0", "id": req["id"], "result": result}  # noqa: E731
        fail = lambda msg: {"jsonrpc": "2.0", "id": req["id"], "error": {"code": 3, "message": msg}}  # noqa: E731
        if method == "eth_getBalance":
            return ok(hex(native_wei))
        if method == "eth_getCode":
            return ok("0x6080604052" if params[0].lower() in contracts else "0x")
        if method == "eth_call":
            to, data = params[0]["to"].lower(), params[0]["data"]
            info = contracts.get(to)
            if info is None or info.get("broken") and data[:10] != "0x70a08231":
                return fail("execution reverted")
            enc = abi_bytes32 if info.get("bytes32") else abi_string
            if data[:10] == "0x06fdde03":
                return ok(enc(info["name"]))
            if data[:10] == "0x95d89b41":
                return ok(enc(info["symbol"]))
            if data[:10] == "0x313ce567":
                return ok(hex(info["decimals"]))
            if data[:10] == "0x70a08231":
                return ok(hex(balances.get(to, 0)))
        return fail("no method")

    def handler(payload):
        return [one(r) for r in payload] if isinstance(payload, list) else one(payload)

    return handler


# --------------------------------------------------------------------------
# Blockchain palsu untuk fitur Kirim (nonce, gas, kirim transaksi, receipt)
# --------------------------------------------------------------------------
class FakeSendChain:
    """Meniru node EVM untuk alur kirim. Semua transaksi yang dikirim tercatat di `sent`."""

    def __init__(self, chain_id=11155111, native_wei=10**18, token_raw=None, nonce=7,
                 base_fee: int | None = 10**9, tip=10**9, gas_price=2 * 10**9,
                 codes=None, estimate_error: str | None = None, send_error: str | None = None,
                 receipt_status: int | None = 1, estimate_gas=21_000):
        self.chain_id, self.native_wei, self.nonce = chain_id, native_wei, nonce
        self.token_raw = {k.lower(): v for k, v in (token_raw or {}).items()}
        self.base_fee, self.tip, self.gas_price = base_fee, tip, gas_price
        self.codes = {k.lower() for k in (codes or ())}
        self.estimate_error, self.send_error = estimate_error, send_error
        self.receipt_status = receipt_status
        self.estimate_gas = estimate_gas
        self.sent: list[str] = []

    def _one(self, req):
        m, p = req["method"], req["params"]
        ok = lambda r: {"jsonrpc": "2.0", "id": req["id"], "result": r}  # noqa: E731
        err = lambda msg: {"jsonrpc": "2.0", "id": req["id"], "error": {"code": -32000, "message": msg}}  # noqa: E731
        if m == "eth_chainId":
            return ok(hex(self.chain_id))
        if m == "eth_getTransactionCount":
            return ok(hex(self.nonce))
        if m == "eth_getBlockByNumber":
            blk = {"number": "0x10"}
            if self.base_fee is not None:
                blk["baseFeePerGas"] = hex(self.base_fee)
            return ok(blk)
        if m == "eth_maxPriorityFeePerGas":
            return ok(hex(self.tip)) if self.base_fee is not None else err("method not found")
        if m == "eth_gasPrice":
            return ok(hex(self.gas_price))
        if m == "eth_getCode":
            return ok("0x6080" if p[0].lower() in self.codes else "0x")
        if m == "eth_getBalance":
            return ok(hex(self.native_wei))
        if m == "eth_call":
            return ok(hex(self.token_raw.get(p[0]["to"].lower(), 0)))
        if m == "eth_estimateGas":
            return err(self.estimate_error) if self.estimate_error else ok(hex(self.estimate_gas))
        if m == "eth_sendRawTransaction":
            if self.send_error:
                return err(self.send_error)
            self.sent.append(p[0])
            from eth_utils import keccak
            return ok("0x" + keccak(bytes.fromhex(p[0].removeprefix("0x"))).hex())   # hash asli, seperti node sungguhan
        if m == "eth_getTransactionReceipt":
            if self.receipt_status is None:
                return ok(None)
            return ok({"status": hex(self.receipt_status), "blockNumber": "0x11"})
        return err("no method")

    def handler(self, payload):
        return [self._one(r) for r in payload] if isinstance(payload, list) else self._one(payload)
