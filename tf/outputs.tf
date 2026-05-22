output "vault_id" {
  description = "OCID of the OCI Vault."
  value       = oci_kms_vault.fusion_audit.id
}

output "vault_management_endpoint" {
  description = "Vault management endpoint used by KMS operations."
  value       = oci_kms_vault.fusion_audit.management_endpoint
}

output "vault_crypto_endpoint" {
  description = "Vault crypto endpoint."
  value       = oci_kms_vault.fusion_audit.crypto_endpoint
}

output "vault_key_id" {
  description = "OCID of the KMS key used for Fusion API secrets."
  value       = oci_kms_key.fusion_audit_secrets.id
}

output "fusion_api_secret_ids" {
  description = "Map of Fusion API Vault secret names to secret OCIDs."
  value       = { for name, secret in oci_vault_secret.fusion_api : name => secret.id }
}

output "stream_pool_id" {
  description = "OCID of the OCI Streaming stream pool."
  value       = oci_streaming_stream_pool.fusion_audit.id
}

output "stream_pool_endpoint_fqdn" {
  description = "FQDN for the stream pool endpoint."
  value       = oci_streaming_stream_pool.fusion_audit.endpoint_fqdn
}

output "kafka_bootstrap_servers" {
  description = "Kafka-compatible bootstrap servers for producers and connectors."
  value       = try(oci_streaming_stream_pool.fusion_audit.kafka_settings[0].bootstrap_servers, null)
}

output "stream_id" {
  description = "OCID of the Fusion audit stream."
  value       = oci_streaming_stream.fusion_audit.id
}

output "stream_name" {
  description = "Name of the stream. Kafka-compatible clients use this as the topic name."
  value       = oci_streaming_stream.fusion_audit.name
}

output "stream_messages_endpoint" {
  description = "OCI Streaming messages endpoint for the stream."
  value       = oci_streaming_stream.fusion_audit.messages_endpoint
}

output "connect_harness_id" {
  description = "OCID of the Kafka Connect configuration."
  value       = oci_streaming_connect_harness.fusion_audit.id
}
