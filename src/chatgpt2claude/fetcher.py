"""Fetch conversations directly from ChatGPT backend API.

Used when the normal 'Export Data' feature is unavailable (e.g., Teams accounts).
"""

from __future__ import annotations

import json
import random
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import click
import requests

from .config import DATA_DIR

FETCH_DIR = DATA_DIR / "fetch"
CONVERSATIONS_DIR = FETCH_DIR / "conversations"
PROGRESS_FILE = FETCH_DIR / "progress.json"

BASE_URL = "https://chatgpt.com/backend-api"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class TokenExpiredError(Exception):
    """Raised when the ChatGPT session token has expired."""


class ChatGPTFetcher:
    """Fetches conversations from the ChatGPT backend API with safety mechanisms."""

    def __init__(self, token: str, delay: float = 5.0):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.progress = self._load_progress()

        # Ensure directories exist
        CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)

    def update_token(self, token: str) -> None:
        """Update the bearer token after expiry."""
        self.session.headers["Authorization"] = f"Bearer {token}"

    # ── Progress / checkpoint ────────────────────────────────────────

    def _load_progress(self) -> dict:
        if PROGRESS_FILE.exists():
            return json.loads(PROGRESS_FILE.read_text())
        return {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "conversation_list": [],
            "total_conversations": 0,
            "fetched_ids": [],
            "last_list_offset": 0,
            "list_complete": False,
        }

    def _save_progress(self) -> None:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS_FILE.write_text(json.dumps(self.progress, indent=2))

    # ── HTTP with retry ──────────────────────────────────────────────

    def _request(self, url: str, max_retries: int = 5) -> dict:
        """GET request with exponential backoff and token refresh."""
        backoff = 30.0

        for attempt in range(max_retries):
            try:
                resp = self.session.get(url, timeout=60)
            except requests.exceptions.RequestException as e:
                click.echo(f"\n  Connection error: {e}", err=True)
                if attempt < max_retries - 1:
                    wait = min(backoff * (2**attempt), 300) + random.uniform(0, 5)
                    click.echo(f"  Retrying in {wait:.0f}s...", err=True)
                    time.sleep(wait)
                    continue
                raise

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code in (401, 403):
                click.echo(
                    "\n\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "  Token expired! Refresh needed.\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "\n"
                    "  1. Go to chatgpt.com in your browser\n"
                    "  2. Open DevTools (F12) → Network tab\n"
                    "  3. Refresh the page or send a message\n"
                    "  4. Find a request to backend-api\n"
                    "  5. Copy the token from the Authorization header\n"
                    "     (the part after 'Bearer ')\n",
                    err=True,
                )
                new_token = click.prompt("Paste new token", hide_input=True)
                self.update_token(new_token.strip())
                continue  # Retry with new token

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    wait = float(retry_after) + random.uniform(1, 5)
                else:
                    wait = min(backoff * (2**attempt), 300) + random.uniform(1, 10)
                click.echo(
                    f"\n  Rate limited (429). Waiting {wait:.0f}s... "
                    f"(attempt {attempt + 1}/{max_retries})",
                    err=True,
                )
                time.sleep(wait)
                continue

            if resp.status_code in (502, 503):
                wait = 10 + random.uniform(1, 5)
                click.echo(
                    f"\n  Server error ({resp.status_code}). Waiting {wait:.0f}s...",
                    err=True,
                )
                time.sleep(wait)
                continue

            # Unknown error
            click.echo(
                f"\n  Unexpected status {resp.status_code}: {resp.text[:200]}",
                err=True,
            )
            if attempt < max_retries - 1:
                time.sleep(10)
                continue
            resp.raise_for_status()

        raise click.ClickException(
            f"Failed after {max_retries} retries. Try again later or increase --delay."
        )

    # ── List all conversations ───────────────────────────────────────

    def list_conversations(self) -> list[dict]:
        """Paginate through all conversations. Resumable via checkpoint."""
        if self.progress["list_complete"]:
            click.echo(
                f"Using cached conversation list "
                f"({self.progress['total_conversations']} conversations)"
            )
            return self.progress["conversation_list"]

        click.echo("Fetching conversation list...")

        offset = self.progress["last_list_offset"]
        known_ids = {c["id"] for c in self.progress["conversation_list"]}
        limit = 100

        while True:
            url = f"{BASE_URL}/conversations?offset={offset}&limit={limit}&order=updated"
            data = self._request(url)

            items = data.get("items", [])
            if not items:
                break

            for item in items:
                if item["id"] not in known_ids:
                    self.progress["conversation_list"].append(
                        {
                            "id": item["id"],
                            "title": item.get("title", "Untitled"),
                            "create_time": item.get("create_time"),
                            "update_time": item.get("update_time"),
                        }
                    )
                    known_ids.add(item["id"])

            offset += len(items)
            self.progress["last_list_offset"] = offset
            self._save_progress()

            total = data.get("total", "?")
            click.echo(f"  Listed {len(self.progress['conversation_list'])}/{total}")

            # Check if we've reached the end
            if data.get("has_missing_conversations") is False and offset >= data.get(
                "total", float("inf")
            ):
                break
            if len(items) < limit:
                break

            # Small delay between listing pages
            time.sleep(2 + random.uniform(0, 1))

        self.progress["list_complete"] = True
        self.progress["total_conversations"] = len(self.progress["conversation_list"])
        self._save_progress()

        click.echo(
            f"Found {self.progress['total_conversations']} conversations total."
        )
        return self.progress["conversation_list"]

    # ── Fetch individual conversation ────────────────────────────────

    def fetch_conversation(self, conv_id: str) -> dict:
        """Fetch a single conversation by ID."""
        url = f"{BASE_URL}/conversation/{conv_id}"
        return self._request(url)

    # ── Main orchestrator ────────────────────────────────────────────

    def fetch_all(self) -> Path:
        """Fetch all conversations and assemble into export ZIP.

        Returns the path to the generated ZIP file.
        """
        conversations = self.list_conversations()
        fetched_set = set(self.progress["fetched_ids"])
        remaining = [c for c in conversations if c["id"] not in fetched_set]

        total = len(conversations)
        done = total - len(remaining)

        if not remaining:
            click.echo("All conversations already fetched!")
        else:
            click.echo(
                f"\nFetching {len(remaining)} conversations "
                f"({done} already done, {total} total)"
            )
            click.echo(
                f"Estimated time: ~{len(remaining) * (self.delay + 1) / 60:.0f} minutes "
                f"(at {self.delay}s delay)\n"
            )

            for i, conv_meta in enumerate(remaining, start=done + 1):
                conv_id = conv_meta["id"]
                title = conv_meta.get("title", "Untitled")
                short_title = title[:50] + "..." if len(title) > 50 else title

                try:
                    conv_data = self.fetch_conversation(conv_id)

                    # Save individual conversation
                    conv_file = CONVERSATIONS_DIR / f"{conv_id}.json"
                    conv_file.write_text(json.dumps(conv_data))

                    # Update checkpoint
                    self.progress["fetched_ids"].append(conv_id)
                    self._save_progress()

                    click.echo(f"  [{i}/{total}] {short_title}")

                except Exception as e:
                    click.echo(
                        f"  [{i}/{total}] FAILED: {short_title} — {e}", err=True
                    )
                    # Continue with next conversation
                    continue

                # Delay between fetches (with jitter)
                if i < total:
                    time.sleep(self.delay + random.uniform(-1, 1))

        # Assemble into ZIP
        return self.assemble_export()

    # ── Assemble export ZIP ──────────────────────────────────────────

    def assemble_export(self) -> Path:
        """Combine all fetched conversations into a conversations.json ZIP."""
        click.echo("\nAssembling export...")

        conv_files = sorted(CONVERSATIONS_DIR.glob("*.json"))
        if not conv_files:
            raise click.ClickException("No conversations fetched yet.")

        conversations = []
        for f in conv_files:
            try:
                conversations.append(json.loads(f.read_text()))
            except json.JSONDecodeError:
                click.echo(f"  Skipping corrupt file: {f.name}", err=True)

        click.echo(f"  {len(conversations)} conversations assembled")

        # Write conversations.json
        conversations_json = FETCH_DIR / "conversations.json"
        conversations_json.write_text(json.dumps(conversations, ensure_ascii=False))

        # Package into ZIP
        zip_path = FETCH_DIR / "export.zip"
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(str(conversations_json), "conversations.json")

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        click.echo(f"  Export saved: {zip_path} ({size_mb:.1f} MB)")

        return zip_path


def clear_fetch_progress() -> None:
    """Remove checkpoint to start fresh."""
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        click.echo("Cleared fetch progress.")
    # Also clear individual conversation files
    if CONVERSATIONS_DIR.exists():
        import shutil

        shutil.rmtree(CONVERSATIONS_DIR)
        click.echo("Cleared cached conversations.")
