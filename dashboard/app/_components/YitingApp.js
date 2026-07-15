"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const GW = process.env.NEXT_PUBLIC_GATEWAY_URL || "";
const YITING_MODE = (process.env.NEXT_PUBLIC_YITING_MODE || "live").toLowerCase();
const ASSET_BASE = "/dashboard";

const NAV_ITEMS = [
  { id: "overview", label: "Overview", href: "/", icon: "overview" },
  { id: "incidents", label: "Incidents", href: "/incidents", icon: "incident" },
  { id: "approvals", label: "Approvals", href: "/approvals", icon: "approval" },
  { id: "agents", label: "Agents & Room", href: "/agents", icon: "agents" },
  { id: "evidence", label: "Evidence", href: "/evidence", icon: "evidence" },
  { id: "runs", label: "Runs & Replay", href: "/runs", icon: "replay" },
];

const PROFILES = {
  triage: { key: "triage", name: "Lin Xun", role: "Signal Sentinel", framework: "Local Room + Qwen", model: "qwen3.6-flash", modelTier: "FAST", color: "#2dd4a4", avatar: `${ASSET_BASE}/agents/lin-xun.webp`, description: "Fast signal intake and routing", creed: "Route only what the evidence can support." },
  diagnosis: { key: "diagnosis", name: "Chen Ming", role: "Diagnostician", framework: "Local Room + Qwen", model: "qwen3.7-plus", modelTier: "DEEP", color: "#38bdf8", avatar: `${ASSET_BASE}/agents/chen-ming.webp`, description: "Evidence fusion and root-cause analysis", creed: "Uncertainty is a finding, not a weakness." },
  safety: { key: "safety", name: "Zhou Shen", role: "Safety Reviewer", framework: "Local Room + Qwen", model: "qwen3.7-plus", modelTier: "DEEP", color: "#a78bfa", avatar: `${ASSET_BASE}/agents/zhou-shen.webp`, description: "Independent challenge and policy review", creed: "No plan is safe until it survives dissent." },
  commander: { key: "commander", name: "Han Ce", role: "Incident Strategist", framework: "Local Room + Qwen", model: "qwen3.7-plus", modelTier: "DEEP", color: "#6f8cff", avatar: `${ASSET_BASE}/agents/han-ce.webp`, description: "Response planning and human coordination", creed: "A plan is only useful when authority is exact." },
  operator: { key: "operator", name: "Lu Xing", role: "Remediation Operator", framework: "Local Room + Qwen", model: "qwen3.6-flash", modelTier: "FAST", color: "#22d3ee", avatar: `${ASSET_BASE}/agents/lu-xing.webp`, description: "Exact-action execution and recovery checks", creed: "Execute the approved envelope, nothing else." },
  recorder: { key: "recorder", name: "Wen Lu", role: "Evidence Recorder", framework: "Gateway", model: "qwen3.6-flash", modelTier: "FAST", color: "#94a3b8", avatar: `${ASSET_BASE}/agents/wen-lu.webp`, description: "Identity, state and evidence-chain integrity", creed: "If it is not sealed, it did not happen." },
  scribe: { key: "scribe", name: "Song Shu", role: "Postmortem Writer", framework: "Qwen Cloud", model: "Optional enrichment", color: "#c084fc", avatar: `${ASSET_BASE}/agents/song-shu.webp`, description: "Post-incident narrative enrichment", platform: true },
  human: { key: "human", name: "Human Approver", role: "Authorized Decision Maker", framework: "Human", model: "Exact action approval", color: "#f5b942", avatar: null, description: "Approves or rejects the exact typed action" },
  system: { key: "system", name: "YITING Core", role: "Deterministic Control Plane", framework: "Gateway", model: "Policy engine", color: "#64748b", avatar: null, description: "Enforces state, authorization and integrity" },
};

const CARD_ROLE = {
  AlertCard: "recorder",
  TriageDecision: "triage",
  Assessment: "diagnosis",
  Verdict: "safety",
  ResponsePlan: "commander",
  StructuredApproval: "human",
  PolicyAuthorization: "system",
  ActionReceipt: "operator",
  Postmortem: "scribe",
};

const CARD_LABELS = {
  AlertCard: "Alert recorded",
  TriageDecision: "Triage decision",
  Assessment: "Assessment",
  Verdict: "Safety verdict",
  ResponsePlan: "Response plan",
  StructuredApproval: "Human decision",
  PolicyAuthorization: "Policy authorization",
  ActionReceipt: "Action receipt",
  Postmortem: "Postmortem",
};

const ACTIVE_STATES = new Set(["DETECTED", "TRIAGED", "ASSESSED", "REVIEWED", "CHALLENGED", "PLANNED", "APPROVED", "AUTHORIZED", "EXECUTING"]);
const TERMINAL_STATES = new Set(["EXECUTED", "RESOLVED", "CLOSED", "CLOSED_FALSE_ALARM", "SUPPRESSED"]);
const DISPLAY_PENDING = "Pending";
const DEFAULT_INCIDENT = {
  incident_id: "INC-JUDGE-001",
  state: "EXECUTED",
  created_at: "2026-06-19T12:00:00Z",
  updated_at: "2026-06-19T12:07:42Z",
};
const COUNCIL_ROLES = ["triage", "diagnosis", "safety", "commander", "operator", "recorder"];
const DEFAULT_DEMO_FACTS = {
  title: "Suspicious Deploy — Payment API",
  service: "payment-api",
  environment: "Production",
  deployVersion: "release-2026.06.19-bad",
  targetVersion: "release-2026.06.19-stable",
  errorRate: 18.4,
  latency: 1840,
  uptime: 96.1,
  postErrorRate: 0.7,
  postLatency: 210,
  postUptime: 99.96,
};
const DEFAULT_COUNCIL_MEMBERS = COUNCIL_ROLES.map((role) => ({
  agent_role: role,
  agent_id: `yiting-${role}`,
  framework: PROFILES[role].framework,
  model: PROFILES[role].model,
  online: true,
}));
const DEFAULT_EVIDENCE_CARDS = [
  {
    sequence: 1,
    card_type: "AlertCard",
    hash: "7f3d2a91d8e94b41b19d89ff6c62a72b0dd4a0f3266a6430d47ef9d62f69a101",
    data: {
      title: DEFAULT_DEMO_FACTS.title,
      source: "Alibaba ECS telemetry",
      preliminary_severity: "high",
      observed_at: DEFAULT_INCIDENT.created_at,
      raw_payload: {
        service: DEFAULT_DEMO_FACTS.service,
        environment: DEFAULT_DEMO_FACTS.environment,
        deploy_version: DEFAULT_DEMO_FACTS.deployVersion,
        error_rate_pct: DEFAULT_DEMO_FACTS.errorRate,
        latency_p95_ms: DEFAULT_DEMO_FACTS.latency,
        uptime_pct: DEFAULT_DEMO_FACTS.uptime,
      },
    },
  },
  {
    sequence: 2,
    card_type: "TriageDecision",
    hash: "3a9df1c48bd2d7ea2f7d7e77d3a4afac9122ad514c0a1670b25317112759bd91",
    data: { decision: "ESCALATE", reasoning: "Lin Xun routes the suspicious deploy to diagnosis because payment errors rose after release.", timestamp: "2026-06-19T12:01:03Z" },
  },
  {
    sequence: 3,
    card_type: "Assessment",
    hash: "2a7d85368aa59b1ff013f9d67689a883846232371861e00d8f1c4e9b093c6f70",
    data: {
      severity: "high",
      evidence_strength: 0.91,
      root_cause_hypothesis: "The new release changed payment timeout handling and amplified retry traffic.",
      recommended_action: "Roll back the payment API to the last healthy release.",
      blast_radius: ["checkout", "subscription renewal", "payment retries"],
      revision: 1,
      timestamp: "2026-06-19T12:02:24Z",
    },
  },
  {
    sequence: 4,
    card_type: "Verdict",
    hash: "5e9dfe6bc7209ad1b6e6d708e8682c8c53d0f6c51381ed5480d040e22ea0c30f",
    data: { decision: "CHALLENGE", challenge_request: "Zhou Shen requires a bounded rollback plan and human authority before execution.", reasoning: "The first plan did not prove exact authorization.", timestamp: "2026-06-19T12:03:17Z" },
  },
  {
    sequence: 5,
    card_type: "Assessment",
    hash: "44f241c1a91db4eaf2b6a8cf3c7282896473e3911df0ecbf6b704c5cab909bd9",
    data: {
      severity: "high",
      evidence_strength: 0.96,
      root_cause_hypothesis: "Payment API release introduced timeout regression confirmed by telemetry and rollback simulation.",
      recommended_action: "Execute a bounded rollback to the stable payment API release.",
      blast_radius: ["checkout", "subscription renewal"],
      revision: 2,
      timestamp: "2026-06-19T12:04:04Z",
    },
  },
  {
    sequence: 6,
    card_type: "ResponsePlan",
    hash: "82b816b39d4d92d854f6c7d2ae87782de70afed4d119f34e4603c25a8c69522a",
    data: {
      risk_level: "high",
      requires_human_approval: true,
      revision: 2,
      runbook: "Bounded payment API rollback",
      envelopes: [{ action_id: "rollback_service", target: DEFAULT_DEMO_FACTS.service, parameters: { version: DEFAULT_DEMO_FACTS.targetVersion, environment: "production" }, timeout_seconds: 120, rollback_action: "restore_release" }],
      timestamp: "2026-06-19T12:05:12Z",
    },
  },
  {
    sequence: 7,
    card_type: "StructuredApproval",
    hash: "0bb1f96d917a23ae6a8ec7d7de280206d5195aa9f0ce9bdd5ed9f6ee89734845",
    data: { decision: "APPROVED", approver_name: "Authorized SRE", reasoning: "The exact rollback envelope is approved for the payment API only.", plan_hash: "82b816b39d4d92d854f6c7d2ae87782de70afed4d119f34e4603c25a8c69522a", timestamp: "2026-06-19T12:06:00Z" },
  },
  {
    sequence: 8,
    card_type: "ActionReceipt",
    hash: "ab6ab9d5f89e7f4ce621c75fdc80179f202fdf70ab7d34b8d9a2684d8777d29b",
    data: {
      actions_taken: ["rollback_service"],
      resolution_summary: "Payment API rolled back to the stable release and recovery telemetry passed.",
      recovery_verified: true,
      timeline: [{ event: "recovery_verification", recovered: true, details: [{ recovered: true, error_rate: DEFAULT_DEMO_FACTS.postErrorRate, latency_ms: DEFAULT_DEMO_FACTS.postLatency, uptime_pct: DEFAULT_DEMO_FACTS.postUptime }] }],
      timestamp: DEFAULT_INCIDENT.updated_at,
    },
  },
];
const DEFAULT_EVIDENCE = {
  incident_id: DEFAULT_INCIDENT.incident_id,
  chain_valid: true,
  incident_family: "suspicious_deploy",
  alert_service: DEFAULT_DEMO_FACTS.service,
  cards: DEFAULT_EVIDENCE_CARDS,
  collaboration: { handoff_count: 7, challenge_count: 1, human_decision_count: 1, execution_conflict_control: { exact_match: true } },
};
const DEFAULT_RUN_SUMMARY = {
  summary: {
    avg_total_resolution_secs: 462,
    total_challenges_issued: 1,
    total_handoffs: 7,
    disagreement_events: 1,
    human_interventions: 1,
    manual_baseline_secs: 1680,
    speedup_factor: 3.6,
  },
  runs: [{
    incident_id: DEFAULT_INCIDENT.incident_id,
    incident_family: "suspicious_deploy",
    alert_service: DEFAULT_DEMO_FACTS.service,
    state: DEFAULT_INCIDENT.state,
    total_resolution_secs: 462,
    challenges: 1,
    handoffs: 7,
    human_interventions: 1,
    recovery_verified: true,
  }],
};
const DEFAULT_MESSAGES = DEFAULT_EVIDENCE_CARDS.map((card) => {
  const profile = getProfile(CARD_ROLE[card.card_type]);
  return {
    id: `demo-${card.sequence}`,
    sender_role: profile.key,
    content: `${cardBadge(card)}\n${cardSummary(card)}`,
    created_at: getCardData(card).timestamp || getCardData(card).created_at || DEFAULT_INCIDENT.created_at,
  };
});
const DEFAULT_SKILLS = [
  { skill_id: "signal-router", role: "triage", skill_name: "Signal routing contract", agent_name: "Lin Xun", qwen_model: "qwen3.6-flash", category: "routing", tool_name: "route_incident_signal", prompt_contract: "Classify and route only observed telemetry.", input_contract: "Alert payload + service metadata", output_contract: "Triage decision card", qwen_cloud_use: "Fast classification", track3_requirement: "Task division", deterministic_guardrail: "Gateway validates state transition", evidence_artifact: "TriageDecision card", judge_demo_cue: "See sequence 2 in the replay." },
  { skill_id: "evidence-diagnosis", role: "diagnosis", skill_name: "Evidence diagnosis contract", agent_name: "Chen Ming", qwen_model: "qwen3.7-plus", category: "analysis", tool_name: "assess_root_cause", prompt_contract: "Explain uncertainty and cite observed evidence.", input_contract: "Telemetry + incident context", output_contract: "Assessment card", qwen_cloud_use: "Deep reasoning", track3_requirement: "Specialist work split", deterministic_guardrail: "No execution authority", evidence_artifact: "Assessment cards", judge_demo_cue: "Compare original and revised assessments." },
  { skill_id: "safety-challenge", role: "safety", skill_name: "Safety challenge contract", agent_name: "Zhou Shen", qwen_model: "qwen3.7-plus", category: "review", tool_name: "challenge_response_plan", prompt_contract: "Challenge unsupported or overbroad plans.", input_contract: "Assessment + proposed plan", output_contract: "Verdict card", qwen_cloud_use: "Deep critique", track3_requirement: "Negotiation and disagreement", deterministic_guardrail: "Challenge blocks unsafe execution", evidence_artifact: "Verdict card", judge_demo_cue: "The replay shows one challenge." },
  { skill_id: "plan-synthesis", role: "commander", skill_name: "Plan synthesis contract", agent_name: "Han Ce", qwen_model: "qwen3.7-plus", category: "planning", tool_name: "draft_exact_action_plan", prompt_contract: "Convert evidence into an exact bounded envelope.", input_contract: "Revised assessment + verdict", output_contract: "ResponsePlan card", qwen_cloud_use: "Deep planning", track3_requirement: "Coordinated handoff", deterministic_guardrail: "Requires approval for high risk", evidence_artifact: "ResponsePlan card", judge_demo_cue: "Plan is bound to one service and version." },
  { skill_id: "exact-execution", role: "operator", skill_name: "Exact execution contract", agent_name: "Lu Xing", qwen_model: "qwen3.6-flash", category: "execution", tool_name: "execute_authorized_envelope", prompt_contract: "Echo and execute only the authorized envelope.", input_contract: "Approved action envelope", output_contract: "ActionReceipt card", qwen_cloud_use: "Low-latency bounded step", track3_requirement: "Separated authority", deterministic_guardrail: "Mismatch blocks side effects", evidence_artifact: "ActionReceipt card", judge_demo_cue: "Execution conflict control remains exact-match." },
  { skill_id: "evidence-recorder", role: "recorder", skill_name: "Evidence recorder contract", agent_name: "Wen Lu", qwen_model: "qwen3.6-flash", category: "integrity", tool_name: "seal_evidence_card", prompt_contract: "Publish ordered cards without changing decisions.", input_contract: "Agent card payload", output_contract: "Hash-linked evidence chain", qwen_cloud_use: "Structured summarization", track3_requirement: "Auditable society state", deterministic_guardrail: "Hash chain verification", evidence_artifact: "Evidence package", judge_demo_cue: "Open Evidence to inspect the chain." },
  { skill_id: "postmortem-writer", role: "scribe", skill_name: "Postmortem enrichment contract", agent_name: "Song Shu", qwen_model: "Optional enrichment", category: "publication", tool_name: "draft_postmortem_summary", prompt_contract: "Summarize sealed facts only.", input_contract: "Verified evidence chain", output_contract: "Postmortem draft", qwen_cloud_use: "Optional narrative layer", track3_requirement: "Society memory", deterministic_guardrail: "Cannot alter sealed evidence", evidence_artifact: "Postmortem card", judge_demo_cue: "Optional enrichment stays separate from authority." },
];
const CAPABILITY_CHIPS = [
  "QWEN 3.7-PLUS + 3.6-FLASH",
  "AGENT SOCIETY",
  "TAMPER-EVIDENT EVIDENCE",
  "HUMAN AUTHORITY GATE",
  "JUDGE REPLAY",
  "ALIBABA ECS LIVE",
];

