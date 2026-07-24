# 灵感系统交接说明

灵感接口统一位于 `/api/v1/inspirations`。所有操作都需要 Bearer 凭据，只能访问当前用户自己的灵感和项目。灵感、项目、来源对话和来源消息都使用 UUID。

## 1. 准备访问凭据

```bash
export API_BASE_URL="http://127.0.0.1:8000/api/v1"
export ACCESS_TOKEN="<登录响应中的 access_token>"
export AUTH_HEADER="Authorization: Bearer $ACCESS_TOKEN"
```

注册、登录和注销见 `docs/HANDOFF_USERSYS.MD`。不要把真实密码、访问令牌或模型密钥写入代码、文档或 Git。

## 2. 创建灵感

标题可以省略，正文必填：

```bash
curl -sS -X POST "$API_BASE_URL/inspirations" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Mac 本地转写速度对比",
    "content": "对比 MPS、CPU 的速度、温度和耗电",
    "project_ids": []
  }'
```

成功返回 `201`：

```json
{
  "id": "8cbd0f46-dcf1-47db-9aad-a62908ac2bd2",
  "user_id": "ecf2afce-af0d-4719-a3b3-f29c366be1ab",
  "title": "Mac 本地转写速度对比",
  "content": "对比 MPS、CPU 的速度、温度和耗电",
  "status": "inbox",
  "source_type": "manual",
  "source_conversation_id": null,
  "source_message_id": null,
  "projects": [],
  "created_at": "2026-07-24T12:00:00Z",
  "updated_at": "2026-07-24T12:00:00Z"
}
```

公共接口支持的来源是：

- `manual`：手动创建，默认值。
- `voice`：由客户端根据语音转写结果创建。

`agent` 来源只能由可信 Agent 运行上下文写入，公共接口不能伪造来源对话或消息。

状态包括：

- `inbox`
- `developing`
- `converted`
- `archived`

未关联项目或来源的灵感必须保持 `inbox`。标题最长 120 字符，正文最长 20,000 字符；内容会清理首尾空白。

## 3. 创建时关联项目

一条灵感可以关联多个自有项目：

```bash
export FIRST_PROJECT_ID="<项目 UUID>"
export SECOND_PROJECT_ID="<项目 UUID>"

curl -sS -X POST "$API_BASE_URL/inspirations" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{
    \"content\":\"把本地转写拆成安装、速度和效果三期\",
    \"project_ids\":[\"$FIRST_PROJECT_ID\",\"$SECOND_PROJECT_ID\"]
  }"
```

`project_ids` 最多 100 个且不能重复。项目不存在或属于其他用户时返回 `404 project_not_found`，不会写入部分关联。

## 4. 查询、搜索和筛选

```bash
curl -sS -G "$API_BASE_URL/inspirations" \
  -H "$AUTH_HEADER" \
  --data-urlencode "project_id=$FIRST_PROJECT_ID" \
  --data-urlencode "status=developing" \
  --data-urlencode "source_type=manual" \
  --data-urlencode "query=本地转写" \
  --data-urlencode "sort_by=updated_at" \
  --data-urlencode "sort_order=desc" \
  --data-urlencode "limit=50" \
  --data-urlencode "offset=0"
```

响应为：

```json
{
  "items": [],
  "total": 0,
  "limit": 50,
  "offset": 0
}
```

支持按 `created_at` 或 `updated_at` 排序，默认按更新时间倒序。关键词会搜索标题和正文。

查询详情：

```bash
export INSPIRATION_ID="<灵感 UUID>"
curl -sS "$API_BASE_URL/inspirations/$INSPIRATION_ID" \
  -H "$AUTH_HEADER"
```

## 5. 修改内容与完整项目集合

`PATCH` 只修改提交的字段。传 `project_ids` 时会完整替换现有项目集合：

```bash
curl -sS -X PATCH "$API_BASE_URL/inspirations/$INSPIRATION_ID" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{
    \"status\":\"developing\",
    \"content\":\"加入温度、耗电和字幕准确率对比\",
    \"project_ids\":[\"$FIRST_PROJECT_ID\"]
  }"
```

`title: null` 可以清空标题。正文、状态和 `project_ids` 不能传 `null`，空补丁返回 `422 validation_error`。

## 6. 增量添加或移除项目

添加操作是幂等的：

```bash
curl -i -X PUT \
  "$API_BASE_URL/inspirations/$INSPIRATION_ID/projects/$SECOND_PROJECT_ID" \
  -H "$AUTH_HEADER"
```

