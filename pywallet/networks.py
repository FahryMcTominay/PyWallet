"""Jaringan EVM yang didukung dan pengelompokan mode (Mainnet / Testnet).

URL RPC di bawah adalah endpoint publik gratis (tanpa API key). Endpoint publik bisa dibatasi
laju permintaannya atau sewaktu-waktu berubah; urutannya dicoba satu per satu (failover).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Network:
    key: str
    name: str
    chain_id: int
    rpc_urls: tuple[str, ...]
    native_symbol: str
    is_testnet: bool
    badge_color: str   # warna lencana kecil di ikon token
    badge_text: str


NETWORKS: dict[str, Network] = {
    "ethereum": Network(
        key="ethereum",
        name="Ethereum",
        chain_id=1,
        rpc_urls=(
            "https://ethereum-rpc.publicnode.com",
            "https://eth.llamarpc.com",
        ),
        native_symbol="ETH",
        is_testnet=False,
        badge_color="#F5EEE9",
        badge_text="",
    ),
    "base": Network(
        key="base",
        name="Base",
        chain_id=8453,
        rpc_urls=(
            "https://mainnet.base.org",
            "https://base-rpc.publicnode.com",
        ),
        native_symbol="ETH",
        is_testnet=False,
        badge_color="#2F6BFF",
        badge_text="B",
    ),
    "sepolia": Network(
        key="sepolia",
        name="Sepolia",
        chain_id=11155111,
        rpc_urls=(
            "https://ethereum-sepolia-rpc.publicnode.com",
            "https://sepolia.drpc.org",
        ),
        native_symbol="ETH",
        is_testnet=True,
        badge_color="#D9A35B",
        badge_text="S",
    ),
}

MODE_MAINNET = "mainnet"
MODE_TESTNET = "testnet"

MODES: dict[str, tuple[str, ...]] = {
    MODE_MAINNET: ("ethereum", "base"),
    MODE_TESTNET: ("sepolia",),
}

MODE_LABELS = {MODE_MAINNET: "Mainnet", MODE_TESTNET: "Testnet"}
MODE_DETAIL = {
    MODE_MAINNET: "Ethereum, Base",
    MODE_TESTNET: "Sepolia",
}


def networks_for_mode(mode: str) -> list[Network]:
    return [NETWORKS[k] for k in MODES[mode]]
