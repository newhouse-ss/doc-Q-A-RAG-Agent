from typing import List

from langchain_core.embeddings import Embeddings
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from rag_agent.config import LLM_MODEL_NAME, EMBEDDING_MODEL_NAME, EMBEDDING_DIM


class DimensionReducedEmbeddings(Embeddings):
    def __init__(self, base: Embeddings, dim: int):
        self._base = base
        self._dim = dim

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [v[: self._dim] for v in self._base.embed_documents(texts)]

    def embed_query(self, text: str) -> List[float]:
        return self._base.embed_query(text)[: self._dim]


def get_embeddings_model():
    base = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME)
    return DimensionReducedEmbeddings(base, EMBEDDING_DIM)

def get_llm_model():
    return ChatGoogleGenerativeAI(
        model=LLM_MODEL_NAME,
        temperature=0,
        max_retries=2,
    )
