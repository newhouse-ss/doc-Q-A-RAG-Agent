from __future__ import annotations

from functools import partial
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.caches import InMemoryCache
from langchain_core.globals import set_llm_cache

from rag_agent.models import get_llm_model
from rag_agent.vectorstore import build_vectorstore
from rag_agent.tools import make_retriever_tool
from rag_agent.nodes import (
    generate_query_or_respond,
    grade_documents,
    rewrite_question,
    generate_answer,
)


def build_graph(urls: list[str] | None = None):
    set_llm_cache(InMemoryCache())
    print("Building Vector Store...")
    vectorstore = build_vectorstore(urls=urls)

    print("Setting up Tools...")
    retriever_tool = make_retriever_tool(vectorstore, k=4)
    tools = [retriever_tool]

    print("Creating LLM...")
    llm = get_llm_model()

    print("Compiling Graph...")
    workflow = StateGraph(MessagesState)

    workflow.add_node(
        "generate_query_or_respond",
        partial(generate_query_or_respond, tools=tools, llm=llm) # in LangGraph, the node and edges only accept a single attribute, but to achieve some aim we need mulitple attributes, they need to be wrapped into a partial then give LangGraph.
    )
    workflow.add_node("retrieve", ToolNode(tools))
    workflow.add_node("rewrite_question", partial(rewrite_question, llm=llm))
    workflow.add_node("generate_answer", partial(generate_answer, llm=llm))

    workflow.add_edge(START, "generate_query_or_respond")

    workflow.add_conditional_edges(
        "generate_query_or_respond",
        tools_condition,
        {"tools": "retrieve", END: END},
    )

    workflow.add_conditional_edges(
        "retrieve",
        partial(grade_documents, llm=llm),
    )

    workflow.add_edge("generate_answer", END)
    workflow.add_edge("rewrite_question", "generate_query_or_respond")

    return workflow.compile()