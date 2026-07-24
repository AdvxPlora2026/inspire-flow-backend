# Agent 用户资料画像与会话接口：实施计划

## Implementation Checklist

1. 阅读数据库、Schema、服务、Agent 工具和测试规范，确认当前 migration head。
2. 先补失败测试：
   - migration upgrade/downgrade 与旧用户兼容；
   - 文本画像更新、清空、无变化时间戳；
   - 两个 Agent 工具的 schema、成功、校验、昵称冲突、无上下文和用户隔离；
   - 动态上下文包含文本画像；
   - 现有消息接口的 Token + session ID 鉴权与上下文延续。
3. 新增迁移和 `User.profile_text` 模型字段。
4. 新增内部文本画像校验与更新服务，保留公开用户 REST schema 不变。
5. 实现 `update_current_user` 和 `update_user_profile_text` FunctionTool，并加入稳定注册顺序。
6. 更新 Agent 默认提示词，写明基础资料的显式授权规则和文本画像的自动归纳边界。
7. 将文本画像加入动态上下文。
8. 补充 API/OpenAPI 或交接文档，明确 `conversation_id` 是持久化 session ID。
9. 运行定向测试、Ruff、格式检查、迁移测试与完整测试套件。

## Validation Commands

```bash
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/data/test_migrations.py
uv run pytest tests/services/agent/test_tools.py tests/services/agent/test_context.py tests/services/test_users.py
uv run pytest tests/api/test_conversations.py tests/api/test_users.py
uv run pytest -W error
```

## Risky Files and Rollback Points

- `migrations/versions/*_add_user_profile_text.py`：必须正确链接当前 migration head。
- `src/inspire_flow_backend/schemas/users.py`：内部画像模型不得意外加入公开 `UserPublic` 或 `UserUpdate`。
- `src/inspire_flow_backend/services/agent/func/registry.py`：新增工具会改变测试中的固定工具顺序。
- `src/inspire_flow_backend/services/agent/context.py`：画像长度受总上下文预算约束，不能挤掉全部近期对话。
- 当前工作区已有未提交的灵感系统改动；实施时只增量修改重叠文件，不回退或覆盖现有改动。

## Pre-start Checks

- `prd.md`、`design.md` 和本文件已通过最终审阅。
- 用户已在最终规划摘要之后明确批准实施。
- 实施前使用 `trellis-before-dev` 加载各层规范。
