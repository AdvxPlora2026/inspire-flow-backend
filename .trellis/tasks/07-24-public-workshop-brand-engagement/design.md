# 创作者公开橱窗与品牌互动：技术设计

## 1. 边界

实现继续沿用现有 FastAPI 分层：

- `api/routes` 只处理 HTTP、依赖和响应状态。
- `schemas` 定义请求、响应、枚举与 SSE 事件载荷。
- `services` 负责权限投影、状态流转、事务和幂等执行。
- `data/repositories` 封装查询，不在路由中拼 SQL。
- `data/models` 与 Alembic 管理关系和约束。

创作者仍是现有 `User`。品牌是独立组织，用户通过成员关系代表品牌。任何品牌写
操作都同时检查登录用户和路径中的 `brand_id`。

## 2. 数据模型

### 2.1 品牌组织

`brand_organizations`

- `id`
- `name`
- `description`
- `website_url`
- `logo_url`
- `created_by_user_id`
- `created_at`
- `updated_at`

`brand_memberships`

- `brand_id`
- `user_id`
- `role`: `owner | member`
- `created_at`
- 唯一约束：`(brand_id, user_id)`

`brand_invitations`

- `id`
- `brand_id`
- `invited_user_id`
- `invited_by_user_id`
- `status`: `pending | accepted | declined | revoked`
- `responded_at`
- `created_at`
- `updated_at`
- 同一品牌与受邀用户最多一条 pending 邀请

删除或退出成员前，由服务检查品牌至少保留一名 owner。首版不提供品牌组织删除。

### 2.2 Public Workshop 草稿与快照

`creator_workshops`

- `user_id`，一对一主键
- `status`: `draft | published | withdrawn`
- 草稿资料字段：
  `nickname`、`avatar_url`、`title`、`bio`、`creator_identity`、
  `content_focus`、`collaboration_preferences`
- 每个资料字段对应一个 visibility 列
- `published_revision_id`
- `published_at`
- `created_at`
- `updated_at`

草稿子表：

- `workshop_social_accounts`
- `workshop_contacts`
- `workshop_project_selections`

发布时创建不可变修订：

- `workshop_publications`
- `workshop_publication_social_accounts`
- `workshop_publication_contacts`
- `workshop_publication_project_cards`

项目卡片保存发布时的标题、类型、受众、简介和图标，同时保留
`source_project_id` 供所有者追溯。线上读取不回查内部项目。旧发布修订保留用于
审计，只有 `published_revision_id` 指向的修订可被读取。

`content_focus` 使用规范化子项或可索引的受控存储，发现查询不能依赖读取后再做
Python 过滤，否则分页总数会失真。

### 2.3 社交账号和联系方式

社交账号草稿及快照字段：

- `platform`
- `handle`
- `profile_url`
- `visibility`
- `sort_order`

联系方式草稿及快照字段：

- `type`
- `label`
- `value_ciphertext`
- `visibility`: `private | authorized_brands`
- `sort_order`

联系方式写入前按类型规范化。服务端解密后生成：

- `email` → `mailto:`
- `phone` → `tel:`
- `telegram` → 安全的 Telegram URI 或 HTTPS 地址
- `wechat`、`qq`、`other` 没有可靠协议时只返回规范化值

未通过授权投影的记录不会实例化包含明文值的响应模型。

### 2.4 品牌授权和互动

`workshop_brand_authorizations`

- `creator_user_id`
- `brand_id`
- `active`
- `granted_at`
- `revoked_at`
- 唯一约束：`(creator_user_id, brand_id)`

`brand_follows`

- `id`
- `brand_id`
- `creator_user_id`
- `status`: `active | inactive`
- `followed_at`
- `unfollowed_at`
- `created_at`
- `updated_at`
- 唯一约束：`(brand_id, creator_user_id)`

`brand_interests`

- `id`
- `brand_id`
- `creator_user_id`
- `message`
- `status`: `pending | accepted | declined | withdrawn`
- `created_by_user_id`
- `responded_at`
- `created_at`
- `updated_at`
- 部分唯一索引保证同一品牌与创作者最多一条 pending 意向

`creator_inbox_items`

- `id`
- `creator_user_id`
- `brand_id`
- `kind`: `follow | interest`
- `reference_id`
- `is_read`
- `read_at`
- `event_at`
- `created_at`
- `updated_at`
- 唯一约束：`(kind, reference_id)`

关注重启用同一 follow 和 inbox item。意向每次进入新 pending 周期时创建新记录和
收件箱项。

### 2.5 幂等记录

`idempotency_records`

- `id`
- `user_id`
- `brand_id`，可空
- `method`
- `route_template`
- `key_digest`
- `request_fingerprint`
- `status`: `processing | completed | failed`
- `response_status`
- `response_headers`
- `response_ciphertext`
- `created_at`
- `completed_at`
- `expires_at`

