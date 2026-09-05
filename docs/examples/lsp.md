# `--lsp`: an editor's own go to definition and workspace symbols

`where-are-we --lsp` speaks the Language Server Protocol on stdin and
stdout: `Content-Length` framed JSON-RPC, the same wire format any LSP
client already knows. It answers two methods from the map, not from a real
compiler or parser for the language in front of it:

- `textDocument/definition`: the identifier under the cursor, looked up in
  the map's own index of what was declared where.
- `workspace/symbol`: every declared name containing the query, case
  insensitive.

Both are instant because the map was already built; nothing is parsed or
indexed again on the request.

Start it once, pointed at a repository and a map:

```
where-are-we --lsp --out /runs/APF-1934 --repo .
```

## VS Code

VS Code has no built in generic client, but any of the small "attach to a
language server" extensions (for example `mattn/vscode-lspclient` or a
custom client extension you already run) read the same `settings.json`
shape:

```json
{
  "genericLanguageServer.servers": [
    {
      "languageId": "python",
      "command": "where-are-we",
      "args": ["--lsp", "--out", "/runs/APF-1934", "--repo", "${workspaceFolder}"]
    }
  ]
}
```

## Neovim

`vim.lsp.start` takes a command and starts it over stdio directly, no
plugin needed beyond Neovim's built in client:

```lua
vim.lsp.start({
  name = "where-are-we",
  cmd = { "where-are-we", "--lsp", "--out", "/runs/APF-1934", "--repo", vim.fn.getcwd() },
  root_dir = vim.fn.getcwd(),
})
```

Run it from an `autocmd FileType` or a `ftplugin` file for the languages the
repository is written in, the same way any other language server is
attached.
