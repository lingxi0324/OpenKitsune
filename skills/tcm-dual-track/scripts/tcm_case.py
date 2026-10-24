#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中医一站式病案推演：辨证 + 处方（组成/剂量/自动加减）+ 北斗七星针法。

用法：
  python tcm_case.py "大便粘滞 腹胀 脉沉紧 舌苔白腻" --pulse 沉紧 --tongue 淡胖 --coat 白腻
  python tcm_case.py --complaint "口苦，咽干，目眩" --pulse 弦 --year 2026
  python tcm_case.py "失眠 心悸" --json

输出：
  输入归一化 / 体用检测 / 六经辨证 / 三观四证 / 双规次序
  处方（主方 + 组成剂量 + 加味 + 减味 + 药证映射 + 配伍校验）
  五运六气 / 火候次第 / 潮汐 / 北斗七星针法 / 综合结论
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tcm_dual_track import DualTrackEngine  # noqa: E402
from tcm_engine import (  # noqa: E402
    build_dialectic_input,
    build_prescription,
    dialectic,
    normalize_symptoms,
    plan as acupuncture_plan,
)


def _serialize(obj):
    if is_dataclass(obj):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        return {k: _serialize(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return obj


def run(complaint: str, pulse: str = "", tongue: str = "", coat: str = "",
        year: str = "", specialty: str = "内科",
        with_acupuncture: bool = True) -> dict:
    inp = build_dialectic_input(
        complaint=complaint,
        pulse=pulse,
        tongue=tongue,
        coat=coat,
        specialty=specialty,
        year=year or None,
    )
    result = dialectic(inp)
    lj = result.六经辨证

    # ── 三观四证（许家栋体系，保留原引擎的定性层）──
    legacy = DualTrackEngine().analyze(inp.symptoms, inp.pulse, f"{inp.tongue} {inp.coat}")
    three_views = legacy["three_views"]
    four = legacy["four_syndromes"]
    organs = legacy["organs"]
    channels = legacy["six_channels"]

    # 五脏填补与主经对齐：太阴先脾、少阴先肾、厥阴先肝
    preferred = {
        "太阴病": "脾", "少阴病": "肾", "厥阴病": "肝",
        "太阳病": "肺", "少阳病": "肝", "阳明病": "脾",
    }.get(lj.推荐经 if lj else "")
    if preferred:
        organs = sorted(organs, key=lambda o: 0 if o["organ"] == preferred else 1)

    # ── 双规次序：六经以加权引擎为准，五脏沿用填补表 ──
    dual = DualTrackEngine._dual_track(channels, organs, four)
    if lj and lj.推荐经:
        target = lj.推荐经
        combined = lj.合病检测 or {}
        if isinstance(combined, dict):
            merged = combined.get("合病经") or []
        else:
            merged = getattr(combined, "合病经", [])
        if merged:
            target = f"{lj.推荐经}（合病：{'、'.join(merged)}）"
        dual["steps"][0] = {
            "step": 1,
            "action": "六经开路",
            "target": target,
            "formula": lj.推荐方[0] if lj.推荐方 else "待议方",
            "note": lj.方剂说明 or "路通即止，不可久用。",
        }
    fill_formula = dual["steps"][1]["formula"]
    if " / " in fill_formula:
        dual["steps"][1]["formula"] = fill_formula.split(" / ")[0]

    # ── 处方 ──
    symptom_list = [s for s in inp.symptoms.replace("，", ",").split(",") if s.strip()]
    top_formula = lj.推荐方[0] if (lj and lj.推荐方) else ""
    prescription = (
        build_prescription(top_formula, inp.symptoms) if top_formula else
        {"主方": "", "错误": "六经辨证未给出推荐方，无法生成处方", "组成": []}
    )

    # ── 北斗七星针法 ──
    acupuncture = None
    if with_acupuncture:
        acupuncture = _serialize(acupuncture_plan(
            liujing_result=lj.推荐经 if lj else "",
            symptoms=symptom_list,
            syndrome_name=lj.推荐经 if lj else "",
        ))

    cautions = legacy["cautions"][:]
    if prescription.get("配伍校验", {}).get("冲突"):
        cautions.append("配伍校验未通过：存在十八反/十九畏药对，须调整后方可应用。")
    if prescription.get("方义提示"):
        cautions.append(prescription["方义提示"])

    return {
        "输入归一化": {
            "主诉原文": complaint,
            "归一化症状": inp.symptoms,
            "脉象补全": inp.pulse,
            "舌象": inp.tongue,
            "舌苔": inp.coat,
        },
        "体用检测": _serialize(result.体用检测),
        "六经辨证": _serialize(lj),
        "三观四证": {
            "three_views": three_views,
            "four_syndromes": four,
            "differentiation_steps": legacy["differentiation_steps"],
        },
        "双规次序": dual,
        "方剂分析": result.方剂分析.方剂 if result.方剂分析 else [],
        "处方": prescription,
        "五运六气": _serialize(result.五运六气推演),
        "火候次第": _serialize(result.火候次第),
        "潮汐上下文": _serialize(result.潮汐上下文),
        "北斗七星针法": acupuncture,
        "综合结论": _serialize(result.综合结论),
        "禁忌": cautions,
        "_legacy": {"channels": channels, "organs": organs},
    }


def format_prescription(rx: dict) -> list[str]:
    lines: list[str] = []
    if rx.get("错误"):
        return [f"  {rx['错误']}"]
    head = f"  主方：{rx['主方']}"
    if rx.get("功效"):
        head += f"｜{rx['功效']}"
    lines.append(head)
    lines.append(f"  主治：{rx.get('主治', '')}")
    lines.append(f"  组成：{'、'.join(rx['组成'])}")
    if rx.get("加味"):
        lines.append("  加味：" + "；".join(
            f"{a['剂量文本']}（{a['依据']}→{a['功效']}）" for a in rx["加味"]))
    if rx.get("减味"):
        lines.append("  减味：" + "；".join(f"{r['药物']}（{r['依据']}）" for r in rx["减味"]))
    lines.append(f"  用法：{rx['用法']}")
    check = rx["配伍校验"]
    lines.append(f"  配伍校验：{'通过' if check['通过'] else '未通过'}"
                 + (f"｜冲突：{'；'.join(check['冲突'])}" if check["冲突"] else ""))
    if rx.get("方义提示"):
        lines.append(f"  方义提示：{rx['方义提示']}")
    lines.append("  药证映射：")
    for item in rx["药证映射"][:12]:
        lines.append(f"    {item['药物']}（{item['君臣佐使']}）｜{item['功效']}｜针对：{item['针对']}")
    return lines


def format_text(report: dict) -> str:
    lines = ["=" * 58, "        中医一站式病案推演", "=" * 58]
    norm = report["输入归一化"]
    lines.append(f"主诉：{norm['主诉原文']}")
    lines.append(f"归一化：{norm['归一化症状']}")
    if norm["脉象补全"]:
        lines.append(f"脉象：{norm['脉象补全']}")
    if norm["舌象"] or norm["舌苔"]:
        lines.append(f"舌象：{norm['舌象']} {norm['舌苔']}".strip())

    lines.append("-" * 58)
    lines.append("【体用检测】")
    ty = report.get("体用检测") or {}
    lines.append(f"  体用三型：{ty.get('体用三型', '待辨')}｜体 {ty.get('体总分', '-')} / 用 {ty.get('用总分', '-')}")
    for m in (ty.get("匹配模式") or [])[:2]:
        lines.append(f"  模式：{m.get('模式')}（{m.get('置信度')}）→ {m.get('代表方')}｜{m.get('治法原则')}")

    lines.append("-" * 58)
    lines.append("【六经脉证合参】")
    lj = report.get("六经辨证") or {}
    lines.append(f"  主经：{lj.get('推荐经', '待辨')}（{lj.get('置信度', '-')}）｜体用倾向 {lj.get('体用倾向', '-')}")
    scores = lj.get("各经评分") or {}
    if scores:
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        lines.append("  评分：" + "｜".join(f"{k} {v:.2f}" for k, v in ranked[:4]))
    if lj.get("亚型"):
        lines.append(f"  亚型：{lj['亚型']}")
    cb = lj.get("合病检测")
    if cb and cb.get("合病经"):
        lines.append(f"  合病：{'、'.join(cb['合病经'])}（{cb.get('合病类型', '')}）→ {'、'.join(cb.get('合方推荐', []))}")
    if lj.get("推荐方"):
        lines.append(f"  推荐方：{'、'.join(lj['推荐方'][:4])}")
    if lj.get("六经传变"):
        lines.append(f"  传变：{lj['六经传变']}")

    lines.append("-" * 58)
    lines.append("【三观四证】")
    for name, info in (report["三观四证"]["three_views"] or {}).items():
        lines.append(f"  {name}：{info['conclusion']}")
    for step in report["三观四证"]["differentiation_steps"]:
        extra = f"（{step.get('evidence')}）" if step.get("evidence") else ""
        lines.append(f"  {step['step']}. {step['name']}：{step['conclusion']}{extra}")
    if report["三观四证"]["four_syndromes"]:
        top = report["三观四证"]["four_syndromes"][:4]
        lines.append("  四证指向：" + "；".join(
            f"{i['category']}·{i['subtype']}({i['score']})" for i in top))
    else:
        lines.append("  四证指向：未见明确四证")

    lines.append("-" * 58)
    lines.append("【双规次序】")
    for step in report["双规次序"]["steps"]:
        lines.append(f"  {step['step']}. {step['action']} → {step['target']}｜{step['formula']}")
    lines.append(f"  节奏：{report['双规次序']['sequence']}")

    lines.append("-" * 58)
    lines.append("【处方】")
    lines.extend(format_prescription(report["处方"]))

    wl = report.get("五运六气") or {}
    if wl:
        lines.append("-" * 58)
        lines.append("【五运六气】")
        lines.append(f"  {wl.get('纪元', '')}｜岁运 {wl.get('岁运', '')}"
                     f"｜司天 {wl.get('司天', '')}｜在泉 {wl.get('在泉', '')}"
                     f"｜主气 {wl.get('主气', '')}｜客气 {wl.get('客气', '')}")

    fire = report.get("火候次第") or {}
    if fire:
        lines.append("-" * 58)
        lines.append("【火候次第】")
        lines.append(f"  策略：{fire.get('火候策略', '')}｜疗程：{fire.get('疗程', '')}")
        for s in (fire.get("火候序列") or [])[:3]:
            lines.append(f"  · {s.get('火候')}：{s.get('理由')}")

    acu = report.get("北斗七星针法")
    if acu:
        lines.append("-" * 58)
        lines.append(f"【北斗七星针法】{acu.get('syndrome_name', '')}")
        lines.append("  主穴：" + "、".join(f"{star}{point}" for star, point, _, _ in acu["stars"]))
        lines.append("  针序：" + " → ".join(acu["order"]))
        if acu["additions"]:
            lines.append("  配穴：" + "、".join(acu["additions"]))
        lines.append("  艾灸：" + "；".join(acu["moxibustion"]))
        lines.append("  疗程：" + "；".join(acu["course_plan"]))
        lines.append(f"  要诀：{acu['summary_verse']}")

    lines.append("-" * 58)
    lines.append("【综合结论】")
    cc = report.get("综合结论") or {}
    lines.append(f"  {cc.get('总纲', '')}｜核心病机：{cc.get('核心病机', '')}")
    lines.append(f"  治法：{cc.get('治法方向', '')}｜处方方向：{cc.get('处方方向', '')}")

    lines.append("-" * 58)
    lines.append("【禁忌】")
    for item in report["禁忌"]:
        lines.append(f"  · {item}")
    lines.append("=" * 58)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="中医一站式病案推演：辨证+处方+北斗七星针法")
    parser.add_argument("complaint", nargs="?", default="", help="主诉文本")
    parser.add_argument("--complaint", dest="complaint_opt", default="", help="主诉文本（与位置参数二选一）")
    parser.add_argument("--pulse", default="", help="脉象，如 '沉细'（自动补全为脉沉细）")
    parser.add_argument("--tongue", default="", help="舌质，如 '淡胖'")
    parser.add_argument("--coat", default="", help="舌苔，如 '白腻'")
    parser.add_argument("--year", default="", help="年份（五运六气）")
    parser.add_argument("--specialty", default="内科", help="科室")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--no-acupuncture", action="store_true", help="不生成北斗七星针法")
    parser.add_argument("--formula", default="", help="直接按方名查备选库并出处方，如 '肾气丸'")
    args = parser.parse_args()

    complaint = args.complaint_opt or args.complaint
    if args.formula:
        rx = build_prescription(args.formula, normalize_symptoms(complaint))
        if args.json:
            print(json.dumps(rx, ensure_ascii=False, indent=2, default=str))
        else:
            print("\n".join(format_prescription(rx)))
        return

    if not complaint.strip():
        parser.print_help()
        sys.exit("缺少主诉：请提供主诉文本。")

    report = run(
        complaint=complaint,
        pulse=args.pulse,
        tongue=args.tongue,
        coat=args.coat,
        year=args.year,
        specialty=args.specialty,
        with_acupuncture=not args.no_acupuncture,
    )
    if args.json:
        payload = {k: v for k, v in report.items() if not k.startswith("_")}
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(format_text(report))


if __name__ == "__main__":
    main()
