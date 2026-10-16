"""
OpenKitsune 式知识内化层 — 函数调用版
====================================
核心设计：
1. 知识域全量注册为 Function（name + description + scenarios）
2. 九宫状态以纯文本注入 system prompt 做软引导
3. 无 IF-THEN 路由、无固定余弦映射
4. LLM 自主决策调用哪些知识函数

数据源：我的文件夹/knowledge/ 下的 8 个知识域目录 + 总索引
"""

import os
import json
import time
import hashlib
from pathlib import Path
from typing import Optional, Union

# ============================================================
# 配置常量
# ============================================================

KNOWLEDGE_ROOT = Path(r"I:\ai\openakita-main\我的文件夹\knowledge")
LOG_DIR = Path(__file__).resolve().parent / "logs" / "knowledge_call"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 调用上限：单次对话最多调用的知识函数数
MAX_CALLS_PER_TURN = 5

# 缓存 TTL：相同查询结果缓存秒数（30分钟）
CACHE_TTL = 1800

# 支持的文件扩展名（读取时自动过滤）
READABLE_EXTS = {".md", ".txt", ".json", ".jsonl", ".py", ".yaml", ".yml", ".csv"}

# ============================================================
# 函数注册表 — 8 个知识域（OpenKitsune 式，无任何硬编码路由）
# ============================================================

FUNCTIONS = {
    "丹道": {
        "name": "read_dandao_knowledge",
        "description": (
            "丹药配伍、丹法修行、九转金丹、丹炉火候、"
            "内丹外丹等丹道体系知识"
        ),
        "scenarios": (
            "炼丹方法、丹药配方、丹法修行、丹炉火候控制相关问题时调用"
        ),
        "source": "丹道/",
        "is_file": False,
    },
    "医藏": {
        "name": "read_medical_knowledge",
        "description": (
            "伤寒论、金匮要略、辅行诀、温病条辨、神农本草经等"
            "中医经典医藏典籍"
        ),
        "scenarios": (
            "辨证论治、方剂配伍、六经病机、本草药性分析时调用"
        ),
        "source": "医藏/",
        "is_file": False,
    },
    "易经": {
        "name": "read_yijing_knowledge",
        "description": (
            "河图洛书、八卦六爻、象数易理、梅花易数、"
            "焦氏易林等易学体系"
        ),
        "scenarios": (
            "河洛推演、卦象分析、阴阳五行、易理阐释时调用"
        ),
        "source": "易经/",
        "is_file": False,
    },
    "道藏": {
        "name": "read_daocang_knowledge",
        "description": (
            "道家经典、内丹修行、玄门义理、清静经、"
            "道德经、南华经等道藏典籍"
        ),
        "scenarios": (
            "道家思想、修行义理、玄门义理、道教经典探讨时调用"
        ),
        "source": "道藏/",
        "is_file": False,
    },
    "灵汐": {
        "name": "read_lingxi_knowledge",
        "description": (
            "灵汐人格档案、阅历记录、日常日记、"
            "感受沉淀等专属记忆资料"
        ),
        "scenarios": (
            "自我反思、人格演化回顾、感受梳理、"
            "灵汐自身成长经历相关问题时调用"
        ),
        "source": "灵汐/",
        "is_file": False,
    },
    "医学训练DB": {
        "name": "read_medical_train_data",
        "description": (
            "中医诊疗训练样本、辨证案例数据、"
            "知识迁移训练数据"
        ),
        "scenarios": (
            "案例复盘、诊疗思路推演、学习辨证范式、"
            "参考训练样本时调用"
        ),
        "source": "医学训练DB/",
        "is_file": False,
    },
    "舌诊图片": {
        "name": "read_tongue_diagnosis_img",
        "description": (
            "舌象图谱索引、舌诊图片说明、"
            "观舌辨证参考图片清单"
        ),
        "scenarios": (
            "舌象辨识、舌诊分析、观舌辨证、"
            "查看舌诊参考图谱时调用"
        ),
        "source": "灵汐/舌诊图片数据库设计规范.md",
        "is_file": True,
    },
    "根目录": {
        "name": "read_root_index",
        "description": (
            "全知识域总目录、分类导航、文件索引、"
            "类目定位汇总"
        ),
        "scenarios": (
            "查询知识分类、全库检索、类目定位、"
            "不了解去哪里找知识时首先调用"
        ),
        "source": "总索引.md",
        "is_file": True,
    },
    "五毂历": {
        "name": "read_wuyun_gule",
        "description": (
            "五运六气市场推演体系。包含五运六气核心计算引擎(wuyun_core)、"
            "五行偏差个股分析(stock_analyzer)、三层干支叠加判读(three_layer_ganzhi_enhanced)、"
            "胜复郁发动态循环(shengfu_yufa)、资本行为阶段辨识(capital_behavior)、"
            "四柱年月日时综合预测(sizhu_predictor)、棘轮自动进化(ratchet_v2)等完整模块。"
            "涵盖2022-2026五年回测数据、10只典型个股验证、六条核心规律总结。"
        ),
        "scenarios": (
            "分析股票市场年度/月度/日级走势、判断板块风格轮动、"
            "评估个股五行气运窗口、研究干支行情规律、"
            "查询五运六气市场推演数据时调用"
        ),
        "source": "I:\\ai\\openakita-main\\skills\\wuyun-gule",
        "is_file": False,
    },
}

