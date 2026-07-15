from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import ecs_ops_acceptance


def _valid_image_env() -> dict[str, str]:
    return {
        "YITING_PYTHON_IMAGE": "registry.example.com/yiting/python@sha256:" + "a" * 64,
        "YITING_DASHBOARD_IMAGE": "registry.example.com/yiting/dashboard@sha256:" + "b" * 64,
        "COTENANT_APP_IMAGE": "registry.example.com/cotenant/app@sha256:" + "c" * 64,
        "COTENANT_VICTIM_IMAGE": "registry.example.com/cotenant/victim@sha256:" + "d" * 64,
    }


def _container(
    container_id: str,
    *,
    project: str,
    service: str,
    networks: list[str],
    mounts: list[dict[str, object]] | None = None,
    group_add: list[str] | None = None,
    env: list[str] | None = None,
) -> dict[str, object]:
    return {
        "Id": container_id,
        "Name": f"/{project}-{service}-1",
        "Config": {
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
            },
            "Env": env or [],
        },
        "Mounts": mounts or [],
        "HostConfig": {"GroupAdd": group_add or []},
        "NetworkSettings": {"Networks": {network: {} for network in networks}},
    }


def _yiting_containers() -> list[dict[str, object]]:
    containers = [
        _container("a" * 64, project="yiting", service="gateway", networks=["yiting-edge", "yiting-internal"]),
        _container("b" * 64, project="yiting", service="dashboard", networks=["yiting-edge", "yiting-internal"]),
    ]
    for index, service in enumerate(
        [
            "victim",
            "triage",
            "diagnosis",
            "safety_reviewer",
            "commander",
            "operator",
            "recorder-heartbeat",
        ],
        start=3,
    ):
        networks = ["yiting-internal"]
        if service in {"triage", "diagnosis", "safety_reviewer", "commander", "operator"}:
            networks.append("yiting-egress")
        containers.append(
            _container(hex(index)[2:] * 64, project="yiting", service=service, networks=networks)
        )
    containers.append(_container("f" * 64, project="platform", service="caddy", networks=["yiting-edge", "cotenant-edge"]))
    return containers


def test_public_listener_ports_extracts_only_wildcard_listeners() -> None:
    output = "\n".join(
        [
            "LISTEN 0 4096 0.0.0.0:80 0.0.0.0:*",
            "LISTEN 0 4096 [::]:443 [::]:*",
            "LISTEN 0 4096 127.0.0.1:8000 0.0.0.0:*",
            "LISTEN 0 4096 *:22 *:*",
        ]
    )

    assert ecs_ops_acceptance.public_listener_ports(output) == {22, 80, 443}


def test_immutable_image_env_requires_all_shared_host_images() -> None:
    assert ecs_ops_acceptance.check_immutable_image_env(_valid_image_env()).ok is True

    missing = _valid_image_env()
    missing.pop("COTENANT_VICTIM_IMAGE")
    missing_result = ecs_ops_acceptance.check_immutable_image_env(missing)
    assert missing_result.ok is False
    assert "COTENANT_VICTIM_IMAGE missing" in missing_result.detail

    mutable = _valid_image_env()
    mutable["YITING_PYTHON_IMAGE"] = "registry.example.com/yiting/python:latest"
    mutable_result = ecs_ops_acceptance.check_immutable_image_env(mutable)
    assert mutable_result.ok is False
    assert "YITING_PYTHON_IMAGE must be image@sha256:<64 hex chars>" in mutable_result.detail


def test_billing_check_requires_valid_period_beyond_judging() -> None:
    ok = ecs_ops_acceptance.check_billing("2026-08-15", "2026-08-01")
    bad = ecs_ops_acceptance.check_billing("2026-07-15", "2026-08-01")

    assert ok.ok is True
    assert bad.ok is False