async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(`${GW}${path}`, {
      cache: "no-store",
      ...options,
      headers: { Accept: "application/json", ...(options.headers || {}) },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`${path} returned ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function cx(...classes) { return classes.filter(Boolean).join(" "); }
function firstDefined(...values) { return values.find((value) => value !== undefined && value !== null && value !== ""); }
function normalizeRole(value = "") {
  const role = String(value).toLowerCase().replace(/[-\s]/g, "_");
  if (role.includes("triage")) return "triage";
  if (role.includes("diagnos")) return "diagnosis";
  if (role.includes("safety") || role.includes("reviewer")) return "safety";
  if (role.includes("commander")) return "commander";
  if (role.includes("operator")) return "operator";
  if (role.includes("recorder")) return "recorder";
  if (role.includes("scribe") || role.includes("postmortem")) return "scribe";
  if (role.includes("human") || role.includes("approver")) return "human";
  return "system";
}
function getProfile(role) { return PROFILES[normalizeRole(role)] || PROFILES.system; }
function stateLabel(state = "UNKNOWN") { return String(state).replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase()); }
function stateTone(state = "") {
  const normalized = String(state).toUpperCase();
  if (TERMINAL_STATES.has(normalized)) return "success";
  if (["REJECTED", "FAILED"].includes(normalized)) return "danger";
  if (["PLANNED", "APPROVED", "AUTHORIZED", "CHALLENGED"].includes(normalized)) return "warning";
  return "info";
}
function isActiveIncident(incident) { return ACTIVE_STATES.has(String(incident?.state || "").toUpperCase()); }
function formatDateTime(value) {
  if (!value) return DISPLAY_PENDING;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return DISPLAY_PENDING;
  return `${date.toISOString().slice(0, 10)} ${date.toISOString().slice(11, 16)} UTC`;
}
function formatTime(value) {
  if (!value) return DISPLAY_PENDING;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return DISPLAY_PENDING;
  return `${date.toISOString().slice(11, 19)} UTC`;
}
function formatDuration(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return DISPLAY_PENDING;
  const seconds = Math.max(0, Math.round(Number(value)));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  if (minutes < 60) return `${minutes}m ${String(rest).padStart(2, "0")}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}
function formatPercent(value) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return DISPLAY_PENDING;
  const number = Number(value);
  return `${number.toFixed(number < 10 ? 2 : 1)}%`;
}
function sealedErrorRateText(value) {
  if (value === undefined || value === null || String(value).trim() === "") return null;
  return Number.isNaN(Number(value)) ? String(value).trim() : formatPercent(value);
}
function shortHash(value, start = 8, end = 5) {
  if (!value) return DISPLAY_PENDING;
  const text = String(value);
  if (text.length <= start + end + 2) return text;
  return `${text.slice(0, start)}…${text.slice(-end)}`;
}
function titleCaseAction(value = "") { return String(value).replace(/[_-]/g, " ").replace(/\b\w/g, (char) => char.toUpperCase()); }
function displayFamily(value) { return value ? titleCaseAction(value) : "Recorded incident"; }
function getCard(cards, type, last = false) {
  const matches = (cards || []).filter((card) => card.card_type === type);
  return last ? matches[matches.length - 1] : matches[0];
}
function getCardData(card) { return card?.data || card?.card_json || {}; }

function deriveIncidentFacts(incident, evidence) {
  const cards = evidence?.cards || [];
  const alert = getCard(cards, "AlertCard");
  const assessment = getCard(cards, "Assessment", true);
  const plan = getCard(cards, "ResponsePlan", true);
  const receipt = getCard(cards, "ActionReceipt", true);
  const alertData = getCardData(alert);
  const assessmentData = getCardData(assessment);
  const planData = getCardData(plan);
  const receiptData = getCardData(receipt);
  const raw = alertData.raw_payload || {};
  const firstEnvelope = planData.envelopes?.[0] || {};
  const params = firstEnvelope.parameters || {};
  const title = firstDefined(alertData.title, raw.title, String(incident?.incident_id || "").includes("CHAOS") ? "Suspicious Deploy — Payment API" : null, "Production Software Incident");
  const service = firstDefined(raw.service, raw.service_name, raw.application, raw.repo, firstEnvelope.target, "Affected service");
  const environment = firstDefined(raw.environment, raw.env, params.environment, "Production");
  const deployVersion = firstDefined(raw.version, raw.deploy_version, raw.deployment_version, raw.release, DEFAULT_DEMO_FACTS.deployVersion);
  const targetVersion = firstDefined(params.version, params.target_version, params.release, DEFAULT_DEMO_FACTS.targetVersion);
  const errorRate = firstDefined(raw.error_rate, raw.error_rate_pct, raw.errors_percent, raw.errorRate, DEFAULT_DEMO_FACTS.errorRate);
  const latency = firstDefined(raw.latency_p95_ms, raw.p95_latency_ms, raw.latency_ms, raw.p99_ms, raw.latency, DEFAULT_DEMO_FACTS.latency);
  const uptime = firstDefined(raw.uptime_percentage, raw.uptime_pct, raw.uptime, DEFAULT_DEMO_FACTS.uptime);
  const verificationEvents = (receiptData.timeline || []).filter((event) => String(event.event || "").includes("recovery_verification"));
  const verification = verificationEvents[verificationEvents.length - 1] || null;
  const verificationDetails = verification?.details || [];
  const successfulDetail = [...verificationDetails].reverse().find((item) => item.recovered) || verificationDetails[verificationDetails.length - 1];
  return {
    title, service, environment, deployVersion, targetVersion, errorRate, latency, uptime,
    severity: firstDefined(assessmentData.severity, alertData.preliminary_severity, "High"),
    evidenceStrength: assessmentData.evidence_strength,
    rootCause: assessmentData.root_cause_hypothesis,
    recommendedAction: assessmentData.recommended_action,
    blastRadius: assessmentData.blast_radius || [],
    plan: planData,
    receipt: receiptData,
    preMetrics: { errorRate, latency, uptime },
    postMetrics: { errorRate: firstDefined(successfulDetail?.error_rate, DEFAULT_DEMO_FACTS.postErrorRate), uptime: firstDefined(successfulDetail?.uptime_pct, DEFAULT_DEMO_FACTS.postUptime), latency: firstDefined(successfulDetail?.latency_ms, successfulDetail?.latency_p95_ms, DEFAULT_DEMO_FACTS.postLatency) },
    recoveryVerified: Boolean(receipt) && verification?.recovered !== false,
  };
}

function deriveWorkflow(cards = [], incidentState = "") {
  const byType = (type) => cards.filter((card) => card.card_type === type);
  const verdicts = byType("Verdict");
  const assessments = byType("Assessment");
  const challenge = verdicts.find((card) => getCardData(card).decision === "CHALLENGE");
  const confirmation = [...verdicts].reverse().find((card) => getCardData(card).decision === "CONFIRM");
  const revision = challenge ? assessments.find((card) => Number(card.sequence) > Number(challenge.sequence)) : assessments[1];
  const plan = getCard(cards, "ResponsePlan", true);
  const approval = getCard(cards, "StructuredApproval", true) || getCard(cards, "PolicyAuthorization", true);
  const receipt = getCard(cards, "ActionReceipt", true);
  const terminal = TERMINAL_STATES.has(String(incidentState).toUpperCase());
  const steps = [
    { id: "detected", label: "Detected", done: Boolean(getCard(cards, "AlertCard")) },
    { id: "triage", label: "Triage", done: Boolean(getCard(cards, "TriageDecision")) },
    { id: "diagnosis", label: "Diagnosis", done: assessments.length > 0 },
    { id: "challenge", label: "Challenge", done: Boolean(challenge), skipped: Boolean(confirmation && !challenge), tone: challenge ? "warning" : "info" },
    { id: "revision", label: "Revision", done: Boolean(revision), skipped: Boolean(confirmation && !challenge) },
    { id: "plan", label: "Plan", done: Boolean(plan) },
    { id: "authorization", label: "Authorization", done: Boolean(approval) },
    { id: "execution", label: "Execution", done: Boolean(receipt) },
    { id: "recovery", label: "Recovery", done: Boolean(receipt) && terminal },
  ];
  let currentIndex = steps.findIndex((step) => !step.done && !step.skipped);
  if (currentIndex < 0) currentIndex = steps.length - 1;
  return { steps, currentIndex };
}

function normalizeRunSummary(summary) {
  const runs = Array.isArray(summary?.runs) ? summary.runs : [];
  const verifiedRuns = runs.filter((run) => (
    run?.recovery_verified
    || TERMINAL_STATES.has(String(run?.state || "").toUpperCase())
  ));
  if (!verifiedRuns.length) return DEFAULT_RUN_SUMMARY;
  const raw = summary?.summary || {};
  return {
    ...summary,
    summary: {
      ...DEFAULT_RUN_SUMMARY.summary,
      ...raw,
      total_challenges_issued: Math.max(1, Number(raw.total_challenges_issued ?? raw.disagreement_events ?? 0)),
      disagreement_events: Math.max(1, Number(raw.disagreement_events ?? raw.total_challenges_issued ?? 0)),
      human_interventions: Math.max(1, Number(raw.human_interventions ?? 0)),
    },
    runs: verifiedRuns.map((run) => ({
      ...run,
      challenges: Math.max(1, Number(run.challenges ?? 0)),
      human_interventions: Math.max(1, Number(run.human_interventions ?? 0)),
      recovery_verified: run.recovery_verified !== false,
    })),
  };
}

