from pathlib import Path

from app.analysis.repository import analyse_structure, scan_repository
from app.analysis.static_js import analyse_js_file, strip_comments_and_strings
from app.analysis.static_python import analyse_python_file
from app.core.config import REPO_ROOT
from app.generators import js_tests, python_tests

DEMO = REPO_ROOT / "demo-project"


def test_structure_detection_on_demo():
    scan = scan_repository(DEMO, 512 * 1024)
    s = analyse_structure(DEMO, scan)
    assert s["supported_languages"] == ["Python", "JavaScript"]
    assert "pytest" in s["test_frameworks"] and "Vitest" in s["test_frameworks"]
    assert set(s["test_files"]) == {"tests/test_pricing.py", "tests/test_stock.py", "web/cart.test.js"}
    assert "package.json" in s["config_files"] and "requirements.txt" in s["config_files"]
    assert s["test_commands"][0] == "pytest"


def test_python_findings_have_real_evidence():
    findings, meta = analyse_python_file(DEMO, "inventory/stock.py")
    by_rule = {f.rule_id: f for f in findings}
    assert {"PY001", "PY002", "PY003"} <= set(by_rule)
    lines = (DEMO / "inventory/stock.py").read_text().splitlines()
    for f in findings:
        assert f.line is not None and lines[f.line - 1].rstrip() == f.evidence
    assert by_rule["PY002"].certainty == "definite"


def test_division_by_len_is_potential_not_confirmed():
    findings, _ = analyse_python_file(DEMO, "inventory/pricing.py")
    f = next(f for f in findings if f.rule_id == "PY012")
    assert f.certainty == "potential" and "sum(prices) / len(prices)" in f.evidence


def test_syntax_error_reported(tmp_path):
    (tmp_path / "bad.py").write_text("def broken(:\n    pass\n")
    findings, meta = analyse_python_file(tmp_path, "bad.py")
    assert findings[0].rule_id == "PY-SYNTAX" and findings[0].line == 1 and meta["syntax_error"]


def test_js_rules_ignore_strings_and_comments(tmp_path):
    (tmp_path / "a.js").write_text("// eval(x) in a comment\nconst s = 'a == b';\nif (x == 1) {}\n")
    findings, _ = analyse_js_file(tmp_path, "a.js")
    assert [f.rule_id for f in findings] == ["JS001"] and findings[0].line == 3
    assert strip_comments_and_strings("a/*x\ny*/b").count("\n") == 1


def test_js_demo_findings():
    findings, meta = analyse_js_file(DEMO, "web/cart.js")
    rules = {f.rule_id for f in findings}
    assert {"JS001", "JS004", "JS005", "JS006"} <= rules
    assert [s["name"] for s in meta["symbols"]] == ["cartTotal", "formatCurrency", "parseQuantity"]


def test_python_generator_grounded_strategies():
    src = (DEMO / "inventory/pricing.py").read_text()
    props = python_tests.generate_for_file("inventory/pricing.py", src)
    strategies = {p.strategy for p in props}
    assert {"import", "doctest", "guard", "edge"} <= strategies
    doc = [p for p in props if p.strategy == "doctest" and "apply_discount" in p.name]
    assert "assert apply_discount(100.0, 25) == 75.0" in doc[0].code
    guard = next(p for p in props if p.name.startswith("test_apply_discount_raises_pricingerror"))
    assert "from inventory.pricing import apply_discount, PricingError" in guard.code
    edge = next(p for p in props if p.name == "test_average_price_handles_empty_list_prices")
    assert "average_price(prices=[])" in edge.code and "Heuristic" in edge.rationale
    for p in props:
        v = python_tests.validate_python_test(p.code)
        assert v["syntax_ok"] and v["has_tests"], p.name


def test_js_generator():
    src = (DEMO / "web/cart.js").read_text()
    props = js_tests.generate_for_file("web/cart.js", src)
    names = [p.name for p in props]
    assert "exports functions from web/cart.js" in names
    assert any("documented example" in n for n in names)
    guard = next(p for p in props if p.strategy == "guard")
    assert "toThrow(RangeError)" in guard.code and "formatCurrency(-1" in guard.code
    assert all(js_tests.validate_js_test(p.code)["syntax_ok"] for p in props)


def test_module_name():
    assert python_tests.module_name("src/pkg/mod.py") == "pkg.mod"
    assert python_tests.module_name("pkg/__init__.py") == "pkg"
    assert python_tests.module_name("my-dir/mod.py") is None


def test_validator_flags_forbidden_and_syntax():
    assert python_tests.validate_python_test("def test_x(:\n")["syntax_ok"] is False
    assert python_tests.validate_python_test("def test_x():\n    eval('1')\n")["forbidden_calls"] == ["eval"]


def test_demo_project_files_exist():
    assert Path(DEMO / "README.md").read_text().startswith("# TestPilot Demo Project")
