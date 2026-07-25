# InspireFlow 后端 API 接入手册

这份文档面向前端、客户端和后续接手后端的开发者，内容以当前代码里的
OpenAPI 定义为准。默认地址是 `http://127.0.0.1:8000`，所有业务接口继续使用
`/api/v1` 前缀。

## 1. 启动服务

安装依赖并升级数据库：

```bash
uv sync --locked --dev
uv run alembic upgrade head
```

启动 FastAPI：

```bash
uv run uvicorn inspire_flow_backend.main:app --reload
```

启动后可以访问：

- Swagger UI：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`

本地配置放在 `.env`，这个文件已经加入 `.gitignore`。至少需要关注以下配置：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_DATABASE_URL` | `sqlite:///./inspire_flow.db` | 数据库地址 |
| `APP_SESSION_TTL_HOURS` | `24` | 登录凭据有效期，单位为小时 |
| `APP_CONTEXT_ENCRYPTION_KEY` | 空 | 对话、摘要和记忆的 Fernet 密钥 |
| `MODEL_API_KEY` | 空 | OpenAI Chat Completions 兼容接口的密钥 |
| `MODEL_NAME` | 空 | Agent、摘要器和记忆提取器使用的模型 |
| `MODEL_BASE_URL` | 空 | API 根地址或完整的 `/chat/completions` 地址 |
| `APP_STT_ENABLED` | `false` | 是否允许提交语音转文字任务 |
| `APP_STT_BROKER_URL` | `redis://127.0.0.1:6379/0` | STT Celery 使用的 Redis |
| `APP_STT_API_KEY` | 空 | Hack Club AI 密钥，启用 STT worker 时必填 |
| `APP_STT_BASE_URL` | `https://ai.hackclub.com/proxy/v1/replicate` | Replicate 代理地址 |

模型没有配置时，注册、登录、手动维护项目等普通接口仍可使用，但 Agent
对话和项目草稿生成会返回 `503 agent_unavailable`。STT 没有启用或 worker
未就绪时，提交任务会返回 `503 stt_unavailable`。

## 2. 调用约定

### 2.1 准备终端变量

后续示例共用这些变量：

```bash
export API_BASE="${API_BASE:-http://127.0.0.1:8000/api/v1}"
export NICKNAME="${NICKNAME:-demo_creator}"

printf 'Password: '
read -r -s ACCOUNT_PASSWORD
printf '\n'
export ACCOUNT_PASSWORD
```

密码不会直接写进命令历史。注册或登录后，再设置这些变量：

```bash
export ACCESS_TOKEN='<登录接口返回的 access_token>'
export PROJECT_ID='<项目 UUID>'
export INSPIRATION_ID='<灵感 UUID>'
export CONVERSATION_ID='<对话 UUID>'
export MEMORY_ID='<记忆 UUID>'
export JOB_ID='<转写任务 UUID>'
export BRAND_ID='<品牌组织 UUID>'
export CREATOR_ID='<创作者用户 UUID>'
export INTEREST_ID='<合作意向 UUID>'
export INBOX_ITEM_ID='<收件箱条目 UUID>'
```

业务写请求还要提供一个 8～128 字符的幂等键。每次新操作生成新键；网络重试必须
复用原键和原请求内容：

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
```

### 2.2 请求和响应

- JSON 请求使用 `Content-Type: application/json`。
- 除健康检查和已发布橱窗公开读取外，其余接口都需要
  `Authorization: Bearer <access_token>`。
- 所有已鉴权业务写请求都必须带 `Idempotency-Key`。注册、登录和注销例外。
- ID 使用 UUID 字符串。
- 时间使用 ISO 8601 格式，一般为 UTC，例如
  `2026-07-24T10:00:00Z`。
- 可选字段没有值时返回 `null`，不是空字符串。
- 成功删除、注销和关联操作返回 `204 No Content`，响应体为空。
- 列表接口使用 `limit` 和 `offset`；对话消息使用
  `after_sequence` 游标。

分页响应通常是：

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

### 2.3 错误格式

业务错误使用统一外层结构：

```json
{
  "error": {
    "code": "project_not_found",
    "message": "Project not found."
  }
}
```

字段校验失败时会附带 `details`：

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [
      {
        "location": ["body", "title"],
        "message": "String should have at least 1 character",
        "type": "string_too_short"
      }
    ]
  }
}
```

客户端应优先按 `error.code` 分支，不要依赖英文 `message`。主要错误码见本文末尾。

## 3. 健康检查

### GET /api/v1/health

不需要登录。接口会实际探测数据库，但不会向模型服务发请求。

```bash
curl --fail-with-body "$API_BASE/health"
```

正常或缺少可选配置时返回 `200`：

```json
{
  "status": "degraded",
  "services": {
    "database": "ok",
    "model": "not_configured",
    "injective": "not_configured"
  },
  "version": "dev",
  "service": "Inspire Flow Backend",
  "environment": "development"
}
```

`status` 可能是 `ok`、`degraded` 或 `unavailable`。数据库不可用时返回 `503`，
此时响应结构不变，`services.database` 为 `unavailable`。

`services.injective` 在配置了 `APP_INJECTIVE_PRIVATE_KEY` 时为 `ok`，否则为
`not_configured`。只有数据库、模型、Injective 三者都就绪时 `status` 才是 `ok`；
缺少模型或链上配置时为 `degraded`，接口仍可正常使用其它能力。

## 4. 用户与登录

公开用户结构如下：

```json
{
  "id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
  "nickname": "demo_creator",
  "avatar_url": null,
  "created_at": "2026-07-24T10:00:00Z",
  "updated_at": "2026-07-24T10:00:00Z"
}
```

`profile_text` 是 Agent 维护的内部用户画像，不会出现在用户资料接口里。

### POST /api/v1/users

注册新用户，不会自动登录。

请求字段：

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `nickname` | string | 是 | 规范化后 2～50 个字符，不能只含空白 |
| `password` | string | 是 | 15～128 个字符 |
| `avatar_url` | string 或 null | 否 | HTTP(S) 地址，最长 2048 个字符 |

```bash
curl --fail-with-body \
  --request POST "$API_BASE/users" \
  --header 'Content-Type: application/json' \
  --data "$(
    NICKNAME="$NICKNAME" ACCOUNT_PASSWORD="$ACCOUNT_PASSWORD" uv run python -c \
      'import json, os; print(json.dumps({"nickname": os.environ["NICKNAME"], "password": os.environ["ACCOUNT_PASSWORD"]}))'
  )"
```

成功返回 `201` 和公开用户结构。昵称按 Unicode NFKC 规范化和大小写折叠后
检查唯一性；冲突时返回 `409 nickname_conflict`。

### GET /api/v1/users/me

读取当前登录用户。

```bash
curl --fail-with-body "$API_BASE/users/me" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200` 和公开用户结构。

### PATCH /api/v1/users/me

修改昵称或头像，至少提交一个字段。`nickname` 不能为 `null`；
`avatar_url: null` 表示清除头像。

```bash
curl --fail-with-body \
  --request PATCH "$API_BASE/users/me" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "nickname": "demo_creator_updated",
    "avatar_url": "https://cdn.example.com/avatars/demo.png"
  }'
```

成功返回 `200` 和更新后的公开用户结构。昵称被占用时返回
`409 nickname_conflict`。

### POST /api/v1/sessions

用昵称和密码登录。

```bash
LOGIN_RESPONSE="$(
  curl --fail-with-body \
    --request POST "$API_BASE/sessions" \
    --header 'Content-Type: application/json' \
    --data "$(
      NICKNAME="$NICKNAME" ACCOUNT_PASSWORD="$ACCOUNT_PASSWORD" uv run python -c \
        'import json, os; print(json.dumps({"nickname": os.environ["NICKNAME"], "password": os.environ["ACCOUNT_PASSWORD"]}))'
    )"
)"
printf '%s\n' "$LOGIN_RESPONSE"
```

成功返回 `201`：

```json
{
  "access_token": "<只在登录响应中返回的随机凭据>",
  "token_type": "bearer",
  "expires_at": "2026-07-25T10:00:00Z",
  "user": {
    "id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
    "nickname": "demo_creator",
    "avatar_url": null,
    "created_at": "2026-07-24T10:00:00Z",
    "updated_at": "2026-07-24T10:00:00Z"
  }
}
```

可直接从响应中取出凭据：

```bash
export ACCESS_TOKEN="$(
  printf '%s' "$LOGIN_RESPONSE" |
    uv run python -c 'import json, sys; print(json.load(sys.stdin)["access_token"])'
)"
unset ACCOUNT_PASSWORD
```

账号不存在和密码错误统一返回 `401 invalid_credentials`，避免暴露账号是否存在。
响应带有 `Cache-Control: no-store` 和 `Pragma: no-cache`。

### DELETE /api/v1/sessions/current

注销当前凭据。注销不会删除用户、项目、对话或记忆。

```bash
curl --fail-with-body \
  --request DELETE "$API_BASE/sessions/current" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `204`，之后继续使用同一凭据会得到 `401 invalid_session`。

## 5. 创作者资料

这是供产品界面编辑的结构化资料，与 Agent 内部的 `profile_text` 分开。

```json
{
  "user_id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
  "bio": "记录独立开发和影像制作。",
  "timezone": "Asia/Shanghai",
  "preferred_language": "zh-CN",
  "creator_identity": "科技区 UP 主",
  "content_focus": ["独立开发", "效率工具"],
  "collaboration_preferences": "优先异步沟通，商业合作需先确认预算。",
  "created_at": "2026-07-24T10:00:00Z",
  "updated_at": "2026-07-24T10:00:00Z"
}
```

### GET /api/v1/users/me/profile

读取当前用户的结构化创作者资料。资料未单独编辑时也会返回完整结构，
可选字段为 `null` 或空列表。

```bash
curl --fail-with-body "$API_BASE/users/me/profile" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200`。

### PATCH /api/v1/users/me/profile

至少提交一个字段：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `bio` | string 或 null | 最长 1000，空白按 `null` 处理 |
| `timezone` | string 或 null | 最长 64，必须是有效 IANA 时区 |
| `preferred_language` | string 或 null | 最长 35，不能只含空白 |
| `creator_identity` | string 或 null | 最长 100，不能只含空白 |
| `content_focus` | string[] 或 null | 最多 20 项，每项最长 100；会去空白和重复 |
| `collaboration_preferences` | string 或 null | 最长 2000，空白按 `null` 处理 |

```bash
curl --fail-with-body \
  --request PATCH "$API_BASE/users/me/profile" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "bio": "记录独立开发和影像制作。",
    "timezone": "Asia/Shanghai",
    "preferred_language": "zh-CN",
    "creator_identity": "科技区 UP 主",
    "content_focus": ["独立开发", "效率工具"],
    "collaboration_preferences": "优先异步沟通，商业合作需先确认预算。"
  }'
```

成功返回 `200` 和更新后的结构化资料。

## 6. 长期记忆

长期记忆按用户隔离并加密保存。普通记忆可以由 Agent 自动提取，也可以由用户
明确创建。自动提取且没有被用户编辑或固定的记忆，会在来源对话删除时一并删除；
用户明确保存、编辑或固定过的记忆继续保留。

记忆结构：

```json
{
  "id": "cb09e4dc-69e6-42fd-94a4-b7e2ed552581",
  "user_id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
  "category": "creative_preference",
  "content": "视频开场偏好直接进入主题。",
  "status": "active",
  "origin": "manual",
  "is_sensitive": false,
  "is_pinned": true,
  "user_edited": false,
  "source_conversation_id": null,
  "source_deleted_at": null,
  "created_at": "2026-07-24T10:00:00Z",
  "updated_at": "2026-07-24T10:00:00Z"
}
```

`category` 可取：

- `creative_focus`
- `creative_preference`
- `workflow_preference`
- `collaboration_preference`
- `project_context`
- `personal_detail`
- `other`

`status` 为 `active` 或 `inactive`。`origin` 为 `automatic`、`explicit` 或
`manual`。从管理接口创建的记忆是 `manual`；Agent 根据用户明确要求保存时是
`explicit`，自动提取时是 `automatic`。

### POST /api/v1/users/me/memories

手动创建一条记忆。`content` 为 1～2000 个字符。

```bash
curl --fail-with-body \
  --request POST "$API_BASE/users/me/memories" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "category": "creative_preference",
    "content": "视频开场偏好直接进入主题。",
    "status": "active",
    "is_sensitive": false,
    "is_pinned": true
  }'
```

成功返回 `201` 和记忆结构。接口会把来源标记为 `manual`。看起来像密码、
令牌或私钥的内容不会入库，会返回 `422 credential_memory_forbidden`。

### GET /api/v1/users/me/memories

查询记忆。可用参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `status` | string | 无 | `active` 或 `inactive` |
| `category` | string | 无 | 按记忆分类筛选 |
| `limit` | integer | `50` | 1～100 |
| `offset` | integer | `0` | 大于等于 0 |

```bash
curl --fail-with-body \
  "$API_BASE/users/me/memories?status=active&category=creative_preference&limit=20&offset=0" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200`：

```json
{
  "items": [],
  "total": 0,
  "limit": 20,
  "offset": 0
}
```

### GET /api/v1/users/me/memories/{memory_id}

读取一条记忆。只能读取自己的记录。

```bash
curl --fail-with-body "$API_BASE/users/me/memories/$MEMORY_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200` 和记忆结构。不存在或属于其他用户时返回
`404 memory_not_found`。

### PATCH /api/v1/users/me/memories/{memory_id}

至少提交一个字段，可修改 `category`、`content`、`status`、`is_sensitive`
或 `is_pinned`。已提交字段不能为 `null`。

```bash
curl --fail-with-body \
  --request PATCH "$API_BASE/users/me/memories/$MEMORY_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "content": "视频开场要在 10 秒内进入主题。",
    "is_pinned": true
  }'
```

成功返回 `200`。通过这个接口编辑后，`user_edited` 会反映用户干预状态，
不会再按普通自动记忆处理。

### DELETE /api/v1/users/me/memories/{memory_id}

永久删除一条记忆。

```bash
curl --fail-with-body \
  --request DELETE "$API_BASE/users/me/memories/$MEMORY_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

成功返回 `204`。

## 7. 项目

项目始终绑定当前登录用户。公开结构如下：

```json
{
  "id": "31baf982-bcca-478e-bf81-2852825813f8",
  "user_id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
  "title": "一周做出个人知识库",
  "type": "科技",
  "audience": "对 AI 工具和独立开发感兴趣的 B 站用户",
  "summary": "记录从需求整理到发布的完整过程。",
  "icon_url": null,
  "created_at": "2026-07-24T10:00:00Z",
  "updated_at": "2026-07-24T10:00:00Z"
}
```

字段约束：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `title` | string | 1～120 |
| `type` | string | 1～50，例如 B 站分区或自定义类型 |
| `audience` | string | 1～500 |
| `summary` | string | 1～2000 |
| `icon_url` | string 或 null | HTTP(S) 地址，最长 2048；未设置返回 `null` |

### POST /api/v1/projects

手动保存项目。

```bash
curl --fail-with-body \
  --request POST "$API_BASE/projects" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "title": "一周做出个人知识库",
    "type": "科技",
    "audience": "对 AI 工具和独立开发感兴趣的 B 站用户",
    "summary": "记录从需求整理到发布的完整过程。",
    "icon_url": null
  }'
