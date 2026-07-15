#!/usr/bin/env python3
"""Alibaba ECS VM operations acceptance checks for the shared judging host."""
from __future__ import annotations

import argparse
import grp
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from datetime import UTC
except ImportError:  # pragma: no cover - Python 3.10 host compatibility
    from datetime import timezone as _timezone

    UTC = _timezone.utc  # noqa: UP017

IMAGE_DIGEST_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
REQUIRED_IMAGE_ENV_VARS = (
    "YITING_PYTHON_IMAGE",
    "YITING_DASHBOARD_IMAGE",
    "COTENANT_APP_IMAGE",
    "COTENANT_VICTIM_IMAGE",
)
YITING_EXPECTED_SERVICES = {
    "gateway",
    "dashboard",
    "victim",
    "triage",
    "diagnosis",
    "safety_reviewer",
    "commander",
    "operator",
    "recorder-heartbeat",
}
YITING_EDGE_SERVICES = {"gateway", "dashboard"}
YITING_EGRESS_SERVICES = {"triage", "diagnosis", "safety_reviewer", "commander", "operator"}
YITING_NETWORKS = {"yiting-edge", "yiting-egress", "yiting-internal"}
DATABASE_NETWORKS = {"yiting-db", "cotenant-db"}
COTENANT_PRIVATE_NETWORKS = {"cotenant-edge", "cotenant-db", "cotenant-internal"}
POSTGRES_ENV_KEYS = {
    "DATABASE_URL",
    "POSTGRES_DB",
    "POSTGRES_PASSWORD",
    "POSTGRES_USER",
    "YITING_POSTGRES_PASSWORD",
    "YITING_POSTGRES_PASSWORD_FILE",
}


@dataclass(slots=True)
class Check:
    name: str
    ok: bool
    detail: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify shared Alibaba ECS VM operational gates.")
    parser.add_argument("--output-json", type=Path, default=Path("artifacts/live/ecs-ops-acceptance.json"))
    parser.add_argument("--disk-path", action="append", default=["/opt/apps", "/var/lib/docker"])
    parser.add_argument("--max-disk-percent", type=float, default=80.0)
    parser.add_argument("--max-container-memory-percent", type=float, default=75.0)
    parser.add_argument("--max-swap-used-percent", type=float, default=25.0)
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--no-ssh", action="store_true", help="Fail if SSH listens publicly.")
    parser.add_argument("--billing-valid-until", default=os.getenv("ECS_BILLING_VALID_UNTIL", ""))
    parser.add_argument("--judging-end-date", default=os.getenv("QWEN_JUDGING_END_DATE", ""))
    parser.add_argument("--uptime-monitor-file", type=Path, default=Path("artifacts/live/uptime-monitoring.json"))
    parser.add_argument("--app-restart-proof-file", type=Path, default=Path("artifacts/live/app-restart-resilience.json"))
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser.parse_args(argv)


def run_cmd(args: list[str], *, timeout: float, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=check)


def parse_percent(value: str) -> float:
    return float(value.strip().rstrip("%"))


def parse_iso_date(value: str) -> date:
    return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()


def check_disk(paths: list[str], threshold: float) -> list[Check]:
    checks: list[Check] = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            checks.append(Check(f"disk path exists: {path}", False, "missing"))
            continue
        usage = shutil.disk_usage(path)
        percent = (usage.used / usage.total) * 100
        checks.append(
            Check(
                f"disk use below {threshold:.0f}%: {path}",
                percent <= threshold,
                f"used={percent:.1f}% free_gib={usage.free / (1024**3):.2f}",
            )
        )
    return checks


def read_meminfo() -> dict[str, int]:
    info: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            info[parts[0].rstrip(":")] = int(parts[1])
    return info


