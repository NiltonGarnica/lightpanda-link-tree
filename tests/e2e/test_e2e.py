"""Prueba con Lightpanda real. Requiere levantar docker-compose.e2e.yml (ver README)."""

import os

import httpx
import pytest

API_URL = os.getenv("E2E_API_URL")
SITE_URL = os.getenv("E2E_SITE_URL", "http://127.0.0.1:8081")
ROOT = "http://site-a:8000/"
TOKEN = "token-de-prueba"

pytestmark = pytest.mark.skipif(not API_URL, reason="define E2E_API_URL para ejecutarla")


def http_client(base_url):
    return httpx.Client(base_url=base_url, timeout=120, trust_env=False)


def crawl(**payload):
    with http_client(SITE_URL) as site:
        site.get("/__reset").raise_for_status()
    with http_client(API_URL) as api:
        response = api.post("/api/v1/link-tree", json={"url": ROOT, **payload})
    response.raise_for_status()
    return response.json()


def site_log():
    with http_client(SITE_URL) as site:
        return site.get("/__log").json()


def walk(node):
    yield node
    for child in node["children"]:
        yield from walk(child)


def by_path(tree):
    return {node["url"].removeprefix("http://site-a:8000"): node for node in walk(tree)}


def test_health_reports_lightpanda():
    with http_client(API_URL) as api:
        response = api.get("/health")
    assert response.status_code == 200
    assert response.json()["lightpanda"]["status"] == "ok"


def test_tree_reaches_third_level_and_stops():
    nodes = by_path(crawl(bearer_token=TOKEN)["tree"])
    assert nodes["/"]["level"] == 0 and nodes["/"]["title"] == "Tienda Demo"
    assert nodes["/productos"]["level"] == 1
    assert nodes["/productos/camisetas"]["level"] == 2
    assert nodes["/productos/camisetas/rojas"]["level"] == 3
    assert nodes["/productos/camisetas/rojas"]["status"] == "not_visited"
    assert "/nivel-cuatro" not in nodes


def test_level_three_is_not_opened():
    crawl(bearer_token=TOKEN)
    assert "/productos/camisetas/rojas" not in {entry["path"] for entry in site_log()}


def test_links_added_by_javascript_are_found():
    assert "/novedades" in by_path(crawl()["tree"])


def test_duplicates_and_fragments_appear_once():
    urls = [node["url"] for node in walk(crawl()["tree"])]
    assert len(urls) == len(set(urls))
    assert "http://site-a:8000/contacto" in urls


def test_external_links_are_not_followed():
    result = crawl()
    assert not any("site-b" in node["url"] for node in walk(result["tree"]))
    assert result["stats"]["external_links_skipped"] == 1


def test_broken_link_is_reported_without_stopping():
    result = crawl()
    node = by_path(result["tree"])["/roto"]
    assert node["status"] == "error" and node["http_status"] == 404
    assert by_path(result["tree"])["/productos"]["status"] == "ok"


def test_token_opens_private_area():
    nodes = by_path(crawl(bearer_token=TOKEN)["tree"])
    assert nodes["/privado"]["status"] == "ok"
    assert "/privado/panel" in nodes


def test_without_token_private_area_is_reported():
    nodes = by_path(crawl()["tree"])
    assert nodes["/privado"]["status"] == "error" and nodes["/privado"]["http_status"] == 401
    assert "/privado/panel" not in nodes


def test_token_never_reaches_another_domain():
    crawl(bearer_token=TOKEN)
    log = site_log()
    other_site = [entry for entry in log if entry["host"].startswith("site-b")]
    same_site = [entry for entry in log if entry["host"].startswith("site-a")]
    assert other_site, "el sitio de prueba debe recibir peticiones en site-b"
    assert all(entry["auth"] is None for entry in other_site)
    assert all(entry["auth"] == f"Bearer {TOKEN}" for entry in same_site)


def test_redirect_to_another_domain_is_marked_and_not_followed():
    nodes = by_path(crawl(bearer_token=TOKEN)["tree"])
    assert nodes["/salir"]["status"] == "external_redirect"
    assert nodes["/salir"]["children"] == []


def test_token_is_not_returned():
    with http_client(SITE_URL) as site:
        site.get("/__reset")
    with http_client(API_URL) as api:
        response = api.post("/api/v1/link-tree", json={"url": ROOT, "bearer_token": TOKEN})
    assert TOKEN not in response.text


def test_tags_autocomplete_from_real_tree():
    result = crawl()
    with http_client(API_URL) as api:
        response = api.get("/api/v1/tags", params={"tree_id": result["tree_id"], "q": "cam"})
    assert [item["tag"] for item in response.json()["suggestions"]] == ["camisetas"]
