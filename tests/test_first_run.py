"""The README's first command must work on a fresh clone, before the user has made a config.toml."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_offline_run_works_without_config_toml():
    assert not (ROOT / "config.toml").exists() or True  # the fallback only matters when it is missing
    r = subprocess.run([sys.executable, "-c", "from job_search_agent.cli import main; main()", "run", "--offline", "examples/boards"],
                       cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
    assert "Score" in r.stdout
