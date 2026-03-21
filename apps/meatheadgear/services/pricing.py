"""
MeatheadGear pricing engine.

Calculates retail prices from Printful's base cost with a target gross margin.
Formula: retail = cost / (1 - margin), then round UP to nearest $X.99.

Decision from 01-CONTEXT.md:
  "Retail price = Printful base cost / (1 - 0.35)"
  "Round up to nearest $0.99 (e.g., $18.46 -> $18.99)"
  "Margin floor: 30% — (retail - cost) / retail >= 0.30"
"""

import math


def calculate_retail_price(printful_cost: float, target_margin: float = 0.35) -> float:
    """
    Calculate retail price to achieve target gross margin.

    Formula: retail = cost / (1 - margin)
    Then round UP to nearest $X.99

    Examples:
        13.50 / 0.65 = 20.77 -> 20.99
        9.49  / 0.65 = 14.60 -> 14.99
        29.94 / 0.65 = 46.06 -> 46.99

    Args:
        printful_cost: Base cost from Printful (before markup).
        target_margin: Target gross margin as a decimal (default 0.35 = 35%).

    Returns:
        Retail price rounded up to nearest $X.99. Returns 0.0 for zero/negative cost.
    """
    if printful_cost <= 0:
        return 0.0

    raw_price = printful_cost / (1 - target_margin)

    # Round UP to nearest $X.99
    # Strategy: ceil to next integer, then subtract 0.01 for the .99 ending
    # If subtracting 0.01 drops us below raw_price, go up one more dollar
    whole = math.ceil(raw_price)
    retail = whole - 0.01  # e.g., ceil(20.77) = 21 -> 20.99

    # If .99 price is below the raw calculated price, step up one dollar
    if retail < raw_price:
        retail = whole + 0.99

    return round(retail, 2)
