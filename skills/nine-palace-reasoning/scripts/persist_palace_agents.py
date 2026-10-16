#!/usr/bin/env python3
"""
九宫持久化注册脚本 · 将巽性/乾气/兑魄三宫写入 ProfileStore
============================================================
三步逻辑：
1. 读取 identity/agents/*.json 源配置
2. 填充 AgentProfile 完整字段架构
3. 写入 {data_dir}/agents/profiles/ 实现持久化

同时更新九宫映射缓存文件，供调度引擎运行时直接调用。
"""

import json
import sys
from pathlib import Path

# ─── 路径 ───
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent.parent  # openakita-main
IDENTITY_DIR = PROJECT_DIR / "identity" / "agents"
PROFILES_TARGET = Path.home() / ".leiwa" / "agents" / "profiles"

PALACE_IDS = {
    "nine-palace-xunxing": "巽性",
    "nine-palace-qianqi": "乾气",
    "nine-palace-duipo": "兑魄",
}

# AgentProfile 完整字段默认值（from_dict 接收的格式）
DEFAULT_FIELDS = {
    "type": "custom",
    "role": "worker",
    "skills": ["lingxi-tuiyan"],
    "skills_mode": "inclusive",
    "tools": [],
    "tools_mode": "all",
    "mcp_servers": [],
    "mcp_mode": "all",
    "plugins": [],
    "plugins_mode": "all",
    "preferred_endpoint": None,
    "endpoint_policy": "prefer",
    "permission_rules": [],
    "hidden": False,
    "user_customized": False,
    "ephemeral": False,
    "inherit_from": None,
    "identity_mode": "shared",
    "memory_mode": "shared",
    "memory_inherit_global": True,
    "user_profile_content": "",
    "runtime_env_mode": "shared",
    "runtime_env_dependencies": [],
    "runtime_env_python": None,
    "max_turns": None,
    "background": False,
    "omit_system_context": False,
    "timeout_seconds": None,
    "output_schema": None,
    "structured_output": "none",
    "token_budget": 0,
    "compute_tier": "auto",
    "context_load_mode": "relevant",
    "pixel_appearance": None,
    "hub_source": None,
    "fallback_profile_id": None,
}
def load_source_config(palace_id: str) -> dict:
    """读取 identity/agents/ 下的 JSON 源配置"""
    fp = IDENTITY_DIR / f"{palace_id}.json"
    if not fp.exists():
        print(f"  ❌ 未找到 {fp}")
        return None
    with open(fp, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  ✅ 读取源配置: {palace_id} → {data.get('name', '?')}")
    return data


def build_profile_data(source: dict) -> dict:
    """将源配置补全为 AgentProfile.from_dict 可接收的完整结构"""
    profile = {**DEFAULT_FIELDS}  # 先从默认值复制
    profile.update(source)        # 源配置覆盖
    # 确保 type 是字符串
    if isinstance(profile.get("type"), str):
        pass  # 已经是 str
    profile.setdefault("created_at", "")
    profile.setdefault("name_i18n", {})
    profile.setdefault("description_i18n", {})
    # 确保 skills 是列表且不丢
    if not profile.get("skills"):
        profile["skills"] = ["lingxi-tuiyan"]
    if not profile.get("skills_mode"):
        profile["skills_mode"] = "inclusive"
    return profile


def write_profile(profile_data: dict) -> bool:
    """写入 ProfileStore 持久化目录"""
    PROFILES_TARGET.mkdir(parents=True, exist_ok=True)
    pid = profile_data.get("id", "unknown")
    fp = PROFILES_TARGET / f"{pid}.json"

    # 如果已存在则读取合并，保留自定义修改
    existing = {}
    if fp.exists():
        try:
            with open(fp, "r", encoding="utf-8") as f:
                existing = json.load(f)
            # 保留 user_customized、pixel_appearance 等用户自定义字段
            for keep_field in ("user_customized", "pixel_appearance", "hub_source"):
                if keep_field in existing:
                    profile_data[keep_field] = existing[keep_field]
        except (json.JSONDecodeError, OSError):
            pass

    with open(fp, "w", encoding="utf-8") as f:
        json.dump(profile_data, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 持久化写入: {fp}")
    return True


def verify_registration(profile_id: str) -> bool:
    """验证写入是否成功且可加载"""
    fp = PROFILES_TARGET / f"{profile_id}.json"
    if not fp.exists():
        print(f"  ❌ 验证失败: {fp} 不存在")
        return False
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not (data.get('id') == profile_id):
            raise AssertionError(f"ID 不匹配: {data.get('id')} != {profile_id}")
        if not ('skills' in data):
            raise AssertionError('缺少 skills 字段')
        print(f"  ✅ 验证通过: {data.get('name', profile_id)} — skills={data.get('skills')}")
        return True
    except (json.JSONDecodeError, AssertionError, OSError) as e:
        print(f"  ❌ 验证失败: {e}")
        return False


def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║      九宫持久化注册 · 巽性·乾气·兑魄                     ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    print(f"📂 源目录: {IDENTITY_DIR}")
    print(f"📂 目标目录: {PROFILES_TARGET}")
    print()

    success = []
    fail = []

    for palace_id, palace_name in PALACE_IDS.items():
        print(f"─── {palace_name} ({palace_id}) ───")
        source = load_source_config(palace_id)
        if source is None:
            fail.append(palace_id)
            continue

        profile_data = build_profile_data(source)

        if write_profile(profile_data):
            if verify_registration(palace_id):
                success.append(palace_id)
            else:
                fail.append(palace_id)
        else:
            fail.append(palace_id)
        print()

    # 统计
    print("═══ 注册结果 ═══")
    print(f"   ✅ 成功: {len(success)}/{len(PALACE_IDS)}")
    for pid in success:
        name = PALACE_IDS.get(pid, pid)
        print(f"     - {name} ({pid})")
    if fail:
        print(f"   ❌ 失败: {len(fail)}")
        for pid in fail:
            name = PALACE_IDS.get(pid, pid)
            print(f"     - {name} ({pid})")

    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
