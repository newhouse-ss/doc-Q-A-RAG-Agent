import os
from pathlib import Path
from typing import List

# model selection
EMBEDDING_MODEL_NAME = "models/text-embedding-004"
LLM_MODEL_NAME = "gemini-2.5-flash"

# document processing configuration
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 50


def ensure_google_api_key() -> None:
    if "GOOGLE_API_KEY" not in os.environ:
        raise RuntimeError(
            "API key required. Set GOOGLE_API_KEY in environment variables."
        )

def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_urls() -> List[str]:
    """
    Always load sources from project_root/urls.txt.
    - One entry per line
    - Ignore empty lines and lines starting with '#'
    - Strip surrounding quotes if accidentally added
    """
    file_path = _project_root() / "urls.txt"
    if not file_path.exists():
        raise FileNotFoundError(f"urls.txt not found: {file_path}")

    urls: List[str] = []
    for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue

        # remove accidental wrapping quotes: "..." or '...'
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()

        urls.append(s)

    if not urls:
        raise ValueError(f"urls.txt is empty: {file_path}")

    return urls