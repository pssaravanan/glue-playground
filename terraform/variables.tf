variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "s3_bucket" {
  description = "Existing S3 bucket name for output"
  type        = string
  default     = "glue-s3-playground27"
}

variable "app_name" {
  description = "Name prefix for all resources"
  type        = string
  default     = "city-temperature"
}

variable "task_cpu" {
  description = "ECS task CPU units (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "ECS task memory in MiB"
  type        = number
  default     = 1024
}

variable "s3_input_key" {
  description = "S3 key for the source city_temperature.csv file"
  type        = string
  default     = "city_temperature.csv"
}
