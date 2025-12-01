"""
Retrieval Engine for semantic search
Connects to shared FAISS index and provides recommendation logic
"""
import asyncio
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

from exceptions import RecommendationException

logger = logging.getLogger(__name__)


class RetrievalEngine:
    """Handles semantic retrieval and recommendation logic"""
    
    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        index_path: str = "/data/faiss.index",
        metadata_path: str = "/data/metadata.pkl",
        cache_embeddings: bool = True
    ):
        self.model_name = model_name
        self.index_path = Path(index_path)
        self.metadata_path = Path(metadata_path)
        self.cache_embeddings = cache_embeddings
        
        self.model: Optional[SentenceTransformer] = None
        self.index: Optional[faiss.IndexFlatL2] = None
        self.metadata: Dict[int, Dict] = {}
        self.product_id_to_idx: Dict[str, int] = {}
        self.idx_to_product_id: Dict[int, str] = {}
        
        # Embedding cache for product-to-product recommendations
        self.embedding_cache: Dict[str, np.ndarray] = {}
    
    async def initialize(self):
        """Initialize model and load FAISS index"""
        logger.info(f"Loading embedding model: {self.model_name}")
        loop = asyncio.get_event_loop()
        self.model = await loop.run_in_executor(
            None,
            lambda: SentenceTransformer(self.model_name)
        )
        
        # Load FAISS index
        await self._load_index()
        
        if not self.index or self.index.ntotal == 0:
            raise RecommendationException(
                "FAISS index not loaded or empty",
                status_code=503
            )
        
        logger.info(f"Retrieval engine initialized with {self.index.ntotal} products")
    
    async def _load_index(self):
        """Load FAISS index and metadata"""
        if not self.index_path.exists() or not self.metadata_path.exists():
            logger.error("Index files not found")
            raise RecommendationException(
                "Index files not found - ingestion service may not have initialized",
                status_code=503
            )
        
        try:
            loop = asyncio.get_event_loop()
            
            # Load index
            self.index = await loop.run_in_executor(
                None,
                lambda: faiss.read_index(str(self.index_path))
            )
            
            # Load metadata
            with open(self.metadata_path, 'rb') as f:
                data = pickle.load(f)
                self.metadata = data['metadata']
                self.product_id_to_idx = data['product_id_to_idx']
                self.idx_to_product_id = data['idx_to_product_id']
            
            logger.info(f"Loaded FAISS index with {self.index.ntotal} vectors")
            
        except Exception as e:
            logger.error(f"Failed to load FAISS index: {e}")
            raise RecommendationException(
                f"Failed to load index: {str(e)}",
                status_code=503
            )
    
    async def generate_query_embedding(self, query: str) -> np.ndarray:
        """Generate embedding for search query"""
        if not query or not query.strip():
            raise RecommendationException(
                "Query cannot be empty",
                status_code=400
            )
        
        try:
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(
                None,
                lambda: self.model.encode(query, convert_to_numpy=True)
            )
            return embedding
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            raise RecommendationException(
                f"Failed to generate query embedding: {str(e)}",
                status_code=500
            )
    
    async def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Search for similar products
        
        Args:
            query_embedding: Query vector
            top_k: Number of results to return
            filters: Optional filters (category, price range, etc.)
        
        Returns:
            List of similar products with scores
        """
        try:
            # Prepare query
            query_2d = query_embedding.reshape(1, -1).astype('float32')
            
            # Search with more results if filtering
            search_k = top_k * 3 if filters else top_k
            search_k = min(search_k, self.index.ntotal)
            
            # FAISS search
            loop = asyncio.get_event_loop()
            distances, indices = await loop.run_in_executor(
                None,
                lambda: self.index.search(query_2d, search_k)
            )
            
            # Process results
            results = []
            for dist, idx in zip(distances[0], indices[0]):
                if idx == -1:
                    continue
                
                product_id = self.idx_to_product_id.get(idx)
                if not product_id:
                    continue
                
                metadata = self.metadata.get(idx, {})
                
                # Apply filters
                if filters and not self._matches_filters(metadata, filters):
                    continue
                
                # Calculate similarity score (convert L2 distance to similarity)
                score = 1 / (1 + dist)
                
                result = {
                    "product_id": product_id,
                    "title": metadata.get("title", ""),
                    "description": metadata.get("description", ""),
                    "category": metadata.get("category"),
                    "price": metadata.get("price"),
                    "score": float(score),
                    "distance": float(dist)
                }
                results.append(result)
                
                # Stop if we have enough results
                if len(results) >= top_k:
                    break
            
            return results
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise RecommendationException(
                f"Search failed: {str(e)}",
                status_code=500
            )
    
    async def find_similar_products(self, product_id: str, top_k: int = 5) -> List[Dict]:
        """Find products similar to a given product"""
        # Get product index
        idx = self.product_id_to_idx.get(product_id)
        if idx is None:
            raise RecommendationException(
                f"Product {product_id} not found",
                status_code=404
            )
        
        # Get product embedding from index
        try:
            loop = asyncio.get_event_loop()
            product_embedding = await loop.run_in_executor(
                None,
                lambda: self.index.reconstruct(int(idx))
            )
            
            # Search for similar products (excluding the product itself)
            results = await self.search(product_embedding, top_k + 1)
            
            # Filter out the source product
            results = [r for r in results if r["product_id"] != product_id]
            
            return results[:top_k]
            
        except Exception as e:
            logger.error(f"Failed to find similar products: {e}")
            raise RecommendationException(
                f"Failed to find similar products: {str(e)}",
                status_code=500
            )
    
    def _matches_filters(self, metadata: Dict, filters: Dict) -> bool:
        """Check if product matches filter criteria"""
        for key, value in filters.items():
            if key == "category":
                if metadata.get("category") != value:
                    return False
            elif key == "min_price":
                if metadata.get("price", 0) < value:
                    return False
            elif key == "max_price":
                if metadata.get("price", float('inf')) > value:
                    return False
            elif key in metadata:
                if metadata[key] != value:
                    return False
        
        return True
    
    def get_index_size(self) -> int:
        """Get number of products in index"""
        return self.index.ntotal if self.index else 0
    
    def is_ready(self) -> bool:
        """Check if engine is ready to serve requests"""
        return (
            self.model is not None and
            self.index is not None and
            self.index.ntotal > 0
        )
    
    def get_stats(self) -> Dict:
        """Get engine statistics"""
        return {
            "index_size": self.get_index_size(),
            "model": self.model_name,
            "index_type": "IndexFlatL2",
            "ready": self.is_ready(),
            "cache_enabled": self.cache_embeddings
        }