import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional


MAX_LOOKBACK_HOURS = 24 * 31


class ConfigurationError(ValueError):
    """Raised when invocation or function configuration is invalid."""


@dataclass(frozen=True)
class SecretReference:
    secret_id: Optional[str] = None
    vault_id: Optional[str] = None
    secret_name: Optional[str] = None


@dataclass(frozen=True)
class VaultSecretConfig:
    fusion_base_url_secret_id: Optional[str] = None
    fusion_username_secret_id: Optional[str] = None
    fusion_password_secret_id: Optional[str] = None
    kafka_username_secret_id: Optional[str] = None
    kafka_password_secret_id: Optional[str] = None
    vault_id: Optional[str] = None
    fusion_base_url_secret_name: str = "fusion-audit-api-base-url"
    fusion_username_secret_name: str = "fusion-audit-api-username"
    fusion_password_secret_name: str = "fusion-audit-api-password"
    kafka_username_secret_name: Optional[str] = None
    kafka_password_secret_name: Optional[str] = None

    def secret_references(self) -> Dict[str, SecretReference]:
        references = {
            "fusion_base_url": self._reference(
                self.fusion_base_url_secret_id,
                self.fusion_base_url_secret_name,
            ),
            "fusion_username": self._reference(
                self.fusion_username_secret_id,
                self.fusion_username_secret_name,
            ),
            "fusion_password": self._reference(
                self.fusion_password_secret_id,
                self.fusion_password_secret_name,
            ),
        }
        if self.kafka_username_secret_id:
            references["kafka_username"] = SecretReference(secret_id=self.kafka_username_secret_id)
        elif self.kafka_username_secret_name:
            references["kafka_username"] = self._reference(None, self.kafka_username_secret_name)
        if self.kafka_password_secret_id:
            references["kafka_password"] = SecretReference(secret_id=self.kafka_password_secret_id)
        elif self.kafka_password_secret_name:
            references["kafka_password"] = self._reference(None, self.kafka_password_secret_name)
        return references

    def _reference(self, secret_id: Optional[str], secret_name: Optional[str]) -> SecretReference:
        if secret_id:
            return SecretReference(secret_id=secret_id)
        return SecretReference(vault_id=self.vault_id, secret_name=secret_name)


@dataclass(frozen=True)
class FusionAuditConfig:
    product: str
    business_object_type: Optional[str] = None
    event_type: str = "all"
    request_mode: str = "body"
    page_size: int = 500
    max_pages: int = 100
    time_zone: str = "UTC"
    attribute_detail_mode: bool = True
    include_attributes: bool = True
    include_child_objects: bool = False
    include_extended_object_identifier_columns: bool = False
    include_impersonator: bool = False
    user: Optional[str] = None
    connect_timeout_seconds: int = 10
    read_timeout_seconds: int = 60


@dataclass(frozen=True)
class KafkaConfig:
    bootstrap_servers: str
    topic: str
    security_protocol: str = "SASL_SSL"
    sasl_mechanism: str = "PLAIN"
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: str = "fusion-audit-function"
    ssl_ca_location: Optional[str] = None
    request_timeout_ms: int = 30000
    message_send_max_retries: int = 5
    max_request_size: int = 1048576
    flush_timeout_seconds: float = 30.0
    extra_config: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AppConfig:
    vault: VaultSecretConfig
    fusion: FusionAuditConfig
    kafka: KafkaConfig
    lookback_hours: float
    dry_run: bool = False


