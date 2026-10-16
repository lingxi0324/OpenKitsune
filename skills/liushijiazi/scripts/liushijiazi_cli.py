#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""六十甲子分析工具 CLI"""
import sys
import os
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from liushijiazi_core import *

def print_help():
    print("""
六十甲子综合分析工具 (Liushijiazi CLI)

用法:
  python liushijiazi_cli.py                         今日分析
  python liushijiazi_cli.py --date 2026-05-15       指定日期
  python liushijiazi_cli.py --date 2026-05-15 -h 10 指定时辰
  python liushijiazi_cli.py --date 2026-05-15 -a    所有时辰
  python liushijiazi_cli.py --ganzhi 丁未           查询干支序号/纳音
  python liushijiazi_cli.py --offset 丁未 3         干支偏移
    """)

def main():
    if len(sys.argv) <= 1:
        # 默认：查询今日
        d = date.today()
        now = datetime.now()
        r = query_date(d, hour=now.hour)
        print(format_query_result(r))
        return

    if sys.argv[1] in ('-h', '--help'):
        print_help()
        return

    if sys.argv[1] == '--date':
        date_str = sys.argv[2]
        parts = date_str.split('-')
        d = date(int(parts[0]), int(parts[1]), int(parts[2]))
        
        hour = None
        show_all = False
        
        if '-a' in sys.argv or '--all' in sys.argv:
            show_all = True
        if '-h' in sys.argv:
            idx = sys.argv.index('-h')
            if idx + 1 < len(sys.argv):
                hour = int(sys.argv[idx + 1])
        if '--hour' in sys.argv:
            idx = sys.argv.index('--hour')
            if idx + 1 < len(sys.argv):
                hour = int(sys.argv[idx + 1])
        
        if show_all:
            r = query_date(d)
            print(format_query_result(r))
            print("")
            print("【十二时辰干支】")
            for hr in query_hours_by_date(d):
                print(f"  {hr['时辰']}：{hr['干支']}（{hr['纳音']}）")
        else:
            if hour is None:
                hour = datetime.now().hour
            r = query_date(d, hour=hour)
            print(format_query_result(r))
            print("")
            print(f"【当前时辰】{hour}:00 - {hour+1}:00")
            print(f"  时干支：{r['时辰']['干']}{r['时辰']['支']}（{r['时辰']['纳音']}）")
        
        return

    if sys.argv[1] == '--ganzhi':
        gz = sys.argv[2]
        gan, zhi = gz[0], gz[1]
        seq = get_ganzhi_seq(gan, zhi)
        nayin = get_nayin(gan, zhi)
        print(f"干支：{gz}")
        print(f"序号：{seq}/60")
        print(f"纳音：{nayin}")
        print(f"天干五行：{TIANGAN_WUXING[gan]}")
        print(f"地支五行：{DIZHI_WUXING[zhi]}")
        print(f"六冲：{zhi}冲{LIUCHONG[zhi]}")
        print(f"六合：{zhi}合{LIUHE[zhi]}")
        return

    if sys.argv[1] == '--offset':
        gz = sys.argv[2]
        offset = int(sys.argv[3])
        gan, zhi = gz[0], gz[1]
        new_gz = get_ganzhi_by_offset(gan, zhi, offset)
        if new_gz:
            print(f"{gz} +{'+' if offset >= 0 else ''}{offset} = {new_gz[0]}{new_gz[1]}")

if __name__ == '__main__':
    main()
