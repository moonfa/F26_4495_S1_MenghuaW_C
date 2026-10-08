import unittest

from app import security as s


class SecurityTests(unittest.TestCase):
    def test_host_check_blocks_rebinding(self):
        for ok in ("127.0.0.1:8000", "localhost:8000", "localhost", "[::1]:8000"):
            self.assertTrue(s.host_ok(ok), ok)
        for bad in ("evil.example:8000", "127.0.0.1.evil.example", "", None):
            self.assertFalse(s.host_ok(bad), bad)

    def test_origin_check_blocks_cross_site_writes(self):
        self.assertTrue(s.origin_ok("POST", "http://127.0.0.1:8000", "127.0.0.1:8000"))
        self.assertTrue(s.origin_ok("POST", None, "127.0.0.1:8000"))                    # curl / scripts
        self.assertTrue(s.origin_ok("GET", "http://evil.example", "127.0.0.1:8000"))    # reads are not state-changing
        self.assertFalse(s.origin_ok("POST", "http://evil.example", "127.0.0.1:8000"))
        self.assertFalse(s.origin_ok("DELETE", "null", "127.0.0.1:8000"))
        self.assertFalse(s.origin_ok("PUT", "http://localhost:3000", "localhost:8000"))

    def test_extra_hosts_from_env(self):
        import os
        os.environ["ALLOWED_HOSTS"] = "mybox.lan"
        try:
            self.assertTrue(s.host_ok("mybox.lan:8000"))
        finally:
            del os.environ["ALLOWED_HOSTS"]
        self.assertFalse(s.host_ok("mybox.lan:8000"))


if __name__ == "__main__":
    unittest.main()
