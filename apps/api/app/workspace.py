import os
import subprocess
import zipfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[3]
raw_root = os.environ.get("JOB_WORKSPACE_ROOT", "workspaces")
WORKSPACE_ROOT = Path(raw_root) if Path(raw_root).is_absolute() else PROJECT_ROOT / "workspaces"


class WorkspaceError(Exception):
    pass


def job_dir(job_id):
    dest = (WORKSPACE_ROOT / str(job_id)).resolve()
    if WORKSPACE_ROOT.resolve() not in dest.parents:
        raise WorkspaceError("bad job_id")
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    return dest


def clone_repo(job_id, repo_url, branch="main"):
    dest = job_dir(job_id)
    if dest.exists() and (dest / ".git").exists():
        return str(dest)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch, repo_url, str(dest)],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceError("clone timed out") from exc
    if result.returncode != 0:
        raise WorkspaceError(result.stderr.strip() or "clone failed")
    return str(dest)


def save_upload_zip(job_id, zip_path):
    dest = job_dir(job_id)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            target = (dest / name).resolve()
            if dest not in target.parents and target != dest:
                raise WorkspaceError("unsafe zip path")
        zf.extractall(dest)
    return str(dest)
