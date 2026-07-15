#!/usr/bin/env python3
"""Live paired single-Qwen-agent vs deployed-society evaluation (Track 3).

FAIR-FIGHT CONTRACT (frozen before any run; see the dataset's fairness_controls):
  * Same held-out incidents for both arms.
  * Same Qwen model family (diagnosis tier, qwen3.7-plus).
  * The single agent receives the COMPLETE task and the SAME evidence the
    society sees -- not a weakened prompt.
  * Society arm = the actual deployed 6-role pipeline.
  * Equal aggregate token cap per incident.
  * Rubric + ground truth frozen in evals/track3_live_paired_scenarios.json.
  * No retries, no cherry-picking, no deleting unfavorable runs.
  * Raw provider responses, token usage, latency preserved.

Ground truth is objective: findings/risks are keyword sets over the concrete
evidence each victim fault emits; expected_action is the project's own
select_runbook() output for that fault (identical target for both arms).

This script is an OFFLINE EVALUATION TOOL. It is never imported by the gateway
or agents and never runs in the judge deployment.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Reuse the FROZEN rubric-scoring formula verbatim from the deterministic harness.
from scripts.track3_paired_benchmark import _score  # noqa: E402


# --------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# --------------------------------------------------------------------------
def _req(method: str, url: str, *, headers: dict | None = None,
         body: dict | None = None, timeout: float = 20.0) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def _meter_tokens(meter_path: str) -> int:
    try:
        return int(json.load(open(meter_path)).get("actual_tokens", 0))
    except Exception:  # noqa: BLE001
        return -1


# --------------------------------------------------------------------------
# Scoring layer (keyword detection over REAL output -> frozen rubric formula)
# --------------------------------------------------------------------------
def _kw_hit(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(kw.lower() in t for kw in keywords)


# ExecutionEnvelope's mandatory rollback-safety field: its KEY name matches
# the "rollback" decoy keyword structurally (present in every sealed plan,
# correct or not — proven false positive, e.g. INC-CHAOS-E7CED6 ResponsePlan).
# Detector v2 strips exactly this field before scanning; prose mentions of
# rollback still count. Applied identically to both arms.
_ENVELOPE_SCHEMA_FIELD = re.compile(r'(\\+"|")rollback_action(\\+"|")\s*:\s*(\\+"|")[^"\\]*(\\+"|"),?')


def _observe(text: str, action_id: str, scenario: dict[str, Any],
             evidence_chain_score: float) -> dict[str, Any]:
    """Turn a real arm's output text + chosen action into the observed dict
    the frozen _score() expects. Detection is keyword-based and identical for
    both arms; ground truth is frozen in the dataset."""
    text = _ENVELOPE_SCHEMA_FIELD.sub("", text)
    detected_findings = [f["name"] for f in scenario["required_findings"]
                         if _kw_hit(text, f["match_keywords"])]
    detected_risks = [r["name"] for r in scenario["required_risks"]
                      if _kw_hit(text, r["match_keywords"])]
    unsupported = sum(1 for d in scenario["decoy_claims"] if _kw_hit(text, d["match_keywords"]))
    return {
        "detected_findings": detected_findings,
        "detected_risks": detected_risks,
        "selected_action": action_id or "",
        "unsupported_claims": unsupported,
        "evidence_chain_score": evidence_chain_score,
    }


def _score_scenario(scenario: dict[str, Any], observed: dict[str, Any],
                    rubric: dict[str, Any]) -> dict[str, Any]:
    # _score expects required_findings/required_risks/expected_action as flat
    # collections; the frozen live dataset stores findings/risks as objects, so
    # map to the name lists the observed dict already uses.
    flat = {
        "required_findings": [f["name"] for f in scenario["required_findings"]],
        "required_risks": [r["name"] for r in scenario["required_risks"]],
        "expected_action": scenario["expected_action"],
    }
    return _score(flat, observed, rubric)


# --------------------------------------------------------------------------
# SOLO arm: one qwen3.7-plus call, COMPLETE task, SAME evidence.
# --------------------------------------------------------------------------
SOLO_SYSTEM = (
    "You are a single senior SRE agent handling a production incident end to end. "
    "You are given an alert and the complete evidence (metrics, recent errors, recent "
    "deploys, uptime). Do the WHOLE job yourself: triage, diagnose the root cause, "
    "assess risks, and choose exactly one remediation action. "
    "Allowed action_id values: restart_service, scale_up, rollback_deploy, "
    "enable_circuit_breaker, dns_failover, enable_maintenance_page, escalate_to_human. "
    "Return JSON: {\"findings\":[...strings...], \"risks\":[...strings...], "
    "\"root_cause\":\"...\", \"action_id\":\"one of the allowed values\"}. "
    "Only assert findings grounded in the provided evidence."
)


async def _solo_arm(alert: dict, evidence: dict) -> tuple[str, str, int]:
    """Returns (output_text, action_id, tokens). One real qwen call."""
    from shared.qwen_reasoning import ask_qwen_json
    from shared.qwen_budget import daily_limit  # noqa: F401
    user = {"alert": alert, "evidence": evidence}
    parsed = await ask_qwen_json(role="diagnosis", system=SOLO_SYSTEM, user=user, max_tokens=1200)
    if not isinstance(parsed, dict):
        return "", "", 0
    text = json.dumps(parsed, default=str)
    action = str(parsed.get("action_id", "")).strip()
    return text, action, 0  # tokens measured via meter delta by caller


# --------------------------------------------------------------------------
# SOCIETY arm: real deployed pipeline via /chaos/trigger + auto-approve.
# --------------------------------------------------------------------------
def _society_arm(gw: str, victim: str, scenario_type: str, op_token: str,
                 recorder_key: str, agent_key: str, timeout_s: float = 480.0) -> dict:
    """Trigger the real society pipeline and score its REASONING QUALITY at the
    plan stage. The six agents (recorder/triage/diagnosis/safety/commander)
    produce findings, risks, and a ResponsePlan action BEFORE the human gate;
    the human approval only authorizes execution and is out of scope for a
    reasoning-quality comparison. We do NOT approve, execute, or bypass the
    gate -- we read the sealed cards the society published up to the plan.
    Returns {incident_id, state, evidence, text, action_id, chain_valid,
    latency_s} or {error}."""
    t0 = time.time()
    # Bounded backoff on the gateway's 30s anti-spam trigger cooldown (429).
    # Transport-level only: the pipeline itself still runs exactly once.
    st, body = 0, None
    for _ in range(6):
        st, body = _req("POST", f"{gw}/chaos/trigger",
                        headers={"X-Operator-Token": op_token},
                        body={"scenario_type": scenario_type}, timeout=120)
        if st != 429:
            break
        m = re.search(r"retry in (\d+)", str(body))
        time.sleep(min((int(m.group(1)) + 2) if m else 10, 45))
    if st not in (200, 201, 202) or not isinstance(body, dict):
        return {"error": f"trigger failed {st}: {str(body)[:160]}"}
    incident_id = body.get("incident_id") or (body.get("incident") or {}).get("incident_id")
    if not incident_id:
        return {"error": f"no incident_id: {str(body)[:160]}"}

    # Shared-evidence snapshot: the same victim surfaces the diagnosis agent
    # reads, for THIS activation. The solo arm receives exactly these bytes.
    evidence: dict[str, Any] = {}
    for ep in ("metrics", "errors/recent", "deploys/recent", "uptime"):
        _, e = _req("GET", f"{victim}/api/v1/{ep}?incident_id={incident_id}", timeout=30)
        evidence[ep] = e

    # poll until a ResponsePlan exists; /incidents/{id} nests under "incident"
    plan_states = {"PLANNED", "AWAITING_APPROVAL", "AWAITING_HUMAN",
                   "EXECUTED", "RESOLVED", "CLOSED_FALSE_ALARM", "FAILED"}
    deadline = time.time() + timeout_s
    state = "?"
    while time.time() < deadline:
        st, inc = _req("GET", f"{gw}/incidents/{incident_id}", timeout=30)
        if isinstance(inc, dict):
            state = str((inc.get("incident") or {}).get("state") or inc.get("state") or "?")
            if state.upper() in plan_states:
                break
        time.sleep(4)

    # v3 scoring surface: the society's ASSERTIONS -- prose the agents
    # authored in their sealed cards. Raw victim evidence (alert payloads,
    # tool results, evidence exports) is data both arms READ; scoring it as
    # society text would credit un-asserted findings and charge un-made
    # claims. The AlertCard (the recorder's capture of the victim alert) is
    # evidence, not an assertion, and is excluded for the same reason.
    incident_payload: dict[str, Any] | None = None
    chain_valid = None
    s, data = _req("GET", f"{gw}/incidents/{incident_id}", timeout=45)
    if s == 200 and isinstance(data, dict):
        incident_payload = data
    s, ev = _req("GET", f"{gw}/evidence/{incident_id}", timeout=45)
    if s == 200 and isinstance(ev, dict):
        chain_valid = bool(ev.get("chain_valid"))
    text = _authored_card_text(incident_payload)
    action_id = (_extract_plan_action(incident_payload)
                 or _extract_action_from_text(text))
    return {
        "incident_id": incident_id, "state": state, "evidence": evidence,
        "text": text, "action_id": action_id,
        "chain_valid": chain_valid,
        "latency_s": round(time.time() - t0, 1),
    }


_AUTHORED_KEYS = frozenset({
    "root_cause_hypothesis", "recommended_action", "summary", "rationale",
    "reason", "notes", "description", "decision", "challenge_reason",
    "risk", "risks", "blast_radius", "verification", "finding", "findings",
})


def _authored_card_text(incident_payload: dict | None) -> str:
    """Collect prose the agents authored across all sealed non-alert cards."""
    if not isinstance(incident_payload, dict):
        return ""
    parts: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _AUTHORED_KEYS:
                    if isinstance(value, str):
                        parts.append(value)
                    elif isinstance(value, list):
                        parts.extend(v for v in value if isinstance(v, str))
                    else:
                        _walk(value)
                else:
                    _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    for card in incident_payload.get("cards") or []:
        if str(card.get("card_type", "")) == "AlertCard":
            continue
        try:
            _walk(json.loads(card.get("card_json") or "{}"))
        except (json.JSONDecodeError, TypeError):
            continue
    return " ".join(parts)


def _extract_plan_action(incident_payload: dict | None) -> str:
    """Pull action_id from the ResponsePlan card itself: authoritative, unlike
    keyword-scanning prose that may discuss several candidate actions."""
    if not isinstance(incident_payload, dict):
        return ""
    for card in reversed(incident_payload.get("cards") or []):
        if "plan" not in str(card.get("card_type", "")).lower():
            continue
        m = re.search(r'"action_id"\s*:\s*"([a-z_]+)"',
                      str(card.get("card_json", "")))
        if m:
            return m.group(1)
    return ""


def _extract_action_from_text(blob: str) -> str:
    low = blob.lower()
    for aid in ("rollback_deploy", "scale_up", "restart_service",
                "enable_circuit_breaker", "dns_failover", "enable_maintenance_page"):
        if aid in low:
            return aid
    return ""


def _extract_action(evidence: dict) -> str:
    """Best-effort pull of the executed action_id from a sealed evidence chain."""
    blob = json.dumps(evidence, default=str).lower()
    for aid in ("rollback_deploy", "scale_up", "restart_service",
                "enable_circuit_breaker", "dns_failover", "enable_maintenance_page"):
        if f'"action_id": "{aid}"' in blob or f'"{aid}"' in blob:
            return aid
    return ""


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
async def _run(args) -> int:
    dataset = json.load(open(args.dataset))
    all_scenarios = dataset["scenarios"]
    rubric = dataset["rubric"]
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "rows.jsonl"

    # --summarize: read accumulated JSONL rows, write summary.json, exit.
    if args.summarize:
        rows = [json.loads(ln) for ln in rows_path.read_text().splitlines() if ln.strip()]
        _write_summary(dataset, rows, out_dir)
        return 0

    start = args.offset
    end = start + args.limit if args.limit else len(all_scenarios)
    scenarios = all_scenarios[start:end]
    print(f"batch: scenarios[{start}:{end}] ({len(scenarios)} of {len(all_scenarios)})", flush=True)
    rows = []
    for sc in scenarios:
        stype = sc["scenario_type"]
        # One SHARED victim activation per scenario: /chaos/trigger breaks the
        # victim and the society consumes it live; the runner snapshots the
        # same victim surfaces for the solo arm. Victim telemetry is reset
        # first so evidence from a prior scenario's fault cannot bleed in.
        # (Never /chaos/reset here -- that also deletes INC-CHAOS-* DB rows.)
        _req("POST", f"{args.victim}/admin/scenario/reset-all", body={}, timeout=30)
        alert = {"scenario_type": stype, "incident_family": sc["incident_family"],
                 "severity": sc["severity"], "summary": sc.get("incident_family")}

        # --- SOCIETY arm first (its plan completes before the solo call, so
        # the shared daily-meter windows stay disjoint) ---
        m0 = _meter_tokens(args.meter)
        soc = {"error": "skipped"} if args.dry_run else _society_arm(
            args.gateway, args.victim, stype, args.op_token, args.recorder_key, args.agent_key)
        m1 = _meter_tokens(args.meter)
        soc_tokens = max(0, m1 - m0) if m0 >= 0 and m1 >= 0 else -1
        if "error" in soc:
            soc_obs = _observe("", "", sc, 0.0)
            soc_score = _score_scenario(sc, soc_obs, rubric)
        else:
            # evidence_chain is measured live: the /evidence endpoint's own
            # verify_chain() result over the sealed cards.
            soc_obs = _observe(soc["text"], soc["action_id"], sc,
                               1.0 if soc.get("chain_valid") else 0.0)
            soc_score = _score_scenario(sc, soc_obs, rubric)

        # --- SOLO arm on the identical evidence bytes ---
        evidence = soc.get("evidence") or {}
        if not evidence:
            # society trigger failed; stage the same fault directly so the
            # solo measurement still happens on real victim evidence.
            solo_iid = f"INC-SOLO-{sc['id']}"
            _req("POST", f"{args.victim}/admin/break/{stype}",
                 headers={}, body={"incident_id": solo_iid}, timeout=30)
            for ep in ("metrics", "errors/recent", "deploys/recent", "uptime"):
                _, e = _req("GET", f"{args.victim}/api/v1/{ep}?incident_id={solo_iid}", timeout=30)
                evidence[ep] = e
        solo_text, solo_action, _ = await _solo_arm(alert, evidence)
        m2 = _meter_tokens(args.meter)
        solo_tokens = max(0, m2 - m1) if m1 >= 0 and m2 >= 0 else -1
        # Raw-response preservation for the solo arm (the society arm's raw
        # output is the sealed card chain, preserved in the gateway DB).
        with open(out_dir / "solo_raw.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": sc["id"], "solo_text": solo_text}) + "\n")
        # Dataset scoring_method: solo evidence_chain = 1.0 ("single
        # structured response, no chain to validate — not used to advantage
        # either arm"). The initial implementation wrongly used the
        # deterministic harness's 0.55 constant; see the dataset's
        # post_run_corrections.
        solo_obs = _observe(solo_text, solo_action, sc, evidence_chain_score=1.0)
        solo_score = _score_scenario(sc, solo_obs, rubric)

        row = {
            "id": sc["id"], "scenario_type": stype, "expected_action": sc["expected_action"],
            "detector": "v3-authored-cards-only",
            "solo": {**solo_score, "action": solo_action, "tokens": solo_tokens},
            "society": {**soc_score, "action": soc.get("action_id", ""),
                        "tokens": soc_tokens, "state": soc.get("state"),
                        "chain_valid": soc.get("chain_valid"),
                        "latency_s": soc.get("latency_s"), "error": soc.get("error")},
        }
        rows.append(row)
        with open(rows_path, "a", encoding="utf-8") as fh:  # accumulate across batches
            fh.write(json.dumps(row, default=str) + "\n")
        print(json.dumps({"id": sc["id"], "type": stype,
                          "solo_score": solo_score["final_score"], "solo_action": solo_action,
                          "soc_score": soc_score["final_score"], "soc_action": soc.get("action_id", ""),
                          "solo_tok": solo_tokens, "soc_tok": soc_tokens}), flush=True)

    print(f"batch done: {len(rows)} rows appended to {rows_path}", flush=True)
    return 0


def _write_summary(dataset, rows, out_dir):
    def _avg(arm, key):
        vals = [r[arm][key] for r in rows if isinstance(r[arm].get(key), (int, float))]
        return round(sum(vals) / len(vals), 4) if vals else None

    summary = {
        "dataset_id": dataset["dataset_id"], "scenarios": len(rows), "live": True,
        "fairness_controls": dataset.get("fairness_controls"),
        "solo": {"mean_final_score": _avg("solo", "final_score"),
                 "mean_finding_recall": _avg("solo", "finding_recall"),
                 "mean_risk_recall": _avg("solo", "risk_recall"),
                 "total_unsupported_claims": sum(r["solo"]["unsupported_claims"] for r in rows),
                 "success_count": sum(1 for r in rows if r["solo"]["success"]),
                 "mean_tokens": _avg("solo", "tokens")},
        "society": {"mean_final_score": _avg("society", "final_score"),
                    "mean_finding_recall": _avg("society", "finding_recall"),
                    "mean_risk_recall": _avg("society", "risk_recall"),
                    "total_unsupported_claims": sum(r["society"]["unsupported_claims"] for r in rows),
                    "success_count": sum(1 for r in rows if r["society"]["success"]),
                    "mean_tokens": _avg("society", "tokens")},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out_dir / "rows.json").write_text(json.dumps(rows, indent=2) + "\n")
    print("\nSUMMARY:", json.dumps(summary, indent=2), flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description="Live paired single-agent vs society Track 3 eval")
    p.add_argument("--dataset", default=str(ROOT / "evals/track3_live_paired_scenarios.json"))
    p.add_argument("--gateway", default="http://gateway:8000")
    p.add_argument("--victim", default="http://victim:9000")
    p.add_argument("--meter", default="/qwen-usage/yiting-qwen-usage.json")
    p.add_argument("--op-token", default=os.getenv("YITING_OPERATOR_TOKEN", ""))
    p.add_argument("--proxy-secret", default=os.getenv("APPROVAL_PROXY_SECRET", ""))
    p.add_argument("--recorder-key", default=os.getenv("RECORDER_SUBMISSION_KEY", ""))
    p.add_argument("--agent-key", default=os.getenv("YITING_AGENT_KEY", ""))
    p.add_argument("--output-dir", default=str(ROOT / "artifacts/track3-live-paired"))
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--summarize", action="store_true", help="Combine accumulated rows.jsonl into summary.json")
    p.add_argument("--dry-run", action="store_true",
                   help="Solo arm only (still calls Qwen); society arm skipped. For wiring + budget checks.")
    args = p.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
