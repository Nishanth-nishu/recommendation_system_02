"""
Tests for Ingestion Service
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
from httpx import AsyncClient

# Mock the dependencies before importing
@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mock all external dependencies"""
    with patch('embedding.SentenceTransformer') as mock_st, \
         patch('embedding.faiss') as mock_faiss, \
         patch('kafka_pub.AIOKafkaProducer') as mock_kafka:
        
        # Setup SentenceTransformer mock
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        mock_model.encode.return_value = np.random.rand(384)
        mock_st.return_value = mock_model
        
        # Setup FAISS mock
        mock_index = MagicMock()
        mock_index.ntotal = 1000
        mock_faiss.IndexFlatL2.return_value = mock_index
        mock_faiss.read_index.return_value = mock_index
        
        # Setup Kafka mock
        mock_producer = AsyncMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()
        mock_kafka.return_value = mock_producer
        
        yield {
            'model': mock_model,
            'index': mock_index,
            'producer': mock_producer
        }


@pytest.fixture
async def client(mock_dependencies):
    """Create test client"""
    # Import after mocking
    import sys
    sys.path.insert(0, '../ingest_service')
    
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
    assert data["service"] == "ingestion"
    assert "total_products" in data


@pytest.mark.asyncio
async def test_ready_endpoint(client):
    """Test readiness probe endpoint"""
    response = await client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"


@pytest.mark.asyncio
async def test_ingest_product(client, mock_dependencies):
    """Test product ingestion"""
    product = {
        "product_id": "TEST001",
        "title": "Test Wireless Headphones",
        "description": "Premium noise-cancelling headphones",
        "category": "Electronics",
        "price": 99.99
    }
    
    response = await client.post("/ingest", json=product)
    assert response.status_code == 200
    
    data = response.json()
    assert data["success"] is True
    assert data["product_id"] == "TEST001"
    assert "message" in data


@pytest.mark.asyncio
async def test_ingest_product_with_correlation_id(client):
    """Test product ingestion with correlation ID tracking"""
    product = {
        "product_id": "TEST002",
        "title": "Test Smart Watch",
        "description": "Fitness tracking smartwatch",
        "category": "Electronics",
        "price": 149.99
    }
    
    correlation_id = "test-correlation-123"
    headers = {"x-correlation-id": correlation_id}
    
    response = await client.post("/ingest", json=product, headers=headers)
    assert response.status_code == 200
    assert response.headers.get("x-correlation-id") == correlation_id


@pytest.mark.asyncio
async def test_batch_ingest(client):
    """Test batch product ingestion"""
    products = [
        {
            "product_id": f"BATCH{i:03d}",
            "title": f"Batch Product {i}",
            "description": f"Description for product {i}",
            "category": "Electronics",
            "price": 50.0 + i
        }
        for i in range(5)
    ]
    
    response = await client.post("/ingest/batch", json={"products": products})
    assert response.status_code == 200
    
    data = response.json()
    assert data["success"] == 5
    assert data["failed"] == 0


@pytest.mark.asyncio
async def test_get_stats(client):
    """Test statistics endpoint"""
    response = await client.get("/stats")
    assert response.status_code == 200
    
    data = response.json()
    assert "total_products" in data
    assert "embedding_dimension" in data
    assert "model" in data


@pytest.mark.asyncio
async def test_ingest_invalid_product(client):
    """Test ingestion with invalid product data"""
    invalid_product = {
        "product_id": "INVALID",
        # Missing required fields
    }
    
    response = await client.post("/ingest", json=invalid_product)
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_correlation_id_generation(client):
    """Test automatic correlation ID generation"""
    product = {
        "product_id": "TEST003",
        "title": "Test Product",
        "description": "Test description",
        "category": "Test",
        "price": 10.0
    }
    
    response = await client.post("/ingest", json=product)
    assert response.status_code == 200
    
    # Should have generated a correlation ID
    assert "x-correlation-id" in response.headers


# Unit tests for EmbeddingEngine
@pytest.mark.asyncio
async def test_embedding_generation(mock_dependencies):
    """Test embedding generation"""
    from embedding import EmbeddingEngine
    
    engine = EmbeddingEngine()
    text = "Test product description"
    
    embedding = await engine.generate_embedding(text)
    
    assert isinstance(embedding, np.ndarray)
    assert embedding.shape[0] == 384  # Mocked dimension


@pytest.mark.asyncio
async def test_add_product_to_index(mock_dependencies):
    """Test adding product to FAISS index"""
    from embedding import EmbeddingEngine
    
    engine = EmbeddingEngine()
    
    product_id = "TEST001"
    embedding = np.random.rand(384)
    metadata = {"title": "Test", "description": "Test product"}
    
    await engine.add_product(product_id, embedding, metadata)
    
    assert product_id in engine.product_id_to_idx


# Unit tests for KafkaPublisher
@pytest.mark.asyncio
async def test_kafka_publish(mock_dependencies):
    """Test Kafka event publishing"""
    from kafka_pub import KafkaPublisher
    
    publisher = KafkaPublisher()
    await publisher.start()
    
    event = {
        "event_type": "product_added",
        "product_id": "TEST001",
        "correlation_id": "test-123"
    }
    
    result = await publisher.publish("test-topic", event)
    
    assert result is True
    mock_dependencies['producer'].send_and_wait.assert_called_once()


@pytest.mark.asyncio
async def test_kafka_batch_publish(mock_dependencies):
    """Test Kafka batch publishing"""
    from kafka_pub import KafkaPublisher
    
    publisher = KafkaPublisher()
    await publisher.start()
    
    events = [
        {"event_type": "test", "product_id": f"TEST{i}"}
        for i in range(3)
    ]
    
    result = await publisher.publish_batch("test-topic", events)
    
    assert result is True