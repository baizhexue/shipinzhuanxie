from __future__ import annotations

from threading import RLock, Thread
from typing import Optional

from douyin_pipeline.config import Settings
from douyin_pipeline.runtime_config import (
    TelegramWebConfig,
    get_runtime_dir,
    load_telegram_web_config,
    telegram_web_config_to_public_payload,
    update_telegram_web_config,
)
from douyin_pipeline.telegram_bot import (
    TelegramBotClient,
    TelegramBotRunner,
    TelegramBotSettings,
)


class TelegramManager:
    def __init__(self, app_settings: Settings) -> None:
        self._app_settings = app_settings
        self._lock = RLock()
        self._runner: Optional[TelegramBotRunner] = None
        self._thread: Optional[Thread] = None
        self._last_error: Optional[str] = None
        self._bot_username: Optional[str] = None

    def ensure_started_from_saved(self) -> None:
        config = load_telegram_web_config(self._app_settings.output_dir)
        if config.enabled and config.token:
            self.start(config)

    def get_public_state(self) -> dict:
        with self._lock:
            config = load_telegram_web_config(self._app_settings.output_dir)
            return {
                "config": telegram_web_config_to_public_payload(config),
                "runtime": {
                    "running": bool(self._thread and self._thread.is_alive()),
                    "bot_username": self._bot_username,
                    "last_error": self._last_error,
                    "mode": "managed_by_web",
                },
            }

    def save_config(self, payload: dict) -> dict:
        config = update_telegram_web_config(self._app_settings.output_dir, payload)
        if config.enabled and config.token:
            self.start(config)
        elif not config.enabled:
            self.stop()
        return self.get_public_state()

    def start(self, config: Optional[TelegramWebConfig] = None) -> dict:
        with self._lock:
            resolved = config or load_telegram_web_config(self._app_settings.output_dir)
            if not resolved.token:
                raise ValueError("Telegram bot token is required.")

            self.stop()

            bot_settings = TelegramBotSettings(
                token=resolved.token,
                allowed_chat_ids=resolved.allowed_chat_ids,
                public_base_url=resolved.public_base_url,
                state_path=get_runtime_dir(self._app_settings.output_dir) / "telegram_bot_state.json",
                poll_timeout=resolved.poll_timeout,
                retry_delay=resolved.retry_delay,
                progress_updates=resolved.progress_updates,
            )
            client = TelegramBotClient(bot_settings)
            profile = client.get_me()
            self._bot_username = str(profile.get("username") or "")
            self._last_error = None
            runner = TelegramBotRunner(self._app_settings, bot_settings, client)
            thread = Thread(target=self._run_runner, args=(runner,), daemon=True)
            self._runner = runner
            self._thread = thread
            thread.start()
        return self.get_public_state()

    def stop(self) -> dict:
        runner = None
        thread = None
        with self._lock:
            runner = self._runner
            thread = self._thread
            self._runner = None
            self._thread = None
            self._bot_username = None
        if runner is not None:
            runner.request_stop()
        if thread is not None and thread.is_alive():
            timeout_seconds = 2.0
            if runner is not None:
                timeout_seconds = min(max(float(runner._bot_settings.poll_timeout) + 2.0, 2.0), 20.0)
            thread.join(timeout=timeout_seconds)
        return self.get_public_state()

    def _run_runner(self, runner: TelegramBotRunner) -> None:
        try:
            runner.run_forever()
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
        finally:
            with self._lock:
                if self._runner is runner:
                    self._runner = None
                self._thread = None
