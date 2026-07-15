# Alibaba ECS IaC Parity Proof

This folder is the reproducible infrastructure definition for the approved
judging deployment:

> Production-oriented single-node deployment on Alibaba ECS for hackathon
> judging, with live Qwen Cloud inference, durable state, isolated application
> boundaries, least-privilege control paths, persistent evidence, and explicit
> disclosure that YITING can share one host with platform services and is not
> highly available.

YITING is not highly available in this single-node judging profile.

Manual ECS provisioning is allowed. If the VM is created manually, this
Terraform configuration is parity proof for the actual deployed ECS VM's
documented shape; do not claim Terraform was applied. If Terraform is actually
used, commit only these source files and never commit state, plans,
`terraform.tfvars`, keys, or backend files.

This repository describes the shared VM profile used by YITING. Do not apply
separate copies of this stack unless you intentionally want separate VMs.

## Declared ECS Shape

- Alibaba ECS instance, default `ecs.c6.xlarge` for a 4 vCPU / 8 GB class.
- Ubuntu 24.04 LTS system image selected from Alibaba's public image catalog.
- 80 GB ESSD system disk by default.
- Security group exposes only:
  - `80/tcp` for Caddy HTTP challenge/redirect;
  - `443/tcp` for Caddy HTTPS;
  - `22/tcp` restricted to `ssh_source_cidr`.
- Runtime services are installed after provisioning with Docker Compose:
  - `platform`
  - `yiting`

## Validation

```bash
terraform fmt -check
terraform init -backend=false
terraform validate
```

Provider downloads require network access. These commands should be run in the
deployment environment before treating the IaC as final.

## IaC Parity Table

Fill the "Actual ECS VM" column from the Alibaba Cloud console or CLI after the
VM exists. Any mismatch must be explained before recording the deployment-proof
video.

| Item | Declared In This IaC | Actual ECS VM | Status / Notes |
|---|---|---|---|
| Region | `var.region`, default `ap-southeast-1` | To be filled after provisioning | Pending live ECS |
| ECS family/size | `var.ecs_instance_type`, default `ecs.c6.xlarge` | To be filled after provisioning | Pending live ECS |
| Operating system | Latest public Ubuntu 24.04 x64 image | To be filled after provisioning | Pending live ECS |
| System disk | ESSD, `var.system_disk_size_gb`, default 80 GB | To be filled after provisioning | Pending live ECS |
| VPC | `10.74.0.0/16` | To be filled after provisioning | Pending live ECS |
| Security group | `80/tcp`, `443/tcp`, restricted `22/tcp` only | To be filled after provisioning | Pending live ECS |
| Public ports | Caddy only: 80 and 443 | To be filled after provisioning | Pending live ECS |
| SSH policy | Existing key pair plus `ssh_source_cidr` | To be filled after provisioning | Pending live ECS |
| Domain routing | DNS must point the YITING hostname to the ECS public IP | To be filled after provisioning | Pending live ECS |
| Docker installation | Post-provisioning Docker Engine | To be filled after provisioning | Pending live ECS |
| Swap | 2-4 GB post-provisioning swap file | To be filled after provisioning | Pending live ECS |
| Persistent paths | `/opt/apps/platform`, `/opt/apps/yiting` | To be filled after provisioning | Pending live ECS |
| Backup paths | `/opt/apps/backups/yiting` | To be filled after provisioning | Pending live ECS |

## Actual ECS Capture Checklist

After the VM exists, capture the actual values below and use them to fill the
parity table before recording the deployment-proof video. Redact account IDs,
public IPs if you do not want them public, and any secret values.

```bash
aliyun ecs DescribeInstances \
  --RegionId "$ALIYUN_REGION" \
  --InstanceIds "[\"$ECS_INSTANCE_ID\"]"

aliyun ecs DescribeSecurityGroupAttribute \
  --RegionId "$ALIYUN_REGION" \
  --SecurityGroupId "$ECS_SECURITY_GROUP_ID"

ssh "$ECS_SSH_HOST" 'lsb_release -ds'
ssh "$ECS_SSH_HOST" 'docker version --format "{{.Server.Version}}"'
ssh "$ECS_SSH_HOST" 'swapon --show || true'
ssh "$ECS_SSH_HOST" 'sudo ss -ltnp'
ssh "$ECS_SSH_HOST" 'sudo find /opt/apps -maxdepth 2 -type d | sort'
ssh "$ECS_SSH_HOST" 'sudo find /opt/apps/backups -maxdepth 2 -type d | sort'

ssh "$ECS_SSH_HOST" 'docker compose -p platform ps'
ssh "$ECS_SSH_HOST" 'docker compose -p yiting ps'
ssh "$ECS_SSH_HOST" 'docker network inspect yiting-edge yiting-egress yiting-internal'
```

Expected listener evidence: only SSH from the restricted operator source plus
Caddy on ports 80 and 443 should be publicly reachable. Application, database,
worker, victim, MCP, and host-agent control-plane listeners must remain private
to Docker networks, Unix sockets, or localhost.

## What This Does Not Claim

- It does not claim high availability.
- It does not claim managed RDS, SAE, SLS, EventBridge, KMS, OSS, SLB, RRSA, or
  Kubernetes are deployed for judging.
- It does not prove live deployment until the parity table, live Qwen smoke, and
  hosted deployment verification artifacts are generated from the real ECS VM.