```

成功返回 `201` 和项目结构。

### GET /api/v1/projects

读取当前用户的项目列表。

| 参数 | 类型 | 默认值 | 约束 |
| --- | --- | --- | --- |
| `limit` | integer | `50` | 1～100 |
| `offset` | integer | `0` | 大于等于 0 |

```bash
curl --fail-with-body "$API_BASE/projects?limit=20&offset=0" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200`：

```json
{
  "items": [],
  "total": 0,
  "limit": 20,
  "offset": 0
}
```

### POST /api/v1/projects/drafts

让 Agent 根据一段描述整理项目草稿。草稿不会写入数据库，也没有
`id`、`user_id` 和时间字段。用户确认或修改后，再调用项目创建接口保存。

```bash
curl --fail-with-body \
  --request POST "$API_BASE/projects/drafts" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "description": "我想拍一期视频，记录自己一周内做出个人知识库的过程，观众是对 AI 工具感兴趣的普通用户。"
  }'
```

`description` 长度为 1～4000。成功返回 `200`：

```json
{
  "title": "一周做出个人知识库",
  "type": "科技",
  "audience": "对 AI 工具感兴趣的普通用户",
  "summary": "记录从需求整理、开发到实际使用的过程。",
  "icon_url": null
}
```

模型未配置时返回 `503 agent_unavailable`；上游调用失败时返回
`502 agent_run_failed`。

### GET /api/v1/projects/{project_id}

读取项目详情。详情比列表项多一个 `inspiration_count`。

```bash
curl --fail-with-body "$API_BASE/projects/$PROJECT_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200`：

```json
{
  "id": "31baf982-bcca-478e-bf81-2852825813f8",
  "user_id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
  "title": "一周做出个人知识库",
  "type": "科技",
  "audience": "对 AI 工具感兴趣的 B 站用户",
  "summary": "记录从需求整理到发布的完整过程。",
  "icon_url": null,
  "created_at": "2026-07-24T10:00:00Z",
  "updated_at": "2026-07-24T10:00:00Z",
  "inspiration_count": 2
}
```

项目不存在或属于其他用户时返回 `404 project_not_found`。

### PATCH /api/v1/projects/{project_id}

修改项目，至少提交一个字段。只有 `icon_url` 可以为 `null`，用于清除图标。

```bash
curl --fail-with-body \
  --request PATCH "$API_BASE/projects/$PROJECT_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "title": "7 天做出个人知识库",
    "icon_url": null
  }'
```

成功返回 `200` 和更新后的项目结构。

### DELETE /api/v1/projects/{project_id}

删除项目。若删除后会让某些灵感失去全部项目和来源关联，接口先返回 `409`：

```json
{
  "error": {
    "code": "orphaned_inspirations_confirmation_required",
    "message": "Deleting this resource would orphan inspirations.",
    "details": [
      {
        "id": "b76aa902-eacc-4c53-9527-195730dbb40a",
        "title": "演示自动字幕前后对比"
      }
    ]
  }
}
```

先按默认方式请求，客户端据此向用户展示受影响的灵感：

```bash
curl --fail-with-body \
  --request DELETE "$API_BASE/projects/$PROJECT_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

用户明确同意连同孤立灵感一起删除后，重试：

```bash
curl --fail-with-body \
  --request DELETE "$API_BASE/projects/$PROJECT_ID?delete_orphan_inspirations=true" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

成功返回 `204`。不要在界面上默认传 `true`。

### GET /api/v1/projects/{project_id}/inspirations

查询某个项目关联的灵感。支持的查询参数：

| 参数 | 类型 | 默认值 |
| --- | --- | --- |
| `status` | `inbox`、`developing`、`converted`、`archived` | 无 |
| `source_type` | `manual`、`agent`、`voice` | 无 |
| `query` | string，最长 300 | 无 |
| `sort_by` | `created_at` 或 `updated_at` | `updated_at` |
| `sort_order` | `asc` 或 `desc` | `desc` |
| `limit` | integer，1～100 | `50` |
| `offset` | integer，大于等于 0 | `0` |

```bash
curl --fail-with-body \
  "$API_BASE/projects/$PROJECT_ID/inspirations?status=developing&sort_by=updated_at&sort_order=desc&limit=20&offset=0" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200` 和灵感分页结构，格式见下一节。

## 8. 灵感

灵感可以来自手动输入、语音识别或 Agent 对话，并且能同时关联多个项目。

灵感结构：

```json
{
  "id": "b76aa902-eacc-4c53-9527-195730dbb40a",
  "user_id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
  "title": "演示自动字幕前后对比",
  "content": "录一段有背景音乐的口播，展示转写文本和情绪标签。",
  "status": "developing",
  "source_type": "manual",
  "source_conversation_id": null,
  "source_message_id": null,
  "projects": [
    {
      "id": "31baf982-bcca-478e-bf81-2852825813f8",
      "title": "一周做出个人知识库",
      "icon_url": null
    }
  ],
  "created_at": "2026-07-24T10:00:00Z",
  "updated_at": "2026-07-24T10:00:00Z"
}
```

`status` 可取 `inbox`、`developing`、`converted`、`archived`。公开创建接口的
`source_type` 只接受 `manual` 或 `voice`；Agent 创建的记录会显示为 `agent`。

一条没有项目、对话或消息来源的灵感只能留在 `inbox`。把这种灵感改成其他
状态，或移除它最后一个有效关联时，接口返回
`409 inspiration_association_required`。这条规则用于避免产生无法追溯的孤立灵感。

### POST /api/v1/inspirations

创建灵感。

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `title` | string 或 null | 否 | 最长 120；传字符串时不能只含空白 |
| `content` | string | 是 | 1～20000，不能只含空白 |
| `status` | string | 否 | 默认 `inbox` |
| `source_type` | string | 否 | `manual` 或 `voice`，默认 `manual` |
| `project_ids` | UUID[] | 否 | 最多 100 个，不能重复，默认空列表 |

```bash
curl --fail-with-body \
  --request POST "$API_BASE/inspirations" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data "{
    \"title\": \"演示自动字幕前后对比\",
    \"content\": \"录一段有背景音乐的口播，展示转写文本和情绪标签。\",
    \"status\": \"developing\",
    \"source_type\": \"manual\",
    \"project_ids\": [\"$PROJECT_ID\"]
  }"
```

成功返回 `201` 和灵感结构。若 `status` 不是 `inbox`，请求中至少要有一个
有效的 `project_ids`。

### GET /api/v1/inspirations

查询当前用户的灵感。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `project_id` | UUID | 无 | 按关联项目筛选 |
| `status` | string | 无 | 按状态筛选 |
| `source_type` | string | 无 | `manual`、`agent` 或 `voice` |
| `query` | string | 无 | 标题或内容关键词，最长 300 |
| `sort_by` | string | `updated_at` | `created_at` 或 `updated_at` |
| `sort_order` | string | `desc` | `asc` 或 `desc` |
| `limit` | integer | `50` | 1～100 |
| `offset` | integer | `0` | 大于等于 0 |

```bash
curl --fail-with-body \
  "$API_BASE/inspirations?project_id=$PROJECT_ID&query=%E5%AD%97%E5%B9%95&sort_by=updated_at&sort_order=desc&limit=20&offset=0" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200`：

```json
{
  "items": [],
  "total": 0,
  "limit": 20,
  "offset": 0
}
```

### GET /api/v1/inspirations/{inspiration_id}

读取一条灵感。

```bash
curl --fail-with-body "$API_BASE/inspirations/$INSPIRATION_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200` 和灵感结构。记录不存在或属于其他用户时返回
`404 inspiration_not_found`。

### PATCH /api/v1/inspirations/{inspiration_id}

修改灵感，至少提交一个字段。

