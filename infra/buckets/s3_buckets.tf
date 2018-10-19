data "aws_iam_role" "admin" {
  name = "${var.DSS_AWS_DELETION_ROLE}"
}

resource aws_s3_bucket dss_s3_bucket {
  count  = "${length(var.DSS_S3_BUCKET) > 0 ? 1 : 0}"
  bucket = "${var.DSS_S3_BUCKET}"
  policy = <<POLICY
  {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "admin_delete"
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:Delete*",
            "Resource": [
              "arn:aws:s3:::${var.DSS_S3_BUCKET}/*",
              "arn:aws:s3:::${var.DSS_S3_BUCKET}"
            ],
            "Condition": {
                "StringNotLike": {
                    "aws:userId": [
                        "${data.aws_iam_role.admin.unique_id}:*",
                        "${local.account_id}"
                    ]
                }
            }
        }
    ]
  }
  POLICY
}

resource aws_s3_bucket dss_s3_bucket_test {
  count  = "${var.DSS_DEPLOYMENT_STAGE == "dev" ? 1 : 0}"
  bucket = "${var.DSS_S3_BUCKET_TEST}"
  lifecycle_rule {
    id      = "prune old things"
    enabled = true
    abort_incomplete_multipart_upload_days = "${var.DSS_BLOB_TTL_DAYS}"
    expiration {
      days = "${var.DSS_BLOB_TTL_DAYS}"
    }
  }
}

resource aws_s3_bucket dss_s3_bucket_test_fixtures {
  count  = "${var.DSS_DEPLOYMENT_STAGE == "dev" ? 1 : 0}"
  bucket = "${var.DSS_S3_BUCKET_TEST_FIXTURES}"
}

resource aws_s3_bucket dss_s3_checkout_bucket {
  count  = "${length(var.DSS_S3_CHECKOUT_BUCKET) > 0 ? 1 : 0}"
  bucket = "${var.DSS_S3_CHECKOUT_BUCKET}"
  lifecycle_rule {
    id      = "dss_checkout_expiration"
    enabled = true
    abort_incomplete_multipart_upload_days = "${var.DSS_BLOB_TTL_DAYS}"
    expiration {
      days = "${var.DSS_BLOB_TTL_DAYS}"
    }
  }
}

resource aws_s3_bucket dss_s3_checkout_bucket_test {
  count  = "${var.DSS_DEPLOYMENT_STAGE == "dev" ? 1 : 0}"
  bucket = "${var.DSS_S3_CHECKOUT_BUCKET_TEST}"
  lifecycle_rule {
    id      = "dss_checkout_expiration"
    enabled = true
    abort_incomplete_multipart_upload_days = "${var.DSS_BLOB_TTL_DAYS}"
    expiration {
      days = "${var.DSS_BLOB_TTL_DAYS}"
    }
  }
}

resource aws_s3_bucket dss_s3_checkout_bucket_unwritable {
  count  = "${var.DSS_DEPLOYMENT_STAGE == "dev" ? 1 : 0}"
  bucket = "${var.DSS_S3_CHECKOUT_BUCKET_UNWRITABLE}"
  policy = <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": [
        "s3:Get*",
        "s3:List*"
      ],
      "Effect": "Allow",
      "Resource": [
        "arn:aws:s3:::${var.DSS_S3_CHECKOUT_BUCKET_UNWRITABLE}",
        "arn:aws:s3:::${var.DSS_S3_CHECKOUT_BUCKET_UNWRITABLE}/*"
      ],
      "Principal": "*"
    },
    {
      "Action": [
        "s3:Put*"
      ],
      "Effect": "Deny",
      "Resource": [
        "arn:aws:s3:::${var.DSS_S3_CHECKOUT_BUCKET_UNWRITABLE}",
        "arn:aws:s3:::${var.DSS_S3_CHECKOUT_BUCKET_UNWRITABLE}/*"
      ],
      "Principal": "*"
    }
  ]
}
POLICY
}
