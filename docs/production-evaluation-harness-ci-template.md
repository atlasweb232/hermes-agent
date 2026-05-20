# Production Evaluation Harness CI Template

This is a safe template for wiring the Phase 14 benchmark harness into CI. It is
not an active GitHub Actions workflow. Copy it into `.github/workflows/` only
after choosing artifact storage, Slack routing, and live provider credentials.

## Pull Request Smoke

Use deterministic fixture mode on every pull request. This mode must not contact
providers, Azure, Slack, or external object storage.

```yaml
name: runtime-benchmark-smoke

on:
  pull_request:

jobs:
  deterministic-smoke:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@<pin-commit-sha> # v4
      - uses: actions/setup-python@<pin-commit-sha> # v5
        with:
          python-version: "3.11"
      - name: Install test dependencies
        run: python -m pip install -e ".[dev]"
      - name: Run deterministic benchmark smoke
        run: |
          PYTHONPATH="$PWD" python -m hermes_cli.main runtime benchmark run \
            --suite specs/001-learning-memory-runtime/fixtures/phase14-smoke.json \
            --artifact-root "$RUNNER_TEMP/hermes-runtime-benchmark" \
            --json
      - name: Check Azure smoke fixture status
        run: |
          PYTHONPATH="$PWD" python -m hermes_cli.main runtime benchmark azure-smoke --json
```

## Scheduled Or Operator-Triggered Full Benchmark

Use full command/provider execution only on scheduled or manual runs. Keep live
credentials in CI secrets, keep urgent Slack delivery explicit, and upload only
bounded benchmark artifacts.

```yaml
name: runtime-benchmark-full

on:
  workflow_dispatch:
    inputs:
      send_urgent_alerts:
        type: boolean
        default: false
  schedule:
    - cron: "0 9 * * 1"

jobs:
  full-benchmark:
    runs-on: ubuntu-latest
    timeout-minutes: 240
    env:
      SLACK_URGENT_CHANNEL: ${{ secrets.SLACK_URGENT_CHANNEL }}
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      AZURE_SUBSCRIPTION_ID: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      AZURE_RESOURCE_GROUP: ${{ secrets.AZURE_RESOURCE_GROUP }}
      AZURE_VM_NAME: ${{ secrets.AZURE_VM_NAME }}
      HERMES_AZURE_LIVE_SMOKE: "1"
    steps:
      - uses: actions/checkout@<pin-commit-sha> # v4
      - uses: actions/setup-python@<pin-commit-sha> # v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: python -m pip install -e ".[dev]"
      - name: Run opt-in long-horizon benchmark
        run: |
          ALERT_FLAG=""
          if [ "${{ inputs.send_urgent_alerts }}" = "true" ]; then
            ALERT_FLAG="--send-urgent-alerts"
          fi
          PYTHONPATH="$PWD" python -m hermes_cli.main runtime benchmark run \
            --suite specs/001-learning-memory-runtime/fixtures/phase14-long-horizon.json \
            --artifact-root "$RUNNER_TEMP/hermes-runtime-benchmark" \
            --execution-mode command \
            --upstream-command "./scripts/run_tests.sh tests/hermes_cli/test_runtime_benchmark.py -q -o addopts=" \
            --branch-command "./scripts/run_tests.sh tests/hermes_cli/test_runtime_benchmark.py -q -o addopts=" \
            $ALERT_FLAG \
            --json
      - name: Record Azure live-smoke readiness
        run: |
          PYTHONPATH="$PWD" python -m hermes_cli.main runtime benchmark azure-smoke --live --json
```

## Guardrails

- Pull request jobs use fixture mode only.
- Live Azure/provider execution is schedule/manual only and opt-in.
- Urgent Slack delivery requires both `--send-urgent-alerts` and configured
  `SLACK_URGENT_CHANNEL`; dry runs do not count as delivered alerts.
- Upload `run.json`, `report.json`, and `telemetry.jsonl` only after confirming
  they contain bounded structured records and no raw transcripts or secrets.
- Sidecar enforcement remains disabled; benchmark sidecars are advisory-only.
