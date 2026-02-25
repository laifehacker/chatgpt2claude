# chatgpt2claude

Search your ChatGPT conversation history from Claude.

Import your ChatGPT data export and make all your old conversations searchable through Claude Desktop or Claude Code — using semantic search, keyword search, and full conversation retrieval.

Everything runs locally. No API keys needed. Your data never leaves your machine.

## Quick Start

### 1. Export your ChatGPT data

Go to [ChatGPT](https://chat.openai.com) → **Settings** → **Data Controls** → **Export Data** → **Confirm export**.

You'll receive an email with a download link. Download the ZIP file.

### 2. Install chatgpt2claude

```bash
pip install chatgpt2claude
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install chatgpt2claude
```

### 3. Import your data

```bash
chatgpt2claude import ~/Downloads/your-chatgpt-export.zip
```

You'll see a progress bar as your conversations are indexed:

```
Found 847 conversations in export.
Successfully parsed 842 conversations.
Importing conversations  [####################################]  842/842
Import complete!
  Imported: 842 conversations (12,456 messages)
  Chunks:   3,891 (indexed for semantic search)
  Range:    2023-01-15 → 2025-02-20
```

### 4. Connect to Claude

**Claude Code (recommended — easiest):**

```bash
claude mcp add chatgpt2claude -- chatgpt2claude serve
```

That's it. No config files to edit.

**Claude Desktop:**

> **WARNING: Back up your config file before editing!**
>
> Claude Desktop's `claude_desktop_config.json` is fragile. If you introduce **any** JSON syntax error (missing comma, trailing comma, unmatched bracket), Claude Desktop will silently **delete your entire config file** on next launch — including all your other MCP servers. This is not recoverable.
>
> **Before you edit, make a backup:**
> ```bash
> # macOS
> cp ~/Library/Application\ Support/Claude/claude_desktop_config.json ~/claude_config_backup.json
>
> # Windows (PowerShell)
> Copy-Item "$env:APPDATA\Claude\claude_desktop_config.json" "$HOME\claude_config_backup.json"
>
> # Linux
> cp ~/.config/Claude/claude_desktop_config.json ~/claude_config_backup.json
> ```

If you already have a config file with other MCP servers, **merge** the `chatgpt2claude` entry into your existing `mcpServers` object. Don't replace the whole file.

If this is your first MCP server, create the file with this content:

```json
{
  "mcpServers": {
    "chatgpt2claude": {
      "command": "chatgpt2claude",
      "args": ["serve"]
    }
  }
}
```

Validate your JSON before saving (paste it into [jsonlint.com](https://jsonlint.com) if unsure). Then **fully quit** Claude Desktop (not just close the window) and reopen it.

Config file locations:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

### 5. Done!

Ask Claude things like:
- "Search my ChatGPT history for conversations about Python decorators"
- "Find that conversation where I discussed database schema design"
- "Show me all conversations from last month"
- "What topics have I discussed most frequently?"

## CLI Commands

```bash
chatgpt2claude import <zip-file>   # Import a ChatGPT export
chatgpt2claude import <zip> --force # Re-import (overwrites existing)
chatgpt2claude stats               # Show import statistics
chatgpt2claude config              # Print Claude Desktop/Code config
chatgpt2claude serve               # Start MCP server (used by Claude)
chatgpt2claude reset               # Delete all imported data
```

## MCP Tools

Once connected, Claude has access to these tools:

| Tool | Description |
|------|-------------|
| `search_conversations` | Semantic + keyword search across all conversations |
| `get_conversation` | Read a full conversation transcript |
| `list_conversations` | Browse conversations by date, with optional keyword filter |
| `get_context_summary` | Quick overview of a conversation (opening + recent messages) |
| `get_stats` | Total conversations, date range, models used, storage info |

## How It Works

1. **Parsing**: The ChatGPT export uses a tree structure for conversations (to support message editing/regeneration). chatgpt2claude traverses this tree to reconstruct the canonical conversation thread.

2. **Storage**: Conversations are stored in SQLite (for structured queries and keyword search via FTS5) and ChromaDB (for semantic/vector search using the all-MiniLM-L6-v2 embedding model).

3. **Search**: When you search, both engines run in parallel. Results are merged, deduplicated, and ranked by a combined relevance score.

All data is stored locally in `~/.chatgpt2claude/`.

## Requirements

- Python 3.10 or newer
- ~100 MB disk space for the embedding model (downloaded on first use)
- Your ChatGPT data export ZIP file

## Troubleshooting

**"No conversations found"**: Make sure you ran `chatgpt2claude import` first. Check with `chatgpt2claude stats`.

**Import seems slow**: First import downloads the embedding model (~90 MB). Subsequent imports are much faster.

**Claude can't find the server**: Run `chatgpt2claude config` to get the exact configuration snippet. Make sure you've restarted Claude Desktop after editing the config.

**Want to re-import**: Use `chatgpt2claude import your-file.zip --force` to overwrite existing conversations.

## Privacy

- All data stays on your machine
- No API keys or network calls required
- Conversations are stored in `~/.chatgpt2claude/`
- Run `chatgpt2claude reset` to delete everything

## License

MIT
