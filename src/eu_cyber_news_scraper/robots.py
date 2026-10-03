"""Robots rules with merged groups, longest-path wins, and UTF-8 matching."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

PRODUCT_TOKEN = "eu-cyber-news-scraper"
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _normalise(value: str) -> str:
    encoded = quote(value, safe="/%*?$&=:+,;@!()[]-._~")

    def decode(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else "%" + match.group(1).upper()

    return re.sub(r"%([0-9a-fA-F]{2})", decode, encoded)


@dataclass(frozen=True)
class RobotsPolicy:
    rules: tuple[tuple[bool, str], ...] = ()
    crawl_delay: float = 0.0

    @classmethod
    def parse(cls, text: str, token: str = PRODUCT_TOKEN) -> RobotsPolicy:
        groups: list[tuple[list[str], list[tuple[bool, str]], float]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        delay = 0.0
        has_records = False
        for line in text.lstrip("\ufeff").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.casefold()
            if key == "user-agent":
                if has_records:
                    groups.append((agents, rules, delay))
                    agents, rules, delay, has_records = [], [], 0.0, False
                agents.append(value.casefold())
            elif agents and key in {"allow", "disallow", "crawl-delay"}:
                has_records = True
                if key == "crawl-delay":
                    try:
                        parsed = float(value)
                        if 0 <= parsed < float("inf"):
                            delay = max(delay, parsed)
                    except ValueError:
                        pass
                elif value.startswith("/"):
                    rules.append((key == "allow", _normalise(value)))
        if agents:
            groups.append((agents, rules, delay))
        specific = [group for group in groups if token.casefold() in group[0]]
        applicable = specific or [group for group in groups if "*" in group[0]]
        return cls(tuple(rule for group in applicable for rule in group[1]),
                   max((group[2] for group in applicable), default=0.0))

    def allows(self, url: str) -> bool:
        parsed = urlsplit(url)
        if parsed.path == "/robots.txt":
            return True
        target = _normalise((parsed.path or "/") + ("?" + parsed.query if parsed.query else ""))
        matches: list[tuple[int, bool]] = []
        for allow, pattern in self.rules:
            anchored = pattern.endswith("$")
            body = pattern[:-1] if anchored else pattern
            expression = "^" + ".*".join(re.escape(part) for part in body.split("*"))
            if anchored:
                expression += "$"
            if re.search(expression, target):
                # Percent escapes represent one octet, not three characters.
                specificity = len(re.sub(r"%[0-9A-F]{2}", "x", body.replace("*", "")))
                matches.append((specificity, allow))
        return max(matches)[1] if matches else True
