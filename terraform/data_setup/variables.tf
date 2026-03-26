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
  default     = 1024 # 1 vCPU
}

variable "task_memory" {
  description = "ECS task memory in MiB"
  type        = number
  default     = 3072 # 134 MB CSV expands to ~500 MB in pandas; 3 GB gives safe headroom
}

variable "s3_input_key" {
  description = "S3 key for the source city_temperature.csv file"
  type        = string
  default     = "city_temperature.csv"
}
