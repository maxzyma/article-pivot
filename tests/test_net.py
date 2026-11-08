from __future__ import annotations

import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from article_pivot import net
from article_pivot.adapters.source import claude_blog, lilian_weng

EOF_ERR = urllib.error.URLError("[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol")


def response(body: str):
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = body.encode()
    resp.headers.get_content_charset.return_value = "utf-8"
    return resp


class FetchTextTests(unittest.TestCase):
    def test_transient_drop_is_retried(self):
        with patch.object(net.urllib.request, "urlopen", side_effect=[EOF_ERR, response("ok")]), \
                patch.object(net.time, "sleep") as sleep:
            self.assertEqual("ok", net.fetch_text("https://x", accept="text/html"))
        sleep.assert_called_once_with(net.BACKOFF[0])

    def test_http_not_found_is_not_retried(self):
        missing = urllib.error.HTTPError("https://x", 404, "Not Found", {}, None)
        with patch.object(net.urllib.request, "urlopen", side_effect=[missing]) as opener, \
                patch.object(net.time, "sleep"), self.assertRaises(urllib.error.HTTPError):
            net.fetch_text("https://x")
        self.assertEqual(1, opener.call_count)

    def test_persistent_drop_gives_up_after_the_schedule(self):
        with patch.object(net.urllib.request, "urlopen", side_effect=EOF_ERR) as opener, \
                patch.object(net.time, "sleep"), self.assertRaises(urllib.error.URLError):
            net.fetch_text("https://x")
        self.assertEqual(len(net.BACKOFF) + 1, opener.call_count)


class AdapterWiringTests(unittest.TestCase):
    def test_source_adapters_fetch_through_the_shared_helper(self):
        for module in (claude_blog, lilian_weng):
            with patch.object(module, "fetch_text", return_value="body") as fetch:
                self.assertEqual("body", module._fetch_text("https://x"))
            fetch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
