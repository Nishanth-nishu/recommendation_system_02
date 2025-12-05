#!/bin/bash

echo "========================================="
echo "Frontend Troubleshooting Script"
echo "========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check 1: Services Running
echo "1. Checking if services are running..."
if docker ps | grep -q "rec-service\|nginx"; then
    echo -e "${GREEN}✓ Services are running${NC}"
else
    echo -e "${RED}✗ Services are NOT running${NC}"
    echo "  Fix: Run 'docker-compose -f docker-compose.prod.yml up -d'"
    exit 1
fi

# Check 2: Nginx responding
echo ""
echo "2. Testing Nginx (port 8080)..."
if curl -s http://localhost:8080/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Nginx is responding${NC}"
    curl -s http://localhost:8080/health | head -1
else
    echo -e "${YELLOW}⚠ Nginx not responding, trying direct service...${NC}"
fi

# Check 3: Recommendation service
echo ""
echo "3. Testing Recommendation Service (port 8002)..."
if curl -s http://localhost:8002/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Recommendation service is responding${NC}"
    curl -s http://localhost:8002/health | head -1
else
    echo -e "${RED}✗ Recommendation service is NOT responding${NC}"
    echo "  Check logs: docker-compose -f docker-compose.prod.yml logs rec-service"
fi

# Check 4: CORS test
echo ""
echo "4. Testing CORS..."
CORS_HEADER=$(curl -s -I -X OPTIONS http://localhost:8080/recommend \
    -H "Origin: http://localhost" \
    -H "Access-Control-Request-Method: POST" | grep -i "access-control-allow-origin")

if [ -n "$CORS_HEADER" ]; then
    echo -e "${GREEN}✓ CORS is enabled${NC}"
    echo "  $CORS_HEADER"
else
    echo -e "${RED}✗ CORS is NOT enabled${NC}"
    echo "  This will cause frontend errors!"
    echo "  Fix: Services need CORSMiddleware (check main_optimized.py)"
fi

# Check 5: Frontend file
echo ""
echo "5. Checking frontend file..."
if [ -f "frontend/index.html" ]; then
    echo -e "${GREEN}✓ frontend/index.html exists${NC}"
    echo "  Size: $(du -h frontend/index.html | cut -f1)"
elif [ -f "frontend/index_fixed.html" ]; then
    echo -e "${YELLOW}⚠ Using frontend/index_fixed.html${NC}"
    echo "  Rename to index.html: mv frontend/index_fixed.html frontend/index.html"
else
    echo -e "${RED}✗ No frontend file found${NC}"
    echo "  Expected: frontend/index.html"
fi

# Check 6: Test API call
echo ""
echo "6. Testing recommendation API..."
TEST_RESPONSE=$(curl -s -X POST http://localhost:8080/recommend \
    -H "Content-Type: application/json" \
    -d '{"query":"test","top_k":1}')

if echo "$TEST_RESPONSE" | grep -q "recommendations"; then
    echo -e "${GREEN}✓ API is working${NC}"
    echo "  Response: $(echo $TEST_RESPONSE | head -c 100)..."
else
    echo -e "${RED}✗ API returned error${NC}"
    echo "  Response: $TEST_RESPONSE"
fi

# Recommendations
echo ""
echo "========================================="
echo "RECOMMENDATIONS"
echo "========================================="
echo ""
echo "How to open frontend:"
echo "  Option 1: Open frontend/index.html directly in browser"
echo "  Option 2: python3 -m http.server 8000 -d frontend"
echo "            Then visit: http://localhost:8000"
echo ""
echo "Common issues:"
echo "  1. Blank page: Open browser console (F12) to see errors"
echo "  2. CORS errors: Services need to be rebuilt with CORS enabled"
echo "  3. Connection failed: Services not running or wrong port"
echo ""
echo "Quick fixes:"
echo "  # Restart services with CORS"
echo "  docker-compose -f docker-compose.prod.yml restart"
echo ""
echo "  # View logs"
echo "  docker-compose -f docker-compose.prod.yml logs -f rec-service"
echo ""
echo "  # Use fixed frontend"
echo "  cp frontend/index_fixed.html frontend/index.html"
echo ""