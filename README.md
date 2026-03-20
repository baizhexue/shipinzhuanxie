# 视频转写助手

一个轻量的 Python 项目，用来处理这条链路：

`抖音 / Bilibili / 小红书 / 快手 / YouTube 分享文案或链接 -> 下载视频 -> 提取音频 -> 转成文字`

当前项目提供 4 个入口：

- CLI
- 本地 Web 页面
- Telegram 机器人
- OpenClaw 局域网技能入口

## 功能

- 从抖音 / Bilibili / 小红书 / 快手 / YouTube 分享文案或链接里提取 URL
- 调用 `yt-dlp` 下载视频
- 在 `yt-dlp` 处理抖音受限链接失败时回退到浏览器辅助下载
- 在 `yt-dlp` 处理小红书、快手页面波动时回退到页面级解析
- 用 `ffmpeg` 提取音频
- 用 `faster-whisper` 做语音转写
- 转写结果默认归一化为简体中文，并补一层大陆常用词汇修正
- 每个任务单独落盘，输出 `manifest.json` 供 Web 和 Telegram 展示状态

## 边界

- 只处理用户主动提交的单条任务
- 不提供平台风控规避、签名逆向、代理池、验证码对抗、设备指纹伪造等能力
- 需要登录态时，只接受用户自己的 `cookies.txt` 或本地浏览器 cookies
- 默认场景是单机、本地局域网或个人服务，不是大规模采集系统

## 运行要求

- Python `>=3.9`
- 本机可用的 `ffmpeg`
- 本机可用的 `yt-dlp`

## 一键部署

仓库下载后，现在可以直接走一键部署。
一键部署负责拉起主服务。
如果你还要给 OpenClaw 使用，再额外执行一次 `scripts/install_openclaw_skill.py`。

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\one_click_deploy.ps1
```

或者直接双击仓库根目录的：

```text
一键部署.bat
```

macOS / Linux：

```bash
bash ./scripts/one_click_deploy.sh
```

自动模式会这样处理：

- 如果本机可用 Docker，优先执行 `docker compose up --build -d web`
- 如果没有 Docker，就自动创建 `.venv`、安装 `.[web,asr]`、生成 `.env`，然后启动本地 Web 服务

默认访问地址：

- Docker 模式：`http://127.0.0.1:4444`
- 本地模式：`http://127.0.0.1:8000`

补充：

- OpenClaw 现在直接复用主服务端口，不再单独部署 `4455`
- 同机部署时，OpenClaw 应该指向当前主服务地址
- 局域网跨机器部署时，直接填写 Web 服务地址，例如 `http://192.168.50.201:4444`

常用参数：

```bash
python scripts/one_click_deploy.py --mode local --skip-asr
python scripts/one_click_deploy.py --mode docker --with-telegram
```

## 安装

基础安装：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

如果你需要转写：

```bash
pip install -e .[asr]
```

`asr` 额外依赖包含：

- `faster-whisper`
- `opencc-python-reimplemented`

如果你需要 Web 页面：

```bash
pip install -e .[web]
```

如果你需要 Web + 转写：

```bash
pip install -e .[web,asr]
```

## 环境自检

```bash
python -m douyin_pipeline doctor
python -m douyin_pipeline doctor --skip-asr
```

## CLI

只下载：

```bash
python -m douyin_pipeline download "https://v.douyin.com/xxxxxx/"
python -m douyin_pipeline download "https://www.bilibili.com/video/BV133NwzHEgy/"
python -m douyin_pipeline download "http://xhslink.com/o/3gjd39CJOsa"
python -m douyin_pipeline download "https://v.kuaishou.com/xxxxxx"
python -m douyin_pipeline download "https://www.youtube.com/watch?v=Sdf8fc9b0mI"
python -m douyin_pipeline download "https://www.youtube.com/shorts/HXvTmGxm2QM"
```

下载并转写：

