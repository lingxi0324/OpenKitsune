const PERM_LABELS: Record<string, { zh: string; en: string }> = {
  "assets.publish": { zh: "发布文件和作品", en: "Publish Files and Artifacts" },
  "assets.consume": { zh: "读取文件和作品", en: "Read Files and Artifacts" },
  "tools.register":      { zh: "注册工具",     en: "Register Tools" },
  "hooks.basic":         { zh: "基础钩子",     en: "Basic Hooks" },
  "hooks.message":       { zh: "消息钩子",     en: "Message Hooks" },
  "hooks.retrieve":      { zh: "检索钩子",     en: "Retrieval Hooks" },
  "hooks.all":           { zh: "所有钩子",     en: "All Hooks" },
  "config.read":         { zh: "读取配置",     en: "Read Config" },
  "config.write":        { zh: "写入配置",     en: "Write Config" },
  "data.own":            { zh: "数据存储",     en: "Data Storage" },
  "log":                 { zh: "日志",         en: "Logging" },
  "skill":               { zh: "技能",         en: "Skill" },
  "memory.read":         { zh: "读取记忆",     en: "Read Memory" },
  "memory.write":        { zh: "写入记忆",     en: "Write Memory" },
  "memory.replace":      { zh: "替换记忆",     en: "Replace Memory" },
  "channel.register":    { zh: "注册通道",     en: "Register Channel" },
  "channel.send":        { zh: "发送消息",     en: "Send Messages" },
  "retrieval.register":  { zh: "注册检索源",   en: "Register Retrieval" },
  "search.register":     { zh: "注册搜索后端", en: "Register Search" },
  "routes.register":     { zh: "注册 API 路由", en: "Register API Routes" },
  "brain.access":        { zh: "访问 Brain",   en: "Access Brain" },
  "vector.access":       { zh: "访问向量库",   en: "Access Vector Store" },
  "settings.read":       { zh: "读取设置",     en: "Read Settings" },
  "llm.register":        { zh: "注册 LLM 服务", en: "Register LLM" },
  "system.config.write": { zh: "系统配置写入", en: "System Config Write" },
};

const LEVEL_LABELS: Record<string, { zh: string; en: string }> = {
  basic:    { zh: "基础", en: "basic" },
  advanced: { zh: "高级", en: "advanced" },
  system:   { zh: "系统", en: "system" },
};

export function permLabel(perm: string, lang: string): string {
  const entry = PERM_LABELS[perm];
  if (!entry) return perm;
  return lang.startsWith("zh") ? entry.zh : entry.en;
}

export function levelLabel(level: string, lang: string): string {
  const entry = LEVEL_LABELS[level];
  if (!entry) return level;
  return lang.startsWith("zh") ? entry.zh : entry.en;
}
