"""
Middleware for correlation ID tracking and request logging
"""
import time
import uuid
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to extract or generate correlation IDs for request tracing
    """
    
    async def dispatch(self, request: Request, call_next):
        # Extract or generate correlation ID
        correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        
        # Store in request state for access by handlers
        request.state.correlation_id = correlation_id
        
        # Log request
        start_time = time.time()
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={'correlation_id': correlation_id}
        )
        
        # Process request
        response = await call_next(request)
        
        # Add correlation ID to response headers
        response.headers["x-correlation-id"] = correlation_id
        
        # Log response
        duration = time.time() - start_time
        logger.info(
            f"Request completed: {request.method} {request.url.path} "
            f"status={response.status_code} duration={duration:.3f}s",
            extra={'correlation_id': correlation_id}
        )
        
        return response