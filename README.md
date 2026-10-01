# Fieldnotes: Floci Contacts

A local, full-stack CRUD application for managing contacts. Docker Compose starts the Floci AWS emulator, Terraform provisioning, Flask API and web UI, an asynchronous audit worker, Prometheus, and Grafana. There are no real AWS credentials, accounts, or cloud resources involved.

## Architecture

```text
Browser -> Flask CRUD API -> DynamoDB (Floci)
                 |
                 +-> SQS audit queue -> audit worker -> S3 event archive (Floci)
                 |                           |
                 +------ Prometheus <---------+---- /metrics
                              |
                              +-> Grafana dashboard
```

Terraform provisions a DynamoDB contacts table, an SQS event queue with a dead-letter queue, and an S3 bucket for archived audit events. Compose waits for Floci, applies Terraform, then starts the API and worker. The API emits structured JSON logs and request count/latency metrics; the worker exposes processed/failed event counters. Grafana loads a Prometheus datasource and dashboard automatically.

## Start Everything

Prerequisites: Docker Engine/Desktop with the Compose plugin, and access to the `floci/floci` image. The Floci container uses the Docker socket as in the supplied project Compose setup.

From the repository root:

```bash
docker compose up --build
```

The first start builds the application image, waits for Floci on port `4566`, provisions its resources with Terraform, and then brings up the app and monitoring services. Keep this terminal open to see container logs.

| Service | URL | Local credentials |
| --- | --- | --- |
| Contacts app | http://localhost:8080 | None |
| Grafana | http://localhost:3000 | `admin` / `dev-only-change-me` |
| Prometheus | http://localhost:9090 | None |
| Floci AWS API | http://localhost:4567 | Mock credentials only |

Change Grafana's local demo password by setting `GRAFANA_ADMIN_PASSWORD` before starting Compose. Do not expose these development services directly to the public internet.

## Use the CRUD API

The web UI supports creating, listing, searching, editing, and deleting contacts. The JSON API is also available directly:

```bash
curl -s http://localhost:8080/api/contacts

curl -s -X POST http://localhost:8080/api/contacts \
  -H 'Content-Type: application/json' \
  -d '{"name":"Jordan Lee","email":"jordan@example.com","company":"Northstar Studio"}'

curl -s -X PATCH http://localhost:8080/api/contacts/CONTACT_ID \
  -H 'Content-Type: application/json' \
  -d '{"company":"Northstar Labs"}'

curl -i -X DELETE http://localhost:8080/api/contacts/CONTACT_ID
```

Replace `CONTACT_ID` with the `contact_id` returned by the create request. Every successful mutation attempts to queue an audit event; the worker stores it in S3 at `events/<event_id>.json`. Failed worker deliveries retry and eventually go to the SQS dead-letter queue.

## Operations and Observability

- API liveness and readiness: `/healthz` and `/readyz`.
- Prometheus metrics: http://localhost:8080/metrics and http://localhost:9101/metrics (worker metrics are available to Prometheus on the Compose network).
- Grafana dashboard: sign in, open **Dashboards**, then **Floci Contacts** → **Contacts · Operations**.
- Structured logs: `docker compose logs -f api audit-worker floci`.
- Resource definitions: `infra/main.tf`.

The dashboard includes API request rate, p95 latency, archived/failed audit events, and recent worker failures. Metrics are in-memory counters and reset when their containers restart; contact and audit data live in Floci's emulator.

## GitHub Actions

The workflow builds the API/worker image on pull requests and pushes to `main`. A GitHub-hosted runner cannot provision durable resources in Floci running on your workstation, so Terraform apply happens locally as part of `docker compose up`. This keeps the project cloud-free while still demonstrating an automated image-build CI stage.

## Stop and Reset

Stop containers and preserve monitoring data:

```bash
docker compose down
```

Remove the Prometheus and Grafana named volumes too:

```bash
docker compose down -v
```

Floci itself is currently ephemeral: removing/recreating its container clears emulator data. To remove provisioned Floci resources, run `docker compose run --rm infrastructure "terraform destroy -auto-approve -input=false"` before taking the stack down. Terraform's local state is stored under `infra/terraform.tfstate` and is ignored by Git.

## Portfolio Highlights

- Full local development environment orchestrated with Docker Compose.
- Terraform-managed AWS-compatible resources against Floci, without a cloud account.
- CRUD REST API with validation, stable resource IDs, and JSON logs.
- Asynchronous audit pipeline using SQS, a retry/DLQ policy, and S3 archival.
- Prometheus metrics and a provisioned Grafana operations dashboard.
- GitHub Actions image-build CI with no cloud credentials.