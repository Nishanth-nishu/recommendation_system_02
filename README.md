Markdown# Semantic Recommendation System

![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688?style=flat-square&logo=fastapi)
![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED?style=flat-square&logo=docker)
![Kubernetes](https://img.shields.io/badge/Kubernetes-Ready-326CE5?style=flat-square&logo=kubernetes)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

A production-grade, event-driven microservices architecture for semantic product recommendations. This system uses **FAISS** for vector similarity search, **Kafka** for asynchronous ingestion, and **Redis** for queue management, all wrapped in **FastAPI** services.

## Table of Contents
- [Overview](#-overview)
- [Key Features](#-key-features)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Prerequisites](#-prerequisites)
- [Quick Start](#-quick-start)
- [Manual Setup](#-manual-setup)
- [API Documentation](#-api-documentation)
- [Testing](#-testing)
- [Kubernetes Deployment](#-kubernetes-deployment)
- [Project Structure](#-project-structure)
- [Contributing](#-contributing)

---

## Overview

The Semantic Recommendation System is designed to solve the "cold start" problem in e-commerce by allowing users to search for products using natural language queries (e.g., *"running shoes for marathon"*). It converts products and user queries into vector embeddings and performs nearest-neighbor search to find the most relevant items.

## Key Features

* **Semantic Search:** Finds products based on meaning, not just keyword matching (powered by `all-MiniLM-L6-v2`).
* **Real-time Ingestion:** Asynchronous processing of new products via **Kafka**.
* **High Performance:** Uses **FAISS (Facebook AI Similarity Search)** for efficient vector retrieval.
* **Scalable Architecture:** Dockerized microservices with Nginx load balancing.
* **Observability:** Integrated **Prometheus** metrics and **Grafana** dashboards.
* **Resilience:** Dead Letter Queues (DLQ) in Redis for failed ingestions.
* **Production Ready:** Includes Kubernetes manifests and health check scripts.

---

## Architecture

The system consists of two main microservices and supporting infrastructure:

1.  **Ingestion Service (`ingest-service`):**
    * Accepts product data via REST API.
    * Generates vector embeddings using Sentence Transformers.
    * Publishes events to Kafka.
    * Updates the shared FAISS index.

2.  **Recommendation Service (`rec-service`):**
    * Handles search queries.
    * Converts queries to vectors.
    * Searches the shared FAISS index for similar products.

**Infrastructure:**
* **Kafka:** Event streaming backbone.
* **Redis:** Queue management and DLQ.
* **Nginx:** Load balancer and reverse proxy.
* **Prometheus & Grafana:** Monitoring stack.

---

## Tech Stack

* **Language:** Python 3.11
* **Framework:** FastAPI, Uvicorn
* **ML/AI:** PyTorch, Sentence-Transformers, FAISS
* **Streaming:** Apache Kafka, Zookeeper
* **Storage:** Redis (Queue/Cache)
* **Containerization:** Docker, Docker Compose
* **Orchestration:** Kubernetes (K8s)
* **Testing:** Pytest, Pytest-Cov

---

## Prerequisites

* **Docker** and **Docker Compose**
* **Python 3.10+** (for local development/testing)
* **Make** (optional, for running convenience commands)
* **Git**

---

## Quick Start

The easiest way to get the system running is using the included automation script.

```bash
# Clone the repository
git clone [https://github.com/yourusername/semantic-recsys.git](https://github.com/yourusername/semantic-recsys.git)
cd semantic-recsys

# Run the quick start script (Linux/Mac/Git Bash)
./scripts/quick_start.sh
This script will:Build Docker images.Start all services (Kafka, Redis, Ingest, Rec, Monitoring).Wait for health checks to pass.Load sample data.⚙ Manual SetupIf you prefer to control the process manually or are on Windows Command Prompt:1. Build and Start ServicesBash# Using Make
make build
make up-prod

# OR using Docker Compose directly
docker-compose -f docker-compose.prod.yml up -d --build
2. Verify HealthWait for about 60 seconds for Kafka and models to initialize, then check:Bashcurl http://localhost:8001/health  # Ingest Service
curl http://localhost:8002/health  # Rec Service
3. Load Sample DataThe system starts with 10k synthetic products. To load realistic sample data:Bash# Requires python libraries: httpx
pip install httpx
python scripts/load_sample.py

 API DocumentationIngestion Service (Port 8001)MethodEndpointDescriptionPayload ExamplePOST/ingestIngest a single product{"product_id": "P1", "title": "...", "description": "..."}POST/ingest/batchBulk ingest products{"products": [...]}GET/healthService health status-Recommendation Service (Port 8002 / LB 8080)MethodEndpointDescriptionPayload ExamplePOST/recommendSemantic search{"query": "wireless headphones", "top_k": 5}GET/recommend/product/{id}Find similar products-GET/statsIndex statistics-Example Recommendation Request:Bashcurl -X POST http://localhost:8002/recommend \
  -H "Content-Type: application/json" \
  -d '{"query": "running shoes for marathon", "top_k": 3}'
 TestingRunning Tests via Docker (Recommended)This avoids installing dependencies locally.Bash# Find your container name
docker ps | grep rec-service

# Run tests inside the container
docker exec -it <container_name> pytest tests/ -v
Running Tests LocallyTo run tests on your host machine (Windows/Linux/Mac):Install dependencies:Bashpip install -r ingest_service/requirements.txt
pip install pytest pytest-asyncio pytest-cov httpx
Set PYTHONPATH (Windows):DOSset PYTHONPATH=ingest_service;rec_service;%PYTHONPATH%
Set PYTHONPATH (Linux/Mac):Bashexport PYTHONPATH=ingest_service:rec_service:$PYTHONPATH
Run Pytest:Bashpytest tests/ -v
☸ Kubernetes DeploymentThe project is ready for Kubernetes deployment.Create Namespace:Bashkubectl apply -f k8s/namespace.yaml
Deploy Components:Bashkubectl apply -f k8s/ingest-deployment.yaml
kubectl apply -f k8s/rec-deployment.yaml
# Add other resources as needed (Redis, etc.)
Verify:Bashmake k8s-status

 Project StructurePlaintext.
├── docker-compose.prod.yml  # Production infrastructure (HA, Monitoring)
├── docker-compose.yml       # Development infrastructure
├── Makefile                 # Shortcuts for common commands
├── ingest_service/          # Ingestion Microservice
│   ├── main.py              # FastAPI app
│   ├── embedding.py         # FAISS & SentenceTransformer logic
│   └── kafka_pub.py         # Kafka Producer
├── rec_service/             # Recommendation Microservice
│   ├── main.py              # FastAPI app
│   └── retrieval.py         # Search logic
├── scripts/                 # Utility scripts
│   ├── health_check.sh      # System verification
│   ├── load_sample.py       # Data loader
│   └── quick_start.sh       # Automated setup
├── k8s/                     # Kubernetes manifests
└── tests/                   # Integration and Unit tests

ContributingContributions are welcome! Please follow these steps:Fork the repository.Create a feature branch (git checkout -b feature/AmazingFeature).Commit your changes (git commit -m 'Add some AmazingFeature').Push to the branch (git push origin feature/AmazingFeature).Open a Pull Request.Please ensure all tests pass before submitting your PR.
