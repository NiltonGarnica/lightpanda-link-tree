import re
import unicodedata
from collections import Counter, OrderedDict
from urllib.parse import unquote, urlsplit

from app.schemas.link_tree import TagCount

MAX_TAGS_PER_LINK = 8
MIN_TAG_LENGTH = 3
MAX_TAG_LENGTH = 30

STOPWORDS = frozenset(
    """
    and are but for from has have how into not our that the this was were what when
    where which who why will with you your
    aqui con como cual cuando del desde donde esta este esto las los mas muy nos
    para pero por que sin sobre son sus todo todos una uno unos unas
    htm html php asp aspx jsp www index
    """.split()
)


def normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _tokens(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", normalize_text(text))
    return [
        token
        for token in tokens
        if MIN_TAG_LENGTH <= len(token) <= MAX_TAG_LENGTH
        and token not in STOPWORDS
        and sum(c.isdigit() for c in token) * 2 < len(token)
    ]


def tags_for_link(url: str, title: str | None) -> list[str]:
    """Primero las palabras de la ruta de la URL y luego las del titulo."""
    path = unquote(urlsplit(url).path)
    candidates = _tokens(path) + _tokens(title or "")
    return list(dict.fromkeys(candidates))[:MAX_TAGS_PER_LINK]


def sorted_tags(counts: Counter[str]) -> list[TagCount]:
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [TagCount(tag=tag, count=count) for tag, count in ordered]


class TagStore:
    """Tags de los ultimos arboles, en memoria y separados por tree_id."""

    def __init__(self, max_trees: int = 100) -> None:
        self._max_trees = max_trees
        self._trees: OrderedDict[str, Counter[str]] = OrderedDict()

    def save(self, tree_id: str, counts: Counter[str]) -> None:
        self._trees[tree_id] = counts
        self._trees.move_to_end(tree_id)
        while len(self._trees) > self._max_trees:
            self._trees.popitem(last=False)

    def suggest(self, tree_id: str, query: str, limit: int = 10) -> list[TagCount] | None:
        counts = self._trees.get(tree_id)
        if counts is None:
            return None
        self._trees.move_to_end(tree_id)
        prefix = normalize_text(query.strip())
        matches = Counter({t: c for t, c in counts.items() if t.startswith(prefix)})
        return sorted_tags(matches)[:limit]