- `title: null` 表示清除标题。
- `content` 和 `status` 一旦提交就不能为 `null`。
- `project_ids` 表示完整替换项目关联，不是追加；提交时不能为 `null`。
- 替换关联后仍需满足“非收件箱灵感必须有来源或项目”的规则。

```bash
curl --fail-with-body \
  --request PATCH "$API_BASE/inspirations/$INSPIRATION_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data "{
    \"title\": \"字幕与情绪识别对比\",
    \"status\": \"developing\",
    \"project_ids\": [\"$PROJECT_ID\"]
  }"
```

成功返回 `200` 和更新后的灵感结构。

### DELETE /api/v1/inspirations/{inspiration_id}

永久删除灵感本身和它的项目关联。

```bash
curl --fail-with-body \
  --request DELETE "$API_BASE/inspirations/$INSPIRATION_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

成功返回 `204`。

### PUT /api/v1/inspirations/{inspiration_id}/projects/{project_id}

把灵感关联到项目。重复调用不会创建重复关联。

```bash
curl --fail-with-body \
  --request PUT "$API_BASE/inspirations/$INSPIRATION_ID/projects/$PROJECT_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

成功返回 `204`。灵感和项目都必须属于当前用户。

### DELETE /api/v1/inspirations/{inspiration_id}/projects/{project_id}

移除一条项目关联。

```bash
curl --fail-with-body \
  --request DELETE "$API_BASE/inspirations/$INSPIRATION_ID/projects/$PROJECT_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

成功返回 `204`。如果这是非 `inbox` 灵感的最后一个有效来源，接口返回
`409 inspiration_association_required`。客户端可以先把灵感改回 `inbox`，
再移除关联。

## 9. Agent 对话

对话 UUID 就是 Agent 的持久 `session_id`。后端会同时使用 Bearer 凭据中的
用户 ID 和这个 UUID 定位上下文，所以同一个用户重新登录后仍能继续原对话，
其他用户拿到 UUID 也读不到内容。

对话结构：

```json
{
  "id": "f707fb86-4356-4e62-9127-55ae8bc82363",
  "user_id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
  "title": "个人知识库视频策划",
  "archived": false,
  "created_at": "2026-07-24T10:00:00Z",
  "updated_at": "2026-07-24T10:00:00Z"
}
```

消息结构：

```json
{
  "id": "499c999d-cea7-463b-a194-4741a43043a5",
  "turn_id": "5c052f94-d4ef-4fcb-966b-4b5148cbd65a",
  "sequence": 1,
  "role": "user",
  "content": "我想拍一期一周做出个人知识库的视频。",
  "created_at": "2026-07-24T10:05:00Z"
}
```

对话内容、滚动摘要和长期记忆都按用户隔离并加密保存。达到本地上下文阈值后，
服务会压缩较早内容，保留摘要和最近完整轮次，客户端无需手动触发。

### POST /api/v1/conversations

创建空对话。`title` 可省略或传 `null`，最长 120 个字符；空白标题按
`null` 处理。

```bash
curl --fail-with-body \
  --request POST "$API_BASE/conversations" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "title": "个人知识库视频策划"
  }'
```

成功返回 `201` 和对话结构。

### GET /api/v1/conversations

查询当前用户的对话。

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `include_archived` | boolean | `false` | 是否包含已归档对话 |
| `limit` | integer | `50` | 1～100 |
| `offset` | integer | `0` | 大于等于 0 |

```bash
curl --fail-with-body \
  "$API_BASE/conversations?include_archived=false&limit=20&offset=0" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200`：

```json
{
  "items": [],
  "total": 0,
  "limit": 20,
  "offset": 0
}
```

### GET /api/v1/conversations/{conversation_id}

读取对话元数据，不包含消息正文。

```bash
curl --fail-with-body "$API_BASE/conversations/$CONVERSATION_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200` 和对话结构。不存在或属于其他用户时返回
`404 conversation_not_found`。

### PATCH /api/v1/conversations/{conversation_id}

修改标题或归档状态，至少提交一个字段。`title: null` 或空白字符串会清除标题；
`archived` 不能为 `null`。

```bash
curl --fail-with-body \
  --request PATCH "$API_BASE/conversations/$CONVERSATION_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "title": "个人知识库视频：大纲与分镜",
    "archived": false
  }'
```

成功返回 `200` 和更新后的对话结构。

### DELETE /api/v1/conversations/{conversation_id}

删除对话、消息和可随来源删除的自动记忆。用户编辑、明确保存或固定过的记忆
继续保留，并记录来源已删除。

如果删除对话会让某些灵感失去全部来源和项目关联，先返回
`409 orphaned_inspirations_confirmation_required`，`details` 中列出受影响灵感。

先进行普通删除：

```bash
curl --fail-with-body \
  --request DELETE "$API_BASE/conversations/$CONVERSATION_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

用户确认同时删除孤立灵感后重试：

```bash
curl --fail-with-body \
  --request DELETE "$API_BASE/conversations/$CONVERSATION_ID?delete_orphan_inspirations=true" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

成功返回 `204`。和项目删除一样，前端不应默认绕过确认。

### GET /api/v1/conversations/{conversation_id}/messages

按消息序号读取对话内容。`after_sequence` 表示只返回序号大于该值的消息，
适合首次加载和增量拉取。

| 参数 | 类型 | 默认值 | 约束 |
| --- | --- | --- | --- |
| `after_sequence` | integer | `0` | 大于等于 0 |
| `limit` | integer | `50` | 1～100 |

```bash
curl --fail-with-body \
  "$API_BASE/conversations/$CONVERSATION_ID/messages?after_sequence=0&limit=1" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200`：

```json
{
  "items": [
    {
      "id": "499c999d-cea7-463b-a194-4741a43043a5",
      "turn_id": "5c052f94-d4ef-4fcb-966b-4b5148cbd65a",
      "sequence": 1,
      "role": "user",
      "content": "我想拍一期一周做出个人知识库的视频。",
      "created_at": "2026-07-24T10:05:00Z"
    }
  ],
  "next_cursor": 1,
  "limit": 1
}
```

只有后面还有消息时，`next_cursor` 才会返回本页最后一条消息的序号；已经到末页
时为 `null`。继续分页时，把非空的 `next_cursor` 作为下一次请求的
`after_sequence`。若客户端还要轮询新消息，应自行保留当前最后一条消息的
`sequence`。

### POST /api/v1/conversations/{conversation_id}/messages

向 Agent 发送一条消息并等待本轮回答。`content` 长度为 1～20000 个字符。

```bash
curl --fail-with-body \
  --request POST "$API_BASE/conversations/$CONVERSATION_ID/messages" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "content": "我想拍一期一周做出个人知识库的视频，先帮我确定最值得讲的主线。"
  }'
```

成功返回 `201`：

```json
{
  "turn_id": "5c052f94-d4ef-4fcb-966b-4b5148cbd65a",
  "user_message": {
    "id": "499c999d-cea7-463b-a194-4741a43043a5",
    "turn_id": "5c052f94-d4ef-4fcb-966b-4b5148cbd65a",
    "sequence": 1,
    "role": "user",
    "content": "我想拍一期一周做出个人知识库的视频，先帮我确定最值得讲的主线。",
    "created_at": "2026-07-24T10:05:00Z"
  },
  "assistant_message": {
    "id": "a836c8f6-cfff-43d1-a9b2-a114ab7aa290",
    "turn_id": "5c052f94-d4ef-4fcb-966b-4b5148cbd65a",
    "sequence": 2,
    "role": "assistant",
    "content": "先抓住一个变化：这一周结束后，你的资料整理方式具体发生了什么改变？",
    "created_at": "2026-07-24T10:05:03Z"
  },
  "memory_updates": [],
  "memory_extraction_status": "completed"
}
```

