from collections import Counter

from app.services.tags import TagStore, tags_for_link


def test_tags_use_path_then_title_without_accents_or_stopwords():
    tags = tags_for_link("https://x.com/productos/camisetas.html", "Catálogo de las camisetas")
    assert tags == ["productos", "camisetas", "catalogo"]


def test_tags_skip_numeric_ids():
    assert tags_for_link("https://x.com/items/123456/a1b2c3", None) == ["items"]


def test_tags_have_a_limit():
    title = " ".join(f"palabra{letter}" for letter in "abcdefghijkl")
    assert len(tags_for_link("https://x.com/", title)) == 8


def test_suggest_matches_prefix_ordered_by_count():
    store = TagStore()
    store.save("t1", Counter({"producto": 1, "proyecto": 3, "camiseta": 5}))
    suggestions = store.suggest("t1", "PRO")
    assert [(s.tag, s.count) for s in suggestions] == [("proyecto", 3), ("producto", 1)]


def test_suggest_ignores_accents_and_respects_limit():
    store = TagStore()
    store.save("t1", Counter({"catalogo": 2, "catalina": 1}))
    assert [s.tag for s in store.suggest("t1", "catá", limit=1)] == ["catalogo"]


def test_suggest_keeps_trees_separate():
    store = TagStore()
    store.save("t1", Counter({"secreto": 1}))
    store.save("t2", Counter({"publico": 1}))
    assert store.suggest("t2", "sec") == []
    assert store.suggest("no-existe", "") is None


def test_store_drops_oldest_tree():
    store = TagStore(max_trees=1)
    store.save("t1", Counter({"uno": 1}))
    store.save("t2", Counter({"dos": 1}))
    assert store.suggest("t1", "") is None
