# src/lm/utils/numbers.py
from typing import Optional

def safe_float(s: str, default: Optional[float] = None) -> Optional[float]:
    try:
        if s is None: return default
        return float(str(s).replace(",", ".").strip())
    except Exception:
        return default

def safe_int(s: str, default: Optional[int] = None) -> Optional[int]:
    try:
        if s is None: return default
        return int(str(s).strip())
    except Exception:
        return default

def signed_text(value: float, zero: str = "0") -> str:
    if value > 0: return f"+{value:.0f}"
    if value < 0: return f"−{abs(value):.0f}"
    return zero
