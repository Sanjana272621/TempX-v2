output "iot_endpoint" {
  description = "AWS IoT ATS data endpoint"
  value       = data.aws_iot_endpoint.ats.endpoint_address
}

output "telemetry_table_name" {
  value = aws_dynamodb_table.telemetry.name
}

output "lambda_function_name" {
  value = aws_lambda_function.store_telemetry.function_name
}

output "iot_rule_name" {
  value = aws_iot_topic_rule.telemetry.name
}

output "device_thing_names" {
  value = sort([
    for device in aws_iot_thing.devices :
    device.name
  ])
}