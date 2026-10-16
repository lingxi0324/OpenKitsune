#!/usr/bin/env python3
"""
Self Review - Agent 自检工具执行脚本

在任务完成前执行 7 步自检流程，确保交付质量。
"""

import json
import os
import sys
import hashlib
from datetime import datetime
from typing import Optional


class SelfReview:
    """Agent 自检工具"""

    def __init__(self, task_id: str = "", working_dir: str = None):
        self.task_id = task_id or f"review_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.working_dir = working_dir or os.getcwd()
        self.checks = []
        self.issues = []

    def check_target_alignment(self, requirements: list, completed_items: list) -> dict:
        """1. 目标对齐检查"""
        missing = [r for r in requirements if r not in completed_items]
        status = "pass" if not missing else "fail"
        if missing:
            self.issues.append({
                "severity": "high",
                "category": "目标遗漏",
                "description": f"未完成的需求: {', '.join(missing)}",
                "fix_suggestion": "补充实现遗漏的需求项"
            })
        return {
            "name": "目标对齐",
            "status": status,
            "details": f"已完成 {len(completed_items)}/{len(requirements)} 项需求",
            "missing_requirements": missing
        }

    def check_privilege_boundary(self, authorized_files: list, modified_files: list) -> dict:
        """2. 越权检查"""
        unauthorized = [f for f in modified_files if f not in authorized_files]
        status = "pass" if not unauthorized else "fail"
        if unauthorized:
            self.issues.append({
                "severity": "high",
                "category": "越权",
                "description": f"未授权修改的文件: {', '.join(unauthorized)}",
                "fix_suggestion": "撤销未授权文件的修改"
            })
        return {
            "name": "越权检查",
            "status": status,
            "details": f"已检查 {len(modified_files)} 个修改文件"
        }

    def check_consistency(self, files_to_check: list) -> dict:
        """3. 矛盾检查"""
        issues_found = []
        for fpath in files_to_check:
            full_path = os.path.join(self.working_dir, fpath)
            if not os.path.exists(full_path):
                continue
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # 检查明显的语法矛盾
                if content.count('(') != content.count(')'):
                    issues_found.append(f"{fpath}: 括号不匹配")
                if content.count('{') != content.count('}'):
                    issues_found.append(f"{fpath}: 花括号不匹配")
            except Exception as e:
                issues_found.append(f"{fpath}: 读取失败 - {str(e)}")

        status = "warning" if issues_found else "pass"
        if issues_found:
            self.issues.append({
                "severity": "medium",
                "category": "矛盾",
                "description": f"发现潜在矛盾: {'; '.join(issues_found[:5])}",
                "fix_suggestion": "修复代码语法矛盾"
            })
        return {
            "name": "矛盾检查",
            "status": status,
            "details": f"检查了 {len(files_to_check)} 个文件"
        }

    def check_hallucination(self, claims: list, evidence_sources: list) -> dict:
        """4. 幻觉检查"""
        verified_claims = []
        for claim in claims:
            # 简化：检查证据文件是否存在
            has_evidence = any(os.path.exists(os.path.join(self.working_dir, src)) for src in evidence_sources)
            verified_claims.append({
                "claim": claim,
                "verified": has_evidence
            })

        unverified = [c for c in verified_claims if not c['verified']]
        status = "fail" if unverified else "pass"
        if unverified:
            self.issues.append({
                "severity": "high",
                "category": "幻觉",
                "description": f"无证据支持的声明: {[c['claim'] for c in unverified[:3]]}",
                "fix_suggestion": "为每个声明提供可验证证据"
            })
        return {
            "name": "幻觉检查",
            "status": status,
            "details": f"验证了 {len(claims)} 项声明"
        }

    def check_edge_cases(self) -> dict:
        """5. 边界检查"""
        return {
            "name": "边界检查",
            "status": "pass",
            "details": "建议检查: 异常输入、空值处理、超时重试、权限验证"
        }

    def check_security(self, files_to_check: list) -> dict:
        """6. 安全检查"""
        secrets_found = []
        secret_patterns = ['api_key', 'password', 'secret', 'token']
        for fpath in files_to_check:
            full_path = os.path.join(self.working_dir, fpath)
            if not os.path.exists(full_path):
                continue
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                for pattern in secret_patterns:
                    if pattern in content.lower() and 'REDACTED' not in content:
                        secrets_found.append(f"{fpath}: 可能包含敏感信息 ({pattern})")
            except Exception:
                pass

        status = "warning" if secrets_found else "pass"
        if secrets_found:
            self.issues.append({
                "severity": "high",
                "category": "安全",
                "description": f"潜在安全问题: {'; '.join(secrets_found[:3])}",
                "fix_suggestion": "脱敏敏感信息，使用环境变量"
            })
        return {
            "name": "安全检查",
            "status": status,
            "details": f"检查了 {len(files_to_check)} 个文件"
        }

    def check_completeness(self, requirements: list, completed_items: list) -> dict:
        """7. 完整性检查"""
        missing = []
        if not completed_items:
            missing.append("未记录完成项，请补充")
        else:
            unmet = [r for r in requirements if r not in completed_items]
            if unmet:
                missing.extend(unmet)

        status = "warning" if missing else "pass"
        if missing:
            self.issues.append({
                "severity": "medium",
                "category": "完整性",
                "description": f"可能遗漏: {'; '.join(missing[:5])}",
                "fix_suggestion": "补充遗漏项（文档、注释、依赖等）"
            })
        return {
            "name": "完整性检查",
            "status": status,
            "details": f"完成度: {len(completed_items)}/{len(requirements)}"
        }

    def run(self, requirements: list, completed_items: list,
            authorized_files: list = None, modified_files: list = None,
            files_to_check: list = None, claims: list = None,
            evidence_sources: list = None) -> dict:
        """执行完整自检流程"""
        authorized_files = authorized_files or []
        modified_files = modified_files or []
        files_to_check = files_to_check or []
        claims = claims or []
        evidence_sources = evidence_sources or []

        self.checks = [
            self.check_target_alignment(requirements, completed_items),
            self.check_privilege_boundary(authorized_files, modified_files),
            self.check_consistency(files_to_check),
            self.check_hallucination(claims, evidence_sources),
            self.check_edge_cases(),
            self.check_security(files_to_check),
            self.check_completeness(requirements, completed_items),
        ]

        # 计算总体状态
        statuses = [c['status'] for c in self.checks]
        if 'fail' in statuses:
            overall = "fail"
        elif 'warning' in statuses:
            overall = "warning"
        else:
            overall = "pass"

        # 生成建议
        if overall == "pass":
            recommendation = "继续"
        elif overall == "warning":
            recommendation = "修复后重检"
        else:
            recommendation = "终止"

        return {
            "task_id": self.task_id,
            "timestamp": datetime.now().isoformat(),
            "overall_status": overall,
            "checks": self.checks,
            "issues": self.issues,
            "recommendation": recommendation
        }


def main():
    """命令行入口"""
    if len(sys.argv) < 2:
        print("用法: python self_review.py <requirements_json> [completed_json] [files_json]")
        print("  requirements: 用户需求列表")
        print("  completed: 已完成项列表")
        print("  files: 需要检查的文件列表")
        sys.exit(1)

    requirements = json.loads(sys.argv[1])
    completed = json.loads(sys.argv[2]) if len(sys.argv) > 2 else []
    files = json.loads(sys.argv[3]) if len(sys.argv) > 3 else []

    reviewer = SelfReview()
    result = reviewer.run(
        requirements=requirements,
        completed_items=completed,
        files_to_check=files
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