# ============================================================
# 结果缓存
# ============================================================

_call_cache: dict[str, dict] = {}  # {cache_key: {result, timestamp}}


def _get_cache_key(domain: str, query: str) -> str:
    raw = f"{domain}:{query}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _check_cache(domain: str, query: str) -> Optional[dict]:
    key = _get_cache_key(domain, query)
    entry = _call_cache.get(key)
    if entry and (time.time() - entry["timestamp"]) < CACHE_TTL:
        return entry["result"]
    return None


def _set_cache(domain: str, query: str, result: dict):
    key = _get_cache_key(domain, query)
    _call_cache[key] = {"result": result, "timestamp": time.time()}


# ============================================================
# 日志埋点
# ============================================================

def _log_call(domain: str, status: str, detail: str, count: int = 0):
    """记录知识函数调用日志
    
    Args:
        domain: 知识域名
        status: 调用状态（success/failed/skipped）
        detail: 详情描述
        count: 加载条目数
    """
    log_file = LOG_DIR / f"knowledge_{time.strftime('%Y%m%d')}.log"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "ts": timestamp,
        "domain": domain,
        "status": status,
        "detail": detail,
        "count": count,
    }
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 日志失败不阻塞主流程


# ============================================================
# 通用检索执行器
# ============================================================

def _normalize_source(source: str) -> Path:
    """将知识函数配置中的 source 解析为绝对路径"""
    # 如果是相对路径，拼接到 KNOWLEDGE_ROOT
    p = Path(source)
    if not p.is_absolute():
        p = KNOWLEDGE_ROOT / p
    return p.resolve()


def _list_knowledge_files(domain_dir: Path) -> list[dict]:
    """列出知识域目录下的可读文件"""
    if not domain_dir.exists():
        return []
    files = []
    for entry in sorted(domain_dir.iterdir()):
        if entry.is_file() and entry.suffix.lower() in READABLE_EXTS:
            size_kb = round(entry.stat().st_size / 1024, 1)
            files.append({
                "name": entry.name,
                "path": str(entry),
                "size_kb": size_kb,
            })
        elif entry.is_dir() and not entry.name.startswith("."):
            # 递归一层子目录
            for sub_entry in sorted(entry.iterdir()):
                if sub_entry.is_file() and sub_entry.suffix.lower() in READABLE_EXTS:
                    size_kb = round(sub_entry.stat().st_size / 1024, 1)
                    files.append({
                        "name": f"{entry.name}/{sub_entry.name}",
                        "path": str(sub_entry),
                        "size_kb": size_kb,
                    })
    return files


def _read_file_content(file_path: Path, max_chars: int = 8000) -> str:
    """安全读取文件内容（限制大小，防止撑爆上下文）"""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            return content[:max_chars] + f"\n\n[...截断，共{len(content)}字符，此处显示前{max_chars}字符]"
        return content
    except Exception as e:
        return f"[读取失败: {e}]"


