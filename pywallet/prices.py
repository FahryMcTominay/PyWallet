"""Harga pasar dari API bursa (Binance, endpoint publik tanpa API key) dan kurs USD -> IDR."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .httpclient import HttpClient, HttpError

# data-api.binance.vision = endpoint data pasar publik; api.binance.com sebagai cadangan.
BINANCE_HOSTS = ("https://data-api.binance.vision", "https://api.binance.com")
FX_FALLBACK_URL = "https://open.er-api.com/v6/latest/USD"
# Harga token menurut CONTRACT ADDRESS (bukan simbol), hanya untuk token yang terdaftar di CoinGecko.
COINGECKO_COIN_URL = "https://api.coingecko.com/api/v3/coins/{platform}/contract/{address}"
COINGECKO_SIMPLE_URL = "https://api.coingecko.com/api/v3/simple/price"
TOKEN_PRICE_CACHE_SECONDS = 60     # API publik tanpa key dibatasi lajunya; jangan panggil tiap muat ulang
ID_RETRY_SECONDS = 600             # token yang tidak terdaftar dicari lagi paling cepat tiap 10 menit
MAX_ID_LOOKUPS = 3                 # pencarian ID baru per panggilan (hemat kuota API)
LOOKUP_PAUSE_SECONDS = 60          # istirahat mencari ID setelah gangguan (mis. 429)
PERSISTED_PRICE_MAX_AGE = 24 * 3600  # harga tersimpan di database dipakai sebagai cadangan paling lama 24 jam


@dataclass(frozen=True)
class Quote:
    usd: float
    change_pct: float | None   # perubahan 24 jam dalam persen


@dataclass
class CustomPrices:
    quotes: dict[str, Quote] = field(default_factory=dict)       # alamat (huruf kecil) -> harga
    resolved: dict[str, str] = field(default_factory=dict)       # alamat (huruf kecil) -> ID koin yang baru ditemukan
    fresh: dict[str, tuple[float, float | None, float]] = field(default_factory=dict)   # ID koin -> (usd, perubahan, waktu)


class PriceService:
    def __init__(self, http: HttpClient, hosts: tuple[str, ...] = BINANCE_HOSTS):
        self.http = http
        self.hosts = hosts
        self._id_quote_cache: dict[str, tuple[float, Quote | None]] = {}
        self._id_negative: dict[tuple[str, str], float] = {}
        self._lookup_pause_until = 0.0

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

    # ------------------------------------------------------------------
    # Harga token kustom (CoinGecko). Aman terhadap token tiruan karena ID koin hanya diterima bila CoinGecko
    # mengakui contract address itu sebagai milik koin tersebut di platform yang sama.
    # ------------------------------------------------------------------
    def _lookup_coin_id(self, platform: str, address: str) -> tuple[str, str | None]:
        """("ok", id) | ("missing", None) = CoinGecko tidak mengenal alamat ini | ("error", None) = gagal sesaat."""
        try:
            data = self.http.get_json(
                COINGECKO_COIN_URL.format(platform=platform, address=address),
                {"localization": "false", "tickers": "false", "market_data": "false",
                 "community_data": "false", "developer_data": "false", "sparkline": "false"},
            )
        except HttpError as exc:
            # 404 = memang tidak terdaftar. Selain itu (429 rate limit, 5xx, timeout) hanya gangguan sementara.
            return ("missing", None) if "404" in str(exc) else ("error", None)
        try:
            coin_id = data["id"]
            listed = str(data["platforms"][platform]).lower()
        except (KeyError, ValueError, TypeError, AttributeError):
            return "missing", None
        if isinstance(coin_id, str) and listed == address:       # koin itu benar-benar milik alamat ini
            return "ok", coin_id
        return "missing", None

    def resolve_coin_id(self, platform: str, address: str) -> str | None:
        """ID koin CoinGecko untuk sebuah contract address; None bila tidak terdaftar atau permintaan gagal.

        Hanya hasil "tidak terdaftar" yang diingat lama (10 menit). Gangguan sementara (mis. 429) tidak boleh
        dianggap "tidak terdaftar": cukup jeda singkat, lalu dicoba lagi.
        """
        address = address.lower()
        key = (platform, address)
        now = time.time()
        failed_at = self._id_negative.get(key)
        if failed_at is not None and now - failed_at < ID_RETRY_SECONDS:
            return None
        if now < self._lookup_pause_until:
            return None
        status, coin_id = self._lookup_coin_id(platform, address)
        if status == "ok":
            return coin_id
        if status == "missing":
            self._id_negative[key] = now
        else:
            self._lookup_pause_until = now + LOOKUP_PAUSE_SECONDS     # kemungkinan rate limit: istirahat sebentar
        return None

    def custom_quotes(self, platform: str, entries: Iterable[tuple[str, str | None]],
                      persisted: dict[str, tuple[float, float | None, float]] | None = None) -> "CustomPrices":
        """Harga untuk token kustom. `entries` = (contract address, ID koin CoinGecko atau None).

        Token yang belum punya ID dicari dulu (maks. MAX_ID_LOOKUPS per panggilan; sisanya pada muat ulang
        berikutnya). Semua harga lalu diambil lewat SATU permintaan gabungan. `persisted` = harga terakhir yang
        tersimpan di database (ID koin -> (usd, perubahan, waktu)); dipakai bila CoinGecko sedang menolak permintaan,
        agar harga tidak hilang begitu saja.
        """
        out = CustomPrices()
        if not platform:
            return out
        ids: dict[str, str] = {}
        lookups = 0
        for address, coin_id in entries:
            address = address.lower()
            if coin_id:
                ids[address] = coin_id
            elif lookups < MAX_ID_LOOKUPS and time.time() >= self._lookup_pause_until:
                lookups += 1
                found = self.resolve_coin_id(platform, address)
                if found:
                    ids[address] = found
                    out.resolved[address] = found
        if not ids:
            return out
        fresh, quotes = self._quotes_by_id(set(ids.values()), persisted or {})
        out.fresh = fresh
        for address, coin_id in ids.items():
            if coin_id in quotes:
                out.quotes[address] = quotes[coin_id]
        return out

    def _quotes_by_id(self, coin_ids: set[str], persisted: dict[str, tuple[float, float | None, float]]):
        """(harga yang baru didapat dari API, semua harga yang bisa dipakai)."""
        now = time.time()
        usable: dict[str, Quote] = {}
        fresh: dict[str, tuple[float, float | None, float]] = {}
        stale: list[str] = []
        for cid in sorted(coin_ids):
            cached = self._id_quote_cache.get(cid)
            if cached and now - cached[0] < TOKEN_PRICE_CACHE_SECONDS:
                if cached[1] is not None:
                    usable[cid] = cached[1]
            else:
                stale.append(cid)
        if not stale:
            return fresh, usable

        def fallback(cid: str) -> None:
            """Permintaan gagal: pakai harga terakhir (memori, lalu database bila belum terlalu tua)."""
            old = self._id_quote_cache.get(cid)
            if old and old[1] is not None:
                usable[cid] = old[1]
            elif cid in persisted and now - persisted[cid][2] < PERSISTED_PRICE_MAX_AGE:
                usd, change, _ts = persisted[cid]
                usable[cid] = Quote(usd, change)

        try:
            data = self.http.get_json(
                COINGECKO_SIMPLE_URL,
                {"ids": ",".join(stale), "vs_currencies": "usd", "include_24hr_change": "true"},
            )
            if not isinstance(data, dict):
                raise TypeError("respons bukan objek")
        except (HttpError, ValueError, TypeError, AttributeError):
            for cid in stale:
                fallback(cid)
            return fresh, usable
        for cid in stale:
            q = self._parse_simple(data.get(cid))
            self._id_quote_cache[cid] = (time.time(), q)
            if q is not None:
                usable[cid] = q
                fresh[cid] = (q.usd, q.change_pct, time.time())
            else:
                fallback(cid)             # tidak ada di respons (mis. sesaat): jangan hilangkan harga lama
        return fresh, usable

    @staticmethod
    def _parse_simple(item) -> Quote | None:
        try:
            usd = float(item["usd"])
            if usd <= 0:
                return None
            change = item.get("usd_24h_change")
            return Quote(usd, float(change) if change is not None else None)
        except (KeyError, ValueError, TypeError, AttributeError):
            return None

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
