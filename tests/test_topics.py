import pytest

from eu_cyber_news_scraper.models import Article
from eu_cyber_news_scraper.topics import classify_article, is_relevant


def article(title, summary=""):
    return Article(
        source_id="test",
        country="EU",
        source_name="Test",
        institution_type="official",
        language="en",
        title=title,
        summary=summary,
        url="https://example.eu/item",
    )


def test_multilingual_legal_topics_are_classified():
    item = classify_article(article("NIS-2 und Cyberresilienz", "Lieferkettensicherheit und Schwachstellenmanagement"))
    assert "NIS2、關鍵基礎設施保護" in item.matched_topics
    assert "供應鏈安全" in item.matched_topics
    assert "產品資安、漏洞揭露義務、SBOM" in item.matched_topics
    assert is_relevant(item)


def test_cra_acronym_requires_cyber_context():
    unrelated = classify_article(article("CRA publishes its annual finance report"))
    related = classify_article(article("CRA compliance for secure software products"))
    assert "產品資安、漏洞揭露義務、SBOM" not in unrelated.matched_topics
    assert "產品資安、漏洞揭露義務、SBOM" in related.matched_topics


def test_csa_acronym_requires_security_context():
    unrelated = classify_article(article("CSA farming statistics released"))
    related = classify_article(article("CSA cybersecurity certification scheme consultation"))
    assert "資安產品認證" not in unrelated.matched_topics
    assert "資安產品認證" in related.matched_topics


def test_french_official_terms_are_classified():
    item = classify_article(
        article(
            "Transposition de la directive NIS 2",
            "Nouvelles mesures de gestion des risques en matière de cybersécurité et signalement d'incident.",
        )
    )
    assert "NIS2、關鍵基礎設施保護" in item.matched_topics


def test_german_official_terms_are_classified():
    item = classify_article(
        article(
            "Resilienz kritischer Einrichtungen",
            "Risikobewertung kritischer Einrichtungen und Sicherheit der Lieferkette.",
        )
    )
    assert "NIS2、關鍵基礎設施保護" in item.matched_topics
    assert "供應鏈安全" in item.matched_topics


def test_local_ai_acronyms_require_context():
    french = classify_article(article("Sécurité des modèles d'IA générative"))
    german = classify_article(article("Sicherheit generativer KI-Modelle"))
    unrelated = classify_article(article("Ki ist ein Ortsname"))
    topic = "AI法、模型評估、演算法問責、自動化決策、AI與著作權"
    assert topic in french.matched_topics
    assert topic in german.matched_topics
    assert topic not in unrelated.matched_topics


def test_vulnerability_advisories_match_in_all_source_languages():
    english = classify_article(article("Critical vulnerabilities in remote access software"))
    french = classify_article(article("Correction de plusieurs vulnérabilités critiques"))
    german = classify_article(article("Kritische Schwachstellen in Netzwerkprodukten"))
    for item in (english, french, german):
        assert "產品資安、漏洞揭露義務、SBOM" in item.matched_topics


def test_document_subtopics_cover_copyright_information_and_hybrid_security():
    copyright_item = classify_article(article("Text and data mining rules for AI training data"))
    information_item = classify_article(article("Foreign information manipulation threatens election integrity"))
    hybrid_item = classify_article(article("Physical and cyber security for critical entities"))
    assert "著作權" in copyright_item.matched_topics
    assert "媒體多元與資訊操縱" in information_item.matched_topics
    assert "關鍵基礎設施的實體與數位融合保護" in hybrid_item.matched_topics


@pytest.mark.parametrize(
    ("text", "topic"),
    (
        ("AI Act model evaluation", "AI法、模型評估、演算法問責、自動化決策、AI與著作權"),
        ("Cross-border data governance and open data reuse", "跨境資料流通、資料主權、資料開放與再利用"),
        ("GDPR personal data protection", "隱私框架（含個人資料保護）"),
        ("eIDAS European digital identity wallet", "數位身份"),
        ("Copyright rules for text and data mining", "著作權"),
        ("Digital Services Act content moderation", "平台責任、內容審查、推薦演算法"),
        ("Foreign information manipulation and media pluralism", "媒體多元與資訊操縱"),
        ("Digital Markets Act gatekeeper competition", "競爭規範面向（平台責任的市場結構面）"),
        ("NIS2 protection of critical infrastructure", "NIS2、關鍵基礎設施保護"),
        ("CRA vulnerability disclosure and SBOM", "產品資安、漏洞揭露義務、SBOM"),
        ("Cybersecurity supply chain security", "供應鏈安全"),
        ("European cybersecurity certification scheme", "資安產品認證"),
        ("Cyber-physical security and physical resilience", "關鍵基礎設施的實體與數位融合保護"),
        ("European semiconductor Chips Act", "半導體"),
        ("Post-quantum cryptography and quantum computers", "量子技術"),
    ),
)
def test_all_fifteen_observation_topics_have_independent_signals(text, topic):
    assert topic in classify_article(article(text)).matched_topics
