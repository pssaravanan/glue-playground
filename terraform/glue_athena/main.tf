terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

data "aws_s3_bucket" "output" {
  bucket = var.s3_bucket
}

# ---------------------------------------------------------------------------
# Glue Database
# ---------------------------------------------------------------------------

resource "aws_glue_catalog_database" "main" {
  name = replace(var.app_name, "-", "_")
}

# ---------------------------------------------------------------------------
# IAM – Glue Crawler Role
# ---------------------------------------------------------------------------

resource "aws_iam_role" "glue_crawler" {
  name = "${var.app_name}-glue-crawler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_crawler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3" {
  name = "${var.app_name}-glue-s3"
  role = aws_iam_role.glue_crawler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = [
        data.aws_s3_bucket.output.arn,
        "${data.aws_s3_bucket.output.arn}/*"
      ]
    }]
  })
}

# ---------------------------------------------------------------------------
# Glue Crawler – discovers city partitions under raw/
# ---------------------------------------------------------------------------

resource "aws_glue_crawler" "temperatures" {
  name          = "${var.app_name}-crawler"
  role          = aws_iam_role.glue_crawler.arn
  database_name = aws_glue_catalog_database.main.name

  s3_target {
    path = "s3://${var.s3_bucket}/raw/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  configuration = jsonencode({
    Version = 1.0
    Grouping = {
      TableGroupingPolicy = "CombineCompatibleSchemas"
    }
  })
}

# ---------------------------------------------------------------------------
# S3 bucket for Athena query results
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "athena_results" {
  bucket        = "${var.app_name}-athena-results-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

# ---------------------------------------------------------------------------
# Athena Workgroup
# ---------------------------------------------------------------------------

resource "aws_athena_workgroup" "main" {
  name = var.app_name

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.bucket}/results/"
    }
  }
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "glue_database" {
  value = aws_glue_catalog_database.main.name
}

output "glue_crawler_name" {
  value = aws_glue_crawler.temperatures.name
}

output "athena_workgroup" {
  value = aws_athena_workgroup.main.name
}

output "athena_results_bucket" {
  value = aws_s3_bucket.athena_results.bucket
}
