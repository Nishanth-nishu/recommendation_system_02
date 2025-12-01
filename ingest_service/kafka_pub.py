"""
Kafka Publisher for event-driven architecture
Publishes product events to Kafka topics
"""
import json
import logging
import os
from typing import Dict, Optional

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

logger = logging.getLogger(__name__)


class KafkaPublisher:
    """Async Kafka event publisher"""
    
    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        client_id: str = "ingest-service"
    ):
        self.bootstrap_servers = bootstrap_servers or os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS",
            "kafka:9092"
        )
        self.client_id = client_id
        self.producer: Optional[AIOKafkaProducer] = None
        
        logger.info(f"Kafka publisher initialized with servers: {self.bootstrap_servers}")
    
    async def start(self):
        """Start Kafka producer"""
        try:
            self.producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                client_id=self.client_id,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                compression_type='gzip',
                acks='all',  # Wait for all replicas
                retries=3,
                max_in_flight_requests_per_connection=5
            )
            await self.producer.start()
            logger.info("Kafka producer started successfully")
        except Exception as e:
            logger.error(f"Failed to start Kafka producer: {e}")
            # Don't fail startup - service can work without Kafka
            self.producer = None
    
    async def stop(self):
        """Stop Kafka producer"""
        if self.producer:
            try:
                await self.producer.stop()
                logger.info("Kafka producer stopped")
            except Exception as e:
                logger.error(f"Error stopping Kafka producer: {e}")
    
    async def publish(self, topic: str, event: Dict, key: Optional[str] = None):
        """
        Publish event to Kafka topic
        
        Args:
            topic: Kafka topic name
            event: Event data (will be JSON serialized)
            key: Optional message key for partitioning
        """
        if not self.producer:
            logger.warning("Kafka producer not available, event not published")
            return False
        
        try:
            # Use product_id as key for consistent partitioning
            message_key = (key or event.get('product_id', '')).encode('utf-8')
            
            # Send message
            await self.producer.send_and_wait(
                topic,
                value=event,
                key=message_key
            )
            
            logger.info(
                f"Published event to {topic}: {event.get('event_type')} "
                f"for product {event.get('product_id')}"
            )
            return True
            
        except KafkaError as e:
            logger.error(f"Kafka error publishing to {topic}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error publishing to {topic}: {e}")
            return False
    
    async def publish_batch(self, topic: str, events: list):
        """Publish multiple events in batch"""
        if not self.producer:
            logger.warning("Kafka producer not available, batch not published")
            return False
        
        try:
            for event in events:
                message_key = event.get('product_id', '').encode('utf-8')
                await self.producer.send(topic, value=event, key=message_key)
            
            # Flush to ensure all messages are sent
            await self.producer.flush()
            
            logger.info(f"Published {len(events)} events to {topic}")
            return True
            
        except Exception as e:
            logger.error(f"Error publishing batch to {topic}: {e}")
            return False