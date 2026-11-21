from lbcsniper.lbc.query import build_payload, build_web_url, config_from_url, parse_location
from lbcsniper.models import ExtraFilter, Location, SearchConfig


def test_url_import_basic():
    url = (
        "https://www.leboncoin.fr/recherche?category=15&text=rtx%203070&price=400-700"
        "&owner_type=private&shippable=1&search_in=subject&sort=time"
    )
    cfg = config_from_url(url)
    assert cfg.keywords == "rtx 3070"
    assert cfg.name == "rtx 3070"
    assert cfg.category == "15"
    assert (cfg.price_min, cfg.price_max) == (400, 700)
    assert cfg.owner_type == "private"
    assert cfg.shippable_only and cfg.title_only
    assert cfg.extra_filters == []


def test_url_import_locations_and_custom_fields():
    url = (
        "https://www.leboncoin.fr/recherche?category=2&locations=Lyon_69003__45.75917_4.82965_5000_20000,d_75,r_22"
        "&mileage=min-100000&regdate=2015-max&fuel=1,2&price=min-9000"
    )
    cfg = config_from_url(url)
    city, dept, region = cfg.locations
    assert (city.type, city.city, city.zipcode, city.lat, city.radius_km) == ("city", "Lyon", "69003", 45.75917, 20.0)
    assert dept.type == "department" and dept.department_id == "75"
    assert region.type == "region" and region.region_id == "22"
    extras = {f.key: f for f in cfg.extra_filters}
    assert extras["mileage"].kind == "range" and extras["mileage"].min is None and extras["mileage"].max == 100000
    assert extras["regdate"].min == 2015 and extras["regdate"].max is None
    assert extras["fuel"].kind == "enum" and extras["fuel"].values == ["1", "2"]
    assert cfg.price_min is None and cfg.price_max == 9000


def test_payload():
    cfg = SearchConfig(
        keywords="rtx", title_only=True, category="15", price_min=100, price_max=700,
        owner_type="private", shippable_only=True,
        locations=[Location(type="city", city="Paris", zipcode="75011", lat=48.85, lng=2.37, radius_km=10)],
        extra_filters=[ExtraFilter(key="item_condition", values=["1", "2"]), ExtraFilter(key="ram", kind="range", min=16)],
    )
    p = build_payload(cfg)
    f = p["filters"]
    assert p["sort_by"] == "time" and p["sort_order"] == "desc"
    assert p["owner_type"] == "private"
    assert f["category"] == {"id": "15"}
    assert f["keywords"] == {"text": "rtx", "type": "subject"}
    assert f["ranges"]["price"] == {"min": 100, "max": 700}
    assert f["ranges"]["ram"] == {"min": 16}
    assert f["enums"]["item_condition"] == ["1", "2"]
    assert f["enums"]["shippable"] == ["true"]
    loc = f["location"]["locations"][0]
    assert loc["locationType"] == "city" and loc["area"]["radius"] == 10000


def test_web_url_roundtrip():
    url = "https://www.leboncoin.fr/recherche?category=15&text=pc%20gamer&locations=d_69&price=300-max&item_condition=1,2"
    cfg = config_from_url(url)
    rebuilt = config_from_url(build_web_url(cfg))
    assert rebuilt.model_dump() == cfg.model_dump()


def test_parse_location_plain_city():
    loc = parse_location("Paris__48.86023_2.33863_9256")
    assert loc.city == "Paris" and loc.default_radius == 9256 and loc.radius_km is None
