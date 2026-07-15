import { NextResponse } from "next/server";

/**
 * Server-side proxy for controlled demo scenarios. Every non-reset scenario
 * goes through Gateway so it creates an incident room, seals an AlertCard, and
 * starts the complete agent pipeline. The browser never calls victim-app.
 */
const SCENARIO_TYPES = new Set([
  "deploy",
  "sentry",
  "latency",
  "db",
  "memory",
  "cert",
  "reset",
]);

async function readGatewayResponse(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { error: "Gateway returned an invalid response" };
  }
}

function operatorTokenFrom(request) {
  const authorization = request.headers.get("authorization") || "";
  if (authorization.toLowerCase().startsWith("bearer ")) {
    return authorization.slice(7);
  }
  return request.headers.get("x-operator-token") || "";
}

export async function POST(request) {
  const gatewayUrl = process.env.GATEWAY_URL || "http://127.0.0.1:8000";

  try {
    const body = await request.json();
    const scenarioType = String(body?.scenario_type || "").trim().toLowerCase();
    if (!SCENARIO_TYPES.has(scenarioType)) {
      return NextResponse.json(
        {
          error: `Unknown scenario_type: ${scenarioType || "(missing)"}. Allowed: ${Array.from(SCENARIO_TYPES).join(", ")}`,
        },
        { status: 400 }
      );
    }

    if (process.env.YITING_LIVE_CHAOS !== "1") {
      return NextResponse.json(
        { error: "Live chaos actions are disabled for this deployment." },
        { status: 403 }
      );
    }

    const operatorToken = process.env.YITING_OPERATOR_TOKEN || "";
    if (!operatorToken) {
      return NextResponse.json(
        { error: "YITING_OPERATOR_TOKEN is not configured." },
        { status: 503 }
      );
    }
    if (operatorTokenFrom(request) !== operatorToken) {
      return NextResponse.json(
        { error: "Valid operator token is required." },
        { status: 401 }
      );
    }

    const endpoint = scenarioType === "reset" ? "/chaos/reset" : "/chaos/trigger";
    const gatewayBody = scenarioType === "reset" ? {} : { scenario_type: scenarioType };
    const response = await fetch(`${gatewayUrl}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Operator-Token": operatorToken },
      body: JSON.stringify(gatewayBody),
      cache: "no-store",
    });
    const data = await readGatewayResponse(response);
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json(
      { error: "Failed to reach the YITING Gateway" },
      { status: 502 }
    );
  }
}
