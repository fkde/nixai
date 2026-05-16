from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_import_smoke(code: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env["XDG_DATA_HOME"] = str(tmp_path / "data")
    env["PYTHONPYCACHEPREFIX"] = str(tmp_path / "pycache")
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def test_main_app_imports_in_fresh_process(tmp_path: Path) -> None:
    result = run_import_smoke(
        "\n".join(
            [
                "import app.main",
                "from uvicorn.importer import import_from_string",
                "loaded = import_from_string('app.main:app')",
                "print(loaded.title)",
            ]
        ),
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "NixAI" in result.stdout


def test_agentic_runner_and_workflow_nodes_import_in_both_orders(tmp_path: Path) -> None:
    result = run_import_smoke(
        "\n".join(
            [
                "import app.agentic_runner",
                "import app.workflows.nodes",
                "import app.workflows.executor",
                "print('ok')",
            ]
        ),
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout

    reverse = run_import_smoke(
        "\n".join(
            [
                "import app.workflows.nodes",
                "import app.agentic_runner",
                "import app.main",
                "print('ok')",
            ]
        ),
        tmp_path,
    )
    assert reverse.returncode == 0, reverse.stderr
    assert "ok" in reverse.stdout
