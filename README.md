# Lightpanda Link Tree

Microservicio en Python que recibe una URL y devuelve su **árbol de enlaces** en JSON, hasta el tercer nivel de profundidad, con tags para autocompletado. Abre las páginas con [Lightpanda](https://github.com/lightpanda-io/browser), un navegador sin interfaz gráfica, por lo que también encuentra enlaces creados con JavaScript.

## Arranque rápido

Requiere Docker Desktop.

```bash
docker compose up -d --build
```

- API: http://127.0.0.1:8000
- Documentación interactiva: http://127.0.0.1:8000/docs

Para detenerlo:

```bash
docker compose down
```

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/link-tree` | Genera el árbol de enlaces |
| `GET` | `/api/v1/tags?tree_id=...&q=pro` | Sugiere tags de un árbol para autocompletar |
| `GET` | `/health` | Indica si la API y Lightpanda funcionan |

### Generar el árbol

```bash
curl -X POST http://127.0.0.1:8000/api/v1/link-tree \
  -H "Content-Type: application/json" \
  -d '{"url": "https://demo-browser.lightpanda.io/", "bearer_token": "mi-token"}'
```

| Campo | Obligatorio | Descripción |
|---|---|---|
| `url` | Sí | URL padre, con `http` o `https` |
| `bearer_token` | No | Token que se envía a las páginas del mismo sitio |
| `max_depth` | No | Niveles a recorrer, de 1 a 3. Por defecto, 3 |

Respuesta resumida:

```json
{
  "tree_id": "2558983ae2f94164b6ddedf2b8692062",
  "tree": {
    "url": "https://ejemplo.com/",
    "level": 0,
    "title": "Inicio",
    "tags": ["inicio"],
    "status": "ok",
    "http_status": 200,
    "error": null,
    "children": [
      {
        "url": "https://ejemplo.com/productos",
        "level": 1,
        "title": "Productos",
        "tags": ["productos"],
        "status": "ok",
        "http_status": 200,
        "error": null,
        "children": []
      }
    ]
  },
  "tags": [{ "tag": "productos", "count": 1 }],
  "stats": {
    "total_links": 2,
    "pages_visited": 2,
    "pages_failed": 0,
    "external_links_skipped": 0,
    "truncated": false,
    "duration_ms": 900
  }
}
```

Valores de `status`:

| Valor | Significado |
|---|---|
| `ok` | La página se abrió y se leyeron sus enlaces |
| `not_visited` | Enlace listado sin abrir: es del último nivel o se alcanzó un límite |
| `error` | La página falló; el detalle está en `error` y `http_status` |
| `external_redirect` | La página redirige a otro sitio y no se siguió |

### Autocompletar tags

```bash
curl "http://127.0.0.1:8000/api/v1/tags?tree_id=2558983ae2f94164b6ddedf2b8692062&q=am"
```

```json
{
  "tree_id": "2558983ae2f94164b6ddedf2b8692062",
  "query": "am",
  "suggestions": [{ "tag": "amiibo", "count": 145 }]
}
```

## Cómo funciona

- **Niveles:** la URL recibida es el nivel 0 y sus hijos llegan hasta el nivel 3. Los enlaces del nivel 3 se listan, pero no se abren.
- **Alcance:** solo se siguen enlaces del mismo sitio. Los externos se cuentan en `external_links_skipped`.
- **Duplicados:** cada URL aparece una sola vez, en el nivel más cercano a la raíz.
- **Tags:** salen de la ruta de la URL y del título de la página o del texto del enlace. Se quitan acentos, palabras comunes e identificadores numéricos.
- **Límites:** si se supera `MAX_LINKS` o `CRAWL_TIMEOUT_SECONDS`, se devuelve el árbol parcial con `truncated: true`.

## Seguridad

- **Token:** se decide petición por petición y solo se envía al mismo sitio. No llega a scripts de terceros ni a redirecciones hacia otros dominios, y nunca se devuelve en las respuestas.
- **Redes internas:** se rechazan las URL que apuntan a `localhost` o a direcciones privadas, y también se bloquean las peticiones de la página hacia ellas. La comprobación se hace desde la API, antes de cada petición, así que no cubre un dominio que cambie de dirección justo después de comprobarlo.
- **Autenticación:** esta API no tiene autenticación propia, por eso Docker Compose solo la publica en `127.0.0.1`. Antes de exponerla, hay que protegerla.
- **Telemetría:** Docker Compose desactiva la telemetría de Lightpanda.

## Limitaciones

- Los tags y los árboles se guardan en memoria, así que `tree_id` deja de funcionar al reiniciar la API.
- Una página con varias URL para el mismo contenido, como `/` y `/index.html`, aparece más de una vez.
- La API espera hasta que dejan de aparecer enlaces nuevos, con un máximo de 3 segundos. Un enlace que tarde más en crearse puede no aparecer.
- Lightpanda no es compatible con todo lo que soporta Chrome, por lo que algunas páginas pueden no cargar igual.

## Configuración

Las variables están en [.env.example](.env.example). Para desarrollo local, cópialo como `.env`. Para Docker Compose, agrégalas en `environment`.

## Desarrollo

```bash
python -m venv .venv
```
```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt
```
```bash
.venv/Scripts/python -m pytest
```

### Prueba de punta a punta

Levanta Lightpanda real y un sitio de prueba con dos dominios, para comprobar entre otras cosas que el token no sale del sitio recorrido. Usa `ALLOW_PRIVATE_NETWORKS=true`, así que no la uses en producción.

```bash
docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --build
```

En PowerShell:

```powershell
$env:E2E_API_URL = "http://127.0.0.1:8000"; .venv/Scripts/python -m pytest tests/e2e
```

Al terminar:

```bash
docker compose -f docker-compose.yml -f docker-compose.e2e.yml down
```

## Estructura

```text
app/
├── main.py                     # arranque de la API
├── config.py                   # configuración
├── api/routes.py               # endpoints
├── schemas/link_tree.py        # formato de entrada y salida
└── services/
    ├── lightpanda_client.py    # conexión con Lightpanda por CDP
    ├── link_tree.py            # recorrido y armado del árbol
    ├── tags.py                 # generación y autocompletado de tags
    └── url_policy.py           # reglas de URL y bloqueo de redes internas
tests/                          # tests unitarios
tests/e2e/                      # prueba con Lightpanda real
```