def check_swap(threshold: float) -> Check:
    info = read_meminfo()
    total = info.get("SwapTotal", 0)
    free = info.get("SwapFree", 0)
    if total <= 0:
        return Check("no sustained swap thrashing", True, "swap not configured; swap_used=0%")
    used_percent = ((total - free) / total) * 100
    return Check(
        "no sustained swap thrashing",
        used_percent <= threshold,
        f"swap_used={used_percent:.1f}% threshold={threshold:.1f}%",
    )


def docker_json_lines(args: list[str], timeout: float) -> list[dict[str, Any]]:
    completed = run_cmd(args, timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    rows: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def docker_inspect_running_containers(timeout: float) -> list[dict[str, Any]]:
    completed = run_cmd(["docker", "ps", "-q"], timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    ids = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not ids:
        return []
    inspected = run_cmd(["docker", "inspect", *ids], timeout=timeout)
    if inspected.returncode != 0:
        raise RuntimeError((inspected.stderr or inspected.stdout).strip())
    data = json.loads(inspected.stdout)
    if not isinstance(data, list):
        raise RuntimeError("docker inspect returned a non-list payload")
    return data


def docker_inspect_network(network_name: str, timeout: float) -> dict[str, Any]:
    completed = run_cmd(["docker", "network", "inspect", network_name], timeout=timeout)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    data = json.loads(completed.stdout)
    if not data:
        raise RuntimeError(f"Docker network {network_name} missing")
    return data[0]


def labels(container: dict[str, Any]) -> dict[str, str]:
    return (container.get("Config") or {}).get("Labels") or {}


def project(container: dict[str, Any]) -> str:
    return labels(container).get("com.docker.compose.project", "")


def service(container: dict[str, Any]) -> str:
    return labels(container).get("com.docker.compose.service", "")


def name(container: dict[str, Any]) -> str:
    return str(container.get("Name") or "").lstrip("/")


def container_id(container: dict[str, Any]) -> str:
    return str(container.get("Id") or "")


def short_id(container: dict[str, Any]) -> str:
    return container_id(container)[:12]


def host_config(container: dict[str, Any]) -> dict[str, Any]:
    return container.get("HostConfig") or {}


def config_env(container: dict[str, Any]) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in (container.get("Config") or {}).get("Env") or []:
        key, separator, value = str(raw).partition("=")
        if separator:
            env[key] = value
    return env


def mount_destinations(container: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mounts: dict[str, dict[str, Any]] = {}
    for mount in container.get("Mounts") or []:
        destination = str(mount.get("Destination") or "")
        if destination:
            mounts[destination] = mount
    return mounts


def network_names(container: dict[str, Any]) -> set[str]:
    return set(((container.get("NetworkSettings") or {}).get("Networks") or {}).keys())


def yiting_containers(containers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in containers if project(item) == "yiting"]


def container_names_for_project(containers: list[dict[str, Any]], project_name: str) -> set[str]:
    return {name(item) for item in containers if project(item) == project_name}


def get_cotenant_control_gid() -> str | None:
    try:
        return str(grp.getgrnam("cotenant-control").gr_gid)
    except KeyError:
        return None


def check_yiting_runtime_boundaries(containers: list[dict[str, Any]], timeout: float) -> list[Check]:
    checks: list[Check] = []
    yiting = yiting_containers(containers)
    checks.append(Check("YITING containers discovered", bool(yiting), f"count={len(yiting)}"))
    if not yiting:
        return checks

    socket_offenders: list[str] = []
    docker_socket_offenders: list[str] = []
    for item in yiting:
        mounts = mount_destinations(item)
        for destination, mount in mounts.items():
            source = str(mount.get("Source") or "")
            if destination == "/run/cotenant" or source == "/run/cotenant" or "host-agent.sock" in {destination, source}:
                socket_offenders.append(f"{service(item)}:{name(item)}")
            if destination == "/var/run/docker.sock" or source == "/var/run/docker.sock":
                docker_socket_offenders.append(f"{service(item)}:{name(item)}")
    checks.append(
        Check(
            "YITING containers do not mount /run/cotenant or host-agent socket",
            not socket_offenders,
            ", ".join(socket_offenders) or "none",
        )
    )
    checks.append(
        Check(
            "YITING containers do not mount Docker socket",
            not docker_socket_offenders,
            ", ".join(docker_socket_offenders) or "none",
        )
    )

    expected_gid = get_cotenant_control_gid()
    if expected_gid is None:
        checks.append(
            Check(
                "YITING containers do not receive cotenant-control GID",
                True,
                "cotenant-control group not present on this host",
            )
        )
    else:
        gid_offenders = [
            f"{service(item)}:{name(item)}"
            for item in yiting
            if expected_gid in [str(group) for group in host_config(item).get("GroupAdd") or []]
        ]
        checks.append(
            Check(
                "YITING containers do not receive cotenant-control GID",
                not gid_offenders,
                f"gid={expected_gid} offenders={', '.join(gid_offenders) or 'none'}",
            )
        )

    runtime_offenders: list[str] = []
    for item in yiting:
        completed = run_cmd(
            [
                "docker",
                "exec",
                short_id(item),
                "sh",
                "-lc",
                "test ! -e /run/cotenant && test ! -e /run/cotenant/host-agent.sock",
            ],
            timeout=timeout,
        )
        if completed.returncode != 0:
            runtime_offenders.append(f"{service(item)}:{name(item)}")
    checks.append(
        Check(
            "/run/cotenant absent inside every YITING container",
            not runtime_offenders,
            ", ".join(runtime_offenders) or "none",
        )
    )

    postgres_env_offenders = []
    for item in yiting:
        keys = sorted(POSTGRES_ENV_KEYS & set(config_env(item)))
        if keys:
            postgres_env_offenders.append(f"{service(item)}:{','.join(keys)}")
    checks.append(
        Check(
            "YITING SQLite profile has no PostgreSQL credentials",
            not postgres_env_offenders,
            "; ".join(postgres_env_offenders) or "none",
        )
    )
    return checks


def check_yiting_network_boundaries(containers: list[dict[str, Any]], timeout: float) -> list[Check]:
    checks: list[Check] = []
    yiting = yiting_containers(containers)
    if not yiting:
        return [Check("YITING network boundaries", False, "no YITING containers")]

    missing_services = sorted(YITING_EXPECTED_SERVICES - {service(item) for item in yiting})
    checks.append(
        Check(
            "all expected YITING shared-host services are running",
            not missing_services,
            ", ".join(missing_services) or "all present",
        )
    )

    cotenant_network_offenders = [
        f"{service(item)}:{','.join(sorted(network_names(item) & COTENANT_PRIVATE_NETWORKS))}"
        for item in yiting
        if network_names(item) & COTENANT_PRIVATE_NETWORKS
    ]
    checks.append(
        Check(
            "YITING containers do not join COTENANT networks",
            not cotenant_network_offenders,
            "; ".join(cotenant_network_offenders) or "none",
        )
    )

    database_network_offenders = [
        f"{service(item)}:{','.join(sorted(network_names(item) & DATABASE_NETWORKS))}"
        for item in yiting
        if network_names(item) & DATABASE_NETWORKS
    ]
    checks.append(
        Check(
            "YITING SQLite profile does not join database networks",
            not database_network_offenders,
            "; ".join(database_network_offenders) or "none",
        )
    )

    edge_offenders = [
        f"{service(item)}:{','.join(sorted(network_names(item)))}"
        for item in yiting
        if ("yiting-edge" in network_names(item)) != (service(item) in YITING_EDGE_SERVICES)
    ]
    checks.append(
        Check(
            "only gateway and dashboard join yiting-edge",
            not edge_offenders,
            "; ".join(edge_offenders) or "gateway,dashboard",
        )
    )

    egress_offenders = [
        f"{service(item)}:{','.join(sorted(network_names(item)))}"
        for item in yiting
        if ("yiting-egress" in network_names(item)) != (service(item) in YITING_EGRESS_SERVICES)
    ]
    checks.append(
        Check(
            "only YITING live-agent workers join yiting-egress",
            not egress_offenders,
            "; ".join(egress_offenders) or ",".join(sorted(YITING_EGRESS_SERVICES)),
        )
    )

    internal_offenders = [
        f"{service(item)}:{','.join(sorted(network_names(item)))}"
        for item in yiting
        if "yiting-internal" not in network_names(item)
    ]
    checks.append(
        Check(
            "all YITING containers join yiting-internal",
            not internal_offenders,
            "; ".join(internal_offenders) or "all present",
        )
    )

    by_id = {container_id(item): item for item in containers}
    for network_name in YITING_NETWORKS:
        network = docker_inspect_network(network_name, timeout)
        offenders: list[str] = []
        for raw_id in ((network.get("Containers") or {}).keys()):
            container = by_id.get(str(raw_id))
            if container is None:
                offenders.append(str(raw_id)[:12])
                continue
            container_project = project(container)
            container_service = service(container)
            if network_name == "yiting-internal":
                allowed = container_project == "yiting"
            elif network_name == "yiting-edge":
                allowed = (
                    (container_project == "yiting" and container_service in YITING_EDGE_SERVICES)
                    or (container_project == "platform" and container_service == "caddy")
                )
            else:
                allowed = container_project == "yiting" and container_service in YITING_EGRESS_SERVICES
            if not allowed:
                offenders.append(f"{container_project}/{container_service}:{name(container)}")
        checks.append(
            Check(
                f"{network_name} has only approved members",
                not offenders,
                ", ".join(offenders) or "approved",
            )
        )

    gateway = next((item for item in yiting if service(item) == "gateway"), None)
    if gateway is None:
        checks.append(Check("YITING gateway cannot resolve COTENANT private services", False, "gateway missing"))
    else:
        completed = run_cmd(
            [
                "docker",
                "exec",
                short_id(gateway),
                "python",
                "-c",
                (
                    "import socket;"
                    "hosts=('cotenant-victim','cotenant-worker','cotenant-postgres','cotenant-api');"
                    "bad=[]\n"
                    "for host in hosts:\n"
                    "    try:\n"
                    "        socket.getaddrinfo(host, 80); bad.append(host)\n"
                    "    except OSError:\n"
                    "        pass\n"
                    "raise SystemExit(','.join(bad) if bad else 0)"
                ),
            ],
            timeout=timeout,
        )
        checks.append(
            Check(
                "YITING gateway cannot resolve COTENANT private services",
                completed.returncode == 0,
                (completed.stdout or completed.stderr).strip() or "blocked",
            )
        )
    return checks


def check_container_memory(
    threshold: float,
    timeout: float,
    *,
    allowed_container_names: set[str] | None = None,
) -> list[Check]:
    rows = docker_json_lines(["docker", "stats", "--no-stream", "--format", "{{json .}}"], timeout)
    if allowed_container_names is not None:
        rows = [
            row
            for row in rows
            if str(row.get("Name") or row.get("Container") or "unknown") in allowed_container_names
        ]
    if not rows:
        scope = " for scoped containers" if allowed_container_names is not None else ""
        return [Check("container memory below threshold", False, f"docker stats returned no containers{scope}")]
    offenders = []
    details = []
    for row in rows:
        percent = parse_percent(str(row.get("MemPerc", "0%")))
        name = str(row.get("Name") or row.get("Container") or "unknown")
        details.append(f"{name}={percent:.1f}%")
        if percent > threshold:
            offenders.append(f"{name}={percent:.1f}%")
    return [
        Check(
            f"container memory below {threshold:.0f}% of limit after warm-up",
            not offenders,
            "; ".join(offenders or details),
        )
    ]


def check_oom(containers: list[dict[str, Any]], *, project_name: str = "yiting") -> Check:
    inspected = [item for item in containers if project(item) == project_name]
    if not inspected:
        return Check("no OOM-killed containers", False, f"no running {project_name} containers")
    offenders = [
        str(item.get("Name") or "").lstrip("/")
        for item in inspected
        if ((item.get("State") or {}).get("OOMKilled") is True)
    ]
    return Check(
        "no OOM-killed containers",
        not offenders,
        ", ".join(offenders) or f"{project_name}_containers={len(inspected)}",
    )


def public_listener_ports(ss_output: str) -> set[int]:
    ports: set[int] = set()
    for line in ss_output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]
        if not (
            local.startswith("0.0.0.0:")
            or local.startswith("[::]:")
            or local.startswith(":::")
            or local.startswith("*:")
        ):
            continue
        match = re.search(r":(\d+)$", local)
        if match:
            ports.add(int(match.group(1)))
    return ports


def check_public_listeners(ssh_port: int, allow_ssh: bool, timeout: float) -> Check:
    if shutil.which("ss"):
        completed = run_cmd(["ss", "-H", "-ltn"], timeout=timeout)
        source = "ss"
    elif shutil.which("netstat"):
        completed = run_cmd(["netstat", "-ltn"], timeout=timeout)
        source = "netstat"
    else:
        return Check("only Caddy and restricted SSH listen publicly", False, "ss/netstat not found")
    if completed.returncode != 0:
        return Check("only Caddy and restricted SSH listen publicly", False, completed.stderr.strip()[:500])
    allowed = {80, 443}
    if allow_ssh:
        allowed.add(ssh_port)
    actual = public_listener_ports(completed.stdout)
    unexpected = sorted(actual - allowed)
    return Check(
        "only Caddy and restricted SSH listen publicly",
        not unexpected and {80, 443}.issubset(actual),
        f"{source} public_ports={sorted(actual)} allowed={sorted(allowed)}",
    )


def check_billing(valid_until: str, judging_end: str) -> Check:
    if not valid_until or not judging_end:
        return Check(
            "ECS billing extends beyond judging end",
            False,
            "set ECS_BILLING_VALID_UNTIL and QWEN_JUDGING_END_DATE as YYYY-MM-DD",
        )
    try:
        valid = parse_iso_date(valid_until)
        end = parse_iso_date(judging_end)
    except ValueError as exc:
        return Check("ECS billing extends beyond judging end", False, str(exc))
    return Check(
        "ECS billing extends beyond judging end",
        valid >= end,
        f"billing_valid_until={valid.isoformat()} judging_end={end.isoformat()}",
    )


def check_uptime_monitor(path: Path) -> Check:
    if not path.exists():
        return Check("external uptime monitoring configured", False, f"{path} missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Check("external uptime monitoring configured", False, str(exc))
    monitors = payload.get("monitors")
    if payload.get("format") != "uptime-monitoring-v1" or not isinstance(monitors, list):
        return Check("external uptime monitoring configured", False, "invalid uptime-monitoring-v1 payload")
    targets = {str(item.get("app", "")).lower(): item for item in monitors if isinstance(item, dict)}
    missing = [app for app in ("yiting",) if app not in targets]
    failures = []
    for app, item in targets.items():
        if app not in {"yiting", "neighbor", "cotenant"}:
            continue
        if item.get("enabled") is not True:
            failures.append(f"{app}: enabled is not true")
        if not str(item.get("target_url") or "").startswith("https://"):
            failures.append(f"{app}: target_url must be https")
        if not str(item.get("monitor_url") or "").startswith("https://"):
            failures.append(f"{app}: monitor_url must be https")
        interval = int(item.get("interval_seconds") or 0)
        if interval <= 0 or interval > 300:
            failures.append(f"{app}: interval_seconds must be 1..300")
    failures.extend(f"missing {item}" for item in missing)
    return Check("external uptime monitoring configured", not failures, "; ".join(failures) or "yiting")


def check_app_restart_resilience(path: Path) -> Check:
    if not path.exists():
        return Check("app restart resilience checked", False, f"{path} missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Check("app restart resilience checked", False, str(exc))

    failures: list[str] = []
    if payload.get("format") != "shared-ecs-app-restart-resilience-v1":
        failures.append("format must be shared-ecs-app-restart-resilience-v1")
    if payload.get("artifact_class") != "live_app_restart_resilience":
        failures.append("artifact_class must be live_app_restart_resilience")
    if payload.get("submission_evidence") is not True or payload.get("verified_live") is not True:
        failures.append("artifact must be verified live submission evidence")
    if payload.get("host_rebooted") is not False:
        failures.append("host_rebooted must be false")
    restart_scope = str(payload.get("restart_scope") or "").lower()
    if "app-scoped" not in restart_scope and "compose" not in restart_scope:
        failures.append("restart_scope must describe app-scoped Compose restart")

    apps = payload.get("apps")
    apps_by_name = {
        str(item.get("app", "")).lower(): item
        for item in apps
        if isinstance(item, dict)
    } if isinstance(apps, list) else {}
    for app in ("yiting", "cotenant"):
        item = apps_by_name.get(app)
        if item is None:
            failures.append(f"{app} app restart proof missing")
            continue
        url = str(item.get("url") or "")
        if not url.startswith("https://"):
            failures.append(f"{app}.url must be https")
        for field in ("healthy_after_restart", "state_persisted", "evidence_persisted", "logs_persisted"):
            if item.get(field) is not True:
                failures.append(f"{app}.{field} must be true")

    return Check(
        "app restart resilience checked",
        not failures,
        "; ".join(failures) or "yiting+cotenant app restart resilience verified",
    )


def check_immutable_image_env(env: dict[str, str] | None = None) -> Check:
    env = env or os.environ
    failures: list[str] = []
    for name in REQUIRED_IMAGE_ENV_VARS:
        value = env.get(name, "").strip()
        if not value:
            failures.append(f"{name} missing")
        elif not IMAGE_DIGEST_RE.fullmatch(value):
            failures.append(f"{name} must be image@sha256:<64 hex chars>")
    return Check(
        "production images are pinned by immutable digest",
        not failures,
        "; ".join(failures) or ", ".join(REQUIRED_IMAGE_ENV_VARS),
    )


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[Check] = []
    try:
        checks.append(check_immutable_image_env())
        checks.extend(check_disk(args.disk_path, args.max_disk_percent))
        checks.append(check_swap(args.max_swap_used_percent))
        containers = docker_inspect_running_containers(args.timeout)
        scoped_names = container_names_for_project(containers, "yiting")
        checks.extend(
            check_container_memory(
                args.max_container_memory_percent,
                args.timeout,
                allowed_container_names=scoped_names,
            )
        )
        checks.append(check_oom(containers, project_name="yiting"))
        checks.extend(check_yiting_runtime_boundaries(containers, args.timeout))
        checks.extend(check_yiting_network_boundaries(containers, args.timeout))
        checks.append(check_public_listeners(args.ssh_port, not args.no_ssh, args.timeout))
        checks.append(check_billing(args.billing_valid_until, args.judging_end_date))
        checks.append(check_uptime_monitor(args.uptime_monitor_file))
        checks.append(check_app_restart_resilience(args.app_restart_proof_file))
    except Exception as exc:
        checks.append(Check("ecs ops acceptance runner failed", False, f"{type(exc).__name__}: {exc}"))

    return {
        "format": "shared-ecs-ops-acceptance-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": all(item.ok for item in checks),
        "checks": [
            {
                "name": item.name,
                "ok": item.ok,
                "detail": item.detail,
            }
            for item in checks
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "output": str(args.output_json)}, indent=2))
    if not report["passed"]:
        for item in report["checks"]:
            if not item["ok"]:
                print(f"[FAIL] {item['name']}: {item['detail']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
