const state = { filings: [], facts: [], events: [], eventIds: new Set(), runs: [], counts: {}, resource: null, ticker: 'ALL', search: '' };
const stageNames = {
  analysis_run: 'SEC 分析任务', source_verified: '源文件校验', mineru_parsing: 'MinerU GPU 解析',
  mineru_parsed: 'MinerU 解析完成', fact_extraction: '信息点提取', database_persist: '数据库写入',
  evidence_indexed: '证据与结果入库', exports_ready: '报告导出',
};
const outputNames = {
  filing_count: '文件数', file: '本地文件', bytes: '文件大小', sha256: 'SHA-256', sec_url: 'SEC 来源',
  input_file: '输入文件', cache_hit: '使用缓存', gpu: 'GPU', job_id: 'MinerU 任务', page_count: '解析页数',
  parser_version: '解析器', fact_count: '信息点', metrics: '指标类型', evidence_samples: '摘录示例',
  filing_id: '数据库记录', report: '导出报告',
};
const $ = (selector) => document.querySelector(selector);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function formatDate(value) {
  if (!value) return '时间未知';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(date);
}

function formatNumber(value) { return Number(value || 0).toLocaleString('zh-CN'); }
function humanBytes(value) {
  const n = Number(value || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

async function loadSnapshot() {
  const response = await fetch('/api/snapshot', { cache: 'no-store' });
  if (!response.ok) throw new Error(`数据库快照读取失败 (${response.status})`);
  const snapshot = await response.json();
  state.filings = snapshot.filings || [];
  state.facts = snapshot.facts || [];
  state.runs = snapshot.processing_runs || [];
  state.counts = snapshot.counts || {};
  for (const event of snapshot.events || []) addEvent(event, false);
  $('#updated-at').textContent = `数据库快照 · ${formatDate(snapshot.generated_at)}`;
  renderAll();
}

function addEvent(event, redraw = true) {
  const key = String(event.event_id ?? `${event.run_id || 'event'}-${event.created_at}-${event.stage}`);
  if (state.eventIds.has(key)) return;
  state.eventIds.add(key);
  state.events.push(event);
  if (redraw) renderTimeline();
}

let refreshTimer;
function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => loadSnapshot().catch(showError), 250);
}

function startStream() {
  const stream = new EventSource('/api/events?after=0');
  const connection = $('#connection');
  stream.addEventListener('connected', () => {
    connection.className = 'connection connected';
    connection.lastElementChild.textContent = '实时连接';
    loadSnapshot().catch(showError);
  });
  stream.addEventListener('pipeline', (message) => {
    try { addEvent(JSON.parse(message.data)); } catch {}
    scheduleRefresh();
  });
  stream.addEventListener('refresh', () => scheduleRefresh());
  stream.addEventListener('resources', (message) => {
    try { state.resource = JSON.parse(message.data); renderResources(); } catch {}
  });
  stream.addEventListener('stream-error', () => scheduleRefresh());
  stream.onerror = () => {
    connection.className = 'connection error';
    connection.lastElementChild.textContent = '正在重连';
  };
}

function showError(error) {
  $('#updated-at').textContent = error?.message || '数据读取失败';
  const connection = $('#connection');
  connection.className = 'connection error';
  connection.lastElementChild.textContent = '数据库连接异常';
}

function renderAll() {
  $('#count-filings').textContent = formatNumber(state.counts.filings ?? state.filings.length);
  $('#count-pages').textContent = formatNumber(state.counts.pages ?? state.filings.reduce((sum, row) => sum + Number(row.evidence_page_count || 0), 0));
  $('#count-facts').textContent = formatNumber(state.counts.facts ?? state.facts.length);
  $('#count-events').textContent = formatNumber(state.counts.events ?? state.events.length);
  renderFilings(); renderTimeline(); renderFacts(); renderResources();
}

