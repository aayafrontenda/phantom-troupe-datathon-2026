/* CashGuard UI — plain JS over /ui/api (docs/api_contract.md). Views: checks list, check, live, rules. Strings: i18n.js */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icon = (id, cls = '') => `<svg class="i ${cls}"><use href="#i-${id}"/></svg>`;
const tc = t => { t = Math.max(0, +t || 0); const m = Math.floor(t / 60); return `${String(m).padStart(2, '0')}:${(t - m * 60).toFixed(1).padStart(4, '0')}`; };
const ago = ts => {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return t('ago.now'); if (s < 3600) return t('ago.min', { n: Math.floor(s / 60) });
  const d = new Date(ts * 1000), today = new Date();
  const hm = d.toTimeString().slice(0, 5);
  return d.toDateString() === today.toDateString() ? t('ago.today', { t: hm }) : `${d.toLocaleDateString(LANGS[LANG].locale)} ${hm}`;
};
const tx = (key, fallback) => (I18N[LANG][key] != null ? t(key) : fallback);
const kindLabel = k => tx(`kind.${k}`, k || '');
const reportUrl = id => `/ui/api/jobs/${id}/report.html?lang=${LANG}`;
const LIVE_CODES = new Set(['T01', 'T05', 'T13', 'T14', 'T15']);

