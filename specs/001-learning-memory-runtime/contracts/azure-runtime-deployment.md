# Hermes Azure Runtime Deployment Contract

## Purpose

The Hermes runtime learning, allocator, degradation, memory, goal-loop, and
observability work belongs to `132-learning-memory-runtime`. Azure migration
infrastructure may live in a separate IaC repository or migration branch, but the
runtime behavior being deployed and tested must remain traceable to this branch.

## Source Of Truth

- Runtime repo on Azure VM: `/home/rakib/git/hermes-agent`
- Runtime branch: `132-learning-memory-runtime`
- Runtime wrapper: `/usr/local/bin/hermes`
- Runtime entrypoint: `/home/rakib/git/hermes-agent/venv/bin/python -m hermes_cli.main`
- Upstream comparison checkout: `/home/rakib/git/hermes-agent-upstream`

## Required Azure VM Capabilities

The recovery VM must provide:

- Python 3.11+ virtualenv for Hermes.
- Node.js 22+ for Claude Code and browser/tooling dependencies.
- Docker for local supporting services and future sidecar/container tests.
- `claude` configured per project through the target repo `.claude/` directory.
- `hermes` globally invokable but resolved through the branch venv wrapper.
- A separate upstream Hermes checkout for behavior comparison.
- Persistent `~/.hermes/` state across SSH sessions.
- User-level systemd gateway service with linger enabled for Slack/Telegram.

## Runtime Tests On Azure

The Azure runtime is not considered ready until these pass:

1. `hermes --version` reports the branch version and venv Python.
2. `hermes status` reports configured gateway/provider state without crashing.
3. A project-local Claude Code command succeeds from the target repo directory.
4. Slack or Telegram gateway runs under `systemd --user` and survives SSH logout.
5. Worker degradation smoke records empty/timeout/degraded worker evidence.
6. Goal-loop smoke can pause, resume, stop, and inspect persisted goal state.
7. Allocation observability captures selected worker, failure reason, fallback,
   retry budget, and final validation status.

## Boundary With Azure Migration Spec

Azure VM/IaC concerns are deployment concerns. They must not redefine Hermes
runtime behavior. Runtime changes must be made on `132-learning-memory-runtime`
or a child branch that explicitly merges back into `132`.

Azure migration artifacts may reference this contract but should not become the
source of truth for:

- worker allocator semantics
- memory retrieval/injection semantics
- learning sidecar promotion rules
- goal-loop convergence rules
- supervisor degradation gates

## Secret Discipline

Runtime secrets must be configured through environment files, OS secret stores,
or Azure Key Vault references. They must not be stored in Spec Kit artifacts,
Terraform state committed to git, Slack manifests, prompt templates, memory wiki
claims, learning candidates, or architecture docs.
