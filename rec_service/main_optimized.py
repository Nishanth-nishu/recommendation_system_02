"""
Optimized Recommendation Service with Caching and Database
Uses Redis for response caching to reduce latency
"""
import logging
import uuid
import sys
import hashlib
import json
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional
import time

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import redis.asyncio as aioredis

# Add common to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'common'))

from retrieval import RetrievalEngine
from middleware import CorrelationIDMiddleware
from exceptions import RecommendationException
from database import get_db, close_db, DatabaseManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances
retrieval_engine: Optional[RetrievalEngine] = None
db_manager: Optional[DatabaseManager] = None
redis_client: Optional[aioredis.Redis] = None


class LoggerAdapter(logging.LoggerAdapter):
    """Add correlation ID to all log messages"""
    def process(self, msg, kwargs):
        return msg, {**kwargs, 'extra': {'correlation_id': self.extra.get('correlation_id', 'N/A')}}


class ResponseCache:
    """Redis-based response cache for reduced latency"""
    
    def __init__(self, redis_client: aioredis.Redis, ttl: int = 300):
        self.redis = redis_client
        self.ttl = ttl  # 5 minutes default
    
    def _generate_key(self, query: str, top_k: int, filters: dict) -> str:
        """Generate cache key from request parameters"""
        cache_data = {
            "query": query,
            "top_k": top_k,
            "filters": filters
        }
        cache_str = json.dumps(cache_data, sort_keys=True)
        return f"rec:{hashlib.md5(cache_str.encode()).hexdigest()}"
    
    async def get(self, query: str, top_k: int, filters: dict) -> Optional[dict]:
        """Get cached response"""
        if not self.redis:
            return None
        
        try:
            key = self._generate_key(query, top_k, filters)
            cached = await self.redis.get(key)
            
            if cached:
                logger.debug(f"Cache hit for key: {key[:16]}...")
                return json.loads(cached)
            
        except Exception as e:
            logger.warning(f"Cache get failed: {e}")
        
        return None
    
    async def set(self, query: str, top_k: int, filters: dict, response: dict):
        """Cache response"""
        if not self.redis:
            return
        
        try:
            key = self._generate_key(query, top_k, filters)
            await self.redis.setex(
                key,
                self.ttl,
                json.dumps(response)
            )
            logger.debug(f"Cached response for key: {key[:16]}...")
            
        except Exception as e:
            logger.warning(f"Cache set failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global retrieval_engine, db_manager, redis_client
    
    # Startup
    logger.info("Initializing Recommendation Service...")
    
    try:
        # Initialize database
        db_manager = await get_db()
        logger.info("Database connected")
        
        # Initialize Redis for caching
        try:
            redis_client = await aioredis.from_url(
                "redis://localhost:6379",
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5
            )
            await redis_client.ping()
            logger.info("Redis cache connected")
        except Exception as e:
            logger.warning(f"Redis not available, caching disabled: {e}")
            redis_client = None
        
        # Initialize retrieval engine
        retrieval_engine = RetrievalEngine()
        await retrieval_engine.initialize()
        logger.info("Retrieval engine initialized")
        
        logger.info("✓ Service ready")
        
    except Exception as e:
        logger.error(f"Failed to initialize service: {e}", exc_info=True)
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    if redis_client:
        await redis_client.close()
    if db_manager:
        await close_db()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Recommendation Service",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add middleware
app.add_middleware(CorrelationIDMiddleware)

# Response cache instance
response_cache: Optional[ResponseCache] = None


# Dependency injection
def get_correlation_id(request: Request) -> str:
    """Get correlation ID from request state"""
    return getattr(request.state, 'correlation_id', 'N/A')


def get_logger(correlation_id: str = Depends(get_correlation_id)):
    """Get logger with correlation ID"""
    return LoggerAdapter(logger, {'correlation_id': correlation_id})


def get_db_dependency() -> DatabaseManager:
    """Get database manager dependency"""
    if db_manager is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    return db_manager


def get_cache() -> Optional[ResponseCache]:
    """Get response cache"""
    global response_cache
    if response_cache is None and redis_client:
        response_cache = ResponseCache(redis_client)
    return response_cache


# Models
class RecommendationRequest(BaseModel):
    query: str = Field(..., description="Search query or product description")
    top_k: int = Field(5, ge=1, le=50, description="Number of recommendations")
    filters: Optional[dict] = Field(default_factory=dict, description="Optional filters")


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
    latency_ms: Optional[float] = None
    from_cache: bool = False


class HealthResponse(BaseModel):
    status: str
    service: str
    index_size: int
    cache_enabled: bool


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
async def health_check(log: LoggerAdapter = Depends(get_logger)):
    """Health check endpoint"""
    log.info("Health check requested")
    
    return {
        "status": "healthy",
        "service": "recommendation",
        "index_size": retrieval_engine.get_index_size() if retrieval_engine else 0,
        "cache_enabled": redis_client is not None
    }


@app.get("/ready")
async def readiness_check(log: LoggerAdapter = Depends(get_logger)):
    """Readiness probe"""
    if not retrieval_engine or not retrieval_engine.is_ready():
        log.warning("Service not ready")
        raise HTTPException(status_code=503, detail="Service not ready")
    
    log.info("Service ready")
    return {"status": "ready", "index_size": retrieval_engine.get_index_size()}


@app.post("/recommend", response_model=RecommendationResponse)
async def get_recommendations(
    request: RecommendationRequest,
    req: Request,
    db: DatabaseManager = Depends(get_db_dependency),
    cache: Optional[ResponseCache] = Depends(get_cache),
    log: LoggerAdapter = Depends(get_logger)
):
    """Get product recommendations with caching"""
    correlation_id = get_correlation_id(req)
    start_time = time.time()
    
    log.info(f"Recommendation request: query='{request.query}', top_k={request.top_k}")
    
    # Check cache first
    if cache:
        cached_response = await cache.get(request.query, request.top_k, request.filters or {})
        if cached_response:
            cached_response['from_cache'] = True
            cached_response['correlation_id'] = correlation_id
            cached_response['latency_ms'] = round((time.time() - start_time) * 1000, 2)
            log.info(f"Returning cached response (latency: {cached_response['latency_ms']}ms)")
            return cached_response
    
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
        recommendations = [ProductRecommendation(**result) for result in results]
        
        latency_ms = round((time.time() - start_time) * 1000, 2)
        
        response = RecommendationResponse(
            recommendations=recommendations,
            query=request.query,
            total_results=len(recommendations),
            correlation_id=correlation_id,
            latency_ms=latency_ms,
            from_cache=False
        )
        
        # Cache the response
        if cache:
            await cache.set(request.query, request.top_k, request.filters or {}, response.dict())
        
        # Log search query to database (async, non-blocking)
        import asyncio
        asyncio.create_task(
            db.log_search_query(
                query=request.query,
                filters=request.filters or {},
                result_count=len(recommendations),
                latency_ms=latency_ms,
                correlation_id=correlation_id
            )
        )
        
        log.info(f"Returned {len(recommendations)} recommendations (latency: {latency_ms}ms)")
        return response
        
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
    db: DatabaseManager = Depends(get_db_dependency),
    log: LoggerAdapter = Depends(get_logger)
):
    """Get similar products"""
    correlation_id = get_correlation_id(req)
    start_time = time.time()
    
    log.info(f"Similar products request for: {product_id}")
    
    try:
        results = await retrieval_engine.find_similar_products(product_id, top_k)
        recommendations = [ProductRecommendation(**result) for result in results]
        
        latency_ms = round((time.time() - start_time) * 1000, 2)
        
        # Log interaction
        import asyncio
        asyncio.create_task(
            db.log_product_interaction(
                product_id=product_id,
                interaction_type="similar_search",
                metadata={"top_k": top_k}
            )
        )
        
        return RecommendationResponse(
            recommendations=recommendations,
            query=f"Similar to {product_id}",
            total_results=len(recommendations),
            correlation_id=correlation_id,
            latency_ms=latency_ms
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
    db: DatabaseManager = Depends(get_db_dependency),
    log: LoggerAdapter = Depends(get_logger)
):
    """Get service statistics"""
    log.info("Stats requested")
    
    engine_stats = retrieval_engine.get_stats() if retrieval_engine else {}
    search_analytics = await db.get_search_analytics()
    popular_searches = await db.get_popular_searches(limit=5)
    
    return {
        **engine_stats,
        "search_analytics": search_analytics,
        "popular_searches": popular_searches,
        "cache_enabled": redis_client is not None
    }


if __name__ == "__main__":
    uvicorn.run(
        "main_optimized:app",
        host="0.0.0.0",
        port=8002,
        reload=False,
        log_level="info"
    )