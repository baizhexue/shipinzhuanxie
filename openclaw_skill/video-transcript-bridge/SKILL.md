---
name: video-transcript-bridge
description: 当研究结果里出现抖音、Bilibili、小红书、快手、YouTube 链接，且你需要把视频语音转成文字时，调用局域网视频转写服务并返回完整稿子。
metadata: {"openclaw":{"skillKey":"video-transcript-bridge","requires":{"bins":["python3"],"env":["VIDEO_TRANSCRIPT_API_URL","VIDEO_TRANSCRIPT_API_TOKEN"]},"primaryEnv":"VIDEO_TRANSCRIPT_API_TOKEN"}}
---

# Video Transcript Bridge

## 何时使用

- 用户明确要“转文字”“提取视频文稿”“拿到视频全文转写”。
- 你在调研过程中已经找到以下平台的公开视频链接，并且后续分析需要完整转写稿：
  - `youtube.com`
  - `youtu.be`
  - `bilibili.com`
  - `b23.tv`
  - `xiaohongshu.com`
  - `xhslink.com`
  - `kuaishou.com`
  - `v.kuaishou.com`
  - `douyin.com`
  - `v.douyin.com`

## 不要使用

- 用户只要摘要，不需要完整转写稿。
- 当前链接不是上面这些平台。
- 你还没有拿到实际的视频链接或分享文案。

## 调用方式

1. 保留用户给出的原始链接或完整分享文案，不要擅自改写。
2. 为了避免 shell 引号问题，把原始输入写进一个 UTF-8 临时文件。
3. 用 shell 执行下面的 helper：

macOS / Linux:

```bash
tmp_file="$(mktemp)"
cat > "$tmp_file" <<'EOF'
<把原始链接或完整分享文案原样放这里>
EOF
python3 "$HOME/.openclaw/skills/video-transcript-bridge/client.py" --input-file "$tmp_file"
rm -f "$tmp_file"
```

Windows PowerShell:

```powershell
$tmpFile = New-TemporaryFile
Set-Content -Path $tmpFile -Value @'
<把原始链接或完整分享文案原样放这里>
'@ -Encoding UTF8
python "$env:USERPROFILE\\.openclaw\\skills\\video-transcript-bridge\\client.py" --input-file $tmpFile
Remove-Item $tmpFile -Force
```

## 结果处理

- helper 成功时会输出 JSON。
- 直接读取 `transcript_text` 作为完整转写稿。
- `title`、`source_platform`、`job_id` 可作为补充元数据。
- 如果返回的是错误 JSON，就把 `detail` 和 `error_hint` 转成面向用户的中文解释。

## 返回给用户时的要求

- 明确这是基于视频链接生成的机器转写稿。
- 如果后续要做总结、观点提炼、时间线整理，先以 `transcript_text` 为依据。
- 不要假装拿到了平台官方字幕；这是本地转写服务返回的结果。