当前数据库结构保留 `brand_id` 和 `route_template` 字段以兼容已部署数据，但新版本
记录固定写入 `brand_id = NULL`，并让 `route_template` 保存规范化实际路径。现有
`brand_id IS NULL` 部分唯一索引因此实现 `(user_id, method, normalized_path,
key_digest)` 唯一作用域。旧品牌作用域记录在原 24 小时保留期后自然清理；后续数据库
整理版本可移除 `brand_id` 并把字段重命名为 `normalized_path`。

请求指纹包含规范化路径参数、语义查询参数和请求体。JSON 使用确定性序列化；
multipart 上传把文件字节摘要和其他字段放入指纹，不把音频复制进幂等表。

## 3. 可见性投影

统一使用一个服务函数进行字段投影，不在各路由重复判断。

| 调用方 | `private` | `workshop_public` | `brands_only` | `authorized_brands` |
| --- | --- | --- | --- | --- |
| 所有者/owner 预览 | 可见 | 可见 | 可见 | 可见 |
| 匿名或普通登录用户 | 不可见 | 可见 | 不可见 | 不可见 |
| 任意品牌成员 | 不可见 | 可见 | 可见 | 不可见 |
| 已授权品牌成员 | 不可见 | 可见 | 可见 | 可见 |

线上 Workshop 读取允许可选 Bearer：

- 未携带凭据按 public 投影。
- 携带无效凭据返回 401，不降级为匿名。
- `brand_id` 缺省时不能读取 authorized 字段。
- 传入 `brand_id` 时先检查成员关系，再判断创作者授权。

发现列表始终位于品牌路径中，因此调用方上下文明确。SQL 的搜索、筛选和排序条件
只引用该品牌可见的发布列或子表。响应模型只接收投影后的值。

## 4. API 轮廓

所有下列写接口都要求 `Idempotency-Key`，除非明确标为现有鉴权例外。

### 4.1 品牌组织和邀请

- `POST /api/v1/brands`
- `GET /api/v1/brands`
- `GET /api/v1/brands/{brand_id}`
- `PATCH /api/v1/brands/{brand_id}`
- `GET /api/v1/brands/{brand_id}/members`
- `PATCH /api/v1/brands/{brand_id}/members/{user_id}`
- `DELETE /api/v1/brands/{brand_id}/members/{user_id}`
- `POST /api/v1/brands/{brand_id}/invitations`
- `DELETE /api/v1/brands/{brand_id}/invitations/{invitation_id}`
- `GET /api/v1/users/me/brand-invitations`
- `POST /api/v1/users/me/brand-invitations/{invitation_id}/accept`
- `POST /api/v1/users/me/brand-invitations/{invitation_id}/decline`

### 4.2 橱窗草稿、快照和子资源

- `GET /api/v1/users/me/workshop`
- `PATCH /api/v1/users/me/workshop`
- `GET /api/v1/users/me/workshop/preview?audience=...`
- `POST /api/v1/users/me/workshop/publish`
- `POST /api/v1/users/me/workshop/withdraw`
- `POST|PATCH|DELETE /api/v1/users/me/workshop/social-accounts/...`
- `POST|PATCH|DELETE /api/v1/users/me/workshop/contacts/...`
- `PUT|PATCH|DELETE /api/v1/users/me/workshop/projects/{project_id}`
- `GET /api/v1/workshops/{creator_id}`
- `GET /api/v1/brands/{brand_id}/creator-discovery`

读取草稿响应包含社交、联系方式和精选项目选择，避免为同一编辑页增加多次 GET。

### 4.3 授权、关注、意向和收件箱

- `GET /api/v1/users/me/workshop/brand-authorizations`
- `PUT /api/v1/users/me/workshop/brand-authorizations/{brand_id}`
- `DELETE /api/v1/users/me/workshop/brand-authorizations/{brand_id}`
- `GET /api/v1/brands/{brand_id}/follows`
- `PUT /api/v1/brands/{brand_id}/follows/{creator_id}`
- `DELETE /api/v1/brands/{brand_id}/follows/{creator_id}`
- `GET /api/v1/brands/{brand_id}/interests`
- `POST /api/v1/brands/{brand_id}/interests`
- `PATCH /api/v1/brands/{brand_id}/interests/{interest_id}`
- `GET /api/v1/users/me/brand-inbox`
- `PATCH /api/v1/users/me/brand-inbox/{item_id}`
- `POST /api/v1/users/me/brand-inbox/mark-read`
- `PATCH /api/v1/users/me/brand-interests/{interest_id}`

状态转换在服务层按主体白名单校验。品牌只能把 pending 改为 withdrawn；创作者只能
把 pending 改为 accepted 或 declined。

## 5. 幂等执行

### 5.1 公共契约

- Header 为 8～128 个可打印 ASCII 字符。
- 缺少 Header：`400 idempotency_key_required`。
- 同作用域、同键、不同指纹：`409 idempotency_key_reused`。
- 同请求正在执行：`409 idempotency_request_in_progress`，错误体包含
  `retryable: true`。
