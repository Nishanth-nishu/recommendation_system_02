#!/bin/bash

# Health Check Script for Semantic Recommendation System
# Checks all components and reports status

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
INGEST_URL="${INGEST_URL:-http://localhost:8001}"
REC_URL="${REC_URL:-http://localhost:8002}"
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
KAFKA_HOST="${KAFKA_HOST:-localhost}"
KAFKA_PORT="${KAFKA_PORT:-9092}"

# Helper functions
print_header() {
    echo -e "\n${YELLOW}=== $1 ===${NC}"
}

check_service() {
    local name=$1
    local url=$2
    
    if curl -sf "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} $name is healthy"
        return 0
    else
        echo -e "${RED}✗${NC} $name is not responding"
        return 1
    fi
}

check_port() {
    local name=$1
    local host=$2
    local port=$3
    
    if nc -z "$host" "$port" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $name is listening on $host:$port"
        return 0
    else
        echo -e "${RED}✗${NC} $name is not reachable on $host:$port"
        return 1
    fi
}

# Main checks
print_header "Service Health Checks"

# Check Ingestion Service
check_service "Ingestion Service" "$INGEST_URL/health"
INGEST_STATUS=$?

if [ $INGEST_STATUS -eq 0 ]; then
    # Get stats
    STATS=$(curl -s "$INGEST_URL/stats")
    TOTAL_PRODUCTS=$(echo "$STATS" | grep -o '"total_products":[0-9]*' | cut -d':' -f2)
    echo "  Products in index: $TOTAL_PRODUCTS"
fi

# Check Recommendation Service
check_service "Recommendation Service" "$REC_URL/health"
REC_STATUS=$?

if [ $REC_STATUS -eq 0 ]; then
    # Get stats
    STATS=$(curl -s "$REC_URL/stats")
    INDEX_SIZE=$(echo "$STATS" | grep -o '"index_size":[0-9]*' | cut -d':' -f2)
    echo "  Index size: $INDEX_SIZE"
fi

# Check Readiness
print_header "Readiness Checks"

if curl -sf "$INGEST_URL/ready" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Ingestion Service is ready"
else
    echo -e "${YELLOW}⚠${NC} Ingestion Service is not ready"
fi

if curl -sf "$REC_URL/ready" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Recommendation Service is ready"
else
    echo -e "${YELLOW}⚠${NC} Recommendation Service is not ready"
fi

# Check Infrastructure
print_header "Infrastructure Checks"

# Redis
if command -v redis-cli &> /dev/null; then
    if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Redis is responding"
        
        # Check queue size
        QUEUE_SIZE=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ZCARD product_ingestion 2>/dev/null || echo "0")
        DLQ_SIZE=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" LLEN product_ingestion:dlq 2>/dev/null || echo "0")
        echo "  Queue size: $QUEUE_SIZE"
        echo "  DLQ size: $DLQ_SIZE"
    else
        echo -e "${RED}✗${NC} Redis is not responding"
    fi
else
    check_port "Redis" "$REDIS_HOST" "$REDIS_PORT"
fi

# Kafka
if command -v kafka-topics &> /dev/null; then
    if kafka-topics --bootstrap-server "$KAFKA_HOST:$KAFKA_PORT" --list > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Kafka is responding"
    else
        echo -e "${RED}✗${NC} Kafka is not responding"
    fi
else
    check_port "Kafka" "$KAFKA_HOST" "$KAFKA_PORT"
fi

# Check Docker containers (if running in Docker)
if command -v docker &> /dev/null; then
    print_header "Docker Container Status"
    
    if docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(ingest|rec|redis|kafka)" > /dev/null 2>&1; then
        docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(ingest|rec|redis|kafka|nginx|prometheus)"
    else
        echo "No containers found. Not running in Docker mode."
    fi
fi

# Functional Tests
print_header "Functional Tests"

# Test ingestion
echo -n "Testing product ingestion... "
INGEST_RESPONSE=$(curl -s -X POST "$INGEST_URL/ingest" \
    -H "Content-Type: application/json" \
    -H "x-correlation-id: health-check-$(date +%s)" \
    -d '{
        "product_id": "HEALTH_CHECK_001",
        "title": "Health Check Product",
        "description": "This is a health check test product",
        "category": "Test",
        "price": 9.99
    }')

if echo "$INGEST_RESPONSE" | grep -q '"success":true'; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
    echo "Response: $INGEST_RESPONSE"
fi

# Test recommendation
echo -n "Testing recommendations... "
REC_RESPONSE=$(curl -s -X POST "$REC_URL/recommend" \
    -H "Content-Type: application/json" \
    -H "x-correlation-id: health-check-$(date +%s)" \
    -d '{
        "query": "health check test",
        "top_k": 3
    }')

if echo "$REC_RESPONSE" | grep -q '"recommendations"'; then
    REC_COUNT=$(echo "$REC_RESPONSE" | grep -o '"total_results":[0-9]*' | cut -d':' -f2)
    echo -e "${GREEN}✓${NC} (returned $REC_COUNT results)"
else
    echo -e "${RED}✗${NC}"
    echo "Response: $REC_RESPONSE"
fi

# Summary
print_header "Summary"

TOTAL_CHECKS=2
PASSED_CHECKS=0

if [ $INGEST_STATUS -eq 0 ]; then
    ((PASSED_CHECKS++))
fi

if [ $REC_STATUS -eq 0 ]; then
    ((PASSED_CHECKS++))
fi

echo "Passed: $PASSED_CHECKS/$TOTAL_CHECKS critical checks"

if [ $PASSED_CHECKS -eq $TOTAL_CHECKS ]; then
    echo -e "${GREEN}System is healthy!${NC}"
    exit 0
else
    echo -e "${RED}System has issues that need attention${NC}"
    exit 1
fi