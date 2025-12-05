"""
Optimized Ingestion Service with Database Integration
Removes lazy initialization for better latency and test compatibility
"""
import logging
import uuid
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
import uvicorn

# Add common to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'common'))

from embedding import EmbeddingEngine
from kafka_pub import KafkaPublisher
from database import get_db, close_db, DatabaseManager, ProductDB

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances - initialized at startup, not lazily
embedding_engine: Optional[EmbeddingEngine] = None
kafka_publisher: Optional[KafkaPublisher] = None
db_manager: Optional[DatabaseManager] = None


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events - proper initialization"""
    global embedding_engine, kafka_publisher, db_manager
    
    # Startup
    logger.info("Initializing Ingestion Service...")
    
    try:
        # Initialize database first
        db_manager = await get_db()
        logger.info("Database connected")
        
        # Initialize embedding engine
        embedding_engine = EmbeddingEngine()
        logger.info("Embedding engine initialized")
        
        # Initialize Kafka publisher
        kafka_publisher = KafkaPublisher()
        await kafka_publisher.start()
        logger.info("Kafka publisher started")
        
        # Load initial dataset (async, non-blocking)
        import asyncio
        asyncio.create_task(embedding_engine.load_initial_dataset())
        logger.info("Initial dataset loading started in background")
        
        logger.info("✓ Service ready")
        
    except Exception as e:
        logger.error(f"Failed to initialize service: {e}", exc_info=True)
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    if kafka_publisher:
        await kafka_publisher.stop()
    if db_manager:
        await close_db()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Ingestion & Embedding Service",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Correlation ID Middleware
app.add_middleware(CorrelationIDMiddleware)


# Dependency injection
def get_correlation_id(request: Request) -> str:
    """Extract correlation ID from request state"""
    return getattr(request.state, "correlation_id", str(uuid.uuid4()))


def get_logger(correlation_id: str = Depends(get_correlation_id)):
    """Get logger with correlation ID"""
    return LoggerAdapter(logger, {'correlation_id': correlation_id})


def get_db_dependency() -> DatabaseManager:
    """Get database manager dependency"""
    if db_manager is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return db_manager


# Models
class Product(BaseModel):
    product_id: str
    title: str
    description: str
    category: Optional[str] = None
    price: Optional[float] = None
    brand: Optional[str] = None
    rating: Optional[float] = None
    stock: Optional[int] = None


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
    db_connected: bool


# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    logger.error(f"HTTP error: {exc.detail}", extra={'correlation_id': correlation_id})
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "correlation_id": correlation_id,
            "status_code": exc.status_code
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    correlation_id = getattr(request.state, "correlation_id", "N/A")
    logger.error(f"Unexpected error: {str(exc)}", extra={'correlation_id': correlation_id}, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "correlation_id": correlation_id,
            "status_code": 500
        }
    )


# Endpoints
@app.get("/health", response_model=HealthResponse)
async def health_check(
    db: DatabaseManager = Depends(get_db_dependency),
    log: LoggerAdapter = Depends(get_logger)
):
    """Health check endpoint"""
    log.info("Health check requested")
    
    db_connected = db.pool is not None and not db.pool._closed
    total_products = await db.get_total_products() if db_connected else 0
    
    return {
        "status": "healthy",
        "service": "ingestion",
        "total_products": total_products,
        "db_connected": db_connected
    }


@app.get("/ready")
async def readiness_check(
    db: DatabaseManager = Depends(get_db_dependency),
    log: LoggerAdapter = Depends(get_logger)
):
    """Readiness probe"""
    if not embedding_engine or not embedding_engine.is_ready():
        log.warning("Embedding engine not ready")
        raise HTTPException(status_code=503, detail="Embedding engine not ready")
    
    if not db.pool or db.pool._closed:
        log.warning("Database not ready")
        raise HTTPException(status_code=503, detail="Database not ready")
    
    log.info("Service ready")
    return {"status": "ready"}


@app.post("/ingest", response_model=IngestResponse)
async def ingest_product(
    product: Product,
    correlation_id: str = Depends(get_correlation_id),
    db: DatabaseManager = Depends(get_db_dependency),
    log: LoggerAdapter = Depends(get_logger)
):
    """Ingest a single product"""
    log.info(f"Ingesting product: {product.product_id}")
    
    try:
        # Generate embedding
        text = f"{product.title} {product.description}"
        embedding = await embedding_engine.generate_embedding(text)
        
        # Add to FAISS index
        await embedding_engine.add_product(
            product.product_id,
            embedding,
            product.dict()
        )
        
        # Store in database
        product_db = ProductDB(**product.dict())
        await db.insert_product(product_db)
        
        # Publish to Kafka
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
            "message": "Product ingested successfully"
        }
        
    except Exception as e:
        log.error(f"Failed to ingest product {product.product_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@app.post("/ingest/batch")
async def batch_ingest(
    request: BatchIngestRequest,
    correlation_id: str = Depends(get_correlation_id),
    db: DatabaseManager = Depends(get_db_dependency),
    log: LoggerAdapter = Depends(get_logger)
):
    """Batch ingest products with database persistence"""
    log.info(f"Batch ingesting {len(request.products)} products")
    
    results = {"success": 0, "failed": 0, "errors": []}
    products_to_db = []
    
    for product in request.products:
        try:
            # Generate embedding
            text = f"{product.title} {product.description}"
            embedding = await embedding_engine.generate_embedding(text)
            
            # Add to FAISS
            await embedding_engine.add_product(
                product.product_id,
                embedding,
                product.dict()
            )
            
            # Prepare for DB bulk insert
            products_to_db.append(ProductDB(**product.dict()))
            
            # Publish to Kafka (async, non-blocking)
            if kafka_publisher:
                event = {
                    "event_type": "product_added",
                    "product_id": product.product_id,
                    "correlation_id": correlation_id
                }
                await kafka_publisher.publish("product-events", event)
            
            results["success"] += 1
            
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({
                "product_id": product.product_id,
                "error": str(e)
            })
            log.error(f"Failed to ingest {product.product_id}: {str(e)}")
    
    # Bulk insert to database
    if products_to_db:
        try:
            await db.bulk_insert_products(products_to_db)
        except Exception as e:
            log.error(f"Failed to bulk insert to database: {e}")
    
    log.info(f"Batch complete: {results['success']} success, {results['failed']} failed")
    return results


@app.get("/stats")
async def get_stats(
    db: DatabaseManager = Depends(get_db_dependency),
    log: LoggerAdapter = Depends(get_logger)
):
    """Get service statistics"""
    log.info("Stats requested")
    
    faiss_stats = embedding_engine.get_stats() if embedding_engine else {}
    db_total = await db.get_total_products()
    search_analytics = await db.get_search_analytics()
    
    return {
        **faiss_stats,
        "db_total_products": db_total,
        "search_analytics": search_analytics
    }


if __name__ == "__main__":
    uvicorn.run(
        "main_optimized:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info"
    )