def load_config(payload: Mapping[str, Any], function_config: Mapping[str, Any]) -> AppConfig:
    merged = _merge_default_config(payload, function_config)

    vault_data = _required_mapping(merged, "vault")
    fusion_data = _required_mapping(merged, "fusion")
    kafka_data = _required_mapping(merged, "kafka")

    lookback_hours = _number(merged, "lookback_hours", default=1)
    if lookback_hours <= 0:
        raise ConfigurationError("lookback_hours must be greater than 0.")
    if lookback_hours > MAX_LOOKBACK_HOURS:
        raise ConfigurationError(
            f"lookback_hours cannot exceed {MAX_LOOKBACK_HOURS}; Fusion audit history can only be retrieved for about one month."
        )

    vault = VaultSecretConfig(
        vault_id=_optional_str(vault_data, "vault_id"),
        fusion_base_url_secret_id=_optional_str(vault_data, "fusion_base_url_secret_id"),
        fusion_username_secret_id=_optional_str(vault_data, "fusion_username_secret_id"),
        fusion_password_secret_id=_optional_str(vault_data, "fusion_password_secret_id"),
        kafka_username_secret_id=_optional_str(vault_data, "kafka_username_secret_id"),
        kafka_password_secret_id=_optional_str(vault_data, "kafka_password_secret_id"),
        fusion_base_url_secret_name=_str(
            vault_data,
            "fusion_base_url_secret_name",
            "fusion-audit-api-base-url",
        ),
        fusion_username_secret_name=_str(
            vault_data,
            "fusion_username_secret_name",
            "fusion-audit-api-username",
        ),
        fusion_password_secret_name=_str(
            vault_data,
            "fusion_password_secret_name",
            "fusion-audit-api-password",
        ),
        kafka_username_secret_name=_optional_str(vault_data, "kafka_username_secret_name"),
        kafka_password_secret_name=_optional_str(vault_data, "kafka_password_secret_name"),
    )
    _validate_vault_references(vault)

    fusion = FusionAuditConfig(
        product=_required_str(fusion_data, "product"),
        business_object_type=_optional_str(fusion_data, "business_object_type"),
        event_type=_str(fusion_data, "event_type", "all"),
        request_mode=_choice(fusion_data, "request_mode", "body", {"body", "query"}),
        page_size=_positive_int(fusion_data, "page_size", 500),
        max_pages=_positive_int(fusion_data, "max_pages", 100),
        time_zone=_str(fusion_data, "time_zone", "UTC"),
        attribute_detail_mode=_bool(fusion_data, "attribute_detail_mode", True),
        include_attributes=_bool(fusion_data, "include_attributes", True),
        include_child_objects=_bool(fusion_data, "include_child_objects", False),
        include_extended_object_identifier_columns=_bool(
            fusion_data, "include_extended_object_identifier_columns", False
        ),
        include_impersonator=_bool(fusion_data, "include_impersonator", False),
        user=_optional_str(fusion_data, "user"),
        connect_timeout_seconds=_positive_int(fusion_data, "connect_timeout_seconds", 10),
        read_timeout_seconds=_positive_int(fusion_data, "read_timeout_seconds", 60),
    )

    kafka = KafkaConfig(
        bootstrap_servers=_required_str(kafka_data, "bootstrap_servers"),
        topic=_required_str(kafka_data, "topic"),
        security_protocol=_str(kafka_data, "security_protocol", "SASL_SSL"),
        sasl_mechanism=_str(kafka_data, "sasl_mechanism", "PLAIN"),
        username=_optional_str(kafka_data, "username"),
        password=_optional_str(kafka_data, "password"),
        client_id=_str(kafka_data, "client_id", "fusion-audit-function"),
        ssl_ca_location=_optional_str(kafka_data, "ssl_ca_location"),
        request_timeout_ms=_positive_int(kafka_data, "request_timeout_ms", 30000),
        message_send_max_retries=_positive_int(kafka_data, "message_send_max_retries", 5),
        max_request_size=_positive_int(kafka_data, "max_request_size", 1048576),
        flush_timeout_seconds=_number(kafka_data, "flush_timeout_seconds", 30.0),
        extra_config=_mapping(kafka_data, "extra_config", {}),
    )

    if kafka.security_protocol.upper().startswith("SASL"):
        has_username = bool(kafka.username or vault.kafka_username_secret_id or vault.kafka_username_secret_name)
        has_password = bool(kafka.password or vault.kafka_password_secret_id or vault.kafka_password_secret_name)
        if not has_username or not has_password:
            raise ConfigurationError(
                "Kafka SASL configuration requires kafka.username or vault.kafka_username_secret_id, "
                "and kafka.password or vault.kafka_password_secret_id."
            )

    return AppConfig(
        vault=vault,
        fusion=fusion,
        kafka=kafka,
        lookback_hours=lookback_hours,
        dry_run=_bool(merged, "dry_run", False),
    )