```bash
python -m douyin_pipeline run "复制打开抖音，看看 https://v.douyin.com/xxxxxx/"
python -m douyin_pipeline run "https://www.bilibili.com/video/BV133NwzHEgy/"
python -m douyin_pipeline run "http://xhslink.com/o/3gjd39CJOsa"
python -m douyin_pipeline run "https://v.kuaishou.com/xxxxxx"
python -m douyin_pipeline run "https://www.youtube.com/watch?v=Sdf8fc9b0mI"
python -m douyin_pipeline run "https://www.youtube.com/shorts/HXvTmGxm2QM"
```

对本地视频补做转写：

```bash
python -m douyin_pipeline transcribe output\job-20260308-120000-123456\video.mp4
```

## Web

启动本地网页：

```bash
python -m douyin_pipeline web --host 127.0.0.1 --port 8000
```

或：

```bash
douyin-web --host 127.0.0.1 --port 8000
```

打开：

```text
http://127.0.0.1:8000
```

页面支持：

- 创建 `只下载` 任务
- 创建 `下载 + 转文字` 任务
- 对已下载成功的视频二次转写
- 任务中心、历史记录、系统设置三块工作区
- 历史任务分页、搜索、筛选和删除
- 查看任务进度、ETA、输出文件和转写预览
- 在网页里直接配置 Telegram 机器人

## Telegram Bot

Telegram 机器人支持作为任务入口。

行为：

- 给机器人发送抖音、Bilibili、小红书、快手或 YouTube 链接、完整分享文案
- 机器人直接执行 `download + transcribe`
- 处理中会按阶段回推任务进度
- 完成后回发任务摘要、转写预览和 `.txt` 文件
- 可以由 Web 页面统一托管和配置，无需单独维护脚本参数

环境变量：

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_IDS`
- `DOUYIN_PUBLIC_BASE_URL`
- `TELEGRAM_STATE_PATH`

CLI：

```bash
python -m douyin_pipeline telegram-bot --token <your_bot_token>
```

或：

```bash
douyin-telegram --token <your_bot_token>
```

## 常用环境变量

参考 [.env.example](.env.example)：

- `APP_OUTPUT_DIR`
- `FFMPEG_BIN`
- `YTDLP_BIN`
- `WHISPER_MODEL`
- `WHISPER_DEVICE`
- `DOUYIN_COOKIES_FILE`
- `DOUYIN_COOKIES_BROWSER`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_IDS`
- `DOUYIN_PUBLIC_BASE_URL`
- `TELEGRAM_STATE_PATH`

## 输出结构

每次任务会创建一个独立目录，例如：

```text
output/
  job-20260308-120000-123456/
    demo_123.mp4
    demo_123.wav
    demo_123.txt
    manifest.json
```

`manifest.json` 用来给 Web 页面和 Telegram 返回任务状态、预览和文件信息。

## 开源发布

仓库里已经补了这些开源基础文件：

