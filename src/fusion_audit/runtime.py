import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional, Tuple

from fusion_audit.config import AppConfig, KafkaConfig
from fusion_audit.fusion import FusionAuditClient, FusionCredentials
from fusion_audit.kafka_publisher import KafkaPublisher
from fusion_audit.oci_log_publisher import OciLogPublisher
from fusion_audit.vault import VaultSecretProvider

logger = logging.getLogger(__name__)


def run_audit_export(
    config: AppConfig,
    secret_provider: Optional[VaultSecretProvider] = None,
    oci_log_publisher: Optional[OciLogPublisher] = None,
) -> Dict:
    secret_provider = secret_provider or VaultSecretProvider()
    secrets = secret_provider.get_many(config.vault.secret_references())
    kafka_config = _with_secret_credentials(config.kafka, secrets)

    to_dt = datetime.now(timezone.utc).replace(microsecond=0)
    from_dt = to_dt - timedelta(hours=config.lookback_hours)

    fusion_client = FusionAuditClient(
        credentials=FusionCredentials(
            base_url=secrets["fusion_base_url"],
            username=secrets["fusion_username"],
            password=secrets["fusion_password"],
        ),
        config=config.fusion,
    )

    publisher = None if config.dry_run else KafkaPublisher(kafka_config)
    if not config.dry_run and config.oci_log.enabled:
        oci_log_publisher = oci_log_publisher or OciLogPublisher(config.oci_log)

    pages_read = 0
    records_read = 0
    messages_published = 0
    oci_log_messages_published = 0

    for page in fusion_client.iter_audit_pages(from_dt=from_dt, to_dt=to_dt):
        pages_read += 1
        records_read += len(page.records)
        messages = list(_audit_messages(config, from_dt, to_dt, page.records))

        if config.dry_run:
            logger.info("Dry run enabled; skipped publishing %s messages from page %s.", len(messages), page.page_number)
            continue

        messages_published += publisher.publish(messages)
        if oci_log_publisher:
            oci_log_messages_published += oci_log_publisher.publish(messages)

    return {
        "status": "success",
        "dry_run": config.dry_run,
        "window": {
            "from": from_dt.isoformat(),
            "to": to_dt.isoformat(),
            "lookback_hours": config.lookback_hours,
        },
        "fusion": {
            "product": config.fusion.product,
            "business_object_type": config.fusion.business_object_type,
            "event_type": config.fusion.event_type,
        },
        "kafka": {
            "bootstrap_servers": kafka_config.bootstrap_servers,
            "topic": kafka_config.topic,
            "messages_published": messages_published,
        },
        "oci_log": {
            "enabled": config.oci_log.enabled,
            "log_id": config.oci_log.log_id,
            "messages_published": oci_log_messages_published,
        },
        "pages_read": pages_read,
        "records_read": records_read,
        "messages_published": messages_published,
    }


def _with_secret_credentials(config: KafkaConfig, secrets: Dict[str, str]) -> KafkaConfig:
    return KafkaConfig(
        bootstrap_servers=config.bootstrap_servers,
        topic=config.topic,
        security_protocol=config.security_protocol,
        sasl_mechanism=config.sasl_mechanism,
        username=config.username or secrets.get("kafka_username"),
        password=config.password or secrets.get("kafka_password"),
        client_id=config.client_id,
        ssl_ca_location=config.ssl_ca_location,
        request_timeout_ms=config.request_timeout_ms,
        message_send_max_retries=config.message_send_max_retries,
        max_request_size=config.max_request_size,
        flush_timeout_seconds=config.flush_timeout_seconds,
        extra_config=config.extra_config,
    )


def _audit_messages(config: AppConfig, from_dt: datetime, to_dt: datetime, records: Iterable[Dict]) -> Iterable[Tuple[str, Dict]]:
    for record in records:
        message = {
            "source": "fusion_erp_audit",
            "extracted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "window": {
                "from": from_dt.isoformat(),
                "to": to_dt.isoformat(),
                "lookback_hours": config.lookback_hours,
            },
            "fusion": {
                "product": config.fusion.product,
                "business_object_type": config.fusion.business_object_type,
                "event_type": config.fusion.event_type,
            },
            "audit_record": record,
        }
        yield _message_key(record), message


def _message_key(record: Dict) -> str:
    key_fields = {
        "date": record.get("date"),
        "userInternalName": record.get("userInternalName"),
        "eventType": record.get("eventType"),
        "qualifiedBusinessObject": record.get("qualifiedBusinessObject"),
        "descriptionInternal": record.get("descriptionInternal"),
        "description": record.get("description"),
    }
    encoded = json.dumps(key_fields, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
