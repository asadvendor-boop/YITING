# YITING Dashboard

Real-time incident monitoring, evidence-chain inspection, human approval, and ChaosPanel controls for the YITING system.

## Stack

- **Framework:** Next.js App Router
- **Styling:** Custom CSS with glassmorphism and particle background
- **Base Path:** `/dashboard`

## Features

- Live incident feed with state transitions and card chains
- Agent heartbeat status with online/offline indicators
- Evidence-chain verification and audit export
- Human approval shortcuts for planned incidents
- Suppression rule visibility
- ChaosPanel for controlled sandbox scenarios

## Development

```bash
npm install
npm run dev
# Open http://localhost:3000/dashboard
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `NEXT_PUBLIC_GATEWAY_URL` | Gateway API base URL | `http://localhost:8000` |
| `VICTIM_APP_URL` | Victim-app URL, server-side only | `http://127.0.0.1:9000` |
| `YITING_LIVE_CHAOS` | Enables live chaos triggers when set to `1` | unset |
