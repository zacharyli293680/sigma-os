#!/usr/bin/env python3
"""
remote.py — the doctor's view of the tailnet surface.

Every subprocess and socket is stubbed: the check must describe the four
states a remote deployment can be in without touching schtasks, tailscale or
the port, because the suite runs on machines that have none of them.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401
import remote     # noqa: E402

SERVE = """https://win-2mhekgnh77i.tailffbbc7.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:8787

"""
FUNNEL = SERVE.replace("(tailnet only)", "(Funnel on)")
OTHER_PORT = SERVE.replace("8787", "3000")


class Parse(unittest.TestCase):
    def test_proxied_url(self):
        self.assertEqual(remote.proxied_url(SERVE),
                         "https://win-2mhekgnh77i.tailffbbc7.ts.net")

    def test_other_port_is_not_ours(self):
        self.assertIsNone(remote.proxied_url(OTHER_PORT))

    def test_empty_and_none(self):
        self.assertIsNone(remote.proxied_url(""))
        self.assertIsNone(remote.proxied_url(None))

    def test_funnel(self):
        self.assertFalse(remote.funnel_on(SERVE))
        self.assertTrue(remote.funnel_on(FUNNEL))


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved = (remote.HERE, remote.serve_status, remote.task_installed,
                       remote.interface_up)
        remote.HERE = Path(self.tmp.name)
        self.stub(status=SERVE, task=True, up=True, login="zach@example.com")

    def tearDown(self):
        (remote.HERE, remote.serve_status, remote.task_installed,
         remote.interface_up) = self._saved
        self.tmp.cleanup()

    def stub(self, status, task, up, login):
        remote.serve_status = lambda: status
        remote.task_installed = lambda: task
        remote.interface_up = lambda port=remote.PORT: up
        cfg = remote.HERE / "privacy.config.json"
        if login is None:
            cfg.unlink(missing_ok=True)
        else:
            cfg.write_text(json.dumps({"remote_login": login}), encoding="utf-8")

    def run_check(self):
        out = []
        remote.check(out)
        return out

    def levels(self, out):
        return [lv for lv, _, _ in out]

    def test_no_tailscale_says_nothing(self):
        self.stub(status=None, task=False, up=False, login=None)
        self.assertEqual(self.run_check(), [])

    def test_proxy_off_is_ok(self):
        self.stub(status="", task=False, up=False, login=None)
        out = self.run_check()
        self.assertEqual(self.levels(out), ["ok"])

    def test_all_good_is_one_info(self):
        out = self.run_check()
        self.assertEqual(self.levels(out), ["info"])
        self.assertIn("zach@example.com", out[0][1])

    def test_missing_login_alerts(self):
        self.stub(status=SERVE, task=True, up=True, login=None)
        out = self.run_check()
        self.assertEqual(self.levels(out), ["alert"])
        self.assertIn("remote_login", out[0][2])

    def test_funnel_alerts_first(self):
        self.stub(status=FUNNEL, task=True, up=True, login="zach@example.com")
        out = self.run_check()
        self.assertEqual(out[0][0], "alert")
        self.assertIn("funnel", out[0][1].lower())

    def test_task_missing_and_down_are_todos(self):
        self.stub(status=SERVE, task=False, up=False, login="zach@example.com")
        out = self.run_check()
        self.assertEqual(self.levels(out), ["info", "todo", "todo"])
        self.assertIn("--install-schedule", out[1][2])


class Command(unittest.TestCase):
    def test_schedule_cmd_names_the_pieces(self):
        cmd = remote.schedule_cmd(8787)
        for piece in ("uvicorn app:app", "--port 8787", "-AtLogOn",
                      "-WindowStyle Hidden", remote.TASK_NAME, "ui.log",
                      "-ExecutionTimeLimit"):
            self.assertIn(piece, cmd)


if __name__ == "__main__":
    unittest.main()
