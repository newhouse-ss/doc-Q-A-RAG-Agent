FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 8000

ENV GOOGLE_API_KEY=""

CMD ["python", "-m", "uvicorn", "rag_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]