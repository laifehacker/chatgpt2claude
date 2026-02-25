"""CLI interface for chatgpt2claude."""

from __future__ import annotations

import json
import shutil
import sys

import click

from . import __version__
from .config import CHROMA_PATH, DATA_DIR, SQLITE_PATH


@click.group()
@click.version_option(version=__version__, prog_name="chatgpt2claude")
def cli():
    """chatgpt2claude — Search your ChatGPT history from Claude.

    Import your ChatGPT export, then use this as an MCP server in Claude Desktop
    or Claude Code to search through all your old conversations.
    """
    pass


@cli.command("import")
@click.argument("zip_path", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Re-import conversations that already exist")
def import_cmd(zip_path: str, force: bool):
    """Import a ChatGPT data export ZIP file.

    Get your export from ChatGPT: Settings → Data Controls → Export Data.
    You'll receive a ZIP file containing your conversations.

    Example:
        chatgpt2claude import ~/Downloads/chatgpt-2024-01-15.zip
    """
    from .importer import import_chatgpt_export

    import_chatgpt_export(zip_path, force=force)


@cli.command()
def serve():
    """Start the MCP server (stdio transport).

    This is used by Claude Desktop and Claude Code to communicate
    with chatgpt2claude. You usually don't need to run this manually.
    """
    if not SQLITE_PATH.exists():
        click.echo(
            "Warning: No data imported yet. Import your ChatGPT export first:",
            err=True,
        )
        click.echo(
            "  chatgpt2claude import ~/Downloads/your-chatgpt-export.zip",
            err=True,
        )

    from .server import mcp

    mcp.run(transport="stdio")


@cli.command()
def stats():
    """Show statistics about your imported conversations."""
    if not SQLITE_PATH.exists():
        click.echo("No data found. Import your ChatGPT export first:")
        click.echo("  chatgpt2claude import ~/Downloads/your-chatgpt-export.zip")
        return

    from .storage import ConversationStore

    store = ConversationStore(SQLITE_PATH)
    s = store.get_stats()
    store.close()

    click.echo()
    click.echo(click.style("ChatGPT Import Statistics", bold=True))
    click.echo(f"  Conversations:  {s['total_conversations']:,}")
    click.echo(f"  Messages:       {s['total_messages']:,}")
    click.echo(f"  Avg msgs/conv:  {s['avg_messages_per_conversation']}")
    if s["date_range_start"]:
        click.echo(f"  Date range:     {s['date_range_start']} → {s['date_range_end']}")
    if s["top_models"]:
        click.echo(f"  Models used:")
        for m in s["top_models"]:
            click.echo(f"    {m['model']}: {m['count']:,}")

    # Storage size
    db_size = SQLITE_PATH.stat().st_size if SQLITE_PATH.exists() else 0
    chroma_size = (
        sum(f.stat().st_size for f in CHROMA_PATH.rglob("*") if f.is_file())
        if CHROMA_PATH.exists()
        else 0
    )
    total_mb = (db_size + chroma_size) / (1024 * 1024)
    click.echo(f"  Storage:        {total_mb:.1f} MB")
    click.echo(f"  Location:       {DATA_DIR}")
    click.echo()


@cli.command()
def config():
    """Print the configuration snippet for Claude Desktop and Claude Code."""
    click.echo()
    click.echo(click.style("Claude Desktop", bold=True))
    click.echo("Add this to your Claude Desktop config file:")
    click.echo()

    # Detect if chatgpt2claude is available via uvx or pip
    chatgpt2claude_path = shutil.which("chatgpt2claude")

    if chatgpt2claude_path:
        desktop_config = {
            "mcpServers": {
                "chatgpt2claude": {
                    "command": chatgpt2claude_path,
                    "args": ["serve"],
                }
            }
        }
    else:
        desktop_config = {
            "mcpServers": {
                "chatgpt2claude": {
                    "command": "uvx",
                    "args": ["chatgpt2claude", "serve"],
                }
            }
        }

    click.echo(json.dumps(desktop_config, indent=2))
    click.echo()

    if sys.platform == "darwin":
        click.echo(
            "Config file location: "
            "~/Library/Application Support/Claude/claude_desktop_config.json"
        )
    elif sys.platform == "win32":
        click.echo("Config file location: %APPDATA%\\Claude\\claude_desktop_config.json")
    else:
        click.echo("Config file location: ~/.config/Claude/claude_desktop_config.json")

    click.echo()
    click.echo(click.style("Claude Code", bold=True))
    click.echo("Run this command:")
    click.echo()

    if chatgpt2claude_path:
        click.echo(f"  claude mcp add chatgpt2claude -- {chatgpt2claude_path} serve")
    else:
        click.echo("  claude mcp add chatgpt2claude -- uvx chatgpt2claude serve")

    click.echo()


@cli.command()
@click.confirmation_option(prompt="This will delete all imported data. Are you sure?")
def reset():
    """Delete all imported data and start fresh."""
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
        click.echo(f"Deleted {DATA_DIR}")
    else:
        click.echo("No data to delete.")
