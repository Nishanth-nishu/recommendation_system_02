"""
Recommendation Service
Provides semantic product recommendations using FAISS
"""
import logging
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from retrieval import RetrievalEngine
from middleware import CorrelationIDMiddleware
from exceptions import RecommendationException

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances
retrieval_engine: Optional[RetrievalEngine] = None


class LoggerAdapter(logging.LoggerAdapter):
    """Add correlation ID to all log messages"""
    def process(self, msg, kwargs):
        return msg, {**kwargs, 'extra': {'correlation_id': self.extra.get('correlation_id', 'N/A')}}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global retrieval_engine
    
    # Startup
    logger.info("Initializing Recommendation Service...")
    retrieval_engine = RetrievalEngine()
    await retrieval_engine.initialize()
    logger.info("Service ready")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")


app = FastAPI(
    title="Recommendation Service",
    version="1.0.0",
    lifespan=lifespan
)

# Add middleware
app.add_middleware(CorrelationIDMiddleware)


# Dependency injection
def get_correlation_id(request: Request) -> str:
    """Get correlation ID from request state"""
    return getattr(request.state, 'correlation_id', 'N/A')


def get_logger(correlation_id: str = Depends(get_correlation_id)):
    """Get logger with correlation ID"""
    return LoggerAdapter(logger, {'correlation_id': correlation_id})


# Models
class RecommendationRequest(BaseModel):
    query: str = Field(..., description="Search query or product description")
    top_k: int = Field(5, ge=1, le=50, description="Number of recommendations")
    filters: Optional[dict] = Field(None, description="Optional filters (e.g., category, price range)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "wireless bluetooth headphones with noise cancellation",
                "top_k": 5,
                "filters": {"category": "Electronics"}
            }
        }


class ProductRecommendation(BaseModel):
    product_id: str
    title: str
    description: str
    category: Optional[str]
    price: Optional[float]
    score: float
    distance: float


class RecommendationResponse(BaseModel):
    recommendations: List[ProductRecommendation]
    query: str
    total_results: int
    correlation_id: str


class HealthResponse(BaseModel):
    status: str
    service: str
    index_size: int


# Error handlers
@app.exception_handler(RecommendationException)
async def recommendation_exception_handler(request: Request, exc: RecommendationException):
    correlation_id = get_correlation_id(request)
    logger.error(f"Recommendation error: {exc.message}", extra={'correlation_id': correlation_id})
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.message,
            "correlation_id": correlation_id,
            "status_code": exc.status_code
        }
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    correlation_id = get_correlation_id(request)
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
async def general_exception_handler(request: Request, exc: Exception):
    correlation_id = get_correlation_id(request)
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
    log: LoggerAdapter = Depends(get_logger)
):
    """Health check endpoint for K8s liveness probe"""
    log.info("Health check requested")
    return {
        "status": "healthy",
        "service": "recommendation",
        "index_size": retrieval_engine.get_index_size()
    }


@app.get("/ready")
async def readiness_check(
    log: LoggerAdapter = Depends(get_logger)
):
    """Readiness probe - checks if retrieval engine is ready"""
    if not retrieval_engine or not retrieval_engine.is_ready():
        log.warning("Service not ready")
        raise HTTPException(status_code=503, detail="Service not ready")
    
    log.info("Service ready")
    return {"status": "ready", "index_size": retrieval_engine.get_index_size()}


@app.post("/recommend", response_model=RecommendationResponse)
async def get_recommendations(
    request: RecommendationRequest,
    req: Request,
    log: LoggerAdapter = Depends(get_logger)
):
    """
    Get product recommendations based on semantic search
    
    Returns top-k most similar products to the query
    """
    correlation_id = get_correlation_id(req)
    log.info(f"Recommendation request: query='{request.query}', top_k={request.top_k}")
    
    try:
        # Generate query embedding
        query_embedding = await retrieval_engine.generate_query_embedding(request.query)
        
        # Search for similar products
        results = await retrieval_engine.search(
            query_embedding,
            top_k=request.top_k,
            filters=request.filters
        )
        
        # Convert to response format
        recommendations = [
            ProductRecommendation(**result) for result in results
        ]
        
        log.info(f"Returning {len(recommendations)} recommendations")
        
        return RecommendationResponse(
            recommendations=recommendations,
            query=request.query,
            total_results=len(recommendations),
            correlation_id=correlation_id
        )
        
    except RecommendationException:
        raise
    except Exception as e:
        log.error(f"Recommendation failed: {str(e)}")
        raise RecommendationException(
            message=f"Failed to generate recommendations: {str(e)}",
            status_code=500
        )


@app.get("/recommend/product/{product_id}")
async def get_similar_products(
    product_id: str,
    top_k: int = 5,
    req: Request = None,
    log: LoggerAdapter = Depends(get_logger)
):
    """Get similar products based on a product ID"""
    correlation_id = get_correlation_id(req)
    log.info(f"Similar products request for: {product_id}")
    
    try:
        results = await retrieval_engine.find_similar_products(product_id, top_k)
        
        recommendations = [
            ProductRecommendation(**result) for result in results
        ]
        
        return RecommendationResponse(
            recommendations=recommendations,
            query=f"Similar to {product_id}",
            total_results=len(recommendations),
            correlation_id=correlation_id
        )
        
    except RecommendationException:
        raise
    except Exception as e:
        log.error(f"Similar products search failed: {str(e)}")
        raise RecommendationException(
            message=f"Failed to find similar products: {str(e)}",
            status_code=500
        )


@app.get("/stats")
async def get_stats(
    log: LoggerAdapter = Depends(get_logger)
):
    """Get retrieval engine statistics"""
    log.info("Stats requested")
    stats = retrieval_engine.get_stats()
    return stats


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8002,
        reload=False,
        log_level="info"
    )