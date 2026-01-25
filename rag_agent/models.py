from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from rag_agent.config import LLM_MODEL_NAME, EMBEDDING_MODEL_NAME

def get_embeddings_model():
    """get the Embedding model instance."""
    return GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME)

def get_llm_model():
    """get LLM instance."""
    return ChatGoogleGenerativeAI(
        model=LLM_MODEL_NAME,
        temperature=0,
        max_retries=2,
    )