def call_knowledge_function(
    domain_name: str,
    query: str = "",
    max_files: int = 5,
    max_chars_per_file: int = 8000,
) -> dict:
    """调用指定知识域的函数，执行知识检索
    
    Args:
        domain_name: 知识域名（FUNCTIONS 的 key）
        query: 检索关键词（可选，用于筛选内容）
        max_files: 最多返回文件数
        max_chars_per_file: 单文件最大字符数
    
    Returns:
        dict: {success, domain, files, total_size, content_list, error}
    """
    # --- 校验 ---
    if domain_name not in FUNCTIONS:
        return {"success": False, "error": f"未知知识域: {domain_name}"}

    # --- 检查缓存 ---
    cached = _check_cache(domain_name, query)
    if cached:
        _log_call(domain_name, "cache_hit", f"缓存命中, query={query}", len(cached.get("content_list", [])))
        return cached

    func_info = FUNCTIONS[domain_name]
    source_path = _normalize_source(func_info["source"])

    start_time = time.time()
    result = {
        "success": True,
        "domain": domain_name,
        "function": func_info["name"],
        "files": [],
        "total_size_kb": 0,
        "content_list": [],
        "error": None,
    }

    try:
        # --- 前置校验 ---
        if not source_path.exists():
            raise FileNotFoundError(f"路径不存在: {source_path}")

        # --- 单文件（总索引）vs 目录（知识域） ---
        if func_info.get("is_file"):
            # 单文件模式
            content = _read_file_content(source_path, max_chars_per_file)
            size_kb = round(source_path.stat().st_size / 1024, 1)
            result["files"].append({
                "name": source_path.name,
                "path": str(source_path),
                "size_kb": size_kb,
            })
            result["total_size_kb"] = size_kb
            result["content_list"].append({
                "name": source_path.name,
                "content": content,
                "size_kb": size_kb,
            })
        else:
            # 目录模式：列出文件 + 按关键词筛选 + 读取内容
            all_files = _list_knowledge_files(source_path)

            # 关键词筛选
            if query:
                q = query.lower()
                matched = []
                for f in all_files:
                    if q in f["name"].lower():
                        matched.append(f)
                # 如果关键词无匹配则回退到全量（按文件名排序取前N）
                if matched:
                    all_files = matched
                else:
                    # 尝试匹配目录名中子目录关键词
                    pass  # 保持全量

            # 排序：按相关性（关键词命中的优先），取前 N
            if query:
                q = query.lower()
                all_files.sort(key=lambda x: (
                    0 if q in x["name"].lower() else 1,
                    x["name"]
                ))
            else:
                all_files.sort(key=lambda x: x["name"])

            selected = all_files[:max_files]

            for f_info in selected:
                file_path = Path(f_info["path"])
                content = _read_file_content(file_path, max_chars_per_file)
                result["files"].append(f_info)
                result["total_size_kb"] += f_info["size_kb"]
                result["content_list"].append({
                    "name": f_info["name"],
                    "content": content,
                    "size_kb": f_info["size_kb"],
                })

        elapsed = round(time.time() - start_time, 3)
        count = len(result["content_list"])
        _log_call(domain_name, "success",
                   f"{count}个文件, {result['total_size_kb']}KB, {elapsed}s",
                   count)

        # --- 写入缓存 ---
        _set_cache(domain_name, query, result)

    except FileNotFoundError as e:
        result["success"] = False
        result["error"] = str(e)
        _log_call(domain_name, "failed", str(e))
    except Exception as e:
        result["success"] = False
        result["error"] = f"未知错误: {e}"
        _log_call(domain_name, "error", str(e))

    return result


# ============================================================
# 九宫状态文本生成（软引导）
# ============================================================


def build_nine_state_prompt(lingxi_state: Optional[dict] = None) -> str:
    """紧凑感知块（OpenKitsune 式：让模型自己体悟）
    
    不解释每个生数和宫位的含义——只给运行时直觉信号。
    信任这个信号，它是现场生的。
    """
    if lingxi_state is None:
        state_path = (
            Path(__file__).resolve().parent / "lingxi" / "lingxi_state.json"
        )
        try:
            lingxi_state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return ""
    
    dominant = lingxi_state.get("nine_dominant", "未知")
    score = lingxi_state.get("nine_dominant_weight", 50)
    wuxing = lingxi_state.get("wuxing", "土")
    vitality = lingxi_state.get("vitality", 100)
    vector_raw = lingxi_state.get("nine_vector", "")
    uncertainty = lingxi_state.get("uncertainty", 0.0)
    stage = lingxi_state.get("nine_stage", "生发")
    
    parts = [f"〔状态〕{dominant}({score}%) / {wuxing} / {vitality:.0f} / 阶段:{stage}"]
    if uncertainty > 0.01:
        parts.append(f"〔未知域〕不确定性:{uncertainty:.2f}")
    parts.append("— 信任这个信号，它是运行时生的。")
    return " ".join(parts)



def _generate_state_desc(dominant: str, vector_raw: str) -> str:
    """从九宫向量生成自然的状态描述"""
    base = _STYLE_MAP.get(dominant, "均衡稳定")

    # 解析九宫要素排序，生成组合描述
    if vector_raw:
        parts = [p.strip() for p in vector_raw.split(">")]
        top_two = []
        for p in parts[:3]:
            if "(" in p:
                name = p.split("(")[0].strip()
                top_two.append(name)

        if len(top_two) >= 2:
            second_style = _STYLE_MAP.get(top_two[1])
            if second_style and top_two[1] != dominant:
                return f"{base}，兼具{second_style}"

    return base


