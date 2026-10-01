from eu_cyber_news_scraper.config import load_sources
from eu_cyber_news_scraper.parsers import parse_listing
from eu_cyber_news_scraper.robots import RobotsPolicy


def test_bnetza_uses_verified_https_home_and_permitted_press_listing():
    source = next(item for item in load_sources() if item.id == "de_bnetza")
    policy = RobotsPolicy.parse("User-agent: *\nDisallow: /SiteGlobals\n")
    assert source.homepage == "https://www.bundesnetzagentur.de/DE/Home/home_node.html"
    assert policy.allows(source.homepage) and policy.allows(source.listing_url)
    assert not policy.allows("https://www.bundesnetzagentur.de/SiteGlobals/rss.xml")


def test_bnetza_base_href_preserves_root_relative_news_and_publication_dates():
    source = next(item for item in load_sources() if item.id == "de_bnetza")
    # Minimal synthetic public-layout contract; no live dependency.
    html = """<html><head><base href="/"></head><body><table class="textualData"><tbody>
    <tr><td>25.09.2026</td><td><a class="titleLink"
    href="SharedDocs/Pressemitteilungen/DE/2026/20260925_DSC.html">DSA enforcement</a></td></tr>
    </tbody></table></body></html>"""
    articles = parse_listing(html, source, source.listing_url)
    assert len(articles) == 1
    article = articles[0]
    assert article.url == "https://www.bundesnetzagentur.de/SharedDocs/Pressemitteilungen/DE/2026/20260925_DSC.html"
    assert article.published_date_local == "2026-09-25"
    assert article.date_confidence == "high" and not article.date_conflict
