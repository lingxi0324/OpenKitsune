#!/usr/bin/env python3
"""
Checkpoint Create - 检查点创建工具

在高风险操作前创建文件/配置/Git状态快照检查点。
"""

import json
import os
import subprocess
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, List


class Checkpoint:
    """检查点创建工具"""

    def __init__(self, base_dir: str = None):
        self.base_dir = base_dir or os.path.join(os.getcwd(), "data", "checkpoints")
        os.makedirs(self.base_dir, exist_ok=True)
        self.max_checkpoints = 10

    def create_id(self, description: str) -> str:
        """生成检查点ID"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        desc = description.replace(' ', '_').replace('/', '_')[:20]
        return f"checkpoint_{timestamp}_{desc}"

    def _get_git_status(self) -> Optional[str]:
        """获取Git状态"""
        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _get_git_branch(self) -> Optional[str]:
        """获取当前分支"""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _get_dependencies(self) -> Optional[str]:
        """获取依赖快照"""
        deps = []
        # pip freeze
        try:
            result = subprocess.run(
                ['pip', 'freeze'],
                capture_output=True, text=True, timeout=10
            )
            deps.append(result.stdout)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        # npm list
        try:
            result = subprocess.run(
                ['npm', 'ls', '--depth=0', '--json'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                deps.append(result.stdout)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return '\n'.join(deps) if deps else None

    def create(self, description: str, files: List[str] = None,
               include_git: bool = True, include_dependencies: bool = True,
               working_dir: str = None) -> dict:
        """创建检查点"""
        working_dir = working_dir or os.getcwd()
        checkpoint_id = self.create_id(description)
        checkpoint_dir = os.path.join(self.base_dir, checkpoint_id)
        os.makedirs(checkpoint_dir, exist_ok=True)

        manifest = {
            "checkpoint_id": checkpoint_id,
            "timestamp": datetime.now().isoformat(),
            "description": description,
            "working_dir": working_dir,
            "files_snapshot": [],
            "git_snapshot": None,
            "dependencies_snapshot": None,
            "files_restored": False
        }

        # 1. 文件快照
        if files:
            snapshot_dir = os.path.join(checkpoint_dir, "files")
            os.makedirs(snapshot_dir, exist_ok=True)
            for fpath in files:
                full_path = os.path.join(working_dir, fpath)
                if os.path.exists(full_path):
                    dest = os.path.join(snapshot_dir, fpath.replace(os.sep, '_'))
                    shutil.copy2(full_path, dest)
                    file_hash = self._hash_file(full_path)
                    manifest["files_snapshot"].append({
                        "path": fpath,
                        "original_hash": file_hash,
                        "snapshot_path": dest
                    })
                else:
                    manifest["files_snapshot"].append({
                        "path": fpath,
                        "error": "文件不存在"
                    })

        # 2. Git 快照
        if include_git:
            git_snapshot_dir = os.path.join(checkpoint_dir, "git")
            os.makedirs(git_snapshot_dir, exist_ok=True)

            # 保存当前 diff
            try:
                diff_result = subprocess.run(
                    ['git', 'diff', 'HEAD', '--', '.'],
                    capture_output=True, text=True, timeout=30
                )
                diff_path = os.path.join(git_snapshot_dir, "diff_before.patch")
                with open(diff_path, 'w', encoding='utf-8') as f:
                    f.write(diff_result.stdout)
            except Exception:
                pass

            # 保存 git status
            git_status = self._get_git_status()
            if git_status:
                with open(os.path.join(git_snapshot_dir, "status.txt"), 'w', encoding='utf-8') as f:
                    f.write(git_status)

            branch = self._get_git_branch()
            manifest["git_snapshot"] = {
                "branch": branch,
                "status_path": os.path.join(git_snapshot_dir, "status.txt"),
                "diff_path": os.path.join(git_snapshot_dir, "diff_before.patch")
            }

        # 3. 依赖快照
        if include_dependencies:
            deps = self._get_dependencies()
            if deps:
                with open(os.path.join(checkpoint_dir, "dependencies.txt"), 'w', encoding='utf-8') as f:
                    f.write(deps)
                manifest["dependencies_snapshot"] = "dependencies.txt"

        # 4. 保存 manifest
        manifest_path = os.path.join(checkpoint_dir, "manifest.json")
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # 5. 清理旧检查点（保留最新 N 个）
        self._cleanup_old_checkpoints()

        # 6. 记录审计日志
        self._log_audit("checkpoint_create", checkpoint_id, "success", description)

        manifest["storage_path"] = checkpoint_dir
        return manifest

    def _hash_file(self, filepath: str) -> str:
        """计算文件哈希"""
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    def _cleanup_old_checkpoints(self):
        """清理旧检查点"""
        checkpoints = sorted(Path(self.base_dir).iterdir())
        while len(checkpoints) > self.max_checkpoints:
            oldest = checkpoints.pop(0)
            shutil.rmtree(str(oldest), ignore_errors=True)

    def _log_audit(self, operation: str, checkpoint_id: str,
                   result: str, description: str):
        """记录审计日志"""
        log_dir = os.path.join(os.getcwd(), "data", "audit_logs")
        os.makedirs(log_dir, exist_ok=True)
        today = datetime.now().strftime('%Y-%m-%d')
        log_file = os.path.join(log_dir, f"audit_{today}.jsonl")
        entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "checkpoint_id": checkpoint_id,
            "result": result,
            "description": description
        }
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def main():
    """命令行入口"""
    if len(sys.argv) < 2:
        print("用法: python checkpoint_create.py <description> [files...]")
        sys.exit(1)

    from sys import argv
    description = argv[1]
    files = argv[2:] if len(argv) > 2 else []

    checkpoint = Checkpoint()
    result = checkpoint.create(description=description, files=files)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    from sys import argv, exit
    exit(main() or 0)
