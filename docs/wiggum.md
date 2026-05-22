# Wiggum

`wiggum.py` is a meta-loop orchestrator. It sits above `loop.py` and handles multi-job goals.

## What it does

1. Takes a goal string.
2. Calls `goal_plan` to decompose the goal into a list of discrete jobs (a manifest).
3. Runs each job as a separate `loop.py` call with a context prefix that re-anchors the model to the goal on every turn.
4. Tracks progress in `CHECKLIST.md`.
5. Marks jobs done or stuck via `goal_check`.

## The wiggum context prefix

Every turn of every job, the loop receives:

```
[WIGGUM-CONTEXT]
GOAL:  <original goal>
JOB:   <job id> — <job title>
STEP:  <current step>/<max turns>
DONE:  <jobs completed>/<total jobs>
LAST:  <compressed context from previous turns>
[/WIGGUM-CONTEXT]
```

This prefix is prepended to the normal context (TOPO, IDENTITY, TOOLS, STATE). Its purpose is to prevent drift — the model cannot forget what it is doing because the goal is re-stated every single turn.

## Manifest

A manifest is a JSON file in `runtime/manifests/` describing the jobs for a goal. If you pass `--manifest` to wiggum, it skips goal decomposition and runs the pre-built manifest. Useful for repeatable workflows.

## Usage

```bash
# From a goal
python wiggum.py "Apply for 3 Python developer jobs on Indeed"

# From a pre-built manifest
python wiggum.py --manifest runtime/manifests/abc123.json

# Via scheduled task (set wiggum=true in scheduled_tasks.json)
python run_task.py <task_id>
```

## Relationship to loop.py

Wiggum calls `loop.loop()` internally. It does not replace the loop — it orchestrates multiple loop runs. The stuck detection, STATE.md management, and grammar constraints all operate normally inside each job.
