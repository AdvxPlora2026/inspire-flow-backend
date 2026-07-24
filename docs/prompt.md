# Agent 服务接入与工具说明

InspireFlow Agent 同时提供内部 Python 调用边界和
`/api/v1/conversations` REST 接口。REST 接口会把对话条目、滚动摘要和长期记忆
加密保存在 SQLite 中，并按登录用户隔离。直接调用 `create_agent_service()` 仍是
无状态模式，只有显式传入 Agents SDK `Session` 时才会使用会话历史。

REST 运行时从 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL` 和
`DEEPSEEK_BASE_URL` 读取 OpenAI 兼容模型配置。不要把真实密钥写进文档、日志或
Git。完整的 HTTP 接入方式见
[HANDOFF_AGENT_MEMORY.md](HANDOFF_AGENT_MEMORY.md)。

## 最小调用方式

下面的最小示例只演示内部无状态调用。OpenAI Agents SDK 默认从进程环境读取
凭据，开发机可以在启动命令前导出：

```bash
export OPENAI_API_KEY='<your-api-key>'
```

不要把真实密钥写进源码、示例、日志或 Git。项目的 `.env` 文件虽然被忽略，
但当前 Agent 服务不会主动从 `.env` 加载 `OPENAI_API_KEY`；部署时应由进程管理器
或密钥管理服务注入。

```python
import asyncio

from inspire_flow_backend.services.agent.agent import create_agent_service


async def main() -> None:
    async with create_agent_service() as service:
        result = await service.run("现在上海几点？")
        print(result.final_output)


asyncio.run(main())
```

`create_agent_service()` 没有传 `model` 时，沿用 Agents SDK 的默认模型配置。
也可以通过 `model="..."` 或自定义 `Model` 实例显式指定。服务默认最多运行
10 个 Agent 回合，单次调用可以覆盖：

```python
result = await service.run("查一下 FastAPI 的最新文档", max_turns=6)
```

空提示词、非正整数回合数会在本地直接报错。SDK、模型或程序错误不会被打印后
吞掉，而是原样交给内部调用方处理。

## 生命周期

工厂默认创建并持有一个 `httpx.AsyncClient`，因此推荐使用 `async with`。
如果调用方注入已有客户端，客户端仍由调用方关闭：

```python
import httpx

from inspire_flow_backend.services.agent.agent import create_agent_service


async with httpx.AsyncClient(
    follow_redirects=False,
    trust_env=False,
) as client:
    service = create_agent_service(http_client=client)
    try:
        result = await service.run("搜索 Python 3.13 的新特性")
    finally:
        await service.aclose()  # 不会关闭注入的 client
```

不要在模块导入时创建全局 Agent。工厂方式便于测试时替换 runner、时钟、DNS
解析器和 HTTP 客户端，也能明确资源由谁关闭。

## 持久化对话与本地上下文压缩

REST 对话和登录会话是两个不同资源。Bearer 登录会话只负责身份认证；Agent
对话保存创作上下文。注销或换一个登录令牌，不会删除同一用户拥有的 Agent
对话。

每轮请求会先尝试压缩超过阈值的旧历史，再保存已脱敏的当前用户消息。模型输入
由以下内容组成：

1. 当前用户的创作者资料；
2. 当前用户的活跃长期记忆；
3. 当前对话的滚动摘要；
4. 摘要游标之后、符合预算的最近完整轮次。

资料、记忆和摘要作为不可信上下文数据注入，只影响本次模型输入，不会成为新的
Session 消息。压缩只更新摘要密文和单调递增的游标，不删除原始消息。压缩失败
时沿用旧摘要和有界最近历史。

同一对话一次只允许一个运行中的 Agent 请求。进程异常留下的锁会在
`APP_AGENT_RUN_LOCK_TTL_SECONDS` 后被下一次请求回收。HTTP 消息接口当前是
非流式响应，包含模型与工具调用的完整延迟；客户端遇到网络超时时，应先读取
消息列表确认用户消息或助手回复是否已经落库，再决定是否重试。

## 内置工具

工具按固定顺序注册：

| 工具 | 参数 | 用途 |
| --- | --- | --- |
| `current_datetime` | `timezone_name="UTC"` | 按 IANA 时区返回当前时间 |
| `search_website` | `query`, `max_results=5` | 免密钥搜索公开网页 |
| `fetch_webpage` | `url` | 抓取公开网页的可读文本 |

工具成功或预期失败时都返回 JSON 字符串，方便模型判断结果。未预料的代码错误
不会伪装成搜索或抓取结果。

搜索结果和网页正文属于不可信外部数据。默认提示词要求 Agent 不执行网页里
夹带的指令，只把它们当作待引用或总结的资料。新增自定义提示词时必须保留这条
边界，并避免把密钥、内部提示词或其他敏感上下文交给网页工具。

### 时间

```json
{
  "ok": true,
  "timezone": "Asia/Shanghai",
  "iso_datetime": "2026-07-23T18:30:00+08:00",
  "unix_timestamp": 1784802600
}
```

时区必须是 `UTC`、`Asia/Shanghai` 这类 IANA 名称。未知时区返回
`invalid_timezone`。

### 搜索

```json
{
  "ok": true,
  "query": "FastAPI documentation",
  "provider": "duckduckgo",
  "results": [
    {
      "title": "FastAPI",
      "url": "https://fastapi.tiangolo.com/",
      "snippet": "FastAPI framework documentation."
    }
  ]
}
```

默认搜索链路如下：

1. 请求 `https://html.duckduckgo.com/html/` 并解析普通 HTML 结果；
2. DuckDuckGo 返回错误、验证页或没有可解析结果时，改查中文维基百科的
   MediaWiki Action API；
