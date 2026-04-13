"""
Utilities for normalized subject codes.
"""

import re

SUBJECT_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")


def normalize_subject_code(subject_code: str | None) -> str:
    return (subject_code or "").strip().lower()


def is_valid_subject_code(subject_code: str | None) -> bool:
    return bool(SUBJECT_CODE_RE.match(normalize_subject_code(subject_code)))


def parse_subject_codes(raw_value) -> list[str]:
    if raw_value is None:
        return []

    if isinstance(raw_value, str):
        raw_items = raw_value.replace("\n", ",").split(",")
    elif isinstance(raw_value, (list, tuple, set)):
        raw_items = list(raw_value)
    else:
        return []

    subject_codes = []
    seen = set()

    for raw_item in raw_items:
        subject_code = normalize_subject_code(str(raw_item))
        if not subject_code or subject_code in seen:
            continue
        subject_codes.append(subject_code)
        seen.add(subject_code)

    return subject_codes
