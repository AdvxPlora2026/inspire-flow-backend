# 品牌项目 AI 投顾接口接入说明

## 1. 接口

```text
POST /api/v1/brands/{brand_id}/advisory-reports
Authorization: Bearer <access_token>
Idempotency-Key: <8..128 ASCII characters>
Content-Type: application/json
```

品牌 owner 和 member 都可以调用。品牌不存在或当前用户不是成员时统一返回
`404 brand_not_found`。报告即时生成，不保存历史。相同用户、方法、品牌路径、请求
内容和幂等键会重放加密保存的首次响应。

## 2. 请求

```json
{
  "project_brief": "为新品冷萃规划一轮 B 站内容合作，目标受众是年轻职场人",
  "project_id": "可选的当前用户项目 UUID",
  "market": "中国大陆",
  "focus_topics": ["职场效率", "即饮咖啡"],
  "lookback_days": 7
}
```

- `project_brief` 必填，去除首尾和重复空白后长度为 1～6000。
- `project_id` 可选，只能引用当前用户自己的项目。项目标题、类型、受众和摘要仅作补充，
  与 `project_brief` 冲突时以后者为准。
- `market` 是自由文本，长度为 1～120，默认 `China mainland`。
- `focus_topics` 最多 5 个去重主题，每项最多 100 个字符。
- `lookback_days` 为 1～30，默认 7。

```bash
export IDEMPOTENCY_KEY="$(uuidgen)"
curl --fail-with-body \
  --request POST "$API_BASE/brands/$BRAND_ID/advisory-reports" \
  --header "Authorization: Bearer $ACCESS_TOKEN" \
  --header "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "project_brief":"为新品冷萃规划一轮 B 站内容合作",
    "market":"中国大陆",
    "focus_topics":["职场效率","即饮咖啡"],
    "lookback_days":7
  }'
```

## 3. 报告逻辑

接口返回简体中文报告，字段包括：

- `evidence_status`: `sufficient`、`limited` 或 `insufficient`。
- `brand`: 已校验成员权限后的品牌投影。
- `project_context`: 显式 brief 与可选的当前用户项目投影。
- `research_scope`: 市场、主题、时间窗口和实际执行的搜索词。
- `evidence[]`: 证据标题、URL、来源域名、摘要、项目关联、抓取时间、核验级别、
  发布时间和时效状态。
- `recommendations[]`: 优先级、行动窗口、动作、预期效果、证据 ID、观察事实、
  对项目的含义、为什么建议成立、风险、反方观点、假设和置信度。
- `caveats[]` 与 `next_research_steps[]`: 数据缺口和下一步研究动作。

应用代码会根据本次 Agent 的 `search_website` 和 `fetch_webpage` 输出重建证据账本。
模型草稿中的 URL 如果不在账本里，请求会返回 `502 agent_run_failed`，不会把该引用
交给客户端。

证据摘要来自搜索摘要或抓取正文的限长摘录，不采用模型自行编写的“事实”。同一规范化
URL 只保留第一个证据 ID，不能靠重复引用凑够三条证据。空白搜索摘要不算证据；抓取
正文为空时，沿用该 URL 已有的搜索摘要。

`sufficient` 必须同时满足：至少 3 条相关证据、至少 2 个来源域名、至少 1 条来源有
已核验且位于查询窗口内的发布时间。任何弱于该门槛的报告只能是 `limited` 或
`insufficient`，且不能保留 `high` 置信度。网页发布时间只读取
`article:published_time`、JSON-LD `datePublished` 或 `<time datetime>`；冲突、无时区
或无效值保持 `null`，不会从正文猜测。

## 4. 错误

| HTTP | `error.code` | 含义 |
| --- | --- | --- |
| 401 | `invalid_session` | Bearer 会话无效 |
| 404 | `brand_not_found` | 品牌不存在或当前用户不是成员 |
| 404 | `project_not_found` | 可选项目不存在或不属于当前用户 |
| 422 | `validation_error` | 请求字段不满足约束 |
| 502 | `agent_run_failed` | 模型、提供商、结构化输出或证据校验失败 |
| 503 | `agent_unavailable` | `MODEL_*` 配置不完整 |

公开搜索失败不一定返回 `502`。如果 Advisor 能返回空证据和后续研究动作，接口仍会
返回 `200`，此时 `evidence_status=insufficient`。

## 5. Agent 内部工具

会话 Agent 追加两个只读工具：

```text
list_brands(limit=50, offset=0)
analyze_brand_project(brand_id, project_brief, project_id=None,
                      market="China mainland", focus_topics=None,
                      lookback_days=7)
```

工具不接受 `user_id`，身份只来自受信任的 `AgentRunContext`。投顾工具与 HTTP 路由
调用同一个 service，因此权限、项目隔离、报告结构和错误语义一致。

## 6. 持久化与升级方向

MVP 不新增 `BrandProject`、`AdvisoryReport` 或报告历史表。项目上下文来自请求内 brief，
现有 `Project` 仍属于单个用户，不会被静默改成品牌资产。

后续版本计划：

1. 新增品牌拥有的 `BrandProject`，明确定义成员创建、编辑、归档和审计权限，并通过
   显式关联连接现有个人项目与商业任务。
2. 质量验证通过后新增版本化 `AdvisoryReport` 快照，保存请求、证据、生成版本、刷新
   链路、审计字段、保留期和删除规则。
3. 社交平台指标、授权趋势数据和定时监控必须映射到同一证据账本，不能绕过引用、
   时效和充分度校验。
