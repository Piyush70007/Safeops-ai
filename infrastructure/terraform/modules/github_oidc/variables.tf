variable "name" {
  type = string
}

variable "github_repository" {
  type        = string
  description = "owner/repository, e.g. ankee/safeops-ai"
}

variable "evidence_bucket_arn" {
  type = string
}
