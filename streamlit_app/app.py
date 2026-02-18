"""
Streamlit dashboard for the Citation-grounded RAG Agent.

Run with:
    streamlit run streamlit_app/app.py
"""

import os
import streamlit as st
import requests

st.set_page_config(page_title="RAG Agent", page_icon=None, layout="wide")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Settings")

    api_base = st.text_input(
        "API base URL",
        value=os.getenv("RAG_API_URL", "http://localhost:8000"),
    )
    timeout = st.slider("Timeout (seconds)", min_value=10, max_value=180, value=60)

    st.divider()
    st.subheader("Cache")
    col_stat, col_clear = st.columns(2)
    with col_stat:
        if st.button("Stats"):
            try:
                r = requests.get(f"{api_base}/v1/cache/stats", timeout=5)
                st.json(r.json())
            except Exception as e:
                st.error(str(e))
    with col_clear:
        if st.button("Clear"):
            try:
                requests.delete(f"{api_base}/v1/cache", timeout=5)
                st.success("Cache cleared")
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.subheader("Health")
    if st.button("Check API"):
        try:
            r = requests.get(f"{api_base}/healthz", timeout=5)
            if r.status_code == 200:
                st.success("API is healthy")
            else:
                st.error(f"Status {r.status_code}")
        except Exception as e:
            st.error(f"Cannot reach API: {e}")

    st.divider()
    st.caption("Citation-grounded RAG Agent v2.0")

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("Citation-grounded RAG Agent")
st.markdown(
    "Ask questions about the ingested document base. "
    "Answers include source citations for traceability."
)

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("citations"):
            with st.expander("Citations"):
                for i, cit in enumerate(msg["citations"], 1):
                    parts = [f"**[{i}]** {cit.get('source', '')}"]
                    if cit.get("title"):
                        parts.append(f"  Title: {cit['title']}")
                    if cit.get("page"):
                        parts.append(f"  Page: {cit['page']}")
                    if cit.get("snippet"):
                        parts.append(f"  Snippet: {cit['snippet'][:200]}...")
                    st.markdown("\n".join(parts))
        if msg.get("cached"):
            st.caption("(served from semantic cache)")

if prompt := st.chat_input("Type your question here..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Retrieving and generating answer..."):
            try:
                resp = requests.post(
                    f"{api_base}/v1/chat",
                    json={"message": prompt, "timeout_s": timeout},
                    timeout=timeout + 5,
                )
                resp.raise_for_status()
                data = resp.json()

                answer = data.get("answer", "")
                citations = data.get("citations", [])
                cached = data.get("cached", False)

                st.markdown(answer)
                if citations:
                    with st.expander("Citations"):
                        for i, cit in enumerate(citations, 1):
                            parts = [f"**[{i}]** {cit.get('source', '')}"]
                            if cit.get("title"):
                                parts.append(f"  Title: {cit['title']}")
                            if cit.get("page"):
                                parts.append(f"  Page: {cit['page']}")
                            if cit.get("snippet"):
                                parts.append(f"  Snippet: {cit['snippet'][:200]}...")
                            st.markdown("\n".join(parts))
                if cached:
                    st.caption("(served from semantic cache)")

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "citations": citations,
                    "cached": cached,
                })

            except requests.exceptions.ConnectionError:
                st.error(
                    f"Cannot connect to the API at {api_base}. "
                    "Make sure the FastAPI server is running:\n\n"
                    "```\nuvicorn rag_agent.api:app --host 0.0.0.0 --port 8000\n```"
                )
            except requests.exceptions.HTTPError as e:
                st.error(f"API error: {e.response.status_code} - {e.response.text}")
            except Exception as e:
                st.error(f"Unexpected error: {e}")
