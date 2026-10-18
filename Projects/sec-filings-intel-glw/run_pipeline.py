#!/usr/bin/env python3
"""Parse the SEC filing set with the local MinerU API, retain page evidence, and index results."""
from __future__ import annotations
import csv
import hashlib
import html
import io
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parent
LONGSHU_ROOT = Path(os.environ.get("LONGSHU_HOME", PROJECT.parents[1])).resolve()
DATA = Path(os.environ.get("SEC_DATA_DIR", LONGSHU_ROOT / "Data" / "Finance" / "SEC")).resolve()
MANIFEST = PROJECT / "filings.json"
API = os.environ.get("MINERU_API_URL", "http://127.0.0.1:8000")
PG_CONTAINER = os.environ.get("SEC_POSTGRES_CONTAINER", "mineru-postgres")
REDIS_CONTAINER = os.environ.get("SEC_REDIS_CONTAINER", "mineru-redis")
MINERU_CONTAINER = os.environ.get("MINERU_GPU_CONTAINER", "mineru-api")
DB = os.environ.get("SEC_DATABASE", "sec_financials")
PG_USER = os.environ.get("SEC_POSTGRES_USER", "mineru")
POLL_SECONDS = 5


def api_json(url: str, payload=None, method=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if body is None else {"Content-Type": "application/json"}
    req = Request(url, data=body, headers=headers, method=method or ("POST" if body is not None else "GET"))
    with urlopen(req, timeout=180) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {}


def api_bytes(url: str, data: bytes, content_type="application/octet-stream", method="PUT"):
    req = Request(url, data=data, headers={"Content-Type": content_type}, method=method)
    with urlopen(req, timeout=900) as response:
        return response.read()


def save_api_content(file_id: str, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    req = Request(f"{API}/v1/files/{file_id}/content")
    with urlopen(req, timeout=300) as response, target.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_with_mineru(filing: dict, source: Path, out_dir: Path) -> tuple[dict, dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / source.stem
    markdown_path = base.with_suffix(".md")
    middle_path = base.with_suffix(".middle.json")
    job_path = base.with_suffix(".job.json")
    if markdown_path.exists() and middle_path.exists():
        job = json.loads(job_path.read_text(encoding="utf-8-sig")) if job_path.exists() else {}
        return job, json.loads(middle_path.read_text(encoding="utf-8-sig"))

    file_hash = sha256_file(source)
    data = source.read_bytes()
    created = api_json(f"{API}/v1/uploads", {
        "filename": source.name,
        "bytes": len(data),
        "mime_type": "application/pdf",
        "purpose": "parse",
        "sha256sum": file_hash,
    })
    file_obj = created.get("file")
    if created.get("upload_url"):
        api_bytes(created["upload_url"], data)
        completed = api_json(f"{API}/v1/uploads/{created['id']}/complete", {"sha256sum": file_hash})
        file_obj = completed.get("file") or completed
    elif not file_obj:
        status = api_json(f"{API}/v1/uploads/{created['id']}")
        file_obj = status.get("file")
    if not file_obj or not file_obj.get("id"):
        raise RuntimeError(f"MinerU did not provide an upload URL or reusable file object: {created}")
    file_id = file_obj["id"]
    job = api_json(f"{API}/v1/parse/jobs", {
        "files": [{"source": {"type": "file_id", "file_id": file_id}}],
        "tier": "standard",
        "ocr_mode": "auto",
        "output_formats": ["markdown", "middle_json"],
    })
    job_id = job["job_id"]
    print(f"[{filing['ticker']} {filing['period_label']}] MinerU job {job_id} queued", flush=True)
    while True:
        time.sleep(POLL_SECONDS)
        job = api_json(f"{API}/v1/parse/jobs/{job_id}")
        status = job.get("status")
        print(f"[{filing['ticker']} {filing['period_label']}] MinerU {status}", flush=True)
        if status in {"completed", "partial", "failed", "canceled"}:
            break
    if job.get("status") != "completed":
        raise RuntimeError(f"MinerU job {job_id} ended as {job.get('status')}: {job}")
    file_result = job["files"][0]
    if file_result.get("status") != "completed":
        raise RuntimeError(f"MinerU file parse failed: {file_result}")
    refs = file_result["output_files"]
    save_api_content(refs["markdown"]["file_id"], markdown_path)
    save_api_content(refs["middle_json"]["file_id"], middle_path)
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    return job, json.loads(middle_path.read_text(encoding="utf-8-sig"))


class TableReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.colspan = 1

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"}:
            self.cell = []
            values = dict(attrs)
            try:
                self.colspan = max(1, int(values.get("colspan", "1")))
            except ValueError:
                self.colspan = 1
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"td", "th"} and self.cell is not None:
            value = re.sub(r"\s+", " ", " ".join(self.cell)).strip()
            self.row.extend([value] * self.colspan)
            self.cell = None
            self.colspan = 1
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def html_rows(fragment: str):
    parser = TableReader()
    parser.feed(fragment)
    return parser.rows


def html_text(fragment: str) -> str:
    parser = TableReader()
    parser.feed(fragment)
    return " | ".join(" ".join(cell for cell in row if cell) for row in parser.rows)


def content_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for child in node:
            yield from content_strings(child)
    elif isinstance(node, dict):
        value = node.get("content")
        if value is not None:
            yield from content_strings(value)


def text_from_block(block: dict) -> str:
    parts = []
    for value in content_strings(block.get("content", [])):
        if "<table" in value.lower():
            parts.append(html_text(value))
        else:
            parts.append(html.unescape(re.sub(r"<[^>]+>", " ", value)))
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def table_fragments(block: dict):
    if block.get("type") != "table":
        return
    for value in content_strings(block.get("content", [])):
        if "<table" in value.lower() and "<tr" in value.lower():
            yield value


def period_scopes(filing: dict, header: str, count: int):
    h = header.casefold()
    if filing["form"] == "10-K":
        years = list(dict.fromkeys(re.findall(r"20\d{2}", header)))
        if len(years) < count:
            years = [str(int(filing["period_end"][:4]) - i) for i in range(count)]
        return [f"FY{years[min(i, len(years)-1)]}" for i in range(count)]
    if "three months" in h and ("six months" in h or "nine months" in h) and count >= 4:
        return ["current_quarter", "prior_year_quarter", "current_ytd", "prior_year_ytd"][:count]
    if "three months" in h:
        return ["current_quarter", "prior_year_quarter"] + [f"column_{i+1}" for i in range(max(0, count-2))]
    if "six months" in h or "nine months" in h or "year ended" in h:
        return ["current_ytd", "prior_year_ytd"] + [f"column_{i+1}" for i in range(max(0, count-2))]
    if re.search(r"20\d{2}", header):
        return ["as_of_period_end", "prior_period_end"] + [f"column_{i+1}" for i in range(max(0, count-2))]
    return [f"column_{i+1}" for i in range(count)]


def metric_for(label: str):
    s = re.sub(r"\s+", " ", label.casefold()).strip()
    if "attributable to non-controlling" in s:
        return None
    if re.search(r"net (?:income|loss)(?: \(loss\))? attributable to", s):
        return "net_income_attributable"
    if s in {"net revenue", "total net revenue", "net sales", "total net sales", "revenue", "sales"}:
        return "revenue"
    if s.startswith("gross profit") or s == "gross margin":
        return "gross_profit"
    if s.startswith("operating income") or s.startswith("income from operations") or s.startswith("operating loss"):
        return "operating_income"
    if re.fullmatch(r"net (?:income|loss)(?: \(loss\))?", s):
        return "net_income"
    if "diluted" in s and "per share" in s:
        return "eps_diluted"
    if s == "cash and cash equivalents" or re.fullmatch(r"cash and cash equivalents at end of (?:period|year)", s):
        return "cash_and_equivalents"
    if "current portion of long-term debt" in s or "current maturities of debt" in s or s == "short-term debt":
        return "current_debt"
    if s == "debt":
        return "long_term_debt"
    if s.startswith("long-term debt") or s.startswith("long term debt"):
        return "long_term_debt"
    if s == "total assets":
        return "total_assets"
    if re.search(r"net cash provided by(?: \(used for\))? operating activities", s) or "net cash from operating activities" in s:
        return "operating_cash_flow"
    if s in {"capital expenditures", "additions to property, plant and equipment", "additions to property, plant, and equipment", "capital additions"}:
        return "capital_expenditures"
    return None
def numeric_value(value: str):
    s = value.replace("$", "").replace(",", "").replace("%", "").strip()
    if not s or s in {"—", "-", "–"}:
        return None
    negative = s.startswith("(") and s.endswith(")")
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m:
        return None
    number = Decimal(m.group(0))
    return -number if negative else number


def extract_facts(filing: dict, middle: dict):
    facts = []
    title_pattern = re.compile(
        r"^(?:(?:consolidated\s+)?(?:condensed\s+)?(?:statements of (?:operations|income|cash flows)|balance sheets))\b",
        re.I,
    )
    flat_labels = [
        ("Net income (loss) attributable to non-controlling interests", None),
        ("Earnings (loss) per share attributable to Intel—diluted", "eps_diluted"),
        ("Earnings (loss) per share attributable to Intel—basic", None),
        ("Net income (loss) attributable to Intel", "net_income_attributable"),
        ("Net income attributable to Corning", "net_income_attributable"),
        ("Net income (loss)", "net_income"),
        ("Net income", "net_income"),
        ("Operating income (loss)", "operating_income"),
        ("Operating income", "operating_income"),
        ("Net revenue", "revenue"),
        ("Net sales", "revenue"),
        ("Gross profit", "gross_profit"),
        ("Gross margin", "gross_profit"),
        ("Earnings (loss) per share", None),
        ("Net cash provided by (used for) operating activities", "operating_cash_flow"),
        ("Net cash provided by operating activities", "operating_cash_flow"),
        ("Additions to property, plant, and equipment", "capital_expenditures"),
        ("Additions to property, plant, and equipment under finance leases", None),
        ("Additions to property, plant and equipment under finance leases", None),
        ("Capital expenditures", "capital_expenditures"),
        ("Cash and cash equivalents at end of period", "cash_and_equivalents"),
        ("Cash and cash equivalents at end of year", "cash_and_equivalents"),
        ("Cash and cash equivalents", "cash_and_equivalents"),
        ("Current maturities of long-term debt", "current_debt"),
        ("Current portion of long-term debt", "current_debt"),
        ("Short-term debt", "current_debt"),
        ("Long-term debt", "long_term_debt"),
        ("Total assets", "total_assets"),
        ("Cost of sales", None),
        ("Research and development", None),
        ("Marketing, general, and administrative", None),
        ("Restructuring and other charges", None),
        ("Operating expenses", None),
        ("Gains (losses) on equity investments, net", None),
        ("Interest and other, net", None),
        ("Income (loss) before taxes", None),
        ("Provision for (benefit from) taxes", None),
        ("Weighted average shares of common stock outstanding:", None),
    ]
    flat_pattern = re.compile("|".join(re.escape(label) for label, _ in sorted(flat_labels, key=lambda p: len(p[0]), reverse=True)), re.I)
    flat_metric = {label.casefold(): key for label, key in flat_labels}
    heading_pattern = re.compile(
        r"^(?:consolidated\s+)?(?:condensed\s+)?(statements of operations|statements of income|balance sheets|statements of cash flows)\b",
        re.I,
    )
    allowed_metrics = {
        "income": {"revenue", "gross_profit", "operating_income", "net_income", "net_income_attributable", "eps_diluted"},
        "balance": {"cash_and_equivalents", "current_debt", "long_term_debt", "total_assets"},
        "cash_flow": {"operating_cash_flow", "capital_expenditures"},
    }
    for page in middle.get("pages", []):
        page_num = int(page.get("page_idx", 0)) + 1
        blocks = page.get("blocks", [])
        block_texts = [text_from_block(b) for b in blocks]
        page_text = " ".join(t for t in block_texts if t)
        lower = page_text.casefold()
        statement_kind = None
        for block in blocks:
            if block.get("type") not in {"header", "paragraph_title", "table"}:
                continue
            match = heading_pattern.match(text_from_block(block))
            if match:
                kind = match.group(1).casefold()
                statement_kind = "balance" if kind == "balance sheets" else "cash_flow" if kind == "statements of cash flows" else "income"
                break
        table_texts = [text_from_block(block) for block in blocks if block.get("type") == "table"]
        combined_tables = " ".join(table_texts).casefold()
        if statement_kind is None:
            if all(term in combined_tables for term in ("current assets", "total assets", "liabilities")):
                statement_kind = "balance"
            elif "cash flows from operating activities" in combined_tables and "net cash" in combined_tables:
                statement_kind = "cash_flow"
            elif all(term in combined_tables for term in ("net sales", "gross margin", "operating income", "net income attributable to corning incorporated")):
                statement_kind = "income"
        if statement_kind is None:
            continue
        has_table = False
        for block in blocks:
            fragments = list(table_fragments(block))
            has_table = has_table or bool(fragments)
            for fragment in fragments:
                rows = html_rows(fragment)
                if not rows:
                    continue
                header = " ".join(" ".join(c for c in row) for row in rows[:4])
                in_eps_section = False
                cashflow_section = None
                for row in rows:
                    if len(row) < 2:
                        continue
                    label = re.sub(r"\s+", " ", row[0]).strip()
                    if statement_kind == "cash_flow":
                        section = label.casefold()
                        if re.search(r"cash flows? (?:provided by|from) .*operating activities", section):
                            cashflow_section = "operating"
                        elif re.search(r"cash flows? (?:provided by|from) .*investing activities", section):
                            cashflow_section = "investing"
                        elif re.search(r"cash flows? (?:provided by|from) .*financing activities", section):
                            cashflow_section = "financing"
                    if re.search(r"earnings per (?:common )?share", label, re.I):
                        in_eps_section = True
                    elif in_eps_section and re.match(r"diluted\b", label, re.I):
                        pass
                    elif in_eps_section and re.match(r"basic\b", label, re.I):
                        continue
                    elif in_eps_section and label:
                        in_eps_section = False
                    metric = metric_for(label)
                    if metric is None and in_eps_section and re.match(r"diluted\b", label, re.I):
                        metric = "eps_diluted"
                    if not metric:
                        continue
                    if metric not in allowed_metrics[statement_kind]:
                        continue
                    if metric == "capital_expenditures" and statement_kind == "cash_flow" and cashflow_section != "investing":
                        continue
                    values = row[1:]
                    scopes = period_scopes(filing, f"{header} {page_text}", len(values))
                    parsed = [(i, v, numeric_value(v)) for i, v in enumerate(values) if numeric_value(v) is not None]
                    if not parsed:
                        continue
                    row_quote = f"{label}: " + " | ".join(f"{scopes[i]}={v}" for i, v, _ in parsed)
                    unit = "USD/share" if metric == "eps_diluted" else "USD millions"
                    for i, value_text, number in parsed:
                        facts.append({
                            "metric_key": metric,
                            "metric_label": label,
                            "value_numeric": str(number),
                            "value_text": value_text,
                            "unit": unit,
                            "period_scope": scopes[i] if i < len(scopes) else f"column_{i+1}",
                            "source_page": page_num,
                            "evidence_quote": row_quote,
                            "sec_url": filing["sec_url"],
                            "extraction_method": "MinerU middle_json table row rule",
                            "confidence": None,
                        })
        if not has_table:
            printed = next((text_from_block(b) for b in blocks if b.get("type") == "page_number"), None)
            matches = list(flat_pattern.finditer(page_text))
            for index, match in enumerate(matches):
                label = re.sub(r"\s+", " ", match.group(0)).strip()
                metric = flat_metric.get(label.casefold()) or metric_for(label)
                if not metric:
                    continue
                if metric not in allowed_metrics[statement_kind]:
                    continue
                end = matches[index + 1].start() if index + 1 < len(matches) else len(page_text)
                segment = page_text[match.end():end]
                tokens = re.findall(r"\(?\$?\s*\d[\d,]*(?:\.\d+)?\)?", segment)[:4]
                scopes = period_scopes(filing, page_text, len(tokens))
                parsed = [(i, token.strip(), numeric_value(token)) for i, token in enumerate(tokens) if numeric_value(token) is not None]
                for i, value_text, number in parsed:
                    scope = scopes[min(i, len(scopes)-1)]
                    prefix = f"Printed page {printed}: " if printed else ""
                    facts.append({
                        "metric_key": metric,
                        "metric_label": label,
                        "value_numeric": str(number),
                        "value_text": value_text,
                        "unit": "USD/share" if metric == "eps_diluted" else "USD millions",
                        "period_scope": scope,
                        "source_page": page_num,
                        "evidence_quote": f"{prefix}{label}: " + " | ".join(token.strip() for token in tokens[:3]),
                        "sec_url": filing["sec_url"],
                        "extraction_method": "MinerU middle_json statement text row rule",
                        "confidence": None,
                    })
    return facts
def sql_literal(value):
    if value is None:
        return "NULL"
    text = str(value).replace("\x00", "")
    tag = "$v$"
    while tag in text:
        tag = "$v" + str(len(tag)) + "$"
    return f"{tag}{text}{tag}"


def psql(args, input_text=None):
    command = ["docker", "exec"]
    if input_text is not None:
        command.append("-i")
    command += [PG_CONTAINER, "psql", "-v", "ON_ERROR_STOP=1", "-U", PG_USER, "-d", DB] + args
    result = subprocess.run(command, input=None if input_text is None else input_text.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace") or result.stdout.decode("utf-8", "replace"))
    return result.stdout.decode("utf-8", "replace").strip()


def db_query(sql: str) -> str:
    return psql(["-q", "-At", "-c", sql])


def record_pipeline_event(run_id: str, stage: str, status: str, title: str, message: str,
                          output: dict | None = None, filing: dict | None = None):
    """Persist one user-visible pipeline milestone for the live dashboard."""
    ticker = filing.get("ticker") if filing else None
    accession = filing.get("accession") if filing else None
    filing_id = None
    if accession:
        found = db_query(f"SELECT filing_id FROM filings WHERE accession={sql_literal(accession)};")
        filing_id = int(found) if found else None
    values = [run_id, filing_id, ticker, accession, stage, status, title, message]
    cols = "run_id, filing_id, ticker, accession, stage, status, title, message, output"
    vals = ", ".join(sql_literal(value) if value is not None else "NULL" for value in values)
    output_json = sql_literal(json.dumps(output or {}, ensure_ascii=False))
    db_query(f"INSERT INTO pipeline_events ({cols}) VALUES ({vals}, {output_json}::jsonb);")


def upsert_filing(filing: dict, source: Path, file_hash: str, job_id: str, parser_version: str, page_count: int):
    cols = [
        "ticker", "company", "cik", "form", "period_label", "period_end", "filed_date", "accession",
        "sec_url", "source_url", "source_kind", "local_source_path", "sha256", "mineru_job_id", "parser_version", "page_count", "parse_status"
    ]
    values = [
        filing["ticker"], filing["company"], filing["cik"], filing["form"], filing["period_label"], filing["period_end"], filing["filed_date"], filing["accession"],
        filing["sec_url"], filing["source_url"], filing["source_kind"], str(source), file_hash, job_id or None, parser_version, page_count, "completed"
    ]
    assignments = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "accession")
    sql = f"INSERT INTO filings ({', '.join(cols)}) VALUES ({', '.join(sql_literal(v) for v in values)}) ON CONFLICT (accession) DO UPDATE SET {assignments}, updated_at=now() RETURNING filing_id;"
    return int(db_query(sql).splitlines()[-1])


def csv_copy(table: str, columns: list[str], rows: list[list]):
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    for row in rows:
        writer.writerow([r"\N" if value is None else str(value).replace("\x00", "") for value in row])
    return f"\\copy {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')\n{buf.getvalue()}\\.\n"


def persist_document(filing: dict, source: Path, file_hash: str, job: dict, middle: dict, pages: list[dict], facts: list[dict]):
    file_result = (job.get("files") or [{}])[0]
    parser_version = (file_result.get("parse") or {}).get("parser_version") or middle.get("metadata", {}).get("producer", {}).get("version")
    page_count = middle.get("metadata", {}).get("document", {}).get("page_count") or len(pages)
    job_id = job.get("job_id")
    filing_id = upsert_filing(filing, source, file_hash, job_id, parser_version, page_count)
    sql = "BEGIN;\n"
    sql += f"DELETE FROM page_evidence WHERE filing_id={filing_id};\nDELETE FROM financial_facts WHERE filing_id={filing_id};\n"
    page_rows = [[filing_id, p["page_number"], p["printed_page_number"], p["markdown_path"], p["page_text"]] for p in pages]
    sql += csv_copy("page_evidence", ["filing_id", "page_number", "printed_page_number", "markdown_path", "page_text"], page_rows)
    fact_rows = [[filing_id, f["metric_key"], f["metric_label"], f["value_numeric"], f["value_text"], f["unit"], f["period_scope"], f["source_page"], f["evidence_quote"], f["sec_url"], f["extraction_method"], f["confidence"]] for f in facts]
    sql += csv_copy("financial_facts", ["filing_id", "metric_key", "metric_label", "value_numeric", "value_text", "unit", "period_scope", "source_page", "evidence_quote", "sec_url", "extraction_method", "confidence"], fact_rows)
    details = json.dumps({"page_count": page_count, "fact_count": len(facts), "source_sha256": file_hash}, ensure_ascii=False)
    sql += f"INSERT INTO processing_runs(filing_id,service,job_id,status,gpu_name,parser_version,finished_at,details) VALUES ({filing_id},'MinerU GPU API',{sql_literal(job_id)},'completed','NVIDIA GeForce RTX 4070',{sql_literal(parser_version)},now(),{sql_literal(details)}::jsonb);\nCOMMIT;\n"
    psql([], input_text=sql)
    return filing_id, page_count, parser_version


def redis_set(key: str, value: dict):
    payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
    items = [b"SET", key.encode("utf-8"), payload, b"EX", b"2592000"]
    request = b"*" + str(len(items)).encode() + b"\r\n" + b"".join(b"$" + str(len(i)).encode() + b"\r\n" + i + b"\r\n" for i in items)
    result = subprocess.run(["docker", "exec", "-i", REDIS_CONTAINER, "sh", "-lc", 'redis-cli -a "$REDIS_PASSWORD" --pipe'], input=request, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode or b"errors: 0" not in result.stdout:
        raise RuntimeError("Redis write failed: " + result.stderr.decode("utf-8", "replace") + result.stdout.decode("utf-8", "replace"))


def page_records(filing: dict, middle: dict, middle_path: Path):
    out = []
    for page in middle.get("pages", []):
        blocks = page.get("blocks", [])
        page_num = int(page.get("page_idx", 0)) + 1
        printed = None
        texts = []
        for block in blocks:
            t = text_from_block(block)
            if t:
                texts.append(t)
            if block.get("type") == "page_number" and t:
                printed = t.strip()
        out.append({"page_number": page_num, "printed_page_number": printed, "markdown_path": str(middle_path), "page_text": "\n".join(texts)})
    return out


def write_exports():
    sql = "SELECT COALESCE(json_agg(row_to_json(q))::text,'[]') FROM (SELECT f.ticker,f.company,f.form,f.period_label,f.period_end,f.filed_date,f.accession,f.sec_url,f.source_url,f.source_kind,f.local_source_path,f.page_count,f.mineru_job_id,x.metric_key,x.metric_label,x.value_numeric::text AS value_numeric,x.value_text,x.unit,x.period_scope,x.source_page,x.evidence_quote,x.extraction_method FROM financial_facts x JOIN filings f USING(filing_id) ORDER BY f.ticker,f.period_end DESC,x.metric_key,x.period_scope,x.source_page) q;"
    data = json.loads(db_query(sql) or "[]")
    report_path = DATA / "reports" / "sec_financials_extraction_2026-10-18.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# INTC and GLW SEC filings: extracted facts and evidence",
        "",
        "Snapshot: 2026-10-18. Each issuer has Q2 2026 10-Q, Q1 2026 10-Q, and FY2025 10-K.",
        "Numbers are extracted from statement tables by row rules after MinerU parsing. Values are in USD millions unless marked USD/share. Each row carries the SEC accession, filing URL, local PDF page sequence, and the exact table row used.",
        "",
        "The GLW Q2 filing was originally filed as HTML. Its local PDF was rendered from the preserved SEC filing HTML mirror; page numbers are local render pages. Use the SEC URL and quote to verify against the filed HTML.",
        "",
        "This is an extraction index, not investment advice. GAAP rows and company-defined Core/non-GAAP rows are kept distinct.",
        "",
    ]
    for ticker in ("INTC", "GLW"):
        lines += [f"## {ticker}", "", "| Report | Metric | Period column | Value | Unit | Local PDF page | SEC accession | Source quote |", "|---|---|---|---:|---|---:|---|---|"]
        for row in data:
            if row["ticker"] != ticker:
                continue
            quote = (row.get("evidence_quote") or "").replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {row['period_label']} | {row['metric_label']} | {row['period_scope']} | {row['value_text']} | {row['unit']} | {row['source_page']} | {row['accession']} | {quote} |")
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    json_path = DATA / "reports" / "extracted_facts.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = DATA / "reports" / "extracted_facts.csv"
    if data:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            writer.writeheader()
            writer.writerows(data)
    return report_path, len(data)


def main():
    psql(["-f", "/dev/null"]) if False else None
    schema = (PROJECT / "schema.sql").read_text(encoding="utf-8-sig")
    psql([], input_text=schema)
    filings = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    run_id = str(uuid.uuid4())
    try:
        gpu = subprocess.run(["docker", "exec", MINERU_CONTAINER, "nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip().splitlines()[0]
    except Exception as exc:
        raise RuntimeError("Could not verify the GPU in mineru-api") from exc
    record_pipeline_event(run_id, "analysis_run", "started", "SEC 分析任务已启动",
                          "开始处理 Intel 与 Corning 的 SEC 文件。", {"filing_count": len(filings), "gpu": gpu})
    for filing in filings:
        source = Path(filing["source_path"])
        if not source.is_absolute():
            source = LONGSHU_ROOT / source
        if not source.is_file():
            raise FileNotFoundError(source)
        file_hash = sha256_file(source)
        record_pipeline_event(run_id, "source_verified", "completed", "SEC 文件已就绪",
                              "本地源文件存在，SHA-256 已计算。",
                              {"file": str(source), "bytes": source.stat().st_size, "sha256": file_hash,
                               "sec_url": filing["sec_url"]}, filing)
        candidates = [DATA / "parsed" / filing["ticker"] / filing["period_label"].replace(" ", "-"), DATA / "parsed" / filing["ticker"] / source.parent.name]
        out_dir = next((candidate for candidate in candidates if (candidate / (source.stem + ".middle.json")).exists()), candidates[0])
        key = f"secfilings:{filing['ticker']}:{filing['accession']}"
        redis_set(key, {"status": "processing", "ticker": filing["ticker"], "accession": filing["accession"], "updated_at": datetime.now(timezone.utc).isoformat()})
        current_stage = "mineru_parsing"
        cache_hit = (out_dir / (source.stem + ".md")).exists() and (out_dir / (source.stem + ".middle.json")).exists()
        record_pipeline_event(run_id, current_stage, "started", "MinerU GPU 解析中",
                              "正在提交 MinerU 解析任务。" if not cache_hit else "发现本地解析缓存，正在读取已保存结果。",
                              {"input_file": str(source), "cache_hit": cache_hit, "gpu": gpu}, filing)
        try:
            job, middle = parse_with_mineru(filing, source, out_dir)
            middle_path = out_dir / (source.stem + ".middle.json")
            parser_version = ((job.get("files") or [{}])[0].get("parse") or {}).get("parser_version") or middle.get("metadata", {}).get("producer", {}).get("version")
            parsed_pages = middle.get("metadata", {}).get("document", {}).get("page_count") or len(middle.get("pages", []))
            record_pipeline_event(run_id, "mineru_parsed", "completed", "MinerU GPU 解析完成",
                                  "解析结果已保存，开始提取页级证据与财务信息点。",
                                  {"job_id": job.get("job_id"), "page_count": parsed_pages,
                                   "parser_version": parser_version, "gpu": gpu, "cache_hit": cache_hit}, filing)

            current_stage = "fact_extraction"
            record_pipeline_event(run_id, current_stage, "started", "正在提取结构化信息点",
                                  "正在扫描页级内容与报表行，并保留可回溯的原文摘录。",
                                  {"page_count": parsed_pages}, filing)
            pages = page_records(filing, middle, middle_path)
            facts = extract_facts(filing, middle)
            record_pipeline_event(run_id, current_stage, "completed", "结构化信息点提取完成",
                                  "逐页证据与财务报表行已按规则提取。",
                                  {"page_count": len(pages), "fact_count": len(facts),
                                   "metrics": sorted({fact["metric_key"] for fact in facts}),
                                   "evidence_samples": [fact["evidence_quote"] for fact in facts[:5]]}, filing)

            current_stage = "database_persist"
            record_pipeline_event(run_id, current_stage, "started", "正在写入证据数据库",
                                  "正在提交页级证据、结构化信息点和解析运行记录。",
                                  {"page_count": len(pages), "fact_count": len(facts)}, filing)
            filing_id, page_count, version = persist_document(filing, source, file_hash, job, middle, pages, facts)
            record_pipeline_event(run_id, "evidence_indexed", "completed", "证据与信息点已写入数据库",
                                  "PostgreSQL 已提交本文件的页级证据、结构化信息点与解析运行记录。",
                                  {"filing_id": filing_id, "page_count": page_count, "fact_count": len(facts),
                                   "parser_version": version, "gpu": gpu}, filing)
            redis_set(key, {"status": "completed", "filing_id": filing_id, "mineru_job_id": job.get("job_id"), "page_count": page_count, "fact_count": len(facts), "gpu": gpu, "parser_version": version, "updated_at": datetime.now(timezone.utc).isoformat()})
            print(f"[{filing['ticker']} {filing['period_label']}] stored filing_id={filing_id}, pages={page_count}, facts={len(facts)}, parser={version}, gpu={gpu}", flush=True)
        except Exception as exc:
            try:
                record_pipeline_event(run_id, current_stage, "failed", "处理步骤失败", str(exc)[:2000],
                                      {"error_type": type(exc).__name__}, filing)
                redis_set(key, {"status": "failed", "error": str(exc)[:1000], "updated_at": datetime.now(timezone.utc).isoformat()})
            except Exception:
                pass
            raise
    report, total = write_exports()
    record_pipeline_event(run_id, "exports_ready", "completed", "分析结果已导出",
                          "Markdown、JSON 与 CSV 结构化结果已更新。",
                          {"report": str(report), "fact_count": total}, None)
    print(f"Exported {total} facts to {report}", flush=True)
    print("Database summary:")
    print(db_query("SELECT ticker || ' reports=' || count(*) || ' pages=' || sum(page_count) FROM filings GROUP BY ticker ORDER BY ticker;"))
    print(db_query("SELECT 'facts=' || count(*) || ' evidence_pages=' || (SELECT count(*) FROM page_evidence) FROM financial_facts;"))


if __name__ == "__main__":
    main()
