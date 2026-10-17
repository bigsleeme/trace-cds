from tracecds.pipeline import TraceCDS
from tracecds.trust import classify
from tracecds.web import WebSearcher, extract_text


def test_trust_tiers():
    assert classify("https://www.fda.gov/news-events/press") == "approved"
    assert classify("https://pubmed.ncbi.nlm.nih.gov/123/") == "approved"
    assert classify("https://www.mayoclinic.org/x") == "reputable"
    assert classify("https://med.stanford.edu/x") == "reputable"
    assert classify("https://www.example-news.com/story") == "unverified"
    assert classify("https://notfda.gov.evil.com/") == "unverified"


def test_extract_text_skips_navigation():
    html = ("<html><head><title>Valve news</title><script>var x=1</script></head><body>"
            "<nav><p>Home About Contact Subscribe to our newsletter today</p></nav>"
            "<p>The FDA approved a pediatric heart valve that can be expanded as the child grows.</p>"
            "</body></html>")
    title, text = extract_text(html)
    assert title == "Valve news"
    assert "pediatric heart valve" in text and "newsletter" not in text


class FakeWeb(WebSearcher):
    PAGES = {
        "https://www.fda.gov/valve": ("FDA approves pediatric valve",
                                      "The FDA approved the first pediatric heart valve designed to grow with "
                                      "children. The valve can be expanded in a later procedure as the child grows."),
        "https://www.somenews.com/valve": ("Valve story",
                                           "A new heart valve for children can be expanded as the child grows, "
                                           "potentially reducing the number of open-heart surgeries."),
    }

    def search(self, query, limit=12):
        return [{"url": "https://www.somenews.com/valve", "title": "Valve story", "content": ""},
                {"url": "https://www.fda.gov/valve", "title": "FDA", "content": ""}]

    def fetch(self, url):
        return self.PAGES[url]


def test_web_answer_ranks_and_flags_sources(passages):
    system = TraceCDS(passages, web=FakeWeb())
    ans = system.ask("FDA approval of a heart valve designed to grow with children", mode="auto")
    assert ans.status == "answered"
    trusts = {c.passage.publisher: c.passage.trust for c in ans.citations}
    assert trusts.get("fda.gov") == "approved"
    if "somenews.com" in trusts:
        assert any("NOT approved" in w for w in ans.warnings)
        assert not next(c for c in ans.criteria if c.criterion == 2).passed
    assert any("web was searched" in n for n in ans.limitations)


def test_web_answer_only_approved_has_no_warning(passages):
    class OnlyFDA(FakeWeb):
        def search(self, query, limit=12):
            return [{"url": "https://www.fda.gov/valve", "title": "FDA", "content": ""}]

    ans = TraceCDS(passages, web=OnlyFDA()).ask("heart valve that grows with children", mode="web")
    assert ans.status == "answered" and not ans.warnings
    assert all(c.passage.trust == "approved" for c in ans.citations)


def test_web_still_blocks_time_critical(passages):
    ans = TraceCDS(passages, web=FakeWeb()).ask("My patient is having anaphylaxis right now", mode="web")
    assert ans.status == "blocked"