- [.gitignore](.gitignore)
- [LICENSE](LICENSE)
- [.env.example](.env.example)
- [CHANGELOG.md](CHANGELOG.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [.github/workflows/ci.yml](.github/workflows/ci.yml)
- [docs/project_state.md](docs/project_state.md)

发布相关：

- 版本号定义在 [pyproject.toml](pyproject.toml) 和 [__init__.py](src/douyin_pipeline/__init__.py)
- 推送 `v*` tag 会触发 [.github/workflows/release.yml](.github/workflows/release.yml) 创建 GitHub Release
- Issue / PR 模板已经放在 `.github/`

## Docker

如果你想用容器启动：

```bash
docker compose up --build web
```

默认会启动 Web 服务并绑定：

```text
http://127.0.0.1:4444
```

如果还要启动 Telegram 机器人：

```bash
docker compose --profile telegram up --build
```

相关文件：

- [Dockerfile](Dockerfile)
- [docker-compose.yml](docker-compose.yml)
- [.dockerignore](.dockerignore)

发布到 GitHub 前，建议先导出一份干净目录：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export_github_repo.ps1
```

导出目录默认是：

```text
release\github
```

这个目录只包含适合公开上传的源码和文档，不包含：

- `output/`
- cookies 文件
- 浏览器临时 profile
- 日志
- 本地虚拟环境

## 测试

本地可以直接跑：

```bash
python -m compileall src tests
python -m unittest discover -s tests -v
```

GitHub Actions 会在 `main` 和 PR 上自动执行同样的基础检查。

## 许可证

项目采用 MIT License，见 [LICENSE](LICENSE)。

## OpenClaw 局域网技能

- OpenClaw 专用接口：`GET /api/openclaw/health`、`POST /api/openclaw/transcribe`
- 技能目录：`skills/video-transcript-bridge`
- 安装脚本：
  - 同机部署：`python scripts/install_openclaw_skill.py --force --mode local`
  - 跨机器局域网：`python scripts/install_openclaw_skill.py --force --mode lan --api-url http://192.168.50.201:4444`
- 接入说明：`docs/openclaw_integration.md`
- 安装脚本会自动：
  - 复制技能到 `~/.openclaw/workspace/skills/video-transcript-bridge`
  - 写入 `~/.openclaw/openclaw.json`
  - 自动生成 `VIDEO_TRANSCRIPT_API_TOKEN`
  - 在同机模式下同步写入服务端 `.env` 里的 `OPENCLAW_SHARED_TOKEN`

### 使用说明

#### 场景 1：OpenClaw 和视频转写服务装在同一台机器

适用条件：

- OpenClaw 和本项目都安装在同一台机器
- OpenClaw 直接调用本机视频转写服务

启动服务后执行：

```bash
python scripts/install_openclaw_skill.py --force --mode local
```

脚本会自动做这些事：

- 把 skill 安装到 `~/.openclaw/workspace/skills/video-transcript-bridge`
- 在 `~/.openclaw/openclaw.json` 写入：
  - Docker 模式：`VIDEO_TRANSCRIPT_API_URL=http://127.0.0.1:4444`
  - 本地模式：`VIDEO_TRANSCRIPT_API_URL=http://127.0.0.1:8000`
  - 自动生成的 `VIDEO_TRANSCRIPT_API_TOKEN`
- 在当前项目的 `.env` 里写入：
  - `OPENCLAW_SHARED_TOKEN=<同一份自动生成的 token>`

这意味着：

- 用户不需要自己生成 token
- 用户不需要自己改 `openclaw.json`
- 用户不需要自己抄服务端密钥

#### 场景 2：OpenClaw 和视频转写服务在不同机器上

适用条件：

- OpenClaw 在一台机器
- 视频转写服务在另一台机器
- 两台机器都在同一个局域网里

例如服务端是：

```text
http://192.168.50.201:4444
```

在 OpenClaw 那台机器执行：

```bash
python scripts/install_openclaw_skill.py --force --mode lan --api-url http://192.168.50.201:4444
```

脚本会自动：

- 安装 skill 到 `~/.openclaw/workspace/skills/video-transcript-bridge`
- 把服务地址写进 `~/.openclaw/openclaw.json`
- 自动生成 `VIDEO_TRANSCRIPT_API_TOKEN`

注意：

- `lan` 模式下，脚本不会自动去改远程服务机上的 `.env`
- 你需要把脚本生成的这份 token 同步到服务端的 `OPENCLAW_SHARED_TOKEN`
- 同步一次即可，后面重复使用

#### 脚本实际会修改哪些文件

- `~/.openclaw/workspace/skills/video-transcript-bridge`
- `~/.openclaw/openclaw.json`
- 同机模式下还会修改当前项目根目录的 `.env`

#### 用户安装完成后怎么验证

1. 先确认视频转写服务正在运行
2. 重启 OpenClaw，或者让 OpenClaw 重新加载技能
3. 给 OpenClaw 一条支持平台的视频链接
4. 它应该会调用这个 skill，并拿回 `transcript_text`

#### 如果安装脚本重复执行

- 加 `--force` 会覆盖旧的 skill 目录
- `openclaw.json` 里的 `video-transcript-bridge` 配置会被更新
- 已有 token 优先复用；没有时才自动生成新的
