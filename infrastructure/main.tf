data "aws_caller_identity" "current" {}

data "aws_iot_endpoint" "ats" {
  endpoint_type = "iot:Data-ATS"
}

locals {
  lambda_source = (
    "${path.module}/../lambda/store_telemetry/lambda_function.py"
  )
}

resource "aws_dynamodb_table" "telemetry" {
  name         = var.telemetry_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "device_id"
  range_key    = "timestamp"

  attribute {
    name = "device_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.lambda_function_name}"
  retention_in_days = 14
}

resource "aws_iam_role" "lambda" {
  name = var.lambda_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Effect = "Allow"

        Principal = {
          Service = "lambda.amazonaws.com"
        }

        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "${var.project_name}-lambda-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"

    Statement = [
      {
        Sid    = "WriteTelemetry"
        Effect = "Allow"

        Action = [
          "dynamodb:PutItem"
        ]

        Resource = aws_dynamodb_table.telemetry.arn
      },
      {
        Sid    = "WriteLambdaLogs"
        Effect = "Allow"

        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]

        Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
      }
    ]
  })
}

data "archive_file" "lambda" {
  type        = "zip"
  source_file = local.lambda_source
  output_path = "${path.module}/store_telemetry.zip"
}

resource "aws_lambda_function" "store_telemetry" {
  function_name = var.lambda_function_name
  role          = aws_iam_role.lambda.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.13"

  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  timeout     = 10
  memory_size = 128

  environment {
    variables = {
      TELEMETRY_TABLE = aws_dynamodb_table.telemetry.name
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda,
  ]
}

resource "aws_iot_topic_rule" "telemetry" {
  name        = var.iot_rule_name
  description = "Route device telemetry to the storage Lambda"
  enabled     = true

  sql = <<-SQL
    SELECT *,
           topic(2) AS topic_device_id
    FROM 'devices/+/telemetry'
  SQL

  sql_version = "2016-03-23"

  lambda {
    function_arn = aws_lambda_function.store_telemetry.arn
  }
}

resource "aws_lambda_permission" "allow_iot" {
  statement_id  = "AllowExecutionFromIoTCore"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.store_telemetry.function_name
  principal     = "iot.amazonaws.com"

  source_arn = aws_iot_topic_rule.telemetry.arn

  source_account = data.aws_caller_identity.current.account_id
}

resource "aws_iot_thing" "devices" {
  for_each = var.device_ids

  name = each.value

  attributes = {
    simulator = "python-fleet"
    project   = var.project_name
  }
}

resource "aws_iot_policy" "device" {
  name = var.iot_policy_name

  policy = templatefile(
    "${path.module}/policies/device-policy.json.tftpl",
    {
      region     = var.aws_region
      account_id = data.aws_caller_identity.current.account_id
    }
  )
}

resource "aws_iot_policy_attachment" "device_certificate" {
  for_each = var.certificate_arns

  policy = aws_iot_policy.device.name
  target = each.value
}

resource "aws_iot_thing_principal_attachment" "device_certificate" {
  for_each = var.certificate_arns

  thing     = aws_iot_thing.devices[each.key].name
  principal = each.value
}