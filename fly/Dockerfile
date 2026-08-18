FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY anthropic_config.py .
COPY auth.py .
COPY db.py .
COPY chat_memory.py .
COPY engineer_scenarios.py .
COPY agents/ ./agents/
COPY management_sim/ ./management_sim/
COPY data/ ./data/
COPY static/ ./static/
# api-key minting via fly ssh console
COPY scripts/ ./scripts/

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