def _validate_vault_references(vault: VaultSecretConfig) -> None:
    if vault.vault_id:
        return

    required_secret_ids = (
        vault.fusion_base_url_secret_id,
        vault.fusion_username_secret_id,
        vault.fusion_password_secret_id,
    )
    if all(required_secret_ids) and not _has_unresolved_name_secret(vault):
        return
    raise ConfigurationError(
        "vault must include either all Fusion secret OCIDs or vault.vault_id with Fusion secret names."
    )


def _has_unresolved_name_secret(vault: VaultSecretConfig) -> bool:
    if vault.vault_id:
        return False
    return bool(
        (vault.kafka_username_secret_name and not vault.kafka_username_secret_id)
        or (vault.kafka_password_secret_name and not vault.kafka_password_secret_id)
    )


def _merge_default_config(payload: Mapping[str, Any], function_config: Mapping[str, Any]) -> Dict[str, Any]:
    config_json = (
        payload.get("config_json")
        or function_config.get("FUSION_AUDIT_CONFIG_JSON")
        or os.getenv("FUSION_AUDIT_CONFIG_JSON")
    )

    base: Dict[str, Any] = {}
    if config_json:
        try:
            decoded = json.loads(config_json)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"FUSION_AUDIT_CONFIG_JSON is not valid JSON: {exc}") from exc
        if not isinstance(decoded, dict):
            raise ConfigurationError("FUSION_AUDIT_CONFIG_JSON must decode to a JSON object.")
        base = decoded

    return _deep_merge(base, dict(payload))


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _required_mapping(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{key} must be provided as an object.")
    return value


def _mapping(mapping: Mapping[str, Any], key: str, default: Dict[str, Any]) -> Dict[str, Any]:
    value = mapping.get(key, default)
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{key} must be an object.")
    return dict(value)


def _required_str(mapping: Mapping[str, Any], key: str) -> str:
    value = _optional_str(mapping, key)
    if not value:
        raise ConfigurationError(f"{key} is required.")
    return value


def _optional_str(mapping: Mapping[str, Any], key: str) -> Optional[str]:
    value = mapping.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"{key} must be a string.")
    return value


def _str(mapping: Mapping[str, Any], key: str, default: str) -> str:
    value = mapping.get(key, default)
    if not isinstance(value, str) or value == "":
        raise ConfigurationError(f"{key} must be a non-empty string.")
    return value


def _choice(mapping: Mapping[str, Any], key: str, default: str, allowed: set) -> str:
    value = _str(mapping, key, default)
    if value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ConfigurationError(f"{key} must be one of: {allowed_values}.")
    return value


def _bool(mapping: Mapping[str, Any], key: str, default: bool) -> bool:
    value = mapping.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes", "y"):
            return True
        if normalized in ("false", "0", "no", "n"):
            return False
    raise ConfigurationError(f"{key} must be a boolean.")


def _number(mapping: Mapping[str, Any], key: str, default: float) -> float:
    value = mapping.get(key, default)
    if isinstance(value, bool):
        raise ConfigurationError(f"{key} must be a number.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{key} must be a number.") from exc


def _positive_int(mapping: Mapping[str, Any], key: str, default: int) -> int:
    value = mapping.get(key, default)
    if isinstance(value, bool):
        raise ConfigurationError(f"{key} must be a positive integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{key} must be a positive integer.") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{key} must be greater than 0.")
    return parsed
