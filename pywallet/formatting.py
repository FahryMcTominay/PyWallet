"""Pemformatan angka: USD, Rupiah, jumlah token, harga, dan persen."""
from __future__ import annotations

import math
from decimal import Decimal

UNIT_USD = "usd"
UNIT_IDR = "idr"
UNIT_ETH = "eth"
UNITS = (UNIT_USD, UNIT_IDR, UNIT_ETH)


def format_usd(value: float) -> str:
    if 0 < value < 0.01:
        return "<$0.01"
    return f"${value:,.2f}"


def format_idr(value: float) -> str:
    if 0 < value < 1:
        return "<Rp1"
    return "Rp" + f"{round(value):,}".replace(",", ".")


def _trim(text: str) -> str:
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_amount(amount: Decimal) -> str:
    """Jumlah token: ringkas dan tidak menyesatkan untuk nilai kecil maupun besar."""
    if amount == 0:
        return "0"
    a = abs(amount)
    if a >= 1000:
        return _trim(f"{amount.quantize(Decimal('0.01')):,.2f}")
    if a >= 1:
        return _trim(f"{amount.quantize(Decimal('0.0001')):,.4f}")
    q = amount.quantize(Decimal("0.000001"))
    if q == 0:
        return "<0.000001"
    return _trim(f"{q:.6f}")


def format_eth(amount: Decimal | float) -> str:
    d = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
    if d == 0:
        return "0 ETH"
    if abs(d) >= 1000:
        return f"{_trim(f'{d.quantize(Decimal('0.01')):,.2f}')} ETH"
    q = d.quantize(Decimal("0.000001"))
    if q == 0:
        return "<0.000001 ETH"
    return f"{_trim(f'{q:.6f}')} ETH"


def format_price(price: float) -> str:
    """Harga satuan; untuk koin murah (SHIB, PEPE) tampilkan cukup digit signifikan."""
    if price >= 1:
        return f"${price:,.2f}"
    if price >= 0.01:
        return f"${price:.4f}"
    if price <= 0:
        return "$0"
    decimals = min(10, -math.floor(math.log10(price)) + 3)
    return f"${price:.{decimals}f}"


def format_percent(pct: float) -> str:
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.2f}%"
