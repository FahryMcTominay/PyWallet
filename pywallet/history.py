"""Riwayat transaksi: gabungan data explorer (keluar + masuk) dan catatan lokal transaksi yang dikirim.

Sumber data:
  * API explorer berformat Etherscan (`module=account&action=txlist` dan `tokentx`). Dipakai instance Blockscout
    publik per jaringan (lihat `Network.history_api`), tanpa API key. Format yang sama juga dipakai Etherscan,
    jadi sumbernya bisa diganti tanpa mengubah parser.
  * Tabel lokal `tx_log`: transaksi yang baru dikirim dari aplikasi tampil langsung sebagai "menunggu",
    sebelum explorer sempat mengindeksnya.
Data explorer diperlakukan sebagai input yang tidak dipercaya: setiap bidang divalidasi, bukan diasumsikan.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Iterable, Sequence

from .httpclient import HttpClient, HttpError
from .networks import MODES, NETWORKS
from .rpc import RpcClient
from .tokens import Token
from .tx import fetch_receipt
from .vault import SentTx

PAGE_SIZE = 50

DIR_OUT, DIR_IN, DIR_SELF, DIR_CALL = "out", "in", "self", "call"
ST_SUCCESS, ST_FAILED, ST_PENDING = "success", "failed", "pending"


@dataclass(frozen=True)
class HistoryItem:
    network: str
    tx_hash: str
    timestamp: int
    direction: str                 # out | in | self | call (panggilan kontrak tanpa transfer aset)
    symbol: str
    amount: Decimal | None         # None untuk panggilan kontrak
    counterparty: str              # alamat lawan transaksi ('' jika tidak ada)
    status: str
    token_address: str | None = None
    known_token: bool = True       # False = token tidak ada di daftarmu (bisa token penipu/airdrop)
    local: bool = False            # True = hanya ada di catatan lokal (belum ada di explorer)


@dataclass
class HistoryResult:
    items: list[HistoryItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    hidden_zero: int = 0           # transfer token bernilai nol yang disembunyikan
    updates: list[tuple[str, str, str, int | None]] = field(default_factory=list)   # (network, hash, status, block)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _addr(value: Any) -> str:
    return value.lower() if isinstance(value, str) and value.startswith("0x") and len(value) == 42 else ""


def parse_txlist(rows: Iterable[dict], me: str, network: str) -> list[HistoryItem]:
    """Transaksi biasa: transfer koin native dan panggilan kontrak."""
    me = me.lower()
    net = NETWORKS[network]
    out: list[HistoryItem] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        tx_hash = str(r.get("hash", "")).lower()
        if not (tx_hash.startswith("0x") and len(tx_hash) == 66):
            continue
        sender, to = _addr(r.get("from")), _addr(r.get("to"))
        value = _int(r.get("value"))
        failed = str(r.get("isError")) == "1" or str(r.get("txreceipt_status")) == "0"
        is_call = str(r.get("input", "0x")) not in ("0x", "")
        if sender == me and to == me:
            direction, other = DIR_SELF, me
        elif sender == me:
            direction, other = DIR_OUT, to
        elif to == me:
            direction, other = DIR_IN, sender
        else:
            continue
        if value == 0 and is_call:
            item_dir, amount = DIR_CALL, None
            other = to if direction != DIR_IN else sender
        else:
            item_dir, amount = direction, Decimal(value).scaleb(-18)
        out.append(HistoryItem(
            network=network, tx_hash=tx_hash, timestamp=_int(r.get("timeStamp")), direction=item_dir,
            symbol=net.native_symbol, amount=amount, counterparty=other,
            status=ST_FAILED if failed else ST_SUCCESS,
        ))
    return out


def parse_tokentx(rows: Iterable[dict], me: str, network: str, known: set[str]) -> tuple[list[HistoryItem], int]:
    """Transfer token ERC-20. Kembalikan (item, jumlah transfer bernilai nol yang dibuang).

    Transfer bernilai nol dari alamat asing dibuang: itu modus "address poisoning" (alamat tiruan muncul di
    riwayatmu supaya kamu menyalinnya secara keliru saat mengirim).
    """
    me = me.lower()
    out: list[HistoryItem] = []
    hidden = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        tx_hash = str(r.get("hash", "")).lower()
        if not (tx_hash.startswith("0x") and len(tx_hash) == 66):
            continue
        sender, to, contract = _addr(r.get("from")), _addr(r.get("to")), _addr(r.get("contractAddress"))
        if me not in (sender, to) or not contract:
            continue
        decimals = min(max(_int(r.get("tokenDecimal"), 18), 0), 36)
        raw = _int(r.get("value"))
        if raw == 0:
            hidden += 1
            continue
        symbol = "".join(ch for ch in str(r.get("tokenSymbol") or "") if ch.isprintable()).strip()[:20] or "?"
        if sender == me and to == me:
            direction, other = DIR_SELF, me
        elif sender == me:
            direction, other = DIR_OUT, to
        else:
            direction, other = DIR_IN, sender
        out.append(HistoryItem(
            network=network, tx_hash=tx_hash, timestamp=_int(r.get("timeStamp")), direction=direction,
            symbol=symbol, amount=Decimal(raw).scaleb(-decimals), counterparty=other, status=ST_SUCCESS,
            token_address=contract, known_token=contract in known,
        ))
    return out, hidden


def merge(network: str, txs: list[HistoryItem], transfers: list[HistoryItem]) -> list[HistoryItem]:
    """Satu transaksi bisa muncul sebagai 'panggilan kontrak' (txlist) sekaligus transfer token (tokentx);
    tampilkan hanya transfer tokennya."""
    # Beberapa explorer ikut mencantumkan transfer koin native di daftar token, dengan simbol kosong.
    # Itu duplikat dari transaksi biasa (hash, arah, dan jumlah sama), jadi dibuang.
    native = {(t.tx_hash, t.direction, t.amount) for t in txs if t.direction != DIR_CALL}
    transfers = [t for t in transfers if not (t.symbol == "?" and (t.tx_hash, t.direction, t.amount) in native)]
    transfer_hashes = {t.tx_hash for t in transfers}
    kept = [t for t in txs if not (t.direction == DIR_CALL and t.status == ST_SUCCESS and t.tx_hash in transfer_hashes)]
    return kept + transfers


def local_item(tx: SentTx) -> HistoryItem:
    return HistoryItem(
        network=tx.network, tx_hash=tx.tx_hash.lower(), timestamp=tx.created_at, direction=DIR_OUT,
        symbol=tx.symbol, amount=Decimal(tx.amount_raw).scaleb(-tx.decimals), counterparty=tx.to_address.lower(),
        status=tx.status, token_address=(tx.token_address or "").lower() or None, local=True,
    )


CACHE_SECONDS = 45          # membuka ulang dialog dalam waktu singkat memakai data ini (hemat kuota API publik)
RETRY_DELAYS = (1.5, 3.0)   # jeda sebelum mencoba ulang saat kena pembatasan laju (rate limit)


PRO_API_URL = "https://api.blockscout.com/{chain_id}/api"   # Blockscout PRO: satu key untuk semua jaringan


def reason_of(exc: Exception) -> str:
    """Alasan singkat dari galat HTTP, tanpa URL panjang dan tanpa API key, agar aman ditampilkan."""
    text = re.sub(r"apikey=[^&\s]+", "apikey=***", str(exc), flags=re.IGNORECASE)
    text = re.sub(r"^https?://\S+?: ", "", text).strip()
    return text[:110] or "tidak diketahui"


def _is_rate_limit(text: str) -> bool:
    t = text.lower()
    return "429" in t or "too many" in t or "rate limit" in t


_EMPTY_MESSAGES = ("no transactions found", "no records found", "no token transfers found")


class HistoryService:
    def __init__(self, http: HttpClient, rpc_for: Callable[[str], RpcClient], timeout: float = 10.0,
                 sleep: Callable[[float], None] = time.sleep):
        self.http = http
        self.rpc_for = rpc_for
        self.timeout = timeout
        self._sleep = sleep
        self.last_token_error = ""
        self._cache: dict[tuple[str, str], tuple[float, list[HistoryItem], int, bool]] = {}

    def _query(self, network: str, action: str, address: str, api_key: str = "") -> list[dict]:
        """Satu panggilan API explorer; mencoba ulang bila kena rate limit. Lempar HttpError bila tetap gagal."""
        for delay in (*RETRY_DELAYS, None):
            try:
                return self._query_once(network, action, address, api_key)
            except HttpError as exc:
                if delay is None or not _is_rate_limit(str(exc)):
                    raise
                self._sleep(delay)
        raise HttpError("tidak mungkin tercapai")   # pragma: no cover

    def _query_once(self, network: str, action: str, address: str, api_key: str = "") -> list[dict]:
        """Satu panggilan API explorer. Lempar HttpError dengan pesan yang bisa ditampilkan."""
        net = NETWORKS[network]
        params = {"module": "account", "action": action, "address": address, "sort": "desc",
                  "page": "1", "offset": str(PAGE_SIZE)}
        if api_key:                                   # key hanya dikirim ke api.blockscout.com (https)
            base = PRO_API_URL.format(chain_id=net.chain_id)
            params["apikey"] = api_key
        else:
            base = net.history_api
        if not base:
            raise HttpError("Jaringan ini belum punya sumber riwayat.")
        data = self.http.get_json(base, params, self.timeout)
        if not isinstance(data, dict):
            raise HttpError("Respons explorer tidak valid.")
        result = data.get("result")
        if isinstance(result, list):
            return result
        message = str(data.get("message", "")).lower()
        if any(m in message for m in _EMPTY_MESSAGES) or result is None:
            return []
        raise HttpError(f"Explorer menolak permintaan: {str(result)[:120]}")

    def load_network(self, network: str, address: str, known: set[str], api_key: str = "") -> tuple[list[HistoryItem], int, bool]:
        """(item, jumlah transfer nol yang disembunyikan, transfer token gagal dimuat?)."""
        txs = parse_txlist(self._query(network, "txlist", address, api_key), address, network)
        try:
            transfers, hidden = parse_tokentx(self._query(network, "tokentx", address, api_key), address, network, known)
        except HttpError as exc:
            self.last_token_error = reason_of(exc)
            return txs, 0, True              # transaksi koin native tetap tampil; hanya transfer token yang kurang
        return merge(network, txs, transfers), hidden, False

    def load(
        self,
        address: str,
        mode: str,
        local: Sequence[SentTx] = (),
        known_tokens: Iterable[Token] = (),
        force: bool = False,
        api_key: str = "",
    ) -> HistoryResult:
        networks = list(MODES[mode])
        known = {t.address.lower() for t in known_tokens if t.address}
        result = HistoryResult()

        def work(net: str):
            key = (address.lower(), net)
            cached = self._cache.get(key)
            if cached and not force and time.time() - cached[0] < CACHE_SECONDS:
                return net, cached[1:], None
            try:
                data = self.load_network(net, address, known, api_key)
            except HttpError as exc:
                if cached:                                   # gagal, tetapi ada data lama: lebih baik daripada kosong
                    return net, cached[1:], f"data lama ditampilkan ({reason_of(exc)})"
                return net, None, reason_of(exc)
            if not data[2]:                                  # hanya simpan hasil yang lengkap
                self._cache[key] = (time.time(), *data)
            return net, data, None

        with ThreadPoolExecutor(max_workers=len(networks)) as pool:
            fetched = list(pool.map(work, networks))

        remote: dict[tuple[str, str], HistoryItem] = {}
        for net, data, error in fetched:
            if error is not None and data is None:
                result.errors.append(f"Riwayat {NETWORKS[net].name} gagal dimuat ({error})")
                continue
            if error is not None:
                result.errors.append(f"Riwayat {NETWORKS[net].name}: {error}")
            items, hidden, tokens_failed = data
            if tokens_failed:
                result.errors.append(f"Transfer token {NETWORKS[net].name} gagal dimuat ({self.last_token_error})")
            result.hidden_zero += hidden
            for it in items:
                remote.setdefault((it.network, it.tx_hash + (it.token_address or "")), it)

        remote_hashes = {(it.network, it.tx_hash) for it in remote.values()}
        items = list(remote.values())
        for tx in local:
            if tx.network not in networks:
                continue
            status, block = tx.status, tx.block
            if status == ST_PENDING:
                rec = fetch_receipt(self.rpc_for(tx.network), tx.tx_hash)
                if rec is not None:
                    status, block = (ST_SUCCESS if rec.success else ST_FAILED), rec.block
                    result.updates.append((tx.network, tx.tx_hash, status, block))
            if (tx.network, tx.tx_hash.lower()) in remote_hashes:
                continue                      # explorer sudah punya; datanya yang dipakai
            li = local_item(tx)
            items.append(HistoryItem(**{**li.__dict__, "status": status}))
        items.sort(key=lambda i: i.timestamp, reverse=True)
        result.items = items
        return result
