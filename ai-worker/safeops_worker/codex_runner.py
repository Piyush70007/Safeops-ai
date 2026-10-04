"""Runs OpenAI Codex inside the ephemeral worker container.

Flow: brief -> repository snapshot (no Git credentials) -> safe extraction -> codex exec ->
git diff -> submit_patch through the gateway. The worker never decides success.

Why --dangerously-bypass-approvals-and-sandbox: Codex's documentation recommends, for
automation, to make the container itself the sandbox. Here the container has no credentials,
a read-only root filesystem, dropped capabilities and egress limited by NetworkPolicy, and
every consequential action goes through the policy-checked gateway. The authority is
outside the model, not in Codex's approval prompt.
"""

import base64
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from safeops_worker.client import GatewayClient

SKILLS = Path(os.environ.get("SAFEOPS_SKILLS", Path(__file__).resolve().parents[1] / "skills"))


def extract_snapshot(snapshot: dict, target: Path) -> None:
    data = base64.b64decode(snapshot["archive_b64"])
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        archive.extractall(target, filter="data")  # blocks absolute paths, '..' and links out


def git(repo: Path, *args: str) -> str:
    identity = {"NAME": "safeops-worker", "EMAIL": "worker@safeops"}
    env = {**os.environ, **{f"GIT_{who}_{k}": v for who in ("AUTHOR", "COMMITTER")
                            for k, v in identity.items()}}  # fmt: skip
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True,
                          check=True).stdout  # fmt: skip


def build_prompt(brief: dict) -> str:
    template = (SKILLS / "prompt.md").read_text(encoding="utf-8")
    return template.replace("{{BRIEF_JSON}}", json.dumps(brief, indent=2))


def run(client: GatewayClient, workdir: Path, codex_bin: str = "codex", model: str = "") -> dict:
    status, brief = client.call("get_incident_brief")
    if status != 200:
        return {"result": "no_access", "body": brief}
    status, snapshot = client.call("get_repository_snapshot")
    if status != 200:
        return {"result": "no_snapshot", "body": snapshot}
    repo = workdir / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    extract_snapshot(snapshot["result"], repo)
    (repo / "AGENTS.md").write_text((SKILLS / "AGENTS.md").read_text(encoding="utf-8"))
    git(repo, "init", "--quiet")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "incident base")

    summary_file = workdir / "codex-summary.md"
    cmd = [codex_bin, "exec", "--dangerously-bypass-approvals-and-sandbox",
           "-o", str(summary_file), build_prompt(brief["result"])]  # fmt: skip
    if model:
        cmd[2:2] = ["-m", model]
    codex = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=1500, check=False)

    git(repo, "add", "-A")
    diff = git(repo, "diff", "--cached", "HEAD")
    if not diff.strip():
        return {"result": "no_change", "codex_exit": codex.returncode, "log": codex.stdout[-2000:]}
    summary = summary_file.read_text(encoding="utf-8")[:4000] if summary_file.exists() else ""
    status, body = client.call("submit_patch", diff=diff, summary=summary or "patch from Codex")
    return {"result": "submitted" if status == 200 else "patch_denied", "body": body,
            "codex_exit": codex.returncode}  # fmt: skip


def main() -> int:
    workdir = Path(os.environ.get("WORKDIR", "/workspace"))
    result = run(GatewayClient(), workdir, os.environ.get("CODEX_BIN", "codex"),
                 os.environ.get("CODEX_MODEL", ""))  # fmt: skip
    print(json.dumps({k: v for k, v in result.items() if k != "log"}, indent=2, default=str))
    return 0 if result["result"] == "submitted" else 1


if __name__ == "__main__":
    sys.exit(main())
