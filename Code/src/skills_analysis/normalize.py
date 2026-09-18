"""Field-level cleaning rules shared by every source.

Each function takes whatever the source actually contains - blanks, free text,
Excel serial numbers, mojibake - and returns either a clean value or ``None``.
Nothing here raises on bad input: unparseable values come back as ``None`` and
the caller logs them to the data-quality table, so one malformed cell never
drops a row on the floor.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

# Excel's day zero on the 1900 date system (with its leap-year quirk baked in).
_EXCEL_EPOCH = date(1899, 12, 30)
_EXCEL_SERIAL_RANGE = (20000, 60000)  # ~1954 to ~2064

_NULLISH = {
    "", "-", "--", "?", "??", "n/a", "na", "n.a.", "none", "null", "tbd", "tba",
    "unknown", "not applicable", "nan", "nat",
}


def fix_mojibake(value: str) -> str:
    """Repair UTF-8 text that was decoded as Latin-1 (``JosÃ©`` -> ``José``)."""
    if not value or not any(ch in value for ch in "ÃÂ¢â€"):
        return value
    try:
        repaired = value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    # Only accept the repair if it did not introduce replacement characters.
    return repaired if "�" not in repaired else value


def clean_text(value: object) -> str | None:
    """Trim, repair encoding, collapse internal whitespace, null out placeholders."""
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    text = fix_mojibake(str(value))
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("​﻿")
    if text.lower() in _NULLISH:
        return None
    return text or None


def norm_key(value: object) -> str:
    """Aggressive lowercase key used for joins and reference lookups."""
    text = clean_text(value) or ""
    text = text.replace("’", "'")
    return re.sub(r"\s+", " ", text).strip().lower()


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

_DATE_FORMATS = (
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%y", "%d-%b-%Y",
    "%b %d, %Y", "%Y/%m/%d", "%d/%m/%Y",
)


def parse_date(value: object) -> date | None:
    """Parse the many date shapes these exports contain.

    Handles ISO strings, US slash dates, ``14-Jan-26``, datetimes, Excel serial
    numbers, and a single typo (``2024-01@08``) where a separator was mistyped.
    Fiscal shorthand (``Q1 FY28``, ``end of FY``) is deliberately not guessed at
    and returns ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        if value != value:  # NaN
            return None
        if _EXCEL_SERIAL_RANGE[0] <= float(value) <= _EXCEL_SERIAL_RANGE[1]:
            return _EXCEL_EPOCH.fromordinal(_EXCEL_EPOCH.toordinal() + int(value))
        return None

    text = clean_text(value)
    if not text:
        return None

    # Repair mistyped separators in otherwise ISO-shaped values: 2024-01@08.
    text = re.sub(r"(?<=\d)[@#](?=\d)", "-", text)
    text = text.replace(" 00:00:00", "")

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    if re.fullmatch(r"\d{4,5}(\.0)?", text):  # Excel serial that arrived as text
        return parse_date(float(text))
    return None


def date_is_fiscal_shorthand(value: object) -> bool:
    """True for values like ``Q1 FY28`` or ``end of FY`` that name no real date."""
    text = (clean_text(value) or "").lower()
    if not text:
        return False
    return bool(re.search(r"\bq[1-4]\b|\bfy\d{2}\b|end of (the )?fy|next (fy|year)", text))


# --------------------------------------------------------------------------
# Proficiency, skills, statuses
# --------------------------------------------------------------------------

def normalize_proficiency(value: object) -> tuple[int | None, str]:
    """Map any rating dialect onto 1-5. Returns ``(proficiency, confidence)``."""
    from .reference import proficiency_scale

    text = clean_text(value)
    if text is None:
        return None, "none"

    scale = proficiency_scale()
    hit = scale.get(norm_key(text))
    if hit is not None:
        return hit.proficiency, hit.confidence

    # "4 - Advanced" style values that are not in the table verbatim.
    leading = re.match(r"^\s*([1-5])\b", text)
    if leading:
        return int(leading.group(1)), "high"

    for word, level in (("expert", 5), ("advanced", 4), ("intermediate", 3), ("beginner", 2), ("novice", 1)):
        if word in text.lower():
            return level, "medium"
    return None, "none"


def canonical_skill(value: object) -> tuple[str | None, str | None]:
    """Map a raw skill string onto the canonical taxonomy.

    Returns ``(canonical_skill, skill_domain)``; ``(None, None)`` means the
    string is not in the alias table and needs a human decision.
    """
    from .reference import skill_aliases

    text = clean_text(value)
    if text is None:
        return None, None
    hit = skill_aliases().get(norm_key(text))
    if hit is None:
        return None, None
    return hit.canonical_skill, hit.skill_domain


_LEARNING_STATUS = {
    "completed": "Completed", "complete": "Completed", "done": "Completed",
    "c": "Completed", "y": "Completed", "yes": "Completed", "finished": "Completed",
    "in progress": "In Progress", "started": "In Progress", "in-progress": "In Progress",
    "not started": "Not Started", "not-started": "Not Started", "assigned": "Not Started",
    "withdrawn": "Withdrawn", "cancelled": "Withdrawn", "canceled": "Withdrawn",
}


