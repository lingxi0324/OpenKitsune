"""
Skill Store 工具定义

提供与 OpenKitsune Platform Skill Store 交互的工具：
- search_store_skills: 搜索平台上的 Skill
- install_store_skill: 从平台安装 Skill 到本地
- get_store_skill_detail: 查看 Skill 详情
- submit_skill_repo: 提交 GitHub 仓库供索引
"""

SKILL_STORE_TOOLS = [
    {
        "name": "search_store_skills",
        "category": "Skill Store",
        "description": "Search for Skills on the OpenKitsune Platform Skill Store. Returns a list of available Skills with trust level, install count, and rating.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword (empty = browse all)",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category",
                },
                "trust_level": {
                    "type": "string",
                    "enum": ["official", "certified", "community"],
                    "description": "Filter by trust level",
                },
                "sort": {
                    "type": "string",
                    "enum": ["installs", "rating", "newest", "stars"],
                    "description": "Sort order (default: installs)",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number (default: 1)",
                },
            },
        },
    },
    {
        "name": "install_store_skill",
        "category": "Skill Store",
        "description": "Install a Skill from the OpenKitsune Platform Skill Store to the local system. Uses git clone or direct download based on the skill source.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {
                    "type": "string",
                    "description": "The ID of the Skill to install from the platform",
                },
            },
            "required": ["skill_id"],
        },
    },
    {
        "name": "get_store_skill_detail",
        "category": "Skill Store",
        "description": "Get detailed information about a specific Skill on the OpenKitsune Platform, including readme, trust level, and installation instructions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {
                    "type": "string",
                    "description": "The ID of the Skill on the platform",
                },
            },
            "required": ["skill_id"],
        },
    },
    {
        "name": "submit_skill_repo",
        "category": "Skill Store",
        "description": "Submit a GitHub repository to be indexed by the OpenKitsune Skill Store. The platform will scan for SKILL.md files and create skill entries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo_url": {
                    "type": "string",
                    "description": "GitHub repository URL (e.g. https://github.com/owner/repo)",
                },
            },
            "required": ["repo_url"],
        },
    },
]
