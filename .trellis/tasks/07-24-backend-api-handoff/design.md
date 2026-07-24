# 完整后端 API 接入文档：结构设计

## 文档结构

`docs/HANDOFF.md` 按调用顺序编排，而不是照源码目录机械罗列：

1. 启动、基础地址和通用请求头
2. 快速跑通：健康检查、注册、登录、保存 Token
3. 通用响应格式、分页和错误信封
4. 用户与结构化资料
5. 长期记忆
6. 项目及 Agent 草稿
7. 灵感与项目关联
8. Agent 对话和消息
9. STT 提交、轮询和结果
10. 内部 Agent 工具与公共 HTTP API 的边界
11. 完整路由核对表

## 单个接口的写法

每个接口至少包含：

- `METHOD /path`
- 是否鉴权
- 请求参数或 JSON/multipart 字段
- 成功状态码和响应重点
- 一段 `curl`
- 有业务分支时补充错误或重试方式

共用响应模型集中说明，避免在 36 个接口下重复整段 JSON。接口小节仍会标明返回的模型名称和关键字段。

## 示例约定

```bash
export BASE_URL="${BASE_URL:-http://127.0.0.1:8000/api/v1}"
export ACCESS_TOKEN='<登录返回的 access_token>'
export USER_ID='<用户 UUID>'
export PROJECT_ID='<项目 UUID>'
export INSPIRATION_ID='<灵感 UUID>'
export CONVERSATION_ID='<对话 UUID，也是 Agent session ID>'
export MEMORY_ID='<记忆 UUID>'
export TRANSCRIPTION_ID='<转写任务 UUID>'
```

示例密码使用明显的占位值，不使用仓库 `.env` 或历史对话里的真实凭据。

## 覆盖校验

从 `create_app().openapi()` 读取 method/path 集合，再从 `docs/HANDOFF.md` 提取接口标题。两边集合必须一致。额外检查：

- 每个接口小节存在 `curl`
- 文档没有长格式 Token、`sk-` 密钥或 `.env` 真实值
- 枚举值与 schema 一致
- Markdown 代码围栏成对

## 文字风格

技术说明直接说调用方式和限制。减少“此外”“至关重要”一类填充词，不用宣传语，不在段末追加空泛总结。需要提醒风险时写具体后果，例如“删除接口返回 204，没有 JSON body”。
