import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin"


class AccountLimitsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.accounts = self.root / "accounts"
        self.accounts.mkdir()
        self.codex = self.root / "codex"
        self.codex.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                from pathlib import Path
                import sys

                account = Path(os.environ["CODEX_HOME"]).name
                for line in sys.stdin:
                    message = json.loads(line)
                    if message.get("id") == 1:
                        print(json.dumps({"id": 1, "result": {}}), flush=True)
                    if message.get("id") != 2:
                        continue
                    if account == "expired":
                        print(json.dumps({
                            "id": 2,
                            "error": {"code": -32603, "message": "request failed: 401 Unauthorized"},
                        }), flush=True)
                    else:
                        used = 20 if account == "alpha" else 35
                        print(json.dumps({
                            "id": 2,
                            "result": {
                                "rateLimitsByLimitId": {
                                    "codex": {
                                        "limitId": "codex",
                                        "limitName": None,
                                        "planType": "plus",
                                        "primary": {
                                            "usedPercent": used,
                                            "windowDurationMins": 300,
                                            "resetsAt": 1780000000,
                                        },
                                        "secondary": {
                                            "usedPercent": 50,
                                            "windowDurationMins": 10080,
                                            "resetsAt": 1780100000,
                                        },
                                    }
                                }
                            },
                        }), flush=True)
                """
            )
        )
        self.codex.chmod(self.codex.stat().st_mode | stat.S_IXUSR)

    def tearDown(self):
        self.temporary.cleanup()

    def account(self, name):
        home = self.accounts / name
        home.mkdir()
        (home / "auth.json").write_text("{}")
        return home

    def run_helper(self, *extra):
        return subprocess.run(
            [
                str(BIN / "codex-account-limits"),
                "--accounts-home",
                str(self.accounts),
                "--codex-bin",
                str(self.codex),
                *extra,
            ],
            text=True,
            capture_output=True,
            timeout=10,
        )

    def test_lists_all_windows_in_account_order(self):
        self.account("zeta")
        self.account("alpha")

        result = self.run_helper("--workers", "2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ACCOUNT", result.stdout)
        self.assertIn("primary", result.stdout)
        self.assertIn("secondary", result.stdout)
        self.assertIn("5h", result.stdout)
        self.assertIn("1w", result.stdout)
        self.assertIn("20%", result.stdout)
        self.assertIn("80%", result.stdout)
        self.assertIn("CST", result.stdout)
        self.assertLess(result.stdout.index("alpha"), result.stdout.index("zeta"))

    def test_one_failed_account_preserves_successful_output(self):
        self.account("alpha")
        self.account("expired")

        result = self.run_helper("--workers", "2")

        self.assertEqual(result.returncode, 1)
        self.assertIn("alpha", result.stdout)
        self.assertIn("expired: need login again", result.stderr)
        self.assertNotIn("401", result.stderr)

    def test_empty_account_directory_is_reported(self):
        result = self.run_helper()

        self.assertEqual(result.returncode, 1)
        self.assertIn("没有找到已登录账号", result.stderr)

    def test_wrapper_dispatches_lslimit_to_helper(self):
        helper = self.root / "limits-helper"
        helper.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$@\"\nexit 7\n"
        )
        helper.chmod(helper.stat().st_mode | stat.S_IXUSR)
        environment = os.environ.copy()
        environment.update(
            {
                "CODEX_ACCOUNTS_HOME": str(self.accounts),
                "CODEX_ACCOUNT_LIMITS_BIN": str(helper),
                "PATH": f"{self.root}:{environment.get('PATH', '')}",
            }
        )

        result = subprocess.run(
            [str(BIN / "codex-account"), "--lslimit"],
            env=environment,
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 7)
        self.assertIn("--accounts-home", result.stdout)
        self.assertIn(str(self.accounts), result.stdout)
        self.assertIn("--codex-bin", result.stdout)
        self.assertIn(str(self.codex), result.stdout)


if __name__ == "__main__":
    unittest.main()
