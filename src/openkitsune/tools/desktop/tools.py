"""
Windows 桌面自动化 - Agent 工具定义

定义供 OpenKitsune Agent 使用的工具
"""

import asyncio
import logging
import sys
from typing import Any

# 平台检查
if sys.platform != "win32":
    raise ImportError(
        f"Desktop automation module is Windows-only. Current platform: {sys.platform}"
    )

logger = logging.getLogger(__name__)


# ==================== 工具定义 ====================

# ==================== Tab-Agent 视觉工具定义 ====================

TAB_AGENT_TOOLS = [
    {
        "name": "segment_object",
        "category": "Vision",
        "description": (
            "Segment objects from an image using LLM vision capability (mimics TAB-Agent's SAM segmentation). "
            "When you need to: (1) Identify specific objects described in natural language from a screenshot/image, "
            "(2) Locate objects without SAM, use a multimodal LLM (like llama-cpp-server with vision model). "
            "Returns object bounding boxes (x1,y1,x2,y2) and confidence scores. "
            "For desktop UI elements, prefer desktop_find_element. For natural objects/photos, use this."
        ),
        "detail": """基于 LLM 视觉能力的对象分割工具（模仿 TAB-Agent 的 SAM 流程）。

**使用方式**：
- 不传 image 参数：自动截取当前屏幕
- 传 image：传入 base64 或图片路径
- description：描述要分割的对象（如 "a red car", "the brown ottoman"）
- 可选：max_objects 限制返回数量
- 可选：refine 模式在已有分割基础上细化

**返回**：对象列表，每个含 object_id、bbox、confidence、description

**适用场景**：
- 照片/截图中的自然对象识别
- 多对象分割
- 在已有分割结果上细化（refine 模式）""",
        "input_schema": {
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Base64 编码图片或文件路径（不填=自动截图）"},
                "description": {"type": "string", "description": "要分割的对象描述"},
                "max_objects": {"type": "integer", "default": 20, "description": "最大返回对象数"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "segment_all_objects",
        "category": "Vision",
        "description": (
            "Detect ALL objects in an image without a specific description (mimics TAB-Agent's full segmentation). "
            "When you need to: (1) Get a complete inventory of objects in a photo, "
            "(2) Understand scene composition before further processing. "
            "Returns all distinct objects with bounding boxes and descriptions."
        ),
        "detail": """自动检测图像中的所有对象（不依赖描述）。

**使用方式**：
- 不传 image 参数：自动截取当前屏幕
- 传入 image：base64 编码图片或文件路径

**返回**：所有检测到的对象列表，含 bbox、confidence、描述""",
        "input_schema": {
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Base64 编码图片或文件路径（不填=自动截图）"},
                "max_objects": {"type": "integer", "default": 50, "description": "最大返回对象数"},
            },
        },
    },
    {
        "name": "spatial_query",
        "category": "Vision",
        "description": (
            "Answer spatial reasoning questions about an image (e.g., 'Is the cat to the left of the dog?', "
            "'What is the red car relative to the building?'). Mimics TAB-Agent spatial reasoning. "
            "When you need to: (1) Determine relative positions, (2) Judge distance relationships, "
            "(3) Identify occlusion/depth order. Returns structured spatial relationships."
        ),
        "detail": """空间关系推理工具（模仿 TAB-Agent 的空间推理）。

**使用方式**：
- question: 空间关系问题（"红色车在建筑左边还是右边？"）
- 可选 image: 不填则自动截图
- 可选 answer_options: 预定义选项如 ["left","right","above","below","front","behind"]

**返回**：问题、答案、推理过程、置信度、对象间空间关系列表""",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "空间关系问题"},
                "image": {"type": "string", "description": "Base64 编码图片或文件路径（不填=自动截图）"},
                "answer_options": {
                    "type": "array", "items": {"type": "string"},
                    "description": "预定义答案选项，如 ['left','right','above','below','front','behind']"
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "track_frames",
        "category": "Vision",
        "description": (
            "Track a target object across a sequence of images/frames (mimics TAB-Agent's VlmFrameExpansion + ExpandFromSecondaryView). "
            "When you need to: (1) Follow an object through a video/photo sequence, "
            "(2) Verify object consistency across frames, (3) Find new angles/views. "
            "Returns tracking results with match scores and bounding boxes."
        ),
        "detail": """时序追踪工具（模仿 TAB-Agent VlmFrameExpansion）。

**使用方式**：
- image_files: 按时间顺序排列的图像文件路径列表
- description: 要追踪的对象描述
- reference_image: 参考帧（包含目标的帧），不填则自动检测
- max_expand_frames: 每方向最大扩展帧数（默认 16）

**返回**：按时间顺序的追踪结果，含 frame_index、has_target、bbox、confidence、match_score""",
        "input_schema": {
            "type": "object",
            "properties": {
                "image_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "按时间顺序排列的图像文件路径列表"
                },
                "description": {"type": "string", "description": "要追踪的对象描述"},
                "reference_image": {"type": "string", "description": "参考帧文件路径（不填=自动检测）"},
                "max_expand_frames": {"type": "integer", "default": 16, "description": "每方向最大扩展帧数"},
            },
            "required": ["image_files", "description"],
        },
    },
]

