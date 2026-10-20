"""Transaksi kirim aset (tahap 4): validasi, estimasi biaya gas, penandatanganan, dan pengiriman.

Lapisan ini tidak menyentuh UI. Alurnya:
  1. `prepare_transfer`  : baca nonce, biaya gas, dan estimasi gas dari jaringan -> `TransferPlan`
  2. `Vault.sign_transfer`: tanda tangani transaksi (butuh master password, kunci tidak keluar dari vault)
  3. `broadcast`         : kirim transaksi yang sudah ditandatangani, lalu `fetch_receipt` untuk status
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from eth_utils import is_checksum_address, to_checksum_address

from .networks import NETWORKS, Network
from .rpc import RpcClient, RpcError, parse_uint
from .tokens import Token

TRANSFER_SELECTOR = "a9059cbb"          # transfer(address,uint256)
NATIVE_TRANSFER_GAS = 21_000
GWEI = 10**9
DEFAULT_TIP = 1 * GWEI                  # cadangan jika jaringan tidak melaporkan priority fee
PLAN_MAX_AGE = 120                      # detik; estimasi biaya yang lebih lama dari ini diperbarui dulu

SPEED_SLOW, SPEED_NORMAL, SPEED_FAST = "slow", "normal", "fast"
SPEEDS = (SPEED_SLOW, SPEED_NORMAL, SPEED_FAST)
SPEED_LABELS = {SPEED_SLOW: "Lambat", SPEED_NORMAL: "Normal", SPEED_FAST: "Cepat"}
# (pengali priority fee, pengali base fee) untuk EIP-1559; pengali gasPrice untuk jaringan lama (legacy)
_EIP1559_FACTORS = {SPEED_SLOW: (1.0, 1.2), SPEED_NORMAL: (1.25, 1.5), SPEED_FAST: (2.0, 2.0)}
_LEGACY_FACTORS = {SPEED_SLOW: 1.0, SPEED_NORMAL: 1.1, SPEED_FAST: 1.3}


class TransferError(Exception):
    """Pesan aman ditampilkan ke pengguna."""


# --------------------------------------------------------------------------
# Validasi input
# --------------------------------------------------------------------------
def normalize_recipient(text: str) -> str:
    """Rapikan alamat tujuan menjadi checksum (EIP-55). Nama ENS belum didukung."""
    raw = (text or "").strip()
    body = raw[2:] if raw[:2].lower() == "0x" else raw
    if raw.lower().endswith(".eth"):
        raise TransferError("Nama ENS belum didukung. Tempel alamat 0x… tujuan.")
    if len(body) != 40 or any(c not in "0123456789abcdefABCDEF" for c in body):
        raise TransferError("Alamat tujuan harus 40 karakter heksadesimal (boleh diawali 0x).")
    if int(body, 16) == 0:
        raise TransferError("Alamat nol (0x000…0) tidak boleh dijadikan tujuan; dana akan hilang.")
    mixed = body != body.lower() and body != body.upper()
    if mixed and not is_checksum_address("0x" + body):
        raise TransferError(
            "Huruf besar/kecil alamat tidak cocok dengan checksum. Kemungkinan ada salah ketik; salin ulang alamatnya."
        )
    return to_checksum_address("0x" + body.lower())


def parse_amount(text: str, decimals: int) -> int:
    """Ubah teks jumlah (boleh koma atau titik sebagai desimal) menjadi satuan terkecil (integer)."""
    raw = (text or "").strip().replace(" ", "")
    if not raw:
        raise TransferError("Masukkan jumlah yang akan dikirim.")
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    if any(c not in "0123456789." for c in raw) or raw.count(".") > 1:
        raise TransferError("Jumlah tidak valid. Gunakan angka saja, mis. 0.25")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise TransferError("Jumlah tidak valid.") from exc
    if value <= 0:
        raise TransferError("Jumlah harus lebih besar dari nol.")
    scaled = value.scaleb(decimals)
    if scaled != scaled.to_integral_value():
        raise TransferError(f"Token ini hanya mendukung sampai {decimals} angka di belakang koma.")
    return int(scaled)


def encode_transfer(to: str, amount: int) -> str:
    return "0x" + TRANSFER_SELECTOR + to.lower().removeprefix("0x").rjust(64, "0") + hex(amount)[2:].rjust(64, "0")


def to_units(raw: int, decimals: int) -> Decimal:
    return Decimal(raw).scaleb(-decimals)


def friendly_rpc_error(exc: Exception) -> str:
    """Terjemahkan galat umum dari node ke bahasa yang bisa dipahami."""
    msg = str(exc).lower()
    if "insufficient funds" in msg:
        return "Saldo koin native tidak cukup untuk membayar biaya gas."
    if "nonce too low" in msg:
        return "Nonce sudah terpakai. Ada transaksi lain yang baru selesai; coba ulang."
    if "already known" in msg or "known transaction" in msg:
        return "Transaksi yang sama sudah dikirim sebelumnya."
    if "underpriced" in msg or "fee too low" in msg or "max fee per gas less than" in msg:
        return "Biaya gas terlalu rendah untuk kondisi jaringan saat ini. Pilih kecepatan lebih tinggi."
    if "execution reverted" in msg or "revert" in msg:
        return "Kontrak menolak transaksi ini (kemungkinan saldo token tidak cukup atau token membatasi transfer)."
    if "exceeds block gas limit" in msg or "gas limit" in msg:
        return "Batas gas tidak valid untuk jaringan ini."
    text = str(exc).strip()
    return text if text else "Jaringan menolak transaksi."


# --------------------------------------------------------------------------
# Rencana transaksi (hasil `prepare_transfer`)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class FeeOption:
    """Biaya untuk satu pilihan kecepatan. `max_fee_per_gas` juga dipakai sebagai gasPrice pada jaringan legacy."""
    max_fee_per_gas: int
    max_priority_fee: int


@dataclass(frozen=True)
class TransferPlan:
    network: str
    token: Token
    sender: str
    to: str
    amount: int                      # satuan terkecil (untuk send_max native: saldo penuh, dikurangi biaya saat `final_amount`)
    send_max: bool
    balance: int
    nonce: int
    gas_limit: int
    eip1559: bool
    fees: dict[str, FeeOption]
    chain_id: int
    native_balance: int              # saldo koin native pengirim (untuk membayar gas)
    warnings: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)

    def fee_wei(self, speed: str) -> int:
        """Biaya gas maksimum (batas atas; biaya sesungguhnya biasanya lebih kecil)."""
        return self.gas_limit * self.fees[speed].max_fee_per_gas

    def final_amount(self, speed: str) -> int:
        """Jumlah yang benar-benar dikirim. Untuk 'kirim maks' koin native, biaya gas dikurangkan dulu."""
        if self.send_max and self.token.is_native:
            return self.balance - self.fee_wei(speed)
        return self.amount

    def check_funds(self, speed: str) -> None:
        """Lempar TransferError jika saldo tidak cukup untuk jumlah + biaya gas."""
        amount = self.final_amount(speed)
        fee = self.fee_wei(speed)
        if self.token.is_native:
            if amount <= 0:
                raise TransferError("Saldo tidak cukup untuk membayar biaya gas.")
            if amount + fee > self.native_balance:
                raise TransferError(
                    f"Saldo {self.token.symbol} tidak cukup untuk jumlah ini ditambah biaya gas "
                    f"(maks {to_units(fee, 18):.8f} {self.token.symbol})."
                )
        else:
            if amount > self.balance:
                raise TransferError(f"Saldo {self.token.symbol} tidak cukup.")
            if fee > self.native_balance:
                raise TransferError(
                    f"Kamu butuh koin native jaringan ini untuk membayar biaya gas "
                    f"(maks {to_units(fee, 18):.8f})."
                )

    def tx_fields(self, speed: str) -> dict:
        """Bidang transaksi siap tanda tangan (format eth-account)."""
        amount = self.final_amount(speed)
        fee = self.fees[speed]
        if self.token.is_native:
            to, value, data = self.to, amount, "0x"
        else:
            to, value, data = self.token.address, 0, encode_transfer(self.to, amount)
        tx: dict = {
            "chainId": self.chain_id,
            "nonce": self.nonce,
            "gas": self.gas_limit,
            "to": to,
            "value": value,
            "data": data,
        }
        if self.eip1559:
            tx["type"] = 2
            tx["maxFeePerGas"] = fee.max_fee_per_gas
            tx["maxPriorityFeePerGas"] = fee.max_priority_fee
        else:
            tx["gasPrice"] = fee.max_fee_per_gas
        return tx


def _scale(value: int, factor: float) -> int:
    return int(value * factor + 0.5)


def build_fees(base_fee: int | None, tip: int, gas_price: int | None) -> tuple[bool, dict[str, FeeOption]]:
    if base_fee is not None:
        fees = {}
        for speed, (tip_f, base_f) in _EIP1559_FACTORS.items():
            t = max(_scale(tip, tip_f), 1)
            fees[speed] = FeeOption(_scale(base_fee, base_f) + t, t)
        return True, fees
    if not gas_price:
        raise TransferError("Tidak bisa membaca biaya gas dari jaringan.")
    return False, {s: FeeOption(_scale(gas_price, f), 0) for s, f in _LEGACY_FACTORS.items()}


def prepare_transfer(
    rpc: RpcClient,
    network: Network,
    token: Token,
    sender: str,
    to: str,
    amount: int,
    balance: int,
    send_max: bool = False,
) -> TransferPlan:
    """Kumpulkan semua data jaringan yang dibutuhkan sebelum pengguna mengonfirmasi.

    Satu permintaan batch: chain ID, nonce, blok terakhir (base fee), priority fee, gasPrice,
    kode di alamat tujuan, saldo native, dan estimasi gas.
    """
    if token.network != network.key:
        raise TransferError("Token tidak cocok dengan jaringan.")
    if to.lower() == sender.lower():
        raise TransferError("Alamat tujuan sama dengan alamat wallet kamu sendiri.")
    if amount <= 0:
        raise TransferError("Jumlah harus lebih besar dari nol.")
    if amount > balance:
        raise TransferError(f"Saldo {token.symbol} tidak cukup.")

    if token.is_native:
        est_tx = {"from": sender, "to": to, "value": hex(0 if send_max else amount)}
    else:
        est_tx = {"from": sender, "to": token.address, "data": encode_transfer(to, amount)}

    (chain, nonce_r, block_r, tip_r, price_r, code_r, native_r, gas_r) = rpc.batch([
        ("eth_chainId", []),
        ("eth_getTransactionCount", [sender, "pending"]),
        ("eth_getBlockByNumber", ["latest", False]),
        ("eth_maxPriorityFeePerGas", []),
        ("eth_gasPrice", []),
        ("eth_getCode", [to, "latest"]),
        ("eth_getBalance", [sender, "latest"]),
        ("eth_estimateGas", [est_tx]),
    ])
    if isinstance(chain, RpcError) or isinstance(nonce_r, RpcError):
        raise TransferError("Tidak bisa terhubung ke jaringan. Periksa koneksi internet lalu coba lagi.")
    try:
        chain_id = parse_uint(chain)
        nonce = parse_uint(nonce_r)
    except RpcError as exc:
        raise TransferError("Respons jaringan tidak valid.") from exc
    if chain_id != network.chain_id:
        raise TransferError(
            f"RPC mengaku jaringan dengan chain ID {chain_id}, padahal {network.name} adalah {network.chain_id}. "
            "Transaksi dibatalkan demi keamanan."
        )

    def _int(r) -> int | None:
        if isinstance(r, RpcError) or r in (None, "0x", ""):
            return None
        try:
            return parse_uint(r)
        except RpcError:
            return None

    base_fee = None
    if isinstance(block_r, dict) and block_r.get("baseFeePerGas") is not None:
        base_fee = _int(block_r["baseFeePerGas"])
    tip = _int(tip_r) or DEFAULT_TIP
    eip1559, fees = build_fees(base_fee, tip, _int(price_r))

    if isinstance(gas_r, RpcError):
        raise TransferError(friendly_rpc_error(gas_r))
    gas = _int(gas_r)
    if not gas:
        raise TransferError("Estimasi gas gagal.")
    if token.is_native and gas == NATIVE_TRANSFER_GAS:
        gas_limit = gas                                  # transfer biasa ke akun: tepat 21.000
    else:
        gas_limit = _scale(gas, 1.2)                     # ruang aman 20% untuk kontrak

    warnings: list[str] = []
    to_has_code = not isinstance(code_r, RpcError) and code_r not in (None, "0x", "")
    if not token.is_native and token.address and to.lower() == token.address.lower():
        raise TransferError("Alamat tujuan adalah kontrak token itu sendiri; token yang dikirim ke sana akan hilang.")
    if to_has_code:
        warnings.append(
            "Alamat tujuan adalah sebuah kontrak, bukan akun biasa. Pastikan kontrak itu memang bisa menerima "
            "aset ini; jika tidak, dana bisa tersangkut."
        )
    native_balance = _int(native_r)
    if native_balance is None:
        native_balance = balance if token.is_native else 0
    plan = TransferPlan(
        network=network.key, token=token, sender=sender, to=to, amount=amount, send_max=send_max,
        balance=balance, nonce=nonce, gas_limit=gas_limit, eip1559=eip1559, fees=fees,
        chain_id=chain_id, native_balance=native_balance, warnings=tuple(warnings),
    )
    # Periksa kecukupan dana pada kecepatan paling lambat; kecepatan lain diperiksa saat dipilih.
    plan.check_funds(SPEED_SLOW)
    return plan


# --------------------------------------------------------------------------
# Kirim & pantau
# --------------------------------------------------------------------------
def broadcast(rpc: RpcClient, raw_tx: str) -> str:
    """Kirim transaksi bertanda tangan; kembalikan hash transaksi."""
    try:
        tx_hash = rpc.call("eth_sendRawTransaction", [raw_tx])
    except RpcError as exc:
        raise TransferError(friendly_rpc_error(exc)) from exc
    if not isinstance(tx_hash, str) or not tx_hash.startswith("0x"):
        raise TransferError("Jaringan tidak mengembalikan hash transaksi.")
    return tx_hash


@dataclass(frozen=True)
class Receipt:
    success: bool
    block: int | None


def fetch_receipt(rpc: RpcClient, tx_hash: str) -> Receipt | None:
    """None = belum masuk blok. Galat jaringan juga dianggap 'belum' agar pemantauan terus mencoba."""
    try:
        data = rpc.call("eth_getTransactionReceipt", [tx_hash])
    except RpcError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        status = parse_uint(data.get("status"))
        block = parse_uint(data.get("blockNumber"))
    except RpcError:
        return None
    return Receipt(success=status == 1, block=block)


def explorer_tx_url(network: str, tx_hash: str) -> str:
    base = NETWORKS[network].explorer
    return f"{base}/tx/{tx_hash}" if base else ""
