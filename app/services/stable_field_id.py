import hashlib
import re


def _normalize_section(s: str) -> str:
    """Lowercase, trim, collapse inner whitespace. Punctuation is preserved."""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _normalize_label(s: str) -> str:
    """Lowercase, trim, strip punctuation, collapse inner whitespace."""
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def compute(section_path: str, raw_label: str) -> str:
    """
    Return the stable_field_id for a given (section_path, raw_label) pair.

    This function is the system's single source of truth.
    All services that need a stable_field_id must import and call this function.
    No inline reimplementation is permitted.
    """
    key = f"{_normalize_section(section_path)}|{_normalize_label(raw_label)}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"sfid_{digest[:8]}"
