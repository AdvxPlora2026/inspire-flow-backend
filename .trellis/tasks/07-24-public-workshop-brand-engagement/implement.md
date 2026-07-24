# 创作者公开橱窗与品牌互动：实施计划

## 开发方式

严格使用 Red-Green-Refactor。每一阶段先写一个能说明公开行为的失败测试，确认失败
原因是功能尚不存在，再添加最小实现。迁移、API、service 和权限投影都不能先写
生产代码再补测试。

## Checklist

### 1. 基础枚举、模型和迁移

- [x] 为品牌组织、成员、邀请、橱窗、发布快照、社交账号、联系方式、精选项目、
  授权、关注、意向、收件箱、幂等记录和 Agent turn run 写模型测试。
- [x] 运行测试并确认因表或模型不存在而失败。
- [x] 添加 SQLAlchemy 模型和 Alembic revision，更新 model registry。
- [x] 覆盖 upgrade、downgrade、唯一约束、外键级联和 UTC 时间。

### 2. 通用幂等层

- [ ] 先写 idempotency executor 的失败测试：缺 Header、首次执行、完成重放、
  payload 冲突、并发 processing、24 小时过期、204 与敏感响应加密。
- [x] 实现请求指纹、key digest、记录仓库、加密响应和错误码。
- [ ] 把现有已鉴权写 service 的事务改为 executor 统一提交。
- [ ] 为 JSON、空 body、query/path 和 multipart 文件摘要分别测试指纹。
- [x] 增加 OpenAPI 契约测试，扫描全部已鉴权写 operation 是否声明
  `Idempotency-Key`；明确排除注册、登录、注销。

### 3. 品牌组织和成员

- [ ] 先写 API/service 失败测试：创建品牌、列表、owner/member 权限、邀请、
  接受/拒绝/撤销、转移 owner、最后 owner 保护和跨品牌 404。
- [x] 实现 brand schemas、repositories、services 和 routes。
- [x] 验证所有品牌路径显式使用 `brand_id`，成员关系不能由客户端伪造。

### 4. Workshop 草稿和字段投影

- [x] 先写四级可见性矩阵失败测试，覆盖 owner、匿名、普通用户、品牌成员和授权
  品牌。
- [x] 实现草稿资料、visibility schema 和统一投影器。
- [x] 实现四种 owner preview。
- [x] 测试无效可选 Bearer 返回 401，而不是降级匿名。

### 5. 社交账号、联系方式和精选项目

- [ ] 先写独立 CRUD、枚举、排序、URL 校验、联系方式规范化和密文测试。
- [x] 实现社交账号和联系方式草稿子资源。
- [x] 测试联系方式拒绝 `brands_only/workshop_public`，未授权响应没有明文或密文。
- [x] 先写项目所有权、选择、排序和卡片 visibility 失败测试，再实现精选项目选择。

### 6. 发布快照、更新和撤回

- [ ] 先写草稿修改不影响线上、项目修改不影响快照、再次发布原子切换、撤回不删
  草稿和旧修订的失败测试。
- [x] 实现 publication clone 和 current revision pointer。
- [ ] 测试发布失败时旧线上修订继续可用。

### 7. 品牌授权和发现

- [x] 先写授权/撤销的品牌级权限测试。
- [x] 实现授权 CRUD 和服务端联系方式解析。
- [x] 先写发现查询的字段侧信道测试：隐藏字段不能命中 query、filter 或 sort。
- [x] 实现 query、内容方向、身份、项目类型、followed、排序和稳定分页。

### 8. 关注、意向和创作者收件箱

- [x] 先写关注 PUT/DELETE、软状态、重复关注和重新未读测试。
- [ ] 先写意向合法状态转换、单 pending 约束和主体权限测试。
- [x] 实现统一 inbox 投影、单条已读和批量已读。
- [x] 验证接受意向不创建品牌授权。

### 9. Agent SSE

- [x] 为 runner streaming protocol 和 SSE encoder 写失败测试。
- [x] 实现 SDK `run_streamed()` 适配和安全事件映射。
- [ ] 先写断开后继续、完成重放、处理中冲突、失败终止、heartbeat、有界队列和
  工具事件脱敏测试。
- [x] 实现 app-scoped stream manager、后台独立 session/runtime 和 shutdown 清理。
- [x] 验证非流式接口行为保持一致，只新增强制幂等 Header。

### 10. 文档与完整验证

- [x] 更新 `docs/HANDOFF.md`、README、OpenAPI 示例和 `.trellis/spec`。
- [x] 为全部新 API 添加 curl 和 SSE 示例。
- [x] 运行迁移升降级验证。
- [x] 运行完整 pytest、Ruff、format、OpenAPI route/idempotency 覆盖和凭据扫描。
- [x] 检查 Git diff，只包含本任务改动，不提交 `.env`、SQLite 数据或上下文密钥。

## Validation

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
git diff --check
```

额外执行：

- OpenAPI 全部写路由 Idempotency-Key 覆盖脚本
- visibility 权限矩阵测试
- 未授权响应敏感字段扫描
- SSE 事件 schema 与断线续跑测试
- 并发幂等测试

## 风险和回滚点

- 幂等层会触及全部已有写接口。先独立完成 executor 和契约测试，再逐模块迁移，
  每迁移一组都运行原测试。
- SQLite 并发写锁与生产数据库行为不同。测试必须覆盖两个请求争用同一键，service
  不能在 executor 之外提交。
- SSE 后台任务不能复用请求依赖的 DB Session 或 runtime。
- 发布快照复制联系方式时必须重新加密或安全复制密文，不能经过日志。
- 发现查询必须在 SQL 层应用 visibility，不能先取全量再由 Pydantic 隐藏。
- 回滚 migration 会删除新品牌和橱窗数据；执行前必须备份。现有用户、项目、灵感
  和对话表不应被 downgrade 修改。
