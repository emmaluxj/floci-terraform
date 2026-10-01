terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  s3_use_path_style           = true

  endpoints {
    dynamodb = "http://floci:4566"
    s3       = "http://floci:4566"
    sqs      = "http://floci:4566"
  }
}

resource "aws_dynamodb_table" "contacts" {
  name         = "floci-contacts"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "contact_id"

  attribute {
    name = "contact_id"
    type = "S"
  }
}

resource "aws_sqs_queue" "dead_letter" {
  name = "floci-contact-events-dlq"
}

resource "aws_sqs_queue" "events" {
  name                       = "floci-contact-events"
  visibility_timeout_seconds = 45
  message_retention_seconds  = 345600
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 3
  })
}

resource "aws_s3_bucket" "audit" {
  bucket = "floci-contact-audit"
}

output "contacts_table" {
  value = aws_dynamodb_table.contacts.name
}

output "audit_queue" {
  value = aws_sqs_queue.events.name
}

output "audit_bucket" {
  value = aws_s3_bucket.audit.bucket
}
