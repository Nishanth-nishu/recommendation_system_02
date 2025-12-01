"""
Sample Dataset Loader
Loads a realistic e-commerce dataset into the ingestion service
"""
import asyncio
import httpx
import json
from typing import List, Dict

# Sample product data - realistic e-commerce products
SAMPLE_PRODUCTS = [
    # Electronics
    {
        "product_id": "ELEC001",
        "title": "Sony WH-1000XM5 Wireless Headphones",
        "description": "Industry-leading noise cancellation with premium sound quality. 30-hour battery life with quick charging. Multipoint connection for seamless switching between devices.",
        "category": "Electronics",
        "price": 399.99
    },
    {
        "product_id": "ELEC002",
        "title": "Apple AirPods Pro 2nd Generation",
        "description": "Active noise cancellation and adaptive transparency mode. Personalized spatial audio with dynamic head tracking. Up to 6 hours listening time.",
        "category": "Electronics",
        "price": 249.99
    },
    {
        "product_id": "ELEC003",
        "title": "Samsung Galaxy S23 Ultra 5G",
        "description": "6.8-inch Dynamic AMOLED display. 200MP camera with enhanced nightography. 5000mAh battery with 45W fast charging.",
        "category": "Electronics",
        "price": 1199.99
    },
    {
        "product_id": "ELEC004",
        "title": "Dell XPS 15 Laptop",
        "description": "15.6-inch 4K OLED touchscreen. Intel Core i7-13700H processor. NVIDIA GeForce RTX 4050 graphics. 32GB RAM, 1TB SSD.",
        "category": "Electronics",
        "price": 2099.99
    },
    {
        "product_id": "ELEC005",
        "title": "iPad Pro 12.9-inch M2",
        "description": "Liquid Retina XDR display. M2 chip with 8-core CPU. Apple Pencil hover support. 5G capable with Wi-Fi 6E.",
        "category": "Electronics",
        "price": 1099.99
    },
    
    # Clothing
    {
        "product_id": "CLTH001",
        "title": "Levi's 501 Original Fit Jeans",
        "description": "Classic straight fit denim jeans. Button fly. Made from premium denim with signature stitching. Available in multiple washes.",
        "category": "Clothing",
        "price": 69.99
    },
    {
        "product_id": "CLTH002",
        "title": "Nike Dri-FIT Running Shirt",
        "description": "Moisture-wicking performance fabric. Lightweight and breathable. Reflective details for low-light visibility.",
        "category": "Clothing",
        "price": 35.00
    },
    {
        "product_id": "CLTH003",
        "title": "Patagonia Down Sweater Jacket",
        "description": "Warm, windproof, and water-resistant. 800-fill-power recycled down insulation. Fair Trade Certified sewn.",
        "category": "Clothing",
        "price": 229.00
    },
    {
        "product_id": "CLTH004",
        "title": "Adidas Ultraboost 22 Running Shoes",
        "description": "Responsive Boost midsole. Primeknit+ upper for adaptive support. Continental rubber outsole for superior grip.",
        "category": "Clothing",
        "price": 190.00
    },
    
    # Books
    {
        "product_id": "BOOK001",
        "title": "Atomic Habits by James Clear",
        "description": "The #1 New York Times bestseller. Practical strategies for building good habits and breaking bad ones. Based on proven scientific research.",
        "category": "Books",
        "price": 16.99
    },
    {
        "product_id": "BOOK002",
        "title": "Designing Data-Intensive Applications",
        "description": "Essential guide to modern data systems. Covers distributed systems, databases, and stream processing. Written by Martin Kleppmann.",
        "category": "Books",
        "price": 49.99
    },
    {
        "product_id": "BOOK003",
        "title": "The Psychology of Money",
        "description": "Timeless lessons on wealth, greed, and happiness. By Morgan Housel. Learn how to think about money and investing.",
        "category": "Books",
        "price": 18.99
    },
    
    # Home & Garden
    {
        "product_id": "HOME001",
        "title": "Dyson V15 Detect Cordless Vacuum",
        "description": "Laser reveals invisible dust. HEPA filtration captures 99.99% of particles. Up to 60 minutes run time. LCD screen shows particle count.",
        "category": "Home & Garden",
        "price": 649.99
    },
    {
        "product_id": "HOME002",
        "title": "Ninja Foodi 14-in-1 Air Fryer",
        "description": "8-quart capacity. Multiple cooking functions including air fry, roast, bake, and dehydrate. Dual-zone technology.",
        "category": "Home & Garden",
        "price": 199.99
    },
    {
        "product_id": "HOME003",
        "title": "Philips Hue White and Color Smart Bulbs",
        "description": "16 million colors. Works with Alexa, Google, and Apple HomeKit. Schedule routines and automations. Energy efficient LED.",
        "category": "Home & Garden",
        "price": 129.99
    },
    
    # Sports & Fitness
    {
        "product_id": "SPRT001",
        "title": "Peloton Bike+ with Rotating Screen",
        "description": "22-inch HD touchscreen that rotates. Auto-follow resistance. Premium sound system. Access to thousands of live and on-demand classes.",
        "category": "Sports",
        "price": 2495.00
    },
    {
        "product_id": "SPRT002",
        "title": "TRX HOME2 Suspension Trainer",
        "description": "Complete body workout system. Lightweight and portable. Includes workout guide and training videos. Suitable for all fitness levels.",
        "category": "Sports",
        "price": 169.95
    },
    {
        "product_id": "SPRT003",
        "title": "Garmin Forerunner 955 GPS Watch",
        "description": "Advanced running and triathlon features. Solar charging. Training readiness and recovery metrics. Up to 20 days battery life.",
        "category": "Sports",
        "price": 549.99
    },
]