/* ---------- api / ui helpers ---------- */
const adminKey = () => { try { return localStorage.getItem('cg_admin_key') || ''; } catch (_) { return ''; } };
async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (opts.json !== undefined) { headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(opts.json); }
  if (opts.admin && adminKey()) headers['X-API-Key'] = adminKey();
  const r = await fetch(path, { method: opts.method || 'GET', headers, body: opts.body });
  let body = null; try { body = await r.json(); } catch (_) { /* empty */ }
  if (!r.ok) { const e = new Error((body && body.detail) || `HTTP ${r.status}`); e.status = r.status; throw e; }
  return body;
}
function toast(msg, kind = '') {
  const el = document.createElement('div'); el.className = `toast ${kind}`;
  el.innerHTML = `${kind === 'err' ? icon('alert') : icon('check')}<span>${esc(msg)}</span>`;
  $('#toasts').appendChild(el); setTimeout(() => el.remove(), 4200);
}
function modal(html, onMount) {
  const m = $('#modal'), c = $('#modalCard');
  c.innerHTML = html; m.hidden = false;
  return new Promise(resolve => {
    const close = v => { m.hidden = true; c.innerHTML = ''; document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = e => { if (e.key === 'Escape') close(null); };
    document.addEventListener('keydown', onKey);
    m.onclick = e => { if (e.target === m) close(null); };
    $$('[data-close]', c).forEach(b => b.onclick = () => close(null));
    onMount && onMount(c, close);
    const f = $('input,button.primary,button.danger-solid', c); f && f.focus();
  });
}
const confirmBox = (title, text, okLabel, danger = true) => modal(`
  <h3>${esc(title)}</h3><p>${text}</p>
  <div class="acts"><button class="btn" data-close>${t('cancel')}</button><button class="btn ${danger ? 'danger-solid' : 'primary'}" id="mOk">${esc(okLabel)}</button></div>`,
  (c, close) => { $('#mOk', c).onclick = () => close(true); });
function zoom(src, cap) { const lb = $('#lightbox'); $('img', lb).src = src; $('#lbCap').textContent = cap; lb.hidden = false; }
$('#lightbox').onclick = () => { $('#lightbox').hidden = true; };

/* ---------- state + routing ---------- */
const S = {
  jobs: [], filter: 'all', q: '', uploads: {}, job: null, sel: 0, t: 0, playing: false, local: {},
  sse: null, poll: null, listTimer: null, cams: [], camWs: {}, laptop: null, alerts: [], alertsTab: 'open', alertsSse: null, rules: null,
};
function route() {
  const q = new URLSearchParams(location.search);
  if (q.get('check') || q.get('job')) return { view: 'check', id: q.get('check') || q.get('job') };
  if (q.get('view') === 'live') return { view: 'live' };
  if (q.get('view') === 'rules') return { view: 'rules' };
  return { view: 'checks' };
}
function go(url) { history.pushState(null, '', url); render(); }
window.addEventListener('popstate', render);
document.addEventListener('click', e => {
  const a = e.target.closest('a[href^="/"]');
  if (!a || a.target === '_blank' || e.metaKey || e.ctrlKey || a.hasAttribute('download') || a.getAttribute('href').startsWith('/ui/')) return;
  e.preventDefault(); go(a.getAttribute('href'));
});
function leaveCheck() {
  if (S.sse) { S.sse.close(); S.sse = null; }
  if (S.poll) { clearInterval(S.poll); S.poll = null; }
  S.job = null;
}
function leaveLive() {
  Object.values(S.camWs).forEach(ws => { ws.onclose = null; ws.close(); }); S.camWs = {};
  if (S.laptop) stopLaptop(true);
}
function render() {
  const r = route();
  $$('.tab').forEach(t => t.classList.toggle('on', t.dataset.nav === (r.view === 'check' ? 'checks' : r.view)));
  if (r.view !== 'check') leaveCheck();
  if (r.view !== 'live') leaveLive();
  clearTimeout(S.listTimer);
  if (r.view === 'checks') return renderChecks();
  if (r.view === 'check') return openCheck(r.id);
  if (r.view === 'live') return renderLive();
  if (r.view === 'rules') return renderRules();
}

/* ---------- header ---------- */
async function pollStatus() {
  const el = $('#status');
  try {
    const h = await api('/health');
    const busy = (h.running || []).length;
    el.className = `status ${busy ? 'busy' : 'ok'}`;
    $('span', el).textContent = busy ? t('status.busy', { n: h.queue }) : t('status.ready', { model: t(h.analyzer === 'mock' ? 'status.demo' : 'status.local') });
    el.title = t('status.tip', { a: h.analyzer, v: h.version });
  } catch (_) { el.className = 'status bad'; $('span', el).textContent = t('status.down'); }
}
function applyStatic() {
  $$('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  $$('[data-i18n-aria]').forEach(el => el.setAttribute('aria-label', t(el.dataset.i18nAria)));
  $$('[data-i18n-title]').forEach(el => { el.title = t(el.dataset.i18nTitle); });
  $$('[data-lang]').forEach(b => { b.classList.toggle('on', b.dataset.lang === LANG); b.setAttribute('aria-pressed', b.dataset.lang === LANG); });
}
$$('[data-lang]').forEach(b => b.onclick = () => {
  if (b.dataset.lang === LANG) return;
  setLang(b.dataset.lang); applyStatic(); pollStatus(); drawAlerts();
  if (route().view === 'check' && S.job) { if (S.job.status === 'processing') renderProcessing(); else renderResultKeepPlayer(); }
  else render();
});
function applyTheme() {
  const dark = document.documentElement.dataset.theme === 'dark';
  $('#themeBtn').innerHTML = icon(dark ? 'sun' : 'moon');
}
$('#themeBtn').onclick = () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next; try { localStorage.setItem('cg_theme', next); } catch (_) { }
  applyTheme();
};

/* ---------- uploads (any page) ---------- */
$('#filePick').onchange = e => { uploadFiles([...e.target.files]); e.target.value = ''; };
function pickFiles() { $('#filePick').click(); }
function uploadFiles(files) {
  const ok = files.filter(f => /\.(mov|mp4|m4v)$/i.test(f.name));
  files.filter(f => !ok.includes(f)).forEach(f => toast(t('up.notVideo', { name: f.name }), 'err'));
  if (!ok.length) return;
  const single = ok.length === 1;
  ok.forEach(f => uploadOne(f, single));
  if (route().view !== 'checks') go('/'); else renderChecks();
}
function uploadOne(file, openAfter) {
  const key = `u${Date.now()}${Math.random().toString(16).slice(2, 6)}`;
  S.uploads[key] = { name: file.name, sent: 0, total: file.size };
  const fd = new FormData(); fd.append('file', file, file.name);
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/ui/api/analyze');
  xhr.upload.onprogress = e => { if (e.lengthComputable) { S.uploads[key].sent = e.loaded; if (route().view === 'checks') drawTable(); } };
  xhr.onload = () => {
    delete S.uploads[key];
    let body = {}; try { body = JSON.parse(xhr.responseText); } catch (_) { }
    if (xhr.status !== 200) { toast(`${file.name}: ${body.detail || t('up.failed')}`, 'err'); refreshJobs(); return; }
    S.local[body.job_id] = URL.createObjectURL(file);
    if (openAfter) go(`/?check=${body.job_id}`); else refreshJobs();
  };
  xhr.onerror = () => { delete S.uploads[key]; toast(`${file.name}: ${t('up.network')}`, 'err'); refreshJobs(); };
  xhr.send(fd);
}
function bindDrop(el) {
  ['dragenter', 'dragover'].forEach(ev => el.addEventListener(ev, e => { e.preventDefault(); el.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => el.addEventListener(ev, e => { e.preventDefault(); el.classList.remove('over'); }));
  el.addEventListener('drop', e => uploadFiles([...e.dataTransfer.files]));
  el.addEventListener('click', e => { if (!e.target.closest('button')) pickFiles(); });
}
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('drop', e => { e.preventDefault(); if (!e.target.closest('.drop') && e.dataTransfer.files.length) uploadFiles([...e.dataTransfer.files]); });

/* ---------- checks list ---------- */
const isActive = j => j.public_status === 'processing';
const needsReview = j => j.verdict === 'violation' && j.public_status === 'done' && (j.reviewed || 0) < j.n_violations;
const FILTERS = {
  all: () => true, review: needsReview,
  violation: j => j.verdict === 'violation' && j.public_status === 'done',
  clear: j => j.verdict === 'no_violation' && j.public_status === 'done',
};
async function refreshJobs() {
  try { S.jobs = (await api('/ui/api/jobs?limit=200')).jobs; } catch (_) { /* keep old */ }
  if (route().view === 'checks') drawChecks();
}
function renderChecks() {
  $('#main').innerHTML = `<div class="page">
    <div class="page-head">
      <div><h1>${t('checks.title')}</h1><p>${t('checks.lead')}</p></div>
      <button class="btn primary lg" id="upBtn">${icon('up')}${t('checks.upload')}</button>
    </div>
    <div id="checksBody"></div>
  </div>`;
  $('#upBtn').onclick = pickFiles;
  drawChecks(); refreshJobs();
}
function drawChecks() {
  const body = $('#checksBody'); if (!body) return;
  const jobs = S.jobs, nUp = Object.keys(S.uploads).length;
  clearTimeout(S.listTimer);
  S.listTimer = setTimeout(refreshJobs, jobs.some(isActive) || nUp ? 2000 : 15000);
  if (!jobs.length && !nUp) {
    body.innerHTML = `<div class="drop big" id="drop"><span class="up">${icon('up')}</span><b>${t('drop.bigTitle')}</b>
      <small>${t('drop.bigHint')}</small>
      <button class="btn primary" id="dropBtn">${t('drop.choose')}</button></div>
      <p class="muted" style="display:flex;gap:8px;align-items:center;justify-content:center">${icon('lock')}${t('drop.privacy')}</p>`;
    bindDrop($('#drop')); $('#dropBtn').onclick = pickFiles; return;
  }
  const cnt = k => jobs.filter(FILTERS[k]).length;
  body.innerHTML = `
    <div class="drop" id="drop"><span class="up">${icon('up')}</span><div><b>${t('drop.title')}</b><small>${t('drop.hint')}</small></div></div>
    <div class="stats">
      ${[['all', ''], ['review', 'attn'], ['violation', 'warn'], ['clear', 'ok']]
        .map(([k, c]) => `<button class="stat ${c} ${S.filter === k ? 'on' : ''}" data-f="${k}"><div class="n">${cnt(k)}</div><div class="l">${t(`f.${k}`)}</div></button>`).join('')}
    </div>
    <div class="toolbar"><label class="search">${icon('search')}<input class="field" id="q" placeholder="${t('search')}" value="${esc(S.q)}"></label></div>
    <div class="card" id="tableCard"></div>`;
  bindDrop($('#drop'));
  $$('[data-f]', body).forEach(b => b.onclick = () => { S.filter = b.dataset.f; drawChecks(); });
  $('#q').oninput = e => { S.q = e.target.value; drawTable(); };
  drawTable();
}
function statusCell(j) {
  if (j.public_status === 'processing') {
    const queued = j.status === 'queued';
    return `<span class="pill info">${queued ? `${t('pill.queued')}${j.queue_position ? ` · ${t('pill.ahead', { n: j.queue_position })}` : ''}` : t('pill.analyzing', { p: Math.round((j.progress || 0) * 100) })}</span>
      <div class="minibar"><i style="width:${queued ? 3 : Math.max(4, (j.progress || 0) * 100)}%"></i></div>`;
  }
  const part = j.partial ? ` <span class="pill neutral">${t('pill.partial')}</span>` : '';
  if (j.public_status === 'failed') return `<span class="pill bad">${icon('x')}${t('pill.failed')}</span>`;
  if (j.verdict === 'violation') return `<span class="pill warn">${icon('alert')}${t('pill.violations', { n: j.n_violations })}</span>${part}`;
  return `<span class="pill ok">${icon('shield')}${t('pill.clear')}</span>${part}`;
}
function reviewCell(j) {
  if (j.public_status !== 'done' || j.verdict !== 'violation') return '<span class="muted">—</span>';
  if ((j.reviewed || 0) >= j.n_violations) return `<span class="pill ok">${icon('check')}${t('pill.reviewed')}</span>`;
  return `<span class="muted">${t('rev.progress', { a: j.reviewed || 0, b: j.n_violations })}</span>`;
}
function drawTable() {
  const card = $('#tableCard'); if (!card) return;
  const q = S.q.trim().toLowerCase();
  const ups = Object.values(S.uploads);
  const rows = S.jobs.filter(FILTERS[S.filter]).filter(j => !q || (j.filename || '').toLowerCase().includes(q));
  if (!rows.length && !ups.length) {
    card.innerHTML = `<div class="empty"><b>${t(S.filter === 'review' ? 'empty.review' : 'empty.none')}</b>${t(S.filter === 'all' && !q ? 'empty.start' : 'empty.other')}</div>`; return;
  }
  card.innerHTML = `<table class="table"><thead><tr><th>${t('th.recording')}</th><th class="c-when">${t('th.uploaded')}</th><th>${t('th.result')}</th><th>${t('th.review')}</th><th></th></tr></thead><tbody>
    ${ups.map(u => `<tr><td><div class="fname"><span class="ic">${icon('up')}</span><div><b>${esc(u.name)}</b><small>${t('row.uploading', { a: (u.sent / 1e6).toFixed(1), b: (u.total / 1e6).toFixed(1) })}</small></div></div></td>
      <td class="c-when muted">${t('now')}</td><td><span class="pill info">${t('pill.uploading', { p: Math.round(u.sent / Math.max(1, u.total) * 100) })}</span><div class="minibar"><i style="width:${u.sent / Math.max(1, u.total) * 100}%"></i></div></td><td></td><td></td></tr>`).join('')}
    ${rows.map(j => `<tr data-open="${j.job_id}">
      <td><div class="fname"><span class="ic">${icon('film')}</span><div><b title="${esc(j.filename)}">${esc(j.filename)}</b><small class="mono">${j.duration_sec ? tc(j.duration_sec) : ''}${j.processing_sec ? ` · ${t('row.analysedIn', { s: j.processing_sec })}` : ''}</small></div></div></td>
      <td class="c-when muted">${ago(j.created_at)}</td>
      <td>${statusCell(j)}</td>
      <td>${reviewCell(j)}</td>
      <td class="c-acts"><div class="row-acts">
        ${needsReview(j) ? `<a class="btn sm primary" href="/?check=${j.job_id}">${t('act.review')}</a>` : `<a class="btn sm" href="/?check=${j.job_id}">${t('act.open')}</a>`}
        ${j.public_status === 'done' ? `<a class="icon-btn" href="${reportUrl(j.job_id)}" target="_blank" rel="noopener" title="${t('act.report')}" aria-label="${t('act.openReport')}">${icon('doc')}</a>` : ''}
        <button class="icon-btn danger" data-del="${j.job_id}" title="${t(isActive(j) ? 'act.cancelDelete' : 'act.delete')}" aria-label="${t('act.delete')}">${icon('trash')}</button>
      </div></td></tr>`).join('')}
  </tbody></table>`;
  $$('tr[data-open]', card).forEach(tr => tr.onclick = e => { if (!e.target.closest('a,button')) go(`/?check=${tr.dataset.open}`); });
  $$('[data-del]', card).forEach(b => b.onclick = () => deleteJob(S.jobs.find(j => j.job_id === b.dataset.del)));
}
async function deleteJob(j, after) {
  if (!j) return;
  const active = j.public_status === 'processing' || j.status === 'queued' || j.status === 'running';
  const ok = await confirmBox(t(active ? 'del.cancelTitle' : 'del.deleteTitle'),
    `<b>${esc(j.filename)}</b><br>${t(active ? 'del.cancelText' : 'del.deleteText')}`,
    t(active ? 'del.cancelBtn' : 'act.delete'));
  if (!ok) return;
  try {
    await api(`/ui/api/jobs/${j.job_id}`, { method: 'DELETE' });
    S.jobs = S.jobs.filter(x => x.job_id !== j.job_id);
    toast(t(active ? 'del.cancelled' : 'del.deleted'));
    after ? after() : drawChecks();
  } catch (e) { toast(e.message, 'err'); }
}

/* ---------- check page ---------- */
const viols = () => (S.job && S.job.violations) || [];
const dur = () => Math.max(0.1, +(S.job && S.job.duration_sec) || +(((S.job || {}).meta || {}).duration_sec) || 0.1);
async function openCheck(id, keepPosition) {
  const fresh = !S.job || S.job.job_id !== id;
  if (fresh) { leaveCheck(); $('#main').innerHTML = `<div class="page"><p class="muted">${t('loading')}</p></div>`; }
  let j;
  try { j = await api(`/ui/api/jobs/${id}`); }
  catch (e) {
    $('#main').innerHTML = `<div class="page"><a class="crumb" href="/">${icon('back')}${t('crumb')}</a><div class="card empty"><b>${t(e.status === 404 ? 'chk.gone' : 'chk.loadErr')}</b>${e.status === 404 ? t('chk.goneHint') : esc(e.message)}</div></div>`;
    return;
  }
  S.job = j;
  if (j.status === 'processing') { renderProcessing(); follow(id); return; }
  if (!keepPosition) { S.sel = 0; S.t = viols().length ? Math.max(0, viols()[0].timecode_sec - 1) : 0; }
  renderResult();
}
function follow(id) {
  if (S.poll) clearInterval(S.poll);
  S.poll = setInterval(async () => {
    try { const j = await api(`/ui/api/jobs/${id}`); if (!S.job || S.job.job_id !== id) return; S.job = j; if (j.status !== 'processing') finish(id); else updateProcessing(); }
    catch (e) { if (e.status === 404) { leaveCheck(); go('/'); } }
  }, 2000);
  if (!S.sse) {
    try {
      const es = new EventSource(`/ui/api/jobs/${id}/events`); S.sse = es;
      es.addEventListener('progress', e => { const d = JSON.parse(e.data); if (S.job && S.job.job_id === id) { S.job.stage = d.stage; S.job.progress = d.progress; updateProcessing(); } });
      ['done', 'failed'].forEach(t => es.addEventListener(t, () => finish(id)));
      es.onerror = () => { };
    } catch (_) { }
  }
}
async function finish(id) {
  if (S.sse) { S.sse.close(); S.sse = null; }
  if (S.poll) { clearInterval(S.poll); S.poll = null; }
  if (!S.job || S.job.job_id !== id) return;
  S.job = null;
  await openCheck(id);
  if (S.job) toast(S.job.verdict === 'violation' ? t('toast.found', { n: viols().length }) : t('toast.clear'));
}
function checkHead(j, extra = '') {
  const meta = [j.duration_sec ? t('meta.long', { t: tc(j.duration_sec) }) : '', j.created_at ? t('meta.uploaded', { ago: ago(j.created_at) }) : '', j.processing_sec ? t('meta.analysed', { s: j.processing_sec }) : ''].filter(Boolean).join(' · ');
  return `<a class="crumb" href="/">${icon('back')}${t('crumb')}</a>
    <div class="check-head"><div><h1>${esc(j.filename)}</h1><div class="meta">${meta}</div></div>
      <div class="acts">${extra}<button class="btn danger" id="delBtn">${icon('trash')}${t(j.status === 'processing' ? 'del.cancelBtn' : 'act.delete')}</button></div></div>`;
}
const STEPS = ['queued', 'frames', 'detection', 'vlm', 'report', 'done'];
function renderProcessing() {
  const j = S.job;
  $('#main').innerHTML = `<div class="page">${checkHead(j)}
    <div class="card proc"><h2 id="pTitle">${t('proc.title')}</h2><p class="muted" id="pSub">${t('proc.sub')}</p>
      <div class="bigbar"><i id="pBar"></i></div>
      <div class="steps">${STEPS.map(k => `<div class="step" data-step="${k}"><b>${t(`step.${k}`)}</b><span class="st"></span></div>`).join('')}</div>
      <div class="proc-foot"><span id="pEta"></span><span class="sp"></span>${S.local[j.job_id] ? `<span>${t('proc.preview')}</span>` : ''}</div>
      ${S.local[j.job_id] ? `<video src="${S.local[j.job_id]}" controls muted playsinline style="width:100%;max-height:360px;border-radius:9px;background:#0D0B10;margin-top:12px"></video>` : ''}
    </div></div>`;
  $('#delBtn').onclick = () => deleteJob({ ...j, public_status: 'processing' }, () => go('/'));
  updateProcessing();
}
function updateProcessing() {
  const j = S.job; if (!j || !$('#pBar')) return;
  const stage = j.stage === 'started' || j.stage === 'retry' ? 'queued' : (j.stage || 'queued');
  const ci = Math.max(0, STEPS.indexOf(stage));
  $('#pBar').style.width = `${Math.max(3, (j.progress || 0) * 100)}%`;
  $$('.step').forEach((el, i) => { el.className = 'step' + (i < ci ? ' done' : i === ci ? ' now' : ''); $('.st', el).textContent = i === ci && i > 0 ? `${Math.round((j.progress || 0) * 100)}%` : ''; });
  $('#pTitle').textContent = j.status === 'processing' && stage === 'queued' ? (j.queue_position ? t('proc.queue', { n: j.queue_position }) : t('proc.starting')) : t('proc.title');
  $('#pEta').textContent = j.eta_sec != null ? t('proc.eta', { s: j.eta_sec }) : '';
  if (j.stage === 'retry') $('#pSub').textContent = t('proc.retry');
}

function renderResult() {
  const j = S.job, vs = viols(), n = vs.length, failed = j.status === 'failed';
  const dec = j.decisions || {}, reviewed = vs.filter((_, i) => dec[i]).length;
  let verdict;
  if (failed) verdict = `<div class="verdict fail"><span class="vi">${icon('x')}</span><div><h2>${t('v.failTitle')}</h2><p>${t('v.failText', { err: esc(j.error || t('v.unknownErr')) })}</p></div></div>`;
  else if (n) verdict = `<div class="verdict ${reviewed === n ? 'done' : 'bad'}"><span class="vi">${icon(reviewed === n ? 'check' : 'alert')}</span>
      <div><h2>${t(reviewed === n ? 'v.doneTitle' : 'v.badTitle')}</h2><p>${reviewed === n ? t('v.doneText', { c: vs.filter((_, i) => dec[i] === 'confirm').length, d: vs.filter((_, i) => dec[i] && dec[i] !== 'confirm').length }) : t('v.badText', { n })}</p></div>
      <div class="rv"><b>${t('rev.progress', { a: reviewed, b: n })}</b><div class="minibar"><i style="width:${reviewed / n * 100}%"></i></div></div></div>`;
  else verdict = `<div class="verdict ok"><span class="vi">${icon('shield')}</span><div><h2>${t('v.okTitle')}</h2><p>${t('v.okText')}</p></div></div>`;
  const note = j.partial ? `<div class="note">${icon('alert')}<span>${t('v.partial')}</span></div>` : '';
  $('#main').innerHTML = `<div class="page">
    ${checkHead(j, j.status === 'done' ? `<a class="btn ${n && reviewed === n ? 'primary' : ''}" href="${reportUrl(j.job_id)}" target="_blank" rel="noopener">${icon('doc')}${t('act.report')}</a>` : '')}
    ${verdict}${note}
    <div class="layout">
      <div class="card player-card">
        <div class="player" id="player"></div>
        <div class="scrub" id="scrub"></div>
        <div class="pctrl"><button class="icon-btn" id="pp" aria-label="${t('p.play')}">${icon('play')}</button><span class="time"><b id="tnow">${tc(S.t)}</b> / ${tc(dur())}</span></div>
        ${n ? `<div class="keys-hint">${t('keys')}</div>` : ''}
      </div>
      <div><div class="findings" id="findings"></div>${techHtml(j)}</div>
    </div></div>`;
  $('#delBtn').onclick = () => deleteJob({ ...j, public_status: j.status }, () => go('/'));
  renderPlayer(); drawScrub(); drawFindings();
  $('#pp').onclick = togglePlay;
}
const shortDesc = d => String(d || '').split(/\s*Основание:/)[0].replace(/\s*Прямой публичной нормы не установлено\.?$/, '').trim();
const observedPart = d => { const p = shortDesc(d).split(/\s*Это может указывать на нарушение:\s*/); return p.length > 1 ? p[0].replace(/\.$/, '') : ''; };
function descHtml(v) {
  const why = typeField(v.type_code, 'why');
  if (LANG === 'ru' || !why) return `<p class="label">${t('f.seen')}</p><p class="desc" lang="ru">${esc(shortDesc(v.description))}</p>`;
  const obs = observedPart(v.description);
  return `<p class="label">${t('f.why')}</p><p class="desc">${esc(why)}</p>${obs ? `<p class="label">${t('f.modelNote')}</p><p class="desc muted" lang="ru">${esc(obs)}.</p>` : ''}`;
}
const refHtml = r => `<div><b>${esc(docName(r))}</b>${r.point ? `, ${esc(pointName(r.point))}` : ''}${r.quote ? `<br><q lang="ru">${esc(r.quote)}</q>${LANG !== 'ru' ? ` <small class="muted">(${t('f.quoteRu')})</small>` : ''}` : ''}${r.url ? `<br><a href="${esc(docUrl(r.url))}" target="_blank" rel="noopener">${t('f.openAdilet')} ${icon('link')}</a>` : ''}</div>`;
function drawFindings() {
  const box = $('#findings'); if (!box) return;
  const j = S.job, vs = viols(), dec = j.decisions || {};
  if (!vs.length) {
    const scenes = ((j.meta || {}).scenes || []);
    box.innerHTML = `<div class="card clear-card"><h3>${t(j.status === 'failed' ? 'c.noResult' : 'c.whatChecked')}</h3>
      <p class="muted">${j.status === 'failed' ? '' : scenes.length ? t('c.scenes', { n: scenes.length }) : t('c.scanned')}</p>
      ${scenes.length ? `<ul class="scenes">${scenes.map(s => `<li><button data-seek="${s.t}"><span class="t">${tc(s.t)}</span><span lang="ru">${esc(s.scene)}</span></button></li>`).join('')}</ul>` : ''}</div>`;
    $$('[data-seek]', box).forEach(b => b.onclick = () => seek(+b.dataset.seek, true));
    return;
  }
  box.innerHTML = vs.map((v, i) => {
    const d = dec[i], rule = v.rule || {}, refs = rule.refs || [], frames = v.evidence_frames || [];
    const ruleTitle = refs.length ? `${refs[0].point ? pointName(refs[0].point) + ' · ' : ''}${docName(refs[0])}` : t('f.internalReg');
    const caveat = typeField(v.type_code, 'caveat', rule.caveat);
    return `<article class="card find ${i === S.sel ? 'on' : ''} ${d === 'confirm' ? 'confirm' : d ? 'reject' : ''}" data-i="${i}">
      <div class="find-h"><span class="num">${i + 1}</span><h3>${esc(typeName(v.type_code, v.type))}</h3>
        <div class="tc"><button class="btn sm" data-seek="${v.timecode_sec}">${icon('play')}<span class="mono">${tc(v.timecode_sec)}</span></button></div></div>
      <div class="find-b">
        <div class="frames">${frames.map((f, k) => `<button class="frame ${Math.abs(f.timestamp_sec - v.timecode_sec) < .3 ? 'key' : ''}" data-zoom="${i}:${k}" title="${t('f.enlarge')}"><img src="data:image/jpeg;base64,${f.image_base64}" alt="${t('f.frameAt', { t: tc(f.timestamp_sec) })}"><span>${tc(f.timestamp_sec)}</span></button>`).join('')}</div>
        <div>
          ${descHtml(v)}
          <details class="rule"><summary>${icon('chev')}<span>${t('f.rule')}: <b>${esc(ruleTitle)}</b></span>${rule.kind ? ` <span class="kind ${esc(rule.kind)}">${esc(kindLabel(rule.kind))}</span>` : ''}</summary>
            <div class="rb">${refs.map(refHtml).join('') || `<div>${t('f.noPublic')}</div>`}
            ${caveat ? `<div class="caveat">${esc(caveat)}</div>` : ''}${(j.clips || []).includes(i) ? `<a href="/ui/api/jobs/${j.job_id}/violations/${i}/clip.mp4" target="_blank" rel="noopener">${icon('clip')} ${t('f.clip')}</a>` : ''}</div></details>
        </div>
      </div>
      <div class="find-f">${d ? `<div class="decided">${d === 'confirm' ? `<span class="pill bad">${icon('check')}${t('f.confirmed')}</span>` : `<span class="pill neutral">${icon('x')}${t('f.notViolation')}</span>`}<button class="btn sm ghost" data-dec="${i}:clear">${t('f.undo')}</button></div>`
        : `<span class="q">${t('f.question')}</span><button class="btn sm yes" data-dec="${i}:confirm">${icon('check')}${t('f.yes')}</button><button class="btn sm no" data-dec="${i}:reject">${icon('x')}${t('f.no')}</button>`}
        <span class="sp"></span>${v.confidence != null ? `<span class="muted" style="font-size:12.5px">${t('f.confidence', { p: Math.round(v.confidence * 100) })}</span>` : ''}</div>
    </article>`;
  }).join('');
  $$('[data-seek]', box).forEach(b => b.onclick = e => { e.stopPropagation(); const i = +b.closest('[data-i]').dataset.i; select(i, false); seek(Math.max(0, +b.dataset.seek - 1), true); });
  $$('[data-zoom]', box).forEach(b => b.onclick = e => { e.stopPropagation(); const [i, k] = b.dataset.zoom.split(':').map(Number); const f = vs[i].evidence_frames[k]; zoom(`data:image/jpeg;base64,${f.image_base64}`, `${S.job.filename} · ${tc(f.timestamp_sec)}`); });
  $$('[data-dec]', box).forEach(b => b.onclick = e => { e.stopPropagation(); const [i, d] = b.dataset.dec.split(':'); decide(+i, d); });
  $$('.find', box).forEach(c => c.onclick = e => { if (!e.target.closest('button,a,summary')) select(+c.dataset.i, true); });
}
async function decide(i, d) {
  try {
    await api(`/ui/api/jobs/${S.job.job_id}/feedback`, { method: 'POST', json: { violation_index: i, decision: d } });
    const dec = S.job.decisions = S.job.decisions || {};
    if (d === 'clear') delete dec[i]; else dec[i] = d;
    const vs = viols();
    const next = vs.findIndex((_, k) => k > i && !dec[k]);
    renderResultKeepPlayer();
    if (d !== 'clear' && next >= 0) select(next, true);
    else if (d !== 'clear' && vs.every((_, k) => dec[k])) toast(t('toast.allReviewed'));
  } catch (e) { toast(t('toast.saveErr', { e: e.message }), 'err'); }
}
function renderResultKeepPlayer() {
  const vid = $('#vid'), t = vid ? vid.currentTime : S.t;
  S.t = t; renderResult();
}
function select(i, jump) {
  if (!viols().length) return;
  S.sel = i;
  $$('.find').forEach(c => c.classList.toggle('on', +c.dataset.i === i));
  drawScrub();
  const card = $(`.find[data-i="${i}"]`); card && card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  if (jump) seek(Math.max(0, viols()[i].timecode_sec - 1), false);
}
function techHtml(j) {
  const m = j.meta || {}, tl = j.timeline && Array.isArray(j.timeline.t) ? j.timeline : null;
  const lanes = ['people', 'screen_on', 'phone', 'drink', 'bag'].filter(k => tl && Array.isArray(tl[k])).map(k => [k, t(`lane.${k}`)]);
  const D = dur();
  const lane = k => {
    const vals = tl[k]; let inner = '', start = null;
    if (k === 'people') {
      let d = 'M0 16'; tl.t.forEach((t, i) => { const x = (t / D * 1000).toFixed(1), y = (16 - Math.min(3, vals[i] || 0) / 3 * 13).toFixed(1); d += ` L${x} ${y}`; });
      inner = `<path d="${d} L1000 16 Z" fill="var(--info)" fill-opacity=".25" stroke="var(--info)" vector-effect="non-scaling-stroke"/>`;
    } else {
      const push = (a, b) => { inner += `<rect x="${(a / D * 1000).toFixed(1)}" y="3" width="${Math.max(2, (b - a) / D * 1000).toFixed(1)}" height="10" rx="2" fill="var(--warn)"/>`; };
      tl.t.forEach((t, i) => { if (vals[i] && start === null) start = t; if (!vals[i] && start !== null) { push(start, t); start = null; } }); if (start !== null) push(start, D);
    }
    return `<svg viewBox="0 0 1000 16" preserveAspectRatio="none">${inner}</svg>`;
  };
  return `<details class="tech card"><summary style="padding:12px 18px">${icon('chev')}${t('tech.title')}</summary><div class="tech-body">
    <div class="kv"><div>${t('kv.analyzer')}<b>${esc(j.analyzer || '—')}</b></div><div>${t('kv.frames')}<b>${m.frames ?? '—'}</b></div><div>${t('kv.moments')}<b>${(m.candidates || []).length || '—'}</b></div><div>${t('kv.calls')}<b>${m.vlm_calls ?? '—'}</b></div><div>${t('kv.time')}<b>${j.processing_sec ?? '—'} ${t('sec')}</b></div><div>${t('kv.id')}<b>${esc(j.job_id)}</b></div></div>
    ${lanes.length ? `<div><p class="label">${t('tech.signals')}</p><div class="lanes">${lanes.map(([k, l]) => `<div class="lrow"><span class="lab">${l}</span><div class="track">${lane(k)}</div></div>`).join('')}</div></div>` : ''}
    ${(m.scenes || []).length ? `<div><p class="label">${t('tech.saw')}</p><ul class="scenes">${m.scenes.map(s => `<li><button data-seek="${s.t}"><span class="t">${tc(s.t)}</span><span lang="ru">${esc(s.scene)}</span></button></li>`).join('')}</ul></div>` : ''}
    ${j.warning ? `<div class="muted" style="font-size:12.5px">${esc(j.warning)}</div>` : ''}
  </div></details>`;
}

/* player */
function renderPlayer() {
  const p = $('#player'); if (!p) return;
  const j = S.job, v = viols()[S.sel];
  const poster = v && v.evidence_frames && v.evidence_frames.length ? `data:image/jpeg;base64,${v.evidence_frames[0].image_base64}` : '';
  const src = S.local[j.job_id] || (j.video_available !== false ? `/ui/api/jobs/${j.job_id}/video` : '');
  if (!src) { p.innerHTML = `${poster ? `<img src="${poster}" alt="" style="width:100%;height:100%;object-fit:contain">` : ''}<div class="no-video">${icon('film')}<b>${t('p.removed')}</b><span>${t('p.removedHint')}</span></div>`; return; }
  p.innerHTML = `<video id="vid" playsinline preload="auto" muted ${poster ? `poster="${poster}"` : ''}></video>`;
  const vid = $('#vid'); vid.src = src;
  vid.addEventListener('loadedmetadata', () => { vid.currentTime = Math.max(0.01, S.t); });
  vid.addEventListener('error', () => p.insertAdjacentHTML('beforeend', `<div class="no-video">${icon('film')}<b>${t('p.cantPlay')}</b><span>${t('p.cantPlayHint')}</span></div>`));
  vid.addEventListener('timeupdate', () => { S.t = vid.currentTime; tick(); });
  vid.addEventListener('play', () => { S.playing = true; syncPlay(); });
  vid.addEventListener('pause', () => { S.playing = false; syncPlay(); });
  vid.onclick = togglePlay;
}
function drawScrub() {
  const s = $('#scrub'); if (!s) return;
  const D = dur(), dec = (S.job && S.job.decisions) || {};
  s.innerHTML = `<div class="rail"></div><div class="fill" id="fill" style="width:${S.t / D * 100}%"></div>
    ${viols().map((v, i) => `<button class="mk ${i === S.sel ? 'on' : ''} ${dec[i] === 'confirm' ? 'confirm' : dec[i] ? 'done' : ''}" style="left:${v.timecode_sec / D * 100}%" data-mk="${i}" title="${esc(typeName(v.type_code, v.type))} · ${tc(v.timecode_sec)}">${i + 1}</button>`).join('')}
    <div class="head" id="head" style="left:${S.t / D * 100}%"></div>`;
  $$('[data-mk]', s).forEach(b => b.onclick = e => { e.stopPropagation(); select(+b.dataset.mk, true); });
  const at = e => { const r = s.getBoundingClientRect(); seek(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * D, true); };
  s.onpointerdown = e => { if (e.target.closest('button')) return; at(e); s.setPointerCapture(e.pointerId); s.onpointermove = at; };
  s.onpointerup = () => { s.onpointermove = null; };
}
function tick() {
  const D = dur(), pct = `${S.t / D * 100}%`;
  const h = $('#head'), f = $('#fill'), t = $('#tnow');
  if (h) h.style.left = pct; if (f) f.style.width = pct; if (t) t.textContent = tc(S.t);
  if (S.playing) {
    const near = viols().findIndex(v => S.t >= v.timecode_sec - 1 && S.t <= v.timecode_sec + 2);
    if (near >= 0 && near !== S.sel) { S.sel = near; $$('.find').forEach(c => c.classList.toggle('on', +c.dataset.i === near)); $$('[data-mk]').forEach(m => m.classList.toggle('on', +m.dataset.mk === near)); }
  }
}
function seek(t, play) {
  S.t = Math.min(dur(), Math.max(0, t));
  const vid = $('#vid');
  if (vid && vid.readyState > 0) { vid.currentTime = S.t; if (play) vid.play().catch(() => { }); }
  tick();
}
function togglePlay() { const v = $('#vid'); if (!v) return; if (v.paused) { if (v.ended) v.currentTime = 0; v.play().catch(() => { }); } else v.pause(); }
function syncPlay() { const b = $('#pp'); if (b) { b.innerHTML = icon(S.playing ? 'pause' : 'play'); b.setAttribute('aria-label', t(S.playing ? 'p.pause' : 'p.play')); } }
document.addEventListener('keydown', e => {
  if (e.target.closest('input,textarea,select') || !$('#modal').hidden) return;
  if (e.key === 'Escape') { $('#lightbox').hidden = true; return; }
  if (route().view !== 'check' || !S.job || S.job.status !== 'done') return;
  const n = viols().length;
  if (e.key === ' ') { e.preventDefault(); togglePlay(); }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); seek(S.t - 1); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); seek(S.t + 1); }
  else if (!n) return;
  else if (e.key === 'n' || e.key === 'N') select((S.sel + 1) % n, true);
  else if (e.key === 'p' || e.key === 'P') select((S.sel - 1 + n) % n, true);
  else if (e.key === 'c' || e.key === 'C') decide(S.sel, 'confirm');
  else if (e.key === 'r' || e.key === 'R') decide(S.sel, 'reject');
});