移除操作也是幂等的：

```bash
curl -i -X DELETE \
  "$API_BASE_URL/inspirations/$INSPIRATION_ID/projects/$SECOND_PROJECT_ID" \
  -H "$AUTH_HEADER"
```

成功返回空的 `204`。如果操作会让非 `inbox` 灵感失去最后一个项目和来源，返回 `409 inspiration_association_required`；可以在同一次 `PATCH` 中先把状态改回 `inbox` 并清空 `project_ids`。

## 7. 从项目查看灵感

项目详情增加 `inspiration_count`：

```bash
curl -sS "$API_BASE_URL/projects/$FIRST_PROJECT_ID" \
  -H "$AUTH_HEADER"
```

完整灵感列表走独立分页接口：

```bash
curl -sS \
  "$API_BASE_URL/projects/$FIRST_PROJECT_ID/inspirations?limit=50&offset=0" \
  -H "$AUTH_HEADER"
```

该接口支持与灵感总列表相同的状态、来源、关键词和排序参数，但项目 ID 已由路径确定。

## 8. 删除与孤立数据确认

直接删除灵感：

```bash
curl -i -X DELETE "$API_BASE_URL/inspirations/$INSPIRATION_ID" \
  -H "$AUTH_HEADER"
```

成功返回空的 `204`，项目关联一并删除。

删除项目或来源对话时，如果某些灵感会失去最后一个项目和来源，首次请求不会执行删除，而是返回 `409`：

```json
{
  "error": {
    "code": "orphaned_inspirations_confirmation_required",
    "message": "Deleting this resource would orphan 1 inspiration(s)",
    "details": [
      {
        "id": "8cbd0f46-dcf1-47db-9aad-a62908ac2bd2",
        "title": "Mac 本地转写速度对比"
      }
    ]
  }
}
```

界面应展示 `details` 并询问用户。用户确认后重试：

```bash
curl -i -X DELETE \
  "$API_BASE_URL/projects/$FIRST_PROJECT_ID?delete_orphan_inspirations=true" \
  -H "$AUTH_HEADER"
```

删除对话使用同一个查询参数：

```bash
curl -i -X DELETE \
  "$API_BASE_URL/conversations/<对话 UUID>?delete_orphan_inspirations=true" \
  -H "$AUTH_HEADER"
```

确认后的目标资源、关联和孤立灵感会在一个数据库事务中删除。仍有其他项目或有效来源的灵感会保留。

## 9. Agent 工具

Agent 新增：

```text
create_inspiration
list_inspirations
get_inspiration
update_inspiration
delete_inspiration
add_inspiration_project
remove_inspiration_project
```

规则：

- 用户表达清晰、可识别的创作想法时，Agent 可以立即调用 `create_inspiration`，然后告知保存结果。
- 内容像一般讨论或表达含糊时，Agent 先询问是否保存。
- 耐久对话会自动注入当前对话和用户消息来源，模型看不到也不能填写 `user_id`、来源对话 ID 或来源消息 ID。
- `delete_inspiration` 先以 `confirmed=false` 返回标题和 UUID；用户在后续一轮确认后才能传 `confirmed=true`。
- 项目删除预览会返回 `orphaned_inspirations`。只有用户确认这些影响后，才能同时传 `confirmed=true` 和 `delete_orphan_inspirations=true`。
- `create_project` 支持 `inspiration_ids`，会在项目草稿确认后原子创建项目并建立关联。

## 10. 错误与存储边界

常见错误：

| HTTP 状态 | `error.code` | 含义 |
| --- | --- | --- |
| `401` | `invalid_session` | Bearer 凭据缺失、过期或无效 |
| `404` | `inspiration_not_found` | 灵感不存在或不属于当前用户 |
| `404` | `project_not_found` | 关联项目不存在或不属于当前用户 |
| `409` | `inspiration_association_required` | 非收件箱灵感缺少项目或来源 |
| `409` | `orphaned_inspirations_confirmation_required` | 删除前需要确认孤立灵感清理 |
| `422` | `validation_error` | 字段、枚举、长度或请求结构无效 |

灵感标题和正文以明文保存在 SQLite 中，以支持中文关键词搜索和数据库分页。HTTP 接口有鉴权和用户隔离，但拥有 SQLite 文件或备份读取权限的人可以直接看到这些内容；数据库文件和备份必须按创作资产管理。

OpenAPI 调试页面默认位于 `http://127.0.0.1:8000/docs`。
