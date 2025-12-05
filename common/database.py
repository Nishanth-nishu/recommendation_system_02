"""
Database models and connection management
Uses PostgreSQL with asyncpg for high-performance async operations
"""
import os
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
from contextlib import asynccontextmanager

import asyncpg
from asyncpg import Pool, Connection
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# Pydantic Models
class ProductDB(BaseModel):
    """Product database model"""
    id: Optional[int] = None
    product_id: str
    title: str
    description: str
    category: Optional[str] = None
    price: Optional[float] = None
    brand: Optional[str] = None
    rating: Optional[float] = None
    stock: Optional[int] = None
    embedding_vector: Optional[List[float]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class SearchQueryLog(BaseModel):
    """Search query logging model"""
    id: Optional[int] = None
    query: str
    filters: Optional[Dict] = None
    result_count: int
    latency_ms: float
    correlation_id: str
    created_at: Optional[datetime] = None


class DatabaseManager:
    """Async PostgreSQL database manager with connection pooling"""
    
    def __init__(
        self,
        host: str = None,
        port: int = None,
        database: str = None,
        user: str = None,
        password: str = None,
        min_pool_size: int = 10,
        max_pool_size: int = 20
    ):
        self.host = host or os.getenv('DB_HOST', 'localhost')
        self.port = port or int(os.getenv('DB_PORT', '5432'))
        self.database = database or os.getenv('DB_NAME', 'semantic_recsys')
        self.user = user or os.getenv('DB_USER', 'postgres')
        self.password = password or os.getenv('DB_PASSWORD', 'postgres')
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        
        self.pool: Optional[Pool] = None
        
    async def connect(self):
        """Create connection pool"""
        try:
            self.pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=self.min_pool_size,
                max_size=self.max_pool_size,
                command_timeout=30.0,
                max_queries=50000,
                max_inactive_connection_lifetime=300.0
            )
            logger.info(
                f"Database pool created: {self.host}:{self.port}/{self.database} "
                f"(pool: {self.min_pool_size}-{self.max_pool_size})"
            )
            
            # Create tables
            await self.create_tables()
            
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    async def disconnect(self):
        """Close connection pool"""
        if self.pool:
            await self.pool.close()
            logger.info("Database pool closed")
    
    @asynccontextmanager
    async def acquire(self) -> Connection:
        """Get connection from pool"""
        if not self.pool:
            raise RuntimeError("Database pool not initialized")
        
        async with self.pool.acquire() as connection:
            yield connection
    
    async def create_tables(self):
        """Create database tables if they don't exist"""
        async with self.acquire() as conn:
            # Products table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    product_id VARCHAR(50) UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    category VARCHAR(100),
                    price DECIMAL(10, 2),
                    brand VARCHAR(100),
                    rating DECIMAL(3, 2),
                    stock INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_products_product_id ON products(product_id);
                CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
                CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);
            """)
            
            # Search queries log
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS search_queries (
                    id SERIAL PRIMARY KEY,
                    query TEXT NOT NULL,
                    filters JSONB,
                    result_count INTEGER,
                    latency_ms DECIMAL(10, 2),
                    correlation_id VARCHAR(100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_search_queries_created_at ON search_queries(created_at);
                CREATE INDEX IF NOT EXISTS idx_search_queries_correlation_id ON search_queries(correlation_id);
            """)
            
            # Product views/interactions (for analytics)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS product_interactions (
                    id SERIAL PRIMARY KEY,
                    product_id VARCHAR(50) NOT NULL,
                    interaction_type VARCHAR(50) NOT NULL,
                    session_id VARCHAR(100),
                    user_id VARCHAR(100),
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_product_interactions_product_id ON product_interactions(product_id);
                CREATE INDEX IF NOT EXISTS idx_product_interactions_type ON product_interactions(interaction_type);
            """)
            
            logger.info("Database tables created/verified")
    
    # Product operations
    async def insert_product(self, product: ProductDB) -> int:
        """Insert a product into database"""
        async with self.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO products (product_id, title, description, category, price, brand, rating, stock)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (product_id) 
                DO UPDATE SET 
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    category = EXCLUDED.category,
                    price = EXCLUDED.price,
                    brand = EXCLUDED.brand,
                    rating = EXCLUDED.rating,
                    stock = EXCLUDED.stock,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
            """, product.product_id, product.title, product.description, 
                product.category, product.price, product.brand, product.rating, product.stock)
            
            return row['id']
    
    async def bulk_insert_products(self, products: List[ProductDB]) -> int:
        """Bulk insert products (much faster than individual inserts)"""
        if not products:
            return 0
        
        async with self.acquire() as conn:
            # Prepare data for batch insert
            data = [
                (p.product_id, p.title, p.description, p.category, p.price, 
                 p.brand, p.rating, p.stock)
                for p in products
            ]
            
            # Use COPY for maximum performance
            result = await conn.copy_records_to_table(
                'products',
                records=data,
                columns=['product_id', 'title', 'description', 'category', 
                        'price', 'brand', 'rating', 'stock'],
                timeout=60.0
            )
            
            return len(products)
    
    async def get_product(self, product_id: str) -> Optional[ProductDB]:
        """Get product by ID"""
        async with self.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM products WHERE product_id = $1
            """, product_id)
            
            if row:
                return ProductDB(**dict(row))
            return None
    
    async def get_products_batch(self, product_ids: List[str]) -> List[ProductDB]:
        """Get multiple products by IDs (optimized batch query)"""
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM products WHERE product_id = ANY($1::text[])
            """, product_ids)
            
            return [ProductDB(**dict(row)) for row in rows]
    
    async def search_products(
        self,
        query: str = None,
        category: str = None,
        min_price: float = None,
        max_price: float = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[ProductDB]:
        """Search products with filters"""
        conditions = []
        params = []
        param_count = 1
        
        if query:
            conditions.append(f"(title ILIKE ${param_count} OR description ILIKE ${param_count})")
            params.append(f"%{query}%")
            param_count += 1
        
        if category:
            conditions.append(f"category = ${param_count}")
            params.append(category)
            param_count += 1
        
        if min_price is not None:
            conditions.append(f"price >= ${param_count}")
            params.append(min_price)
            param_count += 1
        
        if max_price is not None:
            conditions.append(f"price <= ${param_count}")
            params.append(max_price)
            param_count += 1
        
        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        
        async with self.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT * FROM products 
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ${param_count} OFFSET ${param_count + 1}
            """, *params, limit, offset)
            
            return [ProductDB(**dict(row)) for row in rows]
    
    async def get_total_products(self) -> int:
        """Get total product count"""
        async with self.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) as count FROM products")
            return row['count']
    
    # Search query logging
    async def log_search_query(
        self,
        query: str,
        filters: Dict,
        result_count: int,
        latency_ms: float,
        correlation_id: str
    ):
        """Log search query for analytics"""
        async with self.acquire() as conn:
            await conn.execute("""
                INSERT INTO search_queries (query, filters, result_count, latency_ms, correlation_id)
                VALUES ($1, $2, $3, $4, $5)
            """, query, filters, result_count, latency_ms, correlation_id)
    
    async def log_product_interaction(
        self,
        product_id: str,
        interaction_type: str,
        session_id: str = None,
        user_id: str = None,
        metadata: Dict = None
    ):
        """Log product interaction"""
        async with self.acquire() as conn:
            await conn.execute("""
                INSERT INTO product_interactions 
                (product_id, interaction_type, session_id, user_id, metadata)
                VALUES ($1, $2, $3, $4, $5)
            """, product_id, interaction_type, session_id, user_id, metadata)
    
    # Analytics queries
    async def get_popular_searches(self, limit: int = 10) -> List[Dict]:
        """Get most popular search queries"""
        async with self.acquire() as conn:
            rows = await conn.fetch("""
                SELECT query, COUNT(*) as count, AVG(latency_ms) as avg_latency
                FROM search_queries
                WHERE created_at >= NOW() - INTERVAL '7 days'
                GROUP BY query
                ORDER BY count DESC
                LIMIT $1
            """, limit)
            
            return [dict(row) for row in rows]
    
    async def get_search_analytics(self) -> Dict[str, Any]:
        """Get search analytics summary"""
        async with self.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total_searches,
                    AVG(latency_ms) as avg_latency,
                    MAX(latency_ms) as max_latency,
                    MIN(latency_ms) as min_latency,
                    AVG(result_count) as avg_results
                FROM search_queries
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """)
            
            return dict(row) if row else {}


# Global database instance
db_manager: Optional[DatabaseManager] = None


async def get_db() -> DatabaseManager:
    """Get database manager instance"""
    global db_manager
    if db_manager is None:
        db_manager = DatabaseManager()
        await db_manager.connect()
    return db_manager


async def close_db():
    """Close database connection"""
    global db_manager
    if db_manager:
        await db_manager.disconnect()
        db_manager = None