def normalize_learning_status(value: object) -> str | None:
    text = norm_key(value)
    return _LEARNING_STATUS.get(text) if text else None


def normalize_cert_status(value: object) -> str | None:
    """Collapse the tracker's free-text certification statuses.

    Returns ``None`` when the cell holds something that is not a status at all
    (a date typed into the status column, for instance).
    """
    text = clean_text(value)
    if text is None:
        return None
    if parse_date(text) is not None:
        return None
    lowered = re.sub(r"[^a-z ]", " ", text.lower())
    lowered = re.sub(r"\s+", " ", lowered).strip()
    if "expired" in lowered or "lapsed" in lowered:
        return "Expired"
    if "expiring" in lowered:
        return "Expiring"
    if "active" in lowered or "current" in lowered:
        return "Active"
    if "in progress" in lowered or "in prog" in lowered:
        return "In Progress"
    if "not started" in lowered or "notstarted" in lowered:
        return "Not Started"
    return None


# --------------------------------------------------------------------------
# Numbers, money, durations
# --------------------------------------------------------------------------

def parse_number(value: object) -> float | None:
    """Pull a number out of values like ``40 (need 80)`` or ``~$300?``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if value != value else float(value)
    text = clean_text(value)
    if text is None:
        return None
    match = re.search(r"-?\d+(?:[.,]\d+)?", text.replace(",", ""))
    return float(match.group(0)) if match else None


def parse_money(value: object) -> float | None:
    """Money with currency symbols, thousands separators, and ``free``."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None if value != value else float(value)
    text = clean_text(value)
    if text is None:
        return None
    if text.lower() in {"free", "no cost", "internal", "covered"}:
        return 0.0
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    try:
        return float(cleaned) if cleaned not in {"", "-", "."} else None
    except ValueError:
        return None


def parse_duration_hours(value: object) -> float | None:
    """Durations recorded as hours, or as free text like ``90 min``."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None if value != value else float(value)
    text = clean_text(value)
    if text is None:
        return None
    minutes = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(min|mins|minutes)\b", text, re.I)
    if minutes:
        return round(float(minutes.group(1)) / 60.0, 3)
    hours = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(h|hr|hrs|hours)?\s*$", text, re.I)
    return float(hours.group(1)) if hours else None


# --------------------------------------------------------------------------
# People and places
# --------------------------------------------------------------------------

def normalize_person_name(value: object) -> str | None:
    """Return ``First Last`` from either ``Last, First`` or ``First Last``.

    Also fixes all-caps entries; initials and suffixes are left intact.
    """
    text = clean_text(value)
    if text is None:
        return None
    if "," in text:
        last, _, first = text.partition(",")
        text = f"{first.strip()} {last.strip()}".strip()
    if text.isupper() or text.islower():
        text = " ".join(_titlecase_token(tok) for tok in text.split())
    return re.sub(r"\s+", " ", text).strip() or None


def _titlecase_token(token: str) -> str:
    """Title-case a name token while respecting O'Leary, McBride and hyphens."""
    def cap(part: str) -> str:
        if not part:
            return part
        if part.lower().startswith("mc") and len(part) > 2:
            return "Mc" + part[2:].capitalize()
        return part[:1].upper() + part[1:].lower()

    for sep in ("'", "-"):
        if sep in token:
            return sep.join(cap(p) for p in token.split(sep))
    return cap(token)


_LOCATION_CODES = {
    "sjc": "San Jose, CA",
    "rtp": "Research Triangle Park, NC",
    "ams": "Amsterdam",
    "blr": "Bangalore",
    "sfo": "San Francisco, CA",
}


def normalize_location(value: object) -> str | None:
    """Expand three-letter site codes so a site is one value, not two."""
    text = clean_text(value)
    if text is None:
        return None
    return _LOCATION_CODES.get(text.lower(), text)


def normalize_org(value: object) -> str | None:
    """Supervisory organisation, case-normalised and without the manager suffix."""
    text = clean_text(value)
    if text is None:
        return None
    base = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
    if base.isupper():
        base = base.title()
    return base or None


def resolve_employee_id(source_system: str, *candidates: object) -> tuple[str | None, str | None]:
    """Resolve a source's identifier to a Workday employee ID.

    Tries each candidate (employee ID, email, username, name) against the
    override table in order. Returns ``(employee_id, reason)``. A resolved-but-
    empty employee ID means the key is knowingly out of scope, signalled as
    ``("", reason)``; an unknown key returns ``(None, None)``.
    """
    from .reference import identity_name_index, identity_overrides, identity_reasons

    overrides = identity_overrides()
    reasons = identity_reasons()
    name_index = identity_name_index()
    system = source_system.lower()

    for candidate in candidates:
        key = norm_key(candidate)
        if not key:
            continue
        if (system, key) in overrides:
            return overrides[(system, key)], reasons.get((system, key)) or None
        # A bare, well-formed Workday ID needs no override.
        if re.fullmatch(r"10\d{5}", key):
            return key, None
        # Same person, other name order: "Chen, Wei-Lin" vs "Wei-Lin Chen".
        name_key = norm_key(normalize_person_name(candidate))
        if name_key and (system, name_key) in name_index:
            return name_index[(system, name_key)], "Matched on name after normalising name order"
    return None, None
