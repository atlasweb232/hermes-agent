---
name: git-actions
description: Use when performing authenticated Git/GitHub repo actions with git, gh, jq, rg, fd, and eza/exa while keeping credentials in environment variables only.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [git, github, gh, credentials, repo-work, atlas]
    related_skills: [github-auth, github-pr-workflow, github-repo-management]
---

# Git Actions

## Overview

Use this skill for authenticated Git and GitHub repository work. It standardizes how to detect credentials, prefer `gh` when available, fall back to `git`/`curl`, and use local repo utilities like `eza`/`exa`, `rg`, `fd`, and `jq`.

Secrets must never be embedded in this skill, committed to a repo, printed, or placed directly in command lines. GitHub tokens must come from environment/config only, normally `GITHUB_TOKEN` or `GH_TOKEN` loaded from the Hermes `.env` file.

## When to Use

Use when the task involves:

- Checking repository state, branches, remotes, diffs, or logs.
- Creating commits, branches, tags, PRs, issues, or releases.
- Calling the GitHub API.
- Using repo navigation utilities: `eza`/`exa`, `rg`, `fd`, `jq`.
- Verifying GitHub authentication before push/API work.

Do not use for:

- Non-Git filesystem edits with no repo interaction.
- Storing or rotating credentials manually outside Hermes `.env`.
- Printing tokens for debugging.

## Credential Policy

Credentials are environment-only:

- Primary: `GITHUB_TOKEN`
- Alternate: `GH_TOKEN`
- Storage location: Hermes `.env`, e.g. `~/.hermes/.env`
- File permissions: `chmod 600 ~/.hermes/.env`

Never:

- Put tokens in `SKILL.md`.
- Put tokens in git remotes.
- Put tokens in shell history or command arguments.
- Print token values.
- Commit `.env` or credential files.

## Preflight

Run these checks before authenticated work:

```bash
git --version
gh --version 2>/dev/null || true
jq --version 2>/dev/null || true
rg --version 2>/dev/null || true
fd --version 2>/dev/null || fdfind --version 2>/dev/null || true
eza --version 2>/dev/null || exa --version 2>/dev/null || true
```

Check token presence without printing values:

```bash
python3 - <<'PY'
import os
print('GITHUB_TOKEN present:', bool(os.getenv('GITHUB_TOKEN')))
print('GH_TOKEN present:', bool(os.getenv('GH_TOKEN')))
PY
```

If Hermes has not loaded `.env` in the current process, load it in a subshell without printing values:

```bash
set -a
[ -f ~/.hermes/.env ] && . ~/.hermes/.env
set +a
```

## Authentication Decision Tree

1. If `gh auth status` succeeds, use `gh`.
2. Else if `GH_TOKEN` or `GITHUB_TOKEN` is present, use `gh` with token env or `curl`.
3. Else if git credential helper is already configured, use `git` HTTPS operations.
4. Else stop and ask the user to configure GitHub auth.

Safe check:

```bash
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo AUTH_METHOD=gh
elif [ -n "${GH_TOKEN:-${GITHUB_TOKEN:-}}" ]; then
  echo AUTH_METHOD=token-env
else
  echo AUTH_METHOD=none
fi
```

## Common Commands

Repository overview:

```bash
git status --short
git branch --show-current
git log --oneline --decorate -n 12
git remote -v
```

Diff review:

```bash
git diff --stat
git diff --check
git diff -- path/to/file
```

Commit:

```bash
git add <paths>
git commit -m "type: concise subject"
```

Push current branch:

```bash
git push -u origin HEAD
```

Create PR with `gh`:

```bash
gh pr create --title "type: concise subject" --body "Summary and test plan"
```

GitHub API with token env:

```bash
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
curl -fsS -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" https://api.github.com/user | jq .login
```

## Repo Utility Usage

Prefer safe, readable utilities when available:

```bash
eza -la --git 2>/dev/null || exa -la --git 2>/dev/null || ls -la
rg "pattern" path/
fd "filename-or-regex" path/
jq . file.json
```

Use these as machine dependencies only. They are not credential stores.

## Verification Checklist

- [ ] `git status --short` reviewed before edits/commit.
- [ ] Auth method detected without printing secrets.
- [ ] Tokens sourced only from `GITHUB_TOKEN`/`GH_TOKEN` env/config.
- [ ] `git diff --check` passed before commit.
- [ ] Focused tests or relevant validation ran.
- [ ] Commit message is clear.
- [ ] No `.env`, token, or credential material staged.

## Common Pitfalls

1. Printing secrets while debugging. Only print presence booleans.
2. Embedding tokens in remote URLs. Prefer env vars, `gh auth`, or credential helpers.
3. Forgetting `git diff --check` before commit.
4. Assuming `fd` binary name is always `fd`; Debian/Ubuntu may install it as `fdfind`.
5. Assuming `eza` exists; fall back to `exa` or `ls`.
