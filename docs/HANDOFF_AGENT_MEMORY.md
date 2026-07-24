# Agent 对话与长期记忆接入说明

这套接口让 InspireFlow 在不同登录会话之间继续同一段创作对话，并在同一用户
的不同对话之间共享经过筛选的长期记忆。原始对话不会跨项目串联；只有创作者
资料和活跃长期记忆会跨对话使用。

## 运行前配置

先升级数据库：

```bash
uv sync --locked --dev
uv run alembic upgrade head
```

`.env` 至少需要配置一个 OpenAI 兼容模型：

```dotenv
MODEL_API_KEY=<由密钥管理系统注入>
MODEL_NAME=<模型名称>
MODEL_BASE_URL=https://<provider-host>/v1
```

`MODEL_BASE_URL` 可以填写 API 根地址，也可以填写完整的
`/chat/completions` 地址；运行时会自动规范化。只要服务兼容 OpenAI Chat
Completions 协议，就不限定具体模型厂商。不要把真实值复制到示例、日志或提交
中。资料、记忆和对话列表不调用模型；只有发送消息时需要这三项配置。

对话消息、摘要和记忆内容使用 Fernet 加密。部署环境建议通过
`APP_CONTEXT_ENCRYPTION_KEY` 注入固定密钥。本地未配置时，应用会创建
`.inspireflow-context.key`，权限为 `0600`，并由 `.gitignore` 排除。务必安全
备份：密钥丢失后，已有密文无法恢复。更换密钥前需要单独设计数据重加密流程，
不能直接覆盖文件。

上下文默认配置如下：

| 环境变量 | 默认值 | 说明 |
| --- | ---: | --- |
| `APP_AGENT_CONTEXT_TRIGGER_CHARACTERS` | `24000` | 触发滚动摘要的未压缩历史长度 |
| `APP_AGENT_CONTEXT_MAX_CHARACTERS` | `48000` | 单次模型输入的硬上限 |
| `APP_AGENT_CONTEXT_RECENT_TURNS` | `8` | 压缩后保留的最近完整轮次 |
| `APP_AGENT_CONTEXT_SUMMARY_MAX_CHARACTERS` | `6000` | 摘要上限 |
| `APP_AGENT_MEMORY_MAX_ITEMS` | `30` | 单次注入的记忆条数上限 |
| `APP_AGENT_MEMORY_MAX_CHARACTERS` | `8000` | 记忆区字符预算 |
| `APP_AGENT_RUN_LOCK_TTL_SECONDS` | `600` | 异常运行锁的回收时间 |

## 认证

先按 [用户系统接入说明](HANDOFF_USERSYS.MD) 注册、登录并取得 Bearer 令牌：

```bash
export BASE_URL="${BASE_URL:-http://127.0.0.1:8000/api/v1}"
export ACCESS_TOKEN='<登录接口返回的令牌>'
```

下面所有接口都使用：

```text
Authorization: Bearer <access-token>
```

Bearer 登录会话只证明用户身份。Agent 对话是独立的持久化资源。注销、令牌过期
或重新登录不会删除对话。

对话响应中的 `id` 就是 Agent 的持久化 session ID。后续请求同时使用这个 ID
和 Bearer 令牌定位对话：服务会按“当前令牌对应的用户 + session ID”查询，因此
另一个用户即使拿到相同 ID，也只会收到 `404 conversation_not_found`。

## 创建和继续对话

创建对话：

```bash
CONVERSATION="$(
  curl --fail-with-body \
    --request POST "$BASE_URL/conversations" \
    --header 'Content-Type: application/json' \
    --header "Authorization: Bearer $ACCESS_TOKEN" \
    --data '{"title":"本地 AI 工具选题"}'
)"
CONVERSATION_ID="$(
  printf '%s' "$CONVERSATION" |
    uv run python -c 'import json, sys; print(json.load(sys.stdin)["id"])'
)"
```

发送一条消息：

```bash
curl --fail-with-body \
  --request POST "$BASE_URL/conversations/$CONVERSATION_ID/messages" \
  --header 'Content-Type: application/json' \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --data '{"content":"我想做一期普通人如何在本地运行小模型的视频"}'
```

成功返回 `201`，包含本轮用户消息、助手消息、接受的记忆更新和提取状态：

```json
{
  "turn_id": "00000000-0000-4000-8000-000000000001",
  "user_message": {
    "id": "00000000-0000-4000-8000-000000000002",
    "turn_id": "00000000-0000-4000-8000-000000000001",
    "sequence": 1,
    "role": "user",
    "content": "我想做一期普通人如何在本地运行小模型的视频",
    "created_at": "2026-07-24T10:00:00Z"
  },
  "assistant_message": {
    "id": "00000000-0000-4000-8000-000000000003",
    "turn_id": "00000000-0000-4000-8000-000000000001",
    "sequence": 2,
    "role": "assistant",
    "content": "你更想面向完全没接触过本地模型的新手，还是已有基础的开发者？",
    "created_at": "2026-07-24T10:00:02Z"
  },
  "memory_updates": [],
  "memory_extraction_status": "completed"
}
```

接口当前不流式返回。模型搜索、网页抓取和多轮工具调用都会计入请求耗时。客户端
超时后不要立即重复发送相同内容；先读取消息列表，确认用户消息或助手回复是否
已经保存，再决定是否重试。

