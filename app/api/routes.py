from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.schemas.link_tree import LinkTreeRequest, LinkTreeResponse, TagSuggestions
from app.services.lightpanda_client import (
    LightpandaClient,
    LightpandaUnavailable,
    PageVisitor,
)
from app.services.link_tree import build_link_tree
from app.services.tags import TagStore
from app.services.url_policy import HostGuard, normalize_url

router = APIRouter()


def get_visitor(settings: Annotated[Settings, Depends(get_settings)]) -> PageVisitor:
    return LightpandaClient(settings.lightpanda_ws_url, settings.page_timeout_seconds)


@lru_cache
def _tag_store(max_trees: int) -> TagStore:
    return TagStore(max_trees)


def get_tag_store(settings: Annotated[Settings, Depends(get_settings)]) -> TagStore:
    return _tag_store(settings.tree_cache_size)


@router.post("/api/v1/link-tree", response_model=LinkTreeResponse, tags=["link-tree"])
async def create_link_tree(
    payload: LinkTreeRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    visitor: Annotated[PageVisitor, Depends(get_visitor)],
    tag_store: Annotated[TagStore, Depends(get_tag_store)],
) -> LinkTreeResponse:
    """Recorre la URL y devuelve su arbol de enlaces hasta `max_depth` niveles."""
    root_url = normalize_url(str(payload.url))
    if root_url is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La URL no se puede recorrer")

    guard = HostGuard(settings.allow_private_networks)
    if not await guard.allowed(root_url):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "La URL no se resuelve a una direccion publica",
        )

    token = payload.bearer_token.get_secret_value() if payload.bearer_token else None
    try:
        response, counts = await build_link_tree(
            root_url, token, payload.max_depth, visitor, guard, settings
        )
    except LightpandaUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    tag_store.save(response.tree_id, counts)
    return response


@router.get("/api/v1/tags", response_model=TagSuggestions, tags=["tags"])
async def suggest_tags(
    tree_id: str,
    tag_store: Annotated[TagStore, Depends(get_tag_store)],
    q: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> TagSuggestions:
    """Sugiere los tags de un arbol que empiezan por `q`, para autocompletar."""
    suggestions = tag_store.suggest(tree_id, q, limit)
    if suggestions is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Arbol no encontrado")
    return TagSuggestions(tree_id=tree_id, query=q, suggestions=suggestions)


@router.get("/health", tags=["health"])
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> JSONResponse:
    """Indica si la API y Lightpanda estan funcionando."""
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            response = await client.get(f"{settings.lightpanda_http_url}/json/version")
            response.raise_for_status()
            version = response.json().get("Lightpanda-Version")
    except (httpx.HTTPError, ValueError):
        return JSONResponse(
            {"status": "degraded", "lightpanda": {"status": "unavailable"}},
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return JSONResponse({"status": "ok", "lightpanda": {"status": "ok", "version": version}})
