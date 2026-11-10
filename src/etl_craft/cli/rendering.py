"""Human-readable durations shared by command renderers."""


def duration(seconds: float | None) -> str:
    """Render a measured duration without spurious decimal precision."""
    if seconds is None:
        return "not recorded"
    value = max(0, seconds)
    if value < 60:
        return f"{value:.1f}s" if value != round(value) else f"{value:.0f}s"
    minutes, rest = divmod(round(value), 60)
    if minutes < 60:
        return f"{minutes}m {rest:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def hours(value: float | None) -> str:
    """Render an SLA budget as a duration rather than fractional hours."""
    return "not configured" if value is None else duration(value * 3600)
