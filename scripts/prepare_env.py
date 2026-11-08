"""Create `.env` from `.env.example` on first run and report configuration problems.

* Never overwrites an existing `.env` (only fills a placeholder SECRET_KEY).
* Prints `EXECUTION_PROVIDER=<value>` as the last line for the startup scripts.
Standard library only.
"""
from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV, EXAMPLE = ROOT / ".env", ROOT / ".env.example"
PLACEHOLDER = "change-me-to-a-long-random-string"


def main() -> int:
    if not EXAMPLE.exists():
        print("ERROR: .env.example is missing — the repository looks incomplete.", file=sys.stderr)
        return 1
    if not ENV.exists():
        ENV.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        print("Created .env from .env.example")
    text = ENV.read_text(encoding="utf-8")
    if PLACEHOLDER in text:
        text = text.replace(PLACEHOLDER, secrets.token_urlsafe(48))
        ENV.write_text(text, encoding="utf-8")
        print("Generated a random SECRET_KEY in .env")
    values = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*([^#]*)", line)
        if m:
            values[m.group(1)] = m.group(2).strip()
    if values.get("AI_PROVIDER", "none") not in ("", "none") and not values.get("AI_API_KEY"):
        print("WARNING: AI_PROVIDER is set but AI_API_KEY is empty — AI features will be unavailable.")
    if values.get("GITHUB_CLIENT_ID") and not values.get("GITHUB_CLIENT_SECRET"):
        print("WARNING: GITHUB_CLIENT_ID is set without GITHUB_CLIENT_SECRET — GitHub OAuth will be disabled.")
    provider = values.get("EXECUTION_PROVIDER") or "disabled"
    if provider not in ("disabled", "docker", "local_trusted"):
        print(f"ERROR: EXECUTION_PROVIDER={provider} is not valid (disabled | docker | local_trusted).", file=sys.stderr)
        return 1
    print(f"EXECUTION_PROVIDER={provider}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
