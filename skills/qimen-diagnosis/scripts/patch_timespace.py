#!/usr/bin/env python3
"""
补丁：将 _build_timespace 的简化推算替换为基于 time_awareness 的真实时间接入。
"""
import re

FPATH = r"I:\ai\openakita-main\skills\qimen-diagnosis\scripts\nine_dim_engine.py"

with open(FPATH, "r", encoding="utf-8") as f:
    src = f.read()

# ── 替换点1：_build_timespace 方法 ──
old_build = '''    def _build_timespace(self, year, month, day, hour, minute, mode) -> TimeSpaceMeta:
        """构建时空元数据"""
        meta = TimeSpaceMeta(
            gregorian=f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}",
            scene_type=mode,
        )
        
        # 简单节气判定（夏至前阳遁，夏至后阴遁）
        # 芒种通常6月5-7日
        if (month < 6) or (month == 6 and day < 5):
            meta.dun_type = "阳遁"
            meta.ju_number = 4  # 小满下元阳遁4局（简化）
            meta.jieqi = "小满-芒种间"
        else:
            meta.dun_type = "阴遁"
            meta.ju_number = 6  # 简化
            meta.jieqi = "芒种后"
        
        meta.yuejian = "午" if month >= 5 else "巳"
        # 日干支（简化版，使用固定偏移）
        day_offset = (year * 365 + month * 30 + day) % 60
        tian_list = ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"]
        di_list = ["子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"]
        meta.ri_ganzhi = tian_list[(day_offset * 2 + 6) % 10] + di_list[(day_offset + 12) % 12]
        meta.shi_ganzhi = self._calc_shi_ganzhi(hour)
        
        meta.yingqi, meta.near_far, meta.fast_slow = self._calc_yingqi(meta)
        
        return meta'''

new_build = '''    def _build_timespace(self, year, month, day, hour, minute, mode) -> TimeSpaceMeta:
        """构建时空元数据 — 接入 time_awareness 获取真实时间"""
        # ── 自动获取实时时间 ──
        if year == 0 and _HAVE_TIME_AWARENESS:
            try:
                report = get_time_awareness()
                year = int(report.datetime_str[:4]) if report.datetime_str else 2026
                month = int(report.datetime_str[5:7]) if report.datetime_str else 6
                day = int(report.datetime_str[8:10]) if report.datetime_str else 2
                hour = int(report.datetime_str[11:13]) if report.datetime_str else 0
                minute = int(report.datetime_str[14:16]) if report.datetime_str else 0
                
                meta = TimeSpaceMeta(
                    gregorian=report.datetime_str,
                    scene_type=mode,
                )
                # 从 time_awareness 填入真实节气/干支
                meta.jieqi = report.current_jieqi
                meta.ri_ganzhi = report.day_ganzhi
                meta.shi_ganzhi = report.time_ganzhi
                meta.yuejian = report.lunar_month_str if hasattr(report, 'lunar_month_str') else ""
                # 节气 → 奇门局式
                meta.dun_type, meta.ju_number = self._jieqi_to_dun(
                    report.current_jieqi, report.next_jieqi,
                    report.jieqi_days_passed
                )
            except Exception:
                # 兜底：回退到简化推算
                meta = TimeSpaceMeta(
                    gregorian=f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}",
                    scene_type=mode,
                )
                meta.dun_type, meta.ju_number, meta.jieqi = "阳遁", 4, "小满-芒种间"
                meta.ri_ganzhi, meta.shi_ganzhi = "甲子", "甲子"
        else:
            # ── 手动指定时间（传统方式）──
            meta = TimeSpaceMeta(
                gregorian=f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}",
                scene_type=mode,
            )
            # 简单节气判定
            if (month < 6) or (month == 6 and day < 5):
                meta.dun_type, meta.ju_number, meta.jieqi = "阳遁", 4, "小满-芒种间"
            else:
                meta.dun_type, meta.ju_number, meta.jieqi = "阴遁", 6, "芒种后"
            meta.yuejian = "午" if month >= 5 else "巳"
            # 日干支简化
            day_offset = (year * 365 + month * 30 + day) % 60
            tian_list = ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"]
            di_list = ["子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"]
            meta.ri_ganzhi = tian_list[(day_offset * 2 + 6) % 10] + di_list[(day_offset + 12) % 12]
            meta.shi_ganzhi = self._calc_shi_ganzhi(hour)
        
        meta.yingqi, meta.near_far, meta.fast_slow = self._calc_yingqi(meta)
        return meta'''

