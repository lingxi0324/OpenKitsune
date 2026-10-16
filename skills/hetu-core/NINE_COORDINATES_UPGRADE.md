# nine_transform_coordinates 跨域坐标升级方案

> 现状：`nine_transform_coordinates.json`（3200+ 项）为**药物**的河图洛书九维坐标
> （r1_heaven_number / r2_earth_number / r3_loshu_position / r4_loshu_shift /
> r5_yin_yang / r6_three_talents / r7_four_directions / r8_eight_trigrams / r9_return_degree）。
> 目标：升级为**通用九维坐标**——药物/人事/决策/情志共用同一坐标骨架，成为九维思辨的数学底座。

## 一、升级原则

- **不推倒**：现有 3200+ 药物坐标保留，仅追加 `domain` 字段区分；
- **不硬编码**：坐标语义保持九维可解释（每维有名字、有刻度、有落点），不做黑箱；
- **一石二鸟**：坐标系统同时服务「九变」（跨域编码）与「九维思辨」（九尾议会数学底座）。

## 二、通用坐标 Schema（domain 扩展）

```json
{
  "name": "条目名",
  "domain": "药物 | 人事 | 决策 | 情志 | 通用",
  "coordinate": {
    "r1_heaven_number": 3,
    "r2_earth_number": 8,
    "r3_loshu_position": 4,
    "r4_loshu_shift": 0,
    "r5_yin_yang": 0.8,
    "r6_three_talents": 0.85,
    "r7_four_directions": 0,
    "r8_eight_trigrams": 3,
    "r9_return_degree": 0.85
  },
  "ancient_names": [],
  "modern_aliases": [],
  "category": "药物/人事/决策/情志",
  "description": "一句话说明"
}
```

## 三、跨域语义对照（同一九维在不同域的落点）

| 维 | 药物域 | 人事域 | 决策域 |
|---|---|---|---|
| r1 天数 | 药性本天之气 | 人与生俱来之禀赋 | 决策的天时窗口 |
| r2 地数 | 药材产地/质地 | 所处环境/平台 | 决策的地利条件 |
| r3 洛书位 | 归经宫位 | 在组织/关系中的位次 | 选项在全局中的位置 |
| r4 洛书移 | 君臣佐使之偏移 | 位势变动 | 方案调整空间 |
| r5 阴阳 | 寒热温凉 | 性格阴阳/动静 | 保守-激进偏向 |
| r6 三才 | 天药地合人用 | 天时地利人和 | 天时-资源-执行三要素 |
| r7 四向 | 升降浮沉 | 方向/去留 | 多方向收益分布 |
| r8 八卦 | 卦宫象意 | 人事卦象 | 方案卦象特征 |
| r9 归度 | 药性回归度 | 归宿/契合度 | 方案收敛度 |

## 四、示例条目（新增域，供未来录入）

- **人事·求职转行**：domain=人事，r5_yin_yang=0.6（偏进取），r6_three_talents=0.7，r7_four_directions=1（明确方向），r9_return_degree=0.75；
- **决策·是否跳槽**：domain=决策，r1_heaven_number=7（窗口期），r2_earth_number=9（资源充足），r3_loshu_position=3（进取位），r5_yin_yang=0.4（偏稳健），r9_return_degree=0.8（收敛度高）。

## 五、与九尾议会的接线

- 九尾议会启用时，各宫可读取通用坐标作为**先验权重**（如战略尾读取 r1/r2/r4，风控尾读取 r5/r9）；
- 坐标为可复核数据：任何维度都有名字与刻度，他人可理解、可校验（对齐"不硬编码"约定）；
- 现有药物坐标的 `domain` 标记由 `upgrade_nine_coordinates.py` 一次性补齐（备份后执行）。
