import json
import logging
from typing import Dict, Iterable, Tuple

import certifi
from confluent_kafka import KafkaException, Producer

from fusion_audit.config import KafkaConfig

logger = logging.getLogger(__name__)


class KafkaPublisher:
    def __init__(self, config: KafkaConfig):
        self._config = config
        self._producer = Producer(self._producer_config(config))

    def publish(self, messages: Iterable[Tuple[str, Dict]]) -> int:
        delivered = 0
        errors = []

        def on_delivery(error, msg):
            nonlocal delivered
            if error is not None:
                errors.append(str(error))
                logger.error("Kafka delivery failed: %s", error)
                return

            delivered += 1
            logger.debug(
                "Delivered message to %s partition %s offset %s",
                msg.topic(),
                msg.partition(),
                msg.offset(),
            )

        for key, message in messages:
            value = json.dumps(message, default=str, separators=(",", ":")).encode("utf-8")
            self._producer.produce(
                self._config.topic,
                key=key.encode("utf-8"),
                value=value,
                on_delivery=on_delivery,
            )
            self._producer.poll(0)

        remaining = self._producer.flush(self._config.flush_timeout_seconds)
        if remaining:
            raise KafkaException(f"{remaining} Kafka message(s) were not delivered before flush timeout.")
        if errors:
            raise KafkaException(f"Kafka delivery failed for {len(errors)} message(s): {errors[:3]}")

        return delivered

    @staticmethod
    def _producer_config(config: KafkaConfig) -> Dict:
        producer_config = {
            "bootstrap.servers": config.bootstrap_servers,
            "client.id": config.client_id,
            "security.protocol": config.security_protocol,
            "request.timeout.ms": config.request_timeout_ms,
            "message.send.max.retries": config.message_send_max_retries,
            "max.request.size": config.max_request_size,
        }

        if config.security_protocol.upper().startswith("SASL"):
            producer_config.update(
                {
                    "sasl.mechanism": config.sasl_mechanism,
                    "sasl.username": config.username,
                    "sasl.password": config.password,
                }
            )

        if config.security_protocol.upper().endswith("SSL"):
            producer_config["ssl.ca.location"] = config.ssl_ca_location or certifi.where()

        producer_config.update(config.extra_config)
        return producer_config
