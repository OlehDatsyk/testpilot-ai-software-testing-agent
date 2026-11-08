"""AI-assisted test generation. Optional — used only when an AI provider is configured.

Context sent to the model is limited to: the source file under test (truncated),
the list of existing test file paths, and the module/import path. Outputs are
validated (schema + syntax) before they are stored as *proposals*; nothing is
executed without human approval.
"""
from __future__ import annotations

from app.ai.provider import AIProvider, AIUnavailable
from app.ai.schemas import AITestSuggestions
from app.generators.js_tests import validate_js_test
from app.generators.python_tests import Proposal, module_name, validate_python_test

MAX_SOURCE_CHARS = 14000

SYSTEM = (
    "You are a senior QA engineer writing automated tests. Use ONLY behaviour that is visible in the supplied "
    "source code or its docstrings/comments. Do not invent APIs, files or modules that are not shown. If the "
    "correct expected value cannot be determined from the source, prefer tests of documented error handling. "
    "Each test must be self-contained (its own imports) and contain exactly one test function."
)


def generate_with_ai(provider: AIProvider, rel: str, source: str, language: str, existing_tests: list[str],
                     focus: str | None = None) -> list[Proposal]:
    if not provider.available:
        raise AIUnavailable("No AI provider configured")
    truncated = source[:MAX_SOURCE_CHARS]
    if language == "Python":
        mod = module_name(rel)
        if not mod:
            return []
        framework_note = f"Framework: pytest. Import the code under test with `from {mod} import ...`."
    else:
        framework_note = (f"Framework: Vitest with globals enabled (describe/it/expect are global; do not import "
                          f"vitest). The test file is at testpilot_generated/<name>.test.ts; import the module with "
                          f"`from '../{rel}'`.")
    prompt = (
        f"File under test: {rel}\nLanguage: {language}\n{framework_note}\n"
        f"Existing test files: {', '.join(existing_tests[:40]) or 'none'}\n"
        + (f"Focus on: {focus}\n" if focus else "")
        + ("NOTE: the source was truncated.\n" if len(source) > MAX_SOURCE_CHARS else "")
        + f"\n<source>\n{truncated}\n</source>\n\nPropose up to 6 high-value tests (edge cases, error handling, "
          "boundary values) that are not already obviously covered."
    )
    result = provider.structured(system=SYSTEM, prompt=prompt, schema=AITestSuggestions, max_tokens=12000)
    proposals = []
    for t in result.tests:
        validation = validate_python_test(t.code) if language == "Python" else validate_js_test(t.code)
        if not validation.get("syntax_ok") or not validation.get("has_tests") or validation.get("forbidden_calls"):
            continue
        proposals.append(Proposal(
            name=t.name[:200], description=t.description, target=t.target[:300], target_file=rel,
            category=t.category, expected_behaviour=t.expected_behaviour, code=t.code,
            rationale="AI suggestion — " + t.rationale, strategy="ai", source_files=[rel]))
    return proposals
