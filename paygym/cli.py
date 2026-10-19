"""`paygym` command-line entry point. Subcommands are added as each phase lands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from paygym import __version__


def _cmd_validate(args: argparse.Namespace) -> int:
    from paygym.validate import validate_path

    report = validate_path(Path(args.path))
    for error in report.errors:
        print(f"ERROR {error}")
    print(report.summary())
    return 0 if report.ok else 1


def _cmd_schema(args: argparse.Namespace) -> int:
    from paygym.schema import json_schema

    print(json.dumps(json_schema(), indent=2))
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    from paygym.generator import KNOB_PRESETS, generate_split
    from paygym.schema import dump_task

    if args.knobs != "default" and args.split != "train":
        print("difficulty presets apply to the train split only (eval/held-out keep full difficulty)")
        return 1
    tasks = generate_split(args.split, args.seeds, KNOB_PRESETS[args.knobs] if args.split == "train" else None, args.knobs)
    out = Path(args.out or f"tasks/generated/{args.split}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(dump_task(t) + "\n" for t in tasks))
    tiers = {d: sum(t.difficulty == d for t in tasks) for d in (1, 2, 3)}
    print(f"{args.split}: {args.seeds} seeds -> {len(tasks)} tasks {tiers} -> {out}")
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    from paygym.audit import dedup, leakage
    from paygym.validate import read_tasks

    tasks, errors = read_tasks(Path(args.path))
    if errors:
        for e in errors:
            print(f"ERROR {e}")
        return 1
    report = {"path": args.path, "leakage": leakage.audit(tasks), "dedup": dedup.audit(tasks)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    clf = report["leakage"]["classifier"]
    print(f"literal leaks: {report['leakage']['literal_leak_count']} | "
          f"classifier acc {clf.get('cv_accuracy')} vs majority {clf.get('majority_baseline')}, "
          f"balanced acc {clf.get('cv_balanced_accuracy')} vs chance {clf.get('chance_balanced')} | "
          f"exact dup cases: {len(report['dedup']['exact_duplicate_cases'])} | "
          f"near dups: {len(report['dedup']['near_duplicates'])} -> {out}")
    return 0


def _cmd_leaderboard(args: argparse.Namespace) -> int:
    from paygym.eval.leaderboard import write

    out = write(Path(args.results))
    board = json.loads(out.read_text())
    for run in board["runs"]:
        print(f"{run['model']:<40} {run['mode']:<6} mean={run['mean_reward']} run_sd={run['run_sd']} status={run['status']}")
    print(f"{len(board['indistinguishable'])} indistinguishable pair(s) -> {out}")
    return 0


def _cmd_judge(args: argparse.Namespace) -> int:
    from paygym import judge_reliability as jr

    if args.action == "items":
        items = jr.extract_items([Path(p) for p in args.runs])
        out = Path(args.out or "results/judge/items.jsonl")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(json.dumps(i) + "\n" for i in items))
        print(f"{len(items)} correctly-refused trap explanations -> {out}")
    elif args.action == "repeat":
        report = jr.repeat_disagreement(jr.items_from_file(Path(args.items)), repeats=args.repeats)
        out = Path(args.out or "results/judge/reliability_repeat.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
        print(f"disagreement rate {report['disagreement_rate']} over {report['pairs']} (output, criterion) pairs -> {out}")
    elif args.action == "labels":
        out = Path(args.out or "docs/judge_labels.csv")
        n = jr.write_label_sheet(jr.items_from_file(Path(args.items)), out)
        print(f"{n} rows to label (fill human_pass with 1/0 before looking at judge_pass) -> {out}")
    elif args.action == "agreement":
        report = jr.agreement(Path(args.labels))
        out = Path(args.out or "results/judge/reliability_human.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    return 0


def _cmd_rescore(args: argparse.Namespace) -> int:
    from paygym.eval.runner import rescore

    dirs = [Path(d) for d in args.runs] or sorted(p.parent for p in Path(args.results).glob("*/*/config.json"))
    for d in dirs:
        print(json.dumps(rescore(d)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paygym", description="PayGym command-line tools.")
    parser.add_argument("--version", action="version", version=f"paygym {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("validate", help="validate a taskset (a .jsonl file or a directory of them)")
    p.add_argument("path", nargs="?", default="tasks")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("generate", help="generate a split from its seed range")
    p.add_argument("--split", required=True, choices=["train", "val", "heldout", "eval"])
    p.add_argument("--seeds", type=int, required=True, help="number of seeds (a trap seed yields trap + twin)")
    p.add_argument("--knobs", default="default", choices=["default", "easy", "easier"], help="train-split difficulty preset")
    p.add_argument("--out")
    p.set_defaults(func=_cmd_generate)

    p = sub.add_parser("audit", help="answer-leakage and near-duplicate audit of a taskset")
    p.add_argument("path")
    p.add_argument("--out", default="results/audit/audit.json")
    p.set_defaults(func=_cmd_audit)

    p = sub.add_parser("leaderboard", help="aggregate results/ into results/leaderboard.json")
    p.add_argument("--results", default="results")
    p.set_defaults(func=_cmd_leaderboard)

    p = sub.add_parser("judge", help="judge reliability: items | repeat | labels | agreement")
    p.add_argument("action", choices=["items", "repeat", "labels", "agreement"])
    p.add_argument("runs", nargs="*", help="run directories (for 'items')")
    p.add_argument("--items", default="results/judge/items.jsonl")
    p.add_argument("--labels", default="docs/judge_labels.csv")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--out")
    p.set_defaults(func=_cmd_judge)

    p = sub.add_parser("rescore", help="re-score saved runs under the current rubric version (no model calls)")
    p.add_argument("runs", nargs="*", help="run directories (default: every run under --results)")
    p.add_argument("--results", default="results")
    p.set_defaults(func=_cmd_rescore)

    p = sub.add_parser("schema", help="print the task JSON Schema")
    p.set_defaults(func=_cmd_schema)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
