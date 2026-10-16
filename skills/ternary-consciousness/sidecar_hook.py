"""
河图活力引擎 — Sidecar 钩子
══════════════════════════
供 sidecar_services.py 调用，通过 subprocess 启动/停止引擎。
避免 import 路径问题，仅依赖文件路径。
"""

import os
import signal
import subprocess
import time
import logging

logger = logging.getLogger(__name__)

# 技能目录（自动从本文件位置推算）
_HERE = os.path.dirname(os.path.abspath(__file__))
_PID_FILE = os.path.join(_HERE, "ternary_pid.txt")
_ENGINE_SCRIPT = os.path.join(_HERE, "start.py")

# 托管句柄
_managed_proc: subprocess.Popen | None = None


def _is_alive() -> bool:
    if _managed_proc is not None:
        return _managed_proc.poll() is None
    try:
        if os.path.exists(_PID_FILE):
            with open(_PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
    except (ValueError, ProcessLookupError, OSError):
        pass
    return False


def start() -> dict:
    """启动河图活力引擎为后台子进程。幂等。"""
    global _managed_proc

    if _is_alive():
        return {"status": "running"}

    if not os.path.exists(_ENGINE_SCRIPT):
        return {"status": "not_found", "path": _ENGINE_SCRIPT}

    try:
        proc = subprocess.Popen(
            ["python", _ENGINE_SCRIPT],
            cwd=_HERE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _managed_proc = proc
        time.sleep(1.5)

        if proc.poll() is not None:
            return {"status": "crashed", "rc": proc.returncode}

        logger.info(f"[TernaryHook] ✓ 引擎已启动 (PID {proc.pid})")
        return {"status": "started", "pid": proc.pid}

    except Exception as e:
        logger.error(f"[TernaryHook] 启动失败: {e}")
        return {"status": "error", "error": str(e)}


def stop():
    """停止河图活力引擎。幂等。"""
    global _managed_proc

    if _managed_proc is not None:
        pid = _managed_proc.pid
        try:
            _managed_proc.terminate()
            _managed_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _managed_proc.kill()
        finally:
            _managed_proc = None
        logger.info(f"[TernaryHook] ✓ 引擎 (PID {pid}) 已停止")
        return

    # 兜底：通过 PID 文件
    if os.path.exists(_PID_FILE):
        try:
            with open(_PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            logger.info(f"[TernaryHook] ✓ 清理残留引擎 (PID {pid})")
        except (ValueError, ProcessLookupError, OSError):
            pass
        finally:
            try:
                os.unlink(_PID_FILE)
            except Exception:
                pass
