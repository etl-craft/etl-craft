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


def run_labels(result: object) -> dict[str, dict[int, str]]:
    """Collect the stored display labels carried by the operation, including nested summaries."""
    from etl_craft.services.operations.run_labels import OPAQUE, PAIRS
    from etl_craft.services.operations.serialization import encode

    labels: dict[str, dict[int, str]] = {"run": {}, "task": {}}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for identity, label in PAIRS.items():
                number, name = value.get(identity), value.get(label)
                if isinstance(number, int) and isinstance(name, str) and name:
                    labels["task" if "task" in identity else "run"][number] = name
                elif (
                    isinstance(number, list) and isinstance(name, list) and len(number) == len(name)
                ):
                    labels["task" if "task" in identity else "run"].update(
                        (identity, label)
                        for identity, label in zip(number, name, strict=True)
                        if label
                    )
            for key, child in value.items():
                if key not in OPAQUE:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(encode(result))
    return labels