def test_uptime_monitor_proof_requires_yiting_monitor(tmp_path: Path) -> None:
    proof = {
        "format": "uptime-monitoring-v1",
        "monitors": [
            {
                "app": "yiting",
                "target_url": "https://track3.example.com",
                "monitor_url": "https://uptime.example.com/yiting",
                "enabled": True,
                "interval_seconds": 60,
            },
        ],
    }
    path = tmp_path / "uptime-monitoring.json"
    path.write_text(json.dumps(proof), encoding="utf-8")

    assert ecs_ops_acceptance.check_uptime_monitor(path).ok is True

    proof["monitors"].clear()
    path.write_text(json.dumps(proof), encoding="utf-8")
    result = ecs_ops_acceptance.check_uptime_monitor(path)
    assert result.ok is False
    assert "missing yiting" in result.detail

    proof["monitors"].append(
        {
            "app": "neighbor",
            "target_url": "https://track4.example.com",
            "monitor_url": "https://uptime.example.com/neighbor",
            "enabled": True,
            "interval_seconds": 0,
        }
    )
    proof["monitors"].append(
        {
            "app": "yiting",
            "target_url": "https://track3.example.com",
            "monitor_url": "https://uptime.example.com/yiting",
            "enabled": True,
            "interval_seconds": 301,
        }
    )
    path.write_text(json.dumps(proof), encoding="utf-8")
    result = ecs_ops_acceptance.check_uptime_monitor(path)
    assert result.ok is False
    assert "yiting: interval_seconds must be 1..300" in result.detail
    assert "neighbor: interval_seconds must be 1..300" in result.detail


def test_app_restart_resilience_proof_requires_persisted_apps(tmp_path: Path) -> None:
    proof = {
        "format": "shared-ecs-app-restart-resilience-v1",
        "artifact_class": "live_app_restart_resilience",
        "submission_evidence": True,
        "verified_live": True,
        "restart_scope": "app-scoped Docker Compose service restart",
        "host_rebooted": False,
        "apps": [
            {
                "app": "yiting",
                "url": "https://track3.example.com",
                "healthy_after_restart": True,
                "state_persisted": True,
                "evidence_persisted": True,
                "logs_persisted": True,
            },
            {
                "app": "cotenant",
                "url": "https://track4.example.com",
                "healthy_after_restart": True,
                "state_persisted": True,
                "evidence_persisted": True,
                "logs_persisted": True,
            },
        ],
    }
    path = tmp_path / "app-restart-resilience.json"
    path.write_text(json.dumps(proof), encoding="utf-8")

    assert ecs_ops_acceptance.check_app_restart_resilience(path).ok is True

    proof["apps"][0]["state_persisted"] = False
    proof["host_rebooted"] = True
    path.write_text(json.dumps(proof), encoding="utf-8")
    result = ecs_ops_acceptance.check_app_restart_resilience(path)

    assert result.ok is False
    assert "host_rebooted must be false" in result.detail
    assert "yiting.state_persisted must be true" in result.detail


def test_yiting_runtime_boundaries_reject_cotenant_socket_and_group(monkeypatch) -> None:
    containers = _yiting_containers()
    monkeypatch.setattr(ecs_ops_acceptance, "get_cotenant_control_gid", lambda: "12345")
    monkeypatch.setattr(
        ecs_ops_acceptance,
        "run_cmd",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )

    results = {check.name: check for check in ecs_ops_acceptance.check_yiting_runtime_boundaries(containers, 1)}

    assert results["YITING containers do not mount /run/cotenant or host-agent socket"].ok is True
    assert results["YITING containers do not mount Docker socket"].ok is True
    assert results["YITING containers do not receive cotenant-control GID"].ok is True
    assert results["/run/cotenant absent inside every YITING container"].ok is True
    assert results["YITING SQLite profile has no PostgreSQL credentials"].ok is True

    bad = _yiting_containers()
    bad[0]["Mounts"] = [{"Source": "/run/cotenant", "Destination": "/run/cotenant"}]
    bad[1]["HostConfig"] = {"GroupAdd": ["12345"]}
    bad[2]["Config"]["Env"] = ["DATABASE_URL=postgresql://yiting_app:secret@postgres/yiting_db"]
    results = {check.name: check for check in ecs_ops_acceptance.check_yiting_runtime_boundaries(bad, 1)}

    assert results["YITING containers do not mount /run/cotenant or host-agent socket"].ok is False
    assert results["YITING containers do not receive cotenant-control GID"].ok is False
    assert results["YITING SQLite profile has no PostgreSQL credentials"].ok is False


