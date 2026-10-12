import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
raw_root = os.environ.get("JOB_WORKSPACE_ROOT", "workspaces")
WORKSPACE_ROOT = Path(raw_root) if Path(raw_root).is_absolute() else PROJECT_ROOT / "workspaces"


class CloneError(Exception):
    pass


def clone_repo(job_id, repo_url, branch="main"):
    dest = (WORKSPACE_ROOT / str(job_id)).resolve()
    if WORKSPACE_ROOT.resolve() not in dest.parents:
        raise CloneError("bad job_id")
    if dest.exists() and (dest / ".git").exists():
        return {"ok": True, "path": str(dest)}
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", branch, repo_url, str(dest)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise CloneError(result.stderr.strip() or "clone failed")
    return {"ok": True, "path": str(dest)}
