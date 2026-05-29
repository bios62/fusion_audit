variable "tenancy_ocid" {
  description = "OCI tenancy OCID used by the provider."
  type        = string
}

variable "user_ocid" {
  description = "OCI user OCID used by the provider."
  type        = string
}

variable "fingerprint" {
  description = "Fingerprint for the OCI API signing key."
  type        = string
}

variable "private_key_path" {
  description = "Filesystem path to the OCI API signing private key."
  type        = string
}

variable "private_key_password" {
  description = "Optional password for the OCI API signing private key."
  type        = string
  default     = null
  sensitive   = true
}

variable "region" {
  description = "OCI region identifier, for example eu-frankfurt-1."
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment OCID where the Fusion audit resources will be created."
  type        = string
}

variable "defined_tags" {
  description = "Defined tags to apply to OCI resources."
  type        = map(string)
  default     = {}
}

variable "freeform_tags" {
  description = "Free-form tags to apply to OCI resources."
  type        = map(string)
  default     = {}
}

variable "vault_display_name" {
  description = "Display name for the OCI Vault."
  type        = string
}

variable "vault_type" {
  description = "OCI Vault type. DEFAULT is the standard shared vault; VIRTUAL_PRIVATE uses a dedicated HSM."
  type        = string
  default     = "DEFAULT"

  validation {
    condition     = contains(["DEFAULT", "VIRTUAL_PRIVATE"], var.vault_type)
    error_message = "vault_type must be DEFAULT or VIRTUAL_PRIVATE."
  }
}

variable "vault_key_display_name" {
  description = "Display name for the KMS key used to encrypt Fusion API secrets."
  type        = string
}

variable "vault_key_protection_mode" {
  description = "Protection mode for the KMS key. SOFTWARE is the default requested for this project."
  type        = string
  default     = "SOFTWARE"

  validation {
    condition     = contains(["SOFTWARE", "HSM"], var.vault_key_protection_mode)
    error_message = "vault_key_protection_mode must be SOFTWARE or HSM."
  }
}

variable "vault_key_shape_algorithm" {
  description = "Algorithm for the KMS key shape."
  type        = string
  default     = "AES"
}

variable "vault_key_shape_length" {
  description = "Key length, in bytes, for the KMS key shape."
  type        = number
  default     = 32
}

variable "fusion_api_secrets" {
  description = "Map of OCI Vault secret names to Fusion API credential values."
  type        = map(string)
  sensitive   = true

  validation {
    condition     = length(var.fusion_api_secrets) > 0
    error_message = "fusion_api_secrets must contain at least one secret."
  }
}

variable "stream_pool_name" {
  description = "Name of the OCI Streaming stream pool that exposes Kafka-compatible settings."
  type        = string
}

variable "stream_pool_auto_create_topics_enable" {
  description = "Whether Kafka compatibility should auto-create topics in the stream pool."
  type        = bool
  default     = false
}

variable "stream_pool_log_retention_hours" {
  description = "Kafka log retention setting for the stream pool, in hours."
  type        = number
  default     = 24
}

variable "stream_pool_num_partitions" {
  description = "Default number of partitions for Kafka topics in the stream pool."
  type        = number
  default     = 1

  validation {
    condition     = var.stream_pool_num_partitions > 0
    error_message = "stream_pool_num_partitions must be greater than zero."
  }
}

variable "stream_pool_use_vault_key_for_encryption" {
  description = "When true, use the KMS key created for this project as the stream pool custom encryption key."
  type        = bool
  default     = false
}

variable "stream_pool_private_subnet_ocid" {
  description = "Optional subnet OCID for a private stream pool endpoint."
  type        = string
  default     = null
}

variable "stream_pool_private_nsg_ocids" {
  description = "Optional NSG OCIDs for the private stream pool endpoint."
  type        = list(string)
  default     = []
}

variable "stream_pool_private_endpoint_ip" {
  description = "Optional private IP to assign to the private stream pool endpoint."
  type        = string
  default     = null
}

variable "stream_name" {
  description = "Name of the OCI Streaming stream. This is the Kafka topic name for Kafka-compatible producers."
  type        = string
}

variable "stream_partitions" {
  description = "Number of partitions for the Fusion audit stream."
  type        = number
  default     = 1

  validation {
    condition     = var.stream_partitions > 0
    error_message = "stream_partitions must be greater than zero."
  }
}

variable "stream_retention_in_hours" {
  description = "Retention period for stream messages. OCI accepts 24 through 168 hours."
  type        = number
  default     = 24

  validation {
    condition     = var.stream_retention_in_hours >= 24 && var.stream_retention_in_hours <= 168
    error_message = "stream_retention_in_hours must be between 24 and 168."
  }
}

variable "connect_harness_name" {
  description = "Name of the OCI Streaming Kafka Connect configuration."
  type        = string
}

variable "log_group_display_name" {
  description = "Display name for the OCI Logging log group."
  type        = string
}

variable "log_group_description" {
  description = "Description for the OCI Logging log group."
  type        = string
  default     = "Fusion audit log group."
}

variable "custom_log_display_name" {
  description = "Display name for the OCI custom log used for Fusion audit events."
  type        = string
}

variable "custom_log_retention_duration" {
  description = "Custom log retention duration in days. OCI supports 30-day increments up to 180."
  type        = number
  default     = 30

  validation {
    condition     = contains([30, 60, 90, 120, 150, 180], var.custom_log_retention_duration)
    error_message = "custom_log_retention_duration must be one of 30, 60, 90, 120, 150, or 180."
  }
}

variable "custom_log_is_enabled" {
  description = "Whether the Fusion audit custom log is enabled."
  type        = bool
  default     = true
}
