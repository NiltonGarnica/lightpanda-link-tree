"""Sitio de prueba que registra que peticiones recibieron el token."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "Bearer token-de-prueba"
OTHER = "http://site-b:8000"

PAGES = {
    "/": (
        "Tienda Demo",
        f"""<script src="{OTHER}/tercero.js"></script>
        <a href="/productos">Productos</a>
        <a href="/contacto#formulario">Contacto</a>
        <a href="/privado">Zona privada</a>
        <a href="/salir">Salir</a>
        <a href="/roto">Roto</a>
        <a href="{OTHER}/externo">Externo</a>
        <a href="mailto:hola@site-a">Correo</a>
        <script>
          fetch('/datos.json');
          fetch('{OTHER}/datos.json');
          setTimeout(() => {{
            const a = document.createElement('a');
            a.href = '/novedades';
            a.textContent = 'Novedades';
            document.body.appendChild(a);
          }}, 200);
        </script>""",
    ),
    "/productos": ("Productos", '<a href="/productos/camisetas">Camisetas</a><a href="/">Inicio</a>'),
    "/productos/camisetas": ("Camisetas", '<a href="/productos/camisetas/rojas">Rojas</a>'),
    "/productos/camisetas/rojas": ("Rojas", '<a href="/nivel-cuatro">Nivel cuatro</a>'),
    "/nivel-cuatro": ("Nivel cuatro", '<a href="/nivel-cinco">Nivel cinco</a>'),
    "/contacto": ("Contacto", '<a href="/productos">Productos</a>'),
    "/novedades": ("Novedades", ""),
    "/externo": ("Otro sitio", ""),
    "/landing": ("Otro sitio", '<a href="/no-seguir">No seguir</a>'),
}

log: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", content_type="text/html", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/__log":
            self._send(200, json.dumps(log).encode(), "application/json")
            return
        if path == "/__reset":
            log.clear()
            self._send(200)
            return

        authorization = self.headers.get("Authorization")
        log.append({"host": self.headers.get("Host"), "path": path, "auth": authorization})

        if path == "/salir":
            self._send(302, headers={"Location": f"{OTHER}/landing"})
        elif path == "/privado":
            if authorization == TOKEN:
                self._send(200, b'<title>Privado</title><a href="/privado/panel">Panel</a>')
            else:
                self._send(401, b"<title>No autorizado</title>")
        elif path == "/privado/panel":
            self._send(200, b"<title>Panel</title>")
        elif path in PAGES:
            title, body = PAGES[path]
            self._send(200, f"<html><head><title>{title}</title></head><body>{body}</body></html>".encode())
        elif path.endswith(".js"):
            self._send(200, b"", "text/javascript")
        elif path.endswith(".json"):
            self._send(200, b"{}", "application/json")
        else:
            self._send(404, b"<title>No existe</title>")


ThreadingHTTPServer(("", 8000), Handler).serve_forever()
