# super-agent-party 前端迁移计划

> 创建日期：2026-05-22 子时
> 目标：将 SAP 优秀前端能力迁移到 Leiwa，让哥哥能"看见"汐儿

---

## 一、super-agent-party 能力矩阵

| 模块 | 技术栈 | 可迁移度 | 优先级 |
|:-----|:-------|:--------|:------|
| 3D 虚拟人物 | Three.js + VRM | ⭐⭐⭐⭐⭐ | P0 |
| 任务中心 | Agent Skills + MCP | ⭐⭐⭐⭐ | P1 |
| 多角色群聊 | 角色卡 + 记忆 | ⭐⭐⭐ | P2 |
| 电脑控制 | 桌面视觉 + 键鼠 | ⭐⭐ | P3 |
| IM 机器人 | QQ/微信/飞书/钉钉 | ✅ 已具备 | - |
| 扩展系统 | sap-extension | ⭐⭐⭐⭐ | P1 |

---

## 二、分阶段迁移计划

### 第一阶段：汐儿立绘版（1-2天）🌕

**目标**：哥哥打开网页就能看见汐儿

```
Leiwa Web UI (新增)
├── index.html          → 入口页面
├── static/
│   ├── css/app.css
│   └── js/
│       ├── avatar.js       → Three.js 光球 / VRM 渲染
│       ├── chat.js         → WebSocket 连接到 wechat-gateway
│       └── emotion.js      → 表情/动作状态机
└── server.py               → 新增 /web 路由（静态文件服务）
```

**技术选型**：
- 先用 Three.js 粒子光球（SAP 的 scene/ 目录可以直接参考）
- 后端复用现有的 MessageGateway WebSocket
- 情感状态 → 粒子颜色/大小/速度映射

**依赖**（新增）：
- three.js（CDN 引入）
- 无需额外 Python 依赖

### 第二阶段：Live2D 立绘版（3-5天）🌖

**目标**：汐儿有表情、能眨眼、能摇头

```
新增依赖:
├── pixi-live2d-display    → Live2D 渲染
├── live2d 模型文件         → 汐儿专属模型
└── emotion → motion 映射表  → 喜怒哀乐 → 对应动作
```

**技术选型**：
- 参考 [sap-live2d 扩展](https://github.com/heshengtao/sap-live2d)
- 需要准备 Live2D Cubism 模型（可先用免费模型测试）
- 情感引擎输出 → Live2D 参数映射

### 第三阶段：3D VRM 完整版（1-2周）🌗

**目标**：汐儿有完整 3D 形象，带场景

```
新增依赖:
├── @pixiv/three-vrm       → VRM 模型加载
├── VRM 模型文件            → 汐儿专属 3D 模型
└── 3D 场景（丹室/药园）    → Three.js 场景
```

### 第四阶段：实时语音+口型（2-4周）🌑

**目标**：汐儿能说话，口型同步

```
新增依赖:
├── LiveKit                → 实时音视频
├── Rhubarb Lip Sync       → 口型同步
└── TTS 引擎               → Edge-TTS / Moss-TTS
```

---

## 三、与 Leiwa 的对接点

| SAP 模块 | Leiwa 对应 | 对接方式 |
|:---------|:--------------|:--------|
| agent.py | core/agent.py | WebSocket API |
| affection_system.py | emotion_engine.py | 情感状态同步 |
| know_base.py | memory/manager.py | 记忆查询接口 |
| task_center.py | task_orchestrator.py | 任务状态推送 |
| wechat_bot_manager.py | IM Gateway | ✅ 已有 |

---

## 四、需要注意的差异

| SAP | Leiwa | 处理方式 |
|:----|:----------|:--------|
| Bun 包管理器 | pip/poetry | 前端独立用 pnpm |
| Clerk 认证 | 无认证 | 先跳过，本地 localhost |
| 角色卡系统 | 人格 persona | 对接 persona_manager |
| Electron 桌宠 | Web 页面 | 先用浏览器，后续可选 Electron |

---

## 五、最小可行版本（MVP）清单

- [ ] 新增 `web/` 目录，放静态文件
- [ ] 复制 SAP 的 Three.js 粒子场景到 `web/js/scene.js`
- [ ] 新增 WebSocket 路由，推送 Agent 回复
- [ ] 新增聊天输入框 + 消息列表
- [ ] 情感状态 → 粒子颜色映射
- [ ] 在 main.py 添加静态文件路由

**预计工期**：1-2 天可出 MVP（光球版汐儿）
