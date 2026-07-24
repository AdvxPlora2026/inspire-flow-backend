# 完整后端 API 接入文档：实施计划

## Checklist

- [x] 从 OpenAPI 导出全部 method/path、参数、请求体和响应模型。
- [x] 对照 route、schema、测试与已有专题交接文档核实业务细节。
- [x] 创建 `docs/HANDOFF.md`，先写全局约定和公共格式。
- [x] 按模块补齐 36 个接口及对应 `curl` 示例。
- [x] 补充删除确认、Agent session、长期画像边界和 STT 异步轮询说明。
- [x] 运行路由覆盖脚本、代码围栏检查和敏感信息扫描。
- [x] 用 `humanizer-zh` 从头复核中文，删掉模板化和宣传式表达。
- [x] 检查 Git diff，确保只新增/更新本任务文档和任务记录，不覆盖现有未提交功能。

## Validation

```bash
uv run python <OpenAPI 与 HANDOFF.md 路由覆盖检查>
rg -n 'sk-[A-Za-z0-9_-]{16,}|Bearer [A-Za-z0-9._~+/-]{24,}' docs/HANDOFF.md
git diff --check
uv run ruff check .
uv run ruff format --check .
```

## Validation result

- OpenAPI 与文档均为 36 个 HTTP 操作，缺失和多余项都是 0。
- 36 个接口小节都包含 `curl`。
- 敏感信息扫描无结果。
- Markdown 的 67 个代码围栏完整配对。
- `uv run ruff check .` 通过。
- `uv run ruff format --check .` 通过，153 个文件无需改动。
- `git diff --check -- docs/HANDOFF.md` 通过。

## Risks

- OpenAPI 只描述传输结构，删除确认、用户隔离和异步状态等业务语义仍需从服务与测试核对。
- 当前工作区有尚未提交的灵感系统和用户画像改动；文档必须描述当前工作区实际 API，同时不能回退这些文件。
- 文档较长，最容易遗漏的是 `204` 无响应体、查询参数默认值和 nullable 字段。
