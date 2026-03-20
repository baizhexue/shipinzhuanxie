from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.install_openclaw_skill import (
    DEFAULT_SKILL_NAME,
    install_skill,
    load_env_file,
    load_json_file,
    save_openclaw_skill_env,
    write_env_value,
)


class InstallOpenClawSkillTests(unittest.TestCase):
    def test_install_skill_copies_directory(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "skills" / DEFAULT_SKILL_NAME
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("demo", encoding="utf-8")
            dest = root / "workspace" / "skills" / DEFAULT_SKILL_NAME

            install_skill(source, dest, force=False)

            self.assertTrue((dest / "SKILL.md").exists())

    def test_save_openclaw_skill_env_writes_skill_entry(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "openclaw.json"
            config = {
                "skills": {
                    "entries": {}
                }
            }

            save_openclaw_skill_env(
                config_path,
                config,
                api_url="http://127.0.0.1:4455",
                token="demo-token",
            )

            payload = json.loads(config_path.read_text(encoding="utf-8"))
            env = payload["skills"]["entries"][DEFAULT_SKILL_NAME]["env"]
            self.assertEqual(env["VIDEO_TRANSCRIPT_API_URL"], "http://127.0.0.1:4455")
            self.assertEqual(env["VIDEO_TRANSCRIPT_API_TOKEN"], "demo-token")

    def test_write_env_value_upserts_token(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text("OPENCLAW_SHARED_TOKEN=old\nOTHER=1\n", encoding="utf-8")

            write_env_value(env_path, "OPENCLAW_SHARED_TOKEN", "new-token")

            values = load_env_file(env_path)
            self.assertEqual(values["OPENCLAW_SHARED_TOKEN"], "new-token")
            self.assertEqual(values["OTHER"], "1")

    def test_load_json_file_returns_default_when_missing(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            missing_path = Path(tmp_dir) / "missing.json"
            payload = load_json_file(missing_path, default={"skills": {}})
            self.assertEqual(payload, {"skills": {}})


if __name__ == "__main__":
    unittest.main()
