import pytest

from ebaywatch.markets import get_market
from ebaywatch.parser import BlockedError, extract_item_id, is_block_page, parse_search_page

from .conftest import fixture_text, scard_page


def test_scard_layout_fr():
    result = parse_search_page(fixture_text("ebay_fr_scard.html"), get_market("fr"))
    assert result.layout == "s-card"
    ids = [l.item_id for l in result.listings]
    # placeholder 123456 skipped, duplicate skipped, items after "fewer words" divider skipped
    assert ids == ["226789012345", "389012345678", "155566677788"]

    first = result.listings[0]
    assert first.title == "Nintendo Switch OLED Blanche + 2 jeux"   # badge + hidden suffix removed
    assert first.price == 249.0 and first.currency == "EUR"
    assert first.shipping_text == "+8,90 EUR livraison"
    assert first.location_text == "de France"
    assert first.subtitle.startswith("Occasion")
    assert first.url == "https://www.ebay.fr/itm/226789012345"
    assert first.image_url == "https://i.ebayimg.com/images/g/AbCdEf/s-l500.webp"
    assert first.is_auction is False

    auction = result.listings[1]
    assert auction.price == 1049.99
    assert auction.is_auction is True and auction.bids == 3
    assert auction.image_url == "https://i.ebayimg.com/images/g/XyZ/s-l500.jpg"   # lazy-load attr

    ranged = result.listings[2]
    assert ranged.item_id == "155566677788"   # id taken from the SEO url
    assert ranged.price == 280.0


def test_sitem_legacy_layout_uk():
    result = parse_search_page(fixture_text("ebay_uk_sitem.html"), get_market("uk"))
    assert result.layout == "s-item"
    assert [l.item_id for l in result.listings] == ["296543210987", "176655443322"]
    ps5 = result.listings[0]
    assert ps5.title == "Sony PlayStation 5 Console Disc Edition 825GB White"
    assert (ps5.price, ps5.currency) == (1234.56, "GBP")
    assert ps5.shipping_text == "+£4.99 postage"
    assert ps5.location_text == "from United Kingdom"
    assert ps5.url == "https://www.ebay.co.uk/itm/296543210987"
    assert ps5.image_url == "https://i.ebayimg.com/images/g/QwErTy/s-l500.webp"
    auction = result.listings[1]
    assert auction.is_auction and auction.bids == 5


def test_no_exact_results_ignores_fewer_words_section():
    result = parse_search_page(fixture_text("ebay_no_results.html"), get_market("fr"))
    assert result.listings == []
    assert result.no_exact_results is True


def test_challenge_page_raises():
    html = fixture_text("ebay_challenge.html")
    assert is_block_page(html)
    with pytest.raises(BlockedError):
        parse_search_page(html, get_market("fr"))


def test_normal_page_not_flagged_as_block():
    assert not is_block_page(fixture_text("ebay_fr_scard.html"))


def test_fallback_on_unknown_markup():
    html = """<html><body><ul class="srp-results">
      <li class="brand-new-card"><a href="https://www.ebay.de/itm/Some-Title/334455667788?x=1">
        <h3>Nintendo Switch Lite Türkis</h3></a><span>89,00 EUR</span>
        <ul><li class="inner"><a href="https://www.ebay.de/itm/334455667788">x</a></li></ul></li>
      <li class="brand-new-card"><a href="https://www.ebay.de/itm/223344556677"><img alt="Switch OLED Weiß"
         src="https://i.ebayimg.com/images/g/a/s-l225.jpg"></a></li>
    </ul></body></html>"""
    result = parse_search_page(html, get_market("de"))
    assert result.layout == "fallback"
    assert [l.item_id for l in result.listings] == ["334455667788", "223344556677"]
    assert result.listings[1].title == "Switch OLED Weiß"
    assert result.listings[1].image_url == "https://i.ebayimg.com/images/g/a/s-l500.jpg"


def test_empty_page():
    result = parse_search_page("<html><body></body></html>", get_market("fr"))
    assert result.listings == []


def test_generated_page_and_divider():
    html = scard_page(
        [{"id": "226000000010", "title": "A", "price": "5,00 EUR"}],
        rewrite_after=[{"id": "226000000011", "title": "B"}],
    )
    result = parse_search_page(html, get_market("fr"))
    assert [l.item_id for l in result.listings] == ["226000000010"]
    assert result.listings[0].title == "A"


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("https://www.ebay.fr/itm/226789012345?hash=x", "226789012345"),
        ("https://www.ebay.fr/itm/Some-Seo-Title/155566677788?x", "155566677788"),
        ("/itm/123456789012", "123456789012"),
        ("https://ebay.com/itm/123456", None),
        ("https://www.ebay.fr/b/Consoles/139971", None),
        (None, None),
    ],
)
def test_extract_item_id(href, expected):
    assert extract_item_id(href) == expected


def test_large_page_performance():
    items = [{"id": str(226000000000 + i), "title": f"Objet numéro {i}", "price": f"{i},00 EUR"} for i in range(240)]
    html = scard_page(items)
    import time

    started = time.perf_counter()
    for _ in range(20):
        result = parse_search_page(html, get_market("fr"))
    per_page = (time.perf_counter() - started) / 20
    assert len(result.listings) == 240
    assert per_page < 0.25, f"parsing too slow: {per_page:.3f}s per page"


def test_fallback_extracts_price():
    html = """<ul class="srp-results"><li class="x"><a href="https://www.ebay.de/itm/334455667788">
      <h3>Nintendo Switch Lite</h3></a><div><span>89,00 EUR</span><span>+4,99 EUR Versand</span></div></li></ul>"""
    listing = parse_search_page(html, get_market("de")).listings[0]
    assert listing.title == "Nintendo Switch Lite"
    assert listing.price == 89.0
