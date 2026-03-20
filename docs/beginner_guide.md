# 小白安装说明

这份说明是给完全没接触过命令行的人看的。

你不用先学原理。
你只要照着步骤一步一步做，就能把网页跑起来。

## 你最后会得到什么

安装完成后，你可以在网页里：

1. 粘贴抖音、Bilibili、小红书、快手、YouTube 链接
2. 下载视频
3. 把视频转成文字

## Windows

### 第一步：安装 Python

1. 打开浏览器
2. 访问 `https://www.python.org/downloads/`
3. 下载 Python 3.9 或更高版本
4. 安装时记得勾选 `Add Python to PATH`

### 第二步：安装 ffmpeg

1. 打开 Windows 的“终端”或 PowerShell
2. 输入这句：

```powershell
winget install Gyan.FFmpeg
```

3. 等它装完

### 第三步：运行一键部署

找到项目根目录里的这个文件，直接双击：

```text
一键部署.bat
```

如果你不会用命令行，双击这个文件就可以。

### 第四步：等待自动安装

它会自动帮你：

1. 检查环境
2. 安装依赖
3. 下载转写模型
4. 启动网页服务

### 第五步：打开网页

看到下面任意一个地址能打开，就说明安装成功了：

```text
http://127.0.0.1:8000
http://127.0.0.1:4444
```

## macOS

### 第一步：安装 Python

1. 打开浏览器
2. 访问 `https://www.python.org/downloads/`
3. 下载并安装 Python 3.9 或更高版本

### 第二步：安装 ffmpeg

如果你已经安装了 Homebrew，就打开“终端”输入：

```bash
brew install ffmpeg
```

### 第三步：运行一键部署

1. 打开“终端”
2. 进入项目文件夹
3. 输入下面这句：

```bash
bash ./scripts/one_click_deploy.sh
```

### 第四步：等待自动安装

它会自动帮你安装依赖、下载转写模型，并启动网页服务。

### 第五步：打开网页

看到下面任意一个地址能打开，就说明安装成功了：

```text
http://127.0.0.1:8000
http://127.0.0.1:4444
```

## Linux

### 第一步：确认 Python 版本

确认你的机器里已经有 Python 3.9 或更高版本。

### 第二步：安装 ffmpeg

如果你是 Ubuntu / Debian，可以直接输入：

```bash
sudo apt update && sudo apt install -y ffmpeg
```

### 第三步：运行一键部署

1. 打开终端
2. 进入项目文件夹
3. 输入下面这句：

```bash
bash ./scripts/one_click_deploy.sh
```

### 第四步：等待自动安装

它会自动帮你安装依赖、下载转写模型，并启动网页服务。

### 第五步：打开网页

看到下面任意一个地址能打开，就说明安装成功了：

```text
http://127.0.0.1:8000
http://127.0.0.1:4444
```

## 网页打开后怎么用

1. 把视频链接粘贴进去
2. 先点“只下载”试一下
3. 下载成功后，再试“下载 + 转文字”
4. 如果只是想把已经下载好的视频转文字，也可以在结果页继续操作

## 如果你还要给 OpenClaw 用

等网页能正常打开以后，再做这一步。

### 最简单的办法

运行安装脚本：

- 同一台机器：
  - `python scripts/install_openclaw_skill.py --force --mode local`
- 局域网另一台机器：
  - `python scripts/install_openclaw_skill.py --force --mode lan --api-url http://192.168.50.201:4444`

### 也可以手动复制

把这个文件夹：

```text
skills/video-transcript-bridge
```

复制到：

```text
~/.openclaw/workspace/skills/video-transcript-bridge
```

然后再手动配置 `openclaw.json`。

## 如果装到一半失败了

先看是不是下面几个常见原因：

1. Python 没装好
2. ffmpeg 没装好
3. 第一次下载模型时网络太慢
4. 电脑没有联网

这时候最简单的处理方式是：

1. 先把 Python 和 ffmpeg 装好
2. 再重新双击或重新运行一键部署
