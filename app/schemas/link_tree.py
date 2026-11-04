from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, field_validator

NodeStatus = Literal["ok", "error", "not_visited", "external_redirect"]


class LinkTreeRequest(BaseModel):
    url: HttpUrl
    bearer_token: SecretStr | None = None
    max_depth: int = Field(default=3, ge=1, le=3)

    @field_validator("bearer_token")
    @classmethod
    def clean_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        token = value.get_secret_value().strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if any(ord(char) < 33 or ord(char) == 127 for char in token):
            raise ValueError("el token contiene caracteres no validos")
        return SecretStr(token) if token else None


class LinkNode(BaseModel):
    url: str
    level: int
    title: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: NodeStatus = "not_visited"
    http_status: int | None = None
    error: str | None = None
    children: list["LinkNode"] = Field(default_factory=list)


class TagCount(BaseModel):
    tag: str
    count: int


class CrawlStats(BaseModel):
    total_links: int
    pages_visited: int
    pages_failed: int
    external_links_skipped: int
    truncated: bool
    duration_ms: int


class LinkTreeResponse(BaseModel):
    tree_id: str
    tree: LinkNode
    tags: list[TagCount]
    stats: CrawlStats


class TagSuggestions(BaseModel):
    tree_id: str
    query: str
    suggestions: list[TagCount]
