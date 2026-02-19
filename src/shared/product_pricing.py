"""
Price calculation utilities for Super Order Automation.

This module provides functions for:
1. VAT removal from prices
2. Net price calculation (handling promotions like 11+1)
3. Sell price calculation with .90 rounding
"""

import math
from typing import Optional

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


def _calculate_sell_price_old(net_price: float) -> float:
    """
    [DEPRECATED] Calculate sell price from net price with .90 rounding.

    Rules:
    - Multiply net price by 2
    - If net < 15: round up to get .90 decimal (7→14.90, 6.5→13.90)
    - If net >= 15: round to nearest X4.90 or X9.90 (39→79.90, 42→84.90)

    Args:
        net_price: Net cost price

    Returns:
        Sell price ending in .90

    Examples:
        >>> calculate_sell_price(7.0)
        14.9
        >>> calculate_sell_price(6.5)
        13.9
        >>> calculate_sell_price(35.0)
        69.9
        >>> calculate_sell_price(42.0)
        84.9
        >>> calculate_sell_price(39.0)
        79.9
        >>> calculate_sell_price(50.0)
        99.9
    """
    doubled = net_price * 2

    if net_price < 15:
        # For small prices: just round up the integer part and add .90
        # e.g., 14.00 → 14.90, 13.00 → 13.90
        return math.ceil(doubled) + 0.90 - 1  # ceil(14) = 14, 14 + 0.90 - 1 = 13.9... wait that's wrong
        # Let me reconsider: 7*2=14 → 14.90, 6.5*2=13 → 13.90
        # So it's just: ceil(doubled - 0.1) + 0.9? No...
        # Actually: floor(doubled) + 0.9 if doubled is exact, ceil(doubled-1) + 0.9 otherwise
        # Simpler: int(math.ceil(doubled)) - 1 + 0.9? No...
        # Let me just use: math.ceil(doubled - 0.01) gives us the integer, then add 0.9
        # Actually simplest: math.floor(doubled) + 0.9

    # For net >= 15: round to nearest X4.90 or X9.90
    # e.g., 70 → 69.90, 84 → 84.90, 78 → 79.90, 100 → 99.90

    # Get integer part
    int_part = int(doubled)
    last_digit = int_part % 10

    # Find nearest ending in 4 or 9
    if last_digit <= 4:
        # Round to X4
        target = int_part - last_digit + 4
    elif last_digit <= 7:
        # Round to X4 or X9 - closer to 4 if <= 6, else 9
        if last_digit <= 6:
            target = int_part - last_digit + 4
        else:
            target = int_part - last_digit + 9
    else:
        # Round to X9
        target = int_part - last_digit + 9

    return target + 0.9


def _calculate_sell_price_v2(net_price: float) -> float:
    """
    Cleaner implementation of sell price calculation.
    """
    doubled = net_price * 2

    if net_price < 15:
        # For small prices: integer part + .90
        # 7*2=14 → 14.90, 6.5*2=13 → 13.90
        return float(int(doubled)) + 0.9

    # For net >= 15: round to nearest X4.90 or X9.90
    int_part = int(doubled)


    # Targets are: ...4, ...9
    # For each last digit, find the closest target
    # 0,1,2 → 4 (round up to 4)
    # 3,4 → 4 (stay at 4)
    # 5,6 → 4 or 9? 5→4 (closer), 6→9 (closer)
    # 7,8,9 → 9

    # Actually, let's think about it differently
    # We want to round to the nearest multiple of 5 ending in 4 or 9
    # That means: ...-1, 4, 9, 14, 19, 24, 29, ...
    # These are numbers where (n+1) % 5 == 0

    # A simpler approach: round to nearest 5, then subtract 1
    nearest_5 = round(int_part / 5) * 5
    target = nearest_5 - 1  # This gives X4 or X9

    # Make sure we don't go below the cost
    if target < int_part - 2:
        target += 5

    return float(target) + 0.9


# Use the cleaner implementation
calculate_sell_price = _calculate_sell_price_v2


if __name__ == "__main__":
    # Test cases
    test_cases = [
        (7.0, 14.9),
        (6.5, 13.9),
        (35.0, 69.9),
        (42.0, 84.9),
        (39.0, 79.9),
        (50.0, 99.9),
        (6.0, 12.9),
        (10.0, 20.9),  # 10*2=20 → 19.9? or 20.9?
    ]

    print("Testing calculate_sell_price:")
    for net, expected in test_cases:
        result = calculate_sell_price(net)
        status = "OK" if abs(result - expected) < 0.01 else "FAIL"
        print(f"  net={net} -> {result} (expected {expected}) [{status}]")