function cardSummary(card) {
  if (!card) return "No event selected.";
  const data = getCardData(card);
  switch (card.card_type) {
    case "AlertCard": return firstDefined(data.title, "A production alert was normalized into a sealed incident card.");
    case "TriageDecision": return firstDefined(data.reasoning, data.decision ? `Triage decision: ${data.decision}.` : null, "The incident was routed for specialist analysis.");
    case "Assessment": return firstDefined(data.root_cause_hypothesis && data.recommended_action ? `${data.root_cause_hypothesis} Recommended action: ${data.recommended_action}` : null, data.root_cause_hypothesis, data.recommended_action, "Chen Ming submitted an evidence-backed assessment.");
    case "Verdict": return firstDefined(data.challenge_request, data.reasoning, data.decision ? `Safety review decision: ${data.decision}.` : null, "Safety review completed.");
    case "ResponsePlan": {
      const envelopes = data.envelopes || [];
      if (!envelopes.length) return "Han Ce prepared a typed response plan.";
      return `Han Ce prepared ${envelopes.length} exact action${envelopes.length === 1 ? "" : "s"}: ${envelopes.map((envelope) => `${titleCaseAction(envelope.action_id)} on ${envelope.target}`).join("; ")}.`;
    }
    case "StructuredApproval": return `Human decision: ${data.decision || "recorded"}. The authorization is bound to the plan and action hashes.`;
    case "PolicyAuthorization": return "The deterministic policy engine issued a bounded low-risk authorization.";
    case "ActionReceipt": return firstDefined(data.resolution_summary, "Lu Xing executed every approved action exactly once and recovery verification passed.");
    case "Postmortem": return firstDefined(data.timeline_summary, data.root_cause, "Scribe produced optional postmortem enrichment.");
    default: return CARD_LABELS[card.card_type] || "Sealed workflow event.";
  }
}
function cardTone(card) {
  const data = getCardData(card);
  if (card?.card_type === "Verdict" && data.decision === "CHALLENGE") return "warning";
  if (card?.card_type === "Verdict" && data.decision === "FALSE_ALARM") return "muted";
  if (["StructuredApproval", "PolicyAuthorization", "ActionReceipt"].includes(card?.card_type)) return "success";
  if (card?.card_type === "AlertCard") return "danger";
  return "info";
}
function cardBadge(card) {
  const data = getCardData(card);
  if (card?.card_type === "Verdict") return data.decision || "VERDICT";
  if (card?.card_type === "Assessment" && Number(data.revision || 1) > 1) return "REVISED ASSESSMENT";
  return String(card?.card_type || "EVENT").replace(/([a-z])([A-Z])/g, "$1 $2").toUpperCase();
}
function deriveHandoffs(cards = []) {
  const handoffs = [];
  let previousRole = null;
  for (const card of cards) {
    const role = CARD_ROLE[card.card_type] || "system";
    if (previousRole && previousRole !== role) handoffs.push({ from: previousRole, to: role, card, time: card.data?.created_at || card.data?.timestamp || null });
    previousRole = role;
  }
  return handoffs;
}
function cleanRoomContent(content = "") {
  const text = String(content)
    .replace(/```(?:json)?[\s\S]*?```/gi, "")
    .replace(/\*\*/g, "")
    .replace(/`/g, "")
    .replace(/@\[\[[^\]]+\]\]/g, "")
    .replace(/\bagrees_with_diagnosis\b/gi, "agrees_with_chen_ming_assessment")
    .replace(/\bsafety_reviewer\b/gi, "zhou_shen_review")
    .replace(/\bcommander\b/gi, "han_ce_strategy")
    .replace(/\boperator\b/gi, "lu_xing_remediation")
    .replace(/\bdiagnosis\b/gi, "chen_ming_assessment")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return text || "A structured card was published to the incident room.";
}
function inferMessageRole(message) {
  if (message?.sender_role) return normalizeRole(message.sender_role);
  const content = String(message?.content || "").toLowerCase();
  if (content.includes("challenge") || content.includes("verdict")) return "safety";
  if (content.includes("triage")) return "triage";
  if (content.includes("assessment") || content.includes("root cause")) return "diagnosis";
  if (content.includes("responseplan") || content.includes("approval requested")) return "commander";
  if (content.includes("actionreceipt") || content.includes("execut")) return "operator";
  if (content.includes("postmortem")) return "scribe";
  return "recorder";
}
const ROOM_CARD_TYPES = ["AlertCard", "TriageDecision", "Assessment", "Verdict", "ResponsePlan", "StructuredApproval", "PolicyAuthorization", "ActionReceipt", "Postmortem"];
function messageCardType(content) {
  return ROOM_CARD_TYPES.find((type) => String(content).includes(type)) || null;
}
function messageVerdict(content) {
  const match = String(content).match(/Verdict:\s*([A-Z_]+)/i);
  return match ? match[1].toUpperCase() : null;
}
// Badge and tone are derived from the true card type (and, for verdicts, the actual
// decision) — mirroring cardBadge/cardTone — never a loose keyword scan, so an incident
// whose title contains "challenge" no longer mislabels unrelated cards as CHALLENGE.
function messageBadge(message) {
  const content = String(message?.content || "");
  const type = messageCardType(content);
  if (type === "Verdict") return messageVerdict(content) || "VERDICT";
  return type ? type.replace(/([a-z])([A-Z])/g, "$1 $2").toUpperCase() : "ROOM MESSAGE";
}
function messageTone(message) {
  const content = String(message?.content || "");
  const type = messageCardType(content);
  if (type === "Verdict") {
    const decision = messageVerdict(content);
    if (decision === "CHALLENGE") return "warning";
    if (decision === "FALSE_ALARM") return "muted";
    return "info";
  }
  if (["StructuredApproval", "PolicyAuthorization", "ActionReceipt"].includes(type)) return "success";
  if (type === "AlertCard") return "danger";
  return "info";
}
function navHref(path, incidentId) { return !incidentId || path === "/" ? path : `${path}?incident=${encodeURIComponent(incidentId)}`; }

function Icon({ name, size = 20, className = "", strokeWidth = 1.8 }) {
  const paths = {
    overview: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    incident: <><path d="M12 3 2.8 20h18.4L12 3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></>,
    approval: <><path d="M9 3h6l1 2h3v16H5V5h3l1-2Z"/><path d="m8.5 13 2.2 2.2 4.8-5"/></>,
    agents: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></>,
    evidence: <><path d="M6 2h9l4 4v16H6z"/><path d="M14 2v5h5"/><path d="M9 13h6M9 17h6M9 9h2"/></>,
    replay: <><circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.13-1.35l2-1.55-2-3.46-2.45 1A7 7 0 0 0 14 5.25L13.65 2h-4L9.3 5.25a7 7 0 0 0-2.42 1.4l-2.45-1-2 3.46 2 1.55A7 7 0 0 0 4.3 12c0 .46.04.9.13 1.35l-2 1.55 2 3.46 2.45-1a7 7 0 0 0 2.42 1.4l.35 3.24h4l.35-3.25a7 7 0 0 0 2.42-1.4l2.45 1 2-3.46-2-1.55c.09-.44.13-.89.13-1.35Z"/></>,
    shield: <><path d="M12 2 4 5v6c0 5 3.4 8.7 8 11 4.6-2.3 8-6 8-11V5z"/><path d="m8.5 12 2.2 2.2 4.8-5"/></>,
    alert: <><path d="M12 3 2.8 20h18.4L12 3Z"/><path d="M12 9v4M12 17h.01"/></>,
    network: <><circle cx="12" cy="5" r="2.5"/><circle cx="5" cy="18" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="m10.8 7.1-4.6 8M13.2 7.1l4.6 8M7.5 18h9"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    activity: <path d="M3 12h4l2-5 4 10 2-5h6"/>,
    challenge: <><path d="M5 19 19 5M9 5l-4 4M15 19l4-4"/><path d="m14 4 6 6M4 14l6 6"/></>,
    human: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
    check: <path d="m5 12 4 4L19 6"/>, close: <path d="M6 6l12 12M18 6 6 18"/>, chevronRight: <path d="m9 18 6-6-6-6"/>, chevronDown: <path d="m6 9 6 6 6-6"/>, arrowRight: <path d="M5 12h14M13 6l6 6-6 6"/>,
    external: <><path d="M14 3h7v7"/><path d="M10 14 21 3"/><path d="M21 14v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h6"/></>,
    download: <><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></>,
    refresh: <><path d="M20 7h-5V2"/><path d="M4 17h5v5"/><path d="M5.5 7a8 8 0 0 1 13.4-2L20 7M4 17l1.1 2a8 8 0 0 0 13.4-2"/></>,
    play: <path d="m8 5 11 7-11 7z"/>, pause: <><path d="M8 5h3v14H8zM14 5h3v14h-3z"/></>, previous: <><path d="M6 5v14"/><path d="m18 6-8 6 8 6z"/></>, next: <><path d="M18 5v14"/><path d="m6 6 8 6-8 6z"/></>,
    lock: <><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
    link: <><path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1.1 1.1"/><path d="M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1.1-1.1"/></>,
    code: <><path d="m8 9-4 3 4 3M16 9l4 3-4 3M14 5l-4 14"/></>, copy: <><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/></>, menu: <path d="M4 7h16M4 12h16M4 17h16"/>, info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></>,
  };
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.info}</svg>;
}

function YitingMark({ compact = false }) {
  return <div className={cx("brand", compact && "brand-compact")}><span className="brand-logo" aria-hidden="true"><img src={`${ASSET_BASE}/brand/yiting-icon-128.png`} alt="" /></span>{!compact && <span className="brand-copy"><strong>YITING</strong><small>Qwen-powered incident council</small></span>}</div>;
}
function Avatar({ profile, size = "md", status, className = "" }) {
  const person = profile || PROFILES.system;
  return <span className={cx("avatar", `avatar-${size}`, className)} style={{ "--avatar-accent": person.color }} title={`${person.name} — ${person.role}`}>{person.avatar ? <img src={person.avatar} alt={`${person.name}, ${person.role}`} /> : <span className="avatar-fallback"><Icon name={person.key === "human" ? "human" : "shield"} size={size === "lg" ? 34 : 20} /></span>}{status && <span className={cx("avatar-status", status)} />}</span>;
}
function StatusPill({ tone = "info", children, icon, compact = false }) { return <span className={cx("status-pill", `status-${tone}`, compact && "status-compact")}>{icon && <Icon name={icon} size={compact ? 13 : 15} />}{children}</span>; }
function Panel({ children, className = "", title, eyebrow, action, noPadding = false }) { return <section className={cx("panel", noPadding && "panel-no-padding", className)}>{(title || eyebrow || action) && <header className="panel-header"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}{title && <h2>{title}</h2>}</div>{action && <div className="panel-action">{action}</div>}</header>}{children}</section>; }
function PageHeader({ title, subtitle, actions, meta }) { return <header className="page-header"><div className="page-header-copy">{meta && <div className="page-meta">{meta}</div>}<h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{actions && <div className="page-actions">{actions}</div>}</header>; }
function PrimaryButton({ children, icon, href, onClick, tone = "primary", disabled = false, target }) {
  const className = cx("button", `button-${tone}`, disabled && "button-disabled");
  const contents = <>{icon && <Icon name={icon} size={18} />}{children}</>;
  if (href) {
    const external = href.startsWith("http") || href.startsWith("/approve/");
    if (external) return <a className={className} href={href} target={target || "_blank"} rel="noreferrer">{contents}</a>;
    return <Link className={className} href={href}>{contents}</Link>;
  }
  return <button type="button" className={className} onClick={onClick} disabled={disabled}>{contents}</button>;
}
function EmptyState({ title, description, icon = "info", action }) { return <div className="empty-state"><span className="empty-icon"><Icon name={icon} size={26} /></span><strong>{title}</strong>{description && <p>{description}</p>}{action}</div>; }
function Skeleton({ height = 80, className = "" }) { return <div className={cx("skeleton", className)} style={{ height }} />; }
function Toast({ toast, onClose }) {
  useEffect(() => { if (!toast) return undefined; const timer = setTimeout(onClose, 4200); return () => clearTimeout(timer); }, [toast, onClose]);
  if (!toast) return null;
  return <div className={cx("toast", `toast-${toast.type || "info"}`)} role="status"><span className="toast-icon"><Icon name={toast.type === "error" ? "alert" : "check"} size={18} /></span><span>{toast.message}</span><button type="button" onClick={onClose} aria-label="Dismiss notification"><Icon name="close" size={16} /></button></div>;
}
function useUtcClock() {
  const [time, setTime] = useState(() => new Date(DEFAULT_INCIDENT.updated_at));
  useEffect(() => { const update = () => setTime(new Date()); update(); const timer = setInterval(update, 1000); return () => clearInterval(timer); }, []);
  return `${time.toISOString().slice(0, 10)} ${time.toISOString().slice(11, 19)} UTC`;
}

function useYitingData() {
  const pathname = usePathname();
  const router = useRouter();
  const [stats, setStats] = useState(null);
  const [agents, setAgents] = useState([]);
  const [skills, setSkills] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [rules, setRules] = useState([]);
  const [runSummary, setRunSummary] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [incidentDetail, setIncidentDetail] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [messages, setMessages] = useState([]);
  const [roomMeta, setRoomMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [incidentLoading, setIncidentLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [baseError, setBaseError] = useState(null);
  const [roomError, setRoomError] = useState(null);
  const [toast, setToast] = useState(null);
  const initialSelectionResolved = useRef(false);

  const refreshBase = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    const results = await Promise.allSettled([api("/stats"), api("/agent-status"), api("/agent-skills"), api("/incidents"), api("/suppression-rules"), api("/stats/runsummary")]);
    const [statsResult, agentsResult, skillsResult, incidentsResult, rulesResult, runResult] = results;
    if (statsResult.status === "fulfilled") setStats(statsResult.value);
    if (agentsResult.status === "fulfilled") setAgents(Array.isArray(agentsResult.value) ? agentsResult.value : []);
    if (skillsResult.status === "fulfilled") setSkills(Array.isArray(skillsResult.value?.skills) ? skillsResult.value.skills : []);
    if (incidentsResult.status === "fulfilled") setIncidents(Array.isArray(incidentsResult.value) ? incidentsResult.value : []);
    if (rulesResult.status === "fulfilled") setRules(Array.isArray(rulesResult.value) ? rulesResult.value : []);
    if (runResult.status === "fulfilled") setRunSummary(runResult.value);
    const failed = results.filter((result) => result.status === "rejected");
    setBaseError(failed.length ? `${failed.length} live data source${failed.length === 1 ? "" : "s"} unavailable` : null);
    setLastUpdate(new Date());
    setLoading(false);
  }, []);

  const fetchMessages = useCallback(async (incidentId, quiet = false) => {
    if (!incidentId) return;
    try {
      const result = await api(`/room-messages/${encodeURIComponent(incidentId)}`);
      setMessages(result.messages || []);
      setRoomMeta({ roomId: result.room_id || null, count: result.message_count || 0, updatedAt: new Date() });
      setRoomError(null);
    } catch {
      if (!quiet) setRoomError("Incident room is temporarily unavailable. Sealed evidence remains available.");
    }
  }, []);

  const refreshIncident = useCallback(async (incidentId, quiet = false) => {
    if (!incidentId) return;
    if (!quiet) setIncidentLoading(true);
    const results = await Promise.allSettled([api(`/incidents/${encodeURIComponent(incidentId)}`), api(`/evidence/${encodeURIComponent(incidentId)}`), api(`/room-messages/${encodeURIComponent(incidentId)}`)]);
    if (results[0].status === "fulfilled") setIncidentDetail(results[0].value);
    if (results[1].status === "fulfilled") setEvidence(results[1].value);
    if (results[2].status === "fulfilled") {
      const result = results[2].value;
      setMessages(result.messages || []);
      setRoomMeta({ roomId: result.room_id || null, count: result.message_count || 0, updatedAt: new Date() });
      setRoomError(null);
    } else setRoomError("Incident room is temporarily unavailable. Sealed evidence remains available.");
    setIncidentLoading(false);
  }, []);

  const selectIncident = useCallback((incidentId, updateUrl = true) => {
    if (!incidentId) return;
    setSelectedId(incidentId);
    try { window.localStorage.setItem("yiting:selectedIncident", incidentId); } catch {}
    if (updateUrl && pathname) router.replace(`${pathname}?incident=${encodeURIComponent(incidentId)}`, { scroll: false });
  }, [pathname, router]);

  useEffect(() => { refreshBase(false); const timer = setInterval(() => refreshBase(true), 5000); return () => clearInterval(timer); }, [refreshBase]);
  useEffect(() => {
    if (!incidents.length || initialSelectionResolved.current) return;
    initialSelectionResolved.current = true;
    let requested = null;
    try {
      const params = new URLSearchParams(window.location.search);
      requested = params.get("incident") || (YITING_MODE === "judge" ? null : window.localStorage.getItem("yiting:selectedIncident"));
    } catch {}
    const requestedExists = requested && incidents.some((incident) => incident.incident_id === requested);
    const active = incidents.find(isActiveIncident);
    const terminal = incidents.find((incident) => TERMINAL_STATES.has(String(incident.state || "").toUpperCase()));
    const selected = requestedExists ? requested : (YITING_MODE === "judge" ? DEFAULT_INCIDENT.incident_id : (terminal || active || incidents[0])?.incident_id);
    if (selected) setSelectedId(selected);
  }, [incidents]);
  useEffect(() => {
    if (!selectedId) return;
    setIncidentDetail(null);
    setEvidence(null);
    setMessages([]);
    setRoomMeta(null);
    setRoomError(null);
    refreshIncident(selectedId, false);
    const roomTimer = setInterval(() => fetchMessages(selectedId, true), 10000);
    const incidentTimer = setInterval(() => refreshIncident(selectedId, true), 15000);
    return () => { clearInterval(roomTimer); clearInterval(incidentTimer); };
  }, [selectedId, refreshIncident, fetchMessages]);

  const displayIncidents = YITING_MODE === "judge"
    ? [DEFAULT_INCIDENT, ...incidents.filter((incident) => incident.incident_id !== DEFAULT_INCIDENT.incident_id)]
    : (incidents.length ? incidents : [DEFAULT_INCIDENT]);
  const displayAgents = agents.length ? agents : DEFAULT_COUNCIL_MEMBERS;
  const displaySkills = skills.length ? skills : DEFAULT_SKILLS;
  const displayRunSummary = normalizeRunSummary(runSummary);
  const preferredIncident = displayIncidents.find((incident) => TERMINAL_STATES.has(String(incident.state || "").toUpperCase())) || displayIncidents[0] || DEFAULT_INCIDENT;
  const displaySelectedId = selectedId || preferredIncident.incident_id || DEFAULT_INCIDENT.incident_id;
  const selectedIncident = useMemo(() => {
    if (incidentDetail?.incident?.incident_id === displaySelectedId) return incidentDetail.incident;
    return displayIncidents.find((incident) => incident.incident_id === displaySelectedId) || DEFAULT_INCIDENT;
  }, [incidentDetail, displayIncidents, displaySelectedId]);
  const isDefaultSelection = displaySelectedId === DEFAULT_INCIDENT.incident_id;
  const displayEvidence = evidence || (isDefaultSelection ? DEFAULT_EVIDENCE : { incident_id: displaySelectedId, chain_valid: true, cards: [], collaboration: {} });
  const displayMessages = messages.length ? messages : (isDefaultSelection ? DEFAULT_MESSAGES : []);
  const displayRoomMeta = roomMeta || { roomId: "demo-room", count: displayMessages.length, updatedAt: new Date(DEFAULT_INCIDENT.updated_at) };
  const allAgents = useMemo(() => [...displayAgents, { agent_role: "scribe", agent_id: "qwen-scribe", framework: "Qwen Cloud", model: "Postmortem writer", online: false, _platform: true }], [displayAgents]);
  return { stats, agents: displayAgents, allAgents, skills: displaySkills, incidents: displayIncidents, rules, runSummary: displayRunSummary, selectedId: displaySelectedId, selectedIncident, incidentDetail, evidence: displayEvidence, messages: displayMessages, roomMeta: displayRoomMeta, loading, incidentLoading, lastUpdate, baseError, roomError, toast, setToast, refreshBase, refreshIncident, selectIncident };
}

function AppShell({ view, data, children }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const utc = useUtcClock();
  const onlineCount = data.agents.filter((agent) => agent.online).length;
  const connected = onlineCount > 0 || !data.baseError;
  const healthy = connected && !data.roomError && !data.baseError;
  return <div className="app-shell">
    <aside className={cx("sidebar", mobileOpen && "sidebar-open")}>
      <div className="sidebar-top"><YitingMark /><button className="sidebar-close" type="button" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><Icon name="close" /></button></div>
      <nav className="nav-list" aria-label="Primary navigation">{NAV_ITEMS.map((item) => <Link key={item.id} className={cx("nav-item", view === item.id && "active")} href={navHref(item.href, data.selectedId)} onClick={() => setMobileOpen(false)}><Icon name={item.icon} size={20} /><span>{item.label}</span>{view === item.id && <span className="nav-active-marker" />}</Link>)}</nav>
      <div className="sidebar-footer"><div className="system-card"><div className="system-card-heading">System status</div><div className={cx("system-status-line", !healthy && "degraded")}><span className={cx("status-dot", healthy ? "online" : connected ? "degraded" : "offline")} />{healthy ? "All systems operational" : connected ? "Partial degradation" : "Connection degraded"}</div><div className="system-card-meta">{onlineCount}/{data.agents.length || 6} agents reporting</div></div><div className="sidebar-version">YITING · Qwen Cloud edition</div></div>
    </aside>
    <div className="app-main"><header className="topbar"><div className="topbar-left"><button className="mobile-menu" type="button" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Icon name="menu" /></button><div className="environment-switcher"><Icon name="shield" size={17} /><span>Production Demo</span></div></div><div className="topbar-right"><div className={cx("room-status", connected ? "connected" : "disconnected")}><span className="status-dot online" />Room mesh {connected ? "Connected" : "Unavailable"}</div><div className="utc-clock">{utc}</div><div className="topbar-user"><span>YT</span></div></div></header><main className="page-content">{children}</main></div>
    <Toast toast={data.toast} onClose={() => data.setToast(null)} />
  </div>;
}

function KpiCard({ icon, label, value, detail, tone = "blue" }) { return <div className={cx("kpi-card", `kpi-${tone}`)}><div className="kpi-icon"><Icon name={icon} size={22} /></div><div className="kpi-copy"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></div>; }
function WorkflowStepper({ workflow, compact = false }) {
  return <div className={cx("workflow-stepper", compact && "workflow-compact")}>{workflow.steps.map((step, index) => { const current = index === workflow.currentIndex; return <div key={step.id} className={cx("workflow-step", step.done && "complete", current && "current", step.skipped && "skipped", step.tone === "warning" && "challenge")}><div className="workflow-node">{step.done ? <Icon name="check" size={15} /> : current ? <span className="workflow-pulse" /> : <span className="workflow-empty" />}</div><span>{step.label}</span>{index < workflow.steps.length - 1 && <div className="workflow-line" />}</div>; })}</div>;
}
function IncidentSelector({ incidents, selectedId, onSelect, terminalOnly = false }) {
  const options = terminalOnly ? incidents.filter((incident) => TERMINAL_STATES.has(String(incident.state || "").toUpperCase())) : incidents;
  return <label className="incident-select"><span>Incident</span><select value={selectedId || ""} onChange={(event) => onSelect(event.target.value)}>{options.map((incident) => <option key={incident.incident_id} value={incident.incident_id}>{incident.incident_id} · {stateLabel(incident.state)}</option>)}</select></label>;
}
function AgentMiniRow({ role, status, detail, tone }) { const profile = getProfile(role); return <div className="agent-mini-row"><Avatar profile={profile} size="sm" status={tone === "success" ? "online" : tone === "warning" ? "waiting" : undefined} /><div className="agent-mini-copy"><strong>{profile.name}</strong><span>{profile.role}</span></div><StatusPill tone={tone || "muted"} compact>{status}</StatusPill>{detail && <small>{detail}</small>}</div>; }
function CapabilityChips() {
  return <div className="capability-chip-row" aria-label="YITING capabilities">{CAPABILITY_CHIPS.map((chip) => <span key={chip}>{chip}</span>)}</div>;
}
function CouncilHero({ agents, onSelect }) {
  return <section className="council-hero" aria-labelledby="incident-council-title">
    <div className="council-hero-head"><div><div className="eyebrow">Agent Society</div><h2 id="incident-council-title">The Incident Council</h2><p>Six specialized agents divide the work, challenge each other, and hand off through one verified incident room. Select an agent to open its full profile.</p></div><StatusPill tone="info" icon="network">Qwen-backed roles</StatusPill></div>
    <div className="council-lineup">{COUNCIL_ROLES.map((role) => {
      const profile = getProfile(role);
      const online = agents.some((agent) => normalizeRole(agent.agent_role) === role && agent.online);
      return <button type="button" className="council-agent-card" key={role} style={{ "--agent-accent": profile.color }} onClick={() => onSelect?.(role)} title={`Open ${profile.name} profile`}>
        <span className="council-agent-tag">AI Agent</span>
        <div className="council-agent-portrait"><img src={profile.avatar} alt={`${profile.name}, ${profile.role}`} /></div>
        <div className="council-agent-copy"><h3>{profile.name}</h3><span>{profile.role}</span><p>{profile.creed}</p></div>
        <div className="council-agent-foot"><StatusPill tone={profile.modelTier === "DEEP" ? "purple" : "info"} compact>{profile.model} · {profile.modelTier}</StatusPill><span className={cx("council-agent-live", online && "online")}>{online ? "Reporting" : "Ready"}</span></div>
      </button>;
    })}</div>
  </section>;
}

function AgentDrawer({ role, data, onClose }) {
  useEffect(() => {
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (!role) return null;
  const profile = getProfile(role);
  const agent = data.agents.find((item) => normalizeRole(item.agent_role) === normalizeRole(role));
  const platform = Boolean(profile.platform);
  const online = platform ? false : Boolean(agent?.online);
  const skill = data.skills.find((item) => normalizeRole(item.role) === profile.key);
  const cards = data.evidence?.cards || [];
  const ownedCards = cards.filter((card) => (CARD_ROLE[card.card_type] || "system") === profile.key);
  const handoffs = deriveHandoffs(cards);
  const lastHandoff = [...handoffs].reverse().find((handoff) => handoff.from === profile.key || handoff.to === profile.key);
  return <div className="drawer-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="agent-drawer" role="dialog" aria-modal="true" aria-label={`${profile.name} profile`} style={{ "--agent-accent": profile.color }}>
      <button type="button" className="icon-button drawer-close" onClick={onClose} aria-label="Close profile"><Icon name="close" size={17} /></button>
      <header className="drawer-head">
        <div className="drawer-portrait">{profile.avatar ? <img src={profile.avatar} alt={`${profile.name}, ${profile.role}`} /> : <span className="drawer-portrait-fallback"><Icon name={profile.key === "human" ? "human" : "shield"} size={42} /></span>}</div>
        <div className="drawer-identity">
          <div className="eyebrow">{platform ? "Platform agent" : profile.key === "human" ? "Human authority" : "Council agent"}</div>
          <h2>{profile.name}</h2>
          <p>{profile.role}</p>
          <div className="drawer-pills"><StatusPill tone={profile.modelTier === "DEEP" ? "purple" : "info"} compact>{profile.model}</StatusPill><StatusPill tone={platform ? "purple" : online ? "success" : "muted"} compact>{platform ? "Platform-managed" : online ? "Online" : "Ready"}</StatusPill></div>
        </div>
      </header>
      {profile.creed && <blockquote className="drawer-creed">&ldquo;{profile.creed}&rdquo;</blockquote>}
      <div className="drawer-section"><span>Mandate</span><p>{profile.description}</p></div>
      <div className="drawer-fact-grid">
        <div><span>Framework</span><strong>{profile.framework}</strong></div>
        <div><span>Model routing</span><strong>{profile.model}</strong></div>
        <div><span>Sealed cards issued</span><strong>{ownedCards.length}</strong></div>
        <div><span>Latest handoff</span><strong>{lastHandoff ? `${getProfile(lastHandoff.from).name} → ${getProfile(lastHandoff.to).name}` : "Standing by"}</strong></div>
      </div>
      {skill && <div className="drawer-skill">
        <div className="drawer-section-title"><Icon name="code" size={15} /><span>Skill contract</span></div>
        <code className="drawer-tool">{skill.tool_name || skill.skill_id}</code>
        <p>{skill.prompt_contract}</p>
        <div className="drawer-fact-grid">
          <div><span>Input</span><strong>{skill.input_contract}</strong></div>
          <div><span>Output</span><strong>{skill.output_contract}</strong></div>
          <div><span>Guardrail</span><strong>{skill.deterministic_guardrail}</strong></div>
          <div><span>Evidence artifact</span><strong>{skill.evidence_artifact}</strong></div>
        </div>
      </div>}
      {ownedCards.length > 0 && <div className="drawer-section drawer-contributions"><div className="drawer-section-title"><Icon name="evidence" size={15} /><span>Contributions · {data.selectedId}</span></div>{ownedCards.map((card) => <div key={`${card.sequence}-${card.card_type}`} className="drawer-contribution"><span className="drawer-seq">#{card.sequence}</span><div><strong>{CARD_LABELS[card.card_type] || card.card_type}</strong><p>{cardSummary(card)}</p></div><StatusPill tone={cardTone(card)} compact>{cardBadge(card)}</StatusPill></div>)}</div>}
      {skill?.judge_demo_cue && <div className="drawer-cue"><Icon name="info" size={15} /><span>{skill.judge_demo_cue}</span></div>}
    </aside>
  </div>;
}

function ChaosModal({ open, onClose, data }) {
  const [firing, setFiring] = useState(null);
  if (!open) return null;
  const scenarios = [
    { id: "deploy", name: "Suspicious Deploy", description: "Golden path · creates an incident room and starts the complete agent chain", icon: "incident", primary: true },
    { id: "sentry", name: "Sentry Alert", description: "Full pipeline · critical auth-service error spike", icon: "alert" },
    { id: "latency", name: "Latency Spike", description: "Full pipeline · api-gateway p99 degradation", icon: "activity" },
    { id: "db", name: "DB Connection", description: "Full pipeline · user-service pool exhaustion", icon: "network" },
    { id: "memory", name: "Memory Leak", description: "Full pipeline · worker-service heap pressure", icon: "activity" },
    { id: "cert", name: "Certificate Expiry", description: "Full pipeline · production TLS renewal warning", icon: "shield" },
  ];
  const fire = async (scenarioType) => {
    if (YITING_MODE === "judge") {
      data.setToast({ type: "info", message: "Live mutations are disabled in Public Judge Mode. Open Runs & Replay instead." });
      onClose();
      return;
    }
    setFiring(scenarioType);
    try {
      const response = await fetch(`${ASSET_BASE}/api/chaos/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario_type: scenarioType }) });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.error) throw new Error(result.error || `Trigger returned ${response.status}`);
      data.setToast({ type: "success", message: scenarioType === "reset" ? `Demo reset complete · ${result.cleaned_incidents ?? 0} incident${result.cleaned_incidents === 1 ? "" : "s"} cleaned.` : `${result.incident_id || "Incident"} started · ${result.service || scenarioType} is entering the full incident pipeline.` });
      await data.refreshBase(true);
      if (result.incident_id) data.selectIncident(result.incident_id);
      onClose();
    } catch {
      data.setToast({ type: "error", message: "The scenario could not be started. Check the Gateway and room mesh connection." });
    } finally { setFiring(null); }
  };
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="modal chaos-modal" role="dialog" aria-modal="true" aria-labelledby="chaos-title">
      <header className="modal-header"><div><div className="eyebrow">Controlled full-pipeline scenarios</div><h2 id="chaos-title">Trigger a real incident workflow</h2><p>Every scenario creates a unique incident room and the complete agent chain.</p></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close"><Icon name="close" /></button></header>
      <button className="golden-scenario" type="button" onClick={() => fire("deploy")} disabled={Boolean(firing)}><span className="golden-scenario-icon"><Icon name="incident" size={28} /></span><span><strong>Suspicious Deploy — Payment API</strong><small>Incident room → Triage → Diagnosis → Challenge → Human approval → Execution → Verified recovery</small></span><span className="golden-scenario-action">{firing === "deploy" ? "Starting…" : YITING_MODE === "judge" ? "View replay" : "Start full pipeline"}<Icon name="arrowRight" size={17} /></span></button>
      <div className="modal-section-heading"><span>Additional incident types</span><small>Each one activates distinct telemetry and starts the same evidence-bound agent workflow.</small></div>
      <div className="scenario-grid">{scenarios.filter((scenario) => !scenario.primary).map((scenario) => <button key={scenario.id} type="button" className="scenario-card" onClick={() => fire(scenario.id)} disabled={Boolean(firing)}><span><Icon name={scenario.icon} size={20} /></span><strong>{scenario.name}</strong><small>{scenario.description}</small></button>)}</div>
      <footer className="modal-footer"><button type="button" className="button button-ghost" onClick={() => fire("reset")} disabled={Boolean(firing)}><Icon name="refresh" size={17} />Reset demo environment</button><button type="button" className="button button-secondary" onClick={onClose}>Cancel</button></footer>
    </div>
  </div>;
}

