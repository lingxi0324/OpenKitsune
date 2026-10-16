#!/usr/bin/env python
"""
三进制意识引擎 — 生命周期启动器
══════════════════════════════════════
供 sidecar_services.py 在系统初始化时调用。
启动河图活力引擎为后台子进程，shutdown 时自动清理。
"""

import os
import signal
import subprocess
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 路径 ──
SKILL_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SKILL_DIR.parent.parent  # I:\ai\openakita-main
PID_FILE = SKILL_DIR / "ternary_pid.txt"
ENGINE_SCRIPT = SKILL_DIR / "start.py"

# 托管句柄
_managed_proc: subprocess.Popen | None = None
_did_start: bool = False


def _is_alive() -> bool:
    """检查引擎是否已在运行（通过 PID 文件检测）。"""
    if _managed_proc is not None:
        return _managed_proc.poll() is None
    try:
        if PID_FILE.exists():
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)  # 信号 0 = 仅检查存活
            return True
    except (ValueError, ProcessLookupError, OSError):
        pass
    return False


def start_ternary_perception() -> dict:
    """启动河图活力引擎为后台子进程。

    幂等：已在运行 → 返回 {status: 'running'}
    首次启动 → 返回 {status: 'started', pid: ...}

    由 sidecar_services.start_sidecar_services() 在系统初始化时调用。
    """
    global _managed_proc, _did_start

    # 幂等：已在运行
    if _is_alive():
        logger.info("[Ternary] 河图活力引擎已在运行，跳过启动")
        return {"status": "running"}

    # 检查入口脚本
    if not ENGINE_SCRIPT.exists():
        logger.warning(f"[Ternary] 启动脚本不存在: {ENGINE_SCRIPT}")
        return {"status": "not_found", "path": str(ENGINE_SCRIPT)}

    try:
        proc = subprocess.Popen(
            [sys.executable or "python", str(ENGINE_SCRIPT)],
            cwd=str(SKILL_DIR),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _managed_proc = proc
        _did_start = True
        logger.info(f"[Ternary] ✓ 河图活力引擎已启动 (PID {proc.pid})")

        # 等待片刻确认存活
        time.sleep(1.5)
        if proc.poll() is not None:
            logger.warning(f"[Ternary] ⚠ 引擎启动后即退出 (rc={proc.returncode})")
            return {"status": "crashed", "rc": proc.returncode}

        return {"status": "started", "pid": proc.pid}

    except Exception as e:
        logger.error(f"[Ternary] 启动失败: {e}")
        return {"status": "error", "error": str(e)}


def stop_ternary_perception():
    """停止河图活力引擎后台子进程。

    幂等：未启动 → 静默返回。
    由 sidecar_services.stop_sidecar_services() 在系统 shutdown 时调用。
    """
    global _managed_proc, _did_start

    # ── 情况 A：我们亲手拉起的进程 ──
    if _managed_proc is not None:
        pid = _managed_proc.pid
        try:
            _managed_proc.terminate()
            try:
                _managed_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _managed_proc.kill()
            logger.info(f"[Ternary] ✓ 河图活力引擎 (PID {pid}) 已停止")
        except Exception as e:
            logger.error(f"[Ternary] 停止 (PID {pid}) 异常: {e}")
        finally:
            _managed_proc = None
            _did_start = False
        return

    # ── 兜底：通过 PID 文件清理 ──
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            logger.info(f"[Ternary] ✓ 清理残留引擎 (PID {pid})")
        except (ValueError, ProcessLookupError, OSError) as e:
            logger.debug(f"[Ternary] 兜底清理跳过: {e}")
        finally:
            try:
                PID_FILE.unlink()
            except Exception:
                pass


import sys  # noqa: E402 (末尾导入，避免循环)