## 对话和消息列表

```text
GET    /api/v1/conversations
GET    /api/v1/conversations/{conversation_id}
PATCH  /api/v1/conversations/{conversation_id}
DELETE /api/v1/conversations/{conversation_id}
GET    /api/v1/conversations/{conversation_id}/messages
```

对话列表使用 `limit`、`offset`，默认不返回归档项。传
`include_archived=true` 可以包含归档对话。PATCH 支持修改 `title` 或设置
`archived`。归档对话仍可读取，但发送新消息会返回
`409 conversation_archived`，解除归档后可以继续。

消息列表只公开用户和助手文本，内部工具调用不会出现在响应里：

```bash
curl --fail-with-body \
  "$BASE_URL/conversations/$CONVERSATION_ID/messages?after_sequence=0&limit=50" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

存在下一页时，响应的 `next_cursor` 是本页最后一条消息的 sequence。把它作为
下一次 `after_sequence`。

删除对话会删除原始消息和摘要。自动提取、从未编辑且未置顶的记忆也随之删除。
用户明确要求保存、后来编辑或置顶过的记忆继续保留，并标记原始来源已经删除，
但不会保留被删除消息的原文。

## Agent 用户资料与文本画像

Agent 另有两个只作用于当前鉴权用户的内部工具：

```text
update_current_user(nickname=None, avatar_url=None, clear_avatar=False)
update_user_profile_text(profile_text=None, clear_profile_text=False)
```

工具参数不接受 `user_id`。昵称和头像只有在用户明确要求修改时才能写入；普通
聊天不会自动改名或替换头像。

长期文本画像保存在 `users.profile_text`，最多 8000 个字符。Agent 可以从普通
对话中主动归纳用户明确表达、可跨会话复用的信息，并在后续对话中读取。模型推测
不能写成事实；敏感信息只有在用户明确要求记住时才能加入。每次更新会替换完整
画像，所以 Agent 会结合现有画像保留仍然有效的信息。密码、登录令牌、API key、
私钥和恢复码无论用户如何要求都不会写入画像。

`profile_text` 是 Agent 内部上下文，不会出现在 `GET /api/v1/users/me`，也不能
通过 `PATCH /api/v1/users/me` 直接修改。原有
`GET/PATCH /api/v1/users/me/profile` 结构化创作者资料保持不变。

## 长期记忆

手工创建记忆：

```bash
curl --fail-with-body \
  --request POST "$BASE_URL/users/me/memories" \
  --header 'Content-Type: application/json' \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --data '{
    "category":"workflow_preference",
    "content":"脚本确认后再生成分镜",
    "status":"active",
    "is_sensitive":false,
    "is_pinned":true
  }'
```

支持的类别为：

- `creative_focus`
- `creative_preference`
- `workflow_preference`
- `collaboration_preference`
- `project_context`
- `personal_detail`
- `other`

读取、修改和删除：

```text
GET    /api/v1/users/me/memories
GET    /api/v1/users/me/memories/{memory_id}
PATCH  /api/v1/users/me/memories/{memory_id}
DELETE /api/v1/users/me/memories/{memory_id}
```

列表支持 `status`、`category`、`limit` 和 `offset`。只有 `active` 记忆会进入
模型上下文，置顶项优先。

低敏感、由用户明确说出的事实可以自动提取。生日、真实姓名、联系方式等敏感
信息，只有用户在同一条消息里明确说“请记住”或类似表达时才允许保存。密码、
登录令牌、API key、私钥和恢复码无论用户是否要求都不会进入长期记忆；对话中
识别出的凭据会先替换为 `[REDACTED_CREDENTIAL]`。

## 稳定错误

错误都使用 `{"error":{"code":"...","message":"..."}}`：

| HTTP | code | 含义 |
| ---: | --- | --- |
| `401` | `invalid_session` | Bearer 会话不可用 |
| `404` | `conversation_not_found` | 对话不存在或不属于当前用户 |
| `404` | `memory_not_found` | 记忆不存在或不属于当前用户 |
| `409` | `conversation_archived` | 对话已归档 |
| `409` | `conversation_busy` | 同一对话已有运行中的请求 |
| `422` | `credential_memory_forbidden` | 请求保存凭据型内容 |
| `422` | `validation_error` | 请求字段不合法 |
| `502` | `agent_run_failed` | 模型或 Agent 未完成本轮 |
| `503` | `agent_unavailable` | 模型配置缺失 |
| `503` | `context_storage_unavailable` | 加密密钥不可用或密文无法解密 |

`agent_run_failed` 不返回上游异常、密钥或模型原始错误。模型失败前已经提交的用户
消息会保留，可通过消息列表查看。记忆提取失败不会撤销成功的助手回复。

## 迁移和回滚

`20260724_0002` 会创建创作者资料、对话、消息和记忆表，并为已有用户回填空
资料。降级到 `20260723_0001` 会删除这四张表及其中数据，是破坏性操作；执行前
必须备份数据库和加密密钥。

`20260724_0008` 会给 `users` 增加可为空的 `profile_text`。升级不会回填或修改
现有用户；降级到 `20260724_0007` 会删除该列及其中画像文本。
