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

`skills/video-transcript-bridge`

标准安装目录：

`~/.openclaw/workspace/skills/video-transcript-bridge`

除了安装脚本，也可以手动复制：

- 源目录：`skills/video-transcript-bridge`
- 目标目录：`~/.openclaw/workspace/skills/video-transcript-bridge`

## OpenClaw 配置

推荐直接运行安装脚本，而不是手工改配置。

### 同机部署

适用条件：

- OpenClaw 和视频转写服务在同一台机器上
- 服务本机监听当前主服务地址
- 默认服务地址是 `127.0.0.1:4444`
- 如果你把服务改到了别的端口，例如 `5555`，这里也要写成 `http://127.0.0.1:5555`

执行：

```bash
python scripts/install_openclaw_skill.py --force --mode local
```

脚本会自动完成：

- 安装 skill 到 `~/.openclaw/workspace/skills/video-transcript-bridge`
- 把 `VIDEO_TRANSCRIPT_API_URL` 写成当前主服务地址
- 自动生成 `VIDEO_TRANSCRIPT_API_TOKEN`
- 把同一份 token 同步写进当前项目 `.env` 的 `OPENCLAW_SHARED_TOKEN`

这一步完成后，OpenClaw 和服务端已经共享同一份密钥，不需要用户手工生成 token。

### 跨机器局域网部署

适用条件：

- OpenClaw 在机器 A
- 视频转写服务在机器 B
- 例如服务地址是 `http://192.168.50.201:4444`
- 如果服务机换了端口，例如 `5555`，这里也要写成对应的新地址

执行：

```bash
python scripts/install_openclaw_skill.py --force --mode lan --api-url http://192.168.50.201:4444
```

脚本会自动完成：

- 复制技能到 `~/.openclaw/workspace/skills/video-transcript-bridge`
- 写入 `~/.openclaw/openclaw.json`
- 自动生成 `VIDEO_TRANSCRIPT_API_TOKEN`

需要额外注意：

- `lan` 模式不会自动修改远端服务机上的 `.env`
- 你需要把生成出来的 token 同步到服务机的 `OPENCLAW_SHARED_TOKEN`
- 服务端和 OpenClaw 端只要保持同一份 token 即可正常通信

### 脚本修改范围

安装脚本会修改这些位置：

- `~/.openclaw/workspace/skills/video-transcript-bridge`
- `~/.openclaw/openclaw.json`
- 同机模式下还会修改当前项目根目录的 `.env`

### 手动复制 skill 的方式

如果你不想运行安装脚本，也可以自己复制 skill 目录。

步骤：

1. 把仓库中的 `skills/video-transcript-bridge` 复制到 `~/.openclaw/workspace/skills/video-transcript-bridge`
2. 手动修改 `~/.openclaw/openclaw.json`
3. 填好这两个环境变量：
   - `VIDEO_TRANSCRIPT_API_URL`
   - `VIDEO_TRANSCRIPT_API_TOKEN`
4. 重启 OpenClaw

注意：

- 手动复制只会安装 skill 文件，不会自动生成 token
- 也不会自动同步服务端 `.env`
- 如果你想省掉这些手工步骤，优先使用安装脚本

### 用户视角的最小步骤

同机部署：

1. 启动视频转写服务
2. 执行 `python scripts/install_openclaw_skill.py --force --mode local`
3. 重启 OpenClaw

跨机器部署：

1. 确认服务端已经运行
2. 在 OpenClaw 机器执行 `python scripts/install_openclaw_skill.py --force --mode lan --api-url http://192.168.50.201:4444`
3. 把生成的 token 同步到服务端 `.env`
4. 重启 OpenClaw

### 失败排查

- `401 Unauthorized`：两端 token 不一致
- `request failed`：`VIDEO_TRANSCRIPT_API_URL` 地址不通
- Skill 没生效：确认目录在 `~/.openclaw/workspace/skills/video-transcript-bridge`
- OpenClaw 仍读旧配置：重启 OpenClaw 后再试

## 安全边界

- 这是局域网自用桥接，不做公开发布。
- 服务端通过 `OPENCLAW_SHARED_TOKEN` 限制 OpenClaw 调用。
- 不开放匿名跨机器转写接口。
