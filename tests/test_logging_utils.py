from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from douyin_pipeline.logging_utils import configure_logging


class LoggingUtilsTests(unittest.TestCase):
    def test_configure_logging_is_idempotent_for_same_service(self) -> None:
        root_logger = logging.getLogger()
        original_handlers = list(root_logger.handlers)

        with TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / "output"
            with patch("douyin_pipeline.logging_utils._CONFIGURED_LOG_FILES", set()):
                log_file = configure_logging(output_dir, service_name="web")
                same_log_file = configure_logging(output_dir, service_name="web")

            self.assertEqual(log_file, same_log_file)
            self.assertEqual(log_file.name, "web.log")
            self.assertTrue(log_file.parent.exists())

            matching_handlers = [
                handler
                for handler in root_logger.handlers
                if getattr(handler, "baseFilename", None) == str(log_file)
            ]
            self.assertEqual(len(matching_handlers), 1)

            logging.getLogger("douyin_pipeline.test").info("log smoke test")
            self.assertTrue(log_file.exists())

            for handler in matching_handlers:
                root_logger.removeHandler(handler)
                handler.close()

        root_logger.handlers[:] = original_handlers


if __name__ == "__main__":
    unittest.main()
