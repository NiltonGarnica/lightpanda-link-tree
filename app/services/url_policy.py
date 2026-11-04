import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_url(url: str) -> str | None:
    """Devuelve la URL en forma canonica, o None si no se puede recorrer."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS or not parts.hostname:
        return None
    if parts.username or parts.password:
        return None
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port in (None, DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def _site(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().removeprefix("www.")
    port = None if parts.port in (None, DEFAULT_PORTS.get(scheme)) else parts.port
    return scheme, host, port


def same_site(url: str, root_url: str) -> bool:
    """Mismo host (con o sin www) y puerto, sin bajar de https a http."""
    try:
        scheme, host, port = _site(url)
        root_scheme, root_host, root_port = _site(root_url)
    except ValueError:
        return False
    if scheme not in DEFAULT_PORTS or (root_scheme == "https" and scheme != "https"):
        return False
    return host == root_host and port == root_port


def dedupe_key(url: str) -> str:
    _, host, port = _site(url)
    parts = urlsplit(url)
    return f"{host}:{port}{parts.path.rstrip('/')}?{parts.query}"


class HostGuard:
    """Evita que el servicio se use para llegar a redes internas (SSRF)."""

    def __init__(self, allow_private: bool = False) -> None:
        self._allow_private = allow_private
        self._cache: dict[str, bool] = {}

    async def allowed(self, url: str) -> bool:
        if self._allow_private:
            return True
        try:
            host = urlsplit(url).hostname
        except ValueError:
            return False
        if not host:
            return False
        if host not in self._cache:
            self._cache[host] = await self._resolves_to_public(host)
        return self._cache[host]

    @staticmethod
    async def _resolves_to_public(host: str) -> bool:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, None, type=socket.SOCK_STREAM
            )
        except OSError:
            return False
        for info in infos:
            address = ipaddress.ip_address(info[4][0].split("%")[0])
            mapped = getattr(address, "ipv4_mapped", None)
            if not (mapped or address).is_global:
                return False
        return bool(infos)
