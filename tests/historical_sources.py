"""Load archived settings only for historical parser fixture regressions."""
from pathlib import Path
from unittest.mock import patch

from eu_cyber_news_scraper import config
from eu_cyber_news_scraper.organisation_registry import load_organisation_registry

ROOT = Path(__file__).resolve().parents[1]


def load_sources_and_registry():
    registry = load_organisation_registry(external_dir=ROOT / "source_exclusions/modules")
    with patch.object(config, "load_organisation_registry", return_value=registry):
        return config.load_sources_and_registry()


def load_sources():
    return load_sources_and_registry()[0]
