"""Parser for eBay search result pages (SRP).

eBay serves several generations of markup depending on site and A/B tests:

* "s-card" layout          ``ul.srp-results > li.s-card[data-listingid]`` (2025-2026, most sites)
* "search-evo" layout      ``.su-item-card.s-item-card--search-evo`` (rolling out on .co.uk / .com, 2026)
* legacy "s-item" layout   ``li.s-item``

Known layouts are matched by class name. When none matches, a structural
fallback finds every ``/itm/<id>`` link and climbs to the largest element that
contains that single listing only, so that a future renaming of CSS classes on
eBay's side degrades gracefully instead of silently returning nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from selectolax.lexbor import LexborHTMLParser, LexborNode

from .markets import Market
from .models import Listing
from .textutils import clean_spaces, parse_price

ITEM_ID_RE = re.compile(r"/itm/(?:[^/?#\s\"']+/)?(\d{9,15})(?:[/?#\"']|$)")
_PLACEHOLDER_IDS = {"123456"}

_TITLE_SELECTORS = (
    ".s-card__title .su-styled-text",
    ".s-card__title",
    ".su-item-card__title",
    "[class*='card__title']",
    ".s-item__title span[role=heading]",
    ".s-item__title",
    "[role=heading]",
    "h3",
    "h2",
    "h4",
)
_PRICE_SELECTORS = (".s-card__price", ".su-item-card__price", ".s-item__price", "[class*='card__price']")
_SUBTITLE_SELECTORS = (".s-card__subtitle", ".su-item-card__subtitle", ".s-item__subtitle", ".SECONDARY_INFO",
                       "[class*='card__subtitle']")
_SHIPPING_SELECTORS = (".s-item__shipping", ".s-item__logisticsCost", ".s-item__freeXDays", ".s-card__logisticsCost",
                       ".s-card__freeXDays", ".s-card__localDelivery", "[class*='card__logisticsCost']")
_LOCATION_SELECTORS = (".s-item__location", ".s-item__itemLocation", ".s-card__location", "[class*='card__location']")
_BIDS_SELECTORS = (".s-item__bids", ".s-item__bidCount", ".s-card__bidCount", "[class*='card__bidCount']")
_CARD_TITLE_CONTAINERS = (".s-card__title", ".su-item-card__title", ".s-item__title")
_WBR_RE = re.compile(r"<wbr\s*/?>", re.IGNORECASE)

# Strings eBay injects in titles that are not part of the seller's title.
_TITLE_NOISE = re.compile(
    r"^(?:nouvelle annonce|new listing|neues angebot|nuova inserzione|nuevo anuncio|nieuwe advertentie|"
    r"nowa oferta|sponsoris[ée]|sponsored|gesponsert|sponsorizzato|patrocinado)\s*",
    re.IGNORECASE,
)
_TITLE_SUFFIX_NOISE = re.compile(
    r"\s*(?:la page s'ouvre dans une nouvelle fen[êe]tre ou un nouvel onglet|"
    r"opens in a new window or tab|wird in neuem fenster oder tab ge[öo]ffnet|"
    r"si apre in una nuova finestra o scheda|se abre en una nueva ventana o pesta[ñn]a|"
    r"wordt geopend in een nieuw venster of tabblad|otwiera si[ęe] w nowym oknie lub karcie)\s*$",
    re.IGNORECASE,
)
_SHIPPING_WORDS = re.compile(
    r"livraison|shipping|postage|delivery|versand|lieferung|spedizione|env[íi]o|verzending|dostawa|"
    r"retrait|collect|abholung",
    re.IGNORECASE,
)
_LOCATION_WORDS = re.compile(r"^(?:de |from |aus |da |desde |uit |z |situ[ée] |located in )", re.IGNORECASE)
_BIDS_RE = re.compile(r"(\d+)\s*(?:ench[èe]res?|bids?|gebote?|offert[ae]|pujas?|biedingen|ofert)", re.IGNORECASE)
_AUCTION_WORDS = re.compile(
    r"ench[èe]re|\bbids?\b|\bgebot|offerte|\bpujas?\b|bieding|licytac|time left|temps restant|restant",
    re.IGNORECASE,
)

_BLOCK_MARKERS = (
    "pardon our interruption",
    "splashui/challenge",
    "/splashui/captcha",
    "captcha-delivery",
    "please verify yourself",
    "vérifiez que vous n'êtes pas un robot",
    "access denied",
)


class BlockedError(RuntimeError):
    """eBay answered with an anti-bot / captcha page."""


@dataclass(slots=True)
class ParseResult:
    listings: list[Listing] = field(default_factory=list)
    total_containers: int = 0
    layout: str = "none"
    no_exact_results: bool = False


def is_block_page(html: str) -> bool:
    head = html[:20000].lower()
    if any(marker in head for marker in _BLOCK_MARKERS):
        return "/itm/" not in html   # a normal page that merely mentions it is fine
    return False


def extract_item_id(href: str | None) -> str | None:
    if not href:
        return None
    match = ITEM_ID_RE.search(href)
    if not match:
        return None
    item_id = match.group(1)
    return None if item_id in _PLACEHOLDER_IDS else item_id


def _has_descendant(node: LexborNode, selector: str) -> bool:
    """True if a *descendant* matches (lexbor's css() also matches the node itself)."""
    own = node.mem_id
    return any(found.mem_id != own for found in node.css(selector))


def _first_text(node: LexborNode, selectors: tuple[str, ...]) -> str:
    for sel in selectors:
        found = node.css_first(sel)
        if found is not None:
            text = clean_spaces(found.text(separator=" "))
            if text:
                return text
    return ""


def _clean_title(raw: str) -> str:
    title = clean_spaces(raw)
    # Hidden accessibility suffix and "New listing" badge.
    previous = None
    while previous != title:
        previous = title
        title = _TITLE_NOISE.sub("", title)
        title = _TITLE_SUFFIX_NOISE.sub("", title)
    return title.strip()


def _title_from(node: LexborNode) -> str:
    title_node = None
    for sel in _CARD_TITLE_CONTAINERS:
        title_node = node.css_first(sel)
        if title_node is not None:
            break
    if title_node is not None:
        # Drop the hidden "opens in a new window" span and badges before reading.
        parts = []
        for child in title_node.css("span"):
            cls = child.attributes.get("class") or ""
            if "clipped" in cls or "LIGHT_HIGHLIGHT" in cls or "s-item__new-listing" in cls:
                continue
            if _has_descendant(child, "span"):
                continue   # wrapper span, its leaves are visited separately
            parts.append(child.text())
        text = " ".join(parts) if parts else title_node.text(separator=" ")
        title = _clean_title(text)
        if title:
            return title
    title = _clean_title(_first_text(node, _TITLE_SELECTORS))
    if title:
        return title
    img = node.css_first("img[alt]")
    if img is not None:
        alt = _clean_title(img.attributes.get("alt") or "")
        if alt:
            return alt
    # Last resort: the longest link text of the card.
    texts = [_clean_title(a.text(separator=" ")) for a in node.css("a[href*='/itm/']")]
    return max(texts, key=len, default="") if any(len(t) > 3 for t in texts) else ""


def _image_from(node: LexborNode) -> str | None:
    for img in node.css("img"):
        attrs = img.attributes
        for key in ("data-defer-load", "data-src", "src"):
            src = attrs.get(key)
            if src and src.startswith("http") and "ebaystatic.com/rs/" not in src and not src.endswith(".gif"):
                return _upgrade_image(src)
        srcset = attrs.get("srcset") or attrs.get("data-srcset")
        if srcset:
            first = srcset.split(",")[0].strip().split(" ")[0]
            if first.startswith("http"):
                return _upgrade_image(first)
    return None


_IMG_SIZE_RE = re.compile(r"/s-l\d+\.(jpg|jpeg|png|webp)", re.IGNORECASE)


def _upgrade_image(url: str) -> str:
    """eBay thumbnails (s-l140) -> 500 px version, much nicer in notifications."""
    url = url.replace("/thumbs/images/", "/images/")
    return _IMG_SIZE_RE.sub(lambda m: f"/s-l500.{m.group(1)}", url)


def _subtitles(node: LexborNode) -> str:
    """eBay may show several subtitle rows (product line, condition): keep them all, once."""
    for sel in _SUBTITLE_SELECTORS:
        found = [clean_spaces(n.text(separator=" ")) for n in node.css(sel)]
        found = [t for t in dict.fromkeys(found) if t]
        if found:
            # drop rows that are contained in another one (nested matches)
            rows = [t for t in found if not any(t != o and t in o for o in found)]
            return " · ".join(rows)
    return ""


_ROW_SELECTORS = (".s-card__attribute-row", "[class*='card__row']", "[class*='attribute-row']")


def _attribute_rows(node: LexborNode) -> list[str]:
    """Secondary info lines of a card (price, shipping, location, bids...)."""
    for sel in _ROW_SELECTORS:
        rows = [clean_spaces(r.text(separator=" ")) for r in node.css(sel)]
        rows = [r for r in rows if r]
        if rows:
            return rows
    # Unknown markup: short leaf texts outside the title.
    title_ids = {n.mem_id for sel in _CARD_TITLE_CONTAINERS for t in node.css(sel) for n in t.css("*")}
    rows = []
    for leaf in node.css("span, div, p, li"):
        if leaf.mem_id in title_ids or _has_descendant(leaf, "span, div, p, li, a"):
            continue
        text = clean_spaces(leaf.text(separator=" "))
        if 0 < len(text) <= 80 and text not in rows:
            rows.append(text)
    return rows


_CURRENCY_HINT = re.compile(r"€|£|\$|\b(?:EUR|GBP|USD|CHF|PLN|CAD|AUD)\b|zł", re.IGNORECASE)


def _find_price_text(node: LexborNode, rows: list[str], currency: str) -> str:
    text = _first_text(node, _PRICE_SELECTORS)
    if text:
        return text
    # Fallback: first attribute row that parses as a price.
    for row in rows:
        value, _ = parse_price(row, None)
        if value is not None and not _SHIPPING_WORDS.search(row) and _CURRENCY_HINT.search(row):
            return row
    # Unknown markup: first short leaf text that looks like a price.
    for leaf in node.css("span, div, p, strong, b"):
        if _has_descendant(leaf, "span, div, p"):
            continue
        text = clean_spaces(leaf.text())
        if 0 < len(text) <= 40 and not _SHIPPING_WORDS.search(text) and _CURRENCY_HINT.search(text):
            value, _ = parse_price(text, None)
            if value is not None:
                return text
    return ""


def _build_listing(node: LexborNode, item_id: str, market: Market) -> Listing | None:
    title = _title_from(node)
    if not title or title.lower() in ("shop on ebay", "achetez sur ebay", "bei ebay shoppen"):
        return None
    rows = _attribute_rows(node)
    price_text = _find_price_text(node, rows, market.currency)
    price, currency = parse_price(price_text, market.currency)

    shipping = _first_text(node, _SHIPPING_SELECTORS)
    location = _first_text(node, _LOCATION_SELECTORS)
    bids_text = _first_text(node, _BIDS_SELECTORS)
    for row in rows:
        if not shipping and _SHIPPING_WORDS.search(row) and row != price_text:
            shipping = row
        elif not location and _LOCATION_WORDS.search(row):
            location = row
        elif not bids_text and _BIDS_RE.search(row):
            bids_text = row

    bids = None
    match = _BIDS_RE.search(bids_text) if bids_text else None
    if match:
        bids = int(match.group(1))
    full_text = node.text(separator=" ")
    is_auction = bids is not None or (
        bool(_AUCTION_WORDS.search(" ".join(rows + [bids_text]))) and "achat immédiat" not in full_text.lower()
    )

    return Listing(
        item_id=item_id,
        market=market.code,
        title=title,
        url=market.item_url(item_id),
        price=price,
        currency=currency,
        price_text=price_text,
        shipping_text=shipping,
        image_url=_image_from(node),
        subtitle=_subtitles(node),
        location_text=location,
        is_auction=is_auction,
        bids=bids,
    )


def _is_rewrite_divider(node: LexborNode) -> bool:
    """eBay's "Results matching fewer words" separator: what follows is not a real match."""
    cls = node.attributes.get("class") or ""
    return "REWRITE_START" in cls or "srp-river-answer--REWRITE" in cls


def _container_id(node: LexborNode) -> str | None:
    listing_id = node.attributes.get("data-listingid")
    if listing_id and listing_id.isdigit() and 9 <= len(listing_id) <= 15:
        return listing_id
    for link in node.css("a[href]"):
        item_id = extract_item_id(link.attributes.get("href"))
        if item_id:
            return item_id
    return None


def _cut_after_divider(tree: LexborHTMLParser) -> bool:
    """Remove everything after eBay's "Results matching fewer words" divider (document order)."""
    divider = tree.css_first("[class*='REWRITE_START']")
    if divider is None:
        return False
    node = divider
    while node is not None and node.tag not in ("body", "html"):
        sibling = node.next
        while sibling is not None:
            following = sibling.next
            sibling.decompose()
            sibling = following
        node = node.parent
    divider.decompose()
    return True


_KNOWN_CARD_SELECTOR = "li.s-card, [data-listingid], .su-item-card, .s-item-card, li.s-item"


def _layout_of(node: LexborNode) -> str:
    classes = (node.attributes.get("class") or "").split()
    if "s-item" in classes:
        return "s-item"
    if "su-item-card" in classes or "s-item-card" in classes:
        return "search-evo"
    return "s-card"


def _known_cards(root: LexborNode) -> tuple[list[LexborNode], str]:
    nodes = root.css(_KNOWN_CARD_SELECTOR)
    ids = {n.mem_id for n in nodes}
    cards = []
    for node in nodes:
        parent, nested = node.parent, False
        while parent is not None:
            if parent.mem_id in ids:
                nested = True
                break
            parent = parent.parent
        if not nested:
            cards.append(node)
    layouts = {_layout_of(n) for n in cards}
    layout = layouts.pop() if len(layouts) == 1 else ("mixed" if layouts else "none")
    return cards, layout


def _structural_cards(root: LexborNode) -> list[LexborNode]:
    """For each item link, the largest ancestor that contains no other listing."""
    cache: dict[int, set[str]] = {}

    def ids_in(n: LexborNode) -> set[str]:
        key = n.mem_id
        if key not in cache:
            cache[key] = {
                i for a in n.css("a[href*='/itm/']") if (i := extract_item_id(a.attributes.get("href")))
            }
        return cache[key]

    root_id = root.mem_id
    cards: list[LexborNode] = []
    seen: set[str] = set()
    for link in root.css("a[href*='/itm/']"):
        item_id = extract_item_id(link.attributes.get("href"))
        if not item_id or item_id in seen:
            continue
        node = link
        while (
            node.parent is not None
            and node.mem_id != root_id
            and node.parent.tag not in ("body", "html")
            and ids_in(node.parent) <= {item_id}
        ):
            node = node.parent
        seen.add(item_id)
        cards.append(node)
    return cards


def parse_search_page(html: str, market: Market) -> ParseResult:
    if is_block_page(html):
        raise BlockedError("Page anti-robot eBay (captcha / challenge)")

    # <wbr> (word-break hint) splits words in long titles: drop it before parsing.
    tree = LexborHTMLParser(_WBR_RE.sub("", html))
    result = ParseResult()
    had_divider = _cut_after_divider(tree)

    root = (
        tree.css_first("#srp-river-results")
        or tree.css_first(".srp-river-results")
        or tree.css_first("ul.srp-results")
        or tree.body
    )
    if root is None:
        return result

    candidates, layout = _known_cards(root)
    if not candidates:
        candidates = _structural_cards(root)
        layout = "fallback" if candidates else "none"

    result.layout = layout
    result.total_containers = len(candidates)
    seen_ids: set[str] = set()
    for node in candidates:
        item_id = _container_id(node)
        if not item_id or item_id in seen_ids:
            continue
        listing = _build_listing(node, item_id, market)
        if listing is None:
            continue
        seen_ids.add(item_id)
        result.listings.append(listing)
    result.no_exact_results = had_divider and not result.listings
    return result
