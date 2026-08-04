import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_public_json_schemas_are_valid():
    for path in Path("schemas").glob("*.schema.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_packaged_runtime_schemas_match_public_schemas():
    packaged = Path("src/eu_cyber_news_scraper/schemas")
    for name in ("article-v6.schema.json", "run-v6.schema.json", "health-v2.schema.json", "translations-v3.schema.json"):
        assert (packaged / name).read_bytes() == (Path("schemas") / name).read_bytes()