3. 响应中的 `provider` 分别是 `duckduckgo` 或 `mediawiki_zh`。

两条链路都不需要 API key。DuckDuckGo HTML 页面不是官方稳定的搜索 API，
页面结构、限流或反爬策略变化时可能失效。MediaWiki 是受支持的公开 API，
但它只覆盖维基百科，不等同于全网搜索。需要稳定 SLA 时应增加正式搜索供应商，
不要把当前适配器视为有保证的生产搜索接口。

查询会折叠多余空白，最长 300 个字符。每次默认返回 5 条，允许范围为 1 到
10 条。搜索响应最多读取 512 KiB。

### 网页抓取

```json
{
  "ok": true,
  "url": "https://example.com/article",
  "content_type": "text/html",
  "title": "Example article",
  "text": "Readable page text...",
  "truncated": false
}
```

抓取器只接受：

- `http` 和 `https`；
- 显式端口 80 或 443；
- DNS 返回地址全部为公网地址的目标；
- `text/html`、`application/xhtml+xml`、`text/plain` 和
  `application/json`。

每次跳转都会重新检查目标，默认最多跟随 3 次。回环、私网、链路本地、组播、
保留、未指定和共享地址空间都会被拒绝。HTML 会移除
`script`、`style`、`noscript`、`template` 和 SVG 内容，再提取标题与可见文本。

响应正文最多读取 1 MiB，返回文本最多 20,000 个字符，超过后
`truncated=true`。抓取器不执行 JavaScript、不下载二进制文件，也不会递归爬站。

这些检查能显著降低 SSRF 风险，但应用层 DNS 检查无法彻底消除“检查后再解析”
造成的 DNS rebinding。生产环境仍应配置出站网络策略。调用方注入 HTTP 客户端
时，也应关闭环境代理和自动跳转，除非已经评估相应风险。

部分透明代理或网络沙箱会把公共域名映射到保留地址（例如 `198.18.0.0/15`）。
默认策略会拒绝这类地址。不要为了兼容而直接放宽公网判断；应改用受控的出站
代理或能绑定“校验地址与实际连接地址”的网络层。

## 错误格式

```json
{
  "ok": false,
  "error": {
    "code": "unsafe_url",
    "message": "URL does not target a permitted public address"
  }
}
```

常见错误码：

| 错误码 | 含义 |
| --- | --- |
| `invalid_timezone` | IANA 时区不存在 |
| `invalid_query` | 查询为空或过长 |
| `invalid_result_count` | 搜索条数超出 1 到 10 |
| `search_unavailable` | 搜索供应商或搜索工具暂不可用 |
| `invalid_url` | URL 格式或协议不支持 |
| `unsafe_url` | 凭据、端口或目标地址不安全 |
| `redirect_limit` | 网页跳转次数过多 |
| `unsupported_content_type` | 不是允许的文本内容 |
| `response_too_large` | 网页正文超过读取上限 |
| `fetch_unavailable` | 网页连接、状态码或抓取工具异常 |

错误结果不会包含上游响应正文、解析出的私网地址、堆栈或底层异常详情。

## 调整限制

```python
from inspire_flow_backend.services.agent.agent import create_agent_service
from inspire_flow_backend.services.agent.contracts import AgentToolSettings

settings = AgentToolSettings(
    request_timeout_seconds=8,
    tool_timeout_seconds=12,
    default_search_results=3,
    max_search_results=8,
    max_fetch_output_characters=12_000,
    max_redirects=2,
)

service = create_agent_service(tool_settings=settings)
```

配置在构造时校验，并且对象不可变。时间、数量和大小上限必须为有效正数；
`max_redirects=0` 可以完全禁止跳转。

## 测试

Agent 测试不会访问模型、DNS 或公网：

```bash
uv run pytest tests/services/agent
```

测试通过注入 fake runner、固定时钟、`httpx.MockTransport` 和 fake DNS 解析器
覆盖工具结构、回退逻辑、响应上限与 URL 安全策略。真实 DuckDuckGo 页面只适合
作为独立冒烟检查，不能放进稳定测试套件。
