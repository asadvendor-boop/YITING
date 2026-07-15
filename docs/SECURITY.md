# Security

YITING's judging deployment is a production-oriented single-node deployment on Alibaba ECS
for hackathon judging. It is not a highly available deployment.

## Boundaries

- Caddy is the only HTTP/HTTPS ingress.
- Application containers publish no host ports in the shared-host profile.
- YITING does not mount Docker Engine sockets.
- YITING does not receive neighboring app control sockets or control groups.
- Gateway state is stored on a private persistent SQLite volume unless a later
  deployment explicitly migrates it.
- In the approved judging profile, YITING does not join `yiting-db` or
  any external database network and receives no PostgreSQL credentials. A PostgreSQL migration
  would require separate `yiting_app` credentials plus new database-isolation
  acceptance evidence.
- Secrets are stored outside Git under `/opt/apps/yiting/secrets/` on the ECS
  host, with root ownership and narrow permissions.

## Live Qwen Configuration

Production requires a live DashScope/Qwen key. Missing or invalid model
configuration must fail closed for cost-generating workflows; hidden mock
fallback is not an acceptable production mode.

## Abuse And Cost Controls

- Gateway request rate limits are enforced by `gateway/rate_limit.py`.
- Limits are keyed by authenticated identity when an `X-Agent-Key`,
  `X-Operator-Token`, or `Authorization` credential is present, otherwise by
  source IP.
- `YITING_RATE_LIMIT_PER_MINUTE` and `YITING_RATE_LIMIT_WINDOW_SECONDS` must be
  positive integers; invalid values fail closed instead of disabling limits.
- Live Qwen calls are also guarded by the shared daily token circuit breaker in
  `/qwen-usage/yiting-qwen-usage.json`.

## Deployment Isolation

YITING runs within an isolated deployment boundary on Alibaba ECS
and backup tooling. It must not share application credentials,
private networks, logs, evidence, persistent application data, or demo/reset
state.
