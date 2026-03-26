output "ecr_repository_url" {
  description = "ECR repository URL — use this to tag and push the Docker image"
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "ecs_task_definition_arn" {
  description = "ECS task definition ARN"
  value       = aws_ecs_task_definition.app.arn
}

output "push_and_run_commands" {
  description = "Commands to build, push, and run the task"
  value = <<-EOT
    # 1. Authenticate Docker to ECR
    aws ecr get-login-password --region ${var.aws_region} \
      | docker login --username AWS --password-stdin ${aws_ecr_repository.app.repository_url}

    # 2. Build and push image
    docker build -t ${aws_ecr_repository.app.repository_url}:latest data_setup/
    docker push ${aws_ecr_repository.app.repository_url}:latest

    # 3. Run Fargate Spot task
    aws ecs run-task \
      --cluster ${aws_ecs_cluster.main.name} \
      --task-definition ${aws_ecs_task_definition.app.family} \
      --launch-type FARGATE \
      --capacity-provider-strategy capacityProvider=FARGATE_SPOT,weight=1 \
      --network-configuration "awsvpcConfiguration={subnets=[${join(",", data.aws_subnets.default.ids)}],securityGroups=[${aws_security_group.task.id}],assignPublicIp=ENABLED}" \
      --region ${var.aws_region}
  EOT
}
