locals {
  fusion_api_secret_names = toset(keys(nonsensitive(var.fusion_api_secrets)))
}

resource "oci_kms_vault" "fusion_audit" {
  compartment_id = var.compartment_ocid
  display_name   = var.vault_display_name
  vault_type     = var.vault_type

  defined_tags  = var.defined_tags
  freeform_tags = var.freeform_tags
}

resource "oci_kms_key" "fusion_audit_secrets" {
  compartment_id      = var.compartment_ocid
  display_name        = var.vault_key_display_name
  management_endpoint = oci_kms_vault.fusion_audit.management_endpoint
  protection_mode     = var.vault_key_protection_mode

  key_shape {
    algorithm = var.vault_key_shape_algorithm
    length    = var.vault_key_shape_length
  }

  defined_tags  = var.defined_tags
  freeform_tags = var.freeform_tags
}

resource "oci_vault_secret" "fusion_api" {
  for_each = local.fusion_api_secret_names

  compartment_id = var.compartment_ocid
  key_id         = oci_kms_key.fusion_audit_secrets.id
  secret_name    = each.key
  vault_id       = oci_kms_vault.fusion_audit.id

  secret_content {
    content      = base64encode(var.fusion_api_secrets[each.key])
    content_type = "BASE64"
  }

  defined_tags  = var.defined_tags
  freeform_tags = var.freeform_tags
}

resource "oci_streaming_stream_pool" "fusion_audit" {
  compartment_id = var.compartment_ocid
  name           = var.stream_pool_name

  dynamic "custom_encryption_key" {
    for_each = var.stream_pool_use_vault_key_for_encryption ? [oci_kms_key.fusion_audit_secrets.id] : []

    content {
      kms_key_id = custom_encryption_key.value
    }
  }

  kafka_settings {
    auto_create_topics_enable = var.stream_pool_auto_create_topics_enable
    log_retention_hours       = var.stream_pool_log_retention_hours
    num_partitions            = var.stream_pool_num_partitions
  }

  dynamic "private_endpoint_settings" {
    for_each = var.stream_pool_private_subnet_ocid == null ? [] : [var.stream_pool_private_subnet_ocid]

    content {
      nsg_ids             = var.stream_pool_private_nsg_ocids
      private_endpoint_ip = var.stream_pool_private_endpoint_ip
      subnet_id           = private_endpoint_settings.value
    }
  }

  defined_tags  = var.defined_tags
  freeform_tags = var.freeform_tags
}

resource "oci_streaming_stream" "fusion_audit" {
  name               = var.stream_name
  partitions         = var.stream_partitions
  retention_in_hours = var.stream_retention_in_hours
  stream_pool_id     = oci_streaming_stream_pool.fusion_audit.id

  defined_tags  = var.defined_tags
  freeform_tags = var.freeform_tags
}

resource "oci_streaming_connect_harness" "fusion_audit" {
  compartment_id = var.compartment_ocid
  name           = var.connect_harness_name

  defined_tags  = var.defined_tags
  freeform_tags = var.freeform_tags
}

resource "oci_logging_log_group" "fusion_audit" {
  compartment_id = var.compartment_ocid
  display_name   = var.log_group_display_name
  description    = var.log_group_description

  defined_tags  = var.defined_tags
  freeform_tags = var.freeform_tags
}

resource "oci_logging_log" "fusion_audit_custom" {
  display_name       = var.custom_log_display_name
  log_group_id       = oci_logging_log_group.fusion_audit.id
  log_type           = "CUSTOM"
  is_enabled         = var.custom_log_is_enabled
  retention_duration = var.custom_log_retention_duration

  defined_tags  = var.defined_tags
  freeform_tags = var.freeform_tags
}
