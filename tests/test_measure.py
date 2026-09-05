import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import measure

def _line(role, *uses):
    return json.dumps({"type": role, "message": {"role": role, "content": [
        {"type": "tool_use", "name": n, "input": i} for n, i in uses]}})

def test_counts_searches_map_calls_and_orientation(tmp_path):
    p = tmp_path / "s1.jsonl"
    p.write_text("\n".join([
        _line("assistant", ("Grep", {"pattern": "x"})),
        _line("assistant", ("Bash", {"command": "cd /r && grep -rn foo ."})),
        _line("assistant", ("mcp__plugin_where-are-we_where-are-we__ask", {"words": "foo"})),
        _line("assistant", ("Read", {"file_path": "/r/a.py"})),
        _line("assistant", ("Edit", {"file_path": "/r/a.py"})),
        _line("user", ),
        _line("assistant", ("Bash", {"command": "pytest -q"})),
    ]))
    s = measure.summarise([str(p)])[0]
    assert s["turns"] == 6
    assert s["searches"] == 2
    assert s["map_calls"] == 1
    assert s["reads"] == 1
    assert s["first_map_call_turn"] == 3
    assert s["orientation_turns"] == 4

def test_cli_prints_a_table_and_json(tmp_path, capsys):
    (tmp_path / "s.jsonl").write_text(_line("assistant", ("Glob", {"pattern": "*"})))
    assert measure.main(["--sessions", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "searches" in out and "s.jsonl" in out
    assert measure.main(["--sessions", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["searches"] == 1
