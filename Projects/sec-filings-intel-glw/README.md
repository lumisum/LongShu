# SEC Filing Analysis

This project parses locally supplied SEC filing documents with MinerU, stores page evidence and extracted facts in PostgreSQL, and publishes processing progress through the Node.js dashboard.

## Local input data

Before running the pipeline, create filings.json in this directory. It is a local input manifest that identifies each filing and its source document. The manifest and all downloaded SEC documents are excluded from Git because they are machine-specific project data.

The manifest uses a JSON array. Each item includes the issuer ticker and name, SEC form and period, filing accession, source URLs, a source path relative to the LongShu root, and the source type. Keep source documents under Data/Finance/SEC/raw/.

## Local outputs

- Raw documents: Data/Finance/SEC/raw/{ticker}/{period}
- MinerU parse outputs and evidence: Data/Finance/SEC/parsed/
- PostgreSQL stores filing records, page evidence, extracted facts, and processing events.
- Redis stores task state under the secfilings: key prefix.

## Run

Configure the local service environment files using the Docker and dashboard instructions. Ensure the MinerU, PostgreSQL, and Redis containers are running, then run run_pipeline.py from this directory. The dashboard is served at http://127.0.0.1:8090.

See dashboard/README.md for dashboard setup and operations.
