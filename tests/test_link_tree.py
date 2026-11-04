import asyncio

from app.config import Settings
from app.services.lightpanda_client import PageLink, PageResult
from app.services.link_tree import build_link_tree
from app.services.url_policy import HostGuard

ROOT = "https://x.com/"


class FakeVisitor:
    def __init__(self, pages):
        self.pages = pages
        self.visited = []
        self.tokens = []

    async def visit(self, url, *, token, root_url, guard):
        self.visited.append(url)
        self.tokens.append(token)
        return self.pages.get(url, PageResult(final_url=url))


def page(url, *links, title=None):
    return PageResult(
        final_url=url,
        title=title,
        http_status=200,
        links=[PageLink(link) for link in links],
    )


def build(visitor, max_depth=3, **settings):
    return asyncio.run(
        build_link_tree(
            ROOT, "secreto", max_depth, visitor, HostGuard(), Settings(_env_file=None, **settings)
        )
    )[0]


def chain(depth):
    urls = [ROOT] + [f"https://x.com/n{i}" for i in range(1, depth + 1)]
    return {u: page(u, urls[i + 1]) for i, u in enumerate(urls[:-1])}


def test_tree_stops_at_third_level_and_does_not_open_it():
    visitor = FakeVisitor(chain(6))
    result = build(visitor)
    level3 = result.tree.children[0].children[0].children[0]
    assert level3.url == "https://x.com/n3" and level3.level == 3
    assert level3.status == "not_visited" and level3.children == []
    assert visitor.visited == [ROOT, "https://x.com/n1", "https://x.com/n2"]
    assert result.stats.total_links == 4


def test_max_depth_can_be_lower():
    assert build(FakeVisitor(chain(6)), max_depth=1).stats.total_links == 2


def test_cycles_and_duplicates_appear_once():
    pages = {
        ROOT: page(ROOT, "https://x.com/a", "https://x.com/a/", "https://x.com/a#top", ROOT),
        "https://x.com/a": page("https://x.com/a", ROOT, "https://x.com/b"),
    }
    result = build(FakeVisitor(pages))
    assert [c.url for c in result.tree.children] == ["https://x.com/a"]
    assert [c.url for c in result.tree.children[0].children] == ["https://x.com/b"]


def test_external_links_are_counted_not_followed():
    pages = {ROOT: page(ROOT, "https://otro.com/", "https://api.x.com/", "mailto:a@x.com")}
    result = build(FakeVisitor(pages))
    assert result.tree.children == []
    assert result.stats.external_links_skipped == 2


def test_http_error_marks_node_without_children():
    pages = {
        ROOT: PageResult(
            final_url=ROOT, http_status=401, links=[PageLink("https://x.com/a")]
        )
    }
    result = build(FakeVisitor(pages))
    assert result.tree.status == "error" and result.tree.error == "HTTP 401"
    assert result.tree.children == [] and result.stats.pages_failed == 1


def test_failed_child_does_not_stop_the_crawl():
    pages = {
        ROOT: page(ROOT, "https://x.com/mal", "https://x.com/bien"),
        "https://x.com/mal": PageResult(error="net::ERR_TIMED_OUT"),
        "https://x.com/bien": page("https://x.com/bien", "https://x.com/hijo"),
    }
    result = build(FakeVisitor(pages))
    bad, good = result.tree.children
    assert bad.status == "error" and bad.error == "net::ERR_TIMED_OUT"
    assert good.status == "ok" and good.children[0].url == "https://x.com/hijo"


def test_redirect_to_other_site_is_not_followed():
    pages = {
        ROOT: page(ROOT, "https://x.com/salir"),
        "https://x.com/salir": page("https://otro.com/", "https://otro.com/a"),
    }
    result = build(FakeVisitor(pages))
    node = result.tree.children[0]
    assert node.status == "external_redirect" and node.children == []


def test_max_links_truncates():
    links = [f"https://x.com/{i}" for i in range(10)]
    result = build(FakeVisitor({ROOT: page(ROOT, *links)}), max_links=4)
    assert result.stats.total_links == 4 and result.stats.truncated is True


def test_crawl_timeout_returns_partial_tree():
    class Slow(FakeVisitor):
        async def visit(self, url, **kwargs):
            if url != ROOT:
                await asyncio.sleep(5)
            return await super().visit(url, **kwargs)

    visitor = Slow({ROOT: page(ROOT, "https://x.com/lenta")})
    result = build(visitor, crawl_timeout_seconds=0.2)
    assert result.stats.truncated is True
    assert result.tree.status == "ok"
    assert result.tree.children[0].status == "not_visited"


def test_title_from_page_and_tags_are_filled():
    pages = {ROOT: page(ROOT, "https://x.com/contacto", title="Tienda Online")}
    result = build(FakeVisitor(pages))
    assert result.tree.title == "Tienda Online"
    assert result.tree.tags == ["tienda", "online"]
    assert result.tree.children[0].tags == ["contacto"]
    assert {t.tag for t in result.tags} == {"tienda", "online", "contacto"}


def test_token_is_passed_to_visitor():
    visitor = FakeVisitor({})
    build(visitor)
    assert visitor.tokens == ["secreto"]
