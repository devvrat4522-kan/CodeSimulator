CREATE TABLE files (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  size_bytes BIGINT NOT NULL DEFAULT 0,
  content_hash TEXT,
  language TEXT,
  label TEXT NOT NULL,
  UNIQUE (job_id, path)
);

CREATE TABLE secret_findings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  file_path TEXT NOT NULL,
  line_no INTEGER,
  kind TEXT NOT NULL,
  masked TEXT NOT NULL
);
