"""The Docker launcher must start the worker hardened: read-only, tmpfs workspace, no caps."""

from automation.controlplane import adapters


def test_docker_worker_is_started_hardened(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]

        class Result:
            returncode, stderr = 0, ""

        return Result()

    monkeypatch.setattr(adapters.subprocess, "run", fake_run)
    adapters.DockerLauncher("worker:test", "http://gw").launch("INC-1", "secret-token")
    cmd = captured["cmd"]
    pairs = list(zip(cmd, cmd[1:], strict=False))
    assert "--read-only" in cmd
    assert ("--tmpfs", "/workspace:size=1g,uid=10001") in pairs
    assert ("--tmpfs", "/tmp:size=512m") in pairs  # noqa: S108
    assert ("--cap-drop", "ALL") in pairs
    assert "secret-token" not in " ".join(cmd)  # token passed via environment, not argv
    assert captured["env"]["SAFEOPS_TOKEN"] == "secret-token"
