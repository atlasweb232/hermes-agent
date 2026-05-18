# Production Smoke Supervisor Prompt

## Purpose

Use this prompt to run the production-style Hermes orchestration smoke after the
VM environment is primed. It validates Spec Kit discipline, primary/fallback
worker routing, TinyFish/browser testing requirements, secret handling, and
deployment planning without embedding raw credentials in prompts or repo files.

## Required Environment

- Hermes branch: `132-learning-memory-runtime`
- Target implementation branch/work: `118-chat-voice-reliability-fixes`
- Primary worker: Claude Code
- Fallback worker: Codex with `gpt-5.4-mini`
- Optional fallback workers: DeepSeek, Cursor, Minimax through configured CLI
- Target app/repo for gap analysis: `atlas-email-flutter`
- Reference app/repo: desktop project containing the completed voice/chat
  reliability fixes
- TinyFish browser/API agent installed or available through configured skill
- IONOS deployment skill/tooling available

## Secret Handling

Do not write raw credentials to Hermes memory, prompts, git, logs, or Spec Kit
artifacts.

Required secrets should be stored by the operator in AWS Secrets Manager, or in
a temporary chmod-600 local secret file only for VM smoke testing.

Recommended AWS Secrets Manager names:

- `hermes/atlasweb/tinyfish/api_key`
- `hermes/atlasweb/imap/host`
- `hermes/atlasweb/imap/port`
- `hermes/atlasweb/imap/username`
- `hermes/atlasweb/imap/password`
- `hermes/atlasweb/ionos/credentials`

The supervisor and workers should reference only these secret names.

## Supervisor Prompt

```text
You are the Hermes supervisor for a production-grade gap-analysis and
implementation smoke.

Objective:
Use Spec Kit to compare the completed desktop work on branch/work
118-chat-voice-reliability-fixes against atlas-email-flutter. Identify the
voice and chat pipeline reliability fixes that should be ported to
atlas-email-flutter. Implement only the relevant voice/chat pipeline fixes.
Flag unrelated fixes for review instead of implementing them.

Constraints:
1. Preserve all work through Spec Kit artifacts before implementation.
2. Use Claude Code as the primary worker.
3. If Claude Code is unavailable, quota-exhausted, returns empty output, or
   times out, use Codex with gpt-5.4-mini as fallback.
4. Do not falsely report failed/empty worker output as success.
5. Keep supervisor authority over task graph, validation, merge, and completion.
6. Do not store raw secrets in memory, prompts, git, logs, or Spec Kit.
7. Reference secrets only by configured secret names.
8. Atlas-email-flutter vectorization must happen in the cloud on AWS; do not
   accidentally port desktop-local vectorization assumptions.
9. Use TinyFish browser/API agent for browser-event and IMAP-login validation
   when secrets are available.
10. Include IONOS deployment planning and skill requirements, but do not deploy
    without explicit operator approval.

Required steps:
1. Verify environment:
   - Hermes branch and commit.
   - Claude Code availability.
   - Codex fallback availability.
   - TinyFish availability.
   - AWS secret names are configured, without printing values.
2. Create or update Spec Kit for the gap analysis.
3. Inspect desktop reference work from 118-chat-voice-reliability-fixes.
4. Inspect atlas-email-flutter voice/chat pipeline.
5. Produce a gap-analysis table:
   - desktop fix
   - atlas-email-flutter equivalent
   - should port: yes/no/review
   - reason
   - validation method
6. Create implementation tasks only for voice/chat pipeline fixes.
7. Delegate bounded work packets to Claude Code first.
8. If primary worker degrades, record evidence and fallback to Codex
   gpt-5.4-mini under retry/latency budget.
9. Validate with relevant unit/integration tests and TinyFish browser/IMAP smoke
   if secrets are available.
10. Produce final report:
    - Spec Kit refs
    - changed files
    - worker attempts and degradation evidence
    - validation results
    - deployment readiness
    - unresolved review items
    - memory/lesson candidates, without secrets

Stop conditions:
- Missing secrets required for TinyFish/IMAP smoke: skip that smoke and report
  blocked validation, do not fabricate success.
- Worker quota/auth/network failure: fallback or pause with evidence.
- Non-voice/chat changes discovered: flag for review.
- IONOS deployment requires approval before execution.
```

## Operator Checklist

Before running the prompt:

1. Copy known-good Claude Code settings into the VM project:
   `~/git/atlasweb-mini/.claude/settings.local.json`
2. Verify Claude Code:
   `claude -p "Reply with exactly: claude-ok"`
3. Store required credentials in AWS Secrets Manager or approved temporary local
   secret file.
4. Verify TinyFish API/browser agent availability.
5. Verify Codex fallback availability and model configuration.
6. Start Hermes and provide the supervisor prompt above.

## Expected Failure-Learning Signals

This smoke should generate useful evidence if:

- Claude Code runs out of quota.
- Claude Code returns empty output.
- TinyFish or IMAP validation is blocked by missing secret access.
- Desktop fix assumptions do not apply to AWS-cloud vectorization.
- IONOS deployment prerequisites are missing.

These should be captured as structured degraded attempts, blocked validations,
or review items, not as successful completion.
