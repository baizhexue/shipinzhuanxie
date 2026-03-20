# OpenClaw 本地技能

这个目录是给 OpenClaw 用的局域网技能，不是给当前 Web 页面直接调用的前端资源。

## 目录说明

- `SKILL.md`: OpenClaw 技能说明
- `client.py`: 调用局域网转写服务的 helper
- `openclaw.config.example.json`: `~/.openclaw/openclaw.json` 的配置示例

## 依赖

- OpenClaw 所在机器能访问 `VIDEO_TRANSCRIPT_API_URL`
- OpenClaw 所在机器有 `python3` 或 `python`
- 目标转写服务已经部署并配置 `OPENCLAW_SHARED_TOKEN`

## 建议安装位置

- `~/.openclaw/workspace/skills/video-transcript-bridge`
