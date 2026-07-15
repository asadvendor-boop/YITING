.PHONY: dev test smoke dashboard-build verify qwen-smoke track3-benchmark deploy-verify local-certify submission-audit submission-status uptime-monitoring app-restart-resilience docker-build-images docker-smoke-images submission-ready submission-finalize submission-package submission-proof deployment-env ecs-bootstrap

RUN ?= uv run
PYTHON ?= $(RUN) python -B
PYTEST ?= $(RUN) python -B -m pytest
UVICORN ?= $(RUN) uvicorn
NPM ?= npm
YITING_PYTHON_IMAGE_TAG ?= yiting-python:preflight
YITING_DASHBOARD_IMAGE_TAG ?= yiting-dashboard:preflight
YITING_DASHBOARD_BUILD_URL ?= https://track3.example.com
NEXT_PUBLIC_YITING_MODE ?= judge

dev:
	$(UVICORN) gateway.app:app --reload --host 127.0.0.1 --port 8000

test:
	YITING_TEST_MODE=true PYTHONPYCACHEPREFIX=/tmp/yiting-pycache $(PYTEST) tests/ -q

smoke:
	@echo "Running smoke tests..."
	YITING_TEST_MODE=true PYTHONPYCACHEPREFIX=/tmp/yiting-pycache $(PYTEST) tests/ -x -q
	@echo "Smoke tests complete"

dashboard-build:
	cd dashboard && $(NPM) run build

verify: test dashboard-build

qwen-smoke:
	$(PYTHON) scripts/qwen_smoke.py --output-json artifacts/qwen-smoke.json

track3-benchmark:
	$(PYTHON) scripts/track3_paired_benchmark.py

deploy-verify:
	$(PYTHON) scripts/verify_deployment.py

local-certify:
	$(PYTHON) scripts/local_certify.py

submission-audit:
	$(PYTHON) scripts/submission_audit.py

submission-status:
	$(PYTHON) scripts/submission_status.py

uptime-monitoring:
	$(PYTHON) scripts/uptime_monitoring.py \
		--yiting-url "$$YITING_LIVE_URL" \
		--cotenant-url "$$COTENANT_LIVE_URL" \
		--yiting-monitor-url "$$YITING_UPTIME_MONITOR_URL" \
		--cotenant-monitor-url "$$COTENANT_UPTIME_MONITOR_URL"

app-restart-resilience:
	$(PYTHON) scripts/app_restart_resilience.py \
		--yiting-url "$$YITING_LIVE_URL" \
		--cotenant-url "$$COTENANT_LIVE_URL" \
		--yiting-state-path "$$YITING_STATE_PATH" \
		--yiting-evidence-path "$$YITING_EVIDENCE_PATH" \
		--yiting-logs-path "$$YITING_LOG_PATH" \
		--cotenant-state-path "$$COTENANT_STATE_PATH" \
		--cotenant-evidence-path "$$COTENANT_EVIDENCE_PATH" \
		--cotenant-logs-path "$$COTENANT_LOG_PATH"

docker-build-images:
	docker build -t "$(YITING_PYTHON_IMAGE_TAG)" .
	docker build -f dashboard/Dockerfile -t "$(YITING_DASHBOARD_IMAGE_TAG)" \
		--build-arg NEXT_PUBLIC_GATEWAY_URL="$(YITING_DASHBOARD_BUILD_URL)" \
		--build-arg NEXT_PUBLIC_YITING_MODE="$(NEXT_PUBLIC_YITING_MODE)" .

docker-smoke-images:
	$(PYTHON) scripts/docker_image_smoke.py \
		--python-image "$(YITING_PYTHON_IMAGE_TAG)" \
		--dashboard-image "$(YITING_DASHBOARD_IMAGE_TAG)"

submission-ready:
	$(MAKE) test
	$(MAKE) track3-benchmark
	$(MAKE) dashboard-build
	$(MAKE) local-certify
	$(MAKE) submission-package
	$(MAKE) submission-audit
	$(MAKE) submission-status

