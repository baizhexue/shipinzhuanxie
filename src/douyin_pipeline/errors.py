from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UserFacingError:
    code: str
    kind: str
    message: str
    hint: Optional[str] = None
    technical_detail: Optional[str] = None


def classify_exception(exc: BaseException) -> UserFacingError:
    detail = str(exc).strip() or exc.__class__.__name__
    lowered = detail.lower()

    if "no url found" in lowered:
        return _error(
            code="invalid_input",
            kind="input",
            message="没有识别到可用链接。",
            hint="请粘贴完整分享文案，或者直接粘贴抖音 URL。",
            technical_detail=detail,
        )

    if "fresh cookies" in lowered:
        return _error(
            code="douyin_fresh_cookies",
            kind="auth",
            message="抖音要求更新的浏览器 cookies 才能访问这个视频。",
            hint="先在浏览器里打开这条视频并确认能播放，再重试。也可以改用浏览器 cookies 或 cookies.txt。",
            technical_detail=detail,
        )

    if "could not copy chrome cookie database" in lowered or (
        "cookie database" in lowered and "copy" in lowered
    ):
        return _error(
            code="browser_cookie_locked",
            kind="auth",
            message="浏览器 cookies 数据库当前被占用。",
            hint="完全关闭对应浏览器后再试，或者改用其他浏览器 / cookies.txt。",
            technical_detail=detail,
        )

    if "browser fallback requires" in lowered or "pip install playwright" in lowered:
        return _error(
            code="playwright_missing",
            kind="dependency",
            message="浏览器回退下载依赖未安装。",
            hint="安装 playwright 后再试。",
            technical_detail=detail,
        )

    if detail.startswith("Video download failed."):
        return _error(
            code="download_failed",
            kind="download",
            message="视频下载失败。",
            hint="确认链接有效、网络正常；如果是抖音视频，必要时提供浏览器 cookies 或 cookies.txt。",
            technical_detail=detail,
        )

    if "no video file was found" in lowered:
        return _error(
            code="download_output_missing",
            kind="download",
            message="下载命令执行完成，但没有找到视频文件。",
            hint="检查下载目录权限，或查看 yt-dlp 输出是否被站点限制。",
            technical_detail=detail,
        )

    if "unable to resolve douyin video id" in lowered:
        return _error(
            code="douyin_video_id_missing",
            kind="download",
            message="浏览器回退没有解析出抖音视频 ID。",
            hint="确认分享链接仍可访问，必要时重新复制完整分享文案后再试。",
            technical_detail=detail,
        )

    if "detail json did not contain a playable video url" in lowered:
        return _error(
            code="douyin_play_url_missing",
            kind="download",
            message="抖音详情接口没有返回可播放的视频地址。",
            hint="这通常是站点限制或视频状态变化导致，稍后重试或换一条链接验证。",
            technical_detail=detail,
        )

    if detail.startswith("Audio extraction failed."):
        return _error(
            code="audio_extraction_failed",
            kind="media",
            message="音频提取失败。",
            hint="确认 ffmpeg 可用，并检查下载到的视频文件是否完整。",
            technical_detail=detail,
        )

    if "faster-whisper is not installed" in lowered:
        return _error(
            code="asr_dependency_missing",
            kind="dependency",
            message="转写依赖未安装。",
            hint="安装 asr 依赖后重试：pip install -e .[asr]",
            technical_detail=detail,
        )

    if "job manifest not found" in lowered:
        return _error(
            code="manifest_missing",
            kind="storage",
            message="任务记录不存在。",
            hint="这条任务目录可能已被删除，刷新任务列表后再试。",
            technical_detail=detail,
        )

    if "does not have a downloadable video to transcribe" in lowered:
        return _error(
            code="video_missing_for_transcribe",
            kind="input",
            message="这条任务没有可转写的视频文件。",
            hint="先成功下载视频，再发起转文字。",
            technical_detail=detail,
        )

    if "downloaded video file is missing" in lowered:
        return _error(
            code="downloaded_video_missing",
            kind="storage",
            message="已下载的视频文件不存在。",
            hint="检查输出目录是否被移动或清理，然后重新下载。",
            technical_detail=detail,
        )

    return _error(
        code="unknown_error",
        kind="unknown",
        message="任务失败。",
        hint="请查看详细错误信息或日志后重试。",
        technical_detail=detail,
    )


def _error(
    *,
    code: str,
    kind: str,
    message: str,
    hint: Optional[str],
    technical_detail: str,
) -> UserFacingError:
    return UserFacingError(
        code=code,
        kind=kind,
        message=message,
        hint=hint,
        technical_detail=technical_detail,
    )
