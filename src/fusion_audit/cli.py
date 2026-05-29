import argparse
import json
import logging
from typing import Any, Dict

from fusion_audit.config import ConfigurationError, TARGET_KAFKA, TARGET_OCI_LOG, load_config


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level)

    try:
        payload = _payload_from_args(args)
        config = load_config(payload, {})

        from fusion_audit.runtime import run_audit_export
        from fusion_audit.vault import VaultSecretProvider

        secret_provider = VaultSecretProvider(
            profile=args.profile,
            config_file=args.config_file,
            use_resource_principal=False,
        )
        oci_log_publisher = None
        if config.target == TARGET_OCI_LOG:
            from fusion_audit.oci_log_publisher import OciLogPublisher

            oci_log_publisher = OciLogPublisher(
                config.oci_log,
                profile=args.profile,
                config_file=args.config_file,
                use_resource_principal=False,
            )
        result = run_audit_export(
            config,
            secret_provider=secret_provider,
            oci_log_publisher=oci_log_publisher,
        )
    except ConfigurationError as exc:
        parser.error(str(exc))
    except Exception:
        logging.exception("Command-line Fusion audit export failed")
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pull Fusion ERP audit history and publish records to Kafka or OCI Logging."
    )

    parser.add_argument(
        "--profile",
        default="DEFAULT",
        help="OCI config profile to use from ~/.oci/config. Defaults to DEFAULT.",
    )
    parser.add_argument(
        "--config-file",
        default=None,
        help="Optional path to the OCI config file. Defaults to ~/.oci/config.",
    )
    parser.add_argument(
        "--vault-id",
        required=True,
        help="OCI Vault OCID containing the Fusion credential secrets.",
    )
    parser.add_argument(
        "--fusion-base-url-secret-name",
        default="fusion-audit-api-base-url",
        help="Vault secret name for the Fusion API base URL.",
    )
    parser.add_argument(
        "--fusion-username-secret-name",
        default="fusion-audit-api-username",
        help="Vault secret name for the Fusion API username.",
    )
    parser.add_argument(
        "--fusion-password-secret-name",
        default="fusion-audit-api-password",
        help="Vault secret name for the Fusion API password.",
    )
    parser.add_argument(
        "--lookback-hours",
        type=float,
        default=1,
        help="Number of hours of Fusion audit history to pull. Defaults to 1.",
    )
    parser.add_argument(
        "--fusion-product",
        required=True,
        help="Fusion audit product value, for example OPSS.",
    )
    parser.add_argument(
        "--fusion-business-object-type",
        default=None,
        help="Optional Fusion audit business object type filter.",
    )
    parser.add_argument(
        "--fusion-event-type",
        default="all",
        help="Fusion audit event type. Defaults to all.",
    )
    parser.add_argument(
        "--fusion-request-mode",
        choices=("body", "query"),
        default="body",
        help="Send Fusion audit parameters in the JSON body or query string. Defaults to body.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=500,
        help="Fusion audit page size. Defaults to 500.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=100,
        help="Maximum number of Fusion audit pages to read. Defaults to 100.",
    )
    parser.add_argument(
        "--target",
        choices=(TARGET_KAFKA, "oci-log", TARGET_OCI_LOG),
        default=TARGET_KAFKA,
        help="Publish target: kafka or oci-log. Defaults to kafka.",
    )
    parser.add_argument(
        "--kafka-bootstrap-servers",
        default=None,
        help="Kafka bootstrap servers. Required when --target kafka.",
    )
    parser.add_argument(
        "--kafka-topic",
        default=None,
        help="Kafka topic name. Required when --target kafka.",
    )
    parser.add_argument(
        "--kafka-username",
        default=None,
        help="Kafka SASL username. Required when --target kafka with SASL.",
    )

    kafka_password = parser.add_mutually_exclusive_group()
    kafka_password.add_argument(
        "--kafka-password",
        help="Kafka SASL password. Required when --target kafka with SASL unless --kafka-password-secret-name is used.",
    )
    kafka_password.add_argument(
        "--kafka-password-secret-name",
        help="Vault secret name containing the Kafka SASL password. Required when --target kafka with SASL unless --kafka-password is used.",
    )

    parser.add_argument(
        "--kafka-security-protocol",
        default="SASL_SSL",
        help="Kafka security protocol. Defaults to SASL_SSL.",
    )
    parser.add_argument(
        "--kafka-sasl-mechanism",
        default="PLAIN",
        help="Kafka SASL mechanism. Defaults to PLAIN.",
    )
    parser.add_argument(
        "--kafka-client-id",
        default="fusion-audit-cli",
        help="Kafka client id. Defaults to fusion-audit-cli.",
    )
    parser.add_argument(
        "--oci-log-id",
        default=None,
        help="OCI custom log OCID. Required when --target oci-log.",
    )
    parser.add_argument(
        "--oci-log-source",
        default="fusion_audit_cli",
        help="OCI custom log entry source. Defaults to fusion_audit_cli.",
    )
    parser.add_argument(
        "--oci-log-type",
        default="fusion.audit",
        help="OCI custom log entry type. Defaults to fusion.audit.",
    )
    parser.add_argument(
        "--oci-log-subject",
        default="fusion_erp_audit",
        help="OCI custom log entry subject. Defaults to fusion_erp_audit.",
    )
    parser.add_argument(
        "--oci-log-batch-size",
        type=int,
        default=100,
        help="Number of audit records per OCI Logging ingestion request. Defaults to 100.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read Vault secrets and Fusion audit records, but do not publish to Kafka or OCI Logging.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Python logging level. Defaults to INFO.",
    )

    return parser


def _payload_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    target = args.target.replace("-", "_")
    vault = {
        "vault_id": args.vault_id,
        "fusion_base_url_secret_name": args.fusion_base_url_secret_name,
        "fusion_username_secret_name": args.fusion_username_secret_name,
        "fusion_password_secret_name": args.fusion_password_secret_name,
    }
    if args.kafka_password_secret_name:
        vault["kafka_password_secret_name"] = args.kafka_password_secret_name

    payload = {
        "target": target,
        "lookback_hours": args.lookback_hours,
        "dry_run": args.dry_run,
        "vault": vault,
        "fusion": {
            "product": args.fusion_product,
            "business_object_type": args.fusion_business_object_type,
            "event_type": args.fusion_event_type,
            "request_mode": args.fusion_request_mode,
            "page_size": args.page_size,
            "max_pages": args.max_pages,
        },
    }
    if target == TARGET_KAFKA:
        payload["kafka"] = {
            "bootstrap_servers": args.kafka_bootstrap_servers,
            "topic": args.kafka_topic,
            "security_protocol": args.kafka_security_protocol,
            "sasl_mechanism": args.kafka_sasl_mechanism,
            "username": args.kafka_username,
            "password": args.kafka_password,
            "client_id": args.kafka_client_id,
        }
    if target == TARGET_OCI_LOG:
        payload["oci_log"] = {
            "log_id": args.oci_log_id,
            "source": args.oci_log_source,
            "type": args.oci_log_type,
            "subject": args.oci_log_subject,
            "batch_size": args.oci_log_batch_size,
        }
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
