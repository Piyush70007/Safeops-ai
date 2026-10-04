variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "owner" {
  type = string
}

variable "github_repository" {
  type        = string
  description = "owner/repository allowed to assume the CI role"
}

variable "alert_email" {
  type = string
}

variable "monthly_budget_usd" {
  type    = number
  default = 10
}

variable "evidence_object_lock" {
  type    = bool
  default = false
}
