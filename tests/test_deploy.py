#!/usr/bin/env python3
"""
deploy.py — the live checkout catching up with main.

Everything runs against a scratch repo with its own bare `origin`; the build
steps and the restart are recorded rather than run. What matters is the
control flow: what is refused, which steps a change needs, and that a failed
restart puts the previous commit back — including its build.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runtime"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import isolation  # noqa: E402,F401
import deploy     # noqa: E402
import remote     # noqa: E402


def git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                       text=True, encoding="utf-8", check=True)
    return r.stdout.strip()


class DeployBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin = root / "origin.git"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.live = root / "live"
        git(root, "clone", "-q", str(self.origin), str(self.live))
        git(self.live, "config", "user.email", "t@t"); git(self.live, "config", "user.name", "t")
        self.commit("init", {"README.md": "hi\n",
                             "interface/backend/requirements.txt": "fastapi\n",
                             "interface/frontend/package-lock.json": "{}\n",
                             "interface/frontend/src/app.tsx": "a\n"})
        git(self.live, "push", "-q", "-u", "origin", "main")
        # A second clone plays "the dev worktree": commits pushed from here are
        # what the live checkout has to catch up with.
        self.dev = root / "dev"
        git(root, "clone", "-q", str(self.origin), str(self.dev))
        git(self.dev, "config", "user.email", "t@t"); git(self.dev, "config", "user.name", "t")

        self._saved = (deploy.REPO, deploy.BACKEND, deploy.FRONTEND, deploy.DIST, deploy.sh)
        deploy.REPO = self.live
        deploy.BACKEND = self.live / "interface" / "backend"
        deploy.FRONTEND = self.live / "interface" / "frontend"
        deploy.DIST = deploy.FRONTEND / "dist"
        deploy.DIST.mkdir(parents=True)
        self.steps = []
        deploy.sh = lambda argv, cwd, what: self.steps.append(what)
        self.restarts = []

    def tearDown(self):
        (deploy.REPO, deploy.BACKEND, deploy.FRONTEND, deploy.DIST, deploy.sh) = self._saved
        self.tmp.cleanup()

    def commit(self, msg, files, cwd=None):
        cwd = cwd or self.live
        for rel, text in files.items():
            p = cwd / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        git(cwd, "add", "-A")
        git(cwd, "commit", "-q", "-m", msg)
        return git(cwd, "rev-parse", "HEAD")

    def push_from_dev(self, msg, files):
        sha = self.commit(msg, files, cwd=self.dev)
        git(self.dev, "push", "-q", "origin", "main")
        return sha

    def restart_ok(self):
        self.restarts.append(True)
        return True

    def restart_fail_once(self):
        # The new version fails to come up; the rollback's restart succeeds.
        ok = bool(self.restarts)
        self.restarts.append(ok)
        return ok

    def head(self):
        return git(self.live, "rev-parse", "HEAD")


class Refusals(DeployBase):
    def test_not_on_main(self):
        git(self.live, "checkout", "-q", "-b", "feature")
        with self.assertRaises(deploy.DeployError) as cm:
            deploy.deploy(restart=self.restart_ok)
        self.assertIn("not main", str(cm.exception))

    def test_dirty_tree_refused(self):
        (self.live / "README.md").write_text("edited\n", encoding="utf-8")
        with self.assertRaises(deploy.DeployError) as cm:
            deploy.deploy(restart=self.restart_ok)
        self.assertIn("README.md", str(cm.exception))
        self.assertEqual(self.restarts, [])

    def test_untracked_files_do_not_count_as_dirty(self):
        (self.live / "scratch.txt").write_text("x", encoding="utf-8")
        self.assertEqual(deploy.deploy(restart=self.restart_ok), 0)


class HappyPaths(DeployBase):
    def test_nothing_new_just_restarts(self):
        rc = deploy.deploy(restart=self.restart_ok)
        self.assertEqual(rc, 0)
        self.assertEqual(self.steps, [])
        self.assertEqual(self.restarts, [True])

    def test_frontend_change_fast_forwards_and_builds(self):
        sha = self.push_from_dev("ui", {"interface/frontend/src/app.tsx": "b\n"})
        rc = deploy.deploy(restart=self.restart_ok)
        self.assertEqual(rc, 0)
        self.assertEqual(self.head(), sha)
        self.assertEqual(self.steps, ["npm run build"])

    def test_backend_only_change_needs_no_build(self):
        self.push_from_dev("py", {"runtime/x.py": "pass\n"})
        deploy.deploy(restart=self.restart_ok)
        self.assertEqual(self.steps, [])

    def test_requirements_and_lockfile_changes(self):
        self.push_from_dev("deps", {"interface/backend/requirements.txt": "fastapi\nhttpx\n",
                                    "interface/frontend/package-lock.json": "{ }\n"})
        deploy.deploy(restart=self.restart_ok)
        self.assertEqual(self.steps, ["pip install -r requirements.txt", "npm ci",
                                      "npm run build"])

    def test_missing_dist_forces_a_build(self):
        deploy.DIST.rmdir()
        deploy.deploy(restart=self.restart_ok)
        self.assertEqual(self.steps, ["npm run build"])

    def test_local_ahead_of_origin_deploys_local(self):
        # A merge done in the live checkout and not yet pushed is still main.
        sha = self.commit("local merge", {"runtime/y.py": "pass\n"})
        rc = deploy.deploy(restart=self.restart_ok)
        self.assertEqual(rc, 0)
        self.assertEqual(self.head(), sha)


class Rollback(DeployBase):
    def test_failed_restart_rolls_back_and_rebuilds(self):
        before = self.head()
        self.push_from_dev("bad ui", {"interface/frontend/src/app.tsx": "broken\n"})
        rc = deploy.deploy(restart=self.restart_fail_once)
        self.assertEqual(rc, 1)
        self.assertEqual(self.head(), before)
        # Built the new version, then rebuilt the old one after the reset.
        self.assertEqual(self.steps, ["npm run build", "npm run build"])
        self.assertEqual(self.restarts, [False, True])

    def test_allow_dirty_means_no_rollback(self):
        before = self.head()
        (self.live / "README.md").write_text("edited\n", encoding="utf-8")
        after = self.push_from_dev("ui", {"interface/frontend/src/app.tsx": "b\n"})
        rc = deploy.deploy(allow_dirty=True, restart=self.restart_fail_once)
        self.assertEqual(rc, 1)
        self.assertEqual(self.head(), after)          # left where it failed
        self.assertNotEqual(self.head(), before)
        self.assertEqual((self.live / "README.md").read_text(encoding="utf-8"), "edited\n")
        self.assertEqual(self.restarts, [False])


class DryRun(DeployBase):
    def test_dry_run_touches_nothing(self):
        before = self.head()
        self.push_from_dev("ui", {"interface/frontend/src/app.tsx": "b\n"})
        rc = deploy.deploy(dry_run=True, restart=self.restart_ok)
        self.assertEqual(rc, 0)
        self.assertEqual(self.head(), before)
        self.assertEqual(self.steps, [])
        self.assertEqual(self.restarts, [])
        # Not even a fetch: origin/main is still what was last seen.
        self.assertEqual(git(self.live, "rev-parse", "origin/main"), before)


class ListeningPid(unittest.TestCase):
    def test_parses_netstat(self):
        text = ("  TCP    127.0.0.1:8787         0.0.0.0:0              LISTENING       46864\n"
                "  TCP    127.0.0.1:8788         0.0.0.0:0              LISTENING       11\n"
                "  TCP    127.0.0.1:8787         127.0.0.1:5000         ESTABLISHED     46864\n")
        saved = remote.subprocess.run
        class R: stdout = text
        remote.subprocess.run = lambda *a, **k: R()
        try:
            self.assertEqual(remote.listening_pid(8787), 46864)
            self.assertEqual(remote.listening_pid(8788), 11)
            self.assertIsNone(remote.listening_pid(9999))
        finally:
            remote.subprocess.run = saved


if __name__ == "__main__":
    unittest.main()
