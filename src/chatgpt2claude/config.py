"""Central configuration for paths and constants."""

import os
from pathlib import Path

# Data directory — override with CHATGPT2CLAUDE_DATA_DIR env var
DATA_DIR = Path(
    os.environ.get("CHATGPT2CLAUDE_DATA_DIR", str(Path.home() / ".chatgpt2claude"))
)

# Database paths
SQLITE_PATH = DATA_DIR / "conversations.db"
CHROMA_PATH = DATA_DIR / "chroma"

# Chunking parameters
CHUNK_TURN_PAIRS = 4  # Number of user+assistant turn pairs per chunk
CHUNK_OVERLAP_PAIRS = 1  # Overlap between consecutive chunks
MAX_CHUNK_CHARS = 2000  # Safety limit per chunk

# ChromaDB
COLLECTION_NAME = "conversations"

# Roles to include in parsed output
INCLUDED_ROLES = {"user", "assistant"}
