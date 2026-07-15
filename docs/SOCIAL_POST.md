# YITING — social posts (Blog Post Prize companion)

Fill the bracketed URLs after publication. Every number below is backed by
`artifacts/track3-paired-benchmark.json` in the repository.

## X / Twitter — variant A (result angle)

> Do multiple agents actually beat one? We put it on the record for the Qwen Cloud hackathon.
>
> Live on Alibaba ECS: 3 incidents executed with verified recovery, 22 sealed agent handoffs, a safety challenge and a human rejection forcing revised plans — 2.6x faster than our measured human baseline.
>
> Our deterministic society-contract regression harness (contract validation, not live model measurement) adds: 100% vs 33% task success · 0 vs 20 unsupported claims · 3x the risks surfaced.
>
> [BLOG URL]

## X / Twitter — variant B (design angle)

> Most multi-agent demos are group chats. YITING's agents disagree on the record: challenges and human rejections are sealed, hash-linked evidence cards that force revision before anything executes.
>
> Built on Qwen Cloud + Alibaba ECS.
>
> [BLOG URL]

## LinkedIn

> **An agent society with deterministic safety rails.**
>
> For the Global AI Hackathon Series with Qwen Cloud (Track 3: Agent Society), we built YITING — an evidence-bound incident council where six specialized Qwen agents divide emergency-response work, challenge weak reasoning, and negotiate with a human before anything executes.
>
> What makes it a society rather than a group chat:
>
> - Each role ships as an inspectable MCP-style skill contract at `/agent-skills` — inputs, outputs, guardrails, and the evidence artifact it must produce.
> - Disagreement is a product primitive: a safety challenge or a human rejection is a sealed evidence card that forces a revised plan and a fresh authorization nonce.
> - The Gateway owns authority: exact action envelopes, hash-chained evidence, and recovery verification — agents advise, deterministic code decides.
>
> And the Track 3 question — is the society measurably better than one agent? We ran it live: 20 real incidents on the deployed stack, each handled by a single Qwen agent AND by the six-agent society — same model tier, same evidence, frozen rubric. **Society 0.844 vs solo 0.763 — 10 wins, 4 ties, 6 losses — with 100% finding and risk recall and every plan sealed with a live-verified evidence chain** (`artifacts/track3-live-paired/`). The eval caught a real routing bug; we fixed it, redeployed, and revalidated the same day: **0.968 vs 0.843, five wins, two ties, zero losses** (`artifacts/track3-live-paired-postfix/`). Also live on the dashboard: 3 executed incidents with verified recovery, 22 sealed handoffs, challenges and human rejections that forced revised plans, and **2.6x the speed of our measured human baseline** (501 s runbook-guided solo vs 196 s same-family council average). Our deterministic society-contract regression harness — reproducible contract validation, not a live model measurement — adds **100% vs 33.33% task success, 0 vs 20 unsupported claims, 120 vs 40 risks surfaced** on the same 20 scenarios. We publish the society's ~2.5× token cost too; honest numbers are the whole point of evidence-bound design.
>
> Runs live on Alibaba Cloud ECS with Qwen Cloud models end to end.
>
> Blog: [BLOG URL]
> Live app: https://yiting.47.84.232.193.sslip.io/
> Code: [REPO URL]
>
> #QwenCloud #AlibabaCloud #AIAgents #MultiAgent #AgentSociety #SRE #IncidentResponse #Hackathon

## Hashtags pool

`#QwenCloud #AlibabaCloud #Qwen #AIAgents #MultiAgent #AgentSociety #IncidentResponse #LLM #Hackathon`
