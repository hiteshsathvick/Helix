# One module, parameterized per environment via staging.tfvars/prod.tfvars
# (see main.tf's header comment for why this isn't a separate tree per env).

variable "environment" {
  description = "Deployment environment name (\"staging\" or \"production\") -- used as a name prefix/suffix for every resource so both environments can exist side by side under one Render account."
  type        = string
}

variable "render_region" {
  description = "Render region for all services + managed Postgres/Redis in this environment."
  type        = string
  default     = "oregon"
}

variable "aws_region" {
  description = "AWS region for the S3 bucket (SPEC.md storage layer is a plain boto3/S3-endpoint client, so any region works -- pick the one closest to render_region to minimize upload latency)."
  type        = string
  default     = "us-west-2"
}

variable "api_plan" {
  description = "Render service plan for the api process. Smaller in staging.tfvars, larger in prod.tfvars."
  type        = string
  default     = "starter"
}

variable "worker_plan" {
  description = "Render service plan for the worker process."
  type        = string
  default     = "starter"
}

variable "frontend_plan" {
  description = "Render service plan for the frontend process."
  type        = string
  default     = "starter"
}

variable "postgres_plan" {
  description = "Render managed Postgres plan."
  type        = string
  default     = "starter"
}

variable "redis_plan" {
  description = "Render managed Key Value (Redis-compatible) plan."
  type        = string
  default     = "starter"
}

variable "backend_image" {
  description = "Fully qualified ghcr.io image reference for the backend (api + worker share this image -- see infra/docker/backend.Dockerfile's \"single image, two entrypoints\" comment). Set from the deploy workflow's build output, e.g. ghcr.io/<owner>/helix-backend:<sha>."
  type        = string
}

variable "frontend_image" {
  description = "Fully qualified ghcr.io image reference for the frontend."
  type        = string
}

variable "jwt_signing_keys_json" {
  description = "JSON-encoded {kid: key} map for app.core.config.Settings.jwt_signing_keys. Marked sensitive -- passed as a Render secret env var, never committed."
  type        = string
  sensitive   = true
}

variable "connector_encryption_key" {
  description = "Fernet key for app.core.config.Settings.connector_encryption_key. Marked sensitive -- passed as a Render secret env var, never committed."
  type        = string
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Real Anthropic API key for this environment. Marked sensitive."
  type        = string
  sensitive   = true
  default     = ""
}

variable "frontend_url" {
  description = "Public URL of the frontend service, used for CORS (app.core.config.Settings.frontend_url) and OAuth redirect URLs."
  type        = string
}
