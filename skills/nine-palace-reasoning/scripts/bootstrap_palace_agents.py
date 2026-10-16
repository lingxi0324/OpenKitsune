#!/usr/bin/env python3
"""
九宫 Agent 启动引导脚本 · 开机自加载
======================================
功能：
1. 检查三个持久化宫位 Agent 是否已注册到 ProfileStore
2. 若未注册，从 identity/agents/ 源配置补齐
3. 输出各宫位状态，供运行时判断可用性

触发时机：系统启动时由 bootstrap 机制调用
"""

import json
import sys
from pathlib import Path

# ─── 路径 ───
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent.parent  # openakita-main
IDENTITY_DIR = PROJECT_DIR / "identity" / "agents"
PROFILES_DIR = Path.home() / ".leiwa" / "agents" / "profiles"

# 九宫持久化 Agent 清单（后续扩展此列表即可新增）
PERSISTENT_PALACES = {
    "nine-palace-xunxing": "巽性",
    "nine-palace-qianqi": "乾气",
    "nine-palace-duipo": "兑魄",
}

# ─── 调度规则（震魂发散立论→乾气全局审势校正→巽性体质时序→兑魄结构化汇总）───
SCHEDULE_RULES = {
    "pipeline": ["震魂", "乾气", "巽性", "兑魄"],
    "震魂": {
        "role": "创造发散 — 立论起点",
        "position": "第一步",
        "dependents": ["乾气"],
    },
    "乾气": {
        "role": "全局审势 — 校正震魂发散结论",
        "position": "第二步",
        "depends_on": ["震魂"],
    },
    "巽性": {
        "role": "体质时序 — 推演长期演化",
        "position": "第三步",
        "depends_on": ["乾气"],
    },
    "兑魄": {
        "role": "结构化汇总 — 疑点整合输出",
        "position": "第四步",
        "depends_on": ["巽性", "震魂"],
    },
}

# 配置清单
CONFIG_SUMMARY = """
┌────────────────────────────────────────────────────────────┐
│  九宫 Agent 持久化配置总览                                  │
├────────────────────────────────────────────────────────────┤
│  宫位   五行  视角         Agent ID              状态      │
│  ───── ───── ─────────── ───────────────────── ───────── │
│  震魂   木    创造发散     nine-palace-zhenhun    待持久化 │
│  离神   火    专注精准     nine-palace-lishen     待持久化 │
│  坤情   土    共情体察     nine-palace-kunqing    待持久化 │
│  坎精   水    深挖探源     nine-palace-kanjing    待持久化 │
│  艮志   土    目标落地     nine-palace-genzhi     待持久化 │
│  ───── ───── ─────────── ───────────────────── ───────── │
│  巽性   木    本真规律     nine-palace-xunxing    ✅ 已就绪 │
│  乾气   金    全局大势     nine-palace-qianqi     ✅ 已就绪 │
│  兑魄   金    梳理输出     nine-palace-duipo      ✅ 已就绪 │
└────────────────────────────────────────────────────────────┘

调度流水线规则：
  震魂(发散立论) → 乾气(全局校正) → 巽性(体质时序) → 兑魄(结构化输出)

并行协同：
  - 震魂与巽性同属木行，二者无观点冲突，分层互补
  - 乾气与兑魄同属金行，乾气审势、兑魄输出
  - 震魂发散 + 乾气收敛 = 阴阳制衡
"""


def check_registration(palace_id: str) -> dict:
    """检查某宫位是否已在 ProfileStore 中注册"""
    profile_fp = PROFILES_DIR / f"{palace_id}.json"
    identity_fp = IDENTITY_DIR / f"{palace_id}.json"

    status = {
        "id": palace_id,
        "in_profiles": profile_fp.exists(),
        "in_identity": identity_fp.exists(),
        "profile_valid": False,
        "name": None,
    }

    if profile_fp.exists():
        try:
            with open(profile_fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            status["profile_valid"] = True
            status["name"] = data.get("name", palace_id)
        except (json.JSONDecodeError, OSError):
            status["profile_valid"] = False

    if not status["profile_valid"] and identity_fp.exists():
        try:
            with open(identity_fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            status["name"] = data.get("name", palace_id)
        except (json.JSONDecodeError, OSError):
            pass

    return status


def auto_register(palace_id: str) -> bool:
    """从 identity/agents/ 源配置补齐到 ProfileStore"""
    identity_fp = IDENTITY_DIR / f"{palace_id}.json"
    if not identity_fp.exists():
        return False

    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    target_fp = PROFILES_DIR / f"{palace_id}.json"

    try:
        with open(identity_fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 补全默认字段
        data.setdefault("type", "custom")
        data.setdefault("role", "worker")
        data.setdefault("hidden", False)
        data.setdefault("ephemeral", False)
        data.setdefault("skills", ["lingxi-tuiyan"])
        data.setdefault("skills_mode", "inclusive")
        data.setdefault("icon", "🤖")
        data.setdefault("color", "#4A90D9")
        data.setdefault("created_by", "lingxi")

        with open(target_fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except (json.JSONDecodeError, OSError):
        return False


def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║    九宫 Agent 启动引导 · bootstrap_palace_agents        ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    all_ok = True

    for palace_id, palace_name in PERSISTENT_PALACES.items():
        print(f"  🔍 {palace_name} ({palace_id})...", end=" ")
        status = check_registration(palace_id)

        if status["in_profiles"] and status["profile_valid"]:
            print(f"✅ 已就绪 — {status['name']}")
        elif status["in_identity"]:
            print(f"⚠️ 未注册，正在补齐...", end=" ")
            if auto_register(palace_id):
                print(f"✅ 已自动注册")
            else:
                print(f"❌ 注册失败")
                all_ok = False
        else:
            print(f"❌ 源配置不存在")
            all_ok = False

    print()
    print("═══ 调度规则（当前生效） ═══")
    for step_n, palace in enumerate(SCHEDULE_RULES["pipeline"], 1):
        rule = SCHEDULE_RULES[palace]
        dep_info = ""
        if rule.get("depends_on"):
            dep_info = f" ← 依赖: {'/'.join(rule['depends_on'])}"
        print(f"  Step {step_n}: {palace} — {rule['role']}{dep_info}")

    print()
    print(CONFIG_SUMMARY.strip())

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
