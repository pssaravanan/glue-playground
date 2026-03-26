variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "s3_bucket" {
  description = "S3 bucket holding raw/city=*/temperatures.csv"
  type        = string
  default     = "glue-s3-playground27"
}

variable "app_name" {
  description = "Name prefix for all resources (must match data_setup app_name)"
  type        = string
  default     = "city-temperature"
}
