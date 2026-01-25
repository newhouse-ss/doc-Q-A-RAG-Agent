from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse, unquote

import requests
from langchain_community.document_loaders import WebBaseLoader
from langchain_core.documents import Document


def _as_local_file(s: str) -> Optional[Path]:
    """Return Path if s points to an existing local file (supports file://)."""
    s = s.strip()
    if not s:
        return None

    if s.lower().startswith("file://"):
        u = urlparse(s)
        p = unquote(u.path or "")
        # Windows: file:///D:/... -> /D:/...
        if p.startswith("/") and len(p) >= 3 and p[2] == ":":
            p = p[1:]
        s = p

    p = Path(s)
    return p if p.exists() and p.is_file() else None


def _load_pdf_bytes(data: bytes, source: str) -> List[Document]:
    try:
        from pypdf import PdfReader  # pip install pypdf
    except Exception as e:
        raise RuntimeError("PDF loading requires `pypdf` (pip install pypdf).") from e

    import io

    reader = PdfReader(io.BytesIO(data)) # encoding类型怎么变化？怎么加pdf的？
    docs: List[Document] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            docs.append(Document(page_content=text, metadata={"source": source, "page": i})) # metadata includes the information we want to return in the citation.
    return docs


def _is_pdf_source(s: str) -> bool:
    return s.lower().endswith(".pdf")


def load_documents(sources: list[str]) -> List[Document]:
    """
    Supports:
      - local file path (txt/md/pdf/...)
      - file:// URL pointing to a local file
      - http(s) URL (html)
      - http(s) PDF URL (endswith .pdf, loaded per-page)
    """
    print(f"Loading {len(sources)} documents...")
    out: List[Document] = []

    for raw in sources:
        item = raw.strip()
        if not item:
            continue

        local = _as_local_file(item)
        if local:
            if local.suffix.lower() == ".pdf":
                out.extend(_load_pdf_bytes(local.read_bytes(), source=str(local)))
            else:
                text = local.read_text(encoding="utf-8", errors="ignore")
                if text.strip():
                    out.append(Document(page_content=text, metadata={"source": str(local)})) # a document instance = content+metadata
            continue

        if item.lower().startswith(("http://", "https://")):
            if _is_pdf_source(item):
                resp = requests.get(item, timeout=(10, 30)) # (connect, read)
                resp.raise_for_status()
                out.extend(_load_pdf_bytes(resp.content, source=item))
            else:
                out.extend(WebBaseLoader(item).load())
            continue

        raise ValueError(f"Unsupported source (not URL or existing local file): {item}")

    return out