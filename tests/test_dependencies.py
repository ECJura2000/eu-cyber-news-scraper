import re
import tomllib
from pathlib import Path


def _name(value: str) -> str:
    return re.split(r"[<>=!~\[]", value, maxsplit=1)[0].strip().casefold().replace("_", "-")


def test_uv_lock_contains_every_runtime_dependency_and_no_generated_requirements():
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    locked = {_name(row["name"]) for row in lock["package"]}
    assert {_name(value) for value in project["dependencies"]} <= locked
    assert not (root / "requirements.txt").exists()
    assert not (root / "requirements-dev.txt").exists()
