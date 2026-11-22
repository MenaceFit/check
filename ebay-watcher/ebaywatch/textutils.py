"""Text helpers: price parsing, normalisation, keyword matching."""

from __future__ import annotations

import re
import unicodedata

_SPACES = re.compile(r"[\s   ]+")
_NUMBER = re.compile(r"\d[\d\s   .,'’]*")

# Order matters: longer / more specific tokens first.
_CURRENCY_TOKENS: tuple[tuple[str, str], ...] = (
    ("US $", "USD"), ("US$", "USD"), ("AU $", "AUD"), ("AU$", "AUD"), ("C $", "CAD"), ("C$", "CAD"),
    ("CA $", "CAD"), ("EUR", "EUR"), ("€", "EUR"), ("GBP", "GBP"), ("£", "GBP"), ("USD", "USD"),
    ("CHF", "CHF"), ("CAD", "CAD"), ("AUD", "AUD"), ("PLN", "PLN"), ("ZŁ", "PLN"),
)


def clean_spaces(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def normalize(text: str) -> str:
    """Lower-case, strip accents and collapse whitespace (for matching)."""
    decomposed = unicodedata.normalize("NFKD", text)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return clean_spaces(no_accents.casefold())


def _detect_currency(text: str, default: str | None) -> str | None:
    upper = text.upper()
    for token, code in _CURRENCY_TOKENS:
        if token in upper:
            return code
    if "$" in upper:
        return default if default in ("USD", "CAD", "AUD") else "USD"
    return default


def _parse_number(raw: str) -> float | None:
    s = re.sub(r"[\s   '’]", "", raw).strip(".,")
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if len(tail) == 3 and s.count(",") >= 1 and head:
            s = s.replace(",", "")          # 1,234 -> thousands separator
        else:
            s = head.replace(",", "") + "." + tail
    elif "." in s:
        head, _, tail = s.rpartition(".")
        if len(tail) == 3 or s.count(".") > 1:
            s = s.replace(".", "")          # 1.234 -> thousands separator
    try:
        return float(s)
    except ValueError:
        return None


def parse_price(text: str, default_currency: str | None = None) -> tuple[float | None, str | None]:
    """Parse an eBay price string.

    Handles every locale used by eBay sites (``249,00 EUR``, ``£1,234.56``,
    ``US $12.00``, ``CHF 1'250.00``, ranges like ``10,00 EUR à 20,00 EUR`` -> lowest).
    """
    if not text:
        return None, default_currency
    text = clean_spaces(text)
    currency = _detect_currency(text, default_currency)
    match = _NUMBER.search(text)
    if not match:
        return None, currency
    # A range ("10,00 EUR à 20,00 EUR") contains words between the two numbers,
    # so the first regex match is only the low bound.
    raw = match.group(0)
    # Avoid swallowing a second number separated only by a space ("10 20").
    raw = re.split(r"\s(?=\d+[.,]\d{2}\b.*\d)", raw)[0]
    return _parse_number(raw), currency


def tokenize_query(query: str) -> tuple[list[str], list[str]]:
    """Split an eBay-like query into required words and excluded words (``-word``)."""
    required: list[str] = []
    excluded: list[str] = []
    for phrase in re.findall(r'"([^"]+)"|(\S+)', query):
        token = phrase[0] or phrase[1]
        if phrase[1] and token.startswith("-") and len(token) > 1:
            excluded.append(normalize(token[1:].strip("()")))
            continue
        token = token.strip("()")
        if not token or token in ("|", "OR"):
            continue
        # eBay "(a,b)" alternative syntax: cannot require every alternative.
        if "," in token and not phrase[0]:
            continue
        required.append(normalize(token))
    return required, excluded


def contains_term(haystack_normalized: str, term_normalized: str) -> bool:
    """Whole-word-ish containment (``ps5`` matches ``ps5,`` but not ``ps50``)."""
    if not term_normalized:
        return True
    pattern = r"(?<![0-9a-z])" + re.escape(term_normalized) + r"(?![0-9a-z])"
    return re.search(pattern, haystack_normalized) is not None
