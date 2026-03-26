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

data "aws_s3_bucket" "output" {
  bucket = var.s3_bucket
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Reference the ECS cluster and execution role created by data_setup
data "aws_ecs_cluster" "main" {
  cluster_name = var.app_name
}

data "aws_iam_role" "execution" {
  name = "${var.app_name}-execution-role"
}

# ---------------------------------------------------------------------------
# CloudWatch Log Group
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "trino" {
  name              = "/ecs/${var.app_name}-trino"
  retention_in_days = 7
}

# ---------------------------------------------------------------------------
# IAM – Trino Task Role (Glue + S3 read)
# ---------------------------------------------------------------------------

resource "aws_iam_role" "trino_task" {
  name = "${var.app_name}-trino-task-role"

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
  name = "${var.app_name}-trino-glue-s3"
  role = aws_iam_role.trino_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable",
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
  family                   = "${var.app_name}-trino"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 2048
  memory                   = 8192
  execution_role_arn       = data.aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.trino_task.arn

  container_definitions = jsonencode([{
    name      = "trino"
    image     = "trinodb/trino:latest"
    essential = true

    entryPoint = ["/bin/sh", "-c"]
    command    = [
      "node_id=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16); grep -q '^node.id=' /etc/trino/node.properties 2>/dev/null || echo \"node.id=$node_id\" >> /etc/trino/node.properties; grep -q 'http-server.process-forwarded' /etc/trino/config.properties 2>/dev/null || echo 'http-server.process-forwarded=true' >> /etc/trino/config.properties; exec /usr/lib/trino/bin/run-trino"
    ]

    portMappings = [{ containerPort = 8080, protocol = "tcp" }]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.trino.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "ecs"
      }
    }
  }])
}

# ---------------------------------------------------------------------------
# Security Groups
# ---------------------------------------------------------------------------

resource "aws_security_group" "trino_alb" {
  name        = "${var.app_name}-trino-alb-sg"
  description = "Trino ALB"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "trino" {
  name        = "${var.app_name}-trino-sg"
  description = "Trino coordinator"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.trino_alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---------------------------------------------------------------------------
# Application Load Balancer
# ---------------------------------------------------------------------------

resource "aws_lb" "trino" {
  name               = "${var.app_name}-trino-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.trino_alb.id]
  subnets            = data.aws_subnets.default.ids
}

resource "aws_lb_target_group" "trino" {
  name        = "${var.app_name}-trino-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip"

  health_check {
    path                = "/v1/info"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
  }
}

resource "aws_lb_listener" "trino" {
  load_balancer_arn = aws_lb.trino.arn
  port              = 8080
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.trino.arn
  }
}

# ---------------------------------------------------------------------------
# ECS Service – keeps one Trino coordinator running
# ---------------------------------------------------------------------------

resource "aws_ecs_service" "trino" {
  name            = "${var.app_name}-trino"
  cluster         = data.aws_ecs_cluster.main.arn
  task_definition = aws_ecs_task_definition.trino.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.trino.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.trino.arn
    container_name   = "trino"
    container_port   = 8080
  }

  depends_on = [aws_lb_listener.trino]
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "trino_service_name" {
  value = aws_ecs_service.trino.name
}

output "trino_url" {
  value = "http://${aws_lb.trino.dns_name}:8080"
}
