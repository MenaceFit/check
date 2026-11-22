from ebaywatch.models import Listing
from ebaywatch.store import Store


def test_seen_and_baseline(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    assert not store.is_baselined("s", "fr")
    store.mark_baselined("s", "fr")
    assert store.is_baselined("s", "fr") and not store.is_baselined("s", "uk")

    assert store.unseen("s", ["1", "2", "3"]) == ["1", "2", "3"]
    store.mark_seen("s", ["1", "2"])
    assert store.unseen("s", ["1", "2", "3", "3"]) == ["3"]
    assert store.unseen("other", ["1"]) == ["1"]          # isolated per search
    store.reset_search("s")
    assert store.unseen("s", ["1"]) == ["1"] and not store.is_baselined("s", "fr")
    store.close()


def test_unseen_large_batches(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    ids = [str(i) for i in range(1300)]
    store.mark_seen("s", ids[:1000])
    assert store.unseen("s", ids) == ids[1000:]


def test_listings_history_and_persistence(tmp_path):
    path = tmp_path / "db.sqlite"
    store = Store(path)
    listing = Listing(item_id="42", market="fr", title="Titre é", url="https://www.ebay.fr/itm/42", price=9.5,
                      currency="EUR", search_name="S")
    store.add_listing("s", listing)
    store.add_listing("s", listing)          # idempotent
    store.close()

    reopened = Store(path)
    assert reopened.count_listings() == 1
    [back] = reopened.recent_listings()
    assert back.title == "Titre é" and back.price == 9.5 and back.found_at == listing.found_at


def test_prune(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.mark_seen("s", ["1"])
    assert store.prune(max_age_days=0) == 1
    assert store.unseen("s", ["1"]) == ["1"]
