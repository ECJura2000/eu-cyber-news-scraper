import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_public_json_schemas_are_valid():
    for path in Path("schemas").glob("*.schema.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))