submission-finalize:
	@test -n "$(DOMAIN)" || (echo "DOMAIN is required, e.g. make submission-finalize DOMAIN=https://demo.example.com REPO_URL=https://github.com/owner/repo VIDEO_URL=https://youtu.be/id DEPLOYMENT_PROOF_VIDEO_URL=https://vimeo.com/id HERO_INCIDENT_ID=INC-..." && exit 2)
	@test -n "$(REPO_URL)" || (echo "REPO_URL is required" && exit 2)
	@test -n "$(VIDEO_URL)" || (echo "VIDEO_URL is required" && exit 2)
	@test -n "$(DEPLOYMENT_PROOF_VIDEO_URL)" || (echo "DEPLOYMENT_PROOF_VIDEO_URL is required" && exit 2)
	$(PYTHON) scripts/finalize_submission.py --domain "$(DOMAIN)" --repo-url "$(REPO_URL)" --video-url "$(VIDEO_URL)" --deployment-proof-video-url "$(DEPLOYMENT_PROOF_VIDEO_URL)" $(if $(HERO_INCIDENT_ID),--hero-incident-id "$(HERO_INCIDENT_ID)",)

submission-package:
	$(PYTHON) scripts/package_submission.py

submission-proof:
	@test -n "$(PUBLIC_BASE_URL)" || (echo "PUBLIC_BASE_URL is required, e.g. make submission-proof PUBLIC_BASE_URL=https://demo.example.com HERO_INCIDENT_ID=INC-... MEASURED_SINGLE_AGENT_SECS=240 BASELINE_INCIDENT_FAMILY='suspicious deploy'" && exit 2)
	@test -n "$(HERO_INCIDENT_ID)" || (echo "HERO_INCIDENT_ID is required" && exit 2)
	@test -n "$(MEASURED_SINGLE_AGENT_SECS)" || (echo "MEASURED_SINGLE_AGENT_SECS is required" && exit 2)
	@test -n "$(BASELINE_INCIDENT_FAMILY)" || (echo "BASELINE_INCIDENT_FAMILY is required, e.g. suspicious deploy, certificate expiry, latency spike" && exit 2)
	$(PYTHON) scripts/qwen_smoke.py --output-json artifacts/qwen-smoke.json
	$(PYTHON) scripts/track3_paired_benchmark.py --summary-json artifacts/track3-paired-benchmark.json --raw-json artifacts/track3-paired-benchmark-raw.json --raw-csv artifacts/track3-paired-benchmark.csv
	$(PYTHON) scripts/track3_baseline.py --gateway-url "$(PUBLIC_BASE_URL)" --baseline-secs "$(MEASURED_SINGLE_AGENT_SECS)" --baseline-label "Measured single-agent rehearsal" --incident-family "$(BASELINE_INCIDENT_FAMILY)" --output-json artifacts/track3-baseline.json
	$(PYTHON) scripts/verify_deployment.py --public-url "$(PUBLIC_BASE_URL)" --incident-id "$(HERO_INCIDENT_ID)" --require-speedup --require-public-read-only --output-json artifacts/deployment-verification.json
	$(PYTHON) scripts/final_proof_index.py --public-url "$(PUBLIC_BASE_URL)" --hero-incident-id "$(HERO_INCIDENT_ID)"
	$(PYTHON) scripts/submission_audit.py
	@echo "Proof artifacts generated. Next: commit artifacts/, run make submission-package, then run python scripts/submission_audit.py --strict."

deployment-env:
	@test -n "$(PUBLIC_BASE_URL)" || (echo "PUBLIC_BASE_URL is required, e.g. make deployment-env PUBLIC_BASE_URL=https://demo.example.com JUDGE_USER=judge JUDGE_PASSWORD='...' APPROVER_ID=human-1 DASHSCOPE_API_KEY='...'" && exit 2)
	@test -n "$(JUDGE_USER)" || (echo "JUDGE_USER is required" && exit 2)
	@test -n "$(JUDGE_PASSWORD)" || (echo "JUDGE_PASSWORD is required" && exit 2)
	@test -n "$(APPROVER_ID)" || (echo "APPROVER_ID is required" && exit 2)
	$(PYTHON) scripts/generate_deployment_env.py --public-base-url "$(PUBLIC_BASE_URL)" --judge-user "$(JUDGE_USER)" --judge-password "$(JUDGE_PASSWORD)" --approver-id "$(APPROVER_ID)" $(if $(DASHSCOPE_API_KEY),--dashscope-api-key "$(DASHSCOPE_API_KEY)",--qwen-api-key "$(QWEN_API_KEY)")

ecs-bootstrap:
	bash deploy/alibaba-ecs/bootstrap.sh
