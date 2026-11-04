import logging

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_visitor
from app.config import Settings, get_settings
from app.main import app
from app.services.lightpanda_client import LightpandaUnavailable, PageLink, PageResult

ROOT = "https://x.com/"


class FakeVisitor:
    def __init__(self):
        self.tokens = []

    async def visit(self, url, *, token, root_url, guard):
        self.tokens.append(token)
        links = [PageLink("https://x.com/productos", "Productos")] if url == ROOT else []
        return PageResult(final_url=url, http_status=200, title="Inicio", links=links)


@pytest.fixture
def visitor():
    return FakeVisitor()


@pytest.fixture
def client(visitor):
    app.dependency_overrides[get_visitor] = lambda: visitor
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, allow_private_networks=True
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_link_tree_returns_tree_and_tags(client):
    response = client.post("/api/v1/link-tree", json={"url": ROOT})
    assert response.status_code == 200
    body = response.json()
    assert body["tree"]["url"] == ROOT
    assert body["tree"]["children"][0]["url"] == "https://x.com/productos"
    assert body["tree"]["children"][0]["level"] == 1
    assert any(t["tag"] == "productos" for t in body["tags"])


def test_token_reaches_visitor_without_bearer_prefix(client, visitor):
    client.post("/api/v1/link-tree", json={"url": ROOT, "bearer_token": "Bearer abc123"})
    assert set(visitor.tokens) == {"abc123"}


def test_token_is_not_in_response_or_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    response = client.post("/api/v1/link-tree", json={"url": ROOT, "bearer_token": "supersecreto"})
    assert "supersecreto" not in response.text
    assert "supersecreto" not in caplog.text


def test_token_with_line_break_is_rejected_without_echo(client):
    response = client.post("/api/v1/link-tree", json={"url": ROOT, "bearer_token": "abc\r\nX: y"})
    assert response.status_code == 422
    assert "abc" not in response.text


@pytest.mark.parametrize("url", ["no-es-url", "ftp://x.com/", ""])
def test_invalid_url_is_rejected(client, url):
    assert client.post("/api/v1/link-tree", json={"url": url}).status_code == 422


@pytest.mark.parametrize("depth", [0, 4])
def test_depth_out_of_range_is_rejected(client, depth):
    response = client.post("/api/v1/link-tree", json={"url": ROOT, "max_depth": depth})
    assert response.status_code == 422


def test_internal_url_is_blocked_by_default(client):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    response = client.post("/api/v1/link-tree", json={"url": "http://169.254.169.254/"})
    assert response.status_code == 400


def test_lightpanda_down_returns_503(client):
    class Down:
        async def visit(self, *args, **kwargs):
            raise LightpandaUnavailable("sin conexion")

    app.dependency_overrides[get_visitor] = lambda: Down()
    response = client.post("/api/v1/link-tree", json={"url": ROOT})
    assert response.status_code == 503


def test_tags_autocomplete(client):
    tree_id = client.post("/api/v1/link-tree", json={"url": ROOT}).json()["tree_id"]
    response = client.get("/api/v1/tags", params={"tree_id": tree_id, "q": "pro"})
    assert response.status_code == 200
    assert [s["tag"] for s in response.json()["suggestions"]] == ["productos"]


def test_tags_unknown_tree_returns_404(client):
    assert client.get("/api/v1/tags", params={"tree_id": "nada"}).status_code == 404


def test_health_reports_lightpanda_down():
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, lightpanda_http_url="http://127.0.0.1:1"
    )
    response = TestClient(app).get("/health")
    app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["lightpanda"]["status"] == "unavailable"
