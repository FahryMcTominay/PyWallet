"""Daftar token bawaan per jaringan.

Token ditampilkan meskipun saldonya 0 (agar daftar tidak kosong). Token lain bisa ditambahkan
nanti lewat contract address (tahap berikutnya). Alamat kontrak WAJIB dalam format checksum
(EIP-55); ini diperiksa oleh tes otomatis.
"""
from __future__ import annotations

from dataclasses import dataclass

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

    @property
    def key(self) -> str:
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
    Token("ethereum", "AAVE", "Aave", 18, "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
          "AAVEUSDT", None, "#8B6FC9", "A"),
    Token("ethereum", "SHIB", "Shiba Inu", 18, "0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE",
          "SHIBUSDT", None, "#E8602C", "S"),
    Token("ethereum", "PEPE", "Pepe", 18, "0x6982508145454Ce325dDbE47a25d4ec3d2311933",
          "PEPEUSDT", None, "#4C9A3A", "P"),
)

_BASE = (
    Token("base", "ETH", "Ether", 18, None, "ETHUSDT", color="#F5EEE9", glyph=ETH_GLYPH),
    Token("base", "USDC", "USD Coin", 6, "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
          "USDCUSDT", 1.0, "#2775CA", "$"),
    Token("base", "cbBTC", "Coinbase Wrapped BTC", 8, "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",
          "BTCUSDT", None, "#F09242", "₿"),
    Token("base", "DAI", "Dai", 18, "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
          None, 1.0, "#E0A030", "D"),
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


def tokens_for_mode(mode: str) -> list[Token]:
    """Token yang ditampilkan untuk sebuah mode.

    Selama `config.EXTENDED_TOKEN_LIST` False, hanya koin native (ETH) di jaringan utama mode itu.
    """
    everything = [t for net in MODES[mode] for t in TOKENS[net]]
    if config.EXTENDED_TOKEN_LIST:
        return everything
    primary = MODES[mode][0]
    return [t for t in everything if t.is_native and t.network == primary]


def active_networks(mode: str) -> list[Network]:
    """Jaringan yang benar-benar punya token untuk ditampilkan/dimuat pada mode ini."""
    used = {t.network for t in tokens_for_mode(mode)}
    return [NETWORKS[k] for k in MODES[mode] if k in used]
