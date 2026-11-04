import asyncio
import time
import uuid
from collections import Counter
from collections.abc import Iterator

from app.config import Settings
from app.schemas.link_tree import CrawlStats, LinkNode, LinkTreeResponse
from app.services.lightpanda_client import PageResult, PageVisitor
from app.services.tags import sorted_tags, tags_for_link
from app.services.url_policy import HostGuard, dedupe_key, normalize_url, same_site


class _Crawl:
    def __init__(
        self,
        root_url: str,
        token: str | None,
        max_depth: int,
        visitor: PageVisitor,
        guard: HostGuard,
        settings: Settings,
    ) -> None:
        self.root = LinkNode(url=root_url, level=0)
        self._root_url = root_url
        self._token = token
        self._max_depth = max_depth
        self._visitor = visitor
        self._guard = guard
        self._max_links = settings.max_links
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)
        self._deadline = time.monotonic() + settings.crawl_timeout_seconds
        self._seen = {dedupe_key(root_url)}
        self.total_links = 1
        self.pages_visited = 0
        self.pages_failed = 0
        self.external_skipped = 0
        self.truncated = False

    async def run(self) -> None:
        # Los enlaces del ultimo nivel se listan pero no se abren.
        frontier = [self.root]
        for _ in range(self._max_depth):
            if not frontier:
                return
            if time.monotonic() >= self._deadline:
                self.truncated = True
                return
            frontier = await self._visit_level(frontier)

    async def _visit_level(self, nodes: list[LinkNode]) -> list[LinkNode]:
        tasks = [asyncio.create_task(self._visit(node.url)) for node in nodes]
        remaining = max(self._deadline - time.monotonic(), 0)
        _, pending = await asyncio.wait(tasks, timeout=remaining)
        for task in pending:
            task.cancel()
            self.truncated = True
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        for task in tasks:
            if not task.cancelled() and task.exception() is not None:
                raise task.exception()

        next_level: list[LinkNode] = []
        for node, task in zip(nodes, tasks):
            if not task.cancelled():
                next_level.extend(self._apply_result(node, task.result()))
        return next_level

    async def _visit(self, url: str) -> PageResult:
        async with self._semaphore:
            return await self._visitor.visit(
                url, token=self._token, root_url=self._root_url, guard=self._guard
            )

    def _apply_result(self, node: LinkNode, page: PageResult) -> list[LinkNode]:
        self.pages_visited += 1
        node.http_status = page.http_status
        if page.error:
            node.status, node.error = "error", page.error
            self.pages_failed += 1
            return []
        if page.http_status is not None and page.http_status >= 400:
            node.status, node.error = "error", f"HTTP {page.http_status}"
            self.pages_failed += 1
            return []
        final_url = normalize_url(page.final_url or node.url)
        if final_url is None or not same_site(final_url, self._root_url):
            node.status = "external_redirect"
            return []
        node.status = "ok"
        node.title = page.title or node.title
        self._seen.add(dedupe_key(final_url))
        return self._add_children(node, page)

    def _add_children(self, node: LinkNode, page: PageResult) -> list[LinkNode]:
        for link in page.links:
            url = normalize_url(link.url)
            if url is None:
                continue
            if not same_site(url, self._root_url):
                self.external_skipped += 1
                continue
            key = dedupe_key(url)
            if key in self._seen:
                continue
            if self.total_links >= self._max_links:
                self.truncated = True
                break
            self._seen.add(key)
            self.total_links += 1
            node.children.append(LinkNode(url=url, level=node.level + 1, title=link.text or None))
        return node.children


def _walk(node: LinkNode) -> Iterator[LinkNode]:
    yield node
    for child in node.children:
        yield from _walk(child)


async def build_link_tree(
    root_url: str,
    token: str | None,
    max_depth: int,
    visitor: PageVisitor,
    guard: HostGuard,
    settings: Settings,
) -> tuple[LinkTreeResponse, Counter[str]]:
    started = time.monotonic()
    crawl = _Crawl(root_url, token, max_depth, visitor, guard, settings)
    await crawl.run()

    counts: Counter[str] = Counter()
    for node in _walk(crawl.root):
        node.tags = tags_for_link(node.url, node.title)
        counts.update(node.tags)

    response = LinkTreeResponse(
        tree_id=uuid.uuid4().hex,
        tree=crawl.root,
        tags=sorted_tags(counts),
        stats=CrawlStats(
            total_links=crawl.total_links,
            pages_visited=crawl.pages_visited,
            pages_failed=crawl.pages_failed,
            external_links_skipped=crawl.external_skipped,
            truncated=crawl.truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
        ),
    )
    return response, counts