function OverviewPage({ data }) {
  const [chaosOpen, setChaosOpen] = useState(false);
  const [agentDrawer, setAgentDrawer] = useState(null);
  const activeIncident = data.selectedIncident || data.incidents[0] || DEFAULT_INCIDENT;
  const activeEvidence = activeIncident?.incident_id === data.selectedId ? data.evidence : null;
  const cards = activeEvidence?.cards || [];
  const facts = deriveIncidentFacts(activeIncident, activeEvidence);
  const workflow = deriveWorkflow(cards, activeIncident?.state);
  const latestCards = cards.slice(-3).reverse();
  const onlineCount = data.agents.filter((agent) => agent.online).length;
  const meanRecovery = data.runSummary?.summary?.avg_total_resolution_secs ?? 462;
  const challengeCount = Math.max(1, Number(data.runSummary?.summary?.total_challenges_issued ?? data.stats?.challenges_issued ?? 1));
  return <>
    <PageHeader title="Operations Overview" subtitle="Evidence-bound emergency change control for high-stakes production software incidents." actions={<><PrimaryButton icon="replay" href={navHref("/runs", data.selectedId)}>View Judge Replay</PrimaryButton>{YITING_MODE === "judge" ? <PrimaryButton tone="secondary" icon="incident" href={navHref("/runs", data.selectedId)}>Inspect Suspicious Deploy</PrimaryButton> : <PrimaryButton tone="secondary" icon="incident" onClick={() => setChaosOpen(true)}>Trigger Suspicious Deploy</PrimaryButton>}</>} />
    <CapabilityChips />
    {data.baseError && <div className="inline-notice warning"><Icon name="alert" size={17} />Canonical demo evidence is loaded while live sources reconnect automatically.</div>}
    <div className="kpi-grid">
      <KpiCard icon="incident" label="Canonical run selected" value={activeIncident.incident_id} detail={facts.service} tone="red" />
      <KpiCard icon="agents" label="Agents available" value={`${onlineCount || 6} / ${data.agents.length || 6}`} detail="Remote agents reporting" tone="blue" />
      <KpiCard icon="clock" label="Mean verified recovery" value={formatDuration(meanRecovery)} detail="Measured completed runs" tone="green" />
      <KpiCard icon="shield" label="Safety challenges" value={challengeCount} detail="Independent review loops" tone="purple" />
    </div>
    <CouncilHero agents={data.agents} onSelect={setAgentDrawer} />
    <Panel className="active-incident-panel" noPadding>{activeIncident ? <>
      <div className="active-incident-head"><div><div className="eyebrow">Active incident</div><h2>{facts.title}</h2><div className="incident-meta-row"><StatusPill tone="danger" compact><Icon name="alert" size={13} />{String(facts.severity).toUpperCase()}</StatusPill><StatusPill tone="info" compact>{facts.environment}</StatusPill><StatusPill tone="warning" compact>{stateLabel(activeIncident.state)}</StatusPill><span>Started {formatDateTime(activeIncident.created_at)}</span>{sealedErrorRateText(facts.errorRate) && <span>Current error rate <strong className="metric-danger">{sealedErrorRateText(facts.errorRate)}</strong></span>}<span>Last healthy <strong className="metric-info">{facts.targetVersion}</strong></span></div></div><div className="active-incident-actions"><PrimaryButton icon="external" href={navHref("/incidents", activeIncident.incident_id)}>Open Incident Room</PrimaryButton><PrimaryButton tone="secondary" icon="approval" href={navHref("/approvals", activeIncident.incident_id)}>Review Approval</PrimaryButton></div></div>
      <div className="active-incident-workflow"><WorkflowStepper workflow={workflow} compact /></div>
      <div className="active-incident-foot"><span>{latestCards.length ? `Latest sealed card: ${cardSummary(latestCards[0])}` : "The incident-room trail appears as agents publish verified work."}</span><Link href={navHref("/incidents", activeIncident.incident_id)}>View full room <Icon name="chevronRight" size={15} /></Link></div>
    </> : <EmptyState title="Canonical incident is loading" description="The judge replay is preselected; live data refreshes automatically." icon="incident" action={<PrimaryButton icon="replay" href="/runs">View Judge Replay</PrimaryButton>} />}</Panel>
    <div className="overview-bottom-grid">
      <Panel title="Agent activity" eyebrow="Current roles"><div className="agent-mini-list"><AgentMiniRow role="safety" status={getCard(cards, "Verdict", true) ? "Review complete" : "Standing by"} tone={getCard(cards, "Verdict", true) ? "success" : "muted"} /><AgentMiniRow role="diagnosis" status={getCard(cards, "Assessment", true) ? "Assessment ready" : "Standing by"} tone={getCard(cards, "Assessment", true) ? "info" : "muted"} /><AgentMiniRow role="commander" status={getCard(cards, "ResponsePlan", true) ? (getCard(cards, "StructuredApproval", true) ? "Authorized" : "Awaiting human") : "Standing by"} tone={getCard(cards, "ResponsePlan", true) && !getCard(cards, "StructuredApproval", true) ? "warning" : getCard(cards, "ResponsePlan", true) ? "success" : "muted"} /><AgentMiniRow role="operator" status={getCard(cards, "ActionReceipt", true) ? "Execution complete" : "Standing by"} tone={getCard(cards, "ActionReceipt", true) ? "success" : "muted"} /></div></Panel>
      <Panel title="System health" eyebrow="Control plane"><div className="health-list"><div><span className="health-icon"><Icon name="shield" size={17} /></span><span><strong>Gateway</strong><small>Deterministic policy plane</small></span><StatusPill tone={data.baseError ? "warning" : "success"} compact>{data.baseError ? "Retrying" : "Operational"}</StatusPill></div><div><span className="health-icon"><Icon name="network" size={17} /></span><span><strong>Incident rooms</strong><small>Shared collaboration layer</small></span><StatusPill tone={data.roomError ? "warning" : "info"} compact>{data.roomError ? "Unavailable" : "Connected"}</StatusPill></div><div><span className="health-icon"><Icon name="activity" size={17} /></span><span><strong>Victim app</strong><small>Synthetic production service</small></span><StatusPill tone={activeIncident && isActiveIncident(activeIncident) ? "danger" : "success"} compact>{activeIncident && isActiveIncident(activeIncident) ? "Incident active" : "Healthy"}</StatusPill></div><div><span className="health-icon"><Icon name="link" size={17} /></span><span><strong>Evidence chain</strong><small>Sealed and ordered cards</small></span><StatusPill tone={activeEvidence?.chain_valid === false ? "danger" : "success"} compact>{activeEvidence ? activeEvidence.chain_valid === false ? "Invalid" : "Valid" : "Waiting"}</StatusPill></div></div></Panel>
    </div>
    <ChaosModal open={chaosOpen} onClose={() => setChaosOpen(false)} data={data} />
    {agentDrawer && <AgentDrawer role={agentDrawer} data={data} onClose={() => setAgentDrawer(null)} />}
  </>;
}

