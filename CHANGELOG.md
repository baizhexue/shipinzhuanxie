# 更新日志

本项目使用中文维护版本迭代记录，按“功能新增 / 修复 / 优化”归档。

## [0.9.3] - 2026-03-20

### 功能新增

- 为重构后的模块补齐独立测试，新增 `downloader_runtime`、`web_jobs`、`telegram_messages` 的 focused tests。

### 修复

- 修复 `telegram_messages.py` 的文案文件编码污染问题，恢复为干净的 UTF-8 中文文案。
- 修复重构过程中对系统 Python 误用导致的假性回归判断，统一以项目 `.venv` 作为验证环境。

### 优化

- 拆分 `web.py` 的辅助逻辑与任务服务层，新增 `web_support.py`、`web_jobs.py`。
- 拆分 `pipeline.py` 的 manifest 构建与回写逻辑，新增 `pipeline_manifest.py`。
- 拆分下载器的平台回退分发与 YouTube runtime 探测逻辑，新增 `downloader_fallbacks.py`、`downloader_runtime.py`。
- 拆分 Telegram 消息拼装逻辑，新增 `telegram_messages.py`，并清理 `telegram_bot.py` 中已无必要的兼容转发 helper。
- 本轮重构后，本地回归测试提升到 `84` 项，并已同步验证远端 `4444 / 4455` 两套服务。

## [0.9.2] - 2026-03-20

### 功能新增

- 新增跨平台一键部署脚本：`scripts/one_click_deploy.py`、`scripts/one_click_deploy.ps1`、`scripts/one_click_deploy.sh`。
- 新增 Windows 双击入口：`一键部署.bat`。

### 修复

- 修复用户下载仓库后仍需手动创建虚拟环境、复制 `.env`、逐条安装依赖的问题。
- 修复 Docker 入口版本号长期停留在旧版本的问题，`docker-compose.yml` 已跟随当前版本同步。

### 优化

- 一键部署优先探测 Docker；没有 Docker 时自动回退到 `.venv + pip` 本地安装。
- README 补充一键部署说明、默认访问地址和常用参数。
- OpenClaw 技能源码目录统一为 `skills/video-transcript-bridge`，并建议安装到 `~/.openclaw/workspace/skills/`。

## [0.9.1] - 2026-03-12

### 功能新增

- 任务对外返回新增 `status_note` 字段，网页会直接解释当前状态、超时兜底和抖音浏览器回退逻辑。

### 修复

- 修复长时间卡在 `queued`、`downloading`、`transcribing` 的任务无法自动收口的问题。
- 修复卡住任务持续占据历史记录、用户误以为仍在运行的问题。

### 优化

- 任务中心与历史记录卡片新增状态提示文案，详情页同步展示状态解释。
- 补充 Web 接口回归测试，覆盖超时任务自动清理场景。

## [0.9.0] - 2026-03-12

### 功能新增

- 新增 OpenClaw 专用局域网接口：`GET /api/openclaw/health`、`POST /api/openclaw/transcribe`。
- 新增 OpenClaw 技能目录 `skills/video-transcript-bridge`，包含 `SKILL.md`、helper 脚本和配置示例。
- 新增全文接口 `GET /api/jobs/{job_id}/transcript`，方便 OpenClaw 和其他系统读取完整转写稿。
- 新增 `scripts/install_openclaw_skill.py`，支持自动安装技能并写入配置。

### 修复

- 修复跨机器调用时的鉴权边界问题，统一走共享 token。
- 补齐 `Settings` 和测试用例中的 OpenClaw 配置字段，避免新增能力后本地测试失效。

### 优化

- 梳理 OpenClaw 场景的产品边界：网页继续承担人工入口，OpenClaw 走同步桥接接口。
- 补充 `docs/openclaw_integration.md` 和 `.env.example`，固化局域网部署方式。

## [0.8.2] - 2026-03-09

### 功能新增

