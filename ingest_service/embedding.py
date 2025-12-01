"""
Embedding Engine with FAISS vector store
Handles embedding generation and similarity search
"""
import asyncio
import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingEngine:
    """Manages product embeddings and FAISS index"""
    
    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        index_path: str = "/data/faiss.index",
        metadata_path: str = "/data/metadata.pkl"
    ):
        self.model_name = model_name
        self.index_path = Path(index_path)
        self.metadata_path = Path(metadata_path)
        
        # Initialize model
        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        
        # Initialize FAISS index
        self.index: Optional[faiss.IndexFlatL2] = None
        self.metadata: Dict[int, Dict] = {}
        self.product_id_to_idx: Dict[str, int] = {}
        self.idx_to_product_id: Dict[int, str] = {}
        self.next_idx = 0
        
        # Create data directory
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Try to load existing index
        self._load_index()
        
        if self.index is None:
            logger.info("Creating new FAISS index")
            self.index = faiss.IndexFlatL2(self.embedding_dim)
    
    def _load_index(self):
        """Load existing FAISS index and metadata"""
        if self.index_path.exists() and self.metadata_path.exists():
            try:
                logger.info("Loading existing FAISS index")
                self.index = faiss.read_index(str(self.index_path))
                
                with open(self.metadata_path, 'rb') as f:
                    data = pickle.load(f)
                    self.metadata = data['metadata']
                    self.product_id_to_idx = data['product_id_to_idx']
                    self.idx_to_product_id = data['idx_to_product_id']
                    self.next_idx = data['next_idx']
                
                logger.info(f"Loaded index with {self.index.ntotal} vectors")
            except Exception as e:
                logger.error(f"Failed to load index: {e}")
                self.index = None
    
    def _save_index(self):
        """Save FAISS index and metadata to disk"""
        try:
            faiss.write_index(self.index, str(self.index_path))
            
            with open(self.metadata_path, 'wb') as f:
                pickle.dump({
                    'metadata': self.metadata,
                    'product_id_to_idx': self.product_id_to_idx,
                    'idx_to_product_id': self.idx_to_product_id,
                    'next_idx': self.next_idx
                }, f)
            
            logger.info(f"Saved index with {self.index.ntotal} vectors")
        except Exception as e:
            logger.error(f"Failed to save index: {e}")
            raise
    
    async def generate_embedding(self, text: str) -> np.ndarray:
        """Generate embedding for text (async wrapper for CPU-bound operation)"""
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            None,
            lambda: self.model.encode(text, convert_to_numpy=True)
        )
        return embedding
    
    async def add_product(self, product_id: str, embedding: np.ndarray, metadata: Dict):
        """Add product embedding to FAISS index"""
        # Check if product already exists
        if product_id in self.product_id_to_idx:
            logger.warning(f"Product {product_id} already exists, updating...")
            idx = self.product_id_to_idx[product_id]
        else:
            idx = self.next_idx
            self.next_idx += 1
            self.product_id_to_idx[product_id] = idx
            self.idx_to_product_id[idx] = product_id
        
        # Add to index
        embedding_2d = embedding.reshape(1, -1).astype('float32')
        
        if product_id in self.product_id_to_idx and idx < self.index.ntotal:
            # Update existing - FAISS doesn't support updates, so we rebuild
            # For production, consider using IVF index with remove/add
            logger.warning("FAISS doesn't support updates efficiently, adding as new")
        
        self.index.add(embedding_2d)
        self.metadata[idx] = metadata
        
        # Save periodically (every 100 products)
        if self.next_idx % 100 == 0:
            self._save_index()
    
    async def search(self, query_embedding: np.ndarray, top_k: int = 5) -> List[Dict]:
        """Search for similar products"""
        query_2d = query_embedding.reshape(1, -1).astype('float32')
        
        # Search FAISS index
        distances, indices = self.index.search(query_2d, top_k)
        
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:  # FAISS returns -1 for empty slots
                continue
            
            product_id = self.idx_to_product_id.get(idx)
            if product_id:
                result = {
                    "product_id": product_id,
                    "score": float(1 / (1 + dist)),  # Convert distance to similarity score
                    "distance": float(dist),
                    **self.metadata.get(idx, {})
                }
                results.append(result)
        
        return results
    
    async def load_initial_dataset(self):
        """Load initial dataset of 10k+ products"""
        # For demo, generate synthetic products
        # In production, load from CSV/database
        logger.info("Loading initial dataset...")
        
        categories = ["Electronics", "Clothing", "Books", "Home & Garden", "Sports"]
        products = []
        
        for i in range(10000):
            category = categories[i % len(categories)]
            product = {
                "product_id": f"P{i:06d}",
                "title": f"{category} Product {i}",
                "description": f"High-quality {category.lower()} item with premium features",
                "category": category,
                "price": round(10 + (i % 500), 2)
            }
            products.append(product)
        
        # Batch process
        batch_size = 100
        for i in range(0, len(products), batch_size):
            batch = products[i:i+batch_size]
            texts = [f"{p['title']} {p['description']}" for p in batch]
            
            # Generate embeddings in batch
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                None,
                lambda: self.model.encode(texts, convert_to_numpy=True)
            )
            
            # Add to index
            for product, embedding in zip(batch, embeddings):
                await self.add_product(
                    product["product_id"],
                    embedding,
                    product
                )
            
            if (i + batch_size) % 1000 == 0:
                logger.info(f"Loaded {i + batch_size} products...")
        
        # Final save
        self._save_index()
        logger.info(f"Loaded {len(products)} products into FAISS index")
    
    def get_total_products(self) -> int:
        """Get total number of products in index"""
        return self.index.ntotal if self.index else 0
    
    def is_ready(self) -> bool:
        """Check if engine is ready"""
        return self.index is not None and self.index.ntotal > 0
    
    def get_stats(self) -> Dict:
        """Get index statistics"""
        return {
            "total_products": self.get_total_products(),
            "embedding_dimension": self.embedding_dim,
            "model": self.model_name,
            "index_type": "IndexFlatL2"
        }