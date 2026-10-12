import os
import time

from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tools.git import CloneError, clone_repo

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]


def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


while True:
    with db() as conn:
        created = conn.execute(
            """
            SELECT id FROM jobs
            WHERE status = 'created'
            ORDER BY created_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ).fetchone()
        if created:
            conn.execute(
                "UPDATE jobs SET status = 'accepted', updated_at = now() WHERE id = %s",
                (created["id"],),
            )
            conn.execute(
                "INSERT INTO checkpoints (job_id, step, state) VALUES (%s, %s, %s)",
                (created["id"], "accepted", Jsonb({})),
            )
            conn.commit()

        accepted = conn.execute(
            """
            SELECT id, repo_url, branch FROM jobs
            WHERE status = 'accepted'
            ORDER BY created_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ).fetchone()

    if accepted:
        try:
            result = clone_repo(accepted["id"], accepted["repo_url"], accepted["branch"])
            with db() as conn:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'running', current_stage = 'intake', updated_at = now()
                    WHERE id = %s
                    """,
                    (accepted["id"],),
                )
                conn.execute(
                    "INSERT INTO checkpoints (job_id, step, state) VALUES (%s, %s, %s)",
                    (accepted["id"], "cloned", Jsonb(result)),
                )
                conn.commit()
        except CloneError as exc:
            with db() as conn:
                conn.execute(
                    "INSERT INTO checkpoints (job_id, step, state) VALUES (%s, %s, %s)",
                    (accepted["id"], "clone_failed", Jsonb({"detail": str(exc)})),
                )
                conn.commit()

    time.sleep(2)