`memory_updates` 列出本轮产生或更新的长期记忆；
`memory_extraction_status` 用于判断后台提取是否完成。Agent 可能在本轮调用项目、
灵感或用户资料工具，这些变更只会在工具执行成功后体现在结果中。

同一对话同一时刻只允许一个运行中的 Agent 请求：

- 已归档对话：`409 conversation_archived`
- 正在处理上一轮：`409 conversation_busy`
- 模型未配置：`503 agent_unavailable`
- 上游模型或工具链失败：`502 agent_run_failed`
- 加密上下文暂不可用：`503 context_storage_unavailable`

## 10. 语音转文字

STT 是异步接口。FastAPI 只负责鉴权、校验和创建任务，独立 Celery worker
通过 Hack Club AI 的 Replicate 代理调用固定版本的 incredibly-fast-whisper。
上游请求失败或 worker 被替换不会带崩 API 主进程。

默认限制：

- 单文件最大 64 MiB；
- 解码后最长 300 秒；
- prediction 默认最多等待 540 秒，必须短于 Celery soft limit；
- 成功结果包含全文和检测语言；兼容字段 `emotions`、`audio_events` 固定为空数组，
  不提供逐字时间戳、说话人识别或置信度。

部署 STT 依赖和 worker 的完整步骤见
[HANDOFF_STT.md](./HANDOFF_STT.md)。

### POST /api/v1/transcriptions

提交音频，使用 `multipart/form-data`。

| 表单字段 | 类型 | 必填 | 默认值 |
| --- | --- | --- | --- |
| `file` | binary | 是 | 无 |
| `language` | string | 否 | `auto`，还可用 `zh`、`yue`、`en`、`ja`、`ko` |
| `use_itn` | boolean | 否 | `true`，为接口兼容保留；Whisper 不提供对应参数 |

```bash
curl --fail-with-body \
  --request POST "$API_BASE/transcriptions" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --form 'file=@/absolute/path/to/sample.wav' \
  --form 'language=auto' \
  --form 'use_itn=true'
```

成功返回 `202`，并带有
`Location: /api/v1/transcriptions/{job_id}`：

```json
{
  "id": "8b2fc696-b5e9-48e5-b17c-982099c6e32b",
  "status": "queued",
  "language": "auto",
  "use_itn": true,
  "text": null,
  "detected_language": null,
  "emotions": null,
  "audio_events": null,
  "duration_seconds": null,
  "error": null,
  "attempt_count": 0,
  "started_at": null,
  "completed_at": null,
  "created_at": "2026-07-24T10:10:00Z",
  "updated_at": "2026-07-24T10:10:00Z"
}
```

文件过大返回 `413 audio_too_large`，类型不支持返回
`415 unsupported_audio_type`，服务未就绪返回 `503 stt_unavailable`。

### GET /api/v1/transcriptions/{job_id}

轮询任务。建议客户端在前几次使用 1～2 秒间隔，之后逐步增加，不要高频固定轮询。

```bash
curl --fail-with-body "$API_BASE/transcriptions/$JOB_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

`status` 的变化为 `queued` → `running` → `succeeded` 或 `failed`。成功示例：

```json
{
  "id": "8b2fc696-b5e9-48e5-b17c-982099c6e32b",
  "status": "succeeded",
  "language": "auto",
  "use_itn": true,
  "text": "今天我们来测试一下自动字幕。",
  "detected_language": "zh",
  "emotions": [],
  "audio_events": [],
  "duration_seconds": 4.82,
  "error": null,
  "attempt_count": 1,
  "started_at": "2026-07-24T10:10:01Z",
  "completed_at": "2026-07-24T10:10:06Z",
  "created_at": "2026-07-24T10:10:00Z",
  "updated_at": "2026-07-24T10:10:06Z"
}
```

当前 Whisper 模型不输出情绪或音频事件分类，因此新成功任务的两个兼容字段均为
空数组。旧的成功数据仍按其已加密保存的分析结果返回。

失败任务仍通过查询接口返回 `200`，但 `status` 为 `failed`：

```json
{
  "id": "8b2fc696-b5e9-48e5-b17c-982099c6e32b",
  "status": "failed",
  "language": "auto",
  "use_itn": true,
  "text": null,
  "detected_language": null,
  "emotions": null,
  "audio_events": null,
  "duration_seconds": null,
  "error": {
    "code": "audio_too_long",
    "message": "Audio exceeds the configured duration limit."
  },
  "attempt_count": 1,
  "started_at": "2026-07-24T10:10:01Z",
  "completed_at": "2026-07-24T10:10:02Z",
  "created_at": "2026-07-24T10:10:00Z",
  "updated_at": "2026-07-24T10:10:02Z"
}
```

终态错误可能包括 `invalid_audio`、`audio_too_long` 和
`stt_model_unavailable`。任务不存在或属于其他用户时返回
`404 transcription_not_found`。

## 11. 写接口幂等

除注册、登录和注销外，所有需要 Bearer 鉴权的 `POST`、`PUT`、`PATCH`、
`DELETE` 都强制要求：

```text
Idempotency-Key: <8～128 个 ASCII 字符>
```

客户端的正确做法是：

1. 用户发起一次新操作时生成新键。
2. 超时、断网或没有收到响应时，用原键、原方法、原 URL、原查询参数和原请求体重试。
3. 用户修改了内容或重新发起操作时生成新键。

同一用户、品牌作用域、路由和键在 24 小时内会重放第一次完成的状态码与响应，
并增加 `Idempotency-Replayed: true`。同键改了载荷返回
`409 idempotency_key_conflict`；第一次请求仍在执行时返回
`409 idempotency_request_in_progress`；缺少键返回
`400 idempotency_key_required`。运行记录超过 Agent 锁超时仍没有结果时返回
`409 idempotency_outcome_unknown`，客户端应保留本地操作记录并改用新键重试。
服务端只保存键摘要，缓存响应经过加密。

```bash
curl --fail-with-body \
  --request PATCH "$API_BASE/users/me" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{"avatar_url":null}'
```

上传音频时，服务端使用普通表单字段和文件字节摘要计算请求指纹，不会把音频副本
写进幂等表。

## 12. 品牌组织与成员

品牌是独立组织，同一用户可以同时是创作者和多个品牌的成员。品牌接口全部在路径
中明确携带 `brand_id`。角色只有 `owner` 和 `member`：两者都可以发现、关注
创作者并发送意向；只有 owner 可以修改品牌资料、邀请或管理成员。最后一名 owner
不能被降级或移除。

### POST /api/v1/brands

创建品牌，创建者自动成为 owner。

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request POST "$API_BASE/brands" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "name":"Inspire Studio",
    "description":"负责科技内容合作",
    "website_url":"https://brand.example.com",
    "logo_url":null
  }'
```

成功返回 `201`：

```json
{
  "id": "c7a39cea-62e5-4873-a551-7df9c3477d85",
  "name": "Inspire Studio",
  "description": "负责科技内容合作",
  "website_url": "https://brand.example.com/",
  "logo_url": null,
  "my_role": "owner",
  "created_at": "2026-07-24T10:00:00Z",
  "updated_at": "2026-07-24T10:00:00Z"
}
```

### GET /api/v1/brands

列出当前用户加入的品牌：

```bash
curl --fail-with-body "$API_BASE/brands?limit=50&offset=0" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

### GET、PATCH /api/v1/brands/{brand_id}

GET 读取品牌；PATCH 只有 owner 可以调用，可修改
`name`、`description`、`website_url`、`logo_url`。

```bash
curl --fail-with-body "$API_BASE/brands/$BRAND_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN"

export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request PATCH "$API_BASE/brands/$BRAND_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{"description":"新的品牌简介"}'
```

### 品牌邀请

owner 按现有用户昵称创建邀请：

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request POST "$API_BASE/brands/$BRAND_ID/invitations" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{"nickname":"brand_member"}'
```

