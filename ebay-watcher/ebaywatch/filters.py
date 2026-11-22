"""Client-side filtering of listings (in addition to eBay's own filters)."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config, Search
from .models import Listing
from .textutils import contains_term, normalize, tokenize_query


@dataclass(slots=True, frozen=True)
class FilterDecision:
    accepted: bool
    reason: str = ""


class ListingFilter:
    """Pre-computes the normalised terms of one search for fast matching."""

    def __init__(self, search: Search, config: Config) -> None:
        self.search = search
        self.config = config
        self.strict = config.general.strict_title_match
        required, excluded = tokenize_query(search.keywords)
        self.required = required
        self.excluded = excluded + [normalize(w) for w in search.exclude if w.strip()]

    def check(self, listing: Listing) -> FilterDecision:
        title = normalize(listing.title)
        for word in self.excluded:
            if word and contains_term(title, word):
                return FilterDecision(False, f"mot exclu « {word} »")
        if self.strict:
            for word in self.required:
                if not contains_term(title, word):
                    return FilterDecision(False, f"mot-clé « {word} » absent du titre")
        if listing.price is not None and (self.search.min_price or self.search.max_price):
            price = self.config.convert(listing.price, listing.currency or self.search.currency, self.search.currency)
            if self.search.min_price is not None and price < self.search.min_price:
                return FilterDecision(False, f"prix {price:.2f} < min")
            if self.search.max_price is not None and price > self.search.max_price:
                return FilterDecision(False, f"prix {price:.2f} > max")
        return FilterDecision(True)
