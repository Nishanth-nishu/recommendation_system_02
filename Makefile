.PHONY: help build test deploy clean

# Variables
NAMESPACE := semantic-recsys
INGEST_IMAGE := semantic-recsys/ingest-service:latest
REC_IMAGE := semantic-recsys/rec-service:latest

help:
	@echo "Semantic Recommendation System - Make Commands"
	@echo ""
	@echo "Development:"
	@echo "  make install       - Install dependencies"
	@echo "  make test          - Run tests"
	@echo "  make test-cov      - Run tests with coverage"
	@echo "  make lint          - Run linting"
	@echo ""
	@echo "Docker:"
	@echo "  make build         - Build Docker images"
	@echo "  make up            - Start services with docker-compose"
	@echo "  make down          - Stop services"
	@echo "  make logs          - View logs"
	@echo ""
	@echo "Kubernetes:"
	@echo "  make k8s-deploy    - Deploy to Kubernetes"
	@echo "  make k8s-delete    - Delete from Kubernetes"
	@echo "  make k8s-status    - Check deployment status"
	@echo "  make k8s-logs      - View pod logs"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean         - Clean build artifacts"

# Development
install:
	pip install -r ingest_service/requirements.txt
	pip install -r rec_service/requirements.txt

test:
	pytest tests/ -v

test-cov:
	pytest tests/ --cov=. --cov-report=html --cov-report=term

lint:
	flake8 ingest_service/ rec_service/ tests/
	black --check ingest_service/ rec_service/ tests/

format:
	black ingest_service/ rec_service/ tests/

# Docker
build:
	@echo "Building Ingestion Service..."
	docker build -t $(INGEST_IMAGE) ./ingest_service
	@echo "Building Recommendation Service..."
	docker build -t $(REC_IMAGE) ./rec_service
	@echo "Build complete!"

up:
	docker-compose up -d

up-prod:
	docker-compose -f docker-compose.prod.yml up -d --scale rec-service=3

down:
	docker-compose down

down-prod:
	docker-compose -f docker-compose.prod.yml down

logs:
	docker-compose logs -f

logs-prod:
	docker-compose -f docker-compose.prod.yml logs -f

restart:
	docker-compose restart

# Production data loading
load-data:
	@echo "Starting production data loader..."
	python scripts/production_data_loader.py \
		--ingestion-url http://localhost:8001 \
		--redis-url redis://localhost:6379 \
		--workers 5 \
		--target 30000

load-data-docker:
	@echo "Running data loader in Docker..."
	docker run --rm --network semantic-recsys_semantic-network \
		-v $(PWD)/scripts:/scripts \
		python:3.11-slim \
		bash -c "pip install -r /scripts/requirements-loader.txt && python /scripts/production_data_loader.py \
		--ingestion-url http://ingest-service:8001 \
		--redis-url redis://redis:6379 \
		--workers 5 \
		--target 30000"

# Kubernetes
k8s-deploy:
	@echo "Deploying to Kubernetes..."
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/ingest-deployment.yaml
	kubectl apply -f k8s/rec-deployment.yaml
	@echo "Deployment initiated. Check status with: make k8s-status"

k8s-delete:
	kubectl delete -f k8s/rec-deployment.yaml
	kubectl delete -f k8s/ingest-deployment.yaml
	kubectl delete -f k8s/namespace.yaml

k8s-status:
	@echo "=== Namespace ==="
	kubectl get ns $(NAMESPACE)
	@echo ""
	@echo "=== Pods ==="
	kubectl get pods -n $(NAMESPACE)
	@echo ""
	@echo "=== Services ==="
	kubectl get svc -n $(NAMESPACE)
	@echo ""
	@echo "=== HPAs ==="
	kubectl get hpa -n $(NAMESPACE)

k8s-logs:
	@echo "Select service to view logs:"
	@echo "1) Ingestion Service"
	@echo "2) Recommendation Service"
	@read -p "Choice: " choice; \
	if [ "$$choice" = "1" ]; then \
		kubectl logs -n $(NAMESPACE) -l app=ingest-service --tail=100 -f; \
	elif [ "$$choice" = "2" ]; then \
		kubectl logs -n $(NAMESPACE) -l app=rec-service --tail=100 -f; \
	fi

k8s-port-forward:
	@echo "Port forwarding services..."
	kubectl port-forward -n $(NAMESPACE) svc/ingest-service 8001:8001 &
	kubectl port-forward -n $(NAMESPACE) svc/rec-service 8002:8002 &
	@echo "Services available at:"
	@echo "  Ingestion: http://localhost:8001"
	@echo "  Recommendation: http://localhost:8002"

k8s-describe:
	@echo "Select resource to describe:"
	@echo "1) Ingestion Deployment"
	@echo "2) Recommendation Deployment"
	@read -p "Choice: " choice; \
	if [ "$$choice" = "1" ]; then \
		kubectl describe deployment ingest-service -n $(NAMESPACE); \
	elif [ "$$choice" = "2" ]; then \
		kubectl describe deployment rec-service -n $(NAMESPACE); \
	fi

# Testing endpoints
test-ingest:
	@echo "Testing ingestion endpoint..."
	curl -X POST http://localhost:8001/ingest \
		-H "Content-Type: application/json" \
		-d '{"product_id": "TEST001", "title": "Test Product", "description": "Test description", "category": "Test", "price": 99.99}' | jq

test-recommend:
	@echo "Testing recommendation endpoint..."
	curl -X POST http://localhost:8002/recommend \
		-H "Content-Type: application/json" \
		-d '{"query": "wireless headphones", "top_k": 5}' | jq

# Utilities
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".coverage" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned build artifacts"

reset-data:
	@echo "WARNING: This will delete all FAISS index data!"
	@read -p "Are you sure? (yes/no): " confirm; \
	if [ "$$confirm" = "yes" ]; then \
		docker-compose down -v; \
		echo "Data volumes deleted"; \
	else \
		echo "Cancelled"; \
	fi