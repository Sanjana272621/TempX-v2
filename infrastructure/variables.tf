variable "aws_region" {
  description = "AWS region for the project"
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Project name used for AWS resources"
  type        = string
  default     = "tempx-v2"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}

variable "telemetry_table_name" {
  description = "Existing or new DynamoDB telemetry table"
  type        = string
  default     = "tempx-telemetry"
}

variable "lambda_function_name" {
  description = "Telemetry storage Lambda name"
  type        = string
  default     = "tempx-store-telemetry"
}

variable "lambda_role_name" {
  description = "Lambda execution role name"
  type        = string
  default     = "tempx-store-telemetry-role"
}

variable "iot_rule_name" {
  description = "IoT Rule name; only letters, numbers and underscores"
  type        = string
  default     = "tempx_store_telemetry"
}

variable "iot_policy_name" {
  description = "Shared IoT device policy name"
  type        = string
  default     = "tempx-device-policy"
}

variable "device_ids" {
  description = "Simulated device Thing names"
  type        = set(string)

  default = [
    "sim-device-001",
    "sim-device-002",
    "sim-device-003",
  ]
}

variable "certificate_arns" {
  description = "Existing certificate ARN for each device"
  type        = map(string)
  default     = {}
}