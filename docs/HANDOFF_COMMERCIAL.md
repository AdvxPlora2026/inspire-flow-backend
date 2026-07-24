# 商业任务与链上存证交接说明

商业任务接口统一位于 `/api/v1/commercial-tasks`，把创作结算流程写到 Injective
链上做存证。所有写操作都需要登录凭据，并且只会访问当前用户自己的任务；任务 ID
使用 UUID，对其他用户不可见。

链上只写商业事实摘要（action、任务 id、制品 sha256、金额、币种），**绝不写标题、
正文等隐私内容**。私钥只从环境变量读取，绝不落库或打日志。

## 1. 获取访问凭据

先登录并把响应中的 `access_token` 放入环境变量。下面只使用占位值，不要把真实密码
或令牌写进文档、代码或 Git：

```bash
export API_BASE_URL="http://127.0.0.1:8000/api/v1"
export ACCESS_TOKEN="<登录响应中的 access_token>"
```

后续写请求都带上鉴权头和幂等键（读接口不需要幂等键）：

```text
Authorization: Bearer $ACCESS_TOKEN
Idempotency-Key: <每个写请求生成一个新的唯一值>
```

注册、登录和注销的完整调用方式见 `docs/HANDOFF_USERSYS.MD`。

## 2. 前置条件

- 后端需配置 `APP_INJECTIVE_PRIVATE_KEY`（0x 开头 64 位 hex）。未配置时所有写接口
  返回 `503 injective_unavailable`。
- 可用性可通过健康检查确认：`GET /api/v1/health` 的 `services.injective` 为 `ok`
  时表示链功能已就绪。
- 广播交易的 gas 由钱包里的原生币（Injective 上为 INJ）支付；`budget.denom` 只是
  记录在链上 memo 和数据库里的结算币种标签，不参与 gas 计算。

## 3. 状态机

任务按固定顺序推进，任何乱序操作返回 `409 sequence_conflict`：

```
created → escrow_funded（创建即托管）→ submission_recorded（可重复提交）
        → authorization_activated（授权）→ settlement_released（结算）
```

每一步都会先在同一事务里写入一条 `prepared` 链交易，提交后再尝试广播。链交易状态：

```
prepared → broadcast → confirmed / failed
```

**未从网络查到确认前不会报 `confirmed`。** 读取 proof 时会补发失败可重试的交易并向
网络刷新确认状态，因此 proof 可能把 `broadcast` 更新为 `confirmed`。

## 4. 创建任务

```bash
curl -sS -X POST "$API_BASE_URL/commercial-tasks" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{
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

字段约束：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `project_id` | string | 当前用户名下的项目 UUID，否则 `404 project_not_found` |
| `title` | string | 1～200 |
| `budget.amount` | string | 正的十进制字符串，最多 18 位小数 |
| `budget.denom` | string | 1～16，例如 `inj` 或业务结算币种 |
| `deadline` | string | 带时区偏移的 ISO 时间 |
| `splits` | array | 1～16 项；`bps` 各 1～10000，总和必须恰好 `10000`；`party_id` 唯一 |

成功返回 `201` 和任务结构，`status` 为 `escrow_funded`。分账不满足约束时返回
`422 validation_error`。

## 5. 记录制品提交

只上链摘要，可对同一任务多次提交。首次提交把任务推进到 `submission_recorded`。

```bash
curl -sS -X POST "$API_BASE_URL/commercial-tasks/$TASK_ID/submissions" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{
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

成功返回 `201` 和提交结构。

## 6. 授权与结算

```bash
# submission_recorded → authorization_activated
curl -sS -X POST "$API_BASE_URL/commercial-tasks/$TASK_ID/authorize" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Idempotency-Key: $(uuidgen)"

# authorization_activated → settlement_released（写入携带金额与币种的结算交易）
curl -sS -X POST "$API_BASE_URL/commercial-tasks/$TASK_ID/settle" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Idempotency-Key: $(uuidgen)"
```

两者都返回 `200` 和任务结构；状态不满足前置条件时返回 `409 sequence_conflict`。

## 7. 读取存证 proof

```bash
curl -sS "$API_BASE_URL/commercial-tasks/$TASK_ID/proof" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

返回任务当前状态、全部提交记录，以及按时间排序的链交易列表：

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

链交易字段说明：

| 字段 | 说明 |
| --- | --- |
| `action` | 对应任务动作：`escrow_funded`、`submission_recorded`、`authorization_activated`、`settlement_released` |
| `status` | `prepared`、`broadcast`、`confirmed`、`failed` |
| `chain_id` | 链原生 id（testnet `injective-888`、mainnet `injective-1`） |
| `transaction_hash` / `explorer_url` | 广播后可用；失败时仍保留原始哈希供排查 |
| `failure_reason` / `retryable` | 失败时给出原因与是否可重试 |
| `submitted_at` / `confirmed_at` | 广播、确认时间 |

前端在链交易 `status` 变为 `confirmed` 前，不应对用户声称已上链完成。

## 8. 错误码

| HTTP | `error.code` | 处理建议 |
| --- | --- | --- |
| 404 | `commercial_task_not_found` | 任务不存在或不属于当前用户 |
| 404 | `project_not_found` | 创建时项目不存在或不属于当前用户 |
| 409 | `sequence_conflict` | 动作乱序；按状态机顺序重试 |
| 422 | `validation_error` | 按 `details` 修正字段（如分账总和、摘要格式） |
| 503 | `injective_unavailable` | 后端未配置私钥或链集成不可用 |

联调时不要把真实私钥、登录凭据或用户隐私写入测试脚本和 Git。需要排查具体字段时，
以运行中服务的 `/openapi.json` 为最后依据。
