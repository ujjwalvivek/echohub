from __future__ import annotations

from datetime import UTC, datetime


def compact(value: float) -> str:
    value = float(value)
    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(value) >= divisor:
            n = value / divisor
            return f"{n:.1f}{suffix}" if abs(n) < 10 else f"{n:.0f}{suffix}"
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def human_bytes(value: float | None) -> str:
    if value is None:
        return "-"
    size = max(0.0, float(value))
    for suffix, divisor in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size >= divisor:
            n = size / divisor
            return f"{n:.1f} {suffix}" if n < 10 else f"{n:.0f} {suffix}"
    return f"{int(size)} B"


def human_kb(value: float | None) -> str:
    if value is None:
        return "-"
    return human_bytes(float(value) * 1024)


def relative_time(value: str) -> str:
    if not value:
        return "unknown"
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        seconds = max(0, int((datetime.now(UTC) - dt).total_seconds()))
    except ValueError:
        return value
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    if days < 365:
        return f"{days}d ago"
    return f"{days // 365}y ago"


def short_date(value: str) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return value[:10] or "-"


def bar(value: float, width: int, *, full: str = "█", empty: str = "░") -> str:
    value = max(0.0, min(1.0, value))
    filled = round(value * width)
    return full * filled + empty * max(0, width - filled)