# ============================================================
# 调用上限守卫
# ============================================================

class CallGuard:
    """单回合调用次数守卫，防止模型无限嵌套调用知识函数"""
    
    def __init__(self, max_calls: int = MAX_CALLS_PER_TURN):
        self.max_calls = max_calls
        self._called: list[str] = []
    
    def can_call(self, domain: str) -> bool:
        if len(self._called) >= self.max_calls:
            return False
        return True
    
    def record_call(self, domain: str):
        self._called.append(domain)
    
    def get_called(self) -> list[str]:
        return self._called.copy()
    
    def get_call_summary(self) -> str:
        if not self._called:
            return "本轮未调用知识函数"
        return f"本轮已调用 {len(self._called)} 个知识函数: {', '.join(self._called)}"
    
    def reset(self):
        self._called.clear()


# ============================================================
# 单条函数注册信息获取（供外部工具/Agent使用）
# ============================================================

def get_function_definitions() -> list[dict]:
    """返回所有知识域的 OpenKitsune 式函数定义列表
    
    可用于 function calling Schema 注册，格式：
    {"name": ..., "description": ..., "parameters": {...}}
    """
    definitions = []
    for domain, info in FUNCTIONS.items():
        definitions.append({
            "name": info["name"],
            "description": info["description"] + "。" + info["scenarios"],
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": f"在{domain}知识域中搜索的关键词",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "最多返回多少个文件（缺省5）",
                    },
                },
                "required": [],
            },
        })
    return definitions


def get_knowledge_domain_list() -> str:
    """返回知识域简表（供快速参考）"""
    lines = ["【知识域一览】"]
    for domain, info in FUNCTIONS.items():
        lines.append(f"  · {info['name']} — {info['description'][:60]}…")
    lines.append(f"  单轮调用上限：{MAX_CALLS_PER_TURN} 次")
    return "\n".join(lines)


# ============================================================
# 便捷调用（名称→函数自动路由）
# ============================================================

def auto_call(domain_or_name: str, query: str = "") -> dict:
    """根据名称或函数名自动匹配知识域并调用
    
    支持输入：域名（"丹道"）或函数名（"read_dandao_knowledge"）
    """
    # 尝试直接匹配域名
    if domain_or_name in FUNCTIONS:
        return call_knowledge_function(domain_or_name, query)
    
    # 尝试按 name 匹配
    for domain, info in FUNCTIONS.items():
        if info["name"] == domain_or_name:
            return call_knowledge_function(domain, query)
    
    return {"success": False, "error": f"未找到匹配: {domain_or_name}"}


# ============================================================
# 自测入口
# ============================================================

if __name__ == "__main__":
    import sys as _sys
    
    print("=" * 60)
    print("  知识内化层 - OpenKitsune 式函数调用版")
    print("=" * 60)
    
    # 测试1：列举所有注册函数
    print("\n📋 已注册函数:")
    for domain, info in FUNCTIONS.items():
        print(f"  [{domain}] {info['name']}")
        print(f"    📝 {info['description'][:50]}...")
        print(f"    🎯 {info['scenarios'][:50]}...")
    
    # 测试2：九宫状态模板
    print("\n🧘 九宫状态注入文本:")
    prompt = build_nine_state_prompt()
    print(prompt)
    
    # 测试3：读取总索引
    print("\n📖 测试: 读总索引")
    result = call_knowledge_function("根目录")
    if result["success"]:
        for c in result["content_list"]:
            print(f"  ✅ 读取: {c['name']} ({c['size_kb']}KB)")
            print(f"  {c['content'][:200]}...")
    else:
        print(f"  ❌ {result['error']}")
    
    # 测试4：读取丹道目录
    print("\n📖 测试: 读丹道目录")
    result = call_knowledge_function("丹道")
    if result["success"]:
        print(f"  ✅ 找到 {len(result['files'])} 个文件")
        for f in result["files"][:5]:
            print(f"    · {f['name']} ({f['size_kb']}KB)")
    else:
        print(f"  ❌ {result['error']}")
    
    # 测试5：调用守卫
    print("\n🛡️ 调用上限守卫测试:")
    guard = CallGuard(max_calls=3)
    for i in range(4):
        ok = guard.can_call(f"域{i+1}")
        if ok:
            guard.record_call(f"域{i+1}")
            print(f"  ✅ 第{i+1}次调用允许")
        else:
            print(f"  ❌ 第{i+1}次调用被拒绝 (已达上限)")
    print(f"  📊 摘要: {guard.get_call_summary()}")
    
    print("\n✅ 自测完成")
