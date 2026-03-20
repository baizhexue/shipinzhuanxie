# 项目状态

更新日期：`2026-03-20`

## 当前代码状态

- 当前分支：`feature/openclaw-skill`
- 当前提交：`0865831070b17823d81a37e77ea68a0d6f6d24f7`
- 当前版本：`0.9.2`

## 项目目标

这个项目提供一个轻量的视频下载和转写服务，当前支持：

- 抖音
- Bilibili
- 小红书
- 快手
- YouTube

当前入口包括：

- CLI
- Web 页面
- Telegram 机器人
- OpenClaw 局域网技能桥接

## 本地仓库关键目录

- Web/API 主代码：`src/douyin_pipeline`
- OpenClaw 技能模板：`skills/video-transcript-bridge`
- OpenClaw 接入文档：`docs/openclaw_integration.md`
- 一键部署脚本：`scripts/one_click_deploy.py`
- OpenClaw 自动安装脚本：`scripts/install_openclaw_skill.py`

## 远端机器

### 1. 视频转写服务机

- 地址：`192.168.50.201`
- 用户：`baizhexue`

主要目录：

- 主 Web 服务目录：`/Users/baizhexue/dev/xiangmu`
- OpenClaw 专用服务目录：`/Users/baizhexue/dev/video-transcript-openclaw-service`

主要端口：

- Web 页面：`4444`
- OpenClaw 专用接口：`4455`

主要服务：

- `http://192.168.50.201:4444`
- `http://192.168.50.201:4455`

launchd 服务：

- `com.baizhexue.douyin-web`
- `com.baizhexue.video-transcript-openclaw-service`

### 2. OpenClaw 机器

- 地址：`192.168.50.160`
- 用户：`xiaobai`

OpenClaw 主目录：

- `~/.openclaw`

默认 workspace：

- `/home/xiaobai/.openclaw/workspace`

当前 skill 实际安装目录：

- `/home/xiaobai/.openclaw/workspace/skills/video-transcript-bridge`

OpenClaw 配置文件：

- `/home/xiaobai/.openclaw/openclaw.json`

## OpenClaw 通信说明

OpenClaw 调用服务走这两个接口：

- `GET /api/openclaw/health`
- `POST /api/openclaw/transcribe`

鉴权头：

- `X-OpenClaw-Token`

不要把 token 明文写进仓库。

当前原则：

- 同机部署：安装脚本自动生成 token，并同步写入项目 `.env` 和 `openclaw.json`
- 跨机器部署：安装脚本自动生成 token，并写入 OpenClaw；服务端 `.env` 需要保持同一份 token

## OpenClaw 安装约定

当前统一约定：

- skill 模板目录：`skills/video-transcript-bridge`
- 用户机安装目录：`~/.openclaw/workspace/skills/video-transcript-bridge`

推荐命令：

同机部署：

```bash
python scripts/install_openclaw_skill.py --force --mode local
```

跨机器部署：

```bash
python scripts/install_openclaw_skill.py --force --mode lan --api-url http://192.168.50.201:4455
```

## 当前已经完成

- 多平台视频下载与转写
- Web 单页工作台
- Telegram 入口和网页配置
- 任务历史、分页、删除
- 卡住任务自动清理
- OpenClaw 专用接口
- OpenClaw skill 自动安装和配置写入
- 一键部署脚本

## 当前已知约束

- 医生检查接口 `/api/doctor` 现在不会再把服务打挂，但某些环境里 `yt-dlp --version` 探测仍可能超时，表现为 `has_failures=true`
- 这不代表下载一定失败；需要以真实下载链路为准
- 项目里不实现平台风控规避能力

## 换机器后的接手步骤

1. 先打开本文件，确认当前分支、提交号和两台远端机器职责
2. 查看：
   - `README.md`
   - `docs/openclaw_integration.md`
3. 如需本地运行项目，执行：
   - `scripts/one_click_deploy.py`
4. 如需恢复 OpenClaw skill，执行：
   - `scripts/install_openclaw_skill.py`
5. 如需检查远端：
   - `192.168.50.201` 看 Web/OpenClaw 服务
   - `192.168.50.160` 看 OpenClaw skill 和 `openclaw.json`

## 不要写进仓库的内容

- Telegram bot token
- OpenClaw shared token 明文
- cookies 文件
- 本机浏览器登录态
- 远端机器密码

这些信息只应保留在：

- `.env`
- 远端机器本地配置
- 你自己的密码管理工具
