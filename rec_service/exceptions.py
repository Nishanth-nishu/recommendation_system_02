"""
Custom exceptions for recommendation service
"""


class RecommendationException(Exception):
    """Base exception for recommendation errors"""
    
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class IndexNotFoundError(RecommendationException):
    """Raised when FAISS index is not found"""
    
    def __init__(self, message: str = "FAISS index not found"):
        super().__init__(message, status_code=503)


class ProductNotFoundError(RecommendationException):
    """Raised when a product is not found in the index"""
    
    def __init__(self, product_id: str):
        super().__init__(
            f"Product {product_id} not found in index",
            status_code=404
        )


class InvalidQueryError(RecommendationException):
    """Raised when query is invalid"""
    
    def __init__(self, message: str = "Invalid query"):
        super().__init__(message, status_code=400)


class EmbeddingGenerationError(RecommendationException):
    """Raised when embedding generation fails"""
    
    def __init__(self, message: str = "Failed to generate embedding"):
        super().__init__(message, status_code=500)