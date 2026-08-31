output "api_url" {
  description = "Public URL of the deployed api service."
  value       = render_web_service.api.url
}

output "frontend_url" {
  description = "Public URL of the deployed frontend service."
  value       = render_web_service.frontend.url
}

output "postgres_connection_string" {
  description = "Connection string for the managed Postgres instance (app.core.config.Settings.database_url shape). Sensitive -- Terraform will not print this in plan/apply output."
  value       = render_postgres.main.connection_info.external_connection_string
  sensitive   = true
}

output "redis_connection_string" {
  description = "Connection string for the managed Key Value instance (app.core.config.Settings.redis_url shape). Sensitive."
  value       = render_keyvalue.main.connection_info.external_connection_string
  sensitive   = true
}

output "s3_bucket_name" {
  description = "Name of the S3 bucket provisioned for document/object storage in this environment."
  value       = aws_s3_bucket.documents.bucket
}

output "s3_access_key_id" {
  description = "Access key ID for the IAM user scoped to this environment's bucket. Sensitive."
  value       = aws_iam_access_key.documents.id
  sensitive   = true
}

output "s3_secret_access_key" {
  description = "Secret access key for the IAM user scoped to this environment's bucket. Sensitive."
  value       = aws_iam_access_key.documents.secret
  sensitive   = true
}
