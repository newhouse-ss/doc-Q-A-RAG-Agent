from __future__ import annotations

from langchain.tools import tool
from langchain_core.vectorstores import VectorStore


def make_retriever_tool(vectorstore: VectorStore, k: int = 4):
    """
    Retriever tool (no global state, no score).
    Returns structured blocks so API can deterministically extract citations.
    """

    @tool
    def retrieve_blog_posts(query: str) -> str:
        """Search and return information from the knowledge base with citations."""
        docs = vectorstore.similarity_search(query, k=3)

        blocks = []
        for i, doc in enumerate(docs, start=1):
            meta = doc.metadata or {}

            source = meta.get("source", "unknown")   # URL or local file path
            title = meta.get("title", "")            # optional
            page = meta.get("page", "")              # PDF page if exists (1-based)
            chunk = meta.get("chunk_id", str(i))     # set during splitting if you added it

            text = doc.page_content or ""
            snippet = text[:1024].replace("\n", " ").strip()

            blocks.append(
                f"[CITATION {i}]\n"
                f"SOURCE: {source}\n"
                f"TITLE: {title}\n"
                f"PAGE: {page}\n"
                f"CHUNK: {chunk}\n"
                f"SNIPPET: {snippet}\n"
                f"CONTENT:\n{text}"
            )

        return "\n\n".join(blocks)

    return retrieve_blog_posts