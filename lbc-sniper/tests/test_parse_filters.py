from datetime import datetime, timedelta, timezone

from lbcsniper.filters import check_ad
from lbcsniper.lbc.parse import ads_from_html, normalize_ad
from lbcsniper.models import SearchConfig
from lbcsniper.notifier import build_embed


def test_normalize(api_response):
    ad = normalize_ad(api_response["ads"][0])
    assert ad.list_id == "3314900003"
    assert ad.price == 650 and ad.price_label == "650 €"
    assert ad.city == "Lyon" and ad.zipcode == "69003" and ad.department == "Rhône"
    assert ad.owner_type == "Particulier" and ad.owner_name == "Max"
    assert ad.images[0] == "https://img.leboncoin.fr/L3.jpg"
    assert ad.attributes == {"État": "Très bon état"}
    assert ad.shippable is True
    assert ad.published_at.utcoffset() == timedelta(hours=1)  # heure d'hiver à Paris
    # URL reconstruite quand elle est absente
    third = normalize_ad(api_response["ads"][2])
    assert third.url.endswith("/3314900001") and third.shippable is True
    assert normalize_ad(api_response["ads"][1]).shippable is None


def test_html_fallback(api_response):
    import json

    html = (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": {"searchData": {"ads": api_response["ads"]}}}})
        + "</script></html>"
    )
    assert [a["list_id"] for a in ads_from_html(html)] == [3314900003, 3314900002, 3314900001]
    # Structure différente : recherche récursive
    html2 = '<script id="__NEXT_DATA__">' + json.dumps({"x": {"y": [{"list_id": 1}, {"list_id": 2}]}}) + "</script>"
    assert len(ads_from_html(html2)) == 2
    assert ads_from_html("<html>rien</html>") == []


def test_filters(api_response):
    good, hs, _ = (normalize_ad(r) for r in api_response["ads"])
    cfg = SearchConfig(exclude_words=["hs", "pour pièces"], price_max=700)
    assert check_ad(good, cfg)[0] is True
    ok, reason = check_ad(hs, cfg)
    assert not ok and "exclu" in reason

    # Mots obligatoires, insensibles aux accents/majuscules
    assert check_ad(good, SearchConfig(required_words=["rtx", "5800X"], required_mode="all"))[0]
    assert not check_ad(good, SearchConfig(required_words=["rtx", "4090"], required_mode="all"))[0]
    assert check_ad(good, SearchConfig(required_words=["boitier vitre"]))[0]
    # "hs" ne doit pas matcher l'intérieur d'un mot
    assert check_ad(good, SearchConfig(exclude_words=["ta"]))[0]

    assert not check_ad(hs, SearchConfig(owner_type="private"))[0]
    assert not check_ad(good, SearchConfig(price_min=700))[0]

    now = good.published_at.astimezone(timezone.utc) + timedelta(minutes=90)
    assert not check_ad(good, SearchConfig(max_age_minutes=60), now=now)[0]
    assert check_ad(good, SearchConfig(max_age_minutes=120), now=now)[0]


def test_embed(api_response):
    ad = normalize_ad(api_response["ads"][0])
    cfg = SearchConfig(name="PC", display_fields=["price", "location", "latency", "shipping", "attributes", "description", "image"])
    e = build_embed(ad, cfg, 12.4)
    names = [f["name"] for f in e["fields"]]
    assert "💶 Prix" in names and "⚡ Détectée" in names and "🧾 Caractéristiques" in names
    assert e["image"]["url"].endswith("L3.jpg")
    assert e["color"] == 0xFF6E14
    assert e["description"].startswith("Très bon état")
    assert e["timestamp"].startswith("2026-11-21T13:00:05")
    assert any("12 s" in f["value"] for f in e["fields"])
