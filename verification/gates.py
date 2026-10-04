"""Verification gates for a proposed patch. The AI never declares its own work successful.

Used in two places with identical logic:
  * the control plane, immediately after a worker submits a patch (fast feedback)
  * GitHub Actions on the patch branch (adds container, IaC and load gates)

Gates: scope -> dependencies -> secrets -> lint -> SAST -> tests. All must pass.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SECRET_PATTERNS = [
    re.compile(r"(A3T[A-Z0-9]|AKIA|ASIA)[A-Z0-9]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(password|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
]
DEPENDENCY_FILES = ("requirements.txt", "requirements-dev.txt", "pyproject.toml")


def changed_paths(diff: str) -> list[str]:
    """Every path a unified diff touches (old and new names, renames included)."""
    paths: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"diff --git a/(\S+) b/(\S+)", line)
            if match:
                paths.update(match.groups())
        elif line.startswith(("--- a/", "+++ b/")):
            paths.add(line[6:].strip())
        elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            paths.add(line.split(" ", 2)[2].strip())
    paths.discard("/dev/null")
    return sorted(paths)


def glob_match(pattern: str, path: str) -> bool:
    """Same semantics as the policy's glob.match with '/' as separator, for our patterns."""
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-2])
    return path == pattern


def _run(cmd: list[str], cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed argument lists, no shell
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )


def gate(name: str, passed: bool, details: str, started: float) -> dict:
    return {
        "gate": name,
        "passed": passed,
        "details": details[-1500:],
        "seconds": round(time.monotonic() - started, 2),
    }


def verify_patch(
    repo: Path,
    base_ref: str,
    diff: str,
    allowed: list[str],
    never_writable: list[str],
    run_tests: bool = True,
) -> dict:
    paths = changed_paths(diff)
    results: list[dict] = []

    started = time.monotonic()
    outside = [p for p in paths if not any(glob_match(a, p) for a in allowed)]
    guarded = [p for p in paths if any(glob_match(n, p) for n in never_writable)]
    bad = sorted(set(outside + guarded + [p for p in paths if ".." in p or p.startswith("/")]))
    detail = f"out of scope: {bad}" if bad else f"{len(paths)} paths inside scope"
    results.append(gate("scope", not bad and bool(paths), detail, started))

    started = time.monotonic()
    deps = [p for p in paths if p.endswith(DEPENDENCY_FILES)]
    detail = f"dependency files changed (human review): {deps}" if deps else "no dependency changes"
    results.append(gate("dependencies", not deps, detail, started))

    started = time.monotonic()
    added = [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    leaks = [line.strip()[:60] for line in added if any(p.search(line) for p in SECRET_PATTERNS)]
    results.append(gate("secrets", not leaks, f"possible secrets: {leaks}" if leaks
                        else "no secret patterns in added lines", started))  # fmt: skip

    if not all(r["passed"] for r in results):
        return {"passed": False, "paths": paths, "gates": results}

    workdir = Path(tempfile.mkdtemp(prefix="safeops-verify-"))
    try:
        checkout = workdir / "repo"
        clone = _run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(repo), str(checkout)], workdir
        )
        if clone.returncode != 0:
            results.append(gate("checkout", False, clone.stderr, time.monotonic()))
            return {"passed": False, "paths": paths, "gates": results}
        _run(["git", "checkout", "--quiet", base_ref], checkout)
        (workdir / "patch.diff").write_text(diff, encoding="utf-8")
        started = time.monotonic()
        applied = _run(
            ["git", "apply", "--whitespace=nowarn", str(workdir / "patch.diff")], checkout
        )
        detail = applied.stderr or "patch applies cleanly"
        results.append(gate("apply", applied.returncode == 0, detail, started))
        if applied.returncode != 0:
            return {"passed": False, "paths": paths, "gates": results}

        python_files = [p for p in paths if p.endswith(".py") and (checkout / p).exists()]
        started = time.monotonic()
        if python_files:
            lint = _run([sys.executable, "-m", "ruff", "check", *python_files], checkout)
            results.append(gate("lint", lint.returncode == 0, lint.stdout or "ruff clean", started))
        sast_targets = [p for p in python_files if "/tests/" not in p]
        started = time.monotonic()
        if sast_targets:
            bandit = [sys.executable, "-m", "bandit", "-q", "-ll", "-f", "json", *sast_targets]
            sast = _run(bandit, checkout)
            try:
                issues = json.loads(sast.stdout or "{}").get("results", [])
            except json.JSONDecodeError:
                issues = [{"issue_text": sast.stderr or "bandit failed"}]
            summary = "; ".join(
                f"{i.get('test_id', '?')} {i.get('issue_text', '')}"[:120] for i in issues
            )
            results.append(gate("sast", not issues, summary or "no medium/high findings", started))
        if run_tests:
            started = time.monotonic()
            pytest = [sys.executable, "-m", "pytest", "app", "-q", "-p", "no:cacheprovider", "-x"]
            tests = _run(pytest, checkout)
            results.append(
                gate("tests", tests.returncode == 0, tests.stdout + tests.stderr, started)
            )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return {"passed": all(r["passed"] for r in results), "paths": paths, "gates": results}
