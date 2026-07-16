import re
import tomllib
from pathlib import Path


def _name(value: str) -> str:
    return re.split(r"[<>=!~\[]", value, maxsplit=1)[0].strip().casefold().replace("_", "-")


def test_generated_requirements_contains_every_runtime_dependency():
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirements = {
        _name(line)
        for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {_name(value) for value in project["dependencies"]} <= requirements
    assert (root / "uv.lock").exists()
