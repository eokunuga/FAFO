#!/usr/bin/env python3
"""
Chief of Staff state manager.

Structured, deterministic storage for tasks / ideas / daily log so the
agent doesn't have to hand-maintain markdown state across sessions.

Data lives alongside this script (or pass --data-dir) in:
  tasks.json  ideas.json  log.json

Run with -h on any subcommand for its options.
"""

import argparse
import json
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

PRIORITIES = ["must", "should", "if_time"]
STATUSES = ["todo", "in_progress", "blocked", "done", "dropped"]
IDEA_CATEGORIES = ["ideas", "research", "career", "projects", "content", "insights", "someday"]


# ---------- storage ----------

def data_dir(args) -> Path:
    d = Path(args.data_dir) if args.data_dir else Path(__file__).parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(path: Path):
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def save(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def today() -> date:
    return date.today()


def parse_date(s):
    """Returns a date, or None if s is empty/missing/malformed (never raises)."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def valid_date(s):
    """argparse type= validator: reject bad --deadline/--new-deadline values up front."""
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{s}' is not a valid date — use YYYY-MM-DD")
    return s


# ---------- tasks ----------

def cmd_add_task(args):
    p = data_dir(args) / "tasks.json"
    tasks = load(p)
    task = {
        "id": uuid.uuid4().hex[:8],
        "task": args.task,
        "status": "todo",
        "priority": args.priority,
        "deadline": args.deadline,
        "next_action": args.next_action or args.task,
        "project": args.project,
        "blockers": args.blockers,
        "notes": args.notes,
        "date_created": str(today()),
        "date_last_discussed": str(today()),
        "postponed_count": 0,
    }
    tasks.append(task)
    save(p, tasks)
    print(f"Added task {task['id']}: {task['task']}")


def cmd_update_task(args):
    p = data_dir(args) / "tasks.json"
    tasks = load(p)
    for t in tasks:
        if t["id"] == args.id:
            if args.status:
                t["status"] = args.status
            if args.priority:
                t["priority"] = args.priority
            if args.deadline:
                t["deadline"] = args.deadline
            if args.next_action:
                t["next_action"] = args.next_action
            if args.notes:
                t["notes"] = args.notes
            if args.postpone:
                t["postponed_count"] = t.get("postponed_count", 0) + 1
                if args.new_deadline:
                    t["deadline"] = args.new_deadline
            t["date_last_discussed"] = str(today())
            save(p, tasks)
            print(f"Updated {t['id']}: {t['task']} (status={t['status']}, postponed={t.get('postponed_count',0)})")
            return
    print(f"No task with id {args.id}", file=sys.stderr)
    sys.exit(1)


def cmd_list_tasks(args):
    p = data_dir(args) / "tasks.json"
    tasks = load(p)
    d = today()

    def keep(t):
        if t["status"] == "dropped" and not args.include_dropped:
            return False
        if args.status and t["status"] != args.status:
            return False
        if args.priority and t["priority"] != args.priority:
            return False
        if args.project and t.get("project") != args.project:
            return False
        if args.overdue:
            dl = parse_date(t.get("deadline"))
            if not dl or dl >= d or t["status"] == "done":
                return False
        if args.stale is not None:
            last = parse_date(t.get("date_last_discussed")) or parse_date(t.get("date_created"))
            if not last or (d - last).days < args.stale:
                return False
        if args.postponed_min is not None and t.get("postponed_count", 0) < args.postponed_min:
            return False
        return True

    results = [t for t in tasks if keep(t)]
    order = {"must": 0, "should": 1, "if_time": 2}
    results.sort(key=lambda t: (order.get(t["priority"], 9), t.get("deadline") or "9999-99-99"))

    if not results:
        print("(no matching tasks)")
        return
    for t in results:
        dl = f" due {t['deadline']}" if t.get("deadline") else ""
        pc = f" [postponed x{t['postponed_count']}]" if t.get("postponed_count") else ""
        print(f"[{t['id']}] ({t['priority']}/{t['status']}){dl}{pc} {t['task']} -> next: {t['next_action']}")


def cmd_drop_task(args):
    p = data_dir(args) / "tasks.json"
    tasks = load(p)
    for t in tasks:
        if t["id"] == args.id:
            t["status"] = "dropped"
            t["date_last_discussed"] = str(today())
            save(p, tasks)
            print(f"Dropped {t['id']}: {t['task']}")
            return
    print(f"No task with id {args.id}", file=sys.stderr)
    sys.exit(1)


def cmd_overview(args):
    p = data_dir(args) / "tasks.json"
    tasks = [t for t in load(p) if t["status"] not in ("done", "dropped")]
    d = today()

    overdue = [t for t in tasks if (dl := parse_date(t.get("deadline"))) and dl < d]
    due_soon = [t for t in tasks if (dl := parse_date(t.get("deadline"))) and d <= dl <= d + timedelta(days=2)]
    flagged = [t for t in tasks if t.get("postponed_count", 0) >= 3]
    must = [t for t in tasks if t["priority"] == "must"]
    should = [t for t in tasks if t["priority"] == "should"]
    if_time = [t for t in tasks if t["priority"] == "if_time"]

    def line(t):
        dl = f" (due {t['deadline']})" if t.get("deadline") else ""
        return f"  - [{t['id']}] {t['task']}{dl}"

    print(f"=== Overview: {d.isoformat()} ===")
    print(f"\nMust do ({len(must)}):")
    for t in must: print(line(t))
    print(f"\nShould do ({len(should)}):")
    for t in should: print(line(t))
    print(f"\nIf time ({len(if_time)}):")
    for t in if_time: print(line(t))
    if overdue:
        print(f"\n⚠ Overdue ({len(overdue)}):")
        for t in overdue: print(line(t))
    if due_soon:
        print(f"\n⏳ Due within 2 days ({len(due_soon)}):")
        for t in due_soon: print(line(t))
    if flagged:
        print(f"\n🚩 Postponed 3+ times — reconsider or commit ({len(flagged)}):")
        for t in flagged: print(line(t))
    if len(must) > 3:
        print(f"\nNote: {len(must)} tasks marked 'must' — that's likely unrealistic for one day.")


# ---------- ideas ----------

def cmd_add_idea(args):
    p = data_dir(args) / "ideas.json"
    ideas = load(p)
    idea = {
        "id": uuid.uuid4().hex[:8],
        "description": args.description,
        "category": args.category,
        "date_captured": str(today()),
        "status": "open",
    }
    ideas.append(idea)
    save(p, ideas)
    print(f"Captured idea {idea['id']} [{idea['category']}]: {idea['description']}")


def cmd_list_ideas(args):
    p = data_dir(args) / "ideas.json"
    ideas = load(p)
    if args.category:
        ideas = [i for i in ideas if i["category"] == args.category]
    if args.query:
        q = args.query.lower()
        ideas = [i for i in ideas if q in i["description"].lower()]
    if not ideas:
        print("(no matching ideas)")
        return
    for i in ideas:
        print(f"[{i['id']}] ({i['category']}, {i['date_captured']}) {i['description']}")


# ---------- daily log ----------

def cmd_day_log(args):
    p = data_dir(args) / "log.json"
    log = load(p)
    entry = {
        "date": str(today()),
        "completed": args.completed or [],
        "carried_forward": args.carried_forward or [],
        "dropped": args.dropped or [],
        "top3_tomorrow": args.top3 or [],
    }
    log = [e for e in log if e["date"] != entry["date"]]  # replace same-day entry if re-run
    log.append(entry)
    save(p, log)
    print(f"Logged {entry['date']}: {len(entry['completed'])} completed, "
          f"{len(entry['carried_forward'])} carried forward, {len(entry['dropped'])} dropped")


def cmd_recent_log(args):
    p = data_dir(args) / "log.json"
    log = sorted(load(p), key=lambda e: e["date"], reverse=True)[: args.n]
    if not log:
        print("(no log entries yet)")
        return
    for e in log:
        print(f"\n{e['date']}")
        print(f"  completed: {', '.join(e['completed']) or '-'}")
        print(f"  carried forward: {', '.join(e['carried_forward']) or '-'}")
        print(f"  dropped: {', '.join(e['dropped']) or '-'}")
        print(f"  tomorrow's top 3: {', '.join(e['top3_tomorrow']) or '-'}")


# ---------- CLI ----------

def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", help="Directory for tasks.json/ideas.json/log.json (default: script dir)")
    sub = ap.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add-task")
    a.add_argument("--task", required=True)
    a.add_argument("--priority", choices=PRIORITIES, default="should")
    a.add_argument("--deadline", type=valid_date, help="YYYY-MM-DD")
    a.add_argument("--next-action")
    a.add_argument("--project")
    a.add_argument("--blockers")
    a.add_argument("--notes")
    a.set_defaults(func=cmd_add_task)

    a = sub.add_parser("update-task")
    a.add_argument("id")
    a.add_argument("--status", choices=STATUSES)
    a.add_argument("--priority", choices=PRIORITIES)
    a.add_argument("--deadline", type=valid_date)
    a.add_argument("--next-action")
    a.add_argument("--notes")
    a.add_argument("--postpone", action="store_true", help="Increment postponed_count")
    a.add_argument("--new-deadline", type=valid_date, help="New deadline when postponing")
    a.set_defaults(func=cmd_update_task)

    a = sub.add_parser("list-tasks")
    a.add_argument("--status", choices=STATUSES)
    a.add_argument("--priority", choices=PRIORITIES)
    a.add_argument("--project")
    a.add_argument("--overdue", action="store_true")
    a.add_argument("--stale", type=int, help="Not discussed in N+ days")
    a.add_argument("--postponed-min", type=int)
    a.add_argument("--include-dropped", action="store_true")
    a.set_defaults(func=cmd_list_tasks)

    a = sub.add_parser("drop-task")
    a.add_argument("id")
    a.set_defaults(func=cmd_drop_task)

    a = sub.add_parser("overview", help="Full snapshot: priorities, overdue, due soon, flagged")
    a.set_defaults(func=cmd_overview)

    a = sub.add_parser("add-idea")
    a.add_argument("--description", required=True)
    a.add_argument("--category", choices=IDEA_CATEGORIES, default="ideas")
    a.set_defaults(func=cmd_add_idea)

    a = sub.add_parser("list-ideas")
    a.add_argument("--category", choices=IDEA_CATEGORIES)
    a.add_argument("--query")
    a.set_defaults(func=cmd_list_ideas)

    a = sub.add_parser("day-log")
    a.add_argument("--completed", nargs="*")
    a.add_argument("--carried-forward", nargs="*")
    a.add_argument("--dropped", nargs="*")
    a.add_argument("--top3", nargs="*")
    a.set_defaults(func=cmd_day_log)

    a = sub.add_parser("recent-log")
    a.add_argument("-n", type=int, default=5)
    a.set_defaults(func=cmd_recent_log)

    return ap


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
