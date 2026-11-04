import asyncio

import pytest

from app.services.url_policy import HostGuard, dedupe_key, normalize_url, same_site


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("HTTPS://Ejemplo.com", "https://ejemplo.com/"),
        ("https://ejemplo.com:443/a#seccion", "https://ejemplo.com/a"),
        ("http://ejemplo.com:8080/a?x=1", "http://ejemplo.com:8080/a?x=1"),
        ("mailto:hola@ejemplo.com", None),
        ("javascript:void(0)", None),
        ("https://usuario:clave@ejemplo.com/", None),
    ],
)
def test_normalize_url(url, expected):
    assert normalize_url(url) == expected


@pytest.mark.parametrize(
    ("url", "root", "expected"),
    [
        ("https://ejemplo.com/a", "https://ejemplo.com/", True),
        ("https://www.ejemplo.com/a", "https://ejemplo.com/", True),
        ("https://api.ejemplo.com/", "https://ejemplo.com/", False),
        ("https://ejemplo.com.evil.io/", "https://ejemplo.com/", False),
        ("http://ejemplo.com/", "https://ejemplo.com/", False),
        ("https://ejemplo.com/", "http://ejemplo.com/", True),
        ("http://ejemplo.com:8080/", "http://ejemplo.com/", False),
    ],
)
def test_same_site(url, root, expected):
    assert same_site(url, root) is expected


def test_dedupe_key_ignores_trailing_slash_and_www():
    assert dedupe_key("https://www.ejemplo.com/a/") == dedupe_key("https://ejemplo.com/a")
    assert dedupe_key("https://ejemplo.com/a?x=1") != dedupe_key("https://ejemplo.com/a?x=2")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
    ],
)
def test_guard_blocks_internal_addresses(url):
    assert asyncio.run(HostGuard().allowed(url)) is False


def test_guard_allows_public_ip_and_private_when_enabled():
    assert asyncio.run(HostGuard().allowed("http://8.8.8.8/")) is True
    assert asyncio.run(HostGuard(allow_private=True).allowed("http://127.0.0.1/")) is True
