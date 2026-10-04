"""The Codex runner end to end, with a stand-in 'codex' program that edits code like a model would.

What is real here: snapshot transfer, safe extraction, Git bookkeeping, the gateway, the
policy and the verification gates. What is simulated: the model's reasoning.
"""

import stat
import sys

from safeops_worker import codex_runner

FAKE_CODEX = """#!{python}
import pathlib, sys
args = sys.argv[1:]
assert args[0] == "exec" and "--dangerously-bypass-approvals-and-sandbox" in args
out = pathlib.Path(args[args.index("-o") + 1])
service = pathlib.Path("app/services/inventory/service.py")
service.write_text(service.read_text().replace("_PRICE_CACHE[quantity]", "_PRICE_CACHE[sku]"))
assert pathlib.Path("AGENTS.md").exists(), "worker instructions must be present"
out.write_text("Root cause: price cache read with the quantity instead of the SKU.")
"""


def test_codex_runner_submits_a_verified_patch(lab, tmp_path):
    [incident_id] = lab.alert()
    fake = tmp_path / "codex"
    fake.write_text(FAKE_CODEX.format(python=sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    result = codex_runner.run(lab.worker(incident_id), tmp_path / "work", str(fake))
    assert result["result"] == "submitted", result
    incident = lab.incident(incident_id)
    assert incident["patch"]["paths"] == ["app/services/inventory/service.py"]  # no AGENTS.md
    assert incident["status"] == "VERIFIED"
    assert "Root cause" in incident["patch"]["summary"]


def test_snapshot_extraction_refuses_path_traversal(tmp_path):
    import base64
    import io
    import tarfile

    import pytest

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 4
        archive.addfile(info, io.BytesIO(b"evil"))
    snapshot = {"archive_b64": base64.b64encode(buffer.getvalue()).decode()}
    with pytest.raises(tarfile.OutsideDestinationError):
        codex_runner.extract_snapshot(snapshot, tmp_path / "repo")
    assert not (tmp_path / "escape.txt").exists()
