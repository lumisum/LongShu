import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile } from 'node:fs/promises';
import { Client, Pool } from 'pg';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, '..');
const LONGSHU_ROOT = process.env.LONGSHU_HOME || path.resolve(__dirname, '..', '..', '..');
const ENV_FILE = process.env.SEC_ENV_FILE || path.join(LONGSHU_ROOT, 'Docker', 'mineru-stack', '.env');
const MINERU_GPU_CONTAINER = process.env.MINERU_GPU_CONTAINER || 'mineru-api';
const PORT = Number(process.env.PORT || 8090);
const HOST = process.env.HOST || '127.0.0.1';
const execFileAsync = promisify(execFile);
const clients = new Set();

function readDotEnv(source) {
  const values = {};
  for (const line of source.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (match) values[match[1]] = match[2].replace(/^(['"])(.*)\1$/, '$2');
  }
  return values;
}

const dockerEnv = readDotEnv(await readFile(ENV_FILE, 'utf8'));
const pgConfig = {
  host: process.env.PGHOST || '127.0.0.1',
  port: Number(process.env.PGPORT || dockerEnv.POSTGRES_PORT || 5432),
  user: process.env.PGUSER || dockerEnv.POSTGRES_USER || 'mineru',
  password: process.env.PGPASSWORD || dockerEnv.POSTGRES_PASSWORD,
  database: process.env.PGDATABASE || 'sec_financials',
  application_name: 'longshu-sec-live-dashboard',
  max: 8,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
};

if (!pgConfig.password) throw new Error(`PostgreSQL password is missing in ${ENV_FILE}`);
const pool = new Pool(pgConfig);
pool.on('error', (error) => console.error('PostgreSQL pool error:', error.message));

function sendSse(response, event, data, id) {
  if (response.destroyed || response.writableEnded) return;
  if (id !== undefined && id !== null) response.write(`id: ${id}\n`);
  response.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

function broadcast(event, data, id) {
  for (const response of clients) sendSse(response, event, data, id);
}

async function publishDatabaseChange(notification) {
  let change;
  try { change = JSON.parse(notification.payload || '{}'); }
  catch { change = { table: 'unknown' }; }

  if (change.table === 'pipeline_events' && change.operation !== 'DELETE' && change.event_id) {
    try {
      const { rows } = await pool.query(
        `SELECT event_id, run_id, filing_id, ticker, accession, stage, status, title, message, output, created_at
           FROM pipeline_events WHERE event_id = $1`, [change.event_id]);
      if (rows[0]) {
        broadcast('pipeline', rows[0], String(rows[0].event_id));
        return;
      }
    } catch (error) {
      console.error('Could not load pipeline event:', error.message);
    }
  }
  broadcast('refresh', change);
}

async function connectListener() {
  const listener = new Client(pgConfig);
  try {
    await listener.connect();
    await listener.query('LISTEN sec_dashboard_change');
    console.log('Listening to PostgreSQL channel sec_dashboard_change');
    broadcast('refresh', { table: 'listener', operation: 'reconnected' });
    listener.on('notification', publishDatabaseChange);
    listener.on('error', (error) => {
      console.error('PostgreSQL notification listener disconnected:', error.message);
      listener.end().catch(() => {});
      setTimeout(connectListener, 3000).unref();
    });
  } catch (error) {
    console.error('Could not start PostgreSQL notification listener:', error.message);
    await listener.end().catch(() => {});
    setTimeout(connectListener, 5000).unref();
  }
}

async function makeSnapshot() {
  const [filings, facts, events, runs, counts] = await Promise.all([
    pool.query(`SELECT f.filing_id, f.ticker, f.company, f.form, f.period_label,
                       f.period_end, f.filed_date, f.accession, f.sec_url, f.source_url,
                       f.source_kind, f.local_source_path, f.sha256, f.mineru_job_id,
                       f.parser_version, f.page_count, f.parse_status, f.updated_at,
                       COALESCE(p.page_count, 0)::int AS evidence_page_count,
                       COALESCE(x.fact_count, 0)::int AS fact_count
                  FROM filings f
             LEFT JOIN (SELECT filing_id, count(*) AS page_count FROM page_evidence GROUP BY filing_id) p USING (filing_id)
             LEFT JOIN (SELECT filing_id, count(*) AS fact_count FROM financial_facts GROUP BY filing_id) x USING (filing_id)
              ORDER BY f.ticker, f.period_end DESC, f.filing_id`),
    pool.query(`SELECT x.fact_id, f.ticker, f.company, f.form, f.period_label, f.period_end,
                       f.accession, f.sec_url, f.local_source_path, x.metric_key, x.metric_label,
                       x.value_numeric::text AS value_numeric, x.value_text, x.unit, x.period_scope,
                       x.source_page, x.evidence_quote, x.extraction_method, x.confidence
                  FROM financial_facts x JOIN filings f USING (filing_id)
              ORDER BY f.ticker, f.period_end DESC, x.metric_key, x.period_scope, x.source_page`),
    pool.query(`SELECT event_id, run_id, filing_id, ticker, accession, stage, status, title, message, output, created_at
                  FROM pipeline_events ORDER BY event_id`),
    pool.query(`SELECT r.run_id, r.filing_id, f.ticker, f.accession, r.service, r.job_id, r.status,
                       r.gpu_name, r.parser_version, r.started_at, r.finished_at, r.details
                  FROM processing_runs r JOIN filings f USING (filing_id)
              ORDER BY r.run_id DESC`),
    pool.query(`SELECT (SELECT count(*) FROM filings)::int AS filings,
                       (SELECT count(*) FROM page_evidence)::int AS pages,
                       (SELECT count(*) FROM financial_facts)::int AS facts,
                       (SELECT count(*) FROM pipeline_events)::int AS events`),
  ]);
  return {
    generated_at: new Date().toISOString(),
    filings: filings.rows,
    facts: facts.rows,
    events: events.rows,
    processing_runs: runs.rows,
    counts: counts.rows[0],
  };
}

let previousCpu = os.cpus().map((cpu) => cpu.times);
function cpuLoadPercent() {
  const current = os.cpus().map((cpu) => cpu.times);
  let idle = 0;
  let total = 0;
  for (let i = 0; i < current.length; i++) {
    const before = previousCpu[i] || current[i];
    const now = current[i];
    for (const field of Object.keys(now)) {
      const delta = now[field] - (before[field] || 0);
      total += delta;
      if (field === 'idle') idle += delta;
    }
  }
  previousCpu = current;
  return total > 0 ? Math.round((1 - idle / total) * 100) : 0;
}

async function readGpu() {
  try {
    const { stdout } = await execFileAsync('docker', [
      'exec', MINERU_GPU_CONTAINER, 'nvidia-smi',
      '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu',
      '--format=csv,noheader,nounits',
    ], { timeout: 4500, windowsHide: true, maxBuffer: 1024 * 1024 });
    const [name, utilization, memoryUsed, memoryTotal, temperature] = stdout.trim().split(',').map((part) => part.trim());
    return {
      available: true,
      name,
      utilization_percent: Number(utilization),
      memory_used_mb: Number(memoryUsed),
      memory_total_mb: Number(memoryTotal),
      temperature_c: Number(temperature),
    };
  } catch (error) {
    return { available: false, message: `MinerU GPU 容器不可读：${error.message}` };
  }
}

let latestResources = null;
let sampling = false;
async function sampleResources() {
  if (sampling) return latestResources;
  sampling = true;
  try {
    const total = os.totalmem();
    const free = os.freemem();
    const gpu = await readGpu();
    latestResources = {
      sampled_at: new Date().toISOString(),
      cpu_percent: cpuLoadPercent(),
      cpu_threads: os.cpus().length,
      memory_total_bytes: total,
      memory_used_bytes: total - free,
      memory_percent: Math.round((total - free) / total * 100),
      process_rss_bytes: process.memoryUsage().rss,
      gpu,
    };
    broadcast('resources', latestResources);
    return latestResources;
  } finally {
    sampling = false;
  }
}

function json(response, status, data) {
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
  });
  response.end(JSON.stringify(data));
}

async function handle(request, response) {
  const url = new URL(request.url, `http://${HOST}:${PORT}`);
  if (request.method !== 'GET') return json(response, 405, { error: 'Method not allowed' });

  if (url.pathname === '/api/health') {
    try {
      await pool.query('SELECT 1');
      return json(response, 200, { ok: true, database: pgConfig.database, host: HOST, port: PORT });
    } catch (error) {
      return json(response, 503, { ok: false, error: error.message });
    }
  }

  if (url.pathname === '/api/snapshot') {
    try { return json(response, 200, await makeSnapshot()); }
    catch (error) { return json(response, 500, { error: error.message }); }
  }

  if (url.pathname === '/api/resources') {
    return json(response, 200, await sampleResources());
  }

  if (url.pathname === '/api/events') {
    response.writeHead(200, {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-cache, no-transform',
      connection: 'keep-alive',
      'x-accel-buffering': 'no',
    });
    response.flushHeaders();
    clients.add(response);
    sendSse(response, 'connected', { at: new Date().toISOString() });
    const headerCursor = Number(request.headers['last-event-id']);
    const queryCursor = Number(url.searchParams.get('after'));
    const cursor = Number.isFinite(headerCursor) && headerCursor > 0 ? headerCursor : (Number.isFinite(queryCursor) ? queryCursor : 0);
    try {
      const { rows } = await pool.query(
        `SELECT event_id, run_id, filing_id, ticker, accession, stage, status, title, message, output, created_at
           FROM pipeline_events WHERE event_id > $1 ORDER BY event_id`, [cursor]);
      for (const row of rows) sendSse(response, 'pipeline', row, String(row.event_id));
    } catch (error) {
      sendSse(response, 'stream-error', { message: error.message });
    }
    const heartbeat = setInterval(() => {
      if (!response.destroyed && !response.writableEnded) response.write(': keepalive\n\n');
    }, 20000);
    request.on('close', () => {
      clearInterval(heartbeat);
      clients.delete(response);
    });
    return;
  }

  if (url.pathname === '/' || url.pathname === '/index.html') {
    const content = await readFile(path.join(__dirname, 'public', 'index.html'));
    response.writeHead(200, {
      'content-type': 'text/html; charset=utf-8',
      'cache-control': 'no-store',
      'content-security-policy': "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:",
      'x-content-type-options': 'nosniff',
    });
    return response.end(content);
  }

  if (url.pathname === '/app.js' || url.pathname === '/style.css') {
    const content = await readFile(path.join(__dirname, 'public', url.pathname.slice(1)));
    response.writeHead(200, { 'content-type': url.pathname.endsWith('.js') ? 'text/javascript; charset=utf-8' : 'text/css; charset=utf-8', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' });
    return response.end(content);
  }
  return json(response, 404, { error: 'Not found' });
}

const server = http.createServer((request, response) => {
  handle(request, response).catch((error) => {
    console.error('Request failed:', error.message);
    if (!response.headersSent) json(response, 500, { error: 'Internal server error' });
    else response.end();
  });
});

await connectListener();
server.listen(PORT, HOST, () => {
  console.log(`LongShu SEC live dashboard listening at http://${HOST}:${PORT}`);
});
sampleResources().catch((error) => console.error('Initial resource sample failed:', error.message));
setInterval(() => sampleResources().catch((error) => console.error('Resource sampling failed:', error.message)), 3000).unref();

async function shutdown() {
  for (const response of clients) response.end();
  await pool.end();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 2000).unref();
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