function renderFilings() {
  const root = $('#filings'); root.replaceChildren();
  if (!state.filings.length) { root.append(element('div', 'empty-card', '数据库中还没有 SEC 文件记录。')); return; }
  for (const filing of state.filings) {
    const card = element('article', 'filing-card');
    const heading = element('div', 'filing-title');
    const left = element('div');
    left.append(element('span', 'ticker-chip', filing.ticker));
    left.append(element('h3', '', filing.company));
    left.append(element('div', 'filing-period', `${filing.form} · ${filing.period_label} · 申报 ${filing.filed_date || '日期未知'}`));
    heading.append(left, element('span', 'filing-status', filing.parse_status === 'completed' ? '解析完成' : (filing.parse_status || '处理中')));
    card.append(heading);
    const stats = element('div', 'filing-stats');
    for (const [label, value] of [['页数', filing.page_count], ['证据页', filing.evidence_page_count], ['信息点', filing.fact_count]]) {
      const item = element('span'); item.append(element('strong', '', formatNumber(value)), document.createTextNode(label)); stats.append(item);
    }
    card.append(stats);
    const links = element('div', 'filing-links');
    const sec = element('a', '', 'SEC 原始文件'); sec.href = filing.sec_url; sec.target = '_blank'; sec.rel = 'noopener noreferrer';
    const source = element('a', '', '来源副本'); source.href = filing.source_url; source.target = '_blank'; source.rel = 'noopener noreferrer';
    links.append(sec, source); card.append(links);
    card.append(element('div', 'local-path', filing.local_source_path || '本地路径未登记'));
    root.append(card);
  }
}

function describeOutput(output) {
  if (!output || typeof output !== 'object') return [];
  const preferred = ['filing_count', 'file', 'bytes', 'sha256', 'sec_url', 'input_file', 'cache_hit', 'gpu', 'job_id', 'page_count', 'parser_version', 'fact_count', 'metrics', 'evidence_samples', 'filing_id', 'report'];
  return preferred.filter((key) => output[key] !== undefined && output[key] !== null).map((key) => [key, output[key]]);
}

function renderTimeline() {
  const root = $('#timeline'); root.replaceChildren();
  const ordered = [...state.events].sort((a, b) => {
    const byDate = new Date(b.created_at || 0) - new Date(a.created_at || 0);
    if (byDate) return byDate;
    return Number(b.event_id || 0) - Number(a.event_id || 0);
  });
  if (!ordered.length) { root.append(element('div', 'empty-state', '还没有处理步骤记录。启动 SEC 分析流水线后，步骤会在这里逐条出现。')); return; }
  for (const item of ordered) {
    const status = item.status || 'completed';
    const card = element('article', `event-card ${status === 'started' ? 'is-processing' : ''} ${status === 'failed' ? 'is-failed' : ''}`);
    const top = element('div', 'event-top');
    const name = item.title || stageNames[item.stage] || item.stage || '处理步骤';
    top.append(element('span', 'event-title', name), element('time', 'event-time', formatDate(item.created_at)));
    card.append(top);
    const ticker = item.ticker ? `${item.ticker} · ` : '';
    const accession = item.accession ? ` · ${item.accession}` : '';
    const statusText = status === 'started' ? '进行中' : status === 'failed' ? '失败' : '已完成';
    card.append(element('div', 'event-sub', `${ticker}${stageNames[item.stage] || item.stage || '流程'} · ${statusText}${accession}`));
    if (item.message) card.append(element('div', 'event-message', item.message));
    const chips = element('div', 'event-output');
    for (const [key, value] of describeOutput(item.output)) {
      const chip = element('span', 'output-chip');
      chip.append(element('b', '', `${outputNames[key] || key}：`));
      const shown = Array.isArray(value) ? value.join('；') : (typeof value === 'object' ? JSON.stringify(value) : String(value));
      chip.append(document.createTextNode(shown)); chips.append(chip);
    }
    if (chips.childNodes.length) card.append(chips);
    root.append(card);
  }
}

