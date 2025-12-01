#!/bin/bash

# Quick Start Script for Semantic Recommendation System
# This script automates the entire setup process

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
TARGET_PRODUCTS=30000
NUM_WORKERS=5

echo -e "${BLUE}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════╗
║   Semantic Recommendation System - Quick Start           ║
║   Production-Grade E-Commerce Recommendation Engine      ║
╚═══════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Step 1: Check prerequisites
echo -e "\n${YELLOW}[Step 1/6]${NC} Checking prerequisites..."

check_command() {
    if command -v $1 &> /dev/null; then
        echo -e "${GREEN}✓${NC} $1 is installed"
        return 0
    else
        echo -e "${RED}✗${NC} $1 is not installed"
        return 1
    fi
}

MISSING_DEPS=0

check_command docker || MISSING_DEPS=1
check_command docker-compose || MISSING_DEPS=1
check_command python3 || MISSING_DEPS=1
check_command make || MISSING_DEPS=1

if [ $MISSING_DEPS -eq 1 ]; then
    echo -e "${RED}Missing required dependencies. Please install them first.${NC}"
    exit 1
fi

# Check Docker is running
if ! docker info &> /dev/null; then
    echo -e "${RED}✗ Docker daemon is not running. Please start Docker.${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} Docker daemon is running"

# Step 2: Build Docker images
echo -e "\n${YELLOW}[Step 2/6]${NC} Building Docker images..."
make build

# Step 3: Start infrastructure
echo -e "\n${YELLOW}[Step 3/6]${NC} Starting infrastructure (Redis, Kafka, services)..."
docker-compose -f docker-compose.prod.yml up -d

echo "Waiting for services to be healthy (this may take 2-3 minutes)..."
sleep 10

# Wait for health checks
MAX_WAIT=180
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
    if curl -sf http://localhost:8001/health > /dev/null 2>&1 && \
       curl -sf http://localhost:8002/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} All services are healthy!"
        break
    fi
    
    echo -n "."
    sleep 5
    ELAPSED=$((ELAPSED + 5))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    echo -e "\n${RED}✗ Services failed to become healthy. Check logs with: make logs-prod${NC}"
    exit 1
fi

# Step 4: Install data loader dependencies
echo -e "\n${YELLOW}[Step 4/6]${NC} Installing data loader dependencies..."
pip install -q -r scripts/requirements-loader.txt
echo -e "${GREEN}✓${NC} Dependencies installed"

# Step 5: Load data
echo -e "\n${YELLOW}[Step 5/6]${NC} Loading ${TARGET_PRODUCTS} products from DummyJSON..."
echo "This will take approximately 30 minutes with ${NUM_WORKERS} workers"
echo ""

read -p "Start data loading now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Run in background and show progress
    python scripts/production_data_loader.py \
        --ingestion-url http://localhost:8001 \
        --redis-url redis://localhost:6379 \
        --workers ${NUM_WORKERS} \
        --target ${TARGET_PRODUCTS} \
        --metrics-port 9090 &
    
    LOADER_PID=$!
    
    echo -e "${GREEN}✓${NC} Data loader started (PID: $LOADER_PID)"
    echo "Monitor progress at:"
    echo "  - Metrics: http://localhost:9090/metrics"
    echo "  - Prometheus: http://localhost:9091"
    echo "  - Logs: tail -f data_loader.log"
    echo ""
    echo "Press Ctrl+C to stop monitoring (loader will continue in background)"
    
    # Monitor progress
    while kill -0 $LOADER_PID 2>/dev/null; do
        INGESTED=$(curl -s http://localhost:9090/metrics 2>/dev/null | grep "products_ingested_total" | awk '{print $2}' | head -1)
        QUEUE_SIZE=$(redis-cli -h localhost -p 6379 ZCARD product_ingestion 2>/dev/null || echo "0")
        
        if [ ! -z "$INGESTED" ]; then
            PERCENT=$((INGESTED * 100 / TARGET_PRODUCTS))
            echo -ne "\rProgress: ${INGESTED}/${TARGET_PRODUCTS} (${PERCENT}%) | Queue: ${QUEUE_SIZE}        "
        fi
        
        sleep 5
    done
    
    echo -e "\n${GREEN}✓${NC} Data loading complete!"
else
    echo "Skipping data loading. You can run it later with:"
    echo "  make load-data"
fi

# Step 6: Run health checks
echo -e "\n${YELLOW}[Step 6/6]${NC} Running health checks..."
chmod +x scripts/health_check.sh
./scripts/health_check.sh

# Final summary
echo -e "\n${GREEN}╔═══════════════════════════════════════════════════════════╗"
echo -e "║                    Setup Complete! 🎉                     ║"
echo -e "╚═══════════════════════════════════════════════════════════╝${NC}\n"

echo "Services are running at:"
echo "  📊 Recommendation API: http://localhost:8080/recommend"
echo "  📥 Ingestion API: http://localhost:8001/ingest"
echo "  📈 Prometheus: http://localhost:9091"
echo "  📉 Grafana: http://localhost:3000 (admin/admin)"
echo "  🔧 Metrics: http://localhost:9090"
echo ""

echo "Quick test commands:"
echo "  # Test recommendation"
echo "  curl -X POST http://localhost:8080/recommend \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"query\": \"wireless headphones\", \"top_k\": 5}' | jq"
echo ""

echo "  # Ingest a product"
echo "  curl -X POST http://localhost:8001/ingest \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"product_id\": \"TEST001\", \"title\": \"Test Product\", \"description\": \"Test\", \"category\": \"Test\", \"price\": 99.99}' | jq"
echo ""

echo "Management commands:"
echo "  make logs-prod          # View all logs"
echo "  make down-prod          # Stop all services"
echo "  ./scripts/health_check.sh  # Run health checks"
echo ""

echo -e "${YELLOW}Note:${NC} For Kubernetes deployment, see DEPLOYMENT.md"
echo ""

# Ask if user wants to see a test recommendation
read -p "Would you like to see a test recommendation now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "\n${BLUE}Fetching recommendations for 'wireless bluetooth headphones'...${NC}\n"
    
    curl -s -X POST http://localhost:8080/recommend \
        -H 'Content-Type: application/json' \
        -d '{"query": "wireless bluetooth headphones with noise cancellation", "top_k": 3}' | jq
    
    echo ""
fi

echo -e "${GREEN}Happy coding! 🚀${NC}"