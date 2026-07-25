# Replicate Whisper STT 接入说明

InspireFlow 接收登录用户上传的音频，在 SQLite 中创建异步任务，并通过 Redis 只传递
任务 UUID。Celery prefork 子进程使用固定版本的
`vaibhavs10/incredibly-fast-whisper`，请求经 Hack Club AI Replicate 代理发送。
FastAPI 进程不直接访问模型服务。

## 运行流程

```text
FastAPI -> SQLite queued job -> Redis UUID -> Celery pool child
                                           -> 本地音频时长校验
                                           -> Hack Club 文件上传
                                           -> Replicate 创建任务并轮询
                                           -> 加密写入 SQLite
                                           -> 清理本地暂存文件
```

- 子进程崩溃或硬超时后，Celery 会创建新的子进程。
- Redis、worker 或 Replicate 不可用时，FastAPI 的其他接口仍可工作。
- Redis 中不保存音频、转写文本、凭据、文件名或本地路径。
- 任务成功或失败后都会删除本地原始音频。
- 转写文本和带版本的分析结果在 SQLite 中加密保存。

## 准备环境

需要：

- Python 3.13 和 uv
- 本地 Redis，或 worker 能访问的远程 Redis
- 可以调用 Replicate 的 Hack Club AI key
- `ffprobe`。SoundFile 无法解析音频容器时用它读取时长，通常随 ffmpeg 安装

安装普通开发环境即可，不再需要单独的本地模型依赖组：

```bash
uv sync --locked --dev
```

## 配置

把下面的值写入已忽略的 `.env`，生产环境则放进密钥管理系统：

```dotenv
APP_STT_ENABLED=true
APP_STT_BROKER_URL=redis://127.0.0.1:6379/0
APP_STT_API_KEY=replace-with-hack-club-ai-key
APP_STT_BASE_URL=https://ai.hackclub.com/proxy/v1/replicate
APP_STT_MODEL=vaibhavs10/incredibly-fast-whisper:3ab86df6c8f54c11309d4d1f930ac292bad43ace52d10c80d87eb258b3c9f79c
```

不要提交 `APP_STT_API_KEY`。API 与 worker 必须使用同一套数据库、上下文加密密钥、
Redis broker 和暂存目录。

请求时间相关配置：

- `APP_STT_REQUEST_TIMEOUT_SECONDS=70`：单次 HTTP 请求超时。
- `APP_STT_PREDICTION_TIMEOUT_SECONDS=540`：一次模型任务的总时限。
- `APP_STT_POLL_INTERVAL_SECONDS=1`：初次同步等待结束后的轮询间隔。
- Celery 软、硬时限分别是 600 和 660 秒。模型任务时限必须小于软时限，worker 才有
  时间写入失败状态并清理文件。

默认上传上限是 64 MiB，解码后的音频最长 300 秒。

## 启动服务

先升级数据库并启动 FastAPI：

```bash
uv run alembic upgrade head
uv run uvicorn inspire_flow_backend.main:app --reload
```

再启动 STT 专用 worker：

```bash
uv run celery -A inspire_flow_backend.workers.celery_app:celery_app worker \
  --queues stt \
  --pool prefork \
  --concurrency 1 \
  --loglevel INFO
```

默认并发数是 1，用来限制供应商请求量，也让队列耗时更容易判断。worker 建立连接后
会排入 `stt.warmup`。预热只创建供应商客户端，不会提交付费预测。

## 就绪检查

运行：

```bash
uv run python -m inspire_flow_backend.workers.stt_doctor
```

doctor 会检查 Redis、Celery worker 存活状态，以及 prefork 子进程创建 Replicate 客户端
后写入的短期心跳。结果为 `ready` 只说明本地链路配置正确，不能保证下一次远程预测一定
成功。

## 供应商调用

worker 领取任务后按以下顺序执行：

1. 先在本地读取音频时长，不合格的文件不会上传。
2. 把暂存音频上传到 `{APP_STT_BASE_URL}/files`。
3. 使用固定模型版本请求 `{APP_STT_BASE_URL}/predictions`，并发送 `Prefer: wait=60`。
4. 初次响应仍为 `starting` 或 `processing` 时，轮询
   `{APP_STT_BASE_URL}/predictions/{id}`。供应商返回的绝对轮询 URL 不会被采用，避免
   绕过 Hack Club 代理。
5. 达到任务时限后取消预测，并尽力删除远程临时文件。
6. 规范化结果，加密写入数据库，最后删除本地暂存文件。

语言映射：`auto -> None`、`zh -> chinese`、`yue -> cantonese`、`en -> english`、
`ja -> japanese`、`ko -> korean`。`use_itn` 仍保留在公共 API 和任务记录中，用于兼容
旧客户端，但不会传给 Whisper。

## REST 接口

接口保持不变：

```text
POST /api/v1/transcriptions
GET  /api/v1/transcriptions/{job_id}
```

上传需要 Bearer Token 和 `Idempotency-Key`。同一文件重试时复用原键；multipart 的
随机 boundary 不参与请求摘要，文件内容 SHA-256 会参与。

新任务成功后的结果示例：

```json
{
  "status": "succeeded",
  "text": "今天我们来测试一下自动字幕。",
  "detected_language": "zh",
  "emotions": [],
  "audio_events": [],
  "duration_seconds": 4.82
}
```

Whisper 不提供 SenseVoice 原有的情绪和声音事件标签，因此新任务的 `emotions` 和
`audio_events` 是空数组。任务尚未成功时，这两个字段为 `null`；旧成功记录如果没有
加密分析结果，也会返回 `null`。

接口不会返回供应商时间戳、说话人分离、置信度、prediction ID、远程文件 ID 或上游
错误正文。

## 失败与恢复

本地解码失败对应 `invalid_audio`，音频超时长对应 `audio_too_long`。凭据缺失、认证
失败、限流、网络错误、供应商超时、预测取消或失败，以及响应结构错误，统一记为
`stt_model_unavailable`，不会把上游错误详情返回给客户端。

Celery 继续使用延迟确认、worker 丢失拒绝、prefetch 1 和有限重试。已经完成的任务
不会重复执行；所有终态路径都会删除本地暂存音频。
