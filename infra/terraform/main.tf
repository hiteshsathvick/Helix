# Helix cloud infrastructure (SPEC.md §33/§36, ADR 0003).
#
# One parameterized module, not a tree per environment: staging and prod
# differ only in variable values (instance sizes, image tags, secrets),
# never in shape -- staging.tfvars/prod.tfvars carry that difference via
# `terraform apply -var-file=<env>.tfvars`. CLAUDE.md's "don't design for
# hypothetical requirements" argues against a module/environment split
# neither environment currently needs.
#
# NOT applied against a real account (Phase 22 scope: "pipeline + IaC only,
# no live cloud" -- see ADR 0003). This is real, complete, `terraform
# validate`-clean code, ready to `apply` once real Render/AWS credentials
# exist.
#
# State: local (terraform.tfstate, gitignored), the default with no backend
# block. A remote backend is the right answer before two people or CI ever
# run `apply` concurrently, but an S3 remote backend needs a bucket that
# would itself have to be Terraform-managed first (or created by hand) --
# a chicken-and-egg problem not worth solving speculatively before this
# code has ever been applied once. Real next step when that day comes:
# either a manually-created bootstrap state bucket, or Terraform Cloud's
# free tier (no bootstrap resource needed at all).

terraform {
  required_version = ">= 1.5"
  required_providers {
    render = {
      source  = "render-oss/render"
      version = "~> 1.4"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "render" {
  # RENDER_API_KEY env var (never a committed value -- see staging.tfvars'
  # header comment).
}

provider "aws" {
  region = var.aws_region
}

# -- Managed data stores --------------------------------------------------

resource "render_postgres" "main" {
  name    = "helix-${var.environment}-db"
  plan    = var.postgres_plan
  region  = var.render_region
  version = "16"
}

resource "render_keyvalue" "main" {
  name   = "helix-${var.environment}-redis"
  plan   = var.redis_plan
  region = var.render_region
  # arq (backend/app/core/queue.py) doesn't need Redis to retain data under
  # memory pressure -- job payloads are transient, not a durable store --
  # so evicting the least-recently-used key is the safe default rather than
  # noeviction (which would instead reject new writes once memory fills).
  max_memory_policy = "allkeys_lru"
}

# -- Compute ---------------------------------------------------------------
# api and worker share one image (infra/docker/backend.Dockerfile's "single
# image, two entrypoints" -- app/main.py vs app/workers/run.py), differing
# only in start_command, same as docker-compose.yml's api/worker services.

resource "render_web_service" "api" {
  name   = "helix-${var.environment}-api"
  plan   = var.api_plan
  region = var.render_region

  runtime_source = {
    image = {
      image_url = var.backend_image
    }
  }

  start_command = "uvicorn app.main:app --host 0.0.0.0 --port 8000"

  env_vars = local.backend_env_vars
}

resource "render_background_worker" "worker" {
  name   = "helix-${var.environment}-worker"
  plan   = var.worker_plan
  region = var.render_region

  runtime_source = {
    image = {
      image_url = var.backend_image
    }
  }

  start_command = "python -m app.workers.run"

  env_vars = local.backend_env_vars
}

resource "render_web_service" "frontend" {
  name   = "helix-${var.environment}-frontend"
  plan   = var.frontend_plan
  region = var.render_region

  runtime_source = {
    image = {
      image_url = var.frontend_image
    }
  }

  env_vars = {
    NEXT_PUBLIC_API_URL = { value = render_web_service.api.url }
  }
}

# api and worker need the identical settings env vars (both processes read
# app.core.config.Settings) -- defined once here rather than duplicated at
# both resources above.
locals {
  backend_env_vars = {
    DATABASE_URL             = { value = render_postgres.main.connection_info.internal_connection_string }
    MIGRATIONS_DATABASE_URL  = { value = render_postgres.main.connection_info.internal_connection_string }
    REDIS_URL                = { value = render_keyvalue.main.connection_info.internal_connection_string }
    S3_ENDPOINT_URL          = { value = "https://s3.${var.aws_region}.amazonaws.com" }
    S3_ACCESS_KEY            = { value = aws_iam_access_key.documents.id }
    S3_SECRET_KEY            = { value = aws_iam_access_key.documents.secret }
    S3_BUCKET                = { value = aws_s3_bucket.documents.bucket }
    JWT_SIGNING_KEYS         = { value = var.jwt_signing_keys_json }
    CONNECTOR_ENCRYPTION_KEY = { value = var.connector_encryption_key }
    ANTHROPIC_API_KEY        = { value = var.anthropic_api_key }
    FRONTEND_URL             = { value = var.frontend_url }
    ENVIRONMENT              = { value = var.environment }
  }
}
