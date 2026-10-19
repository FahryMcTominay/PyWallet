"""Klien JSON-RPC EVM: batch + failover antar endpoint, dan pembacaan saldo."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .httpclient import HttpClient, HttpError
from .tokens import Token

BALANCE_OF_SELECTOR = "0x70a08231"
NAME_SELECTOR = "0x06fdde03"       # name()
SYMBOL_SELECTOR = "0x95d89b41"     # symbol()
DECIMALS_SELECTOR = "0x313ce567"   # decimals()


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


# --------------------------------------------------------------------------
# Info token dari contract address (nama, simbol, desimal)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TokenInfo:
    address: str
    name: str
    symbol: str
    decimals: int


def decode_abi_string(result: Any) -> str:
    """Terjemahkan hasil eth_call yang berisi string (name/symbol).

    Dua bentuk ada di alam liar: string dinamis standar ABI, dan bytes32 pada token lama (mis. MKR).
    """
    if not isinstance(result, str) or not result.startswith("0x"):
        raise RpcError("Respons tidak valid.")
    try:
        data = bytes.fromhex(result[2:])
    except ValueError as exc:
        raise RpcError("Respons tidak valid.") from exc
    if len(data) == 32:                                   # bytes32
        raw = data.rstrip(b"\x00")
    elif len(data) >= 64:                                 # string dinamis: [offset][panjang][isi]
        offset = int.from_bytes(data[:32], "big")
        if offset + 32 > len(data):
            raise RpcError("Respons tidak valid.")
        length = int.from_bytes(data[offset:offset + 32], "big")
        if offset + 32 + length > len(data):
            raise RpcError("Respons tidak valid.")
        raw = data[offset + 32: offset + 32 + length]
    else:
        raise RpcError("Respons kosong.")
    text = raw.decode("utf-8", errors="replace")
    return "".join(ch for ch in text if ch.isprintable()).strip()


def fetch_token_info(rpc: RpcClient, address: str) -> TokenInfo:
    """Baca info token ERC-20 langsung dari blockchain. `address` harus sudah berformat checksum.

    Lempar RpcError dengan pesan yang aman ditampilkan jika alamat bukan kontrak atau bukan token ERC-20.
    """
    code, name_r, symbol_r, dec_r = rpc.batch([
        ("eth_getCode", [address, "latest"]),
        ("eth_call", [{"to": address, "data": NAME_SELECTOR}, "latest"]),
        ("eth_call", [{"to": address, "data": SYMBOL_SELECTOR}, "latest"]),
        ("eth_call", [{"to": address, "data": DECIMALS_SELECTOR}, "latest"]),
    ])
    if isinstance(code, RpcError):
        raise RpcError("Tidak bisa terhubung ke jaringan. Periksa koneksi internet lalu coba lagi.")
    if code in (None, "0x", ""):
        raise RpcError("Tidak ada kontrak di alamat ini pada jaringan yang dipilih. Periksa alamat dan jaringannya.")
    try:
        if isinstance(symbol_r, RpcError) or isinstance(dec_r, RpcError):
            raise RpcError("")
        symbol = decode_abi_string(symbol_r)
        decimals = parse_uint(dec_r)
        name = symbol
        if not isinstance(name_r, RpcError):
            try:
                name = decode_abi_string(name_r) or symbol
            except RpcError:
                pass
    except RpcError as exc:
        raise RpcError("Kontrak ini tidak terbaca sebagai token ERC-20 (tidak punya symbol/decimals yang valid).") from exc
    if not symbol or len(symbol) > 20:
        raise RpcError("Simbol token tidak valid.")
    if not 0 <= decimals <= 36:
        raise RpcError("Jumlah desimal token tidak valid.")
    return TokenInfo(address, name[:40], symbol, decimals)
