"""
Ingestion + Embedding Service
Handles dataset ingestion, embedding generation, and Kafka event publishing
"""
import logging
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import uvicorn

from embedding import EmbeddingEngine
from kafka_pub import KafkaPublisher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances
embedding_engine: Optional[EmbeddingEngine] = None
kafka_publisher: Optional[KafkaPublisher] = None

class LoggerAdapter(logging.LoggerAdapter):
    """Add correlation ID to all log messages"""
    def process(self, msg, kwargs):
        return msg, {**kwargs, 'extra': {'correlation_id': self.extra.get('correlation_id', 'N/A')}}

class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Middleware to extract or generate correlation IDs"""
    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["x-correlation-id"] = correlation_id
        return response

# --- HELPER: Ensure Initialization ---
async def ensure_initialized():
    """Lazy load resources if lifespan didn't run"""
    global embedding_engine, kafka_publisher
    if embedding_engine is None:
        logger.info("Lazy initializing resources...")
        embedding_engine = EmbeddingEngine()
        kafka_publisher = KafkaPublisher()
        await kafka_publisher.start()
        await embedding_engine.load_initial_dataset()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    await ensure_initialized()
    logger.info("Service ready")
    yield
    logger.info("Shutting down...")
    if kafka_publisher:
        await kafka_publisher.stop()

app = FastAPI(
    title="Ingestion & Embedding Service",
    version="1.0.0",
    lifespan=lifespan
)

# Add Middleware
app.add_middleware(CorrelationIDMiddleware)

# Dependency injection
def get_correlation_id(request: Request) -> str:
    """Extract correlation ID from request state"""
    return getattr(request.state, "correlation_id", str(uuid.uuid4()))

def get_logger(correlation_id: str = Depends(get_correlation_id)):
    """Get logger with correlation ID"""
    return LoggerAdapter(logger, {'correlation_id': correlation_id})

# Models
class Product(BaseModel):
    product_id: str
    title: str
    description: str
    category: Optional[str] = None
    price: Optional[float] = None

class BatchIngestRequest(BaseModel):
    products: List[Product]

class IngestResponse(BaseModel):
    success: bool
    product_id: str
    message: str

class HealthResponse(BaseModel):
    status: str
    service: str
    total_products: int

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    logger.error(f"HTTP error: {exc.detail}", extra={'correlation_id': correlation_id})
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "correlation_id": correlation_id, "status_code": exc.status_code}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    logger.error(f"Unexpected error: {str(exc)}", extra={'correlation_id': correlation_id}, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "correlation_id": correlation_id, "status_code": 500}
    )

# Endpoints
@app.get("/health", response_model=HealthResponse)
async def health_check(log: LoggerAdapter = Depends(get_logger)):
    await ensure_initialized()
    return {
        "status": "healthy",
        "service": "ingestion",
        "total_products": embedding_engine.get_total_products() if embedding_engine else 0
    }

@app.get("/ready")
async def readiness_check(log: LoggerAdapter = Depends(get_logger)):
    await ensure_initialized()
    if not embedding_engine or not embedding_engine.is_ready():
        raise HTTPException(status_code=503, detail="Service not ready")
    return {"status": "ready"}

@app.post("/ingest", response_model=IngestResponse)
async def ingest_product(
    product: Product,
    correlation_id: str = Depends(get_correlation_id),
    log: LoggerAdapter = Depends(get_logger)
):
    await ensure_initialized()
    log.info(f"Ingesting product: {product.product_id}")
    try:
        text = f"{product.title} {product.description}"
        if embedding_engine:
            embedding = await embedding_engine.generate_embedding(text)
            await embedding_engine.add_product(product.product_id, embedding, product.dict())
        
        if kafka_publisher:
            event = {
                "event_type": "product_added",
                "product_id": product.product_id,
                "correlation_id": correlation_id,
                "metadata": product.dict()
            }
            await kafka_publisher.publish("product-events", event)
        
        log.info(f"Successfully ingested product: {product.product_id}")
        return {
            "success": True,
            "product_id": product.product_id,
            "message": "Product ingested and indexed successfully"
        }
    except Exception as e:
        log.error(f"Failed to ingest product {product.product_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")

@app.post("/ingest/batch")
async def batch_ingest(
    request: BatchIngestRequest,
    correlation_id: str = Depends(get_correlation_id),
    log: LoggerAdapter = Depends(get_logger)
):
    await ensure_initialized()
    log.info(f"Batch ingesting {len(request.products)} products")
    results = {"success": 0, "failed": 0, "errors": []}
    for product in request.products:
        try:
            if embedding_engine:
                text = f"{product.title} {product.description}"
                embedding = await embedding_engine.generate_embedding(text)
                await embedding_engine.add_product(product.product_id, embedding, product.dict())
            if kafka_publisher:
                event = {"event_type": "product_added", "product_id": product.product_id, "correlation_id": correlation_id}
                await kafka_publisher.publish("product-events", event)
            results["success"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"product_id": product.product_id, "error": str(e)})
            log.error(f"Failed to ingest {product.product_id}: {str(e)}")
    log.info(f"Batch ingest complete: {results['success']} success, {results['failed']} failed")
    return results

@app.get("/stats")
async def get_stats(log: LoggerAdapter = Depends(get_logger)):
    await ensure_initialized()
    if embedding_engine:
        return embedding_engine.get_stats()
    return {"status": "not_ready"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False, log_level="info")