# 合并所有桌面工具
DESKTOP_TOOLS = [
    {
        "name": "desktop_screenshot",
        "category": "Desktop",
        "description": "Capture Windows desktop screenshot with automatic file saving. When you need to: (1) Show user the desktop state, (2) Capture application windows, (3) Record operation results. IMPORTANT: Must actually call this tool - never say 'screenshot done' without calling. Returns file_path for deliver_artifacts. For browser-only screenshots, use browser_screenshot instead.",
        "detail": """截取 Windows 桌面屏幕截图并保存到文件。

⚠️ **重要警告**：
- 用户要求截图时，必须实际调用此工具
- 禁止不调用就说"截图完成"

**使用流程**：
1. 调用此工具截图
2. 获取返回的 file_path
3. 用 deliver_artifacts(artifacts=[{type:"image", path:file_path, caption:"..."}]) 交付给用户

**适用场景**：
- 桌面应用操作
- 查看整个桌面状态
- 桌面和浏览器混合操作

**可选功能**：
- window_title: 只截取指定窗口
- analyze: 用视觉模型分析截图内容

**注意**：如果只涉及浏览器内的网页操作，请使用 browser_screenshot。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "保存路径（可选），不填则自动生成 desktop_screenshot_YYYYMMDD_HHMMSS.png",
                },
                "window_title": {
                    "type": "string",
                    "description": "可选，只截取指定窗口（模糊匹配标题）",
                },
                "analyze": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否用视觉模型分析截图内容",
                },
                "analyze_query": {
                    "type": "string",
                    "description": "分析查询，如'找到所有按钮'（需要 analyze=true）",
                },
                "auto_ocr": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否自动用视觉模型从截图中提取文字（OCR），默认开启",
                },
                "auto_vision": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否自动用视觉模型理解截图画面（图片内容/布局），默认开启",
                },
            },
            "required": [],
        },
    },
    {
        "name": "desktop_find_element",
        "category": "Desktop",
        "description": "Find desktop UI elements using UIAutomation (fast, accurate) or vision recognition (fallback). When you need to: (1) Locate buttons/menus/icons, (2) Get element positions before clicking, (3) Verify UI state. Supports: natural language ('save button'), name: prefix, id: prefix, type: prefix. For browser webpage elements, use browser_* tools instead.",
        "detail": """查找桌面 UI 元素。优先使用 UIAutomation（快速准确），失败时用视觉识别（通用）。

**支持的查找格式**：
- 自然语言："保存按钮"、"红色图标"
- 按名称："name:保存"
- 按 ID："id:btn_save"
- 按类型："type:Button"

**查找方法**：
- auto: 自动选择（推荐）
- uia: 只用 UIAutomation
- vision: 只用视觉识别

**返回信息**：
- 元素位置（x, y）
- 元素大小
- 元素属性

**注意**：如果操作的是浏览器内的网页元素，请使用 browser_* 工具。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "元素描述，如'保存按钮'、'name:文件'、'id:btn_ok'",
                },
                "window_title": {"type": "string", "description": "可选，限定在某个窗口内查找"},
                "method": {
                    "type": "string",
                    "enum": ["auto", "uia", "vision"],
                    "default": "auto",
                    "description": "查找方法：auto 自动选择，uia 只用 UIAutomation，vision 只用视觉",
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "desktop_click",
        "category": "Desktop",
        "description": "Click desktop elements or coordinates. When you need to: (1) Click buttons/icons in applications, (2) Select menu items, (3) Interact with desktop UI. Supports: element description ('save button'), name: prefix, coordinates ('100,200'). Left/right/middle button and double-click supported. For browser webpage elements, use browser tools (browser_navigate, browser_get_content, etc.).",
        "detail": """点击桌面上的 UI 元素或指定坐标。

**支持的目标格式**：
- 元素描述："保存按钮"、"name:确定"
- 坐标："100,200"

**点击选项**：
- button: left/right/middle
- double: 是否双击

**元素查找方法**：
- auto: 自动选择（推荐）
- uia: 只用 UIAutomation
- vision: 只用视觉识别

**注意**：如果点击的是浏览器内的网页元素，请使用浏览器工具（browser_navigate、browser_get_content 等）。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "元素描述（如'确定按钮'）或坐标（如'100,200'）",
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                    "description": "鼠标按钮",
                },
                "double": {"type": "boolean", "default": False, "description": "是否双击"},
                "method": {
                    "type": "string",
                    "enum": ["auto", "uia", "vision"],
                    "default": "auto",
                    "description": "元素查找方法",
                },
                "window_title": {
                    "type": "string",
                    "description": "可选，限定在某个窗口内查找要点击的元素（推荐：避免命中其它窗口）",
                },
                "modifiers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "同时按住的修饰键，如 ['ctrl']（多选）、['shift']（范围选择）、['ctrl','shift']",
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "desktop_mouse",
        "category": "Desktop",
        "description": (
            "Fine-grained mouse control for web, file managers and games. "
            "Actions: move, move_relative, hover, drag, click, double_click, right_click, "
            "middle_click, down, up, position, scroll. Supports modifier keys "
            "(ctrl/shift/alt) for combined clicks and drags, e.g. ctrl+click multi-select, "
            "ctrl+drag copy, shift+click range select."
        ),
        "detail": """精细鼠标控制（网页 / 文件管理器 / 游戏）。

**action 说明**：
- move: 移动到 (x, y)，可带 duration
- move_relative: 相对移动 (dx, dy)（游戏视角常用）
- hover: 移动到 (x, y) 并停留 pause 秒（触发悬浮菜单）
- drag: 从 (x, y) 拖到 (to_x, to_y)；可带 modifiers（ctrl=复制 / alt=快捷方式）
- click / double_click / right_click / middle_click: 点击 (x, y)
- down / up: 按下/释放鼠标键（长按、拖拽、游戏）
- position: 返回当前鼠标坐标与屏幕尺寸
- scroll: 在 (x, y) 滚动，direction=up/down/left/right，modifiers=['ctrl'] 可缩放

**常用组合**：
- Ctrl+点击多选：{"action":"click","x":..,"y":..,"modifiers":["ctrl"]}
- Shift+点击范围选择：{"action":"click",...,"modifiers":["shift"]}
- Ctrl+拖拽复制文件：{"action":"drag",...,"modifiers":["ctrl"]}
- 框选：down → move → up
- 游戏视角：move_relative(dx, dy)""",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "move",
                        "move_relative",
                        "hover",
                        "drag",
                        "click",
                        "double_click",
                        "right_click",
                        "middle_click",
                        "down",
                        "up",
                        "position",
                        "scroll",
                    ],
                    "description": "鼠标动作",
                },
                "x": {"type": "integer", "description": "屏幕绝对 X 坐标"},
                "y": {"type": "integer", "description": "屏幕绝对 Y 坐标"},
                "dx": {"type": "integer", "description": "相对移动 X 偏移"},
                "dy": {"type": "integer", "description": "相对移动 Y 偏移"},
                "raw": {
                    "type": "boolean",
                    "default": False,
                    "description": "move_relative 时发送原始相对位移（游戏/全屏程序更兼容）",
                },
                "to_x": {"type": "integer", "description": "拖拽终点 X 坐标"},
                "to_y": {"type": "integer", "description": "拖拽终点 Y 坐标"},
                "duration": {"type": "number", "default": 0.3, "description": "移动/拖拽时长（秒）"},
                "pause": {"type": "number", "default": 0.3, "description": "hover 停留秒数"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                    "description": "鼠标按钮",
                },
                "modifiers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "按住的修饰键，如 ['ctrl'] / ['shift'] / ['alt']",
                },
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                    "description": "滚动方向（scroll 使用）",
                },
                "amount": {"type": "integer", "default": 3, "description": "滚动格数"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "desktop_type",
        "category": "Desktop",
        "description": "Type text at current cursor position in desktop applications. When you need to: (1) Enter text in application dialogs, (2) Fill input fields, (3) Type in text editors. Supports Chinese input. Use clear_first=true to replace existing text. For browser webpage forms, use browser tools.",
        "detail": """在当前焦点位置输入文本。

**功能特点**：
- 支持中文输入
- 支持先清空再输入

**参数说明**：
- text: 要输入的文本
- clear_first: 是否先清空（Ctrl+A 后输入）

**使用建议**：
- 先点击目标输入框获得焦点
- 再调用此工具输入

**注意**：如果输入的是浏览器内的网页表单，请使用浏览器工具（browser_navigate、browser_get_content 等）。""",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要输入的文本"},
                "clear_first": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否先清空现有内容（Ctrl+A 后输入）",
                },
                "method": {
                    "type": "string",
                    "enum": ["auto", "paste", "type"],
                    "default": "auto",
                    "description": (
                        "输入方式：auto=优先剪贴板粘贴（避开中文输入法干扰，推荐）；"
                        "paste=只用剪贴板；type=逐字符按键输入"
                    ),
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "desktop_press",
        "category": "Desktop",
        "description": (
            "Press a single keyboard key (Enter, Space, Tab, Escape, Backspace, arrows, F1-F12). "
            "Use when you need to: (1) Submit a form or confirm a dialog with Enter, "
            "(2) Insert a space or navigate with Tab/arrows, (3) Clear a field with Backspace. "
            "For key combinations (Ctrl+C, Alt+F4) use desktop_hotkey instead."
        ),
        "detail": """按下单个按键（可重复）。

**常用按键**：
- enter: 回车/确认
- space: 空格
- tab: 切换焦点
- escape / esc: 取消
- backspace / delete: 删除
- up / down / left / right: 方向键
- home / end / pageup / pagedown
- f1 ~ f12

**参数说明**：
- key: 按键名（不区分大小写）
- times: 按下次数，默认 1

**使用建议**：
- 先点击/聚焦目标控件，再调用此工具
- 组合键请用 desktop_hotkey（如 ['ctrl','c']）""",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "按键名，如 enter、space、tab、escape、backspace、up",
                },
                "times": {
                    "type": "integer",
                    "default": 1,
                    "description": "按下次数",
                },
            },
            "required": ["key"],
        },
    },
    {
        "name": "desktop_key",
        "category": "Desktop",
        "description": (
            "Fine-grained keyboard control: press, down, up, release_all, type, hotkey. "
            "Use down/up to hold keys (games, walk/aim, modifier drag), press with times "
            "for repeated taps, and hotkey for combinations like ['ctrl','shift','esc']."
        ),
        "detail": """精细键盘控制。

**action 说明**：
- press: 按下并释放 key（可 times 重复）
- down: 按住 key 不释放（游戏移动/加速/瞄准）
- up: 释放 key
- release_all: 释放所有仍按住的键（异常恢复）
- type: 输入文本 text（支持中文）
- hotkey: 组合键 keys=['ctrl','shift','esc']

**场景示例**：
- 游戏持续前进：down('w') → 等待 → up('w')
- 连续射击：press('space', times=10, interval=0.05)
- 文件批量重命名：hotkey(['f2']) → type('new name') → press('enter')
- 浏览器无痕窗口：hotkey(['ctrl','shift','n'])""",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["press", "down", "up", "release_all", "type", "hotkey"],
                    "description": "键盘动作",
                },
                "key": {"type": "string", "description": "单个按键，如 enter/space/tab/w/a/f2"},
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "组合键列表（hotkey 使用），如 ['ctrl','c']",
                },
                "text": {"type": "string", "description": "要输入的文本（type 使用）"},
                "times": {"type": "integer", "default": 1, "description": "重复次数（press）"},
                "interval": {
                    "type": "number",
                    "default": 0.1,
                    "description": "重复间隔秒数（press）",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "desktop_hotkey",
        "category": "Desktop",
        "description": "Execute keyboard shortcuts. When you need to: (1) Copy/paste (Ctrl+C/V), (2) Save files (Ctrl+S), (3) Close windows (Alt+F4), (4) Undo/redo (Ctrl+Z/Y), (5) Select all (Ctrl+A). Common shortcuts: ['ctrl','c'], ['ctrl','v'], ['ctrl','s'], ['alt','f4'], ['ctrl','z'].",
        "detail": """执行键盘快捷键。

**常用快捷键**：
- ['ctrl', 'c']: 复制
- ['ctrl', 'v']: 粘贴
- ['ctrl', 'x']: 剪切
- ['ctrl', 's']: 保存
- ['ctrl', 'z']: 撤销
- ['ctrl', 'y']: 重做
- ['ctrl', 'a']: 全选
- ['alt', 'f4']: 关闭窗口
- ['alt', 'tab']: 切换窗口
- ['win', 'd']: 显示桌面

**参数格式**：
keys 是按键数组，如 ['ctrl', 'c']""",
        "input_schema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "按键组合，如 ['ctrl', 'c']、['alt', 'f4']",
                }
            },
            "required": ["keys"],
        },
    },
    {
        "name": "desktop_scroll",
        "category": "Desktop",
        "description": "Scroll mouse wheel in specified direction. When you need to: (1) Scroll page/document content, (2) Navigate long lists, (3) Zoom in/out (with Ctrl). Directions: up/down/left/right. Default amount is 3 scroll units.",
        "detail": """滚动鼠标滚轮。

**支持方向**：
- up: 向上滚动
- down: 向下滚动
- left: 向左滚动
- right: 向右滚动

**参数说明**：
- direction: 滚动方向
- amount: 滚动格数（默认 3）

**适用场景**：
- 滚动页面/文档内容
- 浏览长列表
- 配合 Ctrl 键缩放""",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                    "description": "滚动方向",
                },
                "amount": {"type": "integer", "default": 3, "description": "滚动格数"},
            },
            "required": ["direction"],
        },
    },
    {
        "name": "desktop_window",
        "category": "Desktop",
        "description": "Window management operations. When you need to: (1) List all open windows, (2) Switch to a specific window, (3) Minimize/maximize/restore windows, (4) Close windows. Actions: list, switch, minimize, maximize, restore, close. Use title parameter for targeting specific window (fuzzy match).",
        "detail": """窗口管理操作。

**支持的操作**：
- list: 列出所有窗口
- switch: 切换到指定窗口（激活并置顶）
- minimize: 最小化窗口
- maximize: 最大化窗口
- restore: 恢复窗口
- close: 关闭窗口

**参数说明**：
- action: 操作类型（必填）
- title: 窗口标题（模糊匹配），list 操作不需要

**返回信息**（list 操作）：
- 窗口标题
- 窗口句柄
- 窗口位置和大小""",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "switch", "minimize", "maximize", "restore", "close"],
                    "description": "操作类型",
                },
                "title": {"type": "string", "description": "窗口标题（模糊匹配），list 操作不需要"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "desktop_wait",
        "category": "Desktop",
        "description": "Wait for UI element or window to appear. When you need to: (1) Wait for dialog to open, (2) Wait for loading to complete, (3) Synchronize with application state before next action. Target types: element (UI element), window (window title). Default timeout is 10 seconds.",
        "detail": """等待某个 UI 元素或窗口出现。

**适用场景**：
- 等待对话框打开
- 等待加载完成
- 在下一步操作前同步应用状态

**目标类型**：
- element: 等待 UI 元素
- window: 等待窗口

**参数说明**：
- target: 元素描述或窗口标题
- target_type: 目标类型（默认 element）
- timeout: 超时时间（默认 10 秒）

**返回结果**：
- 成功: 元素/窗口信息
- 超时: 错误信息""",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "元素描述或窗口标题"},
                "target_type": {
                    "type": "string",
                    "enum": ["element", "window"],
                    "default": "element",
                    "description": "目标类型",
                },
                "timeout": {"type": "integer", "default": 10, "description": "超时时间（秒）"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "desktop_inspect",
        "category": "Desktop",
        "description": "Inspect window UI element tree structure for debugging and understanding interface layout. When you need to: (1) Debug UI automation issues, (2) Understand application structure, (3) Find correct element identifiers for clicking/typing. Returns element names, types, and IDs at specified depth.",
        "detail": """检查窗口的 UI 元素树结构（用于调试和了解界面结构）。

**适用场景**：
- 调试 UI 自动化问题
- 了解应用程序界面结构
- 查找正确的元素标识符

**参数说明**：
- window_title: 窗口标题（不填则检查当前活动窗口）
- depth: 元素树遍历深度（默认 2）

**返回信息**：
- 元素名称
- 元素类型
- 元素 ID
- 元素位置
- 子元素列表""",
        "input_schema": {
            "type": "object",
            "properties": {
                "window_title": {
                    "type": "string",
                    "description": "窗口标题，不填则检查当前活动窗口",
                },
                "depth": {"type": "integer", "default": 2, "description": "元素树遍历深度"},
            },
            "required": [],
        },
    },
    {
        "name": "desktop_batch",
        "category": "Desktop",
        "description": (
            "Execute multiple desktop automation actions atomically in sequence. "
            "Use when you need to perform several quick operations (click, type, hotkey) "
            "without screenshots between each step. Each action is a dict with 'tool' "
            "and 'params' keys. Reduces round-trips for multi-step UI interactions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {
                                "type": "string",
                                "enum": [
                                    "desktop_click",
                                    "desktop_mouse",
                                    "desktop_type",
                                    "desktop_press",
                                    "desktop_key",
                                    "desktop_hotkey",
                                    "desktop_scroll",
                                    "desktop_wait",
                                ],
                                "description": "The desktop tool to execute.",
                            },
                            "params": {
                                "type": "object",
                                "description": "Parameters for the tool.",
                            },
                        },
                        "required": ["tool", "params"],
                    },
                    "description": "Array of actions to execute in sequence.",
                },
            },
            "required": ["actions"],
        },
    },
    {
        "name": "desktop_macro",
        "category": "Desktop",
        "description": (
            "Run a coordinated mouse+keyboard macro: an ordered list of desktop steps with "
            "per-step delay, optional repeat. Use for multi-step workflows that must not be "
            "interleaved with screenshots, e.g. ctrl+click multi-select then F2 rename, "
            "game combos (hold key + move mouse + click), drag-and-drop with ctrl held, "
            "or opening a file and typing into it."
        ),
        "detail": """鼠标 + 键盘协同宏（原子序列）。

**steps 每项**：
- tool: desktop_mouse / desktop_key / desktop_click / desktop_type /
        desktop_press / desktop_hotkey / desktop_scroll / desktop_wait
- params: 对应工具参数
- delay_ms: 该步执行后等待毫秒（0~5000）

**顶层参数**：
- repeat: 重复次数（1~20）
- interval_ms: 每轮之间等待毫秒
- stop_on_error: 出错是否中止（默认 true）
- release_at_end: 结束时释放所有按键/鼠标键（默认 true，防卡键）
- focus_window: 执行前先激活的目标窗口标题（模糊匹配）。**强烈建议填写**：
  组合开始时若目标窗口尚未获得焦点，type/hotkey 可能落空；核心引擎会先
  激活该窗口并等待焦点沉降再执行序列。
- focus_delay_ms: 激活窗口后的焦点沉降等待毫秒（默认 250）

**示例：Ctrl+点击多选后重命名**
```json
{"steps":[
  {"tool":"desktop_mouse","params":{"action":"click","x":100,"y":200,"modifiers":["ctrl"]}},
  {"tool":"desktop_key","params":{"action":"hotkey","keys":["f2"]},"delay_ms":200},
  {"tool":"desktop_key","params":{"action":"type","text":"renamed"},"delay_ms":100},
  {"tool":"desktop_key","params":{"action":"press","key":"enter"}}
]}
```

**示例：游戏连招（按住 W + 鼠标移动 + 连点）**
```json
{"steps":[
  {"tool":"desktop_key","params":{"action":"down","key":"w"}},
  {"tool":"desktop_mouse","params":{"action":"move_relative","dx":120,"dy":0}},
  {"tool":"desktop_mouse","params":{"action":"click","modifiers":[]},"delay_ms":50}
],"repeat":3,"interval_ms":100}
```""",
        "input_schema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string", "description": "要执行的桌面工具名"},
                            "params": {"type": "object", "description": "工具参数"},
                            "delay_ms": {
                                "type": "integer",
                                "default": 0,
                                "minimum": 0,
                                "maximum": 5000,
                                "description": "该步之后等待毫秒",
                            },
                        },
                        "required": ["tool"],
                    },
                    "description": "按顺序执行的步骤列表（最多 50 步）",
                },
                "repeat": {
                    "type": "integer",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 20,
                    "description": "重复轮数",
                },
                "interval_ms": {
                    "type": "integer",
                    "default": 0,
                    "minimum": 0,
                    "maximum": 5000,
                    "description": "每轮之间的等待毫秒",
                },
                "stop_on_error": {"type": "boolean", "default": True},
                "release_at_end": {"type": "boolean", "default": True},
                "focus_window": {
                    "type": "string",
                    "description": "执行前先激活的目标窗口标题（模糊匹配），避免 type/hotkey 因焦点未就绪而落空",
                },
                "focus_delay_ms": {
                    "type": "integer",
                    "default": 400,
                    "minimum": 0,
                    "maximum": 5000,
                    "description": "激活窗口后的焦点沉降等待毫秒（新启动窗口可调大）",
                },
                "default_step_delay_ms": {
                    "type": "integer",
                    "default": 120,
                    "minimum": 0,
                    "maximum": 5000,
                    "description": (
                        "未显式给 delay_ms 的步骤的默认步间延迟毫秒；Windows 下紧随注入键"
                        "后的 WM_CHAR 突发可能被窗口丢弃，默认延迟可显著提高组合可靠性，"
                        "显式 delay_ms=0 表示立即执行"
                    ),
                },
            },
            "required": ["steps"],
        },
    },
]


# ==================== 工具处理器 ====================


class DesktopToolHandler:
    """
    桌面工具处理器

    处理 Agent 的工具调用请求
    """

    def __init__(self):
        self._controller = None

    @property
    def controller(self):
        """懒加载控制器"""
        if self._controller is None:
            from .controller import get_controller

            self._controller = get_controller()
        return self._controller

    async def handle(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        处理工具调用

        Args:
            tool_name: 工具名称
            params: 参数字典

        Returns:
            结果字典
        """
        try:
            if tool_name == "desktop_screenshot":
                return await self._handle_screenshot(params)
            elif tool_name == "desktop_find_element":
                return await self._handle_find_element(params)
            elif tool_name == "desktop_click":
                return await self._handle_click(params)
            elif tool_name == "desktop_mouse":
                return self._handle_mouse(params)
            elif tool_name == "desktop_type":
                return self._handle_type(params)
            elif tool_name == "desktop_press":
                return self._handle_press(params)
            elif tool_name == "desktop_key":
                return self._handle_key(params)
            elif tool_name == "desktop_hotkey":
                return self._handle_hotkey(params)
            elif tool_name == "desktop_scroll":
                return self._handle_scroll(params)
            elif tool_name == "desktop_window":
                return self._handle_window(params)
            elif tool_name == "desktop_wait":
                return await self._handle_wait(params)
            elif tool_name == "desktop_inspect":
                return self._handle_inspect(params)
            elif tool_name == "desktop_batch":
                return await self._handle_batch(params)
            elif tool_name == "desktop_macro":
                return await self._handle_macro(params)
            # Tab-Agent 视觉工具
            elif tool_name == "segment_object":
                return await self._handle_segment_object(params)
            elif tool_name == "segment_all_objects":
                return await self._handle_segment_all_objects(params)
            elif tool_name == "spatial_query":
                return await self._handle_spatial_query(params)
            elif tool_name == "track_frames":
                return await self._handle_track_frames(params)
            # End Tab-Agent tools
            else:
                return {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return {"error": str(e)}

    async def _handle_screenshot(self, params: dict) -> dict:
        """处理截图请求 - 截图保存到桌面，自动触发视觉分析"""
        import os
        from datetime import datetime

        path = params.get("path")
        window_title = params.get("window_title")
        analyze = params.get("analyze", False)
        analyze_query = params.get("analyze_query")
        auto_ocr = params.get("auto_ocr", True)  # 自动提取文字
        auto_vision = params.get("auto_vision", True)  # 自动视觉分析（调用 _call_vision_model）

        # 截图
        img = self.controller.screenshot(window_title=window_title)

        # 生成保存路径
        if not path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"desktop_screenshot_{timestamp}.png"
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            if os.path.exists(desktop_path):
                path = os.path.join(desktop_path, filename)
            else:
                path = filename

        # 保存截图（总是保存，便于后续分析）
        try:
            from pathlib import Path

            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.controller.capture.save(img, path)
        except OSError as e:
            # 桌面目录可能被 OneDrive 重定向 / 受控文件夹访问保护，写入会被拒。
            # 回退到项目 data 目录，避免整个截图工具因保存失败而不可用。
            logger.warning(f"Save screenshot to '{path}' failed ({e}); using fallback dir")
            from pathlib import Path

            try:
                from ...config import settings

                fallback_dir = Path(settings.project_root) / "data" / "desktop" / "screenshots" / "adhoc"
            except Exception:
                import tempfile

                fallback_dir = Path(tempfile.gettempdir()) / "openkitsune_screenshots"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            path = str(fallback_dir / Path(path).name)
            self.controller.capture.save(img, path)
        abs_path = os.path.abspath(path)

        # 获取文件 URL（本地 HTTP 服务）
        file_url = None
        try:
            file_url = await self.controller.screenshot_url(path)
        except Exception as e:
            logger.debug(f"Screenshot URL failed: {e}")

        result: dict = {
            "success": True,
            "file_path": abs_path,
            "file_url": file_url,
            "width": img.width,
            "height": img.height,
        }

        # 坐标空间说明：窗口截图的像素坐标需要加上窗口原点才是屏幕绝对坐标，
        # 否则模型会拿窗口内坐标去点击，落到窗口外。
        window_bbox = None
        if window_title:
            try:
                window = self.controller.uia.find_window_fuzzy(window_title, timeout=2.0)
                if window and window.bbox:
                    window_bbox = window.bbox.to_tuple()
            except Exception as e:
                logger.debug(f"Window bbox lookup failed: {e}")

        try:
            screen_size = list(self.controller.capture.get_screen_size(0))
        except Exception:
            screen_size = [img.width, img.height]

        result["window_title"] = window_title
        result["window_bbox"] = window_bbox
        result["screen_size"] = screen_size
        result["coordinate_space"] = "window" if window_bbox else "screen"
        if window_bbox:
            result["window_origin"] = [window_bbox[0], window_bbox[1]]

        # 视觉分析（如果启用）
        if analyze:
            analysis = await self.controller.analyze_screen(
                window_title=window_title,
                query=analyze_query,
            )
            result["analysis"] = analysis

        # 自动 OCR + 视觉语义分析：并行调用，避免串行等待（本地视觉模型较慢）
        if auto_ocr or auto_vision:
            from .vision.analyzer import get_vision_analyzer

            analyzer = get_vision_analyzer()
            tasks = []
            if auto_ocr:
                tasks.append(analyzer.extract_text(img))
            if auto_vision:
                tasks.append(analyzer.analyze_page(img))

            gathered = await asyncio.gather(*tasks, return_exceptions=True)
            idx = 0

            if auto_ocr:
                ocr_result = gathered[idx]
                idx += 1
                if isinstance(ocr_result, Exception):
                    logger.debug(f"OCR failed: {ocr_result}")
                    result["ocr_text"] = None
                    result["extracted_text_success"] = False
                elif ocr_result and ocr_result.success:
                    result["ocr_text"] = ocr_result.answer
                    result["ocr_elements"] = ocr_result.elements
                    result["extracted_text_success"] = True
                else:
                    result["ocr_text"] = None
                    result["extracted_text_success"] = False

            if auto_vision:
                vision_result = gathered[idx]
                if isinstance(vision_result, Exception):
                    logger.debug(f"Vision analysis failed: {vision_result}")
                    result["vision_analysis"] = None
                    result["vision_success"] = False
                elif vision_result and vision_result.success:
                    result["vision_analysis"] = vision_result.answer
                    result["vision_success"] = True
                else:
                    result["vision_analysis"] = None
                    result["vision_success"] = False

        return result

    async def _handle_find_element(self, params: dict) -> dict:
        """处理查找元素请求"""
        target = params.get("target")
        window_title = params.get("window_title")
        method = params.get("method", "auto")

        element = await self.controller.find_element(
            target=target,
            window_title=window_title,
            method=method,
        )

        if element:
            return {
                "success": True,
                "found": True,
                "element": element.to_dict(),
            }
        else:
            return {
                "success": True,
                "found": False,
                "message": f"Element not found: {target}",
            }

    async def _handle_click(self, params: dict) -> dict:
        """处理点击请求"""
        target = params.get("target")
        button = params.get("button", "left")
        double = params.get("double", False)
        method = params.get("method", "auto")
        window_title = params.get("window_title")

        result = await self.controller.click(
            target=target,
            button=button,
            double=double,
            method=method,
            window_title=window_title,
            modifiers=params.get("modifiers") or None,
        )

        return result.to_dict()

    def _handle_mouse(self, params: dict) -> dict:
        """精细鼠标控制（移动/拖拽/组合点击/按下释放/滚动/位置）"""
        action = str(params.get("action") or "").lower()
        button = params.get("button", "left")
        modifiers = params.get("modifiers") or None
        x = params.get("x")
        y = params.get("y")

        def _int(value: Any) -> int:
            return int(value)

        try:
            if action == "position":
                pos = self.controller.mouse_position()
                size = self.controller.mouse.get_screen_size()
                return {
                    "success": True,
                    "action": "position",
                    "position": [int(pos[0]), int(pos[1])],
                    "screen_size": [int(size[0]), int(size[1])],
                    "message": f"Mouse at ({pos[0]}, {pos[1]}), screen {size[0]}x{size[1]}",
                }

            if action == "move":
                if x is None or y is None:
                    return {"error": "move requires x and y"}
                return self.controller.mouse.move_to(
                    _int(x), _int(y), duration=params.get("duration")
                ).to_dict()

            if action == "move_relative":
                dx = params.get("dx", 0)
                dy = params.get("dy", 0)
                return self.controller.mouse.move_relative(
                    _int(dx),
                    _int(dy),
                    duration=params.get("duration"),
                    raw=bool(params.get("raw", False)),
                ).to_dict()

            if action == "hover":
                if x is None or y is None:
                    return {"error": "hover requires x and y"}
                return self.controller.mouse.hover(
                    _int(x), _int(y), pause=float(params.get("pause", 0.3))
                ).to_dict()

            if action == "drag":
                to_x, to_y = params.get("to_x"), params.get("to_y")
                if None in (x, y, to_x, to_y):
                    return {"error": "drag requires x, y, to_x, to_y"}
                return self.controller.drag(
                    _int(x),
                    _int(y),
                    _int(to_x),
                    _int(to_y),
                    duration=float(params.get("duration", 0.5)),
                    button=button,
                    modifiers=modifiers,
                ).to_dict()

            if action in ("click", "double_click", "right_click", "middle_click"):
                if x is not None and y is not None:
                    pos: tuple[int, int] | None = (_int(x), _int(y))
                elif action in ("click", "double_click") and params.get("target"):
                    resolved = self.controller.mouse._resolve_target(params["target"])
                    pos = (int(resolved[0]), int(resolved[1]))
                else:
                    pos = None

                if action == "right_click":
                    button = "right"
                elif action == "middle_click":
                    button = "middle"
                clicks = 2 if action == "double_click" else 1

                return self.controller.mouse.click(
                    pos[0] if pos else None,
                    pos[1] if pos else None,
                    button=button,
                    clicks=clicks,
                    modifiers=modifiers,
                ).to_dict()

            if action in ("down", "up"):
                if action == "down":
                    return self.controller.mouse_down(
                        button=button,
                        x=_int(x) if x is not None else None,
                        y=_int(y) if y is not None else None,
                    ).to_dict()
                return self.controller.mouse_up(
                    button=button,
                    x=_int(x) if x is not None else None,
                    y=_int(y) if y is not None else None,
                ).to_dict()

            if action == "scroll":
                return self.controller.scroll(
                    direction=params.get("direction", "down"),
                    amount=int(params.get("amount", 3)),
                    x=_int(x) if x is not None else None,
                    y=_int(y) if y is not None else None,
                    modifiers=modifiers,
                ).to_dict()

            return {"error": f"Unknown mouse action: {action}"}
        except Exception as e:
            return {"error": str(e)}

    def _handle_type(self, params: dict) -> dict:
        """处理输入请求"""
        text = params.get("text", "")
        clear_first = params.get("clear_first", False)
        method = params.get("method", "auto")

        result = self.controller.type_text(text, clear_first=clear_first, method=method)
        return result.to_dict()

    def _handle_press(self, params: dict) -> dict:
        """处理单键按下请求（enter / space / tab / esc / arrows ...）"""
        key = params.get("key", "")
        times = params.get("times", 1)

        if not key:
            return {"error": "No key provided"}

        try:
            times = int(times or 1)
        except (TypeError, ValueError):
            times = 1

        result = self.controller.press(key, times=times)
        return result.to_dict()

    def _handle_key(self, params: dict) -> dict:
        """精细键盘控制（press/down/up/release_all/type/hotkey）"""
        action = str(params.get("action") or "").lower()
        key = str(params.get("key") or "").strip()
        text = params.get("text", "")
        keys = params.get("keys") or []
        times = int(params.get("times", 1) or 1)
        interval = float(params.get("interval", 0.1) or 0.1)

        try:
            if action == "press":
                if not key:
                    return {"error": "press requires key"}
                if times > 1:
                    results = []
                    for _ in range(min(times, 100)):
                        results.append(self.controller.press(key).to_dict())
                        if interval > 0:
                            import time as _time

                            _time.sleep(interval)
                    return {
                        "success": all(r.get("success") for r in results),
                        "action": "press",
                        "target": key,
                        "message": f"Pressed {key} {len(results)} times",
                        "results": results,
                    }
                return self.controller.press(key).to_dict()

            if action == "down":
                if not key:
                    return {"error": "down requires key"}
                return self.controller.key_down(key).to_dict()

            if action == "up":
                if not key:
                    return {"error": "up requires key"}
                return self.controller.key_up(key).to_dict()

            if action == "release_all":
                return self.controller.release_all_keys().to_dict()

            if action == "type":
                return self.controller.type_text(str(text)).to_dict()

            if action == "hotkey":
                if not keys:
                    return {"error": "hotkey requires keys"}
                return self.controller.hotkey(*[str(k) for k in keys]).to_dict()

            return {"error": f"Unknown key action: {action}"}
        except Exception as e:
            return {"error": str(e)}

    def _handle_hotkey(self, params: dict) -> dict:
        """处理快捷键请求"""
        keys = params.get("keys", [])

        if not keys:
            return {"error": "No keys provided"}

        result = self.controller.hotkey(*keys)
        return result.to_dict()

    def _handle_scroll(self, params: dict) -> dict:
        """处理滚动请求"""
        direction = params.get("direction", "down")
        amount = params.get("amount", 3)

        result = self.controller.scroll(direction, amount)
        return result.to_dict()

    def _handle_window(self, params: dict) -> dict:
        """处理窗口操作请求"""
        action = params.get("action")
        title = params.get("title")

        if action == "list":
            windows = self.controller.list_windows()
            return {
                "success": True,
                "windows": [w.to_dict() for w in windows],
                "count": len(windows),
            }

        result = self.controller.window_action(action, title)
        return result.to_dict()

    async def _handle_wait(self, params: dict) -> dict:
        """处理等待请求"""
        target = params.get("target")
        target_type = params.get("target_type", "element")
        timeout = params.get("timeout", 10)

        if target_type == "window":
            found = await self.controller.wait_for_window(target, timeout=timeout)
            return {
                "success": True,
                "found": found,
                "target": target,
                "target_type": "window",
            }
        else:
            element = await self.controller.wait_for_element(target, timeout=timeout)
            if element:
                return {
                    "success": True,
                    "found": True,
                    "element": element.to_dict(),
                }
            else:
                return {
                    "success": True,
                    "found": False,
                    "message": f"Element not found within {timeout}s: {target}",
                }

    def _handle_inspect(self, params: dict) -> dict:
        """处理检查请求"""
        window_title = params.get("window_title")
        depth = params.get("depth", 2)

        tree = self.controller.inspect(window_title=window_title, depth=depth)
        text = self.controller.inspect_text(window_title=window_title, depth=depth)

        return {
            "success": True,
            "tree": tree,
            "text": text,
        }

    async def _handle_batch(self, params: dict) -> dict:
        """Execute multiple desktop actions atomically in sequence.

        参考 CC computer_batch：原子化批量执行。
        """
        actions = params.get("actions", [])
        if not actions:
            return {"error": "desktop_batch requires a non-empty 'actions' array."}
        if len(actions) > 20:
            return {"error": "desktop_batch supports at most 20 actions per call."}

        allowed = {
            "desktop_click",
            "desktop_mouse",
            "desktop_type",
            "desktop_press",
            "desktop_key",
            "desktop_hotkey",
            "desktop_scroll",
            "desktop_wait",
        }
        results = []
        for i, action in enumerate(actions):
            tool = action.get("tool", "")
            action_params = action.get("params", {})
            if tool not in allowed:
                results.append({"step": i, "error": f"Tool '{tool}' not allowed in batch."})
                continue
            try:
                result = await self.handle(tool, action_params)
                results.append({"step": i, "result": result})
            except Exception as e:
                results.append({"step": i, "error": str(e)})
                break  # abort on first failure for atomicity

        return {
            "success": all("error" not in r for r in results),
            "steps_completed": len(results),
            "results": results,
        }

    async def _handle_macro(self, params: dict) -> dict:
        """鼠标 + 键盘协同宏：委派 DesktopController.macro 核心执行引擎。

        编排/白名单/重复/中止/兜底释放全部由核心方法负责（controller.py），
        此处只做参数透传与校验快路径。
        """
        steps = params.get("steps") or []
        if not isinstance(steps, list) or not steps:
            return {"error": "desktop_macro requires a non-empty 'steps' array."}
        if len(steps) > 50:
            return {"error": "desktop_macro supports at most 50 steps per call."}

        try:
            repeat = max(1, min(int(params.get("repeat", 1) or 1), 20))
        except (TypeError, ValueError):
            repeat = 1
        try:
            interval_ms = max(0, min(int(params.get("interval_ms", 0) or 0), 5000))
        except (TypeError, ValueError):
            interval_ms = 0
        try:
            focus_delay_ms = max(0, min(int(params.get("focus_delay_ms", 400) or 400), 5000))
        except (TypeError, ValueError):
            focus_delay_ms = 400
        try:
            default_step_delay_ms = max(
                0, min(int(params.get("default_step_delay_ms", 120) or 120), 5000)
            )
        except (TypeError, ValueError):
            default_step_delay_ms = 120

        stop_on_error = bool(params.get("stop_on_error", True))
        release_at_end = bool(params.get("release_at_end", True))
        focus_window = params.get("focus_window") or None

        result = await asyncio.to_thread(
            self.controller.macro,
            steps,
            repeat=repeat,
            interval_ms=interval_ms,
            stop_on_error=stop_on_error,
            release_at_end=release_at_end,
            focus_window=focus_window,
            focus_delay_ms=focus_delay_ms,
            default_step_delay_ms=default_step_delay_ms,
        )
        return result

    # ========== Tab-Agent 视觉工具处理器 ==========

    async def _handle_segment_object(self, params: dict) -> dict:
        """Tab-Agent 风格对象分割"""
        import base64
        from io import BytesIO

        from PIL import Image as PILImage

        from .vision.segmenter import LlmSegmenter

        description = params.get("description", "")
        image_data = params.get("image", "")
        max_objects = params.get("max_objects", 20)

        if image_data and not image_data.startswith("data:") and not image_data.startswith("http"):
            img = PILImage.open(image_data)
        elif image_data and image_data.startswith("data:"):
            img = PILImage.open(BytesIO(base64.b64decode(image_data.split(",")[1])))
        else:
            img = None

        segmenter = LlmSegmenter()
        results = await segmenter.segment(image=img, description=description, max_objects=max_objects)

        return {"success": True, "count": len(results), "objects": results}

    async def _handle_segment_all_objects(self, params: dict) -> dict:
        """Tab-Agent 风格全目标分割"""
        import base64
        from io import BytesIO

        from PIL import Image as PILImage

        from .vision.segmenter import LlmSegmenter

        image_data = params.get("image", "")
        max_objects = params.get("max_objects", 50)

        if image_data:
            if image_data.startswith("data:"):
                img = PILImage.open(BytesIO(base64.b64decode(image_data.split(",")[1])))
            elif not image_data.startswith("http"):
                img = PILImage.open(image_data)
            else:
                from urllib.request import urlopen
                img = PILImage.open(BytesIO(urlopen(image_data).read()))
        else:
            img = None

        segmenter = LlmSegmenter()
        results = await segmenter.segment_all(image=img, max_objects=max_objects)

        return {"success": True, "count": len(results), "objects": results}

    async def _handle_spatial_query(self, params: dict) -> dict:
        """Tab-Agent 风格空间推理"""
        import base64
        from io import BytesIO

        from PIL import Image as PILImage

        from .vision.spatial import SpatialReasoner

        question = params.get("question", "")
        image_data = params.get("image", "")
        answer_options = params.get("answer_options")

        if image_data:
            if image_data.startswith("data:"):
                img = PILImage.open(BytesIO(base64.b64decode(image_data.split(",")[1])))
            elif not image_data.startswith("http"):
                img = PILImage.open(image_data)
            else:
                from urllib.request import urlopen
                img = PILImage.open(BytesIO(urlopen(image_data).read()))
        else:
            img = None

        reasoner = SpatialReasoner()
        result = await reasoner.query(question=question, image=img, answer_options=answer_options)

        return {"success": True, "result": result}

    async def _handle_track_frames(self, params: dict) -> dict:
        """Tab-Agent 风格时序追踪"""
        import os

        from .vision.tracker import TemporalTracker

        image_files = params.get("image_files", [])
        description = params.get("description", "")
        reference_image = params.get("reference_image")
        max_expand = params.get("max_expand_frames", 16)

        if image_files:
            valid_files = [f for f in image_files if os.path.exists(f)]
            image_files = valid_files

        tracker = TemporalTracker()
        results = await tracker.track_frames(
            image_files=image_files,
            description=description,
            reference_image=reference_image,
            max_expand_frames=max_expand,
        )

        return {"success": True, "tracked_count": len(results), "results": results}


# 全局工具处理器
_handler: DesktopToolHandler | None = None


def get_tool_handler() -> DesktopToolHandler:
    """获取全局工具处理器"""
    global _handler
    if _handler is None:
        _handler = DesktopToolHandler()
    return _handler


def register_desktop_tools(agent: Any) -> None:
    """
    注册桌面工具到 Agent

    Args:
        agent: OpenKitsune Agent 实例
    """
    handler = get_tool_handler()

    # 注册工具定义
    if hasattr(agent, "register_tools"):
        agent.register_tools(DESKTOP_TOOLS)

    # 注册处理器
    if hasattr(agent, "register_tool_handler"):
        for tool in DESKTOP_TOOLS:
            agent.register_tool_handler(tool["name"], handler.handle)

    logger.info(f"Registered {len(DESKTOP_TOOLS)} desktop tools")
