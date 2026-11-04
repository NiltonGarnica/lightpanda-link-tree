import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.services.url_policy import HostGuard, same_site

STABLE_POLLS = 3
POLL_INTERVAL_SECONDS = 0.25
MAX_SETTLE_SECONDS = 3.0
MAX_MESSAGE_BYTES = 32 * 1024 * 1024

READ_LINKS = """JSON.stringify({
  href: location.href,
  title: document.title,
  links: [...document.querySelectorAll('a[href]')].map(a => ({
    url: a.href,
    text: (a.textContent || '').trim().slice(0, 200)
  }))
})"""


class LightpandaUnavailable(Exception):
    pass


class CdpError(Exception):
    pass


@dataclass
class PageLink:
    url: str
    text: str = ""


@dataclass
class PageResult:
    final_url: str | None = None
    title: str | None = None
    links: list[PageLink] = field(default_factory=list)
    http_status: int | None = None
    error: str | None = None


class PageVisitor(Protocol):
    async def visit(
        self, url: str, *, token: str | None, root_url: str, guard: HostGuard
    ) -> PageResult: ...


class _CdpSession:
    def __init__(
        self, ws: ClientConnection, token: str | None, root_url: str, guard: HostGuard
    ) -> None:
        self._ws = ws
        self._token = token
        self._root_url = root_url
        self._guard = guard
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._session_id: str | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self.loaded = asyncio.Event()
        self.http_status: int | None = None

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        message_id = self._next_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[message_id] = future
        message: dict[str, Any] = {"id": message_id, "method": method, "params": params or {}}
        if self._session_id:
            message["sessionId"] = self._session_id
        await self._ws.send(json.dumps(message))
        return await future

    async def attach(self) -> None:
        target = await self.call("Target.createTarget", {"url": "about:blank"})
        attached = await self.call(
            "Target.attachToTarget", {"targetId": target["targetId"], "flatten": True}
        )
        self._session_id = attached["sessionId"]
        await self.call("Page.enable")
        await self.call("Network.enable")
        await self.call("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})

    async def read_loop(self) -> None:
        try:
            async for raw in self._ws:
                self._dispatch(json.loads(raw))
        except ConnectionClosed:
            pass
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(CdpError("Lightpanda cerro la conexion"))
            self._pending.clear()

    def _dispatch(self, message: dict[str, Any]) -> None:
        future = self._pending.pop(message.get("id", -1), None)
        if future is not None:
            if future.done():
                return
            if "error" in message:
                future.set_exception(CdpError(str(message["error"].get("message", "error CDP"))))
            else:
                future.set_result(message.get("result", {}))
            return
        method = message.get("method")
        params = message.get("params", {})
        if method == "Page.loadEventFired":
            self.loaded.set()
        elif method == "Network.responseReceived" and params.get("type") == "Document":
            self.http_status = params.get("response", {}).get("status")
        elif method == "Fetch.requestPaused":
            task = asyncio.create_task(self._on_request(params))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _on_request(self, params: dict[str, Any]) -> None:
        # El token se decide peticion por peticion: setExtraHTTPHeaders tambien lo
        # enviaria a scripts de terceros y a redirecciones hacia otros dominios.
        request_id = params["requestId"]
        request = params.get("request", {})
        url = request.get("url", "")
        try:
            if url.startswith(("http://", "https://")) and not await self._guard.allowed(url):
                await self.call(
                    "Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"}
                )
                return
            headers = [
                {"name": name, "value": value}
                for name, value in request.get("headers", {}).items()
                if name.lower() != "authorization"
            ]
            if self._token and same_site(url, self._root_url):
                headers.append({"name": "Authorization", "value": f"Bearer {self._token}"})
            await self.call("Fetch.continueRequest", {"requestId": request_id, "headers": headers})
        except (CdpError, ConnectionClosed):
            pass

    async def read_page(self) -> dict[str, Any]:
        result = await self.call(
            "Runtime.evaluate", {"expression": READ_LINKS, "returnByValue": True}
        )
        if "exceptionDetails" in result:
            raise CdpError("no se pudo leer la pagina")
        return json.loads(result["result"]["value"])

    def close(self) -> None:
        for task in self._tasks:
            task.cancel()


class LightpandaClient:
    def __init__(self, ws_url: str, page_timeout: float) -> None:
        self._ws_url = ws_url
        self._page_timeout = page_timeout

    async def visit(
        self, url: str, *, token: str | None, root_url: str, guard: HostGuard
    ) -> PageResult:
        # Cada pagina usa su propia conexion: no comparte estado y Lightpanda no
        # la corta por inactividad mientras se espera el siguiente nivel.
        try:
            ws = await connect(
                self._ws_url, open_timeout=10, max_size=MAX_MESSAGE_BYTES, proxy=None
            )
        except (OSError, TimeoutError, WebSocketException) as exc:
            raise LightpandaUnavailable(f"no se pudo conectar con Lightpanda: {exc}") from exc

        session = _CdpSession(ws, token, root_url, guard)
        reader = asyncio.create_task(session.read_loop())
        try:
            return await asyncio.wait_for(self._load(session, url), self._page_timeout)
        except TimeoutError:
            return PageResult(error="la pagina supero el tiempo de espera")
        except (CdpError, ConnectionClosed, KeyError, ValueError) as exc:
            return PageResult(error=str(exc) or "error al cargar la pagina")
        finally:
            session.close()
            reader.cancel()
            await ws.close()

    async def _load(self, session: _CdpSession, url: str) -> PageResult:
        await session.attach()
        navigation = await session.call("Page.navigate", {"url": url})
        if navigation.get("errorText"):
            return PageResult(error=navigation["errorText"], http_status=session.http_status)
        await session.loaded.wait()
        page = await self._settled_page(session)
        return PageResult(
            final_url=page.get("href"),
            title=(page.get("title") or "").strip() or None,
            links=[PageLink(link["url"], link.get("text", "")) for link in page.get("links", [])],
            http_status=session.http_status,
        )

    @staticmethod
    async def _settled_page(session: _CdpSession) -> dict[str, Any]:
        """Espera a que JavaScript deje de agregar enlaces."""
        deadline = time.monotonic() + MAX_SETTLE_SECONDS
        page = await session.read_page()
        stable = 1
        while stable < STABLE_POLLS and time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            current = await session.read_page()
            stable = stable + 1 if len(current["links"]) == len(page["links"]) else 1
            page = current
        return page