受邀用户查看、接受或拒绝：

```bash
curl --fail-with-body "$API_BASE/users/me/brand-invitations" \
  --header "Authorization: Bearer $ACCESS_TOKEN"

export INVITATION_ID='<邀请 UUID>'
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request POST "$API_BASE/users/me/brand-invitations/$INVITATION_ID/accept" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

拒绝邀请：

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request POST "$API_BASE/users/me/brand-invitations/$INVITATION_ID/decline" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

owner 撤回待处理邀请：

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request DELETE "$API_BASE/brands/$BRAND_ID/invitations/$INVITATION_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

邀请状态为 `pending`、`accepted`、`declined` 或 `revoked`。

### 品牌成员

```bash
curl --fail-with-body "$API_BASE/brands/$BRAND_ID/members" \
  --header "Authorization: Bearer $ACCESS_TOKEN"

export MEMBER_USER_ID='<成员用户 UUID>'
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request PATCH "$API_BASE/brands/$BRAND_ID/members/$MEMBER_USER_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{"role":"owner"}'

export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request DELETE "$API_BASE/brands/$BRAND_ID/members/$MEMBER_USER_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

跨品牌或非成员访问统一返回 `404 brand_not_found`，不会泄露品牌是否存在；
已是成员但缺少 owner 权限返回 `403 brand_owner_required`。

## 13. 创作者公开橱窗

橱窗使用“草稿 + 已发布快照”。编辑草稿不会改变线上版本；调用 publish 后才会
生成新快照。withdraw 只撤回线上入口，不删除草稿、联系方式、授权或历史互动。

字段可见性：

| 值 | 可读取者 |
| --- | --- |
| `private` | 仅创作者本人 |
| `workshop_public` | 所有人 |
| `brands_only` | 任意品牌组织成员 |
| `authorized_brands` | 创作者明确授权的品牌成员 |

联系方式只允许 `private` 或 `authorized_brands`。服务端在每次读取时检查当前品牌
成员关系和有效授权；未授权响应不会包含联系方式原值或密文。

### GET、PATCH /api/v1/users/me/workshop

GET 返回当前草稿、可见性、社交账号、联系方式和精选项目。首次读取尚未保存的
橱窗时会返回由昵称和头像组成的默认草稿。

PATCH 使用平铺字段；值字段和对应的 `*_visibility` 可以独立更新：

```bash
curl --fail-with-body "$API_BASE/users/me/workshop" \
  --header "Authorization: Bearer $ACCESS_TOKEN"

export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request PATCH "$API_BASE/users/me/workshop" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "title":"AI 工具实测工作室",
    "title_visibility":"workshop_public",
    "bio":"专注真实工作流",
    "bio_visibility":"workshop_public",
    "creator_identity":"科技区 UP 主",
    "creator_identity_visibility":"brands_only",
    "content_focus":["AI","效率工具"],
    "content_focus_visibility":"brands_only",
    "collaboration_preferences":"接受深度测评",
    "collaboration_preferences_visibility":"authorized_brands"
  }'
```

资料字段包括 `nickname`、`avatar_url`、`title`、`bio`、
`creator_identity`、`content_focus`、`collaboration_preferences`，每项都有
独立可见性。

### GET /api/v1/users/me/workshop/preview

只有本人能预览草稿。`audience` 可取 `owner`、`public`、`brand`、
`authorized_brand`，只模拟投影，不修改真实授权。

```bash
curl --fail-with-body \
  "$API_BASE/users/me/workshop/preview?audience=brand" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

### 发布与撤回

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request POST "$API_BASE/users/me/workshop/publish" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"

export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request POST "$API_BASE/users/me/workshop/withdraw" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

### GET /api/v1/workshops/{creator_id}

匿名读取已发布橱窗：

```bash
curl --fail-with-body "$API_BASE/workshops/$CREATOR_ID"
```

品牌视角读取时必须同时提供 Bearer 和 `brand_id`：

```bash
curl --fail-with-body \
  "$API_BASE/workshops/$CREATOR_ID?brand_id=$BRAND_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

撤回、未发布或不存在统一返回 `404 workshop_not_published`。

## 14. 社交账号、联系方式和精选项目

### 社交账号

平台支持 `bilibili`、`douyin`、`xiaohongshu`、`weibo`、`zhihu`、
`youtube`、`other`，允许四种可见性。

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request POST "$API_BASE/users/me/workshop/social-accounts" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "platform":"bilibili",
    "handle":"InspireFlow",
    "profile_url":"https://space.bilibili.com/123",
    "visibility":"workshop_public",
    "sort_order":0
  }'
```

成功返回 `201`。修改和删除：

```bash
export SOCIAL_ACCOUNT_ID='<社交账号 UUID>'
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request PATCH "$API_BASE/users/me/workshop/social-accounts/$SOCIAL_ACCOUNT_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{"sort_order":1}'

export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request DELETE "$API_BASE/users/me/workshop/social-accounts/$SOCIAL_ACCOUNT_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

### 联系方式

类型支持 `email`、`phone`、`wechat`、`qq`、`telegram`、`other`。原值加密
存储；email、phone 和 Telegram 会返回服务端生成的 `action_uri`。

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request POST "$API_BASE/users/me/workshop/contacts" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "type":"email",
    "label":"商务邮箱",
    "value":"business@example.com",
    "visibility":"authorized_brands",
    "sort_order":0
  }'
```

修改、删除：

```bash
export CONTACT_ID='<联系方式 UUID>'
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request PATCH "$API_BASE/users/me/workshop/contacts/$CONTACT_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{"label":"合作邮箱"}'

export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request DELETE "$API_BASE/users/me/workshop/contacts/$CONTACT_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

无权限的公开响应会直接省略该联系方式，而不是返回密文或可推断的掩码。

### 精选项目

只能选择当前用户自己的项目：

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request PUT "$API_BASE/users/me/workshop/projects/$PROJECT_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{"visibility":"workshop_public","sort_order":0}'

export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request DELETE "$API_BASE/users/me/workshop/projects/$PROJECT_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

发布时会复制项目标题、类型、受众、简介和图标；内部项目后来发生变化，不会改动
已发布卡片。

## 15. 品牌授权与发现

授权独立于关注和合作意向。接受意向不会自动开放联系方式。

```bash
curl --fail-with-body "$API_BASE/users/me/workshop/brand-authorizations" \
  --header "Authorization: Bearer $ACCESS_TOKEN"

export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request PUT "$API_BASE/users/me/workshop/brand-authorizations/$BRAND_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"

export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request DELETE "$API_BASE/users/me/workshop/brand-authorizations/$BRAND_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

首版授权以“创作者 × 品牌组织”为粒度，对该品牌所有成员生效。

### GET /api/v1/brands/{brand_id}/creator-discovery

```bash
curl --fail-with-body \
  "$API_BASE/brands/$BRAND_ID/creator-discovery?query=AI&content_focus=效率工具&sort_by=updated_at&sort_order=desc&limit=20&offset=0" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

查询参数：

| 参数 | 说明 |
| --- | --- |
| `query` | 对当前品牌可见的已发布文字字段做关键词匹配 |
| `content_focus` | 内容方向 |
| `creator_identity` | 创作者身份 |
| `project_type` | 可见精选项目类型 |
| `followed` | `true` 只看已关注，`false` 排除已关注 |
| `sort_by` | `published_at` 或 `updated_at` |
| `sort_order` | `asc` 或 `desc` |
| `limit`、`offset` | 稳定分页 |

隐藏字段不会参与搜索、筛选、排序、计数或返回，前端不能依靠“是否命中”推断私有
内容。

## 16. 品牌关注、合作意向和创作者收件箱

### 关注

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request PUT "$API_BASE/brands/$BRAND_ID/follows/$CREATOR_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"

