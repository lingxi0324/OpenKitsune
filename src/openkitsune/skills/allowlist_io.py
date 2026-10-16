"""
外部技能 allowlist (data/skills.json) 的唯一读写入口。

目标：
- 所有 API/工具/后台模块读写 skills.json 必须经过此模块，避免多路径写入导致的竞争或格式漂移。
- 写入保证原子性（写临时文件 + os.replace），避免崩溃导致半写文件。
- 进程内并发写入互斥（``_WRITE_LOCK``）。

返回约定：
- ``external_allowlist is None`` 表示 ``data/skills.json`` 不存在或未声明 allowlist（业务语义：全部启用）。
- ``external_allowlist is set()`` 表示用户显式禁用所有外部技能。

该模块本身**不**触发缓存失效或 agent 通知，调用方需在写入后调用 ``Agent.propagate_skill_change``。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_WRITE_LOCK = threading.RLock()


def _skills_json_path() -> Path:
    """解析当前工作区的 data/skills.json 路径。"""
    try:
        from ..config import settings

        return Path(settings.project_root) / "data" / "skills.json"
    except Exception:
        return Path.cwd() / "data" / "skills.json"


def read_allowlist() -> tuple[Path, set[str] | None]:
    """读取 ``data/skills.json`` 中的 ``external_allowlist``。

    Returns:
        (path, allowlist) 元组：
        - path: 当前工作区的 skills.json 绝对路径
        - allowlist: 从文件中读到的显式 allowlist；当文件不存在/损坏/未声明时为 ``None``
    """
    path = _skills_json_path()
    if not path.exists():
        return path, None
    try:
        raw = path.read_text(encoding="utf-8")
        cfg = json.loads(raw) if raw.strip() else {}
        al = cfg.get("external_allowlist", None)
        if isinstance(al, list):
            return path, {str(x).strip() for x in al if str(x).strip()}
        return path, None
    except Exception as e:
        logger.warning("Failed to read %s: %s", path, e)
        return path, None


def _atomic_write_json(path: Path, content: dict) -> None:
    """原子地把 JSON 写入 path：先写临时文件，再 os.replace 覆盖。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(content, ensure_ascii=False, indent=2) + "\n"

    tmp_fd, tmp_path_str = tempfile.mkstemp(
        prefix=".skills.", suffix=".json.tmp", dir=str(path.parent)
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(serialized)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        raise


def _compose_content(allowlist: set[str]) -> dict:
    return {
        "version": 1,
        "external_allowlist": sorted(allowlist),
        "updated_at": datetime.now().isoformat(),
    }


def overwrite_allowlist(allowlist: set[str] | None) -> Path:
    """用完整 allowlist 覆盖 ``data/skills.json``。

    Args:
        allowlist: 目标 allowlist 集合；传入 ``None`` 视为空集合（禁用所有外部技能）。

    Returns:
        实际写入的文件路径。
    """
    path = _skills_json_path()
    final = set(allowlist) if allowlist else set()
    with _WRITE_LOCK:
        _atomic_write_json(path, _compose_content(final))
    logger.info("[skills.json] overwrite allowlist (%d ids) -> %s", len(final), path)
    return path


def upsert_skill_ids(
    skill_ids: set[str], *, default_allowlist: set[str] | None = None,
) -> Path | None:
    """原子地把给定 skill_ids 合并进现有 allowlist。

    - 当 skills.json 不存在时：**不**创建新文件，返回 ``None``
      （语义保持“未声明 allowlist = 全部启用”）；此时新装技能已经默认启用，无需写盘。
    - 当 skills.json 存在但没有 external_allowlist 字段时：与上同义，返回 ``None``。
    - 当 skills.json 已有 external_allowlist：把 skill_ids 合并后原子写回。
    - default_allowlist 可用于显式启用默认禁用的技能：仅当无显式名单时，
      以调用方提供的当前默认启用集合为基底；已有用户名单始终优先。
    """
    if not skill_ids:
        return None

    with _WRITE_LOCK:
        path = _skills_json_path()
        if not path.exists() and default_allowlist is None:
            return None

        try:
            raw = path.read_text(encoding="utf-8") if path.exists() else "{}"
            cfg = json.loads(raw) if raw.strip() else {}
        except Exception as e:
            logger.warning("skills.json unreadable, skip upsert: %s", e)
            return None

        current = cfg.get("external_allowlist", None)
        if not isinstance(current, list):
            if default_allowlist is None:
                return None
            current = list(default_allowlist)

        merged = {str(x).strip() for x in current if str(x).strip()} | {
            s.strip() for s in skill_ids if s and s.strip()
        }
        _atomic_write_json(path, _compose_content(merged))

    logger.info("[skills.json] upsert %d skill id(s): %s", len(skill_ids), sorted(skill_ids))
    return path


def remove_skill_ids(skill_ids: set[str]) -> Path | None:
    """从现有 allowlist 中移除给定 skill_ids（卸载场景）。

    skills.json 不存在或没有 allowlist 时返回 ``None`` 表示无操作。
    """
    if not skill_ids:
        return None

    with _WRITE_LOCK:
        path = _skills_json_path()
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            cfg = json.loads(raw) if raw.strip() else {}
        except Exception as e:
            logger.warning("skills.json unreadable, skip remove: %s", e)
            return None

        current = cfg.get("external_allowlist", None)
        if not isinstance(current, list):
            return None

        remaining = {str(x).strip() for x in current if str(x).strip()} - {
            s.strip() for s in skill_ids if s
        }
        _atomic_write_json(path, _compose_content(remaining))

    logger.info("[skills.json] remove %d skill id(s): %s", len(skill_ids), sorted(skill_ids))
    return path