- `doctor` 新增 YouTube JS runtime 能力校验，避免旧版 `yt-dlp` 被误判为可用。

### 修复

- 修复旧版 `yt-dlp` 不支持 `--js-runtimes` 时 YouTube 下载直接报参数错误的问题。
- 修复 Python 3.9 环境下远端无法直接升级新版 `yt-dlp` 的兼容性问题。
- 修复 macOS 部署优先命中旧版虚拟环境 `yt-dlp` 的问题。

### 优化

- 补充 YouTube runtime 探测与 `doctor` 相关回归测试。

## [0.8.1] - 2026-03-09

### 功能新增

- `doctor` 新增 `youtube_js_runtime` 检查项。

### 修复

- 修复 `node` / `deno` 不在 PATH 时 `yt-dlp` 无法发现 JS runtime 的问题。
- 修复远端 `doctor` 假绿但 YouTube 仍会失败的问题。

### 优化

- 补充 PATH 外安装 Deno 的检测回归测试。

## [0.8.0] - 2026-03-09

### 功能新增

- 正式加入 YouTube 下载与转写支持，覆盖 `watch`、`shorts` 和 `youtu.be` 链接。
- 平台识别补充 YouTube，任务历史和详情可直接看到来源平台。

### 修复

- 修复网页提示、错误提示和帮助文案里未把 YouTube 纳入支持范围的问题。

### 优化

- 统一 CLI、首页、Telegram、README 对多平台支持的表述。

## [0.7.0] - 2026-03-09

### 功能新增

- 正式加入快手视频下载与转写支持。
- 新增快手页面级解析器，可从分享页 `INIT_STATE` 中提取视频直链和标题。

### 修复

- 修复 `yt-dlp` 当前无法稳定处理部分快手短链时的下载失败问题。
- 补充快手“非视频”“直链缺失”等结构化错误提示。

### 优化

- README、首页、Telegram、CLI 文案同步纳入快手来源说明。

## [0.6.0] - 2026-03-09

### 功能新增

- 正式加入小红书视频下载与转写支持。
- 下载失败时新增小红书页面级回退解析器，可直接从页面提取视频地址。
- 任务记录新增来源平台字段。

### 修复

- 去掉 `yt-dlp` 的 `--restrict-filenames`，修复中文标题落盘后被压成下划线的问题。
- 补充小红书访问验证和视频地址缺失的结构化错误提示。

### 优化

- 首页、Telegram、CLI、README 同步纳入小红书来源说明。

## [0.5.0] - 2026-03-09

### 功能新增

- 加入 Bilibili 下载与转写支持。
- 下载器新增 `ffmpeg` 合并能力，支持处理 Bilibili 的分离音视频流。
- 转写器新增 `device=auto` 下 CUDA 失败自动回退 CPU。

### 修复

- 修复 Bilibili 只落地分离流但仍被误判成功的问题。
- 修复 CUDA 运行时缺失时直接失败的问题。

### 优化

- 更新错误分类和用户提示，区分 Bilibili 合并失败等问题。

## [0.4.1] - 2026-03-09

### 功能新增

- Telegram 用户提示进一步中文化。
- 版本记录统一切换为中文 changelog 维护方式。

### 修复

- 修复 Telegram 部分文案和文件标签仍为英文的问题。
- 修复版本元数据中的 BOM 兼容问题，避免远端重新安装失败。

### 优化

- 收敛 Telegram 面向用户的提示风格。

## [0.4.0] - 2026-03-09

### 功能新增

- Web 页面拆分为任务中心、历史记录、系统设置三块工作区。
- 新增历史任务分页、搜索、筛选、删除能力。
- Telegram 支持处理中阶段的任务进度回推。
- Telegram 配置可直接在网页中托管和修改。

### 修复

- 解决历史任务过多时首页拥挤、最近任务无法承载完整记录的问题。
- 修复 Telegram 独立进程管理与网页配置脱节的问题。

### 优化

- 信息架构从单页堆叠改为轻量工作台，更适合长期使用。
