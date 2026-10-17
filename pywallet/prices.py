"""Harga pasar dari API bursa (Binance, endpoint publik tanpa API key) dan kurs USD -> IDR."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from .httpclient import HttpClient, HttpError

# data-api.binance.vision = endpoint data pasar publik; api.binance.com sebagai cadangan.
BINANCE_HOSTS = ("https://data-api.binance.vision", "https://api.binance.com")
FX_FALLBACK_URL = "https://open.er-api.com/v6/latest/USD"


@dataclass(frozen=True)
class Quote:
    usd: float
    change_pct: float | None   # perubahan 24 jam dalam persen


class PriceService:
    def __init__(self, http: HttpClient, hosts: tuple[str, ...] = BINANCE_HOSTS):
        self.http = http
        self.hosts = hosts

    def _get(self, path: str, params: dict[str, str]) -> Any:
        last: Exception | None = None
        for host in self.hosts:
            try:
                return self.http.get_json(host + path, params)
            except HttpError as exc:
                last = exc
        raise HttpError(f"Semua host harga gagal: {last}")

    @staticmethod
    def _parse_quote(item: dict) -> Quote:
        return Quote(float(item["lastPrice"]), float(item["priceChangePercent"]))

    def quotes(self, symbols: Iterable[str]) -> dict[str, Quote]:
        """Harga terakhir + perubahan 24 jam untuk pasangan Binance (mis. 'ETHUSDT')."""
        wanted = sorted({s for s in symbols if s})
        if not wanted:
            return {}
        out: dict[str, Quote] = {}
        try:
            data = self._get(
                "/api/v3/ticker/24hr", {"symbols": json.dumps(wanted, separators=(",", ":"))}
            )
            for item in data:
                out[item["symbol"]] = self._parse_quote(item)
            return out
        except (HttpError, KeyError, ValueError, TypeError):
            pass
        # Satu simbol tidak valid membuat seluruh permintaan gagal -> coba satu per satu.
        for sym in wanted:
            try:
                out[sym] = self._parse_quote(self._get("/api/v3/ticker/24hr", {"symbol": sym}))
            except (HttpError, KeyError, ValueError, TypeError):
                continue
        return out

    def usd_idr(self) -> float | None:
        """Kurs 1 USD dalam rupiah. Utama: Binance USDT/IDR; cadangan: open.er-api.com."""
        try:
            data = self._get("/api/v3/ticker/price", {"symbol": "USDTIDR"})
            rate = float(data["price"])
            if rate > 0:
                return rate
        except (HttpError, KeyError, ValueError, TypeError):
            pass
        try:
            data = self.http.get_json(FX_FALLBACK_URL)
            rate = float(data["rates"]["IDR"])
            if rate > 0:
                return rate
        except (HttpError, KeyError, ValueError, TypeError):
            pass
        return None

    def sparkline(self, symbol: str = "ETHUSDT", points: int = 24) -> list[float]:
        """Harga penutupan per jam untuk grafik mini; list kosong jika gagal."""
        try:
            data = self._get(
                "/api/v3/klines", {"symbol": symbol, "interval": "1h", "limit": str(points)}
            )
            return [float(k[4]) for k in data]
        except (HttpError, KeyError, ValueError, TypeError, IndexError):
            return []
