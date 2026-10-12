import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from psycopg.types.json import Jsonb

from app.db import db
from app.intake import run_intake
from app.workspace import WorkspaceError, clone_repo, save_upload_zip

app = FastAPI()


class CreateCloneJob(BaseModel):
    repo_url: str
    branch: str = "main"


def finish_job(conn, job_id, path, step):
    counts = run_intake(conn, job_id, path)
    row = conn.execute(
        """
        UPDATE jobs
        SET status = 'running',
            current_stage = 'intake',
            workspace_path = %s,
            updated_at = now()
        WHERE id = %s
        RETURNING *
        """,
        (path, job_id),
    ).fetchone()
    conn.execute(
        "INSERT INTO checkpoints (job_id, step, state) VALUES (%s, %s, %s)",
        (job_id, step, Jsonb({"path": path, **counts})),
    )
    return {**row, **counts}


def fail_job(conn, job_id, step, detail):
    conn.execute(
        """
        UPDATE jobs
        SET status = 'failed', updated_at = now()
        WHERE id = %s
        """,
        (job_id,),
    )
    conn.execute(
        "INSERT INTO checkpoints (job_id, step, state) VALUES (%s, %s, %s)",
        (job_id, step, Jsonb({"detail": detail})),
    )


@app.post("/jobs")
def create_clone_job(body: CreateCloneJob):
    with db() as conn:
        job = conn.execute(
            """
            INSERT INTO jobs (repo_url, branch, source_type, status)
            VALUES (%s, %s, 'clone', 'cloning')
            RETURNING *
            """,
            (body.repo_url, body.branch),
        ).fetchone()
        job_id = job["id"]
    try:
        path = clone_repo(job_id, body.repo_url, body.branch)
    except WorkspaceError as exc:
        with db() as conn:
            fail_job(conn, job_id, "clone_failed", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with db() as conn:
        return finish_job(conn, job_id, path, "cloned")


@app.post("/jobs/upload")
def create_upload_job(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="upload a .zip file")
    with db() as conn:
        job = conn.execute(
            """
            INSERT INTO jobs (repo_url, branch, source_type, status)
            VALUES (NULL, 'local', 'upload', 'uploading')
            RETURNING *
            """
        ).fetchone()
        job_id = job["id"]
    tmp = Path(tempfile.mkdtemp()) / "upload.zip"
    try:
        raw = file.file.read()
        if len(raw) > 50 * 1024 * 1024:
            raise WorkspaceError("file too large")
        tmp.write_bytes(raw)
        path = save_upload_zip(job_id, tmp)
    except WorkspaceError as exc:
        with db() as conn:
            fail_job(conn, job_id, "upload_failed", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if tmp.exists():
            tmp.unlink()
    with db() as conn:
        return finish_job(conn, job_id, path, "uploaded")


@app.get("/jobs/{job_id}")
def get_job(job_id: UUID):
    with db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="job not found")
        file_count = conn.execute(
            "SELECT count(*) AS n FROM files WHERE job_id = %s", (job_id,)
        ).fetchone()["n"]
        secret_count = conn.execute(
            "SELECT count(*) AS n FROM secret_findings WHERE job_id = %s", (job_id,)
        ).fetchone()["n"]
    return {**row, "file_count": file_count, "secret_count": secret_count}


@app.get("/jobs/{job_id}/files")
def list_files(job_id: UUID):
    with db() as conn:
        job = conn.execute("SELECT id FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return conn.execute(
            "SELECT path, size_bytes, language, label FROM files WHERE job_id = %s ORDER BY path",
            (job_id,),
        ).fetchall()


@app.get("/jobs/{job_id}/secrets")
def list_secrets(job_id: UUID):
    with db() as conn:
        job = conn.execute("SELECT id FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return conn.execute(
            "SELECT file_path, line_no, kind, masked FROM secret_findings WHERE job_id = %s ORDER BY file_path, line_no",
            (job_id,),
        ).fetchall()
