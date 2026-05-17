Worker delegation packet:

Required fields:
- repo
- branch or worktree
- objective
- owned files
- constraints
- validation commands
- advisory memory packet
- return schema

Rules:
- Do not modify files outside owned scope.
- Do not revert unrelated changes.
- Return blockers instead of guessing.

