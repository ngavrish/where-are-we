"""What the tool must not get wrong, on repositories built for the purpose.

Not a unit suite: the thing being tested is whether a real directory produces a
map that names what is in it, which is exactly what breaks when a regex drifts.
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from where_are_we import mapper  # noqa: E402


def _write(base, rel, body):
    path = os.path.join(base, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path


def test_behave_suite_is_recognised(tmp_path):
    repo = str(tmp_path)
    _write(repo, "steps/portal_steps.py",
           'from behave import step\n\n@step("the portal is open")\ndef f(c):\n    pass\n')
    _write(repo, "tests/ui.feature",
           "Feature: x\n  Scenario: opens\n    Given the portal is open\n")
    m = mapper.build(repo)
    assert m["counts"]["steps"] == 1
    assert m["counts"]["scenarios"] == 1
    assert any("opens" == sc["name"] for f in m["features"].values() for sc in f["scenarios"])


def test_scenarios_carry_line_numbers(tmp_path):
    repo = str(tmp_path)
    _write(repo, "a.feature", "Feature: f\n\n  Scenario: second line three\n    Given x\n")
    m = mapper.build(repo)
    (feat,) = m["features"].values()
    assert feat["scenarios"][0]["line"] == 3


def test_polyglot_runners(tmp_path):
    repo = str(tmp_path)
    _write(repo, "main_test.go", "func TestFoo(t *testing.T) {}\n")
    _write(repo, "spec/user_spec.rb", 'describe "User" do\n  it "signs in" do\n  end\nend\n')
    _write(repo, "steps.ts", 'Given("a logged in user", async function () {});\n')
    _write(repo, "T.cs", '[Fact]\npublic void ChecksTotals() {}\n')
    m = mapper.build(repo)
    assert set(m["other_suites"]) >= {"go", "rspec", "cucumber-js", "dotnet"}


def test_contracts_are_parsed_not_just_listed(tmp_path):
    repo = str(tmp_path)
    _write(repo, "openapi.yaml",
           "openapi: 3.0.0\npaths:\n  /users/{id}:\n    get:\n      summary: x\n")
    _write(repo, "migrations/V1__init.sql", "CREATE TABLE users (id int, email text);\n")
    m = mapper.build(repo)
    assert "GET /users/{id}" in m["contract_details"]["endpoints"]
    assert any(t.startswith("users(") for t in m["contract_details"]["migration_tables"])


def test_manifest_overrides_detection(tmp_path):
    repo = str(tmp_path)
    _write(repo, "steps/a.py", 'from behave import step\n@step("x")\ndef f(c):\n    pass\n')
    _write(repo, ".framework-map.json",
           json.dumps({"name": "stated-name", "layers": {"steps": "our own words"}}))
    os.environ["AGENT_REPO"] = repo
    m = mapper.build(repo)
    assert m["stated"]["name"] == "stated-name"
    assert m["layers"]["steps"] == "our own words"


def test_ignore_file_is_honoured(tmp_path):
    repo = str(tmp_path)
    _write(repo, "keep/a.py", "def visible():\n    pass\n")
    _write(repo, "vendor/b.py", "def hidden():\n    pass\n")
    _write(repo, ".wawe-ignore", "vendor\n")
    os.environ["AGENT_REPO"] = repo
    mapper._IGNORE_CACHE.clear()
    mapper._WALK_CACHE.clear()
    m = mapper.build(repo)
    assert any("keep/a.py" in k for k in m["exports"])
    assert not any("vendor" in k for k in m["exports"])


def test_cli_skips_an_unchanged_map(tmp_path):
    repo, out = str(tmp_path / "repo"), str(tmp_path / "out")
    os.makedirs(repo, exist_ok=True)
    _write(repo, "steps/a.py", 'from behave import step\n@step("x")\ndef f(c):\n    pass\n')
    cmd = [sys.executable, os.path.join(ROOT, "src", "where_are_we", "mapper.py"),
           "--repo", repo, "--out", out]
    first = subprocess.run(cmd, capture_output=True, text=True)
    second = subprocess.run(cmd, capture_output=True, text=True)
    assert "framework map:" in first.stdout
    assert "unchanged since it was built" in second.stdout


def test_brief_survives_a_section_of_the_wrong_shape():
    """A section is data, not a promise. An older map or a future shape must
    degrade to "not shown" rather than take the whole brief down — which is
    exactly what a name collision between two sections did."""
    m = mapper.build(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    m["schemas"] = ["not", "a", "dict"]
    m["languages"] = None
    assert "# Framework map" in mapper.brief(m)