- 完成记录：返回原状态码、允许的响应头和解密后的原响应。
- 响应加 `Idempotency-Replayed: true` 表示重放。

注册和登录不经过 Bearer 鉴权，因此不要求 Header。注销是 Bearer 鉴权 DELETE，必须
要求 Header。GET、HEAD、OPTIONS 不要求 Header。

JSON 请求先解析后使用排序键和无冗余空白的确定性 JSON 序列化。查询参数按键值排序。
multipart 指纹由字段值、文件名、媒体类型、文件大小和文件内容 SHA-256 构成，不包含
随机 boundary。

### 5.2 事务

新增 `IdempotencyExecutor` 作为所有已鉴权写路由的统一执行边界。业务 service
逐步改为 `flush` 而不是自行 `commit`；executor 在同一数据库事务中完成业务
变更和 completed 响应记录，再统一提交。

并发首次请求依靠唯一约束和数据库写锁串行化。检测到已完成记录后不再运行 service。
确定性 4xx 可以记录为终态响应；未捕获的 500 不作为可安全重放的完成结果。

长任务使用两阶段状态：

- 先提交 processing 记录和 durable job/resource ID。
- worker 或 Agent 后台任务完成后更新 completed。
- 超时 processing 不自动重新执行副作用，转为安全失败并要求新键。

STT 的幂等结果是同一个 job；Agent 的幂等结果是同一个 turn run。

普通完成记录至少保留 24 小时。商业任务授权和结算在路由完成后把记录保留期延长为
`max(completed_at + 24h, task.deadline + 24h)`，降低任务周期内重复链上交易风险。

### 5.3 现有接口改造

为所有现有已鉴权 POST、PUT、PATCH、DELETE 添加 Header schema 和 executor。
天然幂等的 PUT/DELETE 仍要求 Header，以保持客户端统一契约。OpenAPI 测试扫描
所有写 operation，防止未来新增路由漏接幂等依赖。

## 6. Agent SSE

新增 `run_streamed` 协议和 `OpenAIAgentRunner` 实现，使用当前 SDK 的
`Runner.run_streamed()`。

应用级 `AgentStreamManager` 管理后台 turn：

1. 请求完成鉴权、输入校验、幂等 claim 和对话锁检查。
2. manager 创建后台任务；后台任务使用自己的 SQLAlchemy Session 和 AgentRuntime，
   不复用请求依赖。
3. SDK 事件映射为安全 SSE 事件，通过有界队列发送给当前订阅者。
4. 客户端断开只取消订阅，不取消后台 turn。
5. 最终消息、记忆更新和 idempotency completed 状态持久化后发送
   `turn.completed`。
6. 完成记录重放只发送 `turn.started` 与 `turn.completed`。

SSE 格式：

```text
id: <monotonic event sequence>
event: response.delta
data: {"turn_id":"...","delta":"..."}
```

每个事件的 `data` 是单行 JSON。服务定期发注释 heartbeat，代理需禁用响应缓冲。
事件不得包含模型原始请求、系统提示词、工具参数、联系方式密文或异常堆栈。

工具调用使用 `(turn_run_id, tool_call_id, tool_name)` 派生内部幂等作用域。服务重启
时清理陈旧对话锁并把未完成 run 标记为可恢复失败，不自动重放未知工具副作用。

## 7. 错误码

至少新增：

- `brand_not_found`
- `brand_membership_required`
- `brand_owner_required`
- `brand_last_owner_required`
- `brand_invitation_not_found`
- `brand_invitation_state_conflict`
- `workshop_not_found`
- `workshop_not_published`
- `workshop_visibility_forbidden`
- `brand_authorization_not_found`
- `brand_interest_not_found`
- `brand_interest_state_conflict`
- `creator_inbox_item_not_found`
- `idempotency_key_required`
- `idempotency_key_reused`
- `idempotency_request_in_progress`
- `idempotency_outcome_unknown`

跨租户资源继续用 404。已找到品牌但当前成员权限不足时使用稳定 403。

## 8. 迁移和兼容

- 在当前 Alembic head 后增加一个或多个可独立回滚的 revision。
- 新表和新列不修改现有用户、项目、灵感的语义。
- 幂等 Header 是有意的破坏性 API 契约变更：原有已鉴权写调用方必须升级。
- 非流式 Agent JSON 接口继续存在，但也要求 Idempotency-Key。
- `.env` 不增加必须的外部服务；SQLite 仍是默认数据库。

## 9. 运维和安全

- 联系方式、幂等响应和 Agent 上下文共用当前密钥管理设施，但使用不同的加密用途
  标签，避免密文误用。
- 日志只记录资源 ID、品牌 ID、状态和 key digest 前缀，不记录原始幂等键或联系
  方式。
- 发布和撤回是短事务；外部模型、SSE 等待和客户端连接期间不持有数据库事务。
- 应用关闭时给后台 Agent turn 一个有界收尾窗口，之后标记未完成状态并释放锁。
- 24 小时幂等清理采用限量批次，不能在每个请求上全表扫描。