/* ---------- live monitoring ---------- */
async function renderLive() {
  $('#main').innerHTML = `<div class="page">
    <div class="page-head"><div><h1>${t('live.title')}</h1><p>${t('live.lead')}</p></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn" id="lapBtn">${icon('cam')}${t('live.useCam')}</button><button class="btn primary" id="addCamBtn">${icon('plus')}${t('live.addCam')}</button></div></div>
    <div class="live-grid"><div class="wall" id="wall"></div>
      <aside class="card alerts"><div class="alerts-h"><h2>${t('live.alerts')}</h2><div class="seg"><button data-at="open">${t('live.open')}</button><button data-at="all">${t('live.all')}</button></div></div><div class="alert-list" id="alertList"></div></aside></div></div>`;
  $('#addCamBtn').onclick = addCamera;
  $('#lapBtn').onclick = () => S.laptop ? stopLaptop() : startLaptop();
  $$('[data-at]').forEach(b => b.onclick = () => { S.alertsTab = b.dataset.at; drawAlerts(); });
  await loadCameras(true); loadAlerts();
}
async function loadCameras(force) {
  try { S.cams = (await api('/ui/api/cameras')).cameras; } catch (_) { S.cams = []; }
  const sig = JSON.stringify(S.cams.map(c => [c.id, c.name])) + !!S.laptop;
  if (route().view === 'live' && (force || sig !== S.wallSig)) drawWall();
  S.wallSig = sig;
}
function drawWall() {
  const wall = $('#wall'); if (!wall) return;
  const ids = new Set(S.cams.map(c => c.id));
  Object.keys(S.camWs).forEach(id => { if (!ids.has(id)) { S.camWs[id].onclose = null; S.camWs[id].close(); delete S.camWs[id]; } });
  const tiles = S.cams.map(c => `<div class="tile" id="tile-${c.id}"><canvas id="cv-${c.id}"></canvas>
      <div class="tile-bar"><span class="rec ${c.state.status === 'online' ? '' : 'off'}"></span><span>${esc(c.name)}</span><span class="sp"></span><small id="st-${c.id}">${esc(tx(`cam.${c.state.status}`, c.state.status))}</small><button class="icon-btn" data-rm="${c.id}" title="${t('live.removeCam')}">${icon('x')}</button></div>
      <div class="tile-foot" id="ft-${c.id}"></div></div>`);
  if (S.laptop) tiles.unshift(`<div class="tile" id="tile-laptop"><canvas id="cv-laptop"></canvas><div class="tile-bar"><span class="rec"></span><span>${t('live.thisComputer')}</span><span class="sp"></span><small id="st-laptop">—</small><button class="icon-btn" id="lapStop" title="${t('live.stop')}">${icon('x')}</button></div><div class="tile-foot" id="ft-laptop"></div></div>`);
  if (!tiles.length) tiles.push(`<div class="tile-add"><span class="ic">${icon('cam')}</span><b>${t('live.noCams')}</b><span>${t('live.noCamsHint')}</span><button class="btn primary" id="addCam2">${icon('plus')}${t('live.addCam')}</button></div>`);
  wall.innerHTML = tiles.join('');
  S.cams.forEach(c => { if (!S.camWs[c.id]) openCamWs(c.id); });
  $$('[data-rm]', wall).forEach(b => b.onclick = () => removeCamera(b.dataset.rm));
  const a2 = $('#addCam2'); if (a2) a2.onclick = addCamera;
  const ls = $('#lapStop'); if (ls) ls.onclick = () => stopLaptop();
  $('#lapBtn').innerHTML = S.laptop ? `${icon('x')}${t('live.stopCam')}` : `${icon('cam')}${t('live.useCam')}`;
}
function adminField() { return adminKey() ? '' : `<label for="mKey">${t('adm.label')}</label><input class="field mono" id="mKey" placeholder="ADMIN_KEY · storage/api_key.txt" autocomplete="off"><small class="muted">${t('adm.saved')}</small>`; }
function saveAdminKey(c) { const k = $('#mKey', c); if (k && k.value.trim()) { try { localStorage.setItem('cg_admin_key', k.value.trim()); } catch (_) { } } }
async function addCamera() {
  await modal(`<h3>${t('live.addCam')}</h3><p>${t('cam.addText')}</p>
    <div class="form"><label for="mName">${t('cam.name')}</label><input class="field" id="mName" placeholder="${t('cam.namePh')}">
      <label for="mUrl">${t('cam.address')}</label><input class="field mono" id="mUrl" placeholder="rtsp://10.20.4.17:554/stream1" spellcheck="false">${adminField()}</div>
    <div class="acts"><button class="btn" data-close>${t('cancel')}</button><button class="btn primary" id="mOk">${t('cam.connect')}</button></div>`, (c, close) => {
    $('#mOk', c).onclick = async () => {
      const name = $('#mName', c).value.trim() || t('cam.default'), url = $('#mUrl', c).value.trim();
      if (!url) { $('#mUrl', c).focus(); return; }
      saveAdminKey(c);
      try { await api('/ui/api/cameras', { method: 'POST', admin: true, json: { name, url, fps: 4 } }); close(true); toast(t('cam.added', { n: name })); loadCameras(true); }
      catch (e) { if (e.status === 401 || e.status === 403) { try { localStorage.removeItem('cg_admin_key'); } catch (_) { } } toast(e.status === 401 || e.status === 403 ? t('cam.wrongKey') : e.message, 'err'); }
    };
  });
}
async function removeCamera(id) {
  const cam = S.cams.find(c => c.id === id);
  const ok = await confirmBox(t('cam.removeTitle'), t('cam.removeText', { name: `<b>${esc(cam ? cam.name : id)}</b>` }), t('cam.remove'));
  if (!ok) return;
  if (!adminKey()) {
    const done = await modal(`<h3>${t('adm.needed')}</h3><div class="form">${adminField()}</div><div class="acts"><button class="btn" data-close>${t('cancel')}</button><button class="btn primary" id="mOk">${t('continue')}</button></div>`, (c, close) => { $('#mOk', c).onclick = () => { saveAdminKey(c); close(true); }; });
    if (!done) return;
  }
  try { await api(`/ui/api/cameras/${id}`, { method: 'DELETE', admin: true }); toast(t('cam.removed')); loadCameras(true); }
  catch (e) { if (e.status === 401 || e.status === 403) { try { localStorage.removeItem('cg_admin_key'); } catch (_) { } } toast(e.message, 'err'); }
}
function drawBoxes(ctx, dets, sx, sy) {
  dets.forEach(d => {
    const [x1, y1, x2, y2] = d.box, warn = ['phone', 'bag', 'drink', 'food'].includes(d.group);
    ctx.strokeStyle = warn ? '#F2A53C' : d.group === 'person' ? '#93ABFF' : '#62D2C4'; ctx.lineWidth = 2;
    ctx.strokeRect(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
    ctx.font = '600 12px "JetBrains Mono", monospace'; const label = `${d.label || d.group} ${(+d.score || 0).toFixed(2)}`;
    ctx.fillStyle = ctx.strokeStyle; ctx.fillRect(x1 * sx - 1, y1 * sy - 18, ctx.measureText(label).width + 10, 17); ctx.fillStyle = '#120F14'; ctx.fillText(label, x1 * sx + 4, y1 * sy - 5);
  });
}
const tags = active => (active || []).map(c => `<span class="pill ${['MOTION', 'EMPTY'].includes(c) ? 'neutral' : 'bad'}" title="${esc(typeName(c, c))}">${esc(c)}</span>`).join('');
function openCamWs(id) {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ui/api/cameras/${id}/ws`);
  S.camWs[id] = ws; const img = new Image();
  ws.onmessage = e => {
    const m = JSON.parse(e.data); if (m.type !== 'frame') return;
    img.onload = () => { const cv = $(`#cv-${id}`); if (!cv) return; if (cv.width !== img.width) { cv.width = img.width; cv.height = img.height; } const ctx = cv.getContext('2d'); ctx.drawImage(img, 0, 0); drawBoxes(ctx, m.detections || [], 1, 1); };
    img.src = `data:image/jpeg;base64,${m.frame}`;
    const st = $(`#st-${id}`); if (st) st.textContent = `${m.ms} ms`;
    const tile = $(`#tile-${id}`); if (tile) tile.classList.toggle('alarmed', (m.active || []).some(c => !['MOTION', 'EMPTY'].includes(c)));
    const ft = $(`#ft-${id}`); if (ft) ft.innerHTML = tags(m.active);
  };
  ws.onclose = () => { if (S.camWs[id] === ws) { delete S.camWs[id]; setTimeout(() => { if (route().view === 'live' && S.cams.some(c => c.id === id) && !S.camWs[id]) openCamWs(id); }, 3000); } };
}
async function startLaptop() {
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 } }, audio: false }); }
  catch (e) { toast(t('cam.denied', { e: e.message }), 'err'); return; }
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ui/api/live`);
  const video = document.createElement('video'); video.srcObject = stream; video.muted = true; video.playsInline = true; await video.play();
  S.laptop = { stream, ws, video, canvas: document.createElement('canvas'), busy: false, timer: null, dets: [], size: null };
  drawWall();
  ws.onopen = () => { S.laptop && (S.laptop.timer = setInterval(sendFrame, 333)); };
  ws.onmessage = e => {
    const m = JSON.parse(e.data), L = S.laptop; if (!L) return; L.busy = false;
    if (m.error) { toast(m.error, 'err'); return; } if (m.skipped) return;
    L.dets = m.detections || []; L.size = m.size;
    const st = $('#st-laptop'); if (st) st.textContent = `${m.ms} ms${m.busy ? ` · ${t('busy')}` : ''}`;
    const ft = $('#ft-laptop'); if (ft) ft.innerHTML = tags(m.active);
    const tile = $('#tile-laptop'); if (tile) tile.classList.toggle('alarmed', (m.active || []).some(c => !['MOTION', 'EMPTY'].includes(c)));
  };
  requestAnimationFrame(drawLaptop);
}
function sendFrame() {
  const L = S.laptop; if (!L || L.busy || L.ws.readyState !== 1 || !L.video.videoWidth) return;
  const k = Math.min(1, 640 / Math.max(L.video.videoWidth, L.video.videoHeight));
  L.canvas.width = Math.round(L.video.videoWidth * k); L.canvas.height = Math.round(L.video.videoHeight * k);
  L.canvas.getContext('2d').drawImage(L.video, 0, 0, L.canvas.width, L.canvas.height);
  L.canvas.toBlob(b => { if (b && L.ws.readyState === 1) { L.busy = true; L.ws.send(b); } }, 'image/jpeg', .75);
}
function drawLaptop() {
  const L = S.laptop; if (!L) return;
  const cv = $('#cv-laptop');
  if (cv && L.video.videoWidth) {
    const w = L.video.videoWidth, h = L.video.videoHeight; if (cv.width !== w) { cv.width = w; cv.height = h; }
    const ctx = cv.getContext('2d'); ctx.drawImage(L.video, 0, 0, w, h); if (L.size) drawBoxes(ctx, L.dets, w / L.size[0], h / L.size[1]);
  }
  requestAnimationFrame(drawLaptop);
}
function stopLaptop(silent) {
  const L = S.laptop; if (!L) return;
  clearInterval(L.timer); L.ws.onclose = null; L.ws.close(); L.stream.getTracks().forEach(t => t.stop()); S.laptop = null;
  if (!silent) drawWall();
}
async function loadAlerts() {
  try { S.alerts = (await api('/ui/api/alerts?limit=60')).alerts; } catch (_) { }
  drawAlerts();
  if (!S.alertsSse) {
    try {
      const es = new EventSource('/ui/api/alerts/stream'); S.alertsSse = es;
      const on = e => { const d = JSON.parse(e.data), a = d.alert; if (!a) return; const i = S.alerts.findIndex(x => x.id === a.id); if (i >= 0) S.alerts[i] = a; else { S.alerts.unshift(a); if (d.type === 'alert' && a.severity === 'critical') toast(t('alert.critical', { n: typeName(a.type_code, a.type_name) }), 'err'); } drawAlerts(); };
      ['alert', 'alert_update', 'alert_escalated'].forEach(t => es.addEventListener(t, on));
    } catch (_) { }
  }
}
function drawAlerts() {
  const visible = S.alerts.filter(a => a.severity !== 'info');
  const open = visible.filter(a => a.state === 'open');
  const badge = $('#alertBadge'); badge.hidden = !open.length; badge.textContent = open.length;
  const el = $('#alertList'); if (!el) return;
  $$('[data-at]').forEach(b => b.classList.toggle('on', b.dataset.at === S.alertsTab));
  const list = (S.alertsTab === 'open' ? open : visible).slice(0, 60);
  if (!list.length) { el.innerHTML = `<div class="empty"><b>${t(S.alertsTab === 'open' ? 'alerts.noneOpen' : 'alerts.none')}</b>${t('alerts.hint')}</div>`; return; }
  el.innerHTML = list.map(a => {
    const where = a.camera_name || (a.filename ? a.filename : a.camera_id) || '';
    return `<div class="al ${esc(a.severity)} ${a.state !== 'open' ? 'closed' : ''}">
      <div class="t1"><span class="pill ${a.severity === 'critical' ? 'bad' : a.severity === 'high' ? 'warn' : 'neutral'}">${esc(tx(`sev.${a.severity}`, a.severity))}</span><span class="sp"></span><span>${ago(a.created_at)}</span></div>
      <b>${esc(typeName(a.type_code, a.type_name))}</b>
      <div class="where">${esc(where)}${a.t_sec != null ? ` · ${t('alert.at', { t: tc(a.t_sec) })}` : ''}${a.count > 1 ? ` · ×${a.count}` : ''}${a.escalation_level ? ` · ${t('alert.escalated')}` : ''}</div>
      <div class="acts">${a.state === 'open' ? `<button class="btn sm primary" data-ack="${a.id}:acknowledged">${icon('check')}${t('alert.ack')}</button><button class="btn sm" data-ack="${a.id}:false_positive">${t('alert.false')}</button>`
        : `<span class="muted" style="font-size:12.5px">${t(a.state === 'false_positive' ? 'alert.markedFalse' : 'alert.acked')}${a.acked_by ? ` ${t('alert.by', { n: esc(a.acked_by) })}` : ''}</span>`}
        ${a.job_id ? `<a class="btn sm ghost" href="/?check=${a.job_id}">${t('alert.openCheck')}</a>` : ''}</div></div>`;
  }).join('');
  $$('[data-ack]', el).forEach(b => b.onclick = async () => {
    const [id, d] = b.dataset.ack.split(':');
    try { const a = await api(`/ui/api/alerts/${id}/ack`, { method: 'POST', json: { decision: d } }); const i = S.alerts.findIndex(x => x.id === a.id); if (i >= 0) S.alerts[i] = a; drawAlerts(); }
    catch (e) { toast(e.message, 'err'); }
  });
}

/* ---------- rules ---------- */
async function renderRules() {
  $('#main').innerHTML = `<div class="page"><div class="page-head"><div><h1>${t('rules.title')}</h1><p>${t('rules.lead')}</p></div></div><div class="card" id="rulesCard"><div class="empty">${t('loading')}</div></div><p class="muted" id="rulesSrc" style="margin-top:12px;font-size:13px"></p></div>`;
  if (!S.rules) { try { S.rules = await api('/ui/api/rules'); } catch (e) { $('#rulesCard').innerHTML = `<div class="empty"><b>${t('rules.loadErr')}</b>${esc(e.message)}</div>`; return; } }
  const { types, sources } = S.rules;
  $('#rulesCard').innerHTML = `<div style="overflow-x:auto"><table class="table rules-table"><thead><tr><th>${t('th.code')}</th><th>${t('th.violation')}</th><th>${t('th.looks')}</th><th>${t('th.regulation')}</th><th>${t('th.live')}</th></tr></thead><tbody>
    ${types.map(ty => `<tr style="cursor:default"><td><span class="code">${esc(ty.code)}</span></td><td><b>${esc(typeName(ty.code, ty.type))}</b><div style="margin-top:6px"><span class="kind ${esc(ty.norm_kind || 'direct')}">${esc(kindLabel(ty.norm_kind || 'direct'))}</span></div></td><td class="vis">${esc(typeField(ty.code, 'visual', ty.visual))}</td>
      <td style="font-size:13px">${(ty.refs || []).map(r => `${r.point ? `<b>${esc(pointName(r.point))}</b> — ` : ''}${esc(docName(r))}${r.url ? ` <a href="${esc(docUrl(r.url))}" target="_blank" rel="noopener">${icon('link')}</a>` : ''}`).join('<br>') || '<span class="muted">—</span>'}</td>
      <td>${LIVE_CODES.has(ty.code) ? `<span class="pill ok">${t('yes')}</span>` : `<span class="muted">${t('rules.recordings')}</span>`}</td></tr>`).join('')}</tbody></table></div>`;
  $('#rulesSrc').innerHTML = `${t('rules.sources')} ${Object.values(sources || {}).filter(s => s.url).map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label || s.short)}</a>`).join(' · ')}`;
}

/* ---------- boot ---------- */
applyStatic(); applyTheme(); pollStatus(); setInterval(pollStatus, 5000);
setInterval(() => { if (route().view === 'live') loadCameras(); }, 10000);
loadAlerts();
kbReady.then(render);
