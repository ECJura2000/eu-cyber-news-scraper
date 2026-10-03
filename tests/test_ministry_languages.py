"""Czech and Slovak original-text topic matching; synthetic lexical cases."""
import pytest

from eu_cyber_news_scraper.models import Article
from eu_cyber_news_scraper.topic_profile import apply_profile, load_profile

CASES = [
    ("cs", "umělá inteligence", 0),
    ("sk", "umelá inteligencia", 0),
    ("cs", "sdílení dat", 1),
    ("sk", "zdieľanie údajov", 1),
    ("cs", "ochrana osobních údajů", 2),
    ("sk", "ochrana osobných údajov", 2),
    ("cs", "digitální identita", 3),
    ("sk", "digitálna identita", 3),
    ("cs", "autorské právo", 4),
    ("sk", "autorské právo", 4),
    ("cs", "digitální služby", 5),
    ("sk", "digitálne služby", 5),
    ("cs", "pluralita médií", 6),
    ("sk", "pluralita médií", 6),
    ("cs", "hospodářská soutěž", 7),
    ("sk", "hospodárska súťaž", 7),
    ("cs", "kybernetická bezpečnost", 8),
    ("sk", "kybernetická bezpečnosť", 8),
    ("cs", "kybernetická odolnost", 9),
    ("sk", "kybernetická odolnosť", 9),
    ("cs", "bezpečnost dodavatelského řetězce", 10),
    ("sk", "bezpečnosť dodávateľského reťazca", 10),
    ("cs", "certifikace kybernetické bezpečnosti", 11),
    ("sk", "certifikácia kybernetickej bezpečnosti", 11),
    ("cs", "kritická infrastruktura", 12),
    ("sk", "kritická infraštruktúra", 12),
    ("cs", "polovodiče", 13),
    ("sk", "polovodiče", 13),
    ("cs", "kvantové technologie", 14),
    ("sk", "kvantové technológie", 14),
]


@pytest.mark.parametrize("language,title,index", CASES)
def test_original_language_keyword_and_word_boundary(language, title, index):
    profile = load_profile()
    topic = profile.topics[index]["name"]
    article = Article(source_id="test", country="CZ", source_name="Test", institution_type="ministry",
                      language=language, title=title, url="https://government.example.eu/news")
    apply_profile(article, profile)
    assert topic in article.matched_topics
    assert title in article.matched_keywords
    article = Article(source_id="test", country="CZ", source_name="Test", institution_type="ministry",
                      language=language, title="prefix"+title+"suffix", url="https://government.example.eu/news")
    apply_profile(article, profile)
    assert topic not in article.matched_topics
    article = Article(source_id="test", country="CZ", source_name="Test", institution_type="ministry",
                      language="fr", title=title, url="https://government.example.eu/news")
    apply_profile(article, profile)
    assert topic not in article.matched_topics


def test_related_ministries_do_not_expand_default_topics():
    profile = load_profile()
    assert len(profile.names) == 15
    for language in ("cs", "sk"):
        assert all(any(isinstance(term, dict) and term.get("language") == language
                       for term in topic.get("synonyms", [])) for topic in profile.topics)
