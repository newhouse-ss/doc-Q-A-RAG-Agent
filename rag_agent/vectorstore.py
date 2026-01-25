from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.vectorstores import InMemoryVectorStore

from rag_agent.config import CHUNK_SIZE, CHUNK_OVERLAP, load_urls
from rag_agent.models import get_embeddings_model
from rag_agent.loader import load_documents


def build_vectorstore(urls: list[str] | None = None) -> InMemoryVectorStore:
    urls = urls or load_urls()

    docs_list = load_documents(urls)

    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    doc_splits = text_splitter.split_documents(docs_list)
    print(f"Documents split into {len(doc_splits)} chunks.")

    # Add stable chunk_id; keep existing metadata like source/page/title
    for idx, d in enumerate(doc_splits):
        d.metadata = d.metadata or {}
        d.metadata["chunk_id"] = str(idx)

    embeddings = get_embeddings_model()
    return InMemoryVectorStore.from_documents(documents=doc_splits, embedding=embeddings)


def build_retriever(urls: list[str] | None = None):
    # Backward compatible if other code still calls build_retriever()
    vs = build_vectorstore(urls=urls)
    return vs.as_retriever()