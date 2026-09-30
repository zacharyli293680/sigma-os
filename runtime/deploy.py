#!/usr/bin/env python3
"""
deploy.py — make the running interface match `main`.

There is no cloud to push to: the site is one process on this PC, started by
the SigmaOS-Interface task from this checkout's working tree (remote.py). So
"deploying" is bringing that tree up to date and restarting the process, with
the two things a hand-run of those steps forgets — checking that what came up
actually answers, and putting the old version back when it does not.

The steps, in order, each skipped when it has nothing to do:

    1. refuse unless on `main` with a clean tree (or --allow-dirty, see below)
    2. git fetch; fast-forward to origin/main (a no-op when local is ahead —
       a merge done here and not yet pushed is still what gets deployed)
    3. pip install -r  if interface/backend/requirements.txt changed
    4. npm ci          if interface/frontend/package-lock.json changed
    5. npm run build   if anything under interface/frontend/ changed, or dist/
                       is missing — the backend serves dist/ from disk
    6. restart the interface (remote.restart) and wait for the port to answer
    7. on failure: reset to the commit from before step 2, rebuild, restart,
       and say so — the site ends on the version that was working

**Why the clean-tree rule.** Rollback is `git reset --hard <before>`, which
would erase an uncommitted edit. So a dirty tree is refused by default, and
`--allow-dirty` deploys *without* a rollback: on failure it stops and reports.
The dev worktree (`sigma-os-dev`, CONTEXT §8) exists so that the live tree
has no reason to be dirty in the first place.

`--dry-run` prints the plan and touches nothing — not even the fetch.
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BACKEND = REPO / "interface" / "backend"
FRONTEND = REPO / "interface" / "frontend"
DIST = FRONTEND / "dist"
REQUIREMENTS = "interface/backend/requirements.txt"
LOCKFILE = "interface/frontend/package-lock.json"
FRONTEND_PREFIX = "interface/frontend/"


class DeployError(RuntimeError):
    pass


def git(*args, check=True) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120)
    if check and r.returncode != 0:
        raise DeployError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip()


def sh(argv, cwd: Path, what: str):
    """A build step. Output flows to the console — a deploy that hides npm's
    error is a deploy you debug twice."""
    print(f"-- {what}")
    r = subprocess.run(argv, cwd=str(cwd), shell=(argv[0] == "npm"), timeout=900)
    if r.returncode != 0:
        raise DeployError(f"{what} failed (exit {r.returncode})")


def changed(before: str, after: str) -> list:
    """Paths that differ between two commits, forward slashes."""
    if before == after:
        return []
    out = git("diff", "--name-only", before, after)
    return [p.strip() for p in out.splitlines() if p.strip()]


def preflight(allow_dirty: bool) -> str:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        raise DeployError(f"on '{branch}', not main - the live checkout deploys "
                          "main only; develop in the sigma-os-dev worktree")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty and not allow_dirty:
        raise DeployError("the working tree has uncommitted changes:\n"
                          + "\n".join("    " + l for l in dirty.splitlines())
                          + "\n  commit or stash them (rollback is `reset --hard`, "
                            "which would erase them), or pass --allow-dirty to "
                            "deploy with no rollback")
    return git("rev-parse", "HEAD")


def plan(before: str, after: str) -> list:
    """The build steps a change from `before` to `after` needs, as
    (what, argv, cwd) — separated from running them so --dry-run and the
    tests see exactly what a real run would do."""
    delta = changed(before, after)
    steps = []
    py = BACKEND / ".venv" / "Scripts" / "python.exe"
    if REQUIREMENTS in delta:
        steps.append(("pip install -r requirements.txt",
                      [str(py), "-m", "pip", "install", "-q", "-r", "requirements.txt"],
                      BACKEND))
    if LOCKFILE in delta:
        steps.append(("npm ci", ["npm", "ci", "--silent"], FRONTEND))
    if any(p.startswith(FRONTEND_PREFIX) for p in delta) or not DIST.is_dir():
        steps.append(("npm run build", ["npm", "run", "build", "--silent"], FRONTEND))
    return steps


def run_steps(steps):
    for what, argv, cwd in steps:
        sh(argv, cwd, what)


def deploy(allow_dirty=False, dry_run=False, restart=None, fetch=True) -> int:
    import remote
    restart = restart or remote.restart
    before = preflight(allow_dirty)
    if dry_run:
        # Look, don't touch: even the fetch stays out of a dry run, so the
        # plan is computed against what origin/main was last seen to be.
        after = git("rev-parse", "origin/main", check=False) or before
        print(f"main {before[:8]} -> origin/main {after[:8]}"
              + ("  (already there)" if before == after else ""))
        steps = plan(before, after) or []
        for what, _, _ in steps:
            print(f"  would: {what}")
        print("  would: restart the interface and wait for it")
        return 0

    if fetch:
        git("fetch", "-q", "origin")
        git("merge", "--ff-only", "origin/main")
    after = git("rev-parse", "HEAD")
    print(f"main {before[:8]} -> {after[:8]}"
          + ("  (already current; restarting)" if before == after else ""))
    try:
        run_steps(plan(before, after))
        if not restart():
            raise DeployError("the interface did not answer after restart")
    except DeployError as e:
        print(f"deploy FAILED: {e}", file=sys.stderr)
        if allow_dirty or before == after:
            print("  no rollback (nothing to roll back to, or --allow-dirty); "
                  "the site may be down - see runtime/ui.log", file=sys.stderr)
            return 1
        print(f"  rolling back to {before[:8]}", file=sys.stderr)
        git("reset", "-q", "--hard", before)
        run_steps(plan(after, before))
        ok = restart()
        print(f"  rolled back; interface {'up' if ok else 'STILL DOWN - see runtime/ui.log'}",
              file=sys.stderr)
        return 1
    print(f"deployed {after[:8]}: interface up")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Make the running interface match main.")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; touch nothing")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="deploy over uncommitted changes (no rollback)")
    ap.add_argument("--no-fetch", action="store_true",
                    help="deploy what is checked out without asking origin")
    a = ap.parse_args(argv)
    try:
        return deploy(allow_dirty=a.allow_dirty, dry_run=a.dry_run, fetch=not a.no_fetch)
    except DeployError as e:
        print(f"deploy: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
