# 用户系统接入说明

本文将介绍如何启动服务、注册用户、登录、携带访问凭据、修改用户资料以及注销当前会话。

## 启动服务

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

默认服务地址是 `http://127.0.0.1:8000`，接口文档位于
`http://127.0.0.1:8000/docs`。

## 调用约定

本文示例使用以下变量：

```bash
export BASE_URL="${BASE_URL:-http://127.0.0.1:8000/api/v1}"
export NICKNAME="${NICKNAME:-aria}"
read -r -s PASSWORD
export PASSWORD
```

JSON 请求使用 `Content-Type: application/json`。响应时间均为 UTC，用户
ID 为 UUID。

## 没有默认账号

服务不包含默认账号或预置密码。调用方需要先注册，再使用同一昵称和密码登录。
注册不会自动创建登录会话。

## 1. 注册

接口：

```text
POST /api/v1/users
```

请求字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `nickname` | string | 是 | 去掉首尾空白后，NFKC 规范化长度为 2 到 50 |
| `password` | string | 是 | 15 到 128 个字符 |
| `avatar_url` | string 或 null | 否 | HTTP 或 HTTPS 地址，最长 2048 个字符 |

请求示例：

```bash
curl --fail-with-body \
  --request POST "$BASE_URL/users" \
  --header 'Content-Type: application/json' \
  --data "{\"nickname\":\"$NICKNAME\",\"password\":\"$PASSWORD\"}"
```

成功状态码为 `201`：

```json
{
  "id": "9f979b61-77cc-4294-945d-dd0dc96bb2d3",
  "nickname": "aria",
  "avatar_url": null,
  "created_at": "2026-07-23T10:00:00Z",
  "updated_at": "2026-07-23T10:00:00Z"
}
```

昵称按 NFKC 规范化和大小写折叠后检查唯一性。已经存在的昵称返回
`409 nickname_conflict`。字段不合法时返回 `422 validation_error`。

## 2. 登录并保存凭据

接口：

```text
POST /api/v1/sessions
```

登录请求：

```bash
LOGIN_RESPONSE="$(
  curl --fail-with-body \
    --request POST "$BASE_URL/sessions" \
    --header 'Content-Type: application/json' \
    --data "{\"nickname\":\"$NICKNAME\",\"password\":\"$PASSWORD\"}"
)"
printf '%s\n' "$LOGIN_RESPONSE"
```

成功状态码为 `201`：

```json
{
  "access_token": "<登录成功后返回的随机字符串>",
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

可以使用项目内的 Python 环境读取令牌：

```bash
export ACCESS_TOKEN="$(
  printf '%s' "$LOGIN_RESPONSE" |
    uv run python -c 'import json, sys; print(json.load(sys.stdin)["access_token"])'
)"
```

令牌默认有效 24 小时。服务端仅保存令牌摘要，原始值无法从数据库恢复。令牌
丢失或过期后需要重新登录。

昵称不存在和密码错误都会返回相同的 `401 invalid_credentials`，客户端不要
根据错误信息判断账号是否存在。

## 3. 携带凭据

需要登录的接口使用以下请求头：

```text
Authorization: Bearer <access_token>
```

curl 示例使用前面的 `ACCESS_TOKEN`：

```bash
: "${ACCESS_TOKEN:?请先用登录响应中的 access_token 设置 ACCESS_TOKEN}"
curl --fail-with-body \
  "$BASE_URL/users/me" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

缺少令牌、格式错误、令牌过期或已注销时，服务返回
`401 invalid_session`，同时带有 `WWW-Authenticate: Bearer` 响应头。

## 4. 读取和修改资料

读取当前用户：

```text
GET /api/v1/users/me
```

```bash
curl --fail-with-body \
  "$BASE_URL/users/me" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
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
  --data '{"nickname":"aria-new","avatar_url":"https://cdn.example.com/aria.png"}'
```

清空头像：

```bash
curl --fail-with-body \
  --request PATCH "$BASE_URL/users/me" \
  --header 'Content-Type: application/json' \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --data '{"avatar_url":null}'
```

请求体至少要包含 `nickname` 或 `avatar_url`。`nickname` 不能是 `null`，
`avatar_url: null` 表示清空头像。资料发生变化时，返回值中的 `updated_at`
会更新。

## 5. 注销

接口：

```text
DELETE /api/v1/sessions/current
```

```bash
curl --fail-with-body \
  --request DELETE "$BASE_URL/sessions/current" \
  --header "Authorization: Bearer $ACCESS_TOKEN"
```

成功状态码为 `204`，响应体为空。注销只撤销本次请求携带的会话，同一用户的
其他会话仍然有效。再次使用已注销的令牌会收到 `401 invalid_session`。

## 错误对照

错误响应格式：

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
| `401` | `invalid_credentials` | 登录昵称或密码不正确 |
| `401` | `invalid_session` | 会话缺失、格式错误、过期、未知或已注销 |
| `409` | `nickname_conflict` | 昵称规范化后已经存在 |
| `422` | `validation_error` | 请求字段或请求体不符合接口约束 |

`validation_error` 可能包含 `details` 数组，用于指出字段位置和错误类型。响应
不会回显提交的密码。

## 凭据使用注意

Bearer 令牌代表当前会话权限。不要把令牌写进源码、Git 提交、URL 或日志，也
不要把真实令牌复制到问题单和聊天记录。生产环境必须使用 HTTPS，并在网关或
反向代理层配置登录限流。

本服务没有刷新令牌接口。令牌过期、丢失或注销后，调用方需要重新登录。

## 接入检查

- 已运行 `uv run alembic upgrade head`。
- 已通过 `POST /api/v1/users` 注册账号。
- 已通过 `POST /api/v1/sessions` 获取并保存 `access_token`。
- 需要登录的请求都携带 `Authorization: Bearer $ACCESS_TOKEN`。
- 已处理 `401`、`409` 和 `422`。
- 注销后会删除客户端保存的令牌。