def test_yiting_network_boundaries_allow_only_yiting_and_platform_edge(monkeypatch) -> None:
    containers = _yiting_containers()

    def fake_network(name: str, _timeout: float) -> dict[str, object]:
        if name == "yiting-edge":
            ids = [containers[0]["Id"], containers[1]["Id"], containers[-1]["Id"]]
        elif name == "yiting-egress":
            ids = [
                item["Id"]
                for item in containers
                if ecs_ops_acceptance.project(item) == "yiting"
                and ecs_ops_acceptance.service(item)
                in {"triage", "diagnosis", "safety_reviewer", "commander", "operator"}
            ]
        else:
            ids = [item["Id"] for item in containers if ecs_ops_acceptance.project(item) == "yiting"]
        return {"Containers": {container_id: {} for container_id in ids}}

    monkeypatch.setattr(ecs_ops_acceptance, "docker_inspect_network", fake_network)
    monkeypatch.setattr(
        ecs_ops_acceptance,
        "run_cmd",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )

    results = {check.name: check for check in ecs_ops_acceptance.check_yiting_network_boundaries(containers, 1)}

    assert results["all expected YITING shared-host services are running"].ok is True
    assert results["YITING containers do not join COTENANT networks"].ok is True
    assert results["YITING SQLite profile does not join database networks"].ok is True
    assert results["only gateway and dashboard join yiting-edge"].ok is True
    assert results["only YITING live-agent workers join yiting-egress"].ok is True
    assert results["all YITING containers join yiting-internal"].ok is True
    assert results["yiting-edge has only approved members"].ok is True
    assert results["yiting-egress has only approved members"].ok is True
    assert results["yiting-internal has only approved members"].ok is True
    assert results["YITING gateway cannot resolve COTENANT private services"].ok is True

    bad = _yiting_containers()
    bad[2]["NetworkSettings"] = {"Networks": {"yiting-internal": {}, "cotenant-internal": {}}}
    results = {check.name: check for check in ecs_ops_acceptance.check_yiting_network_boundaries(bad, 1)}

    assert results["YITING containers do not join COTENANT networks"].ok is False

    db_bad = _yiting_containers()
    db_bad[2]["NetworkSettings"] = {"Networks": {"yiting-internal": {}, "yiting-db": {}}}
    results = {check.name: check for check in ecs_ops_acceptance.check_yiting_network_boundaries(db_bad, 1)}

    assert results["YITING SQLite profile does not join database networks"].ok is False


def test_container_memory_reports_only_yiting_containers(monkeypatch) -> None:
    monkeypatch.setattr(
        ecs_ops_acceptance,
        "docker_json_lines",
        lambda *args, **kwargs: [
            {"Name": "yiting-gateway-1", "MemPerc": "12.5%"},
            {"Name": "cohost-ipfs", "MemPerc": "90.0%"},
        ],
    )

    result = ecs_ops_acceptance.check_container_memory(
        75.0,
        1.0,
        allowed_container_names={"yiting-gateway-1"},
    )[0]

    assert result.ok is True
    assert "yiting-gateway-1=12.5%" in result.detail
    assert "cohost" not in result.detail.lower()


def test_oom_check_ignores_neighboring_projects() -> None:
    yiting = _container("a" * 64, project="yiting", service="gateway", networks=["yiting-internal"])
    yiting["State"] = {"OOMKilled": False}
    cohost = _container("b" * 64, project="cohost", service="gateway", networks=["cohost-internal"])
    cohost["State"] = {"OOMKilled": True}

    result = ecs_ops_acceptance.check_oom([yiting, cohost], project_name="yiting")

    assert result.ok is True
    assert "cohost" not in result.detail.lower()
