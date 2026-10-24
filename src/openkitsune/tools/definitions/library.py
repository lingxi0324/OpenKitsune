"""图书馆（书库）增量阅读工具定义。"""

LIBRARY_TOOLS = [
    {
        "name": "library_read_page",
        "category": "Library",
        "description": (
            "按页读取「图书馆」书库内书籍（Markdown/文本）的指定页内容，用于分批增量阅读："
            "AI 伴学/阅读问答场景下，不要一次性读取整本书，而是从当前页开始逐页调用本工具，"
            "按需翻页直到找到答案。path 为书库根目录内的相对路径（如 丹道/九华金书.md），"
            "不是磁盘绝对路径；返回内容含 total_lines/total_pages/has_more 与页码提示，"
            "据此决定是否继续翻页。本工具只读，不会修改任何文件。"
        ),
        "triggers": [
            "阅读这本书的下一页",
            "书里怎么说",
            "帮我查典籍原文",
            "继续读这本书",
        ],
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "书库根目录内的相对路径，如 丹道/九华金书.md；"
                        "通常由用户在提问中给出，或由上一次调用的返回 path 原样传递。"
                    ),
                },
                "page": {
                    "type": "integer",
                    "description": "要读取的页码，从 1 开始（默认 1）。",
                    "default": 1,
                    "minimum": 1,
                },
                "page_size": {
                    "type": "integer",
                    "description": "每页行数（默认 150，最大 2000）。",
                    "default": 150,
                    "minimum": 1,
                    "maximum": 2000,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "library_study",
        "category": "Library",
        "description": (
            "学习工具：系统研读「图书馆」中某本书（或某段章节范围）。"
            "一次调用批量取回从 from_page 起的多页原文，并提取 Markdown 章节标题（headings），"
            "供逐章理解、归纳要点、总结讲解（可再配合 add_memory 沉淀为长期记忆）。"
            "适合「读完整本书/某章节后帮我学习、总结、讲解」的研读场景；"
            "path 为书库根内相对路径（如 丹道/九华金书.md），不是磁盘绝对路径。"
            "返回含 read_pages/headings/总页数/是否还有后续，达到单次字符上限时会提示从下一页继续。"
        ),
        "triggers": [
            "帮我学习这本书",
            "通读并总结这本书",
            "讲解这本书的核心内容",
            "把这本书的要点整理出来",
        ],
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "书库根目录内的相对路径，如 丹道/九华金书.md；"
                        "通常由用户给出，或由 library_read_page 的返回 path 原样传递。"
                    ),
                },
                "focus": {
                    "type": "string",
                    "description": "学习重点/研读目标（可选），如「重点理解丹道修炼次第」。",
                },
                "from_page": {
                    "type": "integer",
                    "description": "起始页码（默认 1）。",
                    "default": 1,
                    "minimum": 1,
                },
                "to_page": {
                    "type": "integer",
                    "description": "结束页码（可选）；不填则按 max_pages 取到足够页数。",
                    "minimum": 1,
                },
                "page_size": {
                    "type": "integer",
                    "description": "每页行数（默认 150，最大 2000）。",
                    "default": 150,
                    "minimum": 1,
                    "maximum": 2000,
                },
                "max_pages": {
                    "type": "integer",
                    "description": "单次最多读取页数（默认 20，最大 60），受单次字符上限约束。",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 60,
                },
            },
            "required": ["path"],
        },
    },
]
