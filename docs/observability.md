# Structured Logging, Request Tracing and CloudWatch Metrics

Zappa emits structured, JSON-based log entries and (optionally) custom
CloudWatch metrics for every Lambda invocation and every CLI deployment
operation. Everything is emitted through CloudWatch Logs, so `zappa tail`
keeps working unchanged.

## Request trace ids

A single trace id is resolved for every invocation and attached to every
log entry, the WSGI environ and any asynchronous task spawned from the
request. Resolution order (first non-empty value wins):

1. Inbound `X-Zappa-Trace-Id` (or `X-Request-Id`) HTTP header.
2. API Gateway `requestContext.requestId`.
3. Lambda `context.aws_request_id`.
4. A freshly generated UUID4.

Inside a WSGI application the trace id is available as
`environ['zappa.trace_id']` (and mirrored in
`environ['HTTP_X_ZAPPA_TRACE_ID']`). The value is also exported in the
`ZAPPA_TRACE_ID` environment variable for the duration of the invocation.

Tasks sent through `zappa.asynchronous` automatically carry the trace id in
their message; the follow-up Lambda invocation logs under the same trace, so
a single request can be followed across multiple Lambda calls.

Correlate all lines of one request with:

```bash
zappa tail dev --filter 766df67f-8991-11e6-b2c4-d120fedb94e5
```

## Log formats and `zappa tail` compatibility

HTTP access logs keep the Apache Common Log Format line at the start of the
message and append a compact JSON document plus a bare trace id token:

```
96.90.37.59 - - [21/Sep/2026:01:23:45 +0000] "GET /a HTTP/1.1" 200 5 142.5ms | {"log_format":"zappa_access_v1","method":"GET","path":"/a","response_time_ms":142.5,"status_code":200,"trace_id":"766df67f-8991-11e6-b2c4-d120fedb94e5"} trace_id 766df67f-8991-11e6-b2c4-d120fedb94e5
```

* `zappa tail --http` still recognises the line because it begins with the
  remote IP.
* `zappa tail --non-http` shows only the generic event lines, which never
  start with an IP-like token.
* The bare UUID token is highlighted by the existing `zappa tail`
  colouriser.

Generic events are single-line JSON objects such as
`{"event":"timing.wsgi.request","trace_id":"...","duration_ms":140.2,"outcome":"success"}`.

The following key paths are timed on every invocation; both a log entry and
a metric are produced:

| Event                        | Path                                       |
| ---------------------------- | ------------------------------------------ |
| `event.route`                | API Gateway/ALB event to WSGI environ      |
| `wsgi.request`               | Actual WSGI application execution          |
| `event.command`              | Direct `command` and async task dispatch   |
| `event.scheduled`            | Scheduled events                           |
| `event.aws_record`           | S3/SNS/DynamoDB/Kinesis/SQS record events  |
| `event.bot_intent`           | Lex bot intent                             |
| `event.authorizer`           | API Gateway `TOKEN` authorizer             |
| `event.cognito_trigger`      | Cognito triggers                           |
| `event.cloudwatch_logs`      | CloudWatch Logs subscription filters       |
| `http.response`              | HTTP status and response time summary      |

## Custom CloudWatch metrics

Runtime metrics are **off by default**. Enable them per stage:

```json
{
    "dev": {
        "metrics_enabled": true,
        "metrics_namespace": "Zappa/Observability"
    }
}
```

When enabled, every timed path emits:

* `<event>` — latency in `Milliseconds` (e.g. `wsgi.request`).
* `<event>.Success` / `<event>.Failure` — `Count`.
* `http.status_code` — `Count`, dimensioned by `status_code` and `method`.

Deployment operations (`upload_to_s3`, `update_lambda_function` and
`deploy_api_gateway`) emit, under the same namespace:

* `DeploymentLatency` (`Milliseconds`), dimensioned by `operation`
  (`upload_to_s3`, `update_lambda_function`, `deploy_api_gateway`) plus
  `bucket`, `function_name` or `api_id`/`stage` where relevant.
* `DeploymentSuccess` / `DeploymentFailure` (`Count`).

Reporting is always best-effort: metric publication is wrapped so that an
IAM or regional failure never breaks a request or a deployment. The default
execution role includes `cloudwatch:PutMetricData` for new deployments;
existing roles need that action added manually.
