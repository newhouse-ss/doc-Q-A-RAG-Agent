FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir langchain-postgres "psycopg[binary]"

COPY . /app

EXPOSE 8000

ENV GOOGLE_API_KEY=""
ENV PGVECTOR_CONNECTION_STRING=""
ENV PGVECTOR_COLLECTION="documents"

CMD ["python", "-m", "uvicorn", "rag_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
