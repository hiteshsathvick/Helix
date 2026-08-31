# Object storage (SPEC.md storage layer -- backend/app/core/storage.py is a
# plain boto3/S3-endpoint client already, so pointing it at real AWS S3
# instead of MinIO needs zero application code changes, only different
# S3_* env vars, wired in main.tf's local.backend_env_vars).

resource "aws_s3_bucket" "documents" {
  bucket = "helix-${var.environment}-documents"
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled"
  }
}

# One IAM user per environment, scoped to only its own bucket -- a staging
# credential leak can't touch prod data and vice versa.
resource "aws_iam_user" "documents" {
  name = "helix-${var.environment}-documents"
}

resource "aws_iam_access_key" "documents" {
  user = aws_iam_user.documents.name
}

data "aws_iam_policy_document" "documents" {
  statement {
    sid    = "AllowBucketObjectAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["${aws_s3_bucket.documents.arn}/*"]
  }

  statement {
    sid       = "AllowBucketListing"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.documents.arn]
  }
}

resource "aws_iam_user_policy" "documents" {
  name   = "helix-${var.environment}-documents-access"
  user   = aws_iam_user.documents.name
  policy = data.aws_iam_policy_document.documents.json
}
