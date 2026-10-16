"""Read-only cloud knowledge-base tools."""

KNOWLEDGE_TOOLS = [
    {
        "name": "knowledge_list",
        "category": "Knowledge",
        "description": (
            "Browse files and folders in configured cloud knowledge bases when the provider "
            "supports catalogs. Retrieval-only services report listing_supported=false. "
            "When the user asks what files, documents, folders, or contents are in their "
            "knowledge base, use this tool instead of semantic search or local filesystem tools. "
            "This tool is read-only."
        ),
        "triggers": [
            "我的知识库中有哪些文件",
            "列出知识库内容",
            "浏览知识库文件夹",
        ],
        "input_schema": {
            "type": "object",
            "properties": {
                "knowledge_base_id": {
                    "type": "string",
                    "description": (
                        "已配置的知识库 ID。省略时浏览全部已选知识库；工具返回中会包含可用 ID。"
                    ),
                    "default": "",
                },
                "provider": {
                    "type": "string",
                    "enum": ["tencent-ima", "aliyun-bailian"],
                    "description": "可选的云知识库提供方；省略时查询全部已启用连接。",
                },
                "folder_id": {
                    "type": "string",
                    "description": "要浏览的文件夹 ID；省略时浏览根目录。",
                    "default": "",
                },
                "cursor": {
                    "type": "string",
                    "description": "上一页返回的 next_cursor；首页留空。",
                    "default": "",
                },
                "limit": {
                    "type": "integer",
                    "description": "每个知识库返回的最大条目数（1-50，默认 20）。",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
        },
    },
    {
        "name": "knowledge_search",
        "category": "Knowledge",
        "description": (
            "Search all configured cloud knowledge bases by topic or keywords. Results may include "
            "provider-native semantic matches and complete matched text chunks. "
            "When the user asks a content question that should be answered from their knowledge "
            "base, use this tool. Use knowledge_list instead for file inventories or folder browsing. "
            "If a result has no excerpt, or the user asks for a summary or analysis, call "
            "knowledge_read with that result's IDs before answering. "
            "This tool is read-only."
        ),
        "triggers": [
            "在我的知识库中搜索",
            "根据知识库回答",
            "查找知识库资料",
        ],
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要在知识库中搜索的问题或关键词。",
                },
                "knowledge_base_id": {
                    "type": "string",
                    "description": "已配置的知识库 ID；省略时搜索全部已选知识库。",
                    "default": "",
                },
                "provider": {
                    "type": "string",
                    "enum": ["tencent-ima", "aliyun-bailian"],
                    "description": "可选的云知识库提供方；省略时搜索全部已启用连接。",
                },
                "cursor": {
                    "type": "string",
                    "description": (
                        "上一页返回的 next_cursor；仅在指定 knowledge_base_id 时使用。"
                    ),
                    "default": "",
                },
                "limit": {
                    "type": "integer",
                    "description": "最大返回结果数（1-20，默认使用连接配置）。",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "knowledge_read",
        "category": "Knowledge",
        "description": (
            "Read available text for one result returned by knowledge_search or knowledge_list. "
            "Depending on the provider this is the source document or matched semantic chunks. "
            "Use this before summarizing, analyzing, quoting, or answering detailed questions "
            "about a knowledge-base document. Pass the media_id, knowledge_base_id, and "
            "parent_folder_id from the earlier result. This tool is read-only. If reading fails, "
            "explain that the knowledge-base document could not be read; do not switch to web or "
            "browser search unless the user explicitly asks to use external sources."
        ),
        "triggers": [
            "读取知识库正文",
            "概括知识库文档",
            "查看资料原文",
        ],
        "input_schema": {
            "type": "object",
            "properties": {
                "media_id": {
                    "type": "string",
                    "description": "knowledge_search 或 knowledge_list 返回的媒体 ID。",
                },
                "knowledge_base_id": {
                    "type": "string",
                    "description": "该条目所属、且已在设置中选中的知识库 ID。",
                },
                "parent_folder_id": {
                    "type": "string",
                    "description": "搜索或列表结果返回的父文件夹 ID；根目录可留空。",
                    "default": "",
                },
                "provider": {
                    "type": "string",
                    "enum": ["tencent-ima", "aliyun-bailian"],
                    "description": "搜索结果返回的提供方；建议原样传入。",
                },
                "start_page": {
                    "type": "integer",
                    "description": "PDF 起始页码，从 1 开始（默认 1）。",
                    "default": 1,
                    "minimum": 1,
                },
                "max_pages": {
                    "type": "integer",
                    "description": "本次最多读取页数（1-50，默认 20）。",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                },
                "max_chars": {
                    "type": "integer",
                    "description": "本次最多返回字符数（1000-80000，默认 40000）。",
                    "default": 40000,
                    "minimum": 1000,
                    "maximum": 80000,
                },
            },
            "required": ["media_id", "knowledge_base_id"],
        },
    },
]
