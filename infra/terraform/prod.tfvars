# terraform apply -var-file=prod.tfvars
#
# See staging.tfvars' header comment: secrets and the two image vars are
# passed separately, never committed here.

environment   = "production"
render_region = "oregon"
aws_region    = "us-west-2"

# Sized up from staging.tfvars' "starter" plans -- prod carries real
# traffic and can't share staging's smallest tier.
api_plan      = "standard"
worker_plan   = "standard"
frontend_plan = "standard"
postgres_plan = "standard"
redis_plan    = "standard"

frontend_url = "https://helix.example.com"
