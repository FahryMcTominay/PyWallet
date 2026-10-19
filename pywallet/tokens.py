"""Daftar token bawaan per jaringan.

Token ditampilkan meskipun saldonya 0 (agar daftar tidak kosong). Token lain bisa ditambahkan
nanti lewat contract address (belum ada). Alamat kontrak WAJIB dalam format checksum
(EIP-55); ini diperiksa oleh tes otomatis.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

from eth_utils import is_checksum_address, to_checksum_address

from . import config
from .networks import MODES, NETWORKS, Network


@dataclass(frozen=True)
class Token:
    network: str                    # kunci jaringan, mis. "ethereum"
    symbol: str
    name: str
    decimals: int
    address: str | None             # None = koin native (ETH)
    price_symbol: str | None = None  # pasangan Binance, mis. "ETHUSDT"
    peg_usd: float | None = None     # harga cadangan untuk stablecoin bila API gagal
    color: str = "#456882"           # warna latar ikon
    glyph: str = ""                  # teks pada ikon (default: huruf pertama)
    custom: bool = False             # True = ditambahkan pengguna lewat contract address

    @property
    def key(self) -> str:
        """Pengenal unik. Token kustom memakai alamat kontrak, karena simbolnya bisa kembar dengan token lain."""
        if self.custom and self.address:
            return f"{self.network}:{self.address.lower()}"
        return f"{self.network}:{self.symbol}"

    @property
    def is_native(self) -> bool:
        return self.address is None


ETH_GLYPH = "ETH"  # ikon ETH memakai logo Ethereum (gambar), bukan teks

_ETHEREUM = (
    Token("ethereum", "ETH", "Ether", 18, None, "ETHUSDT", color="#F5EEE9", glyph=ETH_GLYPH),
    Token("ethereum", "USDT", "Tether USD", 6, "0xdAC17F958D2ee523a2206206994597C13D831ec7",
          None, 1.0, "#26A17B", "₮"),
    Token("ethereum", "USDC", "USD Coin", 6, "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
          "USDCUSDT", 1.0, "#2775CA", "$"),
    Token("ethereum", "DAI", "Dai", 18, "0x6B175474E89094C44Da98b954EedeAC495271d0F",
          None, 1.0, "#E0A030", "D"),
    Token("ethereum", "WBTC", "Wrapped Bitcoin", 8, "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
          "BTCUSDT", None, "#F09242", "₿"),
    Token("ethereum", "LINK", "Chainlink", 18, "0x514910771AF9Ca656af840dff83E8264EcF986CA",
          "LINKUSDT", None, "#2A5ADA", "L"),
    Token("ethereum", "UNI", "Uniswap", 18, "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
          "UNIUSDT", None, "#E2539A", "U"),
    Token("ethereum", "CAKE", "PancakeSwap Token", 18, "0x152649eA73beAb28c5b49B26eb48f7EAD6d4c898",
          "CAKEUSDT", None, "#1FA9B5", "C"),
)

_BASE = (
    Token("base", "ETH", "Ether", 18, None, "ETHUSDT", color="#F5EEE9", glyph=ETH_GLYPH),
    Token("base", "USDC", "USD Coin", 6, "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
          "USDCUSDT", 1.0, "#2775CA", "$"),
)

_SEPOLIA = (
    Token("sepolia", "ETH", "Sepolia Ether", 18, None, "ETHUSDT", color="#F5EEE9", glyph=ETH_GLYPH),
    Token("sepolia", "USDC", "USD Coin (test)", 6, "0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238",
          "USDCUSDT", 1.0, "#2775CA", "$"),
    Token("sepolia", "LINK", "Chainlink (test)", 18, "0x779877A7B0D9E8603169DdbD7836e478b4624789",
          "LINKUSDT", None, "#2A5ADA", "L"),
    Token("sepolia", "WETH", "Wrapped Ether (test)", 18, "0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14",
          "ETHUSDT", None, "#7A8CA3", "W"),
)

TOKENS: dict[str, tuple[Token, ...]] = {
    "ethereum": _ETHEREUM,
    "base": _BASE,
    "sepolia": _SEPOLIA,
}


class InvalidContractAddress(ValueError):
    """Pesan aman ditampilkan ke pengguna."""


def normalize_contract_address(text: str) -> str:
    """Rapikan alamat kontrak menjadi format checksum (EIP-55), atau lempar InvalidContractAddress."""
    raw = (text or "").strip()
    body = raw[2:] if raw[:2].lower() == "0x" else raw
    if len(body) != 40 or any(c not in "0123456789abcdefABCDEF" for c in body):
        raise InvalidContractAddress("Alamat kontrak harus 40 karakter heksadesimal (boleh diawali 0x).")
    if int(body, 16) == 0:
        raise InvalidContractAddress("Alamat nol bukan alamat kontrak token.")
    mixed = body != body.lower() and body != body.upper()
    if mixed and not is_checksum_address("0x" + body):
        raise InvalidContractAddress(
            "Huruf besar/kecil alamat tidak cocok dengan checksum. Kemungkinan ada salah ketik; salin ulang alamatnya."
        )
    return to_checksum_address("0x" + body.lower())


_CUSTOM_COLORS = ("#2E8B9A", "#5A7D8C", "#3F9C8A", "#7A8CA3", "#4A8FB0", "#6B9E94", "#8A7FA8", "#5C9FA6")


def make_custom_token(network: str, address: str, symbol: str, name: str, decimals: int) -> Token:
    """Token kustom: tanpa pasangan harga; warna ikon diturunkan dari alamat kontrak (stabil)."""
    color = _CUSTOM_COLORS[hashlib.sha256(address.lower().encode()).digest()[0] % len(_CUSTOM_COLORS)]
    return Token(network, symbol, name, decimals, address, None, None, color, (symbol[:1] or "?").upper(), True)


def find_builtin(network: str, address: str) -> Token | None:
    for t in TOKENS.get(network, ()):
        if t.address and t.address.lower() == address.lower():
            return t
    return None


def tokens_for_mode(mode: str, custom: Iterable[Token] = ()) -> list[Token]:
    """Token yang ditampilkan untuk sebuah mode, ditambah token kustom milik pengguna di jaringan mode itu.

    Bila `config.EXTENDED_TOKEN_LIST` dimatikan (False), token bawaan hanya koin native (ETH) di jaringan utama.
    """
    everything = [t for net in MODES[mode] for t in TOKENS[net]]
    if not config.EXTENDED_TOKEN_LIST:
        primary = MODES[mode][0]
        everything = [t for t in everything if t.is_native and t.network == primary]
    extra = [t for t in custom if t.network in MODES[mode]]
    return everything + extra


def active_networks(mode: str, custom: Iterable[Token] = ()) -> list[Network]:
    """Jaringan yang benar-benar punya token untuk ditampilkan/dimuat pada mode ini."""
    used = {t.network for t in tokens_for_mode(mode, custom)}
    return [NETWORKS[k] for k in MODES[mode] if k in used]