async def load_products(base_url: str = "http://localhost:8001", batch_size: int = 5):
    """Load sample products into the ingestion service"""
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check if service is ready
        try:
            response = await client.get(f"{base_url}/health")
            response.raise_for_status()
            print("✓ Ingestion service is healthy")
        except Exception as e:
            print(f"✗ Cannot connect to ingestion service: {e}")
            return
        
        # Load products in batches
        print(f"\nLoading {len(SAMPLE_PRODUCTS)} products...")
        
        for i in range(0, len(SAMPLE_PRODUCTS), batch_size):
            batch = SAMPLE_PRODUCTS[i:i+batch_size]
            
            try:
                response = await client.post(
                    f"{base_url}/ingest/batch",
                    json={"products": batch},
                    headers={"x-correlation-id": f"load-batch-{i}"}
                )
                response.raise_for_status()
                result = response.json()
                
                print(f"  Batch {i//batch_size + 1}: {result['success']} succeeded, {result['failed']} failed")
                
            except Exception as e:
                print(f"  Batch {i//batch_size + 1} failed: {e}")
        
        # Get final stats
        try:
            response = await client.get(f"{base_url}/stats")
            stats = response.json()
            print(f"\n✓ Loading complete!")
            print(f"  Total products in index: {stats['total_products']}")
            print(f"  Embedding dimension: {stats['embedding_dimension']}")
        except Exception as e:
            print(f"✗ Could not fetch stats: {e}")


async def test_recommendations(base_url: str = "http://localhost:8002"):
    """Test recommendation service with sample queries"""
    
    test_queries = [
        "wireless noise cancelling headphones",
        "laptop for programming and development",
        "running shoes with good cushioning",
        "smart home lighting",
        "fitness tracker with GPS"
    ]
    
    print("\n" + "="*60)
    print("Testing Recommendation Service")
    print("="*60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check if service is ready
        try:
            response = await client.get(f"{base_url}/ready")
            response.raise_for_status()
            print("✓ Recommendation service is ready\n")
        except Exception as e:
            print(f"✗ Recommendation service not ready: {e}")
            return
        
        # Test each query
        for query in test_queries:
            print(f"\nQuery: '{query}'")
            print("-" * 60)
            
            try:
                response = await client.post(
                    f"{base_url}/recommend",
                    json={"query": query, "top_k": 3},
                    headers={"x-correlation-id": f"test-{hash(query)}"}
                )
                response.raise_for_status()
                result = response.json()
                
                for i, rec in enumerate(result["recommendations"], 1):
                    print(f"{i}. {rec['title']}")
                    print(f"   Score: {rec['score']:.4f} | Price: ${rec['price']}")
                    print(f"   Category: {rec['category']}")
                
            except Exception as e:
                print(f"✗ Query failed: {e}")


async def main():
    """Main execution"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Load sample data and test recommendations")
    parser.add_argument("--ingest-url", default="http://localhost:8001", help="Ingestion service URL")
    parser.add_argument("--rec-url", default="http://localhost:8002", help="Recommendation service URL")
    parser.add_argument("--skip-load", action="store_true", help="Skip loading data")
    parser.add_argument("--skip-test", action="store_true", help="Skip testing recommendations")
    
    args = parser.parse_args()
    
    if not args.skip_load:
        await load_products(args.ingest_url)
    
    if not args.skip_test:
        # Wait a bit for index to be updated
        await asyncio.sleep(2)
        await test_recommendations(args.rec_url)
    
    print("\n" + "="*60)
    print("Done!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())