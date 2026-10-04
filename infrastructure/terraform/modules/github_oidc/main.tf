# GitHub Actions -> AWS without any stored secret: OIDC federation.
# A workflow run proves who it is with a short-lived token; AWS issues 1-hour credentials
# ONLY for this repository's main branch. Nothing to leak, nothing to rotate.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "ci" {
  name                 = "${var.name}-github-ci"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "evidence_upload" {
  statement {
    sid       = "UploadEvidenceOnly"
    actions   = ["s3:PutObject"]
    resources = ["${var.evidence_bucket_arn}/ci/*"]
  }
}

resource "aws_iam_role_policy" "evidence_upload" {
  name   = "upload-evidence"
  role   = aws_iam_role.ci.id
  policy = data.aws_iam_policy_document.evidence_upload.json
}
