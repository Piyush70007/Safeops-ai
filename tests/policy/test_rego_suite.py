"""Runs the Rego unit tests (opa test) as part of pytest, so one command checks everything."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_policy_unit_tests_pass():
    binary = os.environ.get("OPA_BIN") or shutil.which("opa") or "opa"
    if not shutil.which(binary):
        pytest.skip("OPA binary not available")
    engine = ROOT / "automation" / "policy-engine"
    result = subprocess.run(  # noqa: S603
        [binary, "test", str(engine / "policies"), str(engine / "data")],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout
