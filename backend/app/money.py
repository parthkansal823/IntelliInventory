"""Currency formatting — Indian Rupees with lakh/crore digit grouping (₹1,23,45,678)."""

CURRENCY = "INR"
SYMBOL = "₹"


def _group_indian(integer: int) -> str:
    s = str(abs(integer))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def inr(value: float, decimals: int | None = None) -> str:
    """₹ amount; whole rupees at >= ₹100, paise below that unless `decimals` is given."""
    if decimals is None:
        decimals = 0 if abs(value) >= 100 else 2
    rounded = round(abs(value), decimals)
    whole = int(rounded)
    frac = f"{rounded - whole:.{decimals}f}"[1:] if decimals else ""
    return f"{'-' if value < 0 else ''}{SYMBOL}{_group_indian(whole)}{frac}"
