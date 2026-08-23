"""
Utility functions for filename validation and system operations.
"""

import sys
import logging
import re
import unicodedata

# Constants
UNKNOWN_VALUE = "Unknown"
DEFAULT_DATE = "00000000"

# Filename templating
DEFAULT_FILENAME_TEMPLATE = "{date} {company} {type}"

# Placeholders always available to a filename template.
CORE_TEMPLATE_FIELDS = ("date", "company", "type")

# Placeholders that require extra fields from the AI. Requesting these costs
# tokens on every call, so they are only extracted when the template uses them.
EXTENDED_TEMPLATE_FIELDS = ("recipient", "sender", "amount")

ALL_TEMPLATE_FIELDS = CORE_TEMPLATE_FIELDS + EXTENDED_TEMPLATE_FIELDS

# Characters treated as field separators when collapsing gaps left by empty fields
_SEPARATOR_CHARS = r"\-\u2013\u2014_|\u00b7\u2022,;"


def template_placeholders(template: str) -> set[str]:
    """Return the set of {placeholder} names referenced by a filename template."""
    return set(re.findall(r"\{(\w+)\}", template or ""))


def unknown_placeholders(template: str) -> set[str]:
    """Return placeholders in the template that this tool cannot fill."""
    return template_placeholders(template) - set(ALL_TEMPLATE_FIELDS)


def template_uses_extended_fields(template: str) -> bool:
    """True when the template needs recipient/sender/amount from the AI."""
    return bool(template_placeholders(template) & set(EXTENDED_TEMPLATE_FIELDS))


def render_filename_template(template: str, values: dict) -> str:
    """Fill a filename template, collapsing separators left behind by empty fields.

    Unknown placeholders render as empty rather than raising, so a typo in
    config degrades the filename instead of failing the whole run.
    """
    class _Blank(dict):
        def __missing__(self, key):
            return ""

    try:
        text = template.format_map(_Blank(values))
    except (ValueError, IndexError):
        # Malformed template (stray brace, bad format spec) - fall back
        logging.warning(f"Invalid filename_template {template!r}; using default")
        text = DEFAULT_FILENAME_TEMPLATE.format_map(_Blank(values))

    # An empty field leaves an orphaned separator: "20260403 -  - Receipt"
    text = re.sub(rf"\s*([{_SEPARATOR_CHARS}])\s*(?:[{_SEPARATOR_CHARS}]\s*)+", r" \1 ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(rf"^[\s{_SEPARATOR_CHARS}]+|[\s{_SEPARATOR_CHARS}]+$", "", text)
    return text.strip()


class ExitCode:
    """Process exit codes for structured CLI output."""
    SUCCESS = 0
    GENERAL_ERROR = 1
    USAGE_ERROR = 2
    CONFIG_ERROR = 3
    NO_FILES = 4
    PARTIAL_FAILURE = 5
    PROVIDER_ERROR = 10
    AUTH_ERROR = 11


def is_valid_filename(filename: str) -> bool:
    """Check if a filename is valid for the filesystem."""
    forbidden_chars = r'[<>:"/\\|?*]'

    if re.search(forbidden_chars, filename):
        return False

    if not filename or filename.isspace():
        return False

    if len(filename) > 255:
        return False

    return True


def sanitize_filename(filename: str) -> str:
    """Remove or replace characters that are invalid in Windows filenames.

    Strips forbidden chars, control characters, and trailing dots/spaces
    that cause [Errno 22] on Windows.
    """
    # Remove control characters (U+0000–U+001F, U+007F)
    filename = re.sub(r'[\x00-\x1f\x7f]', '', filename)
    # Replace forbidden Windows filename characters
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    # Strip trailing dots and spaces (invalid on Windows)
    filename = filename.strip('. ')
    return filename


def normalize_unicode(value: str) -> str:
    """Normalize user-visible text to NFC for stable comparisons and filenames."""
    return unicodedata.normalize("NFC", value) if isinstance(value, str) else value
