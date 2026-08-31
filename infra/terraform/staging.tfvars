# terraform apply -var-file=staging.tfvars
#
# Secrets (jwt_signing_keys_json, connector_encryption_key, anthropic_api_key)
# are deliberately NOT in this file -- pass them via -var or TF_VAR_* env
# vars from the deploy workflow's secrets, never committed in plaintext.
# backend_image/frontend_image are also passed via -var from the deploy
# workflow (they change on every merge; a static value here would go stale
# immediately).

environment   = "staging"
render_region = "oregon"
aws_region    = "us-west-2"

api_plan      = "starter"
worker_plan   = "starter"
frontend_plan = "starter"
postgres_plan = "starter"
redis_plan    = "starter"

frontend_url = "https://helix-staging-frontend.onrender.com"
