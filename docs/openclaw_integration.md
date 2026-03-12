# OpenClaw 局域网接入

## 目标

把视频转写服务部署在局域网内的一台机器上，再让 OpenClaw 通过本地技能跨机器调用。

## 架构

1. `192.168.50.201` 运行视频下载和转写服务。
2. `192.168.50.160` 安装 OpenClaw 技能。
3. OpenClaw 在调研时遇到支持的平台链接，需要转写时调用技能。
4. 技能通过 HTTP 请求 `192.168.50.201`，拿回完整转写稿。

## 服务端接口

- 健康检查：`GET /api/openclaw/health`
- 同步转写：`POST /api/openclaw/transcribe`
- 认证头：`X-OpenClaw-Token`

请求体示例：

```json
{
  "raw_input": "https://youtu.be/tCUnnaImyhQ"
}
```

响应体核心字段：

```json
{
  "job_id": "job-20260312-123456-000001",
  "title": "示例标题",
  "source_platform": "youtube",
  "transcript_text": "完整转写稿",
  "transcript_char_count": 1234
}
```

## OpenClaw 技能目录

仓库内技能源码目录：

`openclaw_skill/video-transcript-bridge`

标准安装目录：

`~/.openclaw/skills/video-transcript-bridge`

## OpenClaw 配置

把 `openclaw_skill/video-transcript-bridge/openclaw.config.example.json` 里的 `env` 合并到：

`~/.openclaw/openclaw.json`

至少要配置：

- `VIDEO_TRANSCRIPT_API_URL`
- `VIDEO_TRANSCRIPT_API_TOKEN`

## 安全边界

- 这是局域网自用桥接，不做公开发布。
- 服务端通过 `OPENCLAW_SHARED_TOKEN` 限制 OpenClaw 调用。
- 不开放匿名跨机器转写接口。
