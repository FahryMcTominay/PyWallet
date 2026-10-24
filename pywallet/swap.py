"""Swap token (tahap 5): kutipan harga, izin (approve), dan transaksi tukar lewat kontrak DEX.

Lapisan ini tidak menyentuh UI dan tidak memakai API pihak ketiga: semua lewat panggilan RPC langsung ke kontrak.
DEX dibuat sebagai "penyedia" (`DexProvider`) supaya DEX lain bisa ditambahkan tanpa menulis ulang. Saat ini ada
satu keluarga kontrak, Uniswap V3 (PancakeSwap V3 adalah fork dengan antarmuka yang sama, jadi cukup menambah
alamatnya di `PROVIDERS` ketika jaringannya sudah didukung).

Alur satu swap (tanda tangan tetap di Vault, butuh master password):
  1. `prepare_swap`      : kutipan harga terbaik dari beberapa fee tier + allowance + data jaringan -> `SwapPlan`
  2. bila perlu izin    : `prepare_call` (approve) -> Vault.sign_transfer -> `tx.broadcast` -> `wait_receipt`
  3. `prepare_call`     : estimasi gas transaksi swap yang sebenarnya -> Vault.sign_transfer -> `tx.broadcast`
Memakai jumlah masukan pasti (exactInputSingle) dengan batas minimum penerimaan (slippage) dan batas waktu.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Callable

from eth_abi import decode, encode
from eth_utils import keccak, to_checksum_address

from . import tx
from .networks import NETWORKS, Network
from .rpc import RpcClient, RpcError, parse_uint
from .tokens import Token

ADDRESS_THIS = "0x0000000000000000000000000000000000000002"   # penanda "router sendiri" pada SwapRouter02
DEFAULT_SLIPPAGE_BPS = 50                                      # 0,5%
MAX_SLIPPAGE_BPS = 5000                                        # 50%
WARN_SLIPPAGE_BPS = 500                                        # di atas 5% diberi peringatan
SLIPPAGE_PRESETS_BPS = (50, 100, 300)
DEADLINE_SECONDS = 20 * 60
QUOTE_MAX_AGE = 45                                             # detik; harga lebih tua dari ini diperbarui dulu
ROUTER_GAS_OVERHEAD = 100_000                                  # tambahan di atas estimasi pool untuk tampilan biaya
APPROVE_GAS_ESTIMATE = 60_000
RECEIPT_WAIT_ATTEMPTS = 60
RECEIPT_WAIT_SECONDS = 3.0


def _sel(signature: str) -> str:
    return keccak(text=signature)[:4].hex()


SEL_QUOTE = _sel("quoteExactInputSingle((address,address,uint256,uint24,uint160))")
SEL_SWAP = _sel("exactInputSingle((address,address,uint24,address,uint256,uint256,uint160))")
SEL_MULTICALL = _sel("multicall(uint256,bytes[])")
SEL_UNWRAP = _sel("unwrapWETH9(uint256,address)")
SEL_ALLOWANCE = _sel("allowance(address,address)")
SEL_APPROVE = _sel("approve(address,uint256)")


class SwapError(Exception):
    """Pesan aman ditampilkan ke pengguna."""


@dataclass(frozen=True)
class DexProvider:
    key: str
    name: str
    network: str
    router: str
    quoter: str
    factory: str
    weth: str
    fee_tiers: tuple[int, ...] = (500, 3000, 10000, 100)      # dalam seperjuta (3000 = 0,3%)


# Alamat resmi dari dokumentasi Uniswap (developers.uniswap.org -> V3 deployments), diperiksa 2026-10.
PROVIDERS: dict[str, tuple[DexProvider, ...]] = {
    "sepolia": (
        DexProvider(
            key="uniswap-v3", name="Uniswap V3", network="sepolia",
            router="0x3bFA4769FB09eefC5a80d6E87c3B9C650f7Ae48E",
            quoter="0xEd1f6473345F45b75F8179591dd5bA1888cf2FB3",
            factory="0x0227628f3F023bb0B980b67D528571c95c6DaC1c",
            weth="0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14",
        ),
    ),
}


def providers_for(network: str) -> tuple[DexProvider, ...]:
    return PROVIDERS.get(network, ())


def swap_networks(networks: tuple[str, ...]) -> tuple[str, ...]:
    """Subset `networks` (urutan dipertahankan) yang punya setidaknya satu DEX."""
    return tuple(n for n in networks if providers_for(n))


# --------------------------------------------------------------------------
# Validasi & encoding
# --------------------------------------------------------------------------
def parse_slippage(text: str) -> int:
    """Teks persen (mis. '0,5' atau '1') -> basis poin (50, 100)."""
    raw = (text or "").strip().replace("%", "").replace(" ", "").replace(",", ".")
    if not raw or any(c not in "0123456789." for c in raw) or raw.count(".") > 1:
        raise SwapError("Slippage tidak valid. Isi angka persen, mis. 0.5")
    try:
        bps = int((Decimal(raw) * 100).to_integral_value())
    except InvalidOperation as exc:
        raise SwapError("Slippage tidak valid.") from exc
    if bps < 1:
        raise SwapError("Slippage minimal 0,01%.")
    if bps > MAX_SLIPPAGE_BPS:
        raise SwapError("Slippage maksimal 50%.")
    return bps


def min_out_for(amount_out: int, slippage_bps: int) -> int:
    return amount_out * (10_000 - slippage_bps) // 10_000


def _addr(value: str) -> str:
    return to_checksum_address(value)


def encode_quote(token_in: str, token_out: str, amount_in: int, fee: int) -> str:
    args = encode(["(address,address,uint256,uint24,uint160)"], [(_addr(token_in), _addr(token_out), amount_in, fee, 0)])
    return "0x" + SEL_QUOTE + args.hex()


def encode_allowance(owner: str, spender: str) -> str:
    return "0x" + SEL_ALLOWANCE + encode(["address", "address"], [_addr(owner), _addr(spender)]).hex()


def encode_approve(spender: str, amount: int) -> str:
    return "0x" + SEL_APPROVE + encode(["address", "uint256"], [_addr(spender), amount]).hex()


def encode_swap(
    provider: DexProvider, token_in: str, token_out: str, fee: int, amount_in: int, min_out: int,
    recipient: str, unwrap_native_out: bool, deadline: int,
) -> str:
    """multicall(deadline, [exactInputSingle, (unwrapWETH9)]). Bila keluaran koin native, WETH diterima router lalu dibuka."""
    swap_recipient = ADDRESS_THIS if unwrap_native_out else _addr(recipient)
    swap_call = bytes.fromhex(SEL_SWAP) + encode(
        ["(address,address,uint24,address,uint256,uint256,uint160)"],
        [(_addr(token_in), _addr(token_out), fee, swap_recipient, amount_in, min_out, 0)],
    )
    calls = [swap_call]
    if unwrap_native_out:
        calls.append(bytes.fromhex(SEL_UNWRAP) + encode(["uint256", "address"], [min_out, _addr(recipient)]))
    return "0x" + SEL_MULTICALL + encode(["uint256", "bytes[]"], [deadline, calls]).hex()


# --------------------------------------------------------------------------
# Kutipan harga
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Quote:
    fee: int                 # fee tier pool terpilih
    amount_out: int          # satuan terkecil token tujuan
    gas_estimate: int        # estimasi gas bagian pool (belum termasuk overhead router)


def _decode_quote(result) -> Quote | None:
    """Hasil eth_call QuoterV2 -> (amountOut, sqrtPriceX96After, ticksCrossed, gasEstimate); None bila bukan hasil valid."""
    if not isinstance(result, str) or len(result) < 2 + 4 * 64:
        return None
    try:
        amount_out, _price, _ticks, gas = decode(["uint256", "uint160", "uint32", "uint256"], bytes.fromhex(result[2:]))
    except Exception:  # noqa: BLE001
        return None
    return Quote(0, amount_out, gas) if amount_out > 0 else None


def pick_best(provider: DexProvider, results: list) -> Quote | None:
    """Pilih fee tier dengan keluaran terbanyak dari hasil batch (satu hasil per fee tier, urutannya sama)."""
    best: Quote | None = None
    for fee, res in zip(provider.fee_tiers, results):
        if isinstance(res, RpcError):
            continue
        q = _decode_quote(res)
        if q is not None and (best is None or q.amount_out > best.amount_out):
            best = Quote(fee, q.amount_out, q.gas_estimate)
    return best


def swap_tokens(provider: DexProvider, sell: Token, buy: Token) -> tuple[str, str]:
    """Alamat token masuk/keluar untuk kontrak. Koin native diperlakukan sebagai WETH milik DEX."""
    if sell.network != provider.network or buy.network != provider.network:
        raise SwapError("Token tidak cocok dengan jaringan DEX.")
    token_in = provider.weth if sell.is_native else (sell.address or "")
    token_out = provider.weth if buy.is_native else (buy.address or "")
    if not token_in or not token_out or token_in.lower() == token_out.lower():
        raise SwapError(
            "Token asal dan tujuan harus berbeda. Menukar koin native dengan versi bungkusnya (WETH) "
            "bukan swap; tidak ada kolam untuk itu."
        )
    return _addr(token_in), _addr(token_out)


# --------------------------------------------------------------------------
# Rencana swap
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SwapPlan:
    provider: DexProvider
    network: str
    sell: Token
    buy: Token
    sender: str
    amount_in: int
    quote: Quote
    slippage_bps: int
    balance: int                 # saldo token jual (satuan terkecil)
    native_balance: int
    allowance: int               # izin token jual untuk router (native: tidak berlaku)
    chain_id: int
    eip1559: bool
    fees: dict[str, tx.FeeOption]
    token_in: str
    token_out: str
    created_at: float = field(default_factory=time.time)

    @property
    def min_out(self) -> int:
        return min_out_for(self.quote.amount_out, self.slippage_bps)

    @property
    def needs_approval(self) -> bool:
        return not self.sell.is_native and self.allowance < self.amount_in

    @property
    def unwrap_native_out(self) -> bool:
        return self.buy.is_native

    @property
    def rate(self) -> Decimal:
        """Berapa token tujuan untuk 1 token asal (tanpa memperhitungkan fee)."""
        sold = tx.to_units(self.amount_in, self.sell.decimals)
        got = tx.to_units(self.quote.amount_out, self.buy.decimals)
        return got / sold if sold else Decimal(0)

    def est_gas(self) -> int:
        gas = self.quote.gas_estimate + ROUTER_GAS_OVERHEAD
        return gas + (APPROVE_GAS_ESTIMATE if self.needs_approval else 0)

    def est_fee_wei(self, speed: str = tx.SPEED_NORMAL) -> int:
        return self.est_gas() * self.fees[speed].max_fee_per_gas

    def check_funds(self, speed: str = tx.SPEED_NORMAL) -> None:
        if self.amount_in > self.balance:
            raise SwapError(f"Saldo {self.sell.symbol} tidak cukup.")
        fee = self.est_fee_wei(speed)
        native = NETWORKS[self.network].native_symbol
        need = fee + (self.amount_in if self.sell.is_native else 0)
        if need > self.native_balance:
            raise SwapError(
                f"Saldo {native} tidak cukup untuk jumlah ini ditambah biaya gas "
                f"(perkiraan maks {tx.to_units(fee, 18):.6f} {native})."
            )

    def swap_calldata(self, deadline: int | None = None) -> str:
        return encode_swap(
            self.provider, self.token_in, self.token_out, self.quote.fee, self.amount_in, self.min_out,
            self.sender, self.unwrap_native_out, deadline if deadline is not None else int(time.time()) + DEADLINE_SECONDS,
        )

    def swap_value(self) -> int:
        return self.amount_in if self.sell.is_native else 0

    def approve_calldata(self) -> str:
        return encode_approve(self.provider.router, self.amount_in)      # izin sebesar jumlah ini saja, bukan tak terbatas


def friendly_swap_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "too little received" in msg or "stf" in msg or "slippage" in msg:
        return "Harga bergeser melebihi batas slippage. Coba lagi atau naikkan slippage."
    if "transaction too old" in msg or "deadline" in msg:
        return "Batas waktu transaksi terlewati. Coba lagi."
    if "transfer_from_failed" in msg or "allowance" in msg or "insufficient allowance" in msg:
        return "Izin token ke router belum tercatat. Coba lagi."
    return tx.friendly_rpc_error(exc)


def prepare_swap(
    rpc: RpcClient,
    network: Network,
    provider: DexProvider,
    sell: Token,
    buy: Token,
    amount_in: int,
    sender: str,
    balance: int,
    slippage_bps: int = DEFAULT_SLIPPAGE_BPS,
) -> SwapPlan:
    """Satu permintaan batch: kutipan tiap fee tier, allowance, chain ID, nonce-free fee data, dan saldo native."""
    if provider.network != network.key:
        raise SwapError("DEX tidak cocok dengan jaringan.")
    if amount_in <= 0:
        raise SwapError("Jumlah harus lebih besar dari nol.")
    if amount_in > balance:
        raise SwapError(f"Saldo {sell.symbol} tidak cukup.")
    token_in, token_out = swap_tokens(provider, sell, buy)

    calls: list[tuple[str, list]] = [
        ("eth_call", [{"to": provider.quoter, "data": encode_quote(token_in, token_out, amount_in, fee)}, "latest"])
        for fee in provider.fee_tiers
    ]
    n_quotes = len(calls)
    calls += [
        ("eth_chainId", []),
        ("eth_getBlockByNumber", ["latest", False]),
        ("eth_maxPriorityFeePerGas", []),
        ("eth_gasPrice", []),
        ("eth_getBalance", [sender, "latest"]),
    ]
    if not sell.is_native:
        calls.append(("eth_call", [{"to": sell.address, "data": encode_allowance(sender, provider.router)}, "latest"]))
    out = rpc.batch(calls)
    quotes, (chain_r, block_r, tip_r, price_r, native_r), rest = out[:n_quotes], out[n_quotes:n_quotes + 5], out[n_quotes + 5:]

    if isinstance(chain_r, RpcError):
        raise SwapError("Tidak bisa terhubung ke jaringan. Periksa koneksi internet lalu coba lagi.")
    try:
        chain_id = parse_uint(chain_r)
    except RpcError as exc:
        raise SwapError("Respons jaringan tidak valid.") from exc
    if chain_id != network.chain_id:
        raise SwapError(
            f"RPC mengaku jaringan dengan chain ID {chain_id}, padahal {network.name} adalah {network.chain_id}. "
            "Dibatalkan demi keamanan."
        )

    best = pick_best(provider, quotes)
    if best is None:
        raise SwapError(
            f"Tidak ada kolam likuiditas {provider.name} untuk pasangan {sell.symbol}/{buy.symbol} di {network.name} "
            "(atau jumlahnya terlalu besar untuk likuiditas yang ada). Coba pasangan atau jumlah lain."
        )

    def _int(r) -> int | None:
        if isinstance(r, RpcError) or r in (None, "0x", ""):
            return None
        try:
            return parse_uint(r)
        except RpcError:
            return None

    base_fee = _int(block_r["baseFeePerGas"]) if isinstance(block_r, dict) and block_r.get("baseFeePerGas") is not None else None
    try:
        eip1559, fees = tx.build_fees(base_fee, _int(tip_r) or tx.DEFAULT_TIP, _int(price_r))
    except tx.TransferError as exc:
        raise SwapError(str(exc)) from exc
    native_balance = _int(native_r)
    if native_balance is None:
        native_balance = balance if sell.is_native else 0
    allowance = 0
    if not sell.is_native:
        allowance = _int(rest[0]) if rest else 0
        allowance = allowance or 0

    plan = SwapPlan(
        provider=provider, network=network.key, sell=sell, buy=buy, sender=sender, amount_in=amount_in, quote=best,
        slippage_bps=slippage_bps, balance=balance, native_balance=native_balance, allowance=allowance,
        chain_id=chain_id, eip1559=eip1559, fees=fees, token_in=token_in, token_out=token_out,
    )
    plan.check_funds()
    return plan


# --------------------------------------------------------------------------
# Transaksi panggilan kontrak umum (approve dan swap)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CallPlan:
    network: str
    to: str
    data: str
    value: int
    sender: str
    nonce: int
    gas_limit: int
    eip1559: bool
    fees: dict[str, tx.FeeOption]
    chain_id: int
    native_balance: int
    created_at: float = field(default_factory=time.time)

    def fee_wei(self, speed: str) -> int:
        return self.gas_limit * self.fees[speed].max_fee_per_gas

    def check_funds(self, speed: str) -> None:
        if self.value + self.fee_wei(speed) > self.native_balance:
            raise SwapError("Saldo koin native tidak cukup untuk jumlah dan biaya gas transaksi ini.")

    def tx_fields(self, speed: str) -> dict:
        fee = self.fees[speed]
        fields: dict = {
            "chainId": self.chain_id, "nonce": self.nonce, "gas": self.gas_limit,
            "to": self.to, "value": self.value, "data": self.data,
        }
        if self.eip1559:
            fields["type"] = 2
            fields["maxFeePerGas"] = fee.max_fee_per_gas
            fields["maxPriorityFeePerGas"] = fee.max_priority_fee
        else:
            fields["gasPrice"] = fee.max_fee_per_gas
        return fields


def prepare_call(
    rpc: RpcClient, network: Network, sender: str, to: str, data: str, value: int = 0,
    speed: str = tx.SPEED_NORMAL,
) -> CallPlan:
    """Nonce, biaya, dan estimasi gas untuk satu panggilan kontrak. Estimasi yang gagal berarti transaksi akan ditolak."""
    (chain, nonce_r, block_r, tip_r, price_r, native_r, gas_r) = rpc.batch([
        ("eth_chainId", []),
        ("eth_getTransactionCount", [sender, "pending"]),
        ("eth_getBlockByNumber", ["latest", False]),
        ("eth_maxPriorityFeePerGas", []),
        ("eth_gasPrice", []),
        ("eth_getBalance", [sender, "latest"]),
        ("eth_estimateGas", [{"from": sender, "to": to, "data": data, "value": hex(value)}]),
    ])
    if isinstance(chain, RpcError) or isinstance(nonce_r, RpcError):
        raise SwapError("Tidak bisa terhubung ke jaringan. Periksa koneksi internet lalu coba lagi.")
    try:
        chain_id, nonce = parse_uint(chain), parse_uint(nonce_r)
    except RpcError as exc:
        raise SwapError("Respons jaringan tidak valid.") from exc
    if chain_id != network.chain_id:
        raise SwapError("Chain ID RPC tidak cocok dengan jaringan. Transaksi dibatalkan demi keamanan.")

    def _int(r) -> int | None:
        if isinstance(r, RpcError) or r in (None, "0x", ""):
            return None
        try:
            return parse_uint(r)
        except RpcError:
            return None

    base_fee = _int(block_r["baseFeePerGas"]) if isinstance(block_r, dict) and block_r.get("baseFeePerGas") is not None else None
    try:
        eip1559, fees = tx.build_fees(base_fee, _int(tip_r) or tx.DEFAULT_TIP, _int(price_r))
    except tx.TransferError as exc:
        raise SwapError(str(exc)) from exc
    if isinstance(gas_r, RpcError):
        raise SwapError(friendly_swap_error(gas_r))
    gas = _int(gas_r)
    if not gas:
        raise SwapError("Estimasi gas gagal.")
    plan = CallPlan(
        network=network.key, to=to, data=data, value=value, sender=sender, nonce=nonce,
        gas_limit=tx._scale(gas, 1.25), eip1559=eip1559, fees=fees, chain_id=chain_id,
        native_balance=_int(native_r) or 0,
    )
    plan.check_funds(speed)
    return plan


def wait_receipt(
    rpc: RpcClient, tx_hash: str, attempts: int = RECEIPT_WAIT_ATTEMPTS, delay: float = RECEIPT_WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep, cancelled: Callable[[], bool] = lambda: False,
) -> tx.Receipt | None:
    for i in range(attempts):
        if cancelled():
            return None
        receipt = tx.fetch_receipt(rpc, tx_hash)
        if receipt is not None:
            return receipt
        if i < attempts - 1:
            sleep(delay)
    return None