curl --fail-with-body "$API_BASE/brands/$BRAND_ID/follows?limit=50&offset=0" \
  --header "Authorization: Bearer $ACCESS_TOKEN"

export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request DELETE "$API_BASE/brands/$BRAND_ID/follows/$CREATOR_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

关注关系是 `active/inactive` 软状态。取消后重新关注会复用同一关系，并把创作者
收件箱里的关注条目重新标为未读。

### 合作意向

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request POST "$API_BASE/brands/$BRAND_ID/interests" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data "{
    \"creator_id\":\"$CREATOR_ID\",
    \"message\":\"想合作一期 AI 工具视频\"
  }"

curl --fail-with-body "$API_BASE/brands/$BRAND_ID/interests?limit=50&offset=0" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

同一品牌和创作者同时最多一条 `pending` 意向。重复提交时返回现有待处理记录；
终态后可以新建。品牌撤回：

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request PATCH "$API_BASE/brands/$BRAND_ID/interests/$INTEREST_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{"status":"withdrawn"}'
```

创作者接受或拒绝：

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request PATCH "$API_BASE/users/me/brand-interests/$INTEREST_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{"status":"accepted"}'
```

状态为 `pending`、`accepted`、`declined`、`withdrawn`。

### 创作者收件箱

```bash
curl --fail-with-body "$API_BASE/users/me/brand-inbox?limit=50&offset=0" \
  --header "Authorization: Bearer $ACCESS_TOKEN"

export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request PATCH "$API_BASE/users/me/brand-inbox/$INBOX_ITEM_ID" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{"is_read":true}'
```

批量标记已读。空对象表示全部条目，也可以传 `item_ids`：

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request POST "$API_BASE/users/me/brand-inbox/mark-read" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{}'
```

## 17. Agent SSE 流式对话

原有 `POST /api/v1/conversations/{conversation_id}/messages` JSON 接口继续保留。
需要逐字展示时使用：

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --no-buffer --fail-with-body \
  --request POST "$API_BASE/conversations/$CONVERSATION_ID/messages/stream" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Accept: text/event-stream' \
  --header 'Content-Type: application/json' \
  --data '{"content":"把这个想法整理成视频开头"}'
```

事件格式：

```text
id: 1
event: turn.started
data: {"turn_id":"..."}

id: 2
event: response.delta
data: {"turn_id":"...","delta":"先从"}

event: tool.started
data: {"turn_id":"...","tool":"search_website"}

event: tool.completed
data: {"turn_id":"...","tool":"search_website","status":"completed"}

event: turn.completed
data: {"turn_id":"...","user_message":{...},"assistant_message":{...}}
```

可能事件为 `turn.started`、`response.delta`、`tool.started`、
`tool.completed`、`turn.completed`、`turn.failed`。工具事件只暴露安全工具名和
状态，不含参数、原始结果或内部异常。连接会定期发送 `: heartbeat` 注释。

客户端断线不会取消已经开始的 Agent 本轮；服务端继续写入完整消息、记忆和工具
副作用。使用原幂等键重试时，运行中返回
`409 idempotency_request_in_progress`；完成后只重放 `turn.started` 和
`turn.completed`，不会重放所有增量。流开始前的鉴权、校验和资源错误仍是普通
HTTP 错误；响应头发出后的失败以 `turn.failed` 结束。

## 18. 商业任务与链上存证（Injective）

商业任务把创作结算流程写到 Injective 链上做存证。链上只写商业事实摘要
（action、任务 id、制品 sha256、金额、币种），**绝不写标题、正文等隐私内容**。
所有写接口都需要登录并携带幂等键；未配置 `APP_INJECTIVE_PRIVATE_KEY` 时写接口
返回 `503 injective_unavailable`。

任务状态机按固定顺序推进，乱序返回 `409 sequence_conflict`：

```
created → escrow_funded（创建即托管）→ submission_recorded（可重复提交）
        → authorization_activated（授权）→ settlement_released（结算）
```

每一步都会先在同一事务里写入一条 `prepared` 链交易，再尝试广播。链交易状态为
`prepared → broadcast → confirmed / failed`。**未从网络查到确认前不会报
`confirmed`**；读取 proof 时会补发失败可重试的交易并刷新确认状态。

任务公开结构：

```json
{
  "id": "b1c2...",
  "project_id": "31baf982-bcca-478e-bf81-2852825813f8",
  "user_id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
  "title": "品牌联名短视频",
  "budget": { "amount": "100", "denom": "inj" },
  "deadline": "2026-08-01T10:00:00Z",
  "status": "escrow_funded",
  "splits": [
    { "party_id": "creator", "bps": 7000 },
    { "party_id": "platform", "bps": 3000 }
  ],
  "created_at": "2026-07-24T10:00:00Z",
  "updated_at": "2026-07-24T10:00:00Z"
}
```

字段约束：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `project_id` | string | 当前用户名下的项目 UUID |
| `title` | string | 1～200 |
| `budget.amount` | string | 正的十进制字符串，最多 18 位小数 |
| `budget.denom` | string | 1～16，例如 `inj` 或业务结算币种 |
| `deadline` | string | 带时区偏移的 ISO 时间 |
| `splits` | array | 1～16 项；`bps` 各 1～10000，总和必须恰好 `10000`；`party_id` 唯一 |

> `budget.denom` 只是记在链上 memo 和数据库里的结算币种标签，不影响链上 gas。
> 交易 gas 始终由钱包里的原生币（Injective 上为 INJ）支付。

### POST /api/v1/commercial-tasks

创建商业任务，成功后立即进入 `escrow_funded` 并写入首条链交易。

```bash
curl --fail-with-body \
  --request POST "$API_BASE/commercial-tasks" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "project_id": "31baf982-bcca-478e-bf81-2852825813f8",
    "title": "品牌联名短视频",
    "budget": { "amount": "100", "denom": "inj" },
    "deadline": "2026-08-01T10:00:00Z",
    "splits": [
      { "party_id": "creator", "bps": 7000 },
      { "party_id": "platform", "bps": 3000 }
    ]
  }'
```

成功返回 `201` 和任务结构（`status` 为 `escrow_funded`）。项目不属于当前用户时
返回 `404 project_not_found`；分账不满足约束时返回 `422 validation_error`。

### POST /api/v1/commercial-tasks/{task_id}/submissions

记录一次制品提交，只上链摘要。可对同一任务多次提交。

```bash
curl --fail-with-body \
  --request POST "$API_BASE/commercial-tasks/$TASK_ID/submissions" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "artifact_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "artifact_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "delivery_url": "https://example.com/artifacts/final.mp4"
  }'
```

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `artifact_id` | string | 制品 UUID |
| `artifact_sha256` | string | 64 位小写 hex 摘要 |
| `delivery_url` | string | HTTP(S) 地址，最长 2048 |

首次提交把任务推进到 `submission_recorded`。成功返回 `201`：

```json
{
  "id": "c3d4...",
  "task_id": "b1c2...",
  "artifact_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "artifact_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "delivery_url": "https://example.com/artifacts/final.mp4",
  "created_at": "2026-07-24T11:00:00Z"
}
```

### POST /api/v1/commercial-tasks/{task_id}/authorize

把任务从 `submission_recorded` 推进到 `authorization_activated`。

```bash
curl --fail-with-body \
  --request POST "$API_BASE/commercial-tasks/$TASK_ID/authorize" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

成功返回 `200` 和任务结构；状态不满足前置条件时返回 `409 sequence_conflict`。

### POST /api/v1/commercial-tasks/{task_id}/settle

把任务从 `authorization_activated` 推进到 `settlement_released`，写入结算链交易
（携带金额与币种）。

```bash
curl --fail-with-body \
  --request POST "$API_BASE/commercial-tasks/$TASK_ID/settle" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY"
