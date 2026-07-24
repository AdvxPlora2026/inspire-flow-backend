# 完整后端 API 接入文档

## Goal

在 `docs/HANDOFF.md` 提供一份可以直接交给前端、移动端或联调人员使用的中文后端接入文档。读者不需要翻源码，就能完成鉴权、调用所有 HTTP API、理解请求与响应格式，并处理常见错误。

## Background

- 当前 OpenAPI 共注册 36 个 HTTP 操作，统一使用 `/api/v1` 前缀。
- 现有专题文档分别介绍用户、Agent 记忆、项目、灵感和 STT，但缺少一份按实际路由汇总的总交接文档。
- API 覆盖健康检查、用户、登录会话、结构化资料、长期记忆、项目、灵感、Agent 对话和异步语音转写。
- 除注册、登录和健康检查外，其余接口均使用 Bearer Token。

## Requirements

- R1：创建 `docs/HANDOFF.md`，以当前路由、Pydantic schema、服务错误和 OpenAPI 为事实来源。
- R2：覆盖全部 36 个 HTTP 操作，不遗漏查询参数、路径参数、请求体、成功状态码和响应格式。
- R3：每个 HTTP 操作提供一段可复制修改的 `curl` 示例。
- R4：统一使用环境变量保存 `BASE_URL`、`ACCESS_TOKEN` 和各资源 UUID，避免在示例中出现真实凭据。
- R5：说明 JSON、multipart/form-data、空 `204`、分页、游标、异步任务轮询和删除确认等调用差异。
- R6：列出枚举值、字段限制和稳定错误信封，说明 401、404、409、422、502、503 等常见状态。
- R7：说明 Agent `conversation_id` 是持久化 session ID，并与 Bearer Token 对应用户联合定位。
- R8：说明 `users.profile_text` 是 Agent 内部画像字段，不属于公共 `/users/me` API。
- R9：内部 Agent FunctionTool 只作补充说明，不伪装成可用 `curl` 调用的 HTTP API。
- R10：用 `humanizer-zh` 做最终中文编辑，保持技术文档直接、自然，不写宣传语或机械套话。

## Acceptance Criteria

- [x] AC1：脚本对照 OpenAPI 后确认文档覆盖全部 36 个 method/path 组合。
- [x] AC2：每个 method/path 组合附近都有对应 `curl` 示例。
- [x] AC3：请求字段、枚举、长度限制、默认值、状态码和响应字段与当前 schema 一致。
- [x] AC4：鉴权示例不包含真实 Token、API key、密码或其他凭据。
- [x] AC5：项目/对话删除导致灵感孤立时的 409 确认流程写清楚。
- [x] AC6：STT 上传使用 multipart 示例，并解释 202、Location 和轮询结果。
- [x] AC7：文档通过 Markdown 基本检查、敏感信息扫描和人工可读性复核。
- [x] AC8：`humanizer-zh` 复核后没有多余铺垫、营销语言、机械三段式和聊天机器人话术。

## Out of Scope

- 修改任何 HTTP 路由、业务逻辑或数据库结构。
- 为内部 FunctionTool 增加不存在的 HTTP 入口。
- 提供生产环境真实域名、账号或密钥。
