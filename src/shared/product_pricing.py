"""
Price calculation utilities for Super Order Automation.

This module provides functions for:
1. VAT removal from prices
2. Net price calculation (handling promotions like 11+1)
3. Sell price calculation with .90 rounding
"""

from src.shared.constants import VAT_RATE

# Default VAT rate in Israel (as percentage)
DEFAULT_VAT_RATE = VAT_RATE * 100


def remove_vat(price: float, vat_rate: float = DEFAULT_VAT_RATE) -> float:
    """
    Remove VAT from a price.

    Args:
        price: Price including VAT
        vat_rate: VAT rate as percentage (e.g., 17 for 17%)

    Returns:
        Price excluding VAT

    Example:
        >>> remove_vat(117.0, 17)
        100.0
    """
    if vat_rate <= 0:
        return price
    return price / (1 + vat_rate / 100)


def calculate_net_unit_price(
    raw_unit_price: float,
    paid_quantity: int | None = None,
    total_quantity: int | None = None,
    discount_percentage: float = 0.0,
    vat_included: bool = True,
    vat_rate: float = DEFAULT_VAT_RATE,
) -> float:
    """
    Calculate the true net unit price considering VAT, discounts, and promotions.

    Args:
        raw_unit_price: Price per unit as listed on invoice
        paid_quantity: Number of paid units (e.g., 11 in "11+1 free")
        total_quantity: Total units received (e.g., 12 in "11+1 free")
        discount_percentage: Line-level discount percentage
        vat_included: Whether raw_unit_price includes VAT
        vat_rate: VAT rate as percentage

    Returns:
        Net price per unit (excluding VAT, after all adjustments)

    Example:
        # 11+1 free, price 10 per unit including VAT
        >>> calculate_net_unit_price(10.0, paid_quantity=11, total_quantity=12, vat_included=True, vat_rate=17)
        # = 10 / 1.17 * (11/12) ≈ 7.83
    """
    net_price = raw_unit_price

    # Remove VAT if included
    if vat_included:
        net_price = remove_vat(net_price, vat_rate)

    # Apply line discount
    if discount_percentage > 0:
        net_price = net_price * (1 - discount_percentage / 100)

    # Apply promotion adjustment (e.g., 11+1 free)
    if paid_quantity and total_quantity and total_quantity > paid_quantity:
        # Effective price per unit = (paid units * price) / total units
        net_price = net_price * paid_quantity / total_quantity

    return round(net_price, 2)


def calculate_sell_price(net_price: float) -> float:
    """
    Calculate sell price from net price using .90 endings.

    Rules:
    - Base value is doubled net price.
    - For net < 15: truncate doubled value and add .90.
    - For net >= 15: snap to a nearby integer ending with 4 or 9, then add .90.
    """
    doubled = net_price * 2

    if net_price < 15:
        # Small prices keep the doubled integer part and force a .90 ending.
        return float(int(doubled)) + 0.9

    # Larger prices target ...4 or ...9 before applying the .90 ending.
    int_part = int(doubled)
    nearest_5 = round(int_part / 5) * 5
    target = nearest_5 - 1

    # Avoid dropping too far below the doubled integer price.
    if target < int_part - 2:
        target += 5

    return float(target) + 0.9
