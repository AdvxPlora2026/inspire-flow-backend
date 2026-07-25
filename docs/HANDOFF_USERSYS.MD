# 用户系统接入说明

服务没有默认账号。先注册，再用同一昵称和密码登录。注册本身不会创建会话。

## 先跑起来

安装锁定版本的依赖：

```bash
uv sync --locked --dev
```

创建或升级 SQLite 数据库：

```bash
uv run alembic upgrade head
```

启动开发服务器：

```bash
uv run uvicorn inspire_flow_backend.main:app --reload
```

默认服务地址是 `http://127.0.0.1:8000`，Swagger 文档位于
`http://127.0.0.1:8000/docs`。

服务读取以下数据库和会话配置：

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `APP_DATABASE_URL` | `sqlite:///./inspire_flow.db` | SQLite 数据库地址 |
| `APP_SESSION_TTL_HOURS` | `24` | 登录会话有效小时数 |

本地配置可以写进 `.env`。不要提交这个文件。

## 准备示例变量

后面的命令共用这些变量。密码通过终端读取，不写进命令历史。

```bash
export BASE_URL="${BASE_URL:-http://127.0.0.1:8000/api/v1}"
export NICKNAME="${NICKNAME:-aria}"
printf 'Password: '
read -r -s PASSWORD
printf '\n'
export PASSWORD

json_from_env() {
  uv run python -c \
    'import json, os, sys; print(json.dumps({key.lower(): os.environ[key] for key in sys.argv[1:]}))' \
    "$@"
}
```

所有请求和响应都使用 JSON。时间字段是 UTC，用户 ID 是 UUID。

## 注册

```text
POST /api/v1/users
```

| 字段 | 类型 | 必填 | 约束 |
| --- | --- | --- | --- |
| `nickname` | string | 是 | 去掉首尾空白后，NFKC 规范化长度为 2 到 50 |
| `password` | string | 是 | 15 到 128 个字符 |
| `avatar_url` | string 或 null | 否 | HTTP 或 HTTPS 地址，最长 2048 个字符 |

昵称按 NFKC 规范化和大小写折叠后检查唯一性。因此，只有大小写或兼容字符
不同的昵称也会冲突。

```bash
curl --fail-with-body \
  --request POST "$BASE_URL/users" \
  --header 'Content-Type: application/json' \
  --data "$(json_from_env NICKNAME PASSWORD)"
```

注册成功返回 `201`：

```json
{
  "id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
  "nickname": "aria",
  "avatar_url": null,
  "created_at": "2026-07-23T10:00:00Z",
  "updated_at": "2026-07-23T10:00:00Z"
}
```

昵称已存在时返回 `409 nickname_conflict`。字段不合法时返回
`422 validation_error`。

## 登录并取得凭据

```text
POST /api/v1/sessions
```

```bash
LOGIN_RESPONSE="$(
  curl --fail-with-body \
    --request POST "$BASE_URL/sessions" \
    --header 'Content-Type: application/json' \
    --data "$(json_from_env NICKNAME PASSWORD)"
)"
printf '%s\n' "$LOGIN_RESPONSE"
```

登录成功返回 `201`：

```json
{
  "access_token": "<登录接口返回的随机字符串>",
  "token_type": "bearer",
  "expires_at": "2026-07-24T10:00:00Z",
  "user": {
    "id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
    "nickname": "aria",
    "avatar_url": null,
    "created_at": "2026-07-23T10:00:00Z",
    "updated_at": "2026-07-23T10:00:00Z"
  }
}
```

从响应中读取令牌：

```bash
ACCESS_TOKEN="$(
  printf '%s' "$LOGIN_RESPONSE" |
    uv run python -c 'import json, sys; print(json.load(sys.stdin)["access_token"])'
)"
unset PASSWORD
```

令牌默认有效 24 小时。服务端只保存令牌的 SHA-256 摘要，无法从数据库恢复
原始值。令牌丢失或过期后需要重新登录。

昵称不存在和密码错误都会返回同一个 `401 invalid_credentials`。客户端不要
根据登录错误推断账号是否存在。

## 携带凭据

需要登录的接口使用这个请求头：

```text
Authorization: Bearer <access_token>
```

Bearer 鉴权的写请求还需要 `Idempotency-Key`。同一次操作重试时复用原键；修改了
请求内容就生成新键。

用当前令牌读取自己的资料：

