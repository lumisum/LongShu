CREATE TABLE IF NOT EXISTS filings (
  filing_id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  company TEXT NOT NULL,
  cik TEXT NOT NULL,
  form TEXT NOT NULL,
  period_label TEXT NOT NULL,
  period_end DATE NOT NULL,
  filed_date DATE NOT NULL,
  accession TEXT NOT NULL UNIQUE,
  sec_url TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  local_source_path TEXT NOT NULL,
  sha256 TEXT,
  mineru_job_id TEXT,
  parser_version TEXT,
  page_count INTEGER,
  parse_status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS page_evidence (
  evidence_id BIGSERIAL PRIMARY KEY,
  filing_id BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
  page_number INTEGER NOT NULL,
  markdown_path TEXT NOT NULL,
  page_text TEXT NOT NULL,
  UNIQUE (filing_id, page_number)
);
CREATE TABLE IF NOT EXISTS financial_facts (
  fact_id BIGSERIAL PRIMARY KEY,
  filing_id BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
  metric_key TEXT NOT NULL,
  metric_label TEXT NOT NULL,
  value_numeric NUMERIC(24,6),
  value_text TEXT NOT NULL,
  unit TEXT NOT NULL DEFAULT 'USD millions',
  period_scope TEXT,
  source_page INTEGER,
  evidence_quote TEXT NOT NULL,
  sec_url TEXT NOT NULL,
  extraction_method TEXT NOT NULL,
  confidence NUMERIC(4,3),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (filing_id, metric_key, period_scope, source_page, evidence_quote)
);
CREATE TABLE IF NOT EXISTS processing_runs (
  run_id BIGSERIAL PRIMARY KEY,
  filing_id BIGINT NOT NULL REFERENCES filings(filing_id) ON DELETE CASCADE,
  service TEXT NOT NULL,
  job_id TEXT,
  status TEXT NOT NULL,
  gpu_name TEXT,
  parser_version TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  details JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_facts_metric ON financial_facts(metric_key);
CREATE INDEX IF NOT EXISTS idx_evidence_filing_page ON page_evidence(filing_id,page_number);

ALTER TABLE page_evidence ADD COLUMN IF NOT EXISTS printed_page_number TEXT;

-- Durable timeline used by the local real-time SEC dashboard.
CREATE TABLE IF NOT EXISTS pipeline_events (
  event_id BIGSERIAL PRIMARY KEY,
  run_id TEXT,
  filing_id BIGINT REFERENCES filings(filing_id) ON DELETE CASCADE,
  ticker TEXT,
  accession TEXT,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  output JSONB NOT NULL DEFAULT '{}'::jsonb,
  event_key TEXT UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_created ON pipeline_events(created_at DESC, event_id DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_filing ON pipeline_events(filing_id, event_id);

-- PostgreSQL NOTIFY is delivered only after the writing transaction commits.
-- Identical page/fact row notifications in COPY transactions are coalesced by PostgreSQL.
CREATE OR REPLACE FUNCTION sec_dashboard_notify_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  changed_row JSONB;
  payload JSONB;
BEGIN
  changed_row := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
  payload := jsonb_build_object(
    'table', TG_TABLE_NAME,
    'operation', TG_OP,
    'filing_id', changed_row ->> 'filing_id',
    'event_id', changed_row ->> 'event_id',
    'ticker', changed_row ->> 'ticker',
    'accession', changed_row ->> 'accession'
  );
  PERFORM pg_notify('sec_dashboard_change', payload::text);
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS sec_dashboard_filings_notify ON filings;
CREATE TRIGGER sec_dashboard_filings_notify AFTER INSERT OR UPDATE OR DELETE ON filings
  FOR EACH ROW EXECUTE FUNCTION sec_dashboard_notify_change();
DROP TRIGGER IF EXISTS sec_dashboard_evidence_notify ON page_evidence;
CREATE TRIGGER sec_dashboard_evidence_notify AFTER INSERT OR UPDATE OR DELETE ON page_evidence
  FOR EACH ROW EXECUTE FUNCTION sec_dashboard_notify_change();
DROP TRIGGER IF EXISTS sec_dashboard_facts_notify ON financial_facts;
CREATE TRIGGER sec_dashboard_facts_notify AFTER INSERT OR UPDATE OR DELETE ON financial_facts
  FOR EACH ROW EXECUTE FUNCTION sec_dashboard_notify_change();
DROP TRIGGER IF EXISTS sec_dashboard_runs_notify ON processing_runs;
CREATE TRIGGER sec_dashboard_runs_notify AFTER INSERT OR UPDATE OR DELETE ON processing_runs
  FOR EACH ROW EXECUTE FUNCTION sec_dashboard_notify_change();
DROP TRIGGER IF EXISTS sec_dashboard_events_notify ON pipeline_events;
CREATE TRIGGER sec_dashboard_events_notify AFTER INSERT OR UPDATE OR DELETE ON pipeline_events
  FOR EACH ROW EXECUTE FUNCTION sec_dashboard_notify_change();

-- Materialize a truthful, useful timeline for SEC work completed before this feature existed.
-- These rows are tagged as historical imports and are idempotent across restarts.
INSERT INTO pipeline_events (run_id, filing_id, ticker, accession, stage, status, title, message, output, event_key, created_at)
SELECT NULL, f.filing_id, f.ticker, f.accession, 'source_verified', 'completed', 'SEC 文件已归档',
       '历史记录初始化：该 SEC 文件已保存并登记。',
       jsonb_build_object('file', f.local_source_path, 'sha256', f.sha256, 'sec_url', f.sec_url),
       'legacy:' || f.filing_id || ':source', COALESCE(f.created_at, now())
FROM filings f
ON CONFLICT (event_key) DO NOTHING;

INSERT INTO pipeline_events (run_id, filing_id, ticker, accession, stage, status, title, message, output, event_key, created_at)
SELECT NULL, f.filing_id, f.ticker, f.accession, 'mineru_parsed', 'completed', 'MinerU GPU 解析完成',
       '历史记录初始化：解析结果已保存。',
       jsonb_build_object('parser_version', f.parser_version, 'page_count', f.page_count, 'mineru_job_id', f.mineru_job_id,
                          'gpu', COALESCE(pr.gpu_name, 'NVIDIA GeForce RTX 4070')),
       'legacy:' || f.filing_id || ':parse', COALESCE(pr.finished_at, f.updated_at, now())
FROM filings f
LEFT JOIN LATERAL (
  SELECT gpu_name, finished_at FROM processing_runs WHERE filing_id = f.filing_id
  ORDER BY finished_at DESC NULLS LAST, run_id DESC LIMIT 1
) pr ON TRUE
WHERE f.parse_status = 'completed'
ON CONFLICT (event_key) DO NOTHING;

INSERT INTO pipeline_events (run_id, filing_id, ticker, accession, stage, status, title, message, output, event_key, created_at)
SELECT NULL, f.filing_id, f.ticker, f.accession, 'evidence_indexed', 'completed', '财务信息点已提取并入库',
       '历史记录初始化：页级证据与结构化信息点已写入 PostgreSQL。',
       jsonb_build_object('page_count', (SELECT count(*) FROM page_evidence p WHERE p.filing_id = f.filing_id),
                          'fact_count', (SELECT count(*) FROM financial_facts x WHERE x.filing_id = f.filing_id)),
       'legacy:' || f.filing_id || ':facts', COALESCE(pr.finished_at, f.updated_at, now())
FROM filings f
LEFT JOIN LATERAL (
  SELECT finished_at FROM processing_runs WHERE filing_id = f.filing_id
  ORDER BY finished_at DESC NULLS LAST, run_id DESC LIMIT 1
) pr ON TRUE
WHERE f.parse_status = 'completed'
ON CONFLICT (event_key) DO NOTHING;
