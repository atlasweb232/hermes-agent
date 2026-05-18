# Azure VM Recovery Contract

## Purpose

Define the first recovery environment that replaces the lost AWS VM without
waiting for the full Container Apps migration.

## VM Baseline

Recommended initial VM:

- Ubuntu 24.04 LTS
- East US unless operator chooses otherwise
- 4 vCPU / 16 GB RAM if available
- 128 GB OS disk minimum
- SSH restricted to operator IP where possible
- Managed identity enabled if using Key Vault

## Bootstrap Steps

1. Install base packages: git, curl, build-essential, python3-venv, pipx,
   Docker, ripgrep.
2. Clone Hermes repo.
3. Checkout `132-learning-memory-runtime` or migration branch as instructed.
4. Create Python venv and install package requirements.
5. Install Hermes CLI from repo.
6. Configure Codex manually by operator.
7. Copy known-good Claude Code settings from local project.
8. Install TinyFish SDK into Hermes venv.
9. Configure secrets through Key Vault or temporary chmod-600 env.
10. Run runtime smoke and doctor checks.

## Required Smoke

```bash
venv/bin/python -m hermes_cli.main runtime smoke compare --no-upstream --json
claude -p "Reply with exactly: claude-ok"
venv/bin/python -m hermes_cli.doctor | grep -A5 TinyFish
venv/bin/python -m hermes_cli.main runtime secrets check --json
```

## Teardown

Every VM deployment script must document:

- resource group name
- VM name
- public IP name
- disk name
- teardown command

## Security

- No raw secret values in scripts.
- SSH key auth preferred after initial recovery.
- Password SSH must be disabled before production use.
- Key Vault preferred for any persistent secret.
