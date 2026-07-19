import hashlib
import ssl
from pathlib import Path

from eu_cyber_news_scraper.config import load_sources


def test_default_sources_cover_all_target_jurisdictions():
    sources = load_sources()
    assert len(sources) >= 33
    assert {source.country for source in sources} == {"EU", "FR", "DE", "IE"}
    assert any(source.id == "fr_anssi" and source.feed_urls for source in sources)
    assert any(source.id == "ie_ncsc" and source.critical for source in sources)
    assert any(source.id == "fr_viginum" for source in sources)
    assert any(source.id == "de_bfdi" for source in sources)
    assert any(source.id == "ie_cnam" for source in sources)


def test_source_ids_are_unique():
    sources = load_sources()
    assert len({source.id for source in sources}) == len(sources)


def test_tls_intermediate_bundles_are_limited_to_affected_sources():
    bundles = {source.id: source.tls_intermediate_bundle for source in load_sources() if source.tls_intermediate_bundle}
    assert bundles == {
        "ie_dpc": "sectigo-dv-r36.pem",
        "fr_cea_list": "geant-tls-rsa-1.pem",
    }
    expected_fingerprints = {
        "sectigo-dv-r36.pem": "8c54c334b66ba4e426772af4a3f9136c19a1aec729fdb28c535c07a5a4ef22e0",
        "geant-tls-rsa-1.pem": "5b678dc44095a52895b63b31f27227f4b36c3e347491bf2bfa691837a5fb8c79",
    }
    certificate_dir = Path("src/eu_cyber_news_scraper/certificates")
    for name, expected in expected_fingerprints.items():
        der = ssl.PEM_cert_to_DER_cert((certificate_dir / name).read_text(encoding="ascii"))
        assert hashlib.sha256(der).hexdigest() == expected
