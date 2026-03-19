"""
NexusOps Kafka Infrastructure
===============================
Production-grade Kafka producer and consumer abstractions.
Uses confluent-kafka under the hood with:
  - Automatic serialization/deserialization via Pydantic event schemas
  - Dead-letter queue (DLQ) support for poison messages
  - Graceful shutdown with signal handling
  - Configurable retry and backoff
"""

import json
import logging
import signal
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Type

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from pydantic import BaseModel

from backend.core.events.schemas import NexusEvent

logger = logging.getLogger("nexusops.kafka")


class KafkaConfig(BaseModel):
    bootstrap_servers: str = "localhost:9093"
    group_id: str = "nexusops-default"
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = True
    max_poll_interval_ms: int = 300000
    session_timeout_ms: int = 45000


class NexusKafkaProducer:
    """
    Thread-safe Kafka producer that serializes NexusEvent Pydantic models
    into JSON and publishes them to the specified topic.
    """

    def __init__(self, config: KafkaConfig):
        self.config = config
        self._producer = Producer({
            "bootstrap.servers": config.bootstrap_servers,
            "client.id": "nexusops-producer",
            "acks": "all",                        # Durability: wait for all ISR
            "retries": 5,                         # Retry transient failures
            "retry.backoff.ms": 500,
            "linger.ms": 10,                      # Micro-batch for throughput
            "compression.type": "snappy",         # Compress payloads
        })
        logger.info(f"NexusKafkaProducer initialized → {config.bootstrap_servers}")

    def _delivery_callback(self, err, msg):
        if err:
            logger.error(f"Message delivery failed [{msg.topic()}]: {err}")
        else:
            logger.debug(f"Message delivered → {msg.topic()} [partition={msg.partition()}, offset={msg.offset()}]")

    def publish(self, topic: str, event: NexusEvent, key: Optional[str] = None):
        """Publish a NexusEvent to a Kafka topic."""
        payload = event.model_dump_json()
        msg_key = (key or event.event_id).encode("utf-8")

        self._producer.produce(
            topic=topic,
            key=msg_key,
            value=payload.encode("utf-8"),
            callback=self._delivery_callback,
            headers={"event_type": event.event_type.encode("utf-8")},
        )
        self._producer.poll(0)  # Trigger delivery callbacks

    def flush(self, timeout: float = 5.0):
        """Block until all buffered messages are delivered."""
        remaining = self._producer.flush(timeout)
        if remaining > 0:
            logger.warning(f"{remaining} messages still in queue after flush timeout")


class NexusKafkaConsumer:
    """
    Kafka consumer that deserializes JSON payloads into NexusEvent subclasses
    and dispatches them to registered handler functions.

    Supports:
      - Multiple topic subscriptions
      - Type-safe dispatch by event_type
      - Dead-letter queue for unprocessable messages
      - Graceful shutdown via SIGINT/SIGTERM
    """

    def __init__(self, config: KafkaConfig, topics: List[str], dlq_topic: str = "nexusops-dlq"):
        self.config = config
        self.topics = topics
        self.dlq_topic = dlq_topic
        self._handlers: Dict[str, Callable] = {}
        self._running = False
        self._consumer = Consumer({
            "bootstrap.servers": config.bootstrap_servers,
            "group.id": config.group_id,
            "auto.offset.reset": config.auto_offset_reset,
            "enable.auto.commit": config.enable_auto_commit,
            "max.poll.interval.ms": config.max_poll_interval_ms,
            "session.timeout.ms": config.session_timeout_ms,
        })
        self._dlq_producer = NexusKafkaProducer(config)
        logger.info(f"NexusKafkaConsumer initialized → topics={topics}, group={config.group_id}")

    def register_handler(self, event_type: str, handler: Callable):
        """Register a handler function for a specific event_type."""
        self._handlers[event_type] = handler
        logger.info(f"Handler registered: {event_type} → {handler.__name__}")

    def _send_to_dlq(self, raw_message: bytes, error_reason: str):
        """Send unprocessable messages to the Dead Letter Queue."""
        dlq_event = NexusEvent(
            event_type="dlq.poisoned_message",
            metadata={
                "original_payload": raw_message.decode("utf-8", errors="replace"),
                "error_reason": error_reason,
            },
        )
        self._dlq_producer.publish(self.dlq_topic, dlq_event)
        logger.warning(f"Message sent to DLQ: {error_reason}")

    def start(self):
        """Start the consumer loop. Blocks the calling thread."""
        self._consumer.subscribe(self.topics)
        self._running = True

        # Graceful shutdown on SIGINT / SIGTERM
        def _shutdown(signum, frame):
            logger.info(f"Received signal {signum}, shutting down consumer...")
            self._running = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        logger.info(f"Consumer loop started on topics: {self.topics}")
        try:
            while self._running:
                msg = self._consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    logger.error(f"Consumer error: {msg.error()}")
                    continue

                raw_value = msg.value()
                try:
                    payload = json.loads(raw_value)
                    event_type = payload.get("event_type", "unknown")

                    handler = self._handlers.get(event_type)
                    if handler:
                        handler(payload)
                    else:
                        logger.warning(f"No handler registered for event_type={event_type}")

                except json.JSONDecodeError as e:
                    self._send_to_dlq(raw_value, f"JSON decode error: {e}")
                except Exception as e:
                    self._send_to_dlq(raw_value, f"Handler exception: {e}")
                    logger.exception(f"Error processing message: {e}")

        finally:
            self._consumer.close()
            self._dlq_producer.flush()
            logger.info("Consumer loop stopped cleanly.")

    def stop(self):
        self._running = False


def ensure_topics_exist(bootstrap_servers: str, topics: List[str], num_partitions: int = 3, replication_factor: int = 1):
    """
    Idempotently create Kafka topics if they don't already exist.
    Called once at application startup.
    """
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    existing = admin.list_topics(timeout=5).topics.keys()

    new_topics = []
    for t in topics:
        if t not in existing:
            new_topics.append(NewTopic(t, num_partitions=num_partitions, replication_factor=replication_factor))
            logger.info(f"Creating topic: {t}")

    if new_topics:
        futures = admin.create_topics(new_topics)
        for topic_name, future in futures.items():
            try:
                future.result()
                logger.info(f"Topic created: {topic_name}")
            except Exception as e:
                logger.error(f"Failed to create topic {topic_name}: {e}")
    else:
        logger.info("All required topics already exist.")
