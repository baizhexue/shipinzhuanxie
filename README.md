# douyin-pipeline

一个轻量的 Python 项目，用来处理这条链路：

`抖音分享文案/链接 -> 下载视频 -> 提取音频 -> 转成文字`

当前项目提供 3 个入口：

- CLI
- 本地 Web 页面
- Telegram 机器人

## 功能

- 从抖音分享文案里提取 URL
- 调用 `yt-dlp` 下载视频
- 在 `yt-dlp` 失败时回退到浏览器辅助下载
- 用 `ffmpeg` 提取音频
- 用 `faster-whisper` 做语音转写
- 转写结果默认归一化为简体中文，并补一层大陆常用词汇修正
- 任务结果输出为独立目录和 `manifest.json`

## 边界

- 只处理用户主动提交的单条任务
- 不提供平台风控规避、签名逆向、代理池、验证码对抗、设备指纹伪造等能力
- 需要登录态时，只接受用户自己的 `cookies.txt` 或本地浏览器 cookies
- 默认场景是单机、本地局域网或个人服务，不是大规模采集系统

## 运行要求

- Python `>=3.9`
- 本机可用的 `ffmpeg`
- 本机可用的 `yt-dlp`

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
```

下载并转写：

```bash
python -m douyin_pipeline run "复制打开抖音，看看 https://v.douyin.com/xxxxxx/"
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
- 创建 `下载 + 转写` 任务
- 对已下载成功的视频二次转写
- 任务中心、历史记录、系统设置三块工作区
- 历史任务分页、搜索、筛选和删除
- 查看任务进度、ETA、输出文件和转写预览
- 在网页里直接配置 Telegram 机器人

## Telegram Bot

Telegram 机器人支持作为任务入口。

行为：

- 给机器人发送抖音链接或完整分享文案
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

发布相关：

- 版本号定义在 [pyproject.toml](pyproject.toml) 和 [__init__.py](src/douyin_pipeline/__init__.py)
- 推送 `v*` tag 会触发 [release.yml](.github/workflows/release.yml) 创建 GitHub Release
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
