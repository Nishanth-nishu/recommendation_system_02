# semantic-recsys

Monorepo with two microservices: ingest_service and rec_service.

- ingest_service: FastAPI app that ingests text, embeds with FAISS-compatible embeddings, and publishes events to Kafka.
- rec_service: FastAPI app that exposes a /recommend endpoint and uses FAISS for semantic retrieval.

Quickstart (development):

1. Create virtualenv and install deps for each service:

   python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r ingest_service\requirements.txt
   python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r rec_service\requirements.txt

2. Run services:

   uvicorn ingest_service.main:app --reload --port 8000
   uvicorn rec_service.main:app --reload --port 8001

3. Run tests (from repo root):

   pip install pytest; pytest -q
