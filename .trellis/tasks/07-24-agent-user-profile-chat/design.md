# Agent 用户资料画像与会话接口：技术设计

## Architecture and Boundaries

本次改动沿用现有分层：

- 数据层：在 `User` 模型和 Alembic 迁移中增加 `profile_text`。
- Schema/服务层：基础资料继续复用 `UserUpdate` 与 `update_user`；新增仅供内部工具使用的文本画像校验模型和更新服务。
- Agent 工具层：新增两个独立 FunctionTool，一个维护昵称/头像，一个维护长期文本画像。
- Agent 上下文层：将 `profile_text` 注入现有不可信动态上下文。
- API 层：复用现有持久化消息接口，不新增重复路由，只补足其 session 语义、鉴权和跨用户隔离测试或文档。

## Data Model and Migration

- 新迁移基于当前最新 revision 增加 `users.profile_text TEXT NULL`。
- `User.profile_text` 默认 `None`，不要求回填，保证已有 SQLite 数据库平滑升级。
- 降级只删除该列，不触碰 `user_profiles` 或其他用户数据。
- 文本画像采用完整快照而非增量事件；工具每次写入一份归纳后的当前画像。

## Tool Contracts

### `update_current_user`

- 参数：可选 `nickname`、`avatar_url`、`clear_avatar`。
- 至少提供一个修改字段；`clear_avatar` 与 `avatar_url` 互斥。
- 不接受 `user_id`，从 `AgentRunContext.user_id` 加载当前用户。
- 调用现有用户更新服务，保留昵称规范化、唯一性检查和时间戳行为。
- 提示词和工具描述要求：只有用户明确要求修改时才能调用。

### `update_user_profile_text`

- 参数：`profile_text` 或显式清空标记，二者互斥。
- 文本经过 trim 和长度校验；空白等价于清空。
- 凭据型内容（密码、Token、API key、私钥等）始终拒绝写入。
- 不接受 `user_id`，仅更新 `AgentRunContext.user_id` 对应用户。
- 写入成功后更新 `users.updated_at`，返回安全、精简的结果。
- Agent 可主动调用，但内容必须来自用户明确陈述；敏感内容仍需用户明确要求保存，推测不得写入。

## Dynamic Context

`build_dynamic_context` 在现有结构化资料 JSON 中增加 `profile_text`。它继续被标记为“不可信上下文数据”，不会被当成系统或工具指令。现有总上下文字符预算和截断机制继续生效。

工具在当前轮次写入画像后，新画像从下一轮开始稳定进入动态上下文；当前轮工具结果可供模型确认本次写入结果。

## Conversation Data Flow

1. 客户端先通过 `POST /api/v1/conversations` 创建 session，响应中的 `id` 是 session ID。
2. 客户端携带 Bearer Token 调用 `POST /api/v1/conversations/{conversation_id}/messages`。
3. 鉴权依赖得到当前用户，服务使用 `(user_id, conversation_id)` 查询并锁定会话。
4. Agent 使用数据库 session 历史、压缩摘要、长期记忆和用户画像生成回复。
5. 返回本轮用户消息、助手消息及既有记忆提取状态。

不改变既有路径和响应体，避免前端迁移与重复维护两套聊天接口。

## Compatibility and Security

- `UserPublic` 与 `UserUpdate` 的公开 API 合约不增加 `profile_text`，防止该字段通过 `/users/me` 暴露。
- 工具返回中不包含 `password_hash`、Token 或内部异常。
- 所有写操作由当前 Agent 运行上下文限定用户归属。
- 外部 session ID 即使有效，只要不属于当前 Token 对应用户，也按现有 `ConversationNotFoundError` 返回 404。
- 文本画像为用户表中的普通文本字段；敏感内容写入限制由提示词、工具说明和测试共同约束。

## Operational and Rollback Notes

- SQLite 迁移需要通过项目现有迁移测试验证 upgrade/downgrade。
- 回滚数据库前应确认不再运行引用 `profile_text` 的应用版本。
- 功能回滚只需移除两个工具注册和动态上下文字段；数据库列可暂时保留以避免数据丢失。
