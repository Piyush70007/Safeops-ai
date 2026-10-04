output "evidence_bucket" {
  value = module.evidence.bucket
}

output "ci_role_arn" {
  value       = module.github_oidc.role_arn
  description = "Use in GitHub Actions: aws-actions/configure-aws-credentials with role-to-assume"
}