```

成功返回 `200` 和任务结构；乱序返回 `409 sequence_conflict`。

### GET /api/v1/commercial-tasks/{task_id}/proof

返回任务当前状态、全部提交记录，以及按时间排序的链交易列表。读取时会补发失败
可重试的交易并向网络查询确认状态，因此可能把 `broadcast` 刷新为 `confirmed`。
此接口不需要幂等键。

```bash
curl --fail-with-body "$API_BASE/commercial-tasks/$TASK_ID/proof" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功返回 `200`：

```json
{
  "task": { "id": "b1c2...", "status": "settlement_released", "...": "（同任务结构）" },
  "submissions": [ { "id": "c3d4...", "...": "（同提交结构）" } ],
  "transactions": [
    {
      "id": "d5e6...",
      "action": "escrow_funded",
      "status": "confirmed",
      "network": "testnet",
      "chain_id": "injective-888",
      "transaction_hash": "0xabc...",
      "explorer_url": "https://testnet.blockscout.injective.network/tx/0xabc...",
      "artifact_sha256": null,
      "amount": null,
      "denom": null,
      "failure_reason": null,
      "retryable": null,
      "submitted_at": "2026-07-24T10:00:01Z",
      "confirmed_at": "2026-07-24T10:00:05Z",
      "created_at": "2026-07-24T10:00:00Z"
    }
  ]
}
```

链交易字段：`action` 与任务动作对应；`status` 为 `prepared|broadcast|confirmed|failed`；
`chain_id` 是链原生 id（testnet `injective-888`、mainnet `injective-1`）；失败时
`failure_reason` 给出原因、`retryable` 标记是否可重试，`transaction_hash` 保留原始哈希
供排查。前端在 `status` 变为 `confirmed` 前不应对用户声称已上链完成。

## 19. 新增错误码

| HTTP | `error.code` | 说明 |
| --- | --- | --- |
| 400 | `idempotency_key_required` | 已鉴权业务写请求缺少幂等键 |
| 403 | `brand_owner_required` | 当前成员不是品牌 owner |
| 403 | `workshop_visibility_forbidden` | 当前读取者不满足字段可见性条件 |
| 404 | `brand_not_found` | 品牌不存在或当前用户不是成员 |
| 404 | `brand_invitation_not_found` | 邀请不存在或不属于当前用户/品牌 |
| 404 | `workshop_not_published` | 橱窗未发布、已撤回或不存在 |
| 404 | `workshop_item_not_found` | 社交账号、联系方式或精选项不存在 |
| 404 | `brand_interest_not_found` | 合作意向不存在或不属于当前主体 |
| 404 | `creator_inbox_item_not_found` | 收件箱条目不存在或不属于当前创作者 |
| 409 | `brand_last_owner_required` | 操作会移除最后一名 owner |
| 409 | `brand_invitation_state_conflict` | 邀请已经离开 pending |
| 409 | `brand_interest_state_conflict` | 意向已经离开 pending |
| 409 | `idempotency_key_conflict` | 同一幂等键被用于不同请求 |
| 409 | `idempotency_request_in_progress` | 同一幂等请求仍在运行 |
| 409 | `idempotency_outcome_unknown` | 上一次执行异常中断，结果无法安全重放；改用新键重试 |
| 422 | `invalid_workshop_contact` | 联系方式格式不合法 |
| 404 | `commercial_task_not_found` | 商业任务不存在，或不属于当前用户 |
| 409 | `sequence_conflict` | 商业任务动作乱序（不满足状态机前置条件） |
| 503 | `injective_unavailable` | 未配置私钥或链集成不可用 |

## 20. 常见错误码

| HTTP | `error.code` | 处理建议 |
| --- | --- | --- |
| 401 | `invalid_credentials` | 昵称或密码错误；不要提示账号是否存在 |
| 401 | `invalid_session` | 清除本地凭据并重新登录 |
| 404 | `project_not_found` | 项目不存在，或不属于当前用户 |
| 404 | `inspiration_not_found` | 灵感不存在，或不属于当前用户 |
| 404 | `conversation_not_found` | 对话不存在，或不属于当前用户 |
| 404 | `memory_not_found` | 记忆不存在，或不属于当前用户 |
| 404 | `transcription_not_found` | 转写任务不存在，或不属于当前用户 |
| 409 | `nickname_conflict` | 请用户更换昵称 |
| 409 | `conversation_archived` | 先取消归档，再发送消息 |
| 409 | `conversation_busy` | 等待上一轮完成后重试 |
| 409 | `inspiration_association_required` | 保留来源/项目关联，或先改为 `inbox` |
| 409 | `orphaned_inspirations_confirmation_required` | 展示受影响灵感，用户确认后带删除参数重试 |
| 413 | `audio_too_large` | 压缩或裁剪音频 |
| 415 | `unsupported_audio_type` | 转为后端支持的音频格式 |
| 422 | `validation_error` | 按 `details` 标记字段 |
| 422 | `credential_memory_forbidden` | 不要把密码、令牌或私钥写入长期记忆 |
| 502 | `agent_run_failed` | 保留用户输入，允许稍后重试 |
| 503 | `agent_unavailable` | 检查 `MODEL_*` 配置和模型服务 |
| 503 | `context_storage_unavailable` | 检查上下文加密密钥和存储状态 |
| 503 | `stt_unavailable` | 检查 STT 开关、Redis 和 worker 就绪状态 |

`401 invalid_session` 还会返回 `WWW-Authenticate: Bearer`。未知 HTTP 错误使用
`http_error`，客户端可以按状态码给出通用提示，同时记录完整响应供排查。

## 21. Agent 内部工具

下面这些是 Agent 运行时的 function tools，不是公开 HTTP API，因此没有对应的
`curl` 地址。前端需要项目、灵感或用户资料功能时，应调用前文的 REST 接口；
只有与 Agent 对话时，才由模型根据用户意图选择内部工具。

当前工具包括：

| 工具能力 | 用途 |
| --- | --- |
| 当前日期和时间 | 获取指定时区的日期时间 |
| 全网搜索 | 默认通过 DuckDuckGo 做免密钥搜索 |
| 网页抓取 | 读取公开 HTTP(S) 页面并提取正文 |
| 项目创建、查询、列表、修改、删除 | 在当前用户范围内维护项目 |
| 灵感创建、查询、列表、修改、删除 | 在当前用户范围内维护灵感 |
| 灵感与项目的添加、移除关联 | 管理多项目引用 |
| 修改用户资料 | 修改公开昵称或头像；需要用户明确表达 |
| 更新用户画像 | 更新 `users.profile_text`；仅供 Agent 内部理解用户 |

创建项目、删除项目、删除灵感以及可能造成内容损失的关联调整，都应由 Agent
先说明影响并取得用户确认。工具不能绕过用户隔离，也不能声称已经保存、发布、
付款或授权；只有实际工具结果成功后，才能向用户确认操作完成。

## 22. 推荐接入顺序

一个最小可用客户端可以按这个顺序接入：

1. 调用健康检查，确认数据库可用。
2. 完成注册、登录，并安全保存 `access_token`。
3. 读取当前用户和创作者资料。
4. 接入项目、灵感的列表与编辑。
5. 用对话 UUID 作为 Agent `session_id`，接入消息发送和增量拉取。
6. 最后接入长期记忆管理、删除影响确认和异步 STT。
7. 需要链上存证时接入商业任务：先看健康检查的 `services.injective` 是否为 `ok`，
   再按创建 → 提交 → 授权 → 结算 的顺序推进，并用 proof 接口展示链交易确认状态。

联调时不要把真实模型密钥、登录凭据或用户隐私写入测试脚本和 Git。需要排查
具体字段时，以运行中服务的 `/openapi.json` 为最后依据。
