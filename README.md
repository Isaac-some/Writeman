# Writeman

Writeman is a concrete work-agent instance for weekly requirement maintenance and iteration-demo preparation. It is published separately from the TodoBoard framework so its role, procedures, and media workflow can evolve on their own.

## What it does

- Reviews owned or explicitly accepted work using configured task, meeting, and document sources.
- Separates verified progress from plans and asks before changing business records.
- Prepares a weekly iteration summary and optional narrated demo video.
- Verifies remote media delivery before recording a cleanup receipt. Source recordings are considered for cleanup only in a later run and only after remote verification succeeds.

TodoBoard remains the user's task board. A task card starts a workflow; Writeman does not change its formal status.

## Setup

Requirements depend on the workflow used: Python 3.12, Codex, the relevant local skills, lark-cli, OpenViking access, FFmpeg, Blurt, and OpenScreen. External services and local permissions must be checked in the actual environment.

1. Copy config/writeman.example.json to config/writeman.local.json.
2. Add only the source IDs and settings for your own environment to the local file. Configure business-area precedence rules for the user's own work; the local file is ignored by Git.
3. Install the skills named by agent.json and configure their access using the official tools for your environment.
4. Read AGENTS.md and execution.md before connecting real sources.
5. Run the offline tests with python3 -m unittest discover -s scripts -p 'test_*.py' -v.
6. Review the rules in config/writeman.example.json and supply the operator's business-area priorities in the ignored local configuration.

scripts/check-feishu-access.py --config config/writeman.local.json performs read-only permission checks. scripts/media-lifecycle.py cleanup --config config/writeman.local.json is a dry run; cleanup --apply can remove only files tied to a verified delivery receipt. Review the receipt and target paths before enabling that workflow.

## Configuration boundary

The repository contains no personal work records, source URLs, tenant identifiers, credentials, or verification captures. Keep local IDs and paths in config/writeman.local.json or environment variables. Never commit task exports, meeting transcripts, recordings, delivery receipts, or verification output.

The public example intentionally leaves resource IDs empty. Writeman must not claim a source is connected until the local user has configured and verified it.