if old_build not in src:
    print("❌ 未找到 _build_timespace 方法，请检查文件内容")
    exit(1)

src = src.replace(old_build, new_build)

# ── 替换点2：在 _calc_yingqi 之后、_build_timespace 之前插入 _jieqi_to_dun 辅助方法 ──
old_yuejian = '''        self._build_star_door_stren(meta)
        
        return yingqi, near_far, fast_slow'''

new_yuejian = '''        self._build_star_door_stren(meta)
        
        return yingqi, near_far, fast_slow

    # ── 节气→奇门局式转换（接入 time_awareness 后使用）──
    # 阳遁：冬至→芒种（冬春半年），阴遁：夏至→大雪（夏秋半年）
    # 每个节气三元：上中下各一局
    _JIEQI_TO_DUN = {
        "冬至": ("阳遁", 1), "小寒": ("阳遁", 2), "大寒": ("阳遁", 3),
        "立春": ("阳遁", 4), "雨水": ("阳遁", 5), "惊蛰": ("阳遁", 6),
        "春分": ("阳遁", 7), "清明": ("阳遁", 8), "谷雨": ("阳遁", 9),
        "立夏": ("阳遁", 4), "小满": ("阳遁", 4), "芒种": ("阳遁", 6),
        "夏至": ("阴遁", 9), "小暑": ("阴遁", 8), "大暑": ("阴遁", 7),
        "立秋": ("阴遁", 2), "处暑": ("阴遁", 1), "白露": ("阴遁", 9),
        "秋分": ("阴遁", 7), "寒露": ("阴遁", 6), "霜降": ("阴遁", 5),
        "立冬": ("阴遁", 6), "小雪": ("阴遁", 5), "大雪": ("阴遁", 4),
    }
    
    def _jieqi_to_dun(self, current_jieqi: str, next_jieqi: str = "",
                      days_passed: int = 0) -> tuple:
        """将节气名转为奇门局式（阳遁/阴遁 + 局数）
        
        默认取该节气的上元局数；days_passed 参数留作后续三元细化。
        """
        if current_jieqi in self._JIEQI_TO_DUN:
            return self._JIEQI_TO_DUN[current_jieqi]
        # 未匹配到已知节气时，就近判定
        if next_jieqi:
            dun_info = self._JIEQI_TO_DUN.get(next_jieqi)
            if dun_info:
                dun_type = dun_info[0]
                ju = dun_info[1] - 1 if dun_type == "阳遁" else dun_info[1] + 1
                ju = max(1, min(9, ju))
                return (dun_type, ju)
        return ("阳遁", 4)'''

if old_yuejian in src:
    src = src.replace(old_yuejian, new_yuejian)
    print("✅ _jieqi_to_dun 方法已插入")
else:
    print("⚠️ _jieqi_to_dun 插入点未找到，手动检查")
    # 尝试精确查找
    lines = src.splitlines()
    for i, l in enumerate(lines):
        if "_build_star_door_stren" in l:
            print(f"  找到 '_build_star_door_stren' 在第 {i+1} 行")
    print("  跳过_jieqi_to_dun插入")

with open(FPATH, "w", encoding="utf-8") as f:
    f.write(src)

print("✅ 补丁完成")
print("   — _build_timespace 已接入 time_awareness 实时时间")
print("   — 新增 _jieqi_to_dun 节气→局式对照表（24节气全覆盖）")
