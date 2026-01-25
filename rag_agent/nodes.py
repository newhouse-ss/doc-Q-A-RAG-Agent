from typing import Literal
from pydantic import BaseModel, Field
from langgraph.graph import MessagesState
from langchain_core.messages import HumanMessage

from rag_agent.models import get_llm_model


# --- Prompts ---
GRADE_PROMPT = (
    "You are a grader assessing relevance of a retrieved document to a user question.\n"
    "Here is the retrieved document:\n\n{context}\n\n"
    "Here is the user question:\n{question}\n"
    "If the document is relevant, output 'yes', otherwise output 'no'."
)

REWRITE_PROMPT = (
    "Look at the input question and infer the user's intent.\n"
    "Initial question:\n{question}\n"
    "Rewrite it into a clearer, search-friendly question."
)

GENERATE_PROMPT = (
    "You are an assistant for question-answering tasks.\n"
    "Use the following retrieved context to answer the question.\n"
    "If you don't know, say you don't know.\n"
    "Use three sentences maximum and keep the answer concise.\n\n"
    "Question:\n{question}\n\n"
    "Context:\n{context}"
)


class GradeDocuments(BaseModel):
    binary_score: str = Field(description="Relevance score: 'yes' or 'no'")


def _llm_or_default(llm):
    return llm if llm is not None else get_llm_model()


def generate_query_or_respond(state: MessagesState, tools, llm=None):
    """Decide whether to call the retrieve tool or answer directly."""
    llm = _llm_or_default(llm)
    response = llm.bind_tools(tools).invoke(state["messages"])
    return {"messages": [response]}


def grade_documents(state: MessagesState, llm=None) -> Literal["generate_answer", "rewrite_question"]:
    """Evaluate retrieved context relevance."""
    llm = _llm_or_default(llm)

    question = state["messages"][0].content
    context = state["messages"][-1].content
    prompt = GRADE_PROMPT.format(question=question, context=context)

    response = llm.with_structured_output(GradeDocuments).invoke(
        [{"role": "user", "content": prompt}]
    )

    score = (response.binary_score or "").lower().strip()
    return "generate_answer" if score == "yes" else "rewrite_question"


def rewrite_question(state: MessagesState, llm=None):
    llm = _llm_or_default(llm)

    question = state["messages"][0].content
    prompt = REWRITE_PROMPT.format(question=question)

    response = llm.invoke([{"role": "user", "content": prompt}])
    return {"messages": [HumanMessage(content=response.content)]}


def generate_answer(state: MessagesState, llm=None):
    llm = _llm_or_default(llm)

    question = state["messages"][0].content
    context = state["messages"][-1].content
    prompt = GENERATE_PROMPT.format(question=question, context=context)

    response = llm.invoke([{"role": "user", "content": prompt}])
    return {"messages": [response]}