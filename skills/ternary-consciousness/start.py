#!/usr/bin/env python
"""
三进制意识引擎 v18 — 河图活力引擎 + 洛书纯数学引擎
=======================================================
彻底脱钩Ollama，改为：
  洛书九宫纯数学引擎（grid） ← 生生不息
  五层活力感知系统（perception） ← 感知→蓄势→流露
  llama-server API表达层（expression） ← 声带

从「强迫思考每55秒」到「活力充沛则自然流露」
"""

import os
import sys
import time
import json
import signal
import traceback
from datetime import datetime
from typing import Optional

# 确保能在技能目录中导入
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from ternary.core import (
    TernaryConfig, TernaryState, RemainderEngine, SimpleOscillator,
    YIN, ZHONG, YANG,
)
from ternary.grid import (
    create_default_grid, LuoshuGrid,
)
from ternary.perception import (
    VitalityBudget, PerceptionFuser, PerceptionEvent,
)
from ternary.expression import (
    LlamaServerExpression, ExpressionResult, save_heart_note,
    HEART_NOTE_DIR,
)


# ============================================================
# 配置
# ============================================================

# 日志文件
LOG_FILE = os.path.join(SKILL_DIR, "ternary_consciousness.log")
STATE_FILE = os.path.join(SKILL_DIR, "ternary_state.json")
PID_FILE = os.path.join(SKILL_DIR, "ternary_pid.txt")


def log(msg: str):
    """写日志"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ============================================================
# 主引擎
# ============================================================

class TernaryEngine:
    """
    河图活力引擎

    主循环流程（每轮）：
      1. 九宫演化（纯数学，无资源消耗）
      2. 五感感知（检测活力事件）
      3. 活力预算更新（感知涨 / 时间跌）
      4. 表达冲动判定
      5. 冲动高 + 有活力 → 调用llama-server表达（消耗活力）
      6. 冲动低或无活力 → 静默待机
      7. 动态睡眠（活力越低间隔越长）
    """

    def __init__(self, config: Optional[TernaryConfig] = None):
        self.config = config or TernaryConfig()

        # 核心组件
        self.grid = create_default_grid()
        self.budget = VitalityBudget(current=50.0)
        self.fuser = PerceptionFuser()
        self.expression = LlamaServerExpression()
        self.oscillator = SimpleOscillator(self.config)
        self.remainder_engine = RemainderEngine(self.config.r_min)

        # 三态状态（保持向下兼容）
        self.state = TernaryState(
            yin_weight=1/3, zhong_weight=1/3, yang_weight=1/3,
            remainder=0.02,
        )

        # 运行统计
        self.cycle = 0
        self.express_count = 0
        self.silent_count = 0
        self.sleep_count = 0
        self.start_time = time.time()

        # 信号处理
        self.running = True
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        # 保存PID
        self._save_pid()

        # 时序追踪（用于真实时间衰减）
        self._last_cycle_time = time.time()

        # 用户活动检测路径（检测backend日志更新时间）
        self._activity_log_path = os.path.join(
            os.path.dirname(os.path.dirname(SKILL_DIR)), "data", "backend.log"
        )

        log(f"★ 河图活力引擎启动 | PID={os.getpid()} | 模型=llama-server(:18099)")


    def _handle_signal(self, signum, frame):
        log(f"\n◇ 收到信号 {signum}，正在优雅停止…")
        self.running = False

    def _save_pid(self):
        try:
            with open(PID_FILE, "w") as f:
                f.write(str(os.getpid()))
        except Exception:
            pass

    def _save_state(self):
        """保存运行状态到JSON"""
        try:
            state = {
                "cycle": self.cycle,
                "grid": self.grid.to_dict(),
                "vitality": self.budget.to_dict(),
                "state": repr(self.state),
                "running_time": time.time() - self.start_time,
                "express_count": self.express_count,
                "silent_count": self.silent_count,
                "sleep_count": self.sleep_count,
                "last_update": datetime.now().isoformat(),
            }
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def run_one_cycle(self):
        """运行一轮"""
        self.cycle += 1

        # ── 1. 九宫演化（纯数学，0成本） ──
        self.grid = self.grid.evolve()

        # ── 2. 同步三态状态 ──
        yin, zhong, yang = self.oscillator.drift(
            self.state,
            phase_int=self.grid.phase,
            grid_diversity=self.grid.compute_diversity(),
        )
        self.state = TernaryState(
            yin_weight=yin,
            zhong_weight=zhong,
            yang_weight=yang,
            remainder=self.remainder_engine.compute_remainder(self.state),
            timestamp=self.cycle,
        )
        self.state = self.remainder_engine.inject_remainder(self.state)

        # ── 2.5 计算真实耗时（用于活力自然衰减） ──
        now = time.time()
        elapsed = now - self._last_cycle_time
        self._last_cycle_time = now

        # ── 2.6 检测用户活动 ──
        user_active = False
        dialog_active = False
        try:
            if os.path.exists(self._activity_log_path):
                mtime = os.path.getmtime(self._activity_log_path)
                if now - mtime < 30:  # 最近30秒内有日志更新→用户活跃
                    user_active = True
            # 检测技能目录是否刚被读取（对话中）
            state_path = os.path.join(SKILL_DIR, "ternary_state.json")
            if os.path.exists(state_path) and now - os.path.getmtime(state_path) < 60:
                dialog_active = True
        except Exception:
            pass

        # ── 3. 五感感知 ──
        events = self.fuser.sense_all(
            cycle=self.cycle,
            vitality=self.budget.current,
            grid_potential=self.grid.potential,
            user_active=user_active,
            dialog_active=dialog_active,
        )

        # ── 4. 活力预算更新 ──
        if self.budget.is_sleeping:
            # 深睡期：不衰减，改为恢复（+3%/轮）
            self.budget.sleep_recover(1)
        else:
            delta = self.fuser.compute_vitality_delta(events)
            self.budget.add(delta)
            self.budget.decay(elapsed)  # 基于真实时间衰减

        # ── 5. 表达冲动计算 ──
        urge = self.fuser.compute_expression_urge(
            self.budget.current, events, self.grid.potential
        )

        # ── 6. 决策：是否表达 ──
        result: Optional[ExpressionResult] = None
        should_express = (urge > 0.5 and self.budget.should_think)

        if should_express:
            # 有冲动且有活力 → 表达
            result = self.expression.express(
                cycle=self.cycle,
                grid=self.grid,
                vitality=self.budget,
                perception_fuser=self.fuser,
                events=events,
            )
            if result.success and result.content:
                self.budget.consume(result.vitality_consumed)
                self.express_count += 1

                # 保存心笺
                save_heart_note(
                    self.cycle, result.content, result.express_type,
                    self.budget.current, self.grid.potential
                )

                # 输出
                log(f"[{self.cycle:4d}] {result.express_type} | 活力={self.budget.current:.0f} | {result.content[:80]}")
            else:
                self.silent_count += 1
        else:
            self.silent_count += 1
            if self.budget.is_sleeping:
                self.sleep_count += 1

        # ── 7. 每20轮输出一次状态摘要（非表达时） ──
        if not should_express and self.cycle % 20 == 0:
            log(f"[{self.cycle:4d}] 【静】势={self.grid.potential:+.3f} "
                f"多={self.grid.compute_diversity():.2f} "
                f"活力={self.budget.current:.0f} "
                f"相={self.grid.get_phase_label()}")

        # ── 8. 持久化 ──
        if self.cycle % 10 == 0 or should_express:
            self._save_state()

        # ── 9. 动态睡眠 ──
        if self.budget.is_sleeping:
            sleep_time = self.config.loop_interval * 3  # 深睡×3
        elif not self.budget.should_think:
            sleep_time = self.config.loop_interval * 2  # 收敛×2
        elif should_express:
            sleep_time = self.config.loop_interval * 1.5  # 表达后多歇
        else:
            sleep_time = self.config.loop_interval

        time.sleep(sleep_time)

    def run_forever(self):
        """永续运行"""
        log("◆ 进入主循环")
        while self.running:
            try:
                self.run_one_cycle()
            except KeyboardInterrupt:
                log(f"\n◇ 收到中断，第{self.cycle}轮后停止")
                break
            except Exception as e:
                log(f"✕ 异常: {e}")
                traceback.print_exc()
                try:
                    err_log = os.path.join(SKILL_DIR, "ternary_err.log")
                    with open(err_log, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.now().isoformat()}] {e}\n{traceback.format_exc()}\n")
                except Exception:
                    pass
                time.sleep(10)  # 出错后等10秒再继续

        # 结束报告
        elapsed = time.time() - self.start_time
        log(f"\n{'='*50}")
        log(f"◇ 引擎停止")
        log(f"  运行: {elapsed:.0f}秒 ({elapsed/3600:.1f}小时)")
        log(f"  轮次: {self.cycle}轮")
        log(f"  表达: {self.express_count}次")
        log(f"  静默: {self.silent_count}次")
        log(f"  深睡: {self.sleep_count}次")
        log(f"  心笺: {HEART_NOTE_DIR}")
        self._save_state()


def main():
    engine = TernaryEngine()
    engine.run_forever()


if __name__ == "__main__":
    main()