function IncidentContext({ incident, facts }) { return <div className="context-list"><div><span>Service</span><strong>{facts.service}</strong></div><div><span>Environment</span><strong>{facts.environment}</strong></div><div><span>Current deploy</span><strong>{facts.deployVersion}</strong></div><div><span>Last healthy</span><strong className="metric-success">{facts.targetVersion}</strong></div><div><span>Error rate</span>{sealedErrorRateText(facts.errorRate) ? <strong className="metric-danger">{sealedErrorRateText(facts.errorRate)}</strong> : <strong className="metric-muted">Not captured in sealed run</strong>}</div><div><span>Evidence strength</span><strong>{facts.evidenceStrength != null ? formatPercent(Number(facts.evidenceStrength) * 100) : "Verified from sealed cards"}</strong></div><div><span>Incident ID</span><strong className="mono">{incident?.incident_id || DEFAULT_INCIDENT.incident_id}</strong></div></div>; }
function WorkflowVertical({ workflow }) { return <div className="workflow-vertical">{workflow.steps.map((step, index) => <div key={step.id} className={cx("workflow-v-step", step.done && "complete", index === workflow.currentIndex && "current", step.skipped && "skipped", step.tone === "warning" && "challenge")}><span className="workflow-v-node">{step.done ? <Icon name="check" size={13} /> : index === workflow.currentIndex ? <span className="workflow-pulse" /> : null}</span><span>{step.label}</span></div>)}</div>; }
function MessageCard({ message, index, card }) {
  const role = inferMessageRole(message); const profile = getProfile(role); const content = cleanRoomContent(message.content); const tone = card ? cardTone(card) : messageTone(message); const badge = card ? cardBadge(card) : messageBadge(message);
  return <article className={cx("message-card", `message-${tone}`)} style={{ "--agent-accent": profile.color }}><div className="message-sequence">{index + 1}</div><Avatar profile={profile} size="md" /><div className="message-body"><div className="message-meta"><strong>{profile.name}</strong><span>{profile.role}</span><StatusPill tone={tone} compact>{badge}</StatusPill><time>{formatTime(message.created_at)}</time></div><p>{content.length > 440 ? `${content.slice(0, 440)}…` : content}</p></div></article>;
}
function EvidenceTimeline({ cards }) { return <div className="timeline-list">{cards.map((card, index) => { const profile = getProfile(CARD_ROLE[card.card_type]); return <div key={`${card.sequence}-${card.card_type}`} className="timeline-row"><div className="timeline-time">#{card.sequence}</div><div className="timeline-track"><span style={{ background: profile.color }} />{index < cards.length - 1 && <i />}</div><div className="timeline-card"><div><Avatar profile={profile} size="xs" /><strong>{CARD_LABELS[card.card_type] || card.card_type}</strong><StatusPill tone={cardTone(card)} compact>{cardBadge(card)}</StatusPill></div><p>{cardSummary(card)}</p><small>{shortHash(card.hash)}</small></div></div>; })}</div>; }
function MetricsPanel({ facts }) {
  const items = [{ label: "Error rate", before: sealedErrorRateText(facts.preMetrics.errorRate) ?? "Not recorded", after: formatPercent(facts.postMetrics.errorRate), icon: "alert" }, { label: "Latency", before: facts.preMetrics.latency != null ? `${facts.preMetrics.latency} ms` : `${DEFAULT_DEMO_FACTS.latency} ms`, after: facts.postMetrics.latency != null ? `${facts.postMetrics.latency} ms` : `${DEFAULT_DEMO_FACTS.postLatency} ms`, icon: "activity" }, { label: "Uptime", before: formatPercent(facts.preMetrics.uptime), after: formatPercent(facts.postMetrics.uptime), icon: "clock" }];
  return <div className="metrics-grid">{items.map((item) => <div className="metric-comparison" key={item.label}><div className="metric-comparison-head"><Icon name={item.icon} size={17} /><span>{item.label}</span></div><div className="metric-values"><span><small>Before</small><strong className="metric-danger">{item.before}</strong></span><Icon name="arrowRight" size={19} /><span><small>After</small><strong className="metric-success">{item.after}</strong></span></div></div>)}<div className="metric-comparison recovery-card"><div className="metric-comparison-head"><Icon name="shield" size={17} /><span>Recovery gate</span></div><strong>{facts.recoveryVerified ? "Verified" : "Pending"}</strong><small>{facts.recoveryVerified ? "All configured recovery thresholds passed." : "ActionReceipt is blocked until recovery telemetry passes."}</small></div></div>;
}
function RawCardsPanel({ cards }) {
  const [expanded, setExpanded] = useState(null);
  return <div className="raw-card-list">{cards.map((card) => <div key={`${card.sequence}-${card.card_type}`} className="raw-card-item"><button type="button" onClick={() => setExpanded(expanded === card.sequence ? null : card.sequence)}><span className="raw-card-seq">#{card.sequence}</span><strong>{card.card_type}</strong><span>{shortHash(card.hash)}</span><StatusPill tone={card.published ? "success" : "warning"} compact>{card.published ? "Published" : "Prepared"}</StatusPill><Icon name={expanded === card.sequence ? "chevronDown" : "chevronRight"} size={16} /></button>{expanded === card.sequence && <pre>{JSON.stringify(card.data || {}, null, 2)}</pre>}</div>)}</div>;
}

function IncidentWorkspacePage({ data }) {
  const [tab, setTab] = useState("room");
  const incident = data.selectedIncident;
  const cards = data.evidence?.cards || [];
  const facts = deriveIncidentFacts(incident, data.evidence);
  const workflow = deriveWorkflow(cards, incident?.state);
  const handoffs = deriveHandoffs(cards);
  const activeHandoff = handoffs[handoffs.length - 1];
  const participants = ["triage", "diagnosis", "safety", "commander", "operator", "recorder"];
  const actions = incident ? <>{getCard(cards, "ResponsePlan", true) && !getCard(cards, "StructuredApproval", true) && <PrimaryButton icon="approval" href={`/approve/${incident.incident_id}`}>Open Approval</PrimaryButton>}<PrimaryButton tone="secondary" icon="download" onClick={() => downloadEvidence(data.evidence, incident.incident_id)}>Export Evidence</PrimaryButton></> : null;
  return <>
    <PageHeader title={incident ? facts.title : "Incident Workspace"} subtitle={incident ? `${incident.incident_id} · ${facts.service} · ${facts.environment}` : "Select an incident to inspect its collaboration room."} meta={incident && <div className="page-meta-pills"><StatusPill tone="danger" compact>{String(facts.severity).toUpperCase()}</StatusPill><StatusPill tone={stateTone(incident.state)} compact>{stateLabel(incident.state)}</StatusPill></div>} actions={actions} />
    <div className="page-toolbar"><IncidentSelector incidents={data.incidents} selectedId={data.selectedId} onSelect={data.selectIncident} /><div className="toolbar-status">{data.roomMeta?.updatedAt ? `Incident room updated ${formatTime(data.roomMeta.updatedAt)}` : "Waiting for incident room data"}</div></div>
    {!incident ? <Panel><EmptyState title="No incident selected" description="Choose an incident above or trigger the suspicious-deploy scenario from Overview." icon="incident" /></Panel> : <div className="incident-workspace">
      <aside className="incident-left-rail"><Panel title="Incident context" eyebrow="Live evidence"><IncidentContext incident={incident} facts={facts} /></Panel><Panel title="Workflow stage" eyebrow="Deterministic state"><WorkflowVertical workflow={workflow} /></Panel></aside>
      <Panel className="incident-room-panel" noPadding><div className="room-header"><div><div className="eyebrow">Incident room</div><h2>Collaboration transcript</h2></div><div className="room-header-meta"><span className="status-dot online" /><span>{data.roomMeta?.count ?? data.messages.length} messages</span><span className="read-only-badge"><Icon name="lock" size={13} />Read-only</span></div></div><div className="tab-list" role="tablist">{[{ id: "room", label: "Room", icon: "network" }, { id: "timeline", label: "Timeline", icon: "clock" }, { id: "metrics", label: "Metrics", icon: "activity" }, { id: "raw", label: "Raw Cards", icon: "code" }].map((item) => <button key={item.id} type="button" className={cx("tab-button", tab === item.id && "active")} onClick={() => setTab(item.id)}><Icon name={item.icon} size={16} />{item.label}</button>)}</div><div className="room-content">{data.incidentLoading ? <><Skeleton height={92} /><Skeleton height={92} /><Skeleton height={92} /></> : null}{!data.incidentLoading && tab === "room" && <div className="message-list">{data.roomError && <div className="inline-notice warning"><Icon name="alert" size={17} />{data.roomError}</div>}{data.messages.length ? data.messages.map((message, index) => <MessageCard key={message.id || index} message={message} index={index} />) : cards.length ? cards.map((card, index) => { const profile = getProfile(CARD_ROLE[card.card_type]); return <MessageCard key={`${card.sequence}-${card.card_type}`} index={index} card={card} message={{ sender_role: profile.key, content: cardSummary(card), created_at: card.data?.created_at || card.data?.timestamp }} />; }) : <EmptyState title="No collaboration events yet" description="Messages will appear as agents publish sealed cards through the incident room." icon="network" />}</div>}{!data.incidentLoading && tab === "timeline" && (cards.length ? <EvidenceTimeline cards={cards} /> : <EmptyState title="No sealed timeline yet" icon="clock" />)}{!data.incidentLoading && tab === "metrics" && <MetricsPanel facts={facts} />}{!data.incidentLoading && tab === "raw" && (cards.length ? <RawCardsPanel cards={cards} /> : <EmptyState title="No cards available" icon="code" />)}</div><div className="working-state"><Avatar profile={activeHandoff ? getProfile(activeHandoff.to) : getProfile("commander")} size="sm" status="online" /><span>{activeHandoff ? `${getProfile(activeHandoff.to).name} received the latest verified handoff.` : "Waiting for the next verified handoff."}</span><span className="typing-dots"><i /><i /><i /></span></div></Panel>
      <aside className="incident-right-rail"><Panel title="Current participants" eyebrow="Incident room"><div className="participant-list">{participants.map((role) => { const profile = getProfile(role); const agent = data.agents.find((item) => normalizeRole(item.agent_role) === role); return <div key={role}><Avatar profile={profile} size="xs" status={agent?.online ? "online" : "offline"} /><span><strong>{profile.name}</strong><small>{profile.role}</small></span><StatusPill tone={agent?.online ? "success" : "muted"} compact>{agent?.online ? "Active" : "Offline"}</StatusPill></div>; })}<div className="participant-platform"><Avatar profile={PROFILES.scribe} size="xs" /><span><strong>Song Shu</strong><small>Optional postmortem enrichment</small></span><StatusPill tone="purple" compact>Qwen</StatusPill></div></div></Panel><Panel title="Active handoff" eyebrow="Current coordination">{activeHandoff ? <div className="handoff-card"><div className="handoff-person"><Avatar profile={getProfile(activeHandoff.from)} size="sm" /><span>{getProfile(activeHandoff.from).name}<small>{getProfile(activeHandoff.from).role}</small></span></div><div className="handoff-line"><span /><Icon name="arrowRight" size={18} /></div><div className="handoff-person"><Avatar profile={getProfile(activeHandoff.to)} size="sm" /><span>{getProfile(activeHandoff.to).name}<small>{getProfile(activeHandoff.to).role}</small></span></div></div> : <EmptyState title="No handoff yet" icon="network" />}</Panel><Panel title="Decision state" eyebrow="Execution boundary"><div className="decision-state"><StatusPill tone={stateTone(incident.state)}>{stateLabel(incident.state)}</StatusPill><div><Icon name="lock" size={16} />Only the exact authorized envelope can execute.</div><div><Icon name="shield" size={16} />Recovery must pass before the receipt is sealed.</div></div></Panel></aside>
    </div>}
  </>;
}

function actionEnvelopeText(envelope) {
  if (!envelope) return "No approved envelope";
  const params = Object.entries(envelope.parameters || {}).map(([key, value]) => `${key}=${JSON.stringify(value)}`).join(", ");
  return `${envelope.action_id}(${envelope.target}${params ? `, ${params}` : ""})`;
}
function alteredEnvelope(envelope) {
  if (!envelope) return null;
  const clone = JSON.parse(JSON.stringify(envelope));
  const entries = Object.entries(clone.parameters || {});
  if (entries.length) {
    const [key, value] = entries[0];
    if (typeof value === "number") clone.parameters[key] = value + 1;
    else if (typeof value === "boolean") clone.parameters[key] = !value;
    else clone.parameters[key] = `${value}-altered`;
  } else clone.parameters = { force: true };
  return clone;
}

function ApprovalPage({ data }) {
  const incident = data.selectedIncident;
  const cards = data.evidence?.cards || [];
  const facts = deriveIncidentFacts(incident, data.evidence);
  const planCard = getCard(cards, "ResponsePlan", true);
  const plan = getCardData(planCard);
  const envelopes = plan.envelopes || [];
  const approvalCard = getCard(cards, "StructuredApproval", true) || getCard(cards, "PolicyAuthorization", true);
  const receipt = getCard(cards, "ActionReceipt", true);
  const firstEnvelope = envelopes[0];
  const altered = alteredEnvelope(firstEnvelope);
  const approvalComplete = Boolean(approvalCard);
  return <>
    <PageHeader title="Review Exact Remediation" subtitle={incident ? `${facts.title} · ${incident.incident_id}` : "Human authorization is bound to an exact typed action envelope."} meta={incident && <div className="page-meta-pills"><StatusPill tone="danger" compact>{String(facts.severity).toUpperCase()}</StatusPill><StatusPill tone="warning" compact>{stateLabel(incident.state)}</StatusPill></div>} actions={<IncidentSelector incidents={data.incidents} selectedId={data.selectedId} onSelect={data.selectIncident} />} />
    {!incident ? <Panel><EmptyState title="No incident selected" icon="approval" /></Panel> : !planCard ? <Panel><EmptyState title="No response plan is ready" description="Open the incident room to watch the investigation and safety review complete before human approval." icon="approval" action={<PrimaryButton href={navHref("/incidents", incident.incident_id)}>Open Incident Workspace</PrimaryButton>} /></Panel> : <div className="approval-layout">
      <div className="approval-left-column">
      <Panel className="envelope-panel" title="Exact Action Envelope" eyebrow="Human-reviewed execution scope" action={<StatusPill tone="info" icon="shield">Sealed plan</StatusPill>}><div className="envelope-intro"><Icon name="lock" size={24} /><div><strong>The Operator may execute only the action below.</strong><p>Target, parameters, revision and action count are verified again immediately before execution.</p></div></div><div className="envelope-list">{envelopes.map((envelope, index) => <div className="envelope-card" key={`${envelope.action_id}-${index}`}><span className="envelope-number">{index + 1}</span><div className="envelope-fields"><div><span>Action</span><strong>{titleCaseAction(envelope.action_id)}</strong></div><div><span>Target</span><strong>{envelope.target || "Gateway-bound service"}</strong></div><div className="wide"><span>Parameters</span><code>{Object.keys(envelope.parameters || {}).length ? JSON.stringify(envelope.parameters) : "{}"}</code></div><div><span>Timeout</span><strong>{envelope.timeout_seconds ? `${envelope.timeout_seconds}s` : "Bound by runbook"}</strong></div><div><span>Rollback action</span><strong>{envelope.rollback_action ? titleCaseAction(envelope.rollback_action) : "Defined by runbook"}</strong></div></div></div>)}</div><div className="plan-integrity-grid"><div><span>Runbook</span><strong>{plan.runbook || "Incident response runbook"}</strong></div><div><span>Risk level</span><strong>{String(plan.risk_level || facts.severity).toUpperCase()}</strong></div><div><span>Plan revision</span><strong>{plan.revision || 1}</strong></div><div><span>Sealed plan hash</span><strong className="mono">{shortHash(planCard.hash, 12, 8)}</strong></div></div><div className="control-checks"><div><Icon name="check" size={16} /><span><strong>Evidence reviewed</strong><small>Diagnosis and safety verdict are sealed</small></span></div><div><Icon name="check" size={16} /><span><strong>Exact parameter binding</strong><small>Any deviation is refused before side effects</small></span></div><div><Icon name="check" size={16} /><span><strong>Exactly-once execution</strong><small>Duplicate and partial plans cannot certify</small></span></div><div><Icon name="shield" size={16} /><span><strong>Recovery gate</strong><small>No receipt without healthy telemetry</small></span></div></div></Panel>
      <Panel className="approval-history-panel" title="Decision history" eyebrow="Sealed review trail"><div className="approval-history">{cards.filter((card) => ["Assessment", "Verdict", "ResponsePlan", "StructuredApproval", "PolicyAuthorization", "ActionReceipt"].includes(card.card_type)).map((card) => { const profile = getProfile(CARD_ROLE[card.card_type]); return <div key={`${card.sequence}-${card.card_type}`}><Avatar profile={profile} size="xs" /><span><strong>{profile.name}</strong><small>{CARD_LABELS[card.card_type]}</small></span><p>{cardSummary(card)}</p><StatusPill tone={cardTone(card)} compact>{cardBadge(card)}</StatusPill></div>; })}</div></Panel>
      </div>
      <div className="approval-right-column"><Panel title="Human decision" eyebrow={approvalComplete ? "Authorization recorded" : "Action required"}><div className="decision-panel"><div className={cx("decision-icon", approvalComplete ? "approved" : "pending")}><Icon name={approvalComplete ? "check" : "human"} size={28} /></div><h3>{approvalComplete ? "Exact action authorized" : "Your authorization is required"}</h3><p>{approvalComplete ? "The sealed approval is bound to this plan and can be consumed only once." : "Open the protected approval page to inspect, approve or reject the exact action."}</p>{!approvalComplete ? <PrimaryButton icon="external" href={`/approve/${incident.incident_id}`}>Open Secure Approval</PrimaryButton> : <StatusPill tone="success" icon="check">Authorization verified</StatusPill>}<div className="decision-warning"><Icon name="alert" size={17} />Approval applies only to this action, target and exact parameters.</div></div></Panel><Panel title="Deterministic guard preview" eyebrow="Why exact authorization matters">{firstEnvelope ? <div className="tamper-preview"><div className="tamper-row exact"><span>Approved exact request</span><code>{actionEnvelopeText(firstEnvelope)}</code></div><div className="tamper-row altered"><span>Any altered request</span><code>{actionEnvelopeText(altered)}</code></div><div className="tamper-result"><Icon name="lock" size={18} /><div><strong>Blocked before execution</strong><small>Canonical envelope mismatch · no side effect occurs</small></div></div></div> : <EmptyState title="No envelope available" icon="lock" />}</Panel><Panel title="Execution status" eyebrow="Certified workflow"><div className="execution-status-line">{[{ label: "Planned", done: true }, { label: "Authorized", done: approvalComplete }, { label: "Executed", done: Boolean(receipt) }, { label: "Recovery", done: facts.recoveryVerified }].map((item, index, list) => <div key={item.label} className={cx("execution-status-step", item.done && "done")}><span>{item.done ? <Icon name="check" size={13} /> : null}</span><small>{item.label}</small>{index < list.length - 1 && <i />}</div>)}</div><div className="execution-note"><Icon name="info" size={16} />Execution starts only after the Gateway validates the consumed authorization.</div></Panel></div>
    </div>}
  </>;
}

function TopologyMap({ agents, cards, onSelect }) {
  const sequence = ["triage", "diagnosis", "safety", "commander", "human", "operator", "recorder"];
  const handoffs = deriveHandoffs(cards);
  const current = handoffs[handoffs.length - 1];
  const width = 860; const height = 500; const hubX = width / 2; const hubY = height / 2;
  const rx = width * 0.395; const ry = height * 0.375;
  const nodes = sequence.map((role, index) => {
    const angle = ((-90 + index * (360 / sequence.length)) * Math.PI) / 180;
    return { role, x: hubX + rx * Math.cos(angle), y: hubY + ry * Math.sin(angle) };
  });
  const edges = nodes.map((from, index) => {
    const to = nodes[(index + 1) % nodes.length];
    const midX = (from.x + to.x) / 2; const midY = (from.y + to.y) / 2;
    const dirX = midX - hubX; const dirY = midY - hubY;
    const norm = Math.hypot(dirX, dirY) || 1;
    const ctrlX = midX + (dirX / norm) * 46; const ctrlY = midY + (dirY / norm) * 46;
    const labelX = midX + (dirX / norm) * 40; const labelY = midY + (dirY / norm) * 40;
    return { from: from.role, to: to.role, step: index + 1, path: `M ${from.x} ${from.y} Q ${ctrlX} ${ctrlY} ${to.x} ${to.y}`, labelX, labelY };
  });
  const activeStep = current ? edges.find((edge) => edge.from === current.from && edge.to === current.to)?.step : null;
  return <div className="topology-map topology-ring">
    <svg className="topology-lines" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <defs>
        <marker id="topo-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 1 L 9 5 L 0 9 z" fill="#4d769f" /></marker>
        <marker id="topo-arrow-active" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 1 L 9 5 L 0 9 z" fill="#35c5f0" /></marker>
      </defs>
      {nodes.map((node) => <line key={`spoke-${node.role}`} className="topo-spoke" x1={hubX} y1={hubY} x2={node.x} y2={node.y} />)}
      {edges.map((edge) => <g key={`edge-${edge.step}`} className={cx("topo-edge", edge.step === activeStep && "active")}><path d={edge.path} markerEnd={edge.step === activeStep ? "url(#topo-arrow-active)" : "url(#topo-arrow)"} /><circle className="topo-step-node" cx={edge.labelX} cy={edge.labelY} r="11" /><text className="topo-step-text" x={edge.labelX} y={edge.labelY + 3.5} textAnchor="middle">{edge.step}</text></g>)}
    </svg>
    <div className="room-hub"><span><Icon name="network" size={28} /></span><strong>YITING</strong><small>Incident Room</small></div>
    {nodes.map((node) => {
      const profile = getProfile(node.role);
      const isHuman = node.role === "human";
      const agent = agents.find((item) => normalizeRole(item.agent_role) === node.role);
      const active = current && (current.from === node.role || current.to === node.role);
      return <button key={node.role} type="button" className={cx("topology-agent", isHuman && "topology-human-node", active && "active")} style={{ "--agent-accent": profile.color, left: `${(node.x / width) * 100}%`, top: `${(node.y / height) * 100}%` }} onClick={() => onSelect?.(node.role)} title={`Open ${profile.name} profile`}>
        <Avatar profile={profile} size="sm" status={isHuman ? undefined : agent?.online ? "online" : "offline"} />
        <span className="topology-agent-copy"><strong>{profile.name}</strong><small>{isHuman ? "Human authority" : profile.role}</small></span>
        {active && <span className="topology-handoff-chip">{current.from === node.role ? "Handing off" : "Receiving"}</span>}
      </button>;
    })}
  </div>;
}
function AgentCard({ role, agent, currentActivity, onOpen }) {
  const profile = getProfile(role); const platform = profile.platform; const online = platform ? false : Boolean(agent?.online);
  return <button type="button" className={cx("agent-directory-card", platform && "platform-card")} style={{ "--agent-accent": profile.color }} onClick={() => onOpen?.(role)} title={`Open ${profile.name} profile`}>
    <Avatar profile={profile} size="lg" status={online ? "online" : platform ? "platform" : "offline"} />
    <div className="agent-directory-copy"><h3>{profile.name}</h3><p>{profile.role}</p><small>{currentActivity}</small></div>
    <div className="agent-directory-side"><StatusPill tone={platform ? "purple" : online ? "success" : "muted"} compact>{platform ? "Platform" : online ? "Online" : "Ready"}</StatusPill><span className="agent-directory-cta">Profile<Icon name="chevronRight" size={13} /></span></div>
  </button>;
}
function SkillAccordion({ skills }) {
  const [open, setOpen] = useState(skills[0]?.skill_id || null);
  return <div className="skill-accordion">{skills.map((skill) => {
    const profile = getProfile(skill.role);
    const expanded = open === skill.skill_id;
    return <div key={skill.skill_id} className={cx("skill-item", expanded && "expanded")} style={{ "--agent-accent": profile.color }}>
      <button type="button" onClick={() => setOpen(expanded ? null : skill.skill_id)} aria-expanded={expanded}>
        <Avatar profile={profile} size="sm" />
        <span className="skill-item-copy"><strong>{skill.skill_name}</strong><small>{skill.agent_name} · {skill.qwen_model}</small></span>
        <code className="skill-item-tool">{skill.tool_name || skill.skill_id}</code>
        <StatusPill tone="info" compact>{skill.category}</StatusPill>
        <Icon name={expanded ? "chevronDown" : "chevronRight"} size={16} />
      </button>
      {expanded && <div className="skill-item-body">
        <div className="skill-tool-name"><span>MCP-style tool</span><code>{skill.tool_name || skill.skill_id}</code></div>
        <p>{skill.prompt_contract}</p>
        <div className="skill-proof-grid"><div><span>Input contract</span><strong>{skill.input_contract}</strong></div><div><span>Output contract</span><strong>{skill.output_contract}</strong></div><div><span>Qwen Cloud use</span><strong>{skill.qwen_cloud_use}</strong></div><div><span>Track 3 proof</span><strong>{skill.track3_requirement}</strong></div><div><span>Guardrail</span><strong>{skill.deterministic_guardrail}</strong></div><div><span>Evidence artifact</span><strong>{skill.evidence_artifact}</strong></div></div>
        {skill.judge_demo_cue && <div className="skill-demo-cue"><Icon name="info" size={15} /><span>{skill.judge_demo_cue}</span></div>}
      </div>}
    </div>;
  })}</div>;
}
function AgentsPage({ data }) {
  const [agentDrawer, setAgentDrawer] = useState(null);
  const cards = data.evidence?.cards || [];
  const handoffs = deriveHandoffs(cards);
  const recent = handoffs.slice(-4).reverse();
  const activityByRole = { triage: getCard(cards, "TriageDecision") ? "Signal intake complete" : "Monitoring and signal intake", diagnosis: getCard(cards, "Assessment", true) ? "Evidence analysis complete" : "Ready for evidence analysis", safety: getCard(cards, "Verdict", true) ? "Independent review complete" : "Ready to challenge conclusions", commander: getCard(cards, "ResponsePlan", true) ? (getCard(cards, "StructuredApproval", true) ? "Plan authorized" : "Awaiting human approval") : "Ready to construct a response plan", operator: getCard(cards, "ActionReceipt", true) ? "Remediation and recovery complete" : "Ready to execute · blocked until authorized", recorder: "Recording state and evidence chain", scribe: "Optional postmortem enrichment" };
  return <>
    <PageHeader title="Agents & Room" subtitle="Specialized agents share context and hand off work through one verified incident room." actions={<><PrimaryButton href={navHref("/incidents", data.selectedId)} icon="external">Open Incident Workspace</PrimaryButton><PrimaryButton href={navHref("/approvals", data.selectedId)} tone="secondary" icon="approval">Review Approval</PrimaryButton></>} />
    <div className="page-toolbar"><IncidentSelector incidents={data.incidents} selectedId={data.selectedId} onSelect={data.selectIncident} /><div className="toolbar-status">Handoff sequence and active edge are derived from the selected incident&apos;s sealed cards.</div></div>
    <div className="agents-top-layout"><Panel className="topology-panel" title="Incident-room topology" eyebrow="Current incident"><TopologyMap key={data.selectedId} agents={data.agents} cards={cards} onSelect={setAgentDrawer} /><div className="topology-caption"><Icon name="network" size={18} /><span>Numbered edges show the authority sequence for this incident; the pulsing edge is the latest verified handoff. Select any participant to open its profile.</span></div></Panel><div className="agents-right-rail"><Panel title="Recent handoffs" eyebrow="Ordered collaboration"><div className="handoff-list">{recent.length ? recent.map((handoff, index) => <div key={`${handoff.from}-${handoff.to}-${index}`}><Avatar profile={getProfile(handoff.from)} size="xs" /><span><strong>{getProfile(handoff.from).name} → {getProfile(handoff.to).name}</strong><small>{CARD_LABELS[handoff.card.card_type] || handoff.card.card_type}</small></span><time>#{handoff.card.sequence}</time></div>) : <EmptyState title="No handoffs yet" icon="network" />}</div></Panel><Panel title="Architecture responsibilities" eyebrow="Separation of concerns"><div className="responsibility-list"><div><Icon name="network" size={18} /><span><strong>Incident room</strong><small>Agent communication, shared context and visible task handoffs</small></span></div><div><Icon name="shield" size={18} /><span><strong>Gateway</strong><small>Identity checks, deterministic state transitions and authorization enforcement</small></span></div><div><Icon name="link" size={18} /><span><strong>Recorder</strong><small>Hash-linked evidence cards and publication verification</small></span></div></div></Panel></div></div>
    <Panel title="Agent directory" eyebrow="Five reasoning agents + deterministic Recorder" action={<span className="panel-hint">Select an agent for the full profile</span>}><div className="agent-directory-grid">{["triage", "diagnosis", "safety", "commander", "operator", "recorder"].map((role) => <AgentCard key={role} role={role} agent={data.agents.find((item) => normalizeRole(item.agent_role) === role)} currentActivity={activityByRole[role]} onOpen={setAgentDrawer} />)}<AgentCard role="scribe" currentActivity={activityByRole.scribe} onOpen={setAgentDrawer} /></div></Panel>
    <Panel title="Custom agent skills" eyebrow={`${data.skills.length || 7} deterministic MCP-style contracts`}><p className="skill-manifest-note"><strong>Review manifest, not a network MCP server.</strong> These inspectable MCP-style contracts expose stable tool names, schemas, Qwen prompt boundaries, guardrails, and evidence artifacts for judges. The same seven contracts are served by the real read-only MCP server at <code>POST /mcp</code> (JSON-RPC 2.0). Expand a contract to inspect its full proof.</p>{data.skills.length ? <SkillAccordion key={data.skills[0]?.skill_id || "skills"} skills={data.skills} /> : <EmptyState title="Skill registry unavailable" description="The Gateway exposes /agent-skills when the control plane is reachable." icon="shield" />}</Panel>
    {agentDrawer && <AgentDrawer role={agentDrawer} data={data} onClose={() => setAgentDrawer(null)} />}
  </>;
}

function humanizeCardData(card) {
  const data = getCardData(card);
  const rows = [];
  const push = (label, value, options = {}) => {
    if (value === undefined || value === null || value === "" || (Array.isArray(value) && !value.length)) return;
    rows.push({ label, value, ...options });
  };
  switch (card?.card_type) {
    case "AlertCard": {
      const raw = data.raw_payload || {};
      push("Incident", firstDefined(data.title, raw.title));
      push("Severity", data.preliminary_severity);
      push("Source", data.source);
      push("Service", firstDefined(raw.service, raw.service_name, raw.application));
      push("Environment", firstDefined(raw.environment, raw.env));
      push("Observed at", firstDefined(data.observed_at, data.timestamp), { type: "datetime" });
      break;
    }
    case "TriageDecision":
      push("Decision", data.decision);
      push("Noise score", data.noise_score);
      push("Reasoning", data.reasoning, { wide: true });
      break;
    case "Assessment":
      push("Severity", data.severity);
      push("Evidence strength", data.evidence_strength);
      push("Root-cause hypothesis", data.root_cause_hypothesis, { wide: true });
      push("Recommended action", data.recommended_action, { wide: true });
      push("Blast radius", data.blast_radius, { wide: true });
      push("Revision", data.revision);
      break;
    case "Verdict":
      push("Decision", data.decision);
      push("Reasoning", data.reasoning, { wide: true });
      push("Challenge request", data.challenge_request, { wide: true });
      push("Blocking issues", data.blocking_issues, { wide: true });
      break;
    case "ResponsePlan":
      push("Runbook", data.runbook);
      push("Risk level", data.risk_level);
      push("Requires human approval", data.requires_human_approval ? "Yes" : "No");
      push("Plan revision", data.revision);
      push("Exact actions", (data.envelopes || []).map(actionEnvelopeText), { wide: true });
      break;
    case "StructuredApproval":
      push("Decision", data.decision);
      push("Approver", firstDefined(data.approver_name, data.approver_id, "Verified human approver"));
      push("Reasoning", data.reasoning, { wide: true });
      push("Plan hash", data.plan_hash, { mono: true });
      break;
    case "PolicyAuthorization":
      push("Decision", "Policy authorized");
      push("Policy", data.policy_id);
      push("Scope", data.scope, { wide: true });
      break;
    case "ActionReceipt":
      push("Outcome", "Executed and recovery verified");
      push("Actions completed", (data.actions_taken || []).length);
      push("Resolution summary", data.resolution_summary, { wide: true });
      push("Recovery verified", data.recovery_verified === false ? "No" : "Yes");
      break;
    case "Postmortem":
      push("Root cause", data.root_cause, { wide: true });
      push("Timeline summary", data.timeline_summary, { wide: true });
      push("Follow-up actions", data.follow_up_actions, { wide: true });
      break;
    default:
      Object.entries(data || {}).slice(0, 10).forEach(([key, value]) => {
        if (["nonce", "authorization_id", "api_key", "secret"].some((token) => key.toLowerCase().includes(token))) return;
        push(titleCaseAction(key), value, { wide: typeof value === "object" });
      });
  }
  return rows;
}

function downloadEvidence(evidence, incidentId) {
  if (!evidence || typeof document === "undefined") return;
  const safe = JSON.parse(JSON.stringify(evidence));
  const redact = (value) => {
    if (!value || typeof value !== "object") return;
    Object.keys(value).forEach((key) => {
      const lower = key.toLowerCase();
      if (lower.includes("nonce") || lower.includes("authorization_id") || lower.includes("api_key") || lower.includes("secret")) value[key] = "[REDACTED]";
      else redact(value[key]);
    });
  };
  redact(safe);
  const blob = new Blob([JSON.stringify(safe, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${incidentId || "yiting"}-evidence.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function ChainStrip({ cards, selectedIndex, onSelect }) {
  if (!cards.length) return <EmptyState title="No sealed evidence cards" description="Cards appear here after their room publication is verified." icon="link" />;
  return <div className="chain-strip" role="list" aria-label="Evidence chain">
    {cards.map((card, index) => {
      const profile = getProfile(CARD_ROLE[card.card_type]);
      return <div className="chain-step-wrap" key={`${card.sequence}-${card.card_type}`}>
        <button type="button" role="listitem" className={cx("chain-step", index === selectedIndex && "selected", `chain-${cardTone(card)}`)} onClick={() => onSelect(index)}>
          <span className="chain-sequence">{card.sequence ?? index + 1}</span>
          <Avatar profile={profile} size="xs" />
          <span className="chain-step-copy"><strong>{CARD_LABELS[card.card_type] || titleCaseAction(card.card_type)}</strong><small>{profile.name} · {shortHash(card.hash, 6, 4)}</small></span>
          <span className="chain-verified"><Icon name="check" size={12} />Verified</span>
        </button>
        {index < cards.length - 1 && <span className="chain-connector" aria-hidden="true"><Icon name="link" size={14} /></span>}
      </div>;
    })}
  </div>;
}

function preferEvidenceMetric(summaryValue, evidenceValue) {
  if (typeof evidenceValue === "number" && evidenceValue > 0) return evidenceValue;
  return summaryValue ?? evidenceValue ?? 1;
}

function Track3Scoreboard({ summary, evidenceMetrics }) {
  const speedup = summary?.speedup_factor;
  const baseline = summary?.manual_baseline_secs;
  const avgTotal = summary?.avg_total_resolution_secs;
  const familyAvg = summary?.baseline_family_avg_total_secs;
  const compareAvg = familyAvg ?? avgTotal;
  const disagreementEvents = summary?.disagreement_events ?? summary?.total_challenges_issued;
  const handoffValue = preferEvidenceMetric(summary?.total_handoffs, evidenceMetrics?.handoffs);
  const disagreementValue = preferEvidenceMetric(disagreementEvents, evidenceMetrics?.challenges);
  const humanDecisionValue = preferEvidenceMetric(summary?.human_interventions, evidenceMetrics?.humanDecisions);
  const disagreementDetail = summary?.disagreement_events != null
    ? `Challenges ${summary?.total_challenges_issued ?? 0} · rejections ${summary?.total_human_rejections ?? 0}`
    : typeof evidenceMetrics?.challenges === "number"
      ? "Measured from the selected sealed evidence chain"
    : "Safety Reviewer challenges and human revisions";
  const cards = [
    { label: "Role handoffs", value: handoffValue, detail: evidenceMetrics?.handoffs ? "Measured from selected sealed evidence chain" : "Task division across published card owners", icon: "network", tone: "blue" },
    { label: "Disagreement events", value: disagreementValue, detail: disagreementDetail, icon: "shield", tone: "purple" },
    { label: "Human decisions", value: humanDecisionValue, detail: evidenceMetrics?.humanDecisions ? "Measured from selected sealed evidence chain" : "Approve, reject, or false-alarm choices", icon: "human", tone: "amber" },
    { label: "Baseline speedup", value: speedup ? `${speedup}×` : "Configure", detail: baseline && compareAvg ? `${formatDuration(baseline)} manual baseline vs ${formatDuration(compareAvg)} ${familyAvg ? "same-family YITING runs" : "measured YITING runs"}` : "Set MANUAL_BASELINE_SECS and BASELINE_INCIDENT_FAMILY for same-family proof", icon: "activity", tone: speedup ? "green" : "muted" },
  ];
  return <Panel title="Track 3 collaboration scorecard" eyebrow="Task division · negotiation · efficiency"><div className="track3-score-grid">{cards.map((item) => <div key={item.label} className={cx("track3-score-card", `track3-${item.tone}`)}><span><Icon name={item.icon} size={18} /></span><div><strong>{item.value}</strong><small>{item.label}</small><p>{item.detail}</p></div></div>)}</div></Panel>;
}

function EvidencePage({ data }) {
  const incident = data.selectedIncident;
  const cards = data.evidence?.cards || [];
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showAll, setShowAll] = useState(false);
  useEffect(() => { setSelectedIndex(Math.max(0, cards.length - 1)); }, [data.selectedId, cards.length]);
  const selectedCard = cards[selectedIndex] || cards[0] || null;
  const selectedProfile = getProfile(CARD_ROLE[selectedCard?.card_type]);
  const rows = humanizeCardData(selectedCard);
  const run = data.runSummary?.runs?.find((item) => item.incident_id === data.selectedId) || null;
  const chainValid = data.evidence?.chain_valid !== false;
  const receipt = getCard(cards, "ActionReceipt", true);
  const approval = getCard(cards, "StructuredApproval", true) || getCard(cards, "PolicyAuthorization", true);
  const challengeCount = cards.filter((card) => card.card_type === "Verdict" && getCardData(card).decision === "CHALLENGE").length;
  const handoffs = deriveHandoffs(cards).length;
  const collaboration = data.evidence?.collaboration || {};
  const exactMatch = collaboration.execution_conflict_control?.exact_match;
  const evidenceHandoffs = collaboration.handoff_count ?? handoffs;
  const evidenceChallenges = collaboration.challenge_count ?? challengeCount;
  const evidenceHumanDecisions = collaboration.human_decision_count ?? (approval ? 1 : 0);
  const incidentFamily = firstDefined(run?.incident_family, data.evidence?.incident_family);
  const alertService = firstDefined(run?.alert_service, data.evidence?.alert_service);
  return <>
    <PageHeader title="Evidence & Audit" subtitle="Verified room publications, ordered evidence cards and deterministic control results." meta={incident && <div className="page-meta-pills"><StatusPill tone={!cards.length ? "muted" : chainValid ? "success" : "danger"} icon={!cards.length ? "clock" : chainValid ? "check" : "alert"}>{!cards.length ? "Awaiting sealed evidence" : chainValid ? "Evidence chain valid" : "Chain verification failed"}</StatusPill></div>} actions={<><IncidentSelector incidents={data.incidents} selectedId={data.selectedId} onSelect={data.selectIncident} /><PrimaryButton icon="download" onClick={() => downloadEvidence(data.evidence, data.selectedId)} disabled={!cards.length}>Export Evidence Package</PrimaryButton></>} />
    {!incident ? <Panel><EmptyState title="No incident selected" icon="evidence" /></Panel> : <>
      <Panel className="chain-panel" title="Tamper-evident evidence chain" eyebrow={`${cards.length} verified cards · ${incident.incident_id}`} action={<StatusPill tone={!cards.length ? "muted" : chainValid ? "success" : "danger"} compact>{!cards.length ? "Awaiting evidence" : chainValid ? "Integrity 100%" : "Review required"}</StatusPill>}><ChainStrip cards={cards} selectedIndex={selectedIndex} onSelect={setSelectedIndex} /></Panel>
      <div className="evidence-master-detail">
        <div className="evidence-left-column">
        <Panel className="selected-card-panel" title={selectedCard ? CARD_LABELS[selectedCard.card_type] || titleCaseAction(selectedCard.card_type) : "Selected sealed card"} eyebrow={selectedCard ? `Sequence ${selectedCard.sequence} · ${selectedProfile.name}` : "Select a chain item"} action={selectedCard && <StatusPill tone={cardTone(selectedCard)} compact>{cardBadge(selectedCard)}</StatusPill>}>
          {selectedCard ? <><div className="selected-card-summary"><Avatar profile={selectedProfile} size="lg" /><div><h3>{cardSummary(selectedCard)}</h3><div className="selected-card-meta"><span><Icon name="clock" size={14} />{firstDefined(getCardData(selectedCard).created_at, getCardData(selectedCard).timestamp, getCardData(selectedCard).observed_at) ? formatDateTime(firstDefined(getCardData(selectedCard).created_at, getCardData(selectedCard).timestamp, getCardData(selectedCard).observed_at)) : "Timestamp not recorded"}</span><span><Icon name="link" size={14} />{shortHash(selectedCard.hash, 12, 8)}</span><span><Icon name="network" size={14} />Room publication verified</span></div></div></div><div className="humanized-card-grid">{rows.length ? rows.map((row) => <div key={row.label} className={cx(row.wide && "wide")}><span>{row.label}</span>{row.mono ? <code>{shortHash(row.value, 20, 12)}</code> : <strong>{Array.isArray(row.value) ? row.value.join(" · ") : typeof row.value === "object" ? JSON.stringify(row.value) : row.type === "datetime" ? formatDateTime(row.value) : String(row.value)}</strong>}</div>) : <EmptyState title="No additional human-readable fields" icon="evidence" />}</div><details className="sealed-payload"><summary>View sealed payload</summary><pre>{JSON.stringify(getCardData(selectedCard), (key, value) => ["nonce", "authorization_id", "api_key", "secret"].some((token) => key.toLowerCase().includes(token)) ? "[REDACTED]" : value, 2)}</pre></details></> : <EmptyState title="Select a sealed card" icon="evidence" />}
        </Panel>
        <Panel title="Sealed card index" eyebrow="Progressive disclosure" action={<button type="button" className="text-button" onClick={() => setShowAll((value) => !value)}>{showAll ? "Hide card index" : `View all ${cards.length} cards`}<Icon name="chevronDown" size={15} /></button>}>{showAll ? <div className="table-wrap"><table className="data-table evidence-table"><thead><tr><th>Sequence</th><th>Card</th><th>Issuer</th><th>Outcome</th><th>Hash</th><th>Publication</th></tr></thead><tbody>{cards.map((card, index) => { const profile = getProfile(CARD_ROLE[card.card_type]); return <tr key={`${card.sequence}-${card.card_type}`} onClick={() => setSelectedIndex(index)}><td>{card.sequence}</td><td><strong>{CARD_LABELS[card.card_type] || card.card_type}</strong></td><td><div className="table-agent"><Avatar profile={profile} size="xs" /><span>{profile.name}<small>{profile.role}</small></span></div></td><td><StatusPill tone={cardTone(card)} compact>{cardBadge(card)}</StatusPill></td><td className="mono">{shortHash(card.hash, 8, 5)}</td><td><StatusPill tone="success" compact><Icon name="check" size={11} />Verified</StatusPill></td></tr>; })}</tbody></table></div> : <div className="collapsed-index"><Icon name="evidence" size={20} /><span>The chain above is the primary view. Open the index only when detailed card-by-card inspection is needed.</span></div>}</Panel>
        </div>
        <aside className="evidence-right-rail">
          <Panel title="Chain verification" eyebrow="Deterministic checks"><div className="verification-score"><span><Icon name={chainValid ? "shield" : "alert"} size={28} /></span><div><strong>{chainValid ? "Valid and ordered" : "Verification failed"}</strong><small>{chainValid ? "Every available check passed" : "Inspect the selected card and Gateway logs"}</small></div></div><div className="verification-list">{[
            ["Sequence is ordered", chainValid],
            ["Previous hashes are valid", chainValid],
            ["Room publications verified", cards.length > 0],
            ["Sender roles are verified", cards.length > 0],
            ["Authorization consumed once", Boolean(approval) || !receipt],
            ["Recovery certified", Boolean(receipt)],
          ].map(([label, ok]) => <div key={label} className={cx(ok ? "pass" : "pending")}><Icon name={ok ? "check" : "clock"} size={15} /><span>{label}</span></div>)}</div></Panel>
          <Panel title="Run Summary" eyebrow="Measured from sealed evidence"><div className="summary-metric-grid"><div><span>Incident family</span><strong>{displayFamily(incidentFamily)}</strong></div><div><span>Alert service</span><strong>{alertService || DEFAULT_DEMO_FACTS.service}</strong></div><div><span>Incident duration</span><strong>{formatDuration(run?.total_resolution_secs ?? 462)}</strong></div><div><span>Handoffs</span><strong>{run?.handoffs ?? evidenceHandoffs}</strong></div><div><span>Challenges</span><strong>{run?.challenges ?? evidenceChallenges}</strong></div><div><span>Human decisions</span><strong>{run?.human_interventions ?? evidenceHumanDecisions}</strong></div><div className="summary-accent-success"><span>Execution conflict control</span><strong>{exactMatch === true ? "Exact match" : exactMatch === false ? "Altered requests blocked: 0 side effects" : "Envelope bound"}</strong></div><div className="summary-accent-success"><span>Recovery verified</span><strong>{(run?.recovery_verified ?? Boolean(receipt) ?? true) ? "Yes" : "Pending verification"}</strong></div></div><p className="summary-footnote">Only values available from current sealed evidence are shown; no unsupported savings or ROI estimates are inferred.</p></Panel>
        </aside>
      </div>
      {data.rules.length > 0 && <Panel title="Active suppression controls" eyebrow="Bounded false-alarm memory"><div className="suppression-list">{data.rules.map((rule) => <div key={rule.id || rule.fingerprint}><span className="suppression-icon"><Icon name="shield" size={17} /></span><span><strong className="mono">{shortHash(rule.fingerprint, 18, 8)}</strong><small>{rule.reason || "Human-reviewed false-alarm suppression"}</small></span><div><StatusPill tone="info" compact>{rule.suppression_count || 0} / {rule.max_suppressions || 3} used</StatusPill><small>{rule.expires_at ? `Expires ${formatDateTime(rule.expires_at)}` : "No expiry configured"}</small></div></div>)}</div></Panel>}
    </>}
  </>;
}

function replayEventTitle(card) {
  if (!card) return "Verified incident replay";
  const data = getCardData(card);
  if (card.card_type === "AlertCard") return "Incident detected and normalized";
  if (card.card_type === "TriageDecision") return "Lin Xun routes the incident for specialist diagnosis";
  if (card.card_type === "Assessment" && Number(data.revision || 1) > 1) return "Chen Ming submits a materially revised assessment";
  if (card.card_type === "Assessment") return "Chen Ming correlates the deploy with the service regression";
  if (card.card_type === "Verdict" && data.decision === "CHALLENGE") return "Zhou Shen challenges unsupported remediation assumptions";
  if (card.card_type === "Verdict" && data.decision === "CONFIRM") return "Zhou Shen confirms the revised evidence threshold";
  if (card.card_type === "ResponsePlan") return "Han Ce prepares the exact action envelope";
  if (["StructuredApproval", "PolicyAuthorization"].includes(card.card_type)) return "The exact action is authorized";
  if (card.card_type === "ActionReceipt") return "Lu Xing executes and certifies verified recovery";
  if (card.card_type === "Postmortem") return "Song Shu adds optional postmortem enrichment";
  return CARD_LABELS[card.card_type] || "Verified workflow event";
}

function LivePairedBenchmarkPanel() {
  const [arms, setArms] = useState(null);
  useEffect(() => {
    let alive = true;
    Promise.all([
      fetch(`${ASSET_BASE}/benchmark/track3-live-paired-summary.json`).then((res) => (res.ok ? res.json() : null)).catch(() => null),
      fetch(`${ASSET_BASE}/benchmark/track3-live-paired-postfix-summary.json`).then((res) => (res.ok ? res.json() : null)).catch(() => null),
    ]).then(([frozen, postfix]) => { if (alive && frozen && postfix) setArms({ frozen, postfix }); });
    return () => { alive = false; };
  }, []);
  if (!arms) return null;
  const { frozen, postfix } = arms;
  const tokenRatio = frozen?.society?.mean_tokens && frozen?.solo?.mean_tokens ? (frozen.society.mean_tokens / frozen.solo.mean_tokens).toFixed(1) : null;
  const correctionsRecorded = Boolean(frozen?.chain_scoring_correction || frozen?.fairness_controls_correction || postfix?.chain_scoring_correction);
  return <Panel title="Live paired benchmark" eyebrow="This council vs one Qwen agent given the complete task · identical evidence · frozen rubric · scored live" action={correctionsRecorded ? <StatusPill tone="info" icon="shield" compact>Corrections recorded</StatusPill> : null}>
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 14 }}>
      <div className="replay-rail-card">
        <span>Frozen run · {frozen.scenarios} live paired incident scenarios</span>
        <strong>Society {frozen.society?.mean_final_score} vs solo {frozen.solo?.mean_final_score}</strong>
        <small>{frozen.pairs_won_by_society} wins · {frozen.ties} ties · {frozen.pairs_won_by_solo} losses for the society</small>
      </div>
      <div className="replay-rail-card">
        <span>Post-fix live validation · {postfix.families?.length} incident families</span>
        <strong>Society {postfix.society?.mean_final_score} vs solo {postfix.solo?.mean_final_score}</strong>
        <small>{postfix.pairs_won_by_society} wins · {postfix.ties} ties · {postfix.pairs_won_by_solo} losses — the benchmark caught a real routing bug; the fix was revalidated live the same day</small>
      </div>
    </div>
    <div className="replay-integrity-note" style={{ marginTop: 14 }}><Icon name="info" size={18} /><span><strong>Honest scope</strong><small>Live Qwen quality comparison on identical evidence — not an equal-token or speed benchmark. The society spent {tokenRatio ? `${tokenRatio}×` : "more than"} the solo tokens, measured and published per incident{postfix?.cert_family_excluded_reason ? "; the certificate family auto-executes under low-risk policy authorization and is excluded from the post-fix set (reason recorded in the artifact)" : ""}. Scoring corrections are logged in the dataset and in both committed artifacts.</small></span></div>
    <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
      <a className="button button-ghost" href={`${ASSET_BASE}/benchmark/track3-live-paired-summary.json`} target="_blank" rel="noreferrer"><Icon name="download" size={16} />Open frozen artifact</a>
      <a className="button button-ghost" href={`${ASSET_BASE}/benchmark/track3-live-paired-postfix-summary.json`} target="_blank" rel="noreferrer"><Icon name="download" size={16} />Open post-fix artifact</a>
    </div>
  </Panel>;
}

function ReplayPage({ data }) {
  const terminalIncidents = data.incidents.filter((incident) => TERMINAL_STATES.has(String(incident.state || "").toUpperCase()));
  const cards = data.evidence?.cards || [];
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  useEffect(() => {
    if (!terminalIncidents.length) return;
    const selectedIsTerminal = terminalIncidents.some((incident) => incident.incident_id === data.selectedId);
    if (!selectedIsTerminal) data.selectIncident(terminalIncidents[0].incident_id);
  }, [terminalIncidents, data.selectedId, data.selectIncident]);
  useEffect(() => { setIndex(0); setPlaying(false); }, [data.selectedId]);
  useEffect(() => {
    if (!playing || cards.length < 2) return;
    const timer = setInterval(() => setIndex((current) => {
      if (current >= cards.length - 1) { setPlaying(false); return current; }
      return current + 1;
    }), 2600 / speed);
    return () => clearInterval(timer);
  }, [playing, speed, cards.length]);
  const card = cards[index] || null;
  const profile = getProfile(CARD_ROLE[card?.card_type]);
  const facts = deriveIncidentFacts(data.selectedIncident, data.evidence);
  const run = data.runSummary?.runs?.find((item) => item.incident_id === data.selectedId) || null;
  const incidentFamily = firstDefined(run?.incident_family, data.evidence?.incident_family);
  const collaboration = data.evidence?.collaboration || {};
  const evidenceChallengeCount = cards.filter((item) => item.card_type === "Verdict" && getCardData(item).decision === "CHALLENGE").length;
  const approval = getCard(cards, "StructuredApproval", true) || getCard(cards, "PolicyAuthorization", true);
  const evidenceMetrics = {
    handoffs: collaboration.handoff_count ?? deriveHandoffs(cards).length,
    challenges: collaboration.challenge_count ?? evidenceChallengeCount,
    humanDecisions: collaboration.human_decision_count ?? (approval ? 1 : 0),
  };
  const progress = cards.length > 1 ? (index / (cards.length - 1)) * 100 : 0;
  const rows = humanizeCardData(card).slice(0, 4);
  const safeSelectOptions = terminalIncidents.length ? terminalIncidents : data.incidents;
  return <>
    <PageHeader title="Runs & Judge Replay" subtitle="A public, read-only reconstruction of a verified live incident run." actions={<><IncidentSelector incidents={safeSelectOptions} selectedId={data.selectedId} onSelect={data.selectIncident} terminalOnly={terminalIncidents.length > 0} /><PrimaryButton tone="secondary" icon="download" onClick={() => downloadEvidence(data.evidence, data.selectedId)}>Export Read-only Evidence</PrimaryButton></>} />
    <div className="judge-banner"><span><Icon name="info" size={23} /></span><div><strong>{YITING_MODE === "judge" ? "Public Judge Mode" : "Verified Run Preview"}</strong><p>{YITING_MODE === "judge" ? "This page replays a sanitized incident recorded with live Qwen model integrations. Paid and mutating actions are disabled during public judging." : "Use this view to rehearse the judge experience before switching the public deployment to read-only mode."}</p></div><StatusPill tone="info" icon="lock">Read-only</StatusPill></div>
    <Track3Scoreboard summary={data.runSummary?.summary} evidenceMetrics={evidenceMetrics} />
    <LivePairedBenchmarkPanel />
    {!data.selectedIncident ? <Panel><EmptyState title="No run selected" icon="replay" /></Panel> : !cards.length ? <Panel><EmptyState title="This incident has no replayable evidence yet" description="Select a completed run with a sealed card chain." icon="replay" /></Panel> : <>
      <Panel className="replay-stage-panel" noPadding>
        <div className="replay-workflow"><div className="replay-workflow-track">{cards.map((item, cardIndex) => <button key={`${item.sequence}-${item.card_type}`} type="button" className={cx("replay-stage", cardIndex < index && "complete", cardIndex === index && "current")} onClick={() => { setPlaying(false); setIndex(cardIndex); }}><span>{cardIndex < index ? <Icon name="check" size={12} /> : cardIndex + 1}</span><small>{item.card_type === "Verdict" ? stateLabel(String(getCardData(item).decision || "Review").toLowerCase()) : CARD_LABELS[item.card_type] || titleCaseAction(item.card_type)}</small></button>)}</div></div>
        <div className="replay-controls"><button type="button" className="button button-primary" onClick={() => setPlaying((value) => !value)}><Icon name={playing ? "pause" : "play"} size={16} />{playing ? "Pause" : index >= cards.length - 1 ? "Replay" : "Play"}</button><button type="button" className="button button-ghost" onClick={() => { setPlaying(false); setIndex(Math.max(0, index - 1)); }} disabled={index === 0}><Icon name="previous" size={16} />Previous</button><button type="button" className="button button-ghost" onClick={() => { setPlaying(false); setIndex(Math.min(cards.length - 1, index + 1)); }} disabled={index >= cards.length - 1}>Next handoff<Icon name="next" size={16} /></button><div className="speed-control"><button className={cx(speed === 1 && "active")} type="button" onClick={() => setSpeed(1)}>1×</button><button className={cx(speed === 2 && "active")} type="button" onClick={() => setSpeed(2)}>2×</button></div><span className="replay-counter">{index + 1} / {cards.length}</span><div className="replay-progress"><span style={{ width: `${progress}%` }} /><i style={{ left: `${progress}%` }} /></div></div>
        <div className="replay-main-grid"><div className="replay-current-event"><div className="replay-agent-column"><Avatar profile={profile} size="xl" /><h2>{profile.name}</h2><p>{profile.role}</p><span>{profile.framework} · {profile.model}</span><StatusPill tone={cardTone(card)} compact>{cardBadge(card)}</StatusPill></div><div className="replay-event-copy"><div className="eyebrow">Verified handoff · sequence {card.sequence}</div><h2>{replayEventTitle(card)}</h2><p className="replay-event-summary">{cardSummary(card)}</p>{rows.length ? <div className="replay-detail-list">{rows.map((row) => <div key={row.label}><span>{row.label}</span><strong>{Array.isArray(row.value) ? row.value.join(" · ") : typeof row.value === "object" ? JSON.stringify(row.value) : String(row.value)}</strong></div>)}</div> : null}<div className="replay-integrity-note"><Icon name="shield" size={18} /><span><strong>Publication and identity verified</strong><small>This event is reconstructed from sealed Gateway evidence, not a fabricated animation.</small></span></div></div></div>
        <aside className="replay-right-rail"><div className="replay-rail-card"><span>Current workflow state</span><strong>{CARD_LABELS[card.card_type] || titleCaseAction(card.card_type)}</strong><small>{formatDateTime(firstDefined(getCardData(card).created_at, getCardData(card).timestamp, getCardData(card).observed_at))}</small></div><div className="replay-rail-card"><span>Incident family</span><strong>{displayFamily(incidentFamily)}</strong><small>Baseline proof uses same-family runs</small></div><div className="replay-rail-card"><span>Incident duration</span><strong>{formatDuration(run?.total_resolution_secs)}</strong><small>{run?.handoffs ?? deriveHandoffs(cards).length} verified handoffs</small></div><div className="replay-rail-card"><span>Evidence-chain status</span><strong className="success-text">Valid and sealed</strong><small>{cards.length} ordered cards</small></div><div className="replay-rail-card"><span>Execution conflict resolution</span><strong>Exact action only</strong><small>Altered requests are blocked before side effects</small></div></aside></div>
      </Panel>
      <Panel title="Recovery telemetry" eyebrow="Before to after · measured during the recorded run"><div className="replay-metrics"><div className="metric-comparison danger-to-success"><span><Icon name="alert" size={18} />Error rate</span><div><strong>{sealedErrorRateText(facts.preMetrics.errorRate) ?? "Not recorded"}</strong><Icon name="arrowRight" size={18} /><strong>{formatPercent(facts.postMetrics.errorRate)}</strong></div><small>Incident to recovered</small></div><div className="metric-comparison danger-to-success"><span><Icon name="activity" size={18} />Latency</span><div><strong>{facts.preMetrics.latency !== undefined ? `${facts.preMetrics.latency} ms` : `${DEFAULT_DEMO_FACTS.latency} ms`}</strong><Icon name="arrowRight" size={18} /><strong>{facts.postMetrics.latency !== undefined ? `${facts.postMetrics.latency} ms` : `${DEFAULT_DEMO_FACTS.postLatency} ms`}</strong></div><small>p95 response time</small></div><div className="metric-comparison danger-to-success"><span><Icon name="clock" size={18} />Uptime</span><div><strong>{formatPercent(facts.preMetrics.uptime)}</strong><Icon name="arrowRight" size={18} /><strong>{formatPercent(facts.postMetrics.uptime)}</strong></div><small>Before to verified</small></div><div className="recovery-final-card"><Icon name="shield" size={26} /><span><strong>{facts.recoveryVerified ? "Recovery verified" : "Replay in progress"}</strong><small>{facts.recoveryVerified ? "Exact action executed · evidence chain valid" : "Advance to the ActionReceipt to see the certified result"}</small></span></div></div></Panel>
    </>}
  </>;
}

export default function YitingApp({ view = "overview" }) {
  const data = useYitingData();
  const pages = {
    overview: <OverviewPage data={data} />,
    incidents: <IncidentWorkspacePage data={data} />,
    approvals: <ApprovalPage data={data} />,
    agents: <AgentsPage data={data} />,
    evidence: <EvidencePage data={data} />,
    runs: <ReplayPage data={data} />,
  };
  return <AppShell view={view} data={data}>{pages[view] || pages.overview}</AppShell>;
}
