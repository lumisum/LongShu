# SEC Filing Analysis

This project parses locally supplied SEC filing documents with MinerU, stores page evidence and extracted facts in PostgreSQL, and publishes processing progress through the Node.js dashboard.

## Local input data

Before running the pipeline, create filings.json in this directory. It is a local input manifest that identifies each filing and its source document. The manifest and downloaded SEC documents are excluded from Git because they are machine-specific project data.

The manifest is a JSON array. Each item includes the issuer ticker and name, SEC form and period, filing accession, source URLs, a source path relative to the LongShu root, and the source type. Keep source documents under Data/Finance/SEC/raw/.

## Local outputs

- Raw documents: Data/Finance/SEC/raw/{ticker}/{period}
- MinerU parse outputs and evidence: Data/Finance/SEC/parsed/
- PostgreSQL stores filing records, page evidence, extracted facts, and processing events.
- Redis stores task state under the secfilings: key prefix.

## Run

Run start-services.ps1 from the LongShu root to start Docker and the base service stacks. Then run start-nodejs.ps1 to start the Node.js dashboard at http://127.0.0.1:8090. Use stop-nodejs.ps1 and restart-nodejs.ps1 to manage only the dashboard process.

Run the SEC analysis job separately with python Projects/sec-filings-intel-glw/run_pipeline.py from the LongShu root. The local filings.json manifest and SEC documents must be present first.

See dashboard/README.md for dashboard setup and operations.