```bash
: "${ACCESS_TOKEN:?请先用登录响应中的 access_token 设置 ACCESS_TOKEN}"
curl --fail-with-body \
  "$BASE_URL/users/me" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

缺少令牌、格式错误、令牌过期或已经注销时，服务返回
`401 invalid_session`，并带有 `WWW-Authenticate: Bearer` 响应头。

## 读取和修改资料

读取当前用户：

```text
GET /api/v1/users/me
```

修改昵称或头像地址：

```text
PATCH /api/v1/users/me
```

```bash
curl --fail-with-body \
  --request PATCH "$BASE_URL/users/me" \
  --header 'Content-Type: application/json' \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $(uuidgen)" \
  --data '{"nickname":"aria-new","avatar_url":"https://cdn.example.com/aria.png"}'
```

清空头像时显式传入 `null`：

```bash
curl --fail-with-body \
  --request PATCH "$BASE_URL/users/me" \
  --header 'Content-Type: application/json' \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $(uuidgen)" \
  --data '{"avatar_url":null}'
```

请求体至少要包含 `nickname` 或 `avatar_url`。`nickname` 不能为 `null`，
`avatar_url: null` 表示清空头像。资料实际发生变化时，返回值中的
`updated_at` 会更新。

## 创作者资料

每个用户注册时都会同时创建一条创作者资料。它和昵称、头像分开维护：

```text
GET   /api/v1/users/me/profile
PATCH /api/v1/users/me/profile
```

可以保存简介、IANA 时区、首选语言、创作者身份、内容方向和协作偏好：

```bash
curl --fail-with-body \
  --request PATCH "$BASE_URL/users/me/profile" \
  --header 'Content-Type: application/json' \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $(uuidgen)" \
  --data '{
    "bio":"记录从灵感到成片的过程",
    "timezone":"Asia/Shanghai",
    "preferred_language":"zh-CN",
    "creator_identity":"科技区 UP 主",
    "content_focus":["AI","数码"],
    "collaboration_preferences":"先确认大纲，再进入脚本"
  }'
```

PATCH 至少要提供一个字段。可空字段传 `null` 表示清空。内容方向会去除空项和
重复项；没有实际变化时 `updated_at` 保持不变。

真实姓名、生日、联系方式不属于固定创作者资料。需要长期保存时，使用长期记忆
接口；敏感信息只有在用户明确要求后才能保存。参见
[Agent 对话与记忆接入说明](HANDOFF_AGENT_MEMORY.md)。

## 注销当前会话

```text
DELETE /api/v1/sessions/current
```

```bash
curl --fail-with-body \
  --request DELETE "$BASE_URL/sessions/current" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $(uuidgen)"
```

注销成功返回 `204`，响应体为空。这个操作只撤销当前令牌，同一用户的其他
会话仍然有效。再次使用已注销的令牌会收到 `401 invalid_session`。

客户端收到 `204` 后应删除本地保存的令牌：

```bash
unset ACCESS_TOKEN
```

## 错误对照

错误响应采用固定外层结构：

```json
{
  "error": {
    "code": "invalid_session",
    "message": "A valid bearer session is required"
  }
}
```

| HTTP 状态码 | `error.code` | 含义 |
| --- | --- | --- |
| `400` | `idempotency_key_required` | 注销缺少有效 `Idempotency-Key` |
| `401` | `invalid_credentials` | 登录昵称或密码不正确 |
| `401` | `invalid_session` | 会话缺失、格式错误、过期、未知或已注销 |
| `409` | `nickname_conflict` | 昵称规范化后已经存在 |
| `422` | `validation_error` | 请求字段或请求体不符合接口约束 |

`validation_error` 可能带有 `details` 数组，用于标出字段位置和错误类型。
响应不会回显提交的密码。

## 凭据保存边界

Bearer 令牌代表当前会话权限。不要把真实令牌放进源码、Git 提交、URL、
日志、问题单或聊天记录。浏览器客户端也不应把令牌放进可被页面脚本随意读取
的长期存储。

生产环境必须使用 HTTPS。登录限流放在网关或反向代理层；本服务没有内置限流，
也不提供刷新令牌接口。

登录会话和 Agent 对话互相独立。注销只撤销当前 Bearer 令牌，不会删除 Agent
对话、消息、长期记忆或创作者资料。重新登录后仍可以凭同一用户身份继续原对话。

## 接入检查

- 已运行 `uv run alembic upgrade head`。
- 已通过 `POST /api/v1/users` 注册账号。
- 已通过 `POST /api/v1/sessions` 取得 `access_token`。
- 需要登录的请求都携带 `Authorization: Bearer $ACCESS_TOKEN`。
- 注销请求还会携带新的 `Idempotency-Key`。
- 客户端已处理 `401`、`409` 和 `422`。
- 注销成功后，客户端会删除保存的令牌。
