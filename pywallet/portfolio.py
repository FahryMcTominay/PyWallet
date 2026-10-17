"""Portofolio: gabungan saldo on-chain + harga, diurutkan, dan total dalam USD / IDR / ETH."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal

from .formatting import UNIT_ETH, UNIT_IDR, UNIT_USD
from .httpclient import HttpClient, UrllibClient
from .networks import MODE_MAINNET, NETWORKS
from .prices import PriceService, Quote
from .rpc import RpcClient, RpcError, fetch_balances
from .tokens import Token, active_networks, tokens_for_mode

ETH_PRICE_SYMBOL = "ETHUSDT"


@dataclass(frozen=True)
class AssetRow:
    token: Token
    amount: Decimal | None          # None = gagal dimuat
    price_usd: float | None
    change_pct: float | None

    @property
    def has_balance(self) -> bool:
        return self.amount is not None and self.amount > 0

    @property
    def value_usd(self) -> float | None:
        if self.amount is None or self.price_usd is None:
            return None
        return float(self.amount) * self.price_usd

    @property
    def rank_value(self) -> float:
        """Nilai pembanding untuk pengurutan. Di testnet harga referensi mainnet dipakai
        HANYA untuk mengurutkan; nilainya tidak ditampilkan."""
        return self.value_usd or 0.0


def sort_assets(rows: list[AssetRow]) -> list[AssetRow]:
    """Aset yang dimiliki dulu (nilai terbesar -> terkecil); saldo 0 menyusul, urut abjad."""

    def key(r: AssetRow):
        symbol = r.token.symbol.lower()
        if r.has_balance:
            return (0, -r.rank_value, -float(r.amount), symbol, r.token.network)
        return (1, 0.0, 0.0, symbol, r.token.network)

    return sorted(rows, key=key)


@dataclass
class Snapshot:
    mode: str
    address: str
    rows: list[AssetRow]
    usd_idr: float | None = None
    eth_usd: float | None = None
    eth_change: float | None = None
    eth_spark: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fetched_at: float = field(default_factory=time.time)

    @property
    def fiat_enabled(self) -> bool:
        """Aset testnet tidak bernilai uang, jadi nilai fiat hanya untuk mainnet."""
        return self.mode == MODE_MAINNET

    @property
    def has_holdings(self) -> bool:
        return any(r.has_balance for r in self.rows)

    def total_usd(self) -> float:
        if not self.fiat_enabled:
            return 0.0
        return sum(r.value_usd or 0.0 for r in self.rows)

    def has_unpriced_holdings(self) -> bool:
        return self.fiat_enabled and any(r.has_balance and r.price_usd is None for r in self.rows)

    def change_pct(self) -> float | None:
        """Perubahan 24 jam portofolio, ditimbang dengan nilai tiap aset."""
        if not self.fiat_enabled:
            return None
        now = prev = 0.0
        for r in self.rows:
            v = r.value_usd
            if not v or r.change_pct is None:
                continue
            now += v
            prev += v / (1 + r.change_pct / 100)
        return (now / prev - 1) * 100 if prev > 0 else None

    def total_eth(self) -> Decimal | None:
        if self.fiat_enabled:
            if not self.eth_usd:
                return None
            return Decimal(str(self.total_usd())) / Decimal(str(self.eth_usd))
        return sum((r.amount for r in self.rows if r.token.is_native and r.amount), Decimal(0))

    def total_in(self, unit: str):
        """Total dalam satuan yang dipilih; None bila data pendukung (kurs/harga) belum ada."""
        if unit == UNIT_USD:
            return self.total_usd()
        if unit == UNIT_IDR:
            if not self.fiat_enabled:
                return 0.0
            return self.total_usd() * self.usd_idr if self.usd_idr else None
        if unit == UNIT_ETH:
            return self.total_eth()
        raise ValueError(unit)

    def row_value(self, row: AssetRow, unit: str):
        """Nilai satu aset dalam satuan terpilih; None jika tidak tersedia / testnet."""
        if not self.fiat_enabled:
            return None
        usd = row.value_usd
        if usd is None:
            return None
        if unit == UNIT_USD:
            return usd
        if unit == UNIT_IDR:
            return usd * self.usd_idr if self.usd_idr else None
        if unit == UNIT_ETH:
            return Decimal(str(usd)) / Decimal(str(self.eth_usd)) if self.eth_usd else None
        raise ValueError(unit)


class PortfolioService:
    def __init__(self, http: HttpClient | None = None):
        self.http = http or UrllibClient()
        self.prices = PriceService(self.http)
        self._rpc = {k: RpcClient(self.http, n.rpc_urls) for k, n in NETWORKS.items()}

    def load(self, address: str, mode: str) -> Snapshot:
        tokens = tokens_for_mode(mode)
        networks = active_networks(mode)
        symbols = {t.price_symbol for t in tokens if t.price_symbol} | {ETH_PRICE_SYMBOL}

        with ThreadPoolExecutor(max_workers=len(networks) + 3) as pool:
            bal_futures = {
                net.key: pool.submit(
                    fetch_balances, self._rpc[net.key], address, [t for t in tokens if t.network == net.key]
                )
                for net in networks
            }
            quotes_f = pool.submit(self.prices.quotes, symbols)
            idr_f = pool.submit(self.prices.usd_idr)
            spark_f = pool.submit(self.prices.sparkline, ETH_PRICE_SYMBOL)

            balances: dict[str, int | RpcError] = {}
            for fut in bal_futures.values():
                balances.update(fut.result())
            quotes: dict[str, Quote] = quotes_f.result()
            usd_idr = idr_f.result()
            spark = spark_f.result()

        errors: list[str] = []
        failed_networks = {NETWORKS[t.network].name for t in tokens if isinstance(balances.get(t.key), RpcError)}
        errors.extend(f"Saldo {name} gagal dimuat" for name in sorted(failed_networks))
        if not quotes:
            errors.append("Harga pasar gagal dimuat")

        rows: list[AssetRow] = []
        for t in tokens:
            raw = balances.get(t.key)
            amount = None if isinstance(raw, (RpcError, type(None))) else Decimal(raw).scaleb(-t.decimals)
            q = quotes.get(t.price_symbol) if t.price_symbol else None
            if q is not None:
                price, change = q.usd, q.change_pct
            elif t.peg_usd is not None:
                price, change = t.peg_usd, None
            else:
                price, change = None, None
            rows.append(AssetRow(t, amount, price, change))

        eth_q = quotes.get(ETH_PRICE_SYMBOL)
        return Snapshot(
            mode=mode,
            address=address,
            rows=sort_assets(rows),
            usd_idr=usd_idr,
            eth_usd=eth_q.usd if eth_q else None,
            eth_change=eth_q.change_pct if eth_q else None,
            eth_spark=spark,
            errors=errors,
        )
