# Scheduler

`scheduler.py` is a cron-based autonomous task daemon. It polls every 60 seconds, fires any due tasks, and updates their next run time.

## What it is

A prompt injection on a timer. There is no special agent machinery — when a task is due, it calls `loop.loop()` or `wiggum.run()` with the task's prompt string. The model runs the task, tools execute, results are logged.

## scheduled_tasks.json

Located at `runtime/scheduled_tasks.json`. Each entry:

```json
{
  "id": "unique-task-id",
  "name": "Human readable name",
  "prompt": "The prompt the agent will receive",
  "cron": "0 9 * * 1-5",
  "enabled": true,
  "max_turns": 30,
  "wiggum": false,
  "next_run": "2026-01-01T09:00:00+00:00"
}
```

- `wiggum: true` routes through `wiggum.run()` for multi-job goal decomposition.
- `wiggum: false` routes directly through `loop.loop()`.
- `next_run` is updated by the scheduler after each firing. If unset, the task will not fire until you set it or restart the scheduler.

## Stopping

Create the file `runtime/scheduler.stop`. The scheduler checks for this file on each tick and exits cleanly.

## Manual fire

```bash
python run_task.py                    # list all tasks
python run_task.py <task_id>          # fire immediately
python run_task.py <task_id> --dry-run  # print prompt, don't run
```

## Logging

Each fire, completion, and error is appended to `logs/scheduler.jsonl` and `logs/events.jsonl`. View with:

```bash
python logflow.py --sched
```
