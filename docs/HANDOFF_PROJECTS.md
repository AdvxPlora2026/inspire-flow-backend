# 项目系统交接说明

项目接口统一位于 `/api/v1/projects`，所有操作都需要登录凭据，并且只会访问当前用户自己的项目。项目 ID 使用 UUID；同一个 UUID 对其他用户不可见。

## 1. 获取访问凭据

先登录并把响应中的 `access_token` 放入环境变量。下面只使用占位值，不要把真实密码或令牌写进文档、代码或 Git：

```bash
export API_BASE_URL="http://127.0.0.1:8000/api/v1"
export ACCESS_TOKEN="<登录响应中的 access_token>"
```

后续请求都带上：

```text
Authorization: Bearer $ACCESS_TOKEN
```

注册、登录和注销的完整调用方式见 `docs/HANDOFF_USERSYS.MD`。

## 2. 用描述生成可编辑草稿

```bash
curl -sS -X POST "$API_BASE_URL/projects/drafts" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description":"做一期在 Mac 上本地部署语音识别的实测视频"}'
```

响应包含可编辑的项目字段；没有图标时 `icon_url` 为 `null`：

```json
{
  "title": "Mac 本地语音识别实测",
  "type": "科技数码",
  "audience": "重视隐私和本地工作流的内容创作者",
  "summary": "实测本地语音识别的部署过程、速度与使用效果",
  "icon_url": null
}
```

这一步不会创建数据库记录，也不会返回 `id`、`user_id` 或时间。前端应让用户检查和修改草稿，再调用创建接口保存。草稿接口需要配置 `MODEL_API_KEY`、`MODEL_NAME` 和 `MODEL_BASE_URL`；模型暂时不可用不会影响手动创建、查询、修改或删除项目。

## 3. 手动创建或保存草稿

`type` 是经过首尾空白清理的自由文本，可以使用 B 站分区名称，也可以填写自定义类型。

```bash
curl -sS -X POST "$API_BASE_URL/projects" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Mac 本地语音识别实测",
    "type": "科技数码",
    "audience": "重视隐私和本地工作流的内容创作者",
    "summary": "实测本地语音识别的部署过程、速度与使用效果",
    "icon_url": "https://cdn.example.com/project-icons/mac-stt.png"
  }'
```

成功返回 `201`：

```json
{
  "title": "Mac 本地语音识别实测",
  "type": "科技数码",
  "audience": "重视隐私和本地工作流的内容创作者",
  "summary": "实测本地语音识别的部署过程、速度与使用效果",
  "icon_url": "https://cdn.example.com/project-icons/mac-stt.png",
  "id": "0ff9c615-f226-4275-b62f-270e8e8b2761",
  "user_id": "ecf2afce-af0d-4719-a3b3-f29c366be1ab",
  "created_at": "2026-07-24T12:00:00Z",
  "updated_at": "2026-07-24T12:00:00Z"
}
```

字段限制：标题 120 字符、类型 50 字符、受众 500 字符、简介 2000 字符。四个内容字段都必填，清理首尾空白后不能为空。`icon_url` 可选，只接受最长 2048 字符的 HTTP/HTTPS URL；省略时返回 `null`。

## 4. 查询项目

按最近更新时间倒序分页：

```bash
curl -sS "$API_BASE_URL/projects?limit=50&offset=0" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

响应格式：

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

查询单个项目：

```bash
export PROJECT_ID="<项目 UUID>"
curl -sS "$API_BASE_URL/projects/$PROJECT_ID" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

项目详情比创建、列表和修改响应多一个 `inspiration_count` 字段，用于表示当前关联灵感数量。完整灵感数据通过
`GET /api/v1/projects/{project_id}/inspirations` 分页获取，具体见
`docs/HANDOFF_INSPIRATIONS.md`。

## 5. 修改和删除

修改时只提交需要变化的字段。必填内容字段不能传 `null`；
`icon_url: null` 专门用于清空图标：

```bash
curl -sS -X PATCH "$API_BASE_URL/projects/$PROJECT_ID" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"summary":"补充 MPS、CPU 的速度和准确率对比"}'
```

```bash
curl -sS -X PATCH "$API_BASE_URL/projects/$PROJECT_ID" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"icon_url":null}'
```

没有孤立灵感影响时，删除成功返回空的 `204`：

```bash
curl -i -X DELETE "$API_BASE_URL/projects/$PROJECT_ID" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

如果删除会让某些灵感失去最后一个项目和来源，接口返回
`409 orphaned_inspirations_confirmation_required` 和受影响灵感列表。产品界面展示影响并取得确认后，使用：

```bash
curl -i -X DELETE \
  "$API_BASE_URL/projects/$PROJECT_ID?delete_orphan_inspirations=true" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

## 6. Agent 项目工具

对话 Agent 可使用以下工具，工具中的所有读写都自动绑定当前登录用户：

```text
create_project
list_projects
get_project
update_project
delete_project
```

模型看不到也不能提交 `user_id`。创建采用“草稿 → 用户确认 → 保存”两轮流程；`confirmed=false` 只返回草稿，不写数据库。删除也必须先用 `confirmed=false` 展示项目标题和 UUID，等用户在单独一轮明确确认后，才允许用 `confirmed=true` 删除。

`create_project` 可以接收 `icon_url`。`update_project` 可以传新的
`icon_url`，或用 `clear_icon=true` 清空图标。它会直接修改用户明确指定的字段。查询外部用户或不存在的 UUID 都只返回安全的 `project_not_found`，不会暴露项目是否真实存在。

`create_project` 还可以接收 `inspiration_ids`。预览会列出将关联的灵感，用户确认后，项目与这些关联在一个事务中创建。`delete_project` 的预览会列出 `orphaned_inspirations`；只有用户明确确认影响后，才能同时传
`confirmed=true` 和 `delete_orphan_inspirations=true`。

## 7. 错误约定

REST 错误统一使用：

```json
{
  "error": {
    "code": "project_not_found",
    "message": "Project was not found"
  }
}
```

常见状态：

| HTTP 状态 | `error.code` | 含义 |
| --- | --- | --- |
| `401` | `invalid_session` | 缺少、过期或无效的 Bearer 凭据 |
| `404` | `project_not_found` | 项目不存在，或不属于当前用户 |
| `409` | `orphaned_inspirations_confirmation_required` | 删除会产生孤立灵感，需要展示影响并重试确认 |
| `422` | `validation_error` | 请求字段缺失、为空、超限或包含未知字段 |
| `502` | `agent_run_failed` | 模型未能生成有效草稿 |
| `503` | `agent_unavailable` | 模型配置不完整 |

OpenAPI 调试页面默认位于 `http://127.0.0.1:8000/docs`。
