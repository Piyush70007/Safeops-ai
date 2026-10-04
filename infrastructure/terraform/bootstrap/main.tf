# One-time bootstrap: the S3 bucket that stores Terraform state for all environments.
# This folder itself uses LOCAL state (the bucket cannot store its own creation).
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "safeops-ai"
      ManagedBy = "terraform"
      Component = "bootstrap"
    }
  }
}

variable "region" {
  type    = string
  default = "eu-central-1"
}

data "aws_caller_identity" "current" {}

locals {
  bucket_name = "safeops-tfstate-${data.aws_caller_identity.current.account_id}-${var.region}"
}

resource "aws_s3_bucket" "state" {
  #checkov:skip=CKV_AWS_18:Access logging for the state bucket is out of scope for the lab (cost); CloudTrail records API access.
  #checkov:skip=CKV_AWS_144:Cross-region replication is not required for a training project (RSK-007 accepted).
  #checkov:skip=CKV2_AWS_62:No event notifications needed for the state bucket.
  #checkov:skip=CKV_AWS_145:SSE-KMS with the AWS managed key avoids the monthly cost of a customer managed key.
  bucket = local.bucket_name

  lifecycle {
    prevent_destroy = true # losing the state means Terraform forgets what it created
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled" # every state change is kept; corrupted state can be rolled back
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.tls_only.json
}

output "state_bucket" {
  value       = aws_s3_bucket.state.bucket
  description = "Use as: terraform init -backend-config=\"bucket=<this value>\""
}
