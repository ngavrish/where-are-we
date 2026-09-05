import json, os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from where_are_we import mapper

def _frame(obj):
    b = json.dumps(obj).encode(); return b"Content-Length: %d\r\n\r\n%s" % (len(b), b)

def _unframe(data):
    out = []
    while data:
        head, _, rest = data.partition(b"\r\n\r\n")
        n = int(head.split(b":")[1]); out.append(json.loads(rest[:n])); data = rest[n:]
    return out

def test_definition_and_symbols(tmp_path):
    repo, out = tmp_path / "r", tmp_path / "o"; repo.mkdir(); out.mkdir()
    (repo / "billing.py").write_text("def charge(x):\n    return x\n")
    (repo / "api.py").write_text("from billing import charge\n\ndef pay():\n    return charge(1)\n")
    m = mapper.build(str(repo))
    (out / "framework_map.md").write_text(mapper.digest(m)); (out / "framework_map_brief.md").write_text(mapper.brief(m))
    (out / "framework_map.json").write_text(json.dumps(m))
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "textDocument/definition", "params": {
                "textDocument": {"uri": f"file://{repo}/api.py"}, "position": {"line": 3, "character": 13}}},
            {"jsonrpc": "2.0", "id": 3, "method": "workspace/symbol", "params": {"query": "cha"}},
            {"jsonrpc": "2.0", "id": 4, "method": "shutdown"}, {"jsonrpc": "2.0", "method": "exit"}]
    p = subprocess.run([sys.executable, "-m", "where_are_we.mapper", "--out", str(out), "--repo", str(repo), "--lsp"],
                       input=b"".join(_frame(m) for m in msgs), capture_output=True, timeout=30,
                       env={**os.environ, "PYTHONPATH": os.path.join(os.path.dirname(__file__), "..", "src")})
    replies = {r["id"]: r for r in _unframe(p.stdout) if "id" in r}
    assert replies[1]["result"]["capabilities"]["definitionProvider"] is True
    loc = replies[2]["result"][0]
    assert loc["uri"].endswith("/billing.py") and loc["range"]["start"]["line"] == 0
    assert [s["name"] for s in replies[3]["result"]] == ["charge"]
