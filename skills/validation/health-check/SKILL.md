---
name: health-check
description: 检测本地服务的存活状态，支持 HTTP/TCP/进程/端口等多种探测方式。
---

# Health Check - Agent 服务健康检测工具

**ID**: health_check
**描述**: 检测本地服务的存活状态，支持 HTTP/TCP/进程/端口等多种探测方式。
**类型**: 验证层工具

---

# Health Check - Agent 服务健康检测工具

## 核心功能

在服务启动、配置变更、部署后，自动检测服务的**存活状态**和**健康状态**。支持 HTTP 健康端点、TCP 端口探测、进程状态检查、端口占用检测。

## 检测方式

| 检测方式 | 适用场景 | 示例 |
|---------|---------|------|
| **HTTP 健康端点** | Web 服务、API 服务 | `GET http://localhost:8080/health` |
| **TCP 端口探测** | 数据库、消息队列 | `localhost:5432` |
| **进程状态检查** | 后台服务、守护进程 | `Get-Process node` |
| **端口占用检测** | 服务启动前检查 | `netstat -ano | findstr 8080` |

## 使用场景

- **服务启动后** — 验证服务是否正常启动
- **配置变更后** — 验证配置变更未导致服务异常
- **部署后** — 验证部署成功
- **定时巡检** — 定期检查服务健康状态
- **故障诊断** — 服务异常时诊断

## 检测流程

```
1. 确定检测方式
   - HTTP 端点 → HTTP 检测
   - 数据库 → TCP 检测
   - 后台进程 → 进程检测

2. 执行检测
   - 发起 HTTP 请求 / TCP 连接 / 进程查询
   - 等待响应

3. 分析结果
   - HTTP 状态码
   - TCP 连接状态
   - 进程状态

4. 报告状态
   - 存活状态
   - 响应时间
   - 健康指标
```

## 参数说明

- **service_name**: 服务名称（必填）
- **check_type**: 检测类型（http/tcp/process/port，默认 http）
- **target**: 检测目标（URL/主机:端口/进程名）
- **timeout**: 检测超时（秒，默认 5）
- **max_retries**: 最大重试次数（默认 3）
- **retry_interval**: 重试间隔（秒，默认 1）

## 输出格式

```json
{
  "health_check_id": "health_20240101_120000_001",
  "timestamp": "2024-01-01T12:00:00",
  "service_name": "api-server",
  "check_type": "http",
  "target": "http://localhost:8080/health",
  "status": "healthy|unhealthy|unknown",
  "details": {
    "http_status_code": 200,
    "response_time_ms": 45,
    "response_body": "{\"status\":\"ok\",\"version\":\"1.0.0\"}",
    "tcp_connected": true,
    "process_running": true
  },
  "retries": 0,
  "recommendation": "service_running_ok|retry|investigate"
}
```

## 与相关工具的关系

- **service_ctl** — 服务控制（启动/停止/重启）
- **log_inspect** — 服务异常时查看日志
- **port_scan** — 检测端口占用
- **self_review** — 服务健康后自检
- **audit_log** — 记录健康检查结果

## 使用示例

```python
# 示例 1：检测 HTTP 服务
health_check(
    service_name="api-server",
    check_type="http",
    target="http://localhost:8080/health",
    timeout=5
)
# 返回健康状态、响应时间、响应体

# 示例 2：检测数据库
health_check(
    service_name="postgres",
    check_type="tcp",
    target="localhost:5432",
    max_retries=3
)
# 返回 TCP 连接状态

# 示例 3：检测进程
health_check(
    service_name="node-server",
    check_type="process",
    target="node"
)
# 返回进程状态
```

## 注意事项

- **超时设置** — 合理设置超时，避免长时间等待
- **重试机制** — 服务启动需要时间，建议重试
- **健康端点** — 优先使用 `/health` 端点
- **端口冲突** — 启动前检查端口是否被占用
- **进程残留** — 旧进程未退出会导致端口占用
- **日志记录** — 健康检查结果记录到日志
- **告警集成** — 可集成告警系统
