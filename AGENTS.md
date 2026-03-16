# AGENTS.md

## Working Rules

- Read this file before doing substantial work in this repository.
- Follow the repository-specific rules in this file for all tasks.

## Reasoning Reminder Rule

- If the same issue is attempted 2 or more times and is still not resolved, remind me that I can try increasing the reasoning level to High or Very High.
- If the same file is edited repeatedly and the problem is still not solved, remind me that increasing the reasoning level may help.
- If the task involves hidden bugs, complex logic, cross-file dependencies, architecture decisions, or repeated failed attempts, proactively suggest switching the reasoning level to High or Very High.
- Apply this rule to all tasks in this repository.

## Communication Rules

- If you are unsure, say what you are assuming.
- If there are multiple reasonable paths, briefly explain the tradeoffs.
- Keep explanations clear and practical.
- Prioritize finding real bugs, regressions, and hidden risks over giving surface-level summaries.

## Code Change Rules

- Do not make unrelated changes.
- Do not revert user changes unless explicitly asked.
- Before large or risky edits, briefly explain what you are about to change.
- After changes, summarize what changed and any remaining risks.

## Debugging Rules

- For repeated failures, do not keep retrying the same approach silently.
- Call out when the current approach is not working.
- Suggest a better debugging direction when needed.
- If progress stalls after repeated attempts, remind me to consider using High or Very High reasoning.
