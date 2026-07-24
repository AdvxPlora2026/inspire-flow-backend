# Agent 用户资料画像与会话接口

## Goal

让 InspireFlow Agent 能在当前已鉴权用户的授权范围内维护用户基础资料和长期文本画像，并提供一个通过用户令牌与会话标识定位上下文的对话入口，供前端持续与 Agent 对话。

## Background

- `users` 表当前保存 UUID、昵称、头像、密码摘要和创建/更新时间，尚无文本画像字段。
- 项目已有 `user_profiles` 一对一结构化画像表，保存简介、时区、首选语言、创作者身份、内容方向和协作偏好。
- 项目已有需 Bearer Token 鉴权的 `POST /api/v1/conversations/{conversation_id}/messages`，会使用当前用户 ID 与对话 UUID 联合校验归属，并调用 Agent 完成一轮对话。
- Agent FunctionTool 已统一放在 `src/inspire_flow_backend/services/agent/func/` 并通过注册表装配；目前没有修改当前用户资料或文本画像的工具。

## Requirements

- R1：在 `users` 表新增可为空的 `profile_text` 文本列，作为长期文本画像；保留 `user_profiles` 表及已有结构化资料接口。
- R2：为 Agent 增加修改当前用户昵称、头像的工具。工具只能从 `AgentRunContext.user_id` 确定目标，参数中不得接受任意 `user_id`。
- R3：昵称和头像只允许在用户明确提出修改时由 Agent 工具写入；普通对话不得触发身份资料修改。
- R4：为 Agent 增加替换或清空当前用户 `profile_text` 的工具，同样只能作用于当前运行用户。
- R5：Agent 可以从普通对话中主动归纳并更新文本画像，但只能记录用户明确表达、具有跨会话价值的信息，不得把模型推测写成事实。
- R6：敏感信息沿用长期记忆规则，只有用户明确强调需要保存时才允许写入文本画像。
- R7：文本画像仅供 Agent 内部上下文与工具使用，不加入现有 `GET/PATCH /api/v1/users/me` 的公开响应或请求模型。
- R8：沿用 `POST /api/v1/conversations/{conversation_id}/messages` 作为 Agent 对话接口，其中 `conversation_id` 即持久化 session ID；请求仍通过 Bearer Token 鉴权，并联合用户 ID 校验归属。
- R9：沿用 `/api/v1` 前缀及现有错误响应、事务和资源隔离约定，不新增重复聊天路由。
- R10：不得破坏项目、灵感、记忆、结构化用户资料及持久化对话的现有行为。

## Technical Notes

- `profile_text` 采用数据库 `Text` 类型并允许 `NULL`，旧用户升级后默认无画像。
- 每轮 Agent 调用的动态用户上下文应包含 `profile_text`，使 Agent 能基于现有画像做完整替换，避免盲目覆盖。
- 文本画像需要设置长度上限并进行首尾空白规范化；空白文本按清空处理。
- Agent 工具返回安全 JSON，不返回密码摘要或认证凭据。
- 昵称冲突、无上下文、参数校验失败等情况应转换为稳定且不泄露内部信息的工具错误。

## Acceptance Criteria

- [x] AC1（R1）：迁移升级后 `users.profile_text` 存在、可为空，旧用户保持可用；迁移降级可移除该列。
- [x] AC2（R2、R3）：Agent 在有运行上下文时能修改当前用户昵称或头像，工具 schema 不暴露 `user_id`；无明确用户请求时提示词禁止调用。
- [x] AC3（R4-R6）：Agent 能替换或清空当前用户文本画像；超长或非法输入返回安全校验错误，敏感信息与推测遵守写入边界。
- [x] AC4（R5、R7）：后续 Agent 轮次能从动态上下文读取已保存画像，但 `/api/v1/users/me` 的请求和响应结构不增加 `profile_text`。
- [x] AC5（R8、R9）：消息接口缺少、无效或已撤销令牌时返回 401；session 不属于当前用户时返回 404 且不泄露资源存在性。
- [x] AC6（R8）：同一用户使用同一 session ID 能延续已有上下文，不同用户不能访问该 session。
- [x] AC7（R10）：现有用户、结构化画像、项目、灵感、记忆和对话测试保持通过。
- [x] AC8：新增迁移、服务、动态上下文、Agent 工具与 API 鉴权行为均有测试覆盖，Ruff、格式检查和完整 pytest 通过。

## Out of Scope

- 修改登录、注册或令牌签发机制。
- 改变已有 `/api/v1` 路由前缀。
- 允许 Agent 指定任意用户 ID 执行资料修改。
- 新增 `/api/v1/agent/chat` 或其他重复聊天入口。
- 通过公共用户 REST API 查看或编辑 `profile_text`。
- 删除或迁移现有 `user_profiles` 表。
