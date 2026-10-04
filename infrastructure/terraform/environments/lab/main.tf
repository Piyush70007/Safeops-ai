# SafeOps AI cloud footprint: identity for CI and an evidence store. Costs cents per month.
provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "safeops-ai"
      ManagedBy = "terraform"
      Owner     = var.owner
    }
  }
}

module "evidence" {
  source      = "../../modules/evidence"
  name        = "safeops"
  object_lock = var.evidence_object_lock
}

module "github_oidc" {
  source              = "../../modules/github_oidc"
  name                = "safeops"
  github_repository   = var.github_repository
  evidence_bucket_arn = module.evidence.bucket_arn
}

resource "aws_budgets_budget" "monthly" {
  name         = "safeops-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}