function renderFacts() {
  const body = $('#facts-body'); body.replaceChildren();
  const query = state.search.trim().toLocaleLowerCase();
  const rows = state.facts.filter((fact) => {
    if (state.ticker !== 'ALL' && fact.ticker !== state.ticker) return false;
    if (!query) return true;
    return [fact.ticker, fact.company, fact.period_label, fact.metric_key, fact.metric_label, fact.period_scope, fact.value_text, fact.evidence_quote].some((value) => String(value || '').toLocaleLowerCase().includes(query));
  });
  $('#facts-count-label').textContent = `${formatNumber(rows.length)} / ${formatNumber(state.facts.length)} 条信息点`;
  $('#facts-empty').classList.toggle('hidden', rows.length > 0);
  for (const fact of rows) {
    const tr = document.createElement('tr');
    const companyCell = document.createElement('td'); companyCell.append(element('div', 'fact-company', fact.ticker), element('div', 'fact-report', `${fact.company} · ${fact.period_label}`));
    const metricCell = document.createElement('td'); metricCell.append(element('div', 'metric-name', fact.metric_label), element('code', 'metric-key', fact.metric_key));
    const periodCell = document.createElement('td'); periodCell.append(element('span', 'period-tag', fact.period_scope || '期间未标注'));
    const valueCell = document.createElement('td'); valueCell.append(element('div', 'fact-value', fact.value_text), element('div', 'fact-unit', fact.unit));
    const sourceCell = document.createElement('td'); sourceCell.className = 'fact-source';
    sourceCell.append(element('span', 'fact-page', `本地 PDF 第 ${fact.source_page ?? '—'} 页`));
    sourceCell.append(element('blockquote', '', fact.evidence_quote || '原文摘录未保存'));
    const link = element('a', '', `SEC 文件 · ${fact.accession}`); link.href = fact.sec_url; link.target = '_blank'; link.rel = 'noopener noreferrer'; sourceCell.append(link);
    tr.append(companyCell, metricCell, periodCell, valueCell, sourceCell); body.append(tr);
  }
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = element('td', 'empty-table', '没有符合条件的信息点');
    td.colSpan = 5; tr.append(td); body.append(tr);
  }
}

function updateMeter(id, percent) { const node = $(id); node.style.width = `${Math.max(0, Math.min(100, Number(percent) || 0))}%`; }
function renderResources() {
  const data = state.resource;
  if (!data) return;
  $('#cpu-value').textContent = `${data.cpu_percent ?? 0}%`;
  $('#cpu-detail').textContent = `${data.cpu_threads ?? '—'} 个逻辑处理器 · 本机使用率`;
  updateMeter('#cpu-meter', data.cpu_percent);
  $('#ram-value').textContent = `${data.memory_percent ?? 0}%`;
  $('#ram-detail').textContent = `${humanBytes(data.memory_used_bytes)} / ${humanBytes(data.memory_total_bytes)} · Node 进程 ${humanBytes(data.process_rss_bytes)}`;
  updateMeter('#ram-meter', data.memory_percent);
  const gpu = data.gpu || {};
  if (gpu.available) {
    $('#gpu-value').textContent = `${gpu.utilization_percent}%`;
    $('#gpu-detail').textContent = `${gpu.name} · 显存 ${formatNumber(gpu.memory_used_mb)} / ${formatNumber(gpu.memory_total_mb)} MB · ${gpu.temperature_c}°C · ${formatDate(data.sampled_at)}`;
    updateMeter('#gpu-meter', gpu.utilization_percent);
  } else {
    $('#gpu-value').textContent = '离线';
    $('#gpu-detail').textContent = gpu.message || '无法读取 RTX 4070 状态';
    updateMeter('#gpu-meter', 0);
  }
}

$('#fact-search').addEventListener('input', (event) => { state.search = event.target.value; renderFacts(); });
document.querySelectorAll('.filter-button').forEach((button) => button.addEventListener('click', () => {
  document.querySelectorAll('.filter-button').forEach((candidate) => candidate.classList.toggle('active', candidate === button));
  state.ticker = button.dataset.ticker; renderFacts();
}));

startStream();
