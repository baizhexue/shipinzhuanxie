from __future__ import annotations

import unittest

from douyin_pipeline.kuaishou_page import (
    _extract_init_state,
    _extract_photo_payload,
    _extract_title,
    _extract_video_url,
)


HTML_SAMPLE = """
<html>
  <body>
    <script>
      window.INIT_STATE = {
        "demo": {
          "photo": {
            "photoId": "5219109210059965448",
            "photoType": "VIDEO",
            "caption": "女子包揽3年同学聚会，第4年闹得不欢而散",
            "mainMvUrls": [
              {"url": "https://txmov2.a.kwimgs.com/demo.mp4"}
            ]
          }
        }
      }
    </script>
    <script>window.__USE_SSR__ = true</script>
  </body>
</html>
"""


class KuaishouPageTests(unittest.TestCase):
    def test_extract_init_state_and_photo_payload(self) -> None:
        state = _extract_init_state(HTML_SAMPLE)
        photo = _extract_photo_payload(state)
        self.assertEqual(photo["photoType"], "VIDEO")
        self.assertEqual(photo["photoId"], "5219109210059965448")

    def test_extract_title_from_photo_caption(self) -> None:
        state = _extract_init_state(HTML_SAMPLE)
        photo = _extract_photo_payload(state)
        self.assertEqual(_extract_title(photo, "5219109210059965448"), "女子包揽3年同学聚会，第4年闹得不欢而散")

    def test_extract_video_url_from_main_mv_urls(self) -> None:
        state = _extract_init_state(HTML_SAMPLE)
        photo = _extract_photo_payload(state)
        self.assertEqual(_extract_video_url(photo), "https://txmov2.a.kwimgs.com/demo.mp4")


if __name__ == "__main__":
    unittest.main()
