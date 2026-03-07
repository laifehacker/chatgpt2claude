"""Import pipeline: ZIP/markdown extraction → parsing → chunking → storage."""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

import click

from .chunker import chunk_conversation
from .config import CHROMA_PATH, SQLITE_PATH
from .parser import parse_conversations
from .storage import ConversationStore
from .vectorstore import ConversationVectorStore

logger = logging.getLogger(__name__)


def _load_conversations_from_zip(zip_file: Path):
    """Load and parse conversations from a ChatGPT export ZIP."""
    if not zipfile.is_zipfile(str(zip_file)):
        raise click.ClickException(f"Not a valid ZIP file: {zip_file}")

    click.echo("Reading ZIP file...")
    with zipfile.ZipFile(str(zip_file), "r") as zf:
        if "conversations.json" not in zf.namelist():
            raise click.ClickException(
                "No conversations.json found in ZIP. "
                "Make sure this is a ChatGPT data export "
                "(Settings → Data Controls → Export Data)."
            )

        with zf.open("conversations.json") as f:
            data = json.load(f)

    if not isinstance(data, list):
        raise click.ClickException("conversations.json is not a JSON array.")

    click.echo(f"Found {len(data)} conversations in export.")
    click.echo("Parsing conversations...")
    conversations = parse_conversations(data)
    click.echo(f"Successfully parsed {len(conversations)} conversations.")
    return conversations


def _load_conversations_from_markdown(md_path: Path):
    """Load and parse conversations from markdown files (chatgptexporter format)."""
    from .md_parser import parse_markdown_path

    click.echo(f"Reading markdown files from {md_path}...")
    conversations = parse_markdown_path(md_path)
    click.echo(f"Parsed {len(conversations)} conversations from markdown.")
    return conversations


def import_chatgpt_export(input_path: str, force: bool = False) -> dict:
    """Import a ChatGPT export (ZIP file or markdown folder/file).

    Supports:
      - Standard ChatGPT export ZIP (conversations.json inside)
      - Markdown files from chatgptexporter (.md files or folder)

    Returns a summary dict with import statistics.
    """
    path = Path(input_path)

    if not path.exists():
        raise click.ClickException(f"File not found: {input_path}")

    # Detect input type
    if path.is_dir() or path.suffix == ".md":
        conversations = _load_conversations_from_markdown(path)
    elif path.suffix == ".zip" or zipfile.is_zipfile(str(path)):
        conversations = _load_conversations_from_zip(path)
    else:
        raise click.ClickException(
            f"Unsupported input: {input_path}\n"
            "Expected a .zip file, .md file, or folder with .md files."
        )

    if not conversations:
        click.echo("No conversations to import.")
        return {"imported": 0, "skipped": 0, "messages": 0}

    # Initialize storage
    store = ConversationStore(SQLITE_PATH)
    vectorstore = ConversationVectorStore(CHROMA_PATH)

    imported = 0
    skipped = 0
    total_messages = 0
    total_chunks = 0

    with click.progressbar(
        conversations,
        label="Importing conversations",
        show_pos=True,
    ) as progress:
        for conv in progress:
            # Skip existing unless force re-import
            if not force and store.conversation_exists(conv.id):
                skipped += 1
                continue

            # Store in SQLite
            store.upsert_conversation(conv)

            # Chunk and store in ChromaDB
            if force:
                vectorstore.delete_conversation(conv.id)
            chunks = chunk_conversation(conv)
            vectorstore.add_chunks(chunks)

            imported += 1
            total_messages += conv.message_count
            total_chunks += len(chunks)

    # Record import metadata
    store.record_import(
        file_path=str(path),
        conversations=imported,
        messages=total_messages,
    )
    store.close()

    summary = {
        "imported": imported,
        "skipped": skipped,
        "messages": total_messages,
        "chunks": total_chunks,
    }

    # Print summary
    click.echo()
    click.echo(click.style("Import complete!", fg="green", bold=True))
    click.echo(f"  Imported: {imported} conversations ({total_messages} messages)")
    if skipped:
        click.echo(f"  Skipped:  {skipped} (already imported, use --force to re-import)")
    click.echo(f"  Chunks:   {total_chunks} (indexed for semantic search)")

    with ConversationStore(SQLITE_PATH) as stats_store:
        stats = stats_store.get_stats()
    if stats["date_range_start"]:
        click.echo(
            f"  Range:    {stats['date_range_start']} → {stats['date_range_end']}"
        )

    return summary
