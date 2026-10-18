CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS doc_bundles (
    bundle_id UUID PRIMARY KEY,
    source_url TEXT NOT NULL,
    project_title TEXT,
    notice_html_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS doc_attachments (
    attachment_id UUID PRIMARY KEY,
    bundle_id UUID NOT NULL REFERENCES doc_bundles(bundle_id) ON DELETE CASCADE,
    attachment_url TEXT NOT NULL,
    file_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    sha256 TEXT,
    mime_type TEXT,
    page_count INTEGER CHECK (page_count IS NULL OR page_count > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    attachment_id UUID NOT NULL REFERENCES doc_attachments(attachment_id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL CHECK (page_no > 0),
    bbox JSONB NOT NULL CHECK (jsonb_typeof(bbox) = 'array' AND jsonb_array_length(bbox) = 4),
    text_content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS document_chunks_attachment_page_idx
    ON document_chunks (attachment_id, page_no);
CREATE INDEX IF NOT EXISTS document_chunks_text_search_idx
    ON document_chunks USING GIN (to_tsvector('simple', text_content));

CREATE TABLE IF NOT EXISTS extracted_facts (
    fact_id UUID PRIMARY KEY,
    bundle_id UUID NOT NULL REFERENCES doc_bundles(bundle_id) ON DELETE CASCADE,
    field_key TEXT NOT NULL,
    value_text TEXT NOT NULL,
    chunk_id TEXT NOT NULL REFERENCES document_chunks(chunk_id),
    page_no INTEGER NOT NULL CHECK (page_no > 0),
    exact_quote TEXT NOT NULL,
    verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS extracted_facts_bundle_idx
    ON extracted_facts (bundle_id, field_key);
