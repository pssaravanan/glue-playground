# ---------------------------------------------------------------------------
# Trino coordinator on ECS Fargate – conditional on var.enable_trino
# Enable with: terraform apply -var="enable_trino=true"
#
# Uses the Glue catalog as metastore (no separate Hive needed).
# Requires enable_glue_athena=true so the Glue database exists.
# ---------------------------------------------------------------------------

locals {
  trino_config = var.enable_trino ? {
    "config.properties" = <<-EOT
      coordinator=true
      node-scheduler.include-coordinator=true
      http-server.http.port=8080
      discovery.uri=http://localhost:8080
    EOT

    "jvm.config" = <<-EOT
      -server
      -Xmx4G
      -XX:+UseG1GC
      -XX:G1HeapRegionSize=32M
      -XX:+UseGCOverheadLimit
      -XX:+ExplicitGCInvokesConcurrent
      -XX:+HeapDumpOnOutOfMemoryError
    EOT

    # Hive connector pointing at the Glue catalog
    "catalog/hive.properties" = <<-EOT
      connector.name=hive
      hive.metastore=glue
      hive.metastore.glue.region=${var.aws_region}
      hive.s3.region=${var.aws_region}
    EOT
  } : {}
}

# ---------------------------------------------------------------------------
# CloudWatch Log Group
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "trino" {
  count             = var.enable_trino ? 1 : 0
  name              = "/ecs/${var.app_name}-trino"
  retention_in_days = 7
}

# ---------------------------------------------------------------------------
# IAM – Trino Task Role (Glue + S3 read)
# ---------------------------------------------------------------------------

resource "aws_iam_role" "trino_task" {
  count = var.enable_trino ? 1 : 0
  name  = "${var.app_name}-trino-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "trino_glue_s3" {
  count = var.enable_trino ? 1 : 0
  name  = "${var.app_name}-trino-glue-s3"
  role  = aws_iam_role.trino_task[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable",
                    "glue:GetTables", "glue:GetPartition", "glue:GetPartitions"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          data.aws_s3_bucket.output.arn,
          "${data.aws_s3_bucket.output.arn}/*"
        ]
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# ECS Task Definition
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "trino" {
  count                    = var.enable_trino ? 1 : 0
  family                   = "${var.app_name}-trino"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 2048
  memory                   = 8192
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.trino_task[0].arn

  container_definitions = jsonencode([{
    name      = "trino"
    image     = "trinodb/trino:latest"
    essential = true

    portMappings = [{ containerPort = 8080, protocol = "tcp" }]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.trino[0].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "ecs"
      }
    }
  }])
}

# ---------------------------------------------------------------------------
# Security Group (allows inbound 8080 from within VPC)
# ---------------------------------------------------------------------------

resource "aws_security_group" "trino" {
  count       = var.enable_trino ? 1 : 0
  name        = "${var.app_name}-trino-sg"
  description = "Trino coordinator"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.default.cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---------------------------------------------------------------------------
# ECS Service – keeps one Trino coordinator running
# ---------------------------------------------------------------------------

resource "aws_ecs_service" "trino" {
  count           = var.enable_trino ? 1 : 0
  name            = "${var.app_name}-trino"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.trino[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.trino[0].id]
    assign_public_ip = true
  }
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "trino_service_name" {
  value = var.enable_trino ? aws_ecs_service.trino[0].name : null
}
