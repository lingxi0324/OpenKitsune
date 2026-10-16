# -*- coding: utf-8 -*-
"""DecisionPath 写入/查询工具（V2.0 核心数据对象落点）。

用法：
  python scripts/decision_path.py write --goal "..." --json '{"paths":[...]}'
  python scripts/decision_path.py list
  python scripts/decision_path.py show <id>

说明：
  - 每次 write 生成 data/plans/decision_YYYYMMDD_HHMMSS.json（追加不覆盖）；
  - --json 可传完整 paths 数组（name/pros/cons/risk/cost/score）；
  - 未传 --json 时走交互参数（--path-a/--path-b/--recommend/--fallback 等）。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PLANS_DIR = Path(__file__).resolve().parents[1] / "data" / "plans"


def _now_id() -> str:
    return datetime.now().strftime("decision_%Y%m%d_%H%M%S")


def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def cmd_write(args: argparse.Namespace) -> None:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    doc_id = _now_id()
    doc = {
        "id": doc_id,
        "goal": args.goal,
        "created_at": _iso_now(),
        "scenario": args.scenario or "",
        "nine_tails_score": args.nine_tails_score,
        "paths": [],
        "priority": [],
        "recommendation": args.recommend or "",
        "fallback": args.fallback or "",
        "risks": args.risks or [],
        "tail_coverage": args.tails or [],
    }
    if args.json:
        try:
            parsed = json.loads(args.json)
        except json.JSONDecodeError as e:
            sys.exit(f"--json 解析失败: {e}")
        doc["paths"] = parsed.get("paths", [])
        doc["priority"] = parsed.get("priority", [])
        doc["risks"] = parsed.get("risks", doc["risks"])
        doc["tail_coverage"] = parsed.get("tail_coverage", doc["tail_coverage"])
        if parsed.get("recommendation"):
            doc["recommendation"] = parsed["recommendation"]
        if parsed.get("fallback"):
            doc["fallback"] = parsed["fallback"]
        if parsed.get("scenario"):
            doc["scenario"] = parsed["scenario"]
    elif args.path_a or args.path_b:
        paths = []
        for name, pros, cons in (
            ("路径A", args.path_a_pros, args.path_a_cons),
            ("路径B", args.path_b_pros, args.path_b_cons),
        ):
            if pros or cons:
                paths.append(
                    {
                        "name": name,
                        "pros": pros,
                        "cons": cons,
                        "risk": "",
                        "cost": "",
                        "score": 0,
                    }
                )
        doc["paths"] = paths
        doc["priority"] = [p["name"] for p in paths]

    if not doc["paths"] and not doc["recommendation"]:
        sys.exit("错误：至少提供 --json（含 paths）或 --path-a/--path-b 或 --recommend")

    out = PLANS_DIR / f"{doc_id}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 DecisionPath: {out}")


def cmd_list(_: argparse.Namespace) -> None:
    if not PLANS_DIR.exists():
        print("data/plans 为空")
        return
    files = sorted(PLANS_DIR.glob("decision_*.json"))
    if not files:
        print("data/plans 为空")
        return
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            print(f"{d.get('id','?')}  {d.get('created_at','?')}  目标: {d.get('goal','')[:40]}  路径数: {len(d.get('paths', []))}")
        except Exception:
            print(f"{f.name}  (解析失败)")


def cmd_show(args: argparse.Namespace) -> None:
    path = PLANS_DIR / f"{args.id}.json"
    if not path.exists():
        sys.exit(f"未找到决策: {args.id}")
    d = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(d, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser(description="DecisionPath 写入/查询工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    pw = sub.add_parser("write", help="写入一条决策路径")
    pw.add_argument("--goal", required=True, help="目标描述")
    pw.add_argument("--json", default="", help="完整 JSON（paths/priority/risks 等）")
    pw.add_argument("--scenario", default="", help="场景标签")
    pw.add_argument("--recommend", default="", help="推荐方案")
    pw.add_argument("--fallback", default="", help="兜底方案")
    pw.add_argument("--risks", nargs="*", default=[], help="全局风险")
    pw.add_argument("--tails", nargs="*", default=[], help="启用的九尾")
    pw.add_argument("--nine_tails_score", type=float, default=0.0, help="九维覆盖度 0-1")
    pw.add_argument("--path-a", action="store_true", help="使用路径A参数")
    pw.add_argument("--path-a-pros", nargs="*", default=[])
    pw.add_argument("--path-a-cons", nargs="*", default=[])
    pw.add_argument("--path-b", action="store_true", help="使用路径B参数")
    pw.add_argument("--path-b-pros", nargs="*", default=[])
    pw.add_argument("--path-b-cons", nargs="*", default=[])
    pw.set_defaults(func=cmd_write)

    pl = sub.add_parser("list", help="列出全部决策")
    pl.set_defaults(func=cmd_list)

    ps = sub.add_parser("show", help="查看单条决策")
    ps.add_argument("id", help="决策 id（decision_YYYYMMDD_HHMMSS）")
    ps.set_defaults(func=cmd_show)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
