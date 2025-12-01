"""
Tests for Recommendation Service
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mock all external dependencies"""
    with patch('retrieval.SentenceTransformer') as mock_st, \
         patch('retrieval.faiss') as mock_faiss, \
         patch('retrieval.Path') as mock_path:
        
        # Setup SentenceTransformer mock
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_model.encode.return_value = np.random.rand(384)
        mock_st.return_value = mock_model
        
        # Setup FAISS mock
        mock_index = MagicMock()
        mock_index.ntotal = 1000
        mock_index.search.return_value = (
            np.array([[0.1, 0.2, 0.3, 0.4, 0.5]]),
            np.array([[0, 1, 2, 3, 4]])
        )
        mock_index.reconstruct.return_value = np.random.rand(384)
        mock_faiss.IndexFlatL2.return_value = mock_index
        mock_faiss.read_index.return_value = mock_index
        
        # Setup Path mock for file existence
        mock_path_inst = MagicMock()
        mock_path_inst.exists.return_value = True
        mock_path_inst.parent.mkdir = MagicMock()
        mock_path.return_value = mock_path_inst
        
        yield {
            'model': mock_model,
            'index': mock_index
        }


@pytest.fixture
async def client(mock_dependencies):
    """Create test client"""
    import sys
    sys.path.insert(0, '../rec_service')
    
    # Mock pickle loading
    with patch('builtins.open', create=True) as mock_open:
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file
        
        with patch('pickle.load') as mock_pickle:
            mock_pickle.return_value = {
                'metadata': {
                    0: {'title': 'Product 0', 'description': 'Desc 0', 'category': 'Electronics', 'price': 99.99},
                    1: {'title': 'Product 1', 'description': 'Desc 1', 'category': 'Electronics', 'price': 149.99},
                    2: {'title': 'Product 2', 'description': 'Desc 2', 'category': 'Clothing', 'price': 29.99},
                    3: {'title': 'Product 3', 'description': 'Desc 3', 'category': 'Electronics', 'price': 199.99},
                    4: {'title': 'Product 4', 'description': 'Desc 4', 'category': 'Books', 'price': 19.99}
                },
                'product_id_to_idx': {
                    'P000000': 0,
                    'P000001': 1,
                    'P000002': 2,
                    'P000003': 3,
                    'P000004': 4
                },
                'idx_to_product_id': {
                    0: 'P000000',
                    1: 'P000001',
                    2: 'P000002',
                    3: 'P000003',
                    4: 'P000004'
                },
                'next_idx': 5
            }
            
            from main import app
            
            async with AsyncClient(app=app, base_url="http://test") as ac:
                yield ac


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Test health check endpoint"""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "recommendation"
    assert "index_size" in data


@pytest.mark.asyncio
async def test_ready_endpoint(client):
    """Test readiness probe endpoint"""
    response = await client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"


@pytest.mark.asyncio
async def test_get_recommendations(client):
    """Test recommendation endpoint"""
    request_data = {
        "query": "wireless bluetooth headphones",
        "top_k": 5
    }
    
    response = await client.post("/recommend", json=request_data)
    assert response.status_code == 200
    
    data = response.json()
    assert "recommendations" in data
    assert "query" in data
    assert "total_results" in data
    assert "correlation_id" in data
    assert data["query"] == request_data["query"]
    assert len(data["recommendations"]) <= 5


@pytest.mark.asyncio
async def test_recommendations_structure(client):
    """Test recommendation response structure"""
    request_data = {
        "query": "laptop computer",
        "top_k": 3
    }
    
    response = await client.post("/recommend", json=request_data)
    assert response.status_code == 200
    
    data = response.json()
    recommendations = data["recommendations"]
    
    if recommendations:
        rec = recommendations[0]
        assert "product_id" in rec
        assert "title" in rec
        assert "description" in rec
        assert "score" in rec
        assert "distance" in rec
        assert isinstance(rec["score"], float)
        assert isinstance(rec["distance"], float)


@pytest.mark.asyncio
async def test_recommendations_with_filters(client):
    """Test recommendations with category filter"""
    request_data = {
        "query": "electronics device",
        "top_k": 5,
        "filters": {"category": "Electronics"}
    }
    
    response = await client.post("/recommend", json=request_data)
    assert response.status_code == 200
    
    data = response.json()
    assert "recommendations" in data
    
    # All results should be Electronics
    for rec in data["recommendations"]:
        if rec.get("category"):
            assert rec["category"] == "Electronics"


@pytest.mark.asyncio
async def test_recommendations_correlation_id(client):
    """Test correlation ID tracking"""
    request_data = {
        "query": "test query",
        "top_k": 5
    }
    
    correlation_id = "test-correlation-456"
    headers = {"x-correlation-id": correlation_id}
    
    response = await client.post("/recommend", json=request_data, headers=headers)
    assert response.status_code == 200
    
    data = response.json()
    assert data["correlation_id"] == correlation_id
    assert response.headers.get("x-correlation-id") == correlation_id


@pytest.mark.asyncio
async def test_similar_products(client):
    """Test finding similar products"""
    product_id = "P000000"
    
    response = await client.get(f"/recommend/product/{product_id}?top_k=5")
    assert response.status_code == 200
    
    data = response.json()
    assert "recommendations" in data
    assert "correlation_id" in data
    
    # Original product should not be in results
    for rec in data["recommendations"]:
        assert rec["product_id"] != product_id


@pytest.mark.asyncio
async def test_similar_products_not_found(client):
    """Test similar products with non-existent product"""
    product_id = "NONEXISTENT"
    
    response = await client.get(f"/recommend/product/{product_id}")
    assert response.status_code == 404
    
    data = response.json()
    assert "error" in data


@pytest.mark.asyncio
async def test_empty_query(client):
    """Test recommendation with empty query"""
    request_data = {
        "query": "",
        "top_k": 5
    }
    
    response = await client.post("/recommend", json=request_data)
    # Should return 400 or 500 depending on validation
    assert response.status_code in [400, 500]


@pytest.mark.asyncio
async def test_invalid_top_k(client):
    """Test recommendation with invalid top_k"""
    request_data = {
        "query": "test",
        "top_k": 100  # Exceeds maximum
    }
    
    response = await client.post("/recommend", json=request_data)
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_get_stats(client):
    """Test statistics endpoint"""
    response = await client.get("/stats")
    assert response.status_code == 200
    
    data = response.json()
    assert "index_size" in data
    assert "model" in data
    assert "ready" in data


# Unit tests for RetrievalEngine
@pytest.mark.asyncio
async def test_query_embedding_generation(mock_dependencies):
    """Test query embedding generation"""
    with patch('builtins.open', create=True), \
         patch('pickle.load') as mock_pickle:
        
        mock_pickle.return_value = {
            'metadata': {},
            'product_id_to_idx': {},
            'idx_to_product_id': {},
            'next_idx': 0
        }
        
        from retrieval import RetrievalEngine
        
        engine = RetrievalEngine()
        await engine.initialize()
        
        query = "test product search"
        embedding = await engine.generate_query_embedding(query)
        
        assert isinstance(embedding, np.ndarray)
        assert embedding.shape[0] == 384


@pytest.mark.asyncio
async def test_search_with_filters(mock_dependencies):
    """Test search with category filter"""
    with patch('builtins.open', create=True), \
         patch('pickle.load') as mock_pickle:
        
        mock_pickle.return_value = {
            'metadata': {
                0: {'category': 'Electronics', 'title': 'Test', 'description': 'Desc'},
                1: {'category': 'Books', 'title': 'Test2', 'description': 'Desc2'}
            },
            'product_id_to_idx': {'P1': 0, 'P2': 1},
            'idx_to_product_id': {0: 'P1', 1: 'P2'},
            'next_idx': 2
        }
        
        from retrieval import RetrievalEngine
        
        engine = RetrievalEngine()
        await engine.initialize()
        
        query_embedding = np.random.rand(384)
        results = await engine.search(
            query_embedding,
            top_k=5,
            filters={'category': 'Electronics'}
        )
        
        # All results should match filter
        for result in results:
            if result.get('category'):
                assert result['category'] == 'Electronics'


@pytest.mark.asyncio
async def test_middleware_correlation_id():
    """Test correlation ID middleware"""
    from middleware import CorrelationIDMiddleware
    from fastapi import FastAPI, Request
    from starlette.responses import Response
    
    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)
    
    @app.get("/test")
    async def test_endpoint(request: Request):
        correlation_id = getattr(request.state, 'correlation_id', None)
        return {"correlation_id": correlation_id}
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # Test with correlation ID
        response = await ac.get("/test", headers={"x-correlation-id": "test-123"})
        assert response.json()["correlation_id"] == "test-123"
        assert response.headers.get("x-correlation-id") == "test-123"
        
        # Test without correlation ID (should generate one)
        response = await ac.get("/test")
        assert response.json()["correlation_id"] is not None
        assert response.headers.get("x-correlation-id") is not None