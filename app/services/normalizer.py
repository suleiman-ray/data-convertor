import re
from datetime import date
from typing import Callable

from app.models.enums import ValueType

"""
Value normalizer — converts raw string values into typed canonical dicts.

Each normalizer returns a JSON-serialisable dict whose shape maps 1-to-1
to the corresponding FHIR data type so the FHIR builder can inject it
directly into the template placeholder without any further transformation.

Version is frozen alongside stable_field_id: bumping it requires a
migration plan because downstream FHIR bundles depend on the shape.
"""

NORMALIZER_VERSION = "1.0"

_TRUTHY = {"yes", "true", "1", "y", "positive", "si", "oui"}
_FALSY  = {"no", "false", "0", "n", "negative", "non"}

_ACCEPTED_DATE_PATTERNS = [
    (r"^(\d{4})-(\d{2})-(\d{2})$",     "ymd"),  # YYYY-MM-DD (ISO 8601)
    (r"^(\d{2})/(\d{2})/(\d{4})$",     "mdy"),  # MM/DD/YYYY
    (r"^(\d{1,2})-(\d{1,2})-(\d{4})$", "mdy"),  # M-D-YYYY
]

_QUANTITY_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*(\w*)$")


class NormalizationError(Exception):
    pass


def normalize_quantity(raw: str, unit: str | None = None) -> dict:
    """
    Returns {"value": float, "unit": str | None} matching FHIR Quantity.
    Explicit unit from the canonical concept overrides any trailing unit token.
    """
    raw = raw.strip()
    match = _QUANTITY_RE.match(raw)
    if not match:
        raise NormalizationError(
            f"Cannot parse quantity from {raw!r}. "
            "Expected a number optionally followed by a word-character unit (e.g. '14', '14months', '3.5 kg')."
        )
    value = float(match.group(1))
    raw_unit = match.group(2) or None
    return {"value": value, "unit": unit or raw_unit}


def normalize_boolean(raw: str) -> dict:
    """Returns {"value": bool} matching FHIR boolean."""
    normalised = raw.strip().lower()
    if normalised in _TRUTHY:
        return {"value": True}
    if normalised in _FALSY:
        return {"value": False}
    raise NormalizationError(
        f"Cannot parse boolean from {raw!r}. "
        f"Expected one of: {sorted(_TRUTHY | _FALSY)}"
    )


def normalize_date(raw: str) -> dict:
    """Returns {"value": "YYYY-MM-DD"} — ISO 8601 date, matching FHIR date."""
    raw = raw.strip()
    for pattern, order in _ACCEPTED_DATE_PATTERNS:
        m = re.match(pattern, raw)
        if m:
            g = m.groups()
            if order == "ymd":
                year, month, day = int(g[0]), int(g[1]), int(g[2])
            else:
                month, day, year = int(g[0]), int(g[1]), int(g[2])
            try:
                return {"value": date(year, month, day).isoformat()}
            except ValueError as exc:
                raise NormalizationError(f"Invalid date {raw!r}: {exc}") from exc

    raise NormalizationError(
        f"Cannot parse date from {raw!r}. "
        "Expected YYYY-MM-DD, MM/DD/YYYY, or M-D-YYYY."
    )


def normalize_coded(raw: str, value_domain: dict | None = None) -> dict:
    """
    Returns {"code": str, "display": str | None, "system": str | None}.
    If value_domain provides a code map, resolve the raw value through it.
    value_domain shape: {"codes": {"yes": {"code": "Y", "display": "Yes", "system": "..."}}}
    """
    normalised = raw.strip()
    if value_domain:
        code_map = value_domain.get("codes", {})
        entry = code_map.get(normalised) or code_map.get(normalised.lower())
        if entry:
            return {
                "code": entry.get("code", normalised),
                "display": entry.get("display"),
                "system": entry.get("system"),
            }
    return {"code": normalised, "display": None, "system": None}


def normalize_string(raw: str) -> dict:
    """Returns {"value": str} — trimmed, matching FHIR string."""
    return {"value": raw.strip()}


# Dispatch table — exhaustiveness is visible at a glance and adding a new
# ValueType without a normalizer raises KeyError immediately, not silently.
_NORMALIZERS: dict[ValueType, Callable[..., dict]] = {
    ValueType.QUANTITY: normalize_quantity,
    ValueType.BOOLEAN:  normalize_boolean,
    ValueType.DATE:     normalize_date,
    ValueType.CODED:    normalize_coded,
    ValueType.STRING:   normalize_string,
}


def normalize(
    value_type: ValueType,
    raw: str,
    unit: str | None = None,
    value_domain: dict | None = None,
) -> dict:
    """
    Dispatch raw value → typed canonical dict based on value_type.
    Raises NormalizationError on parse failure.
    Raises KeyError if value_type is not in _NORMALIZERS (programming error).
    """
    normalizer = _NORMALIZERS.get(value_type)
    if normalizer is None:
        raise NormalizationError(
            f"No normalizer registered for value_type={value_type!r}. "
            f"Known types: {list(_NORMALIZERS)}"
        )
    if value_type == ValueType.QUANTITY:
        return normalizer(raw, unit=unit)
    if value_type == ValueType.CODED:
        return normalizer(raw, value_domain=value_domain)
    return normalizer(raw)
