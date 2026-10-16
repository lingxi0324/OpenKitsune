# -*- coding: utf-8 -*-
"""P2-3：能力域验证状态标记（玄学/认知域未验证显式化）。

对 evolution/capability_domains.json：
- total_answers > 0 的域/子域 → validation_status = "validated"
- 其余（含 source=manual 的玄学认知域）→ validation_status = "unverified"
保留 confidence 原值不破坏类型；先备份再写回。
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path(r"C:\Users\Administrator\.OpenKitsune\evolution\capability_domains.json")


def mark(node: dict) -> None:
    """递归标记域节点。"""
    answers = int(node.get("total_answers", 0) or 0)
    node["validation_status"] = "validated" if answers > 0 else "unverified"
    for sub in node.get("sub_domains", []) or []:
        mark(sub)


def main() -> None:
    backup = TARGET.with_suffix(
        f".json.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    shutil.copy2(TARGET, backup)
    print("备份:", backup)

    data = json.loads(TARGET.read_text(encoding="utf-8"))
    changed = 0
    for key, node in data.items():
        before = node.get("validation_status")
        mark(node)
        if node.get("validation_status") != before:
            changed += 1

    TARGET.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已标记 {changed} 个顶层域（含子域递归）")

    # 摘要输出
    for key, node in data.items():
        subs = len(node.get("sub_domains", []) or [])
        print(f"  {key}: {node.get('validation_status')} (子域 {subs})")


if __name__ == "__main__":
    main()
