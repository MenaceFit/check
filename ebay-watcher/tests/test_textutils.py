import pytest

from ebaywatch.textutils import contains_term, normalize, parse_price, tokenize_query


@pytest.mark.parametrize(
    ("text", "default", "expected"),
    [
        ("249,00 EUR", "EUR", (249.0, "EUR")),
        ("EUR 249,00", "EUR", (249.0, "EUR")),
        ("1 049,99 EUR", "EUR", (1049.99, "EUR")),
        ("1 049,99 EUR", "EUR", (1049.99, "EUR")),
        ("1 049,99 €", "EUR", (1049.99, "EUR")),
        ("1.234,56 €", "EUR", (1234.56, "EUR")),
        ("£1,234.56", "GBP", (1234.56, "GBP")),
        ("£250.00", "GBP", (250.0, "GBP")),
        ("US $12.34", "USD", (12.34, "USD")),
        ("$1,299.00", "USD", (1299.0, "USD")),
        ("C $45.00", "CAD", (45.0, "CAD")),
        ("AU $45.00", "AUD", (45.0, "AUD")),
        ("CHF 1'250.50", "CHF", (1250.5, "CHF")),
        ("CHF 1’250.50", "CHF", (1250.5, "CHF")),
        ("12,34 zł", "PLN", (12.34, "PLN")),
        ("280,00 EUR à 320,00 EUR", "EUR", (280.0, "EUR")),
        ("£10.00 to £20.00", "GBP", (10.0, "GBP")),
        ("10,00 EUR bis 20,00 EUR", "EUR", (10.0, "EUR")),
        ("1.234 €", "EUR", (1234.0, "EUR")),
        ("15 €", "EUR", (15.0, "EUR")),
        ("", "EUR", (None, "EUR")),
        ("Prix sur demande", "EUR", (None, "EUR")),
    ],
)
def test_parse_price(text, default, expected):
    assert parse_price(text, default) == expected


def test_normalize_strips_accents_and_case():
    assert normalize("  Édition  ZELDA Tbé ") == "edition zelda tbe"


def test_tokenize_query():
    required, excluded = tokenize_query('nintendo switch -lite "oled blanche" (rouge,bleu)')
    assert required == ["nintendo", "switch", "oled blanche"]
    assert excluded == ["lite"]


@pytest.mark.parametrize(
    ("hay", "term", "found"),
    [
        ("console ps5 slim", "ps5", True),
        ("console ps50", "ps5", False),
        ("ps5,slim", "ps5", True),
        ("boite vide ps5", "boite vide", True),
        ("hs", "hs", True),
        ("hdmi cable", "hs", False),
    ],
)
def test_contains_term(hay, term, found):
    assert contains_term(hay, term) is found
