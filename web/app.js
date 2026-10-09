const app = document.querySelector('#app');
const modal = document.querySelector('#modal');
let token = '', projects = [], view = null;
let pid = '', reviewer = '', selected = '', tab = 'screen', blinded = true, query = '', filter = 'all', pdfMode = false;
const escape = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const el = (id) => document.getElementById(id);
const value = (id) => el(id).value;
const button = (id, fn) => { const node = document.getElementById(id); if (node)
    node.addEventListener('click', async () => { if (node instanceof HTMLButtonElement)
        node.disabled = true; try {
        await fn();
    }
    catch (e) {
        fail(e);
    }
    finally {
        if (node instanceof HTMLButtonElement)
            node.disabled = false;
    } }); };
const safeUrl = (raw) => { try {
    const u = new URL(raw);
    return ['http:', 'https:'].includes(u.protocol) ? escape(u.href) : '';
}
catch {
    return '';
} };
function message(text, error = false) { const m = el('message'); m.textContent = text; m.className = error ? 'error' : ''; const mm = document.getElementById('modal-message'); if (mm && modal.open) {
    mm.textContent = text;
    mm.className = error ? 'notice error' : 'notice';
} }
function fail(error) { message(error instanceof Error ? error.message : String(error), true); }
async function api(path, data) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 45000);
    try {
        const res = await fetch('/api/' + path, { method: data ? 'POST' : 'GET', headers: data ? { 'Content-Type': 'application/json', 'X-Redreview-Token': token } : {}, body: data ? JSON.stringify(data) : undefined, signal: controller.signal });
        const result = await res.json();
        if (!res.ok)
            throw new Error((result.error || 'Action failed. Retry after reloading.') + (result.retry_after ? ` Retry in ${result.retry_after} seconds.` : ''));
        return result;
    }
    catch (e) {
        if (e instanceof Error && e.name === 'AbortError')
            throw new Error('The backend request timed out. Check connectivity and refresh the project before retrying a save.');
        throw e;
    }
    finally {
        clearTimeout(timer);
    }
}
function showModal(html) { el('modal-body').innerHTML = '<div id="modal-message" role="status" aria-live="polite"></div>' + html; if (!modal.open)
    modal.showModal(); }
button('close-modal', () => modal.close());
async function refresh() {
    projects = await api('projects');
    if (pid) {
        const profiles = await api('reviewers?project=' + encodeURIComponent(pid));
        if (!profiles.some(r => r.id === reviewer))
            reviewer = profiles[0]?.id || '';
        view = await api(`view?project=${encodeURIComponent(pid)}&reviewer=${encodeURIComponent(reviewer)}&blinded=${blinded}`);
        if (!view.records.some(r => r.id === selected && !r.merged_into))
            selected = view.records.find(r => !r.merged_into)?.id || '';
    }
    else
        view = null;
    render();
}
async function mutate(path, data) { await api(path, { project: pid, ...data }); await refresh(); message('Saved locally.'); }
function createProject() { showModal('<h2>New review project</h2><p class="muted">Start with a question, then import your search results.</p><label for="project-name">Project name</label><input id="project-name" maxlength="200" placeholder="e.g. Community wellbeing scoping review"><div class="actions"><button id="create-project">Create project</button></div>'); button('create-project', async () => { const p = await api('create', { name: value('project-name') }); pid = p.id; reviewer = ''; selected = ''; modal.close(); await refresh(); }); }
function render() {
    if (!view) {
        app.innerHTML = `<main class="empty"><div class="eyebrow">Your evidence workspace</div><h1>Make room for a clearer review.</h1><p>Bring your records together, screen independently, and preserve the story behind every decision.</p><div class="actions"><button id="new">Create a project</button><button id="demo" class="secondary">Try synthetic demo</button><button id="restore" class="secondary">Restore backup</button></div>${projects.length ? `<label for="open-project">Open a local project</label><select id="open-project"><option value="">Choose a project</option>${projects.map(p => `<option value="${p.id}">${escape(p.name)}${p.archived ? ' · archived' : ''}</option>`).join('')}</select>` : ''}<div class="notice">Local reviewer profiles are not secure accounts. This version has no online collaboration. Your records and PDFs stay on this computer.</div></main>`;
        button('new', createProject);
        button('demo', async () => { const p = await api('demo', {}); pid = p.id; await refresh(); });
        button('restore', restoreDialog);
        el('open-project')?.addEventListener('change', async (e) => { pid = e.target.value; await refresh().catch(fail); });
        return;
    }
    const p = view.project;
    app.innerHTML = `<div class="toolbar"><select id="project-select" aria-label="Open project"><option value="">All projects</option>${projects.map(x => `<option value="${x.id}" ${pid === x.id ? 'selected' : ''}>${escape(x.name)}${x.archived ? ' · archived' : ''}</option>`).join('')}</select><button id="new" class="secondary small">+ New</button><button id="settings" class="secondary small">Project settings</button><span class="spacer"></span><label for="reviewer-select" class="sr">Reviewer profile</label><select id="reviewer-select">${view.reviewers.map(r => `<option value="${r.id}" ${reviewer === r.id ? 'selected' : ''}>${escape(r.name)}${r.role === 'adjudicator' ? ' · adjudicator' : ''}</option>`).join('')}</select><button id="add-reviewer" class="secondary small">+ Profile</button><label class="chart-state"><input id="blinded" type="checkbox" ${blinded ? 'checked' : ''}> Blinded</label></div><nav class="tabs" aria-label="Review sections">${[['discover', 'Article search'], ['screen', 'Screening'], ['duplicates', 'Duplicates'], ['reports', 'Exports & counts']].map(([id, name]) => `<button id="tab-${id}" class="${tab === id ? 'active' : ''}">${name}</button>`).join('')}<button id="import">Import records</button></nav>${p.demo ? '<div class="notice demo-notice">DEMO PROJECT — All sample records and findings are synthetic.</div>' : ''}${p.archived ? '<div class="notice">Archived project · Open Project settings to restore editing.</div>' : ''}<div id="view-body"></div>`;
    button('new', createProject);
    button('settings', settingsDialog);
    button('add-reviewer', reviewerDialog);
    button('import', importDialog);
    for (const id of ['discover', 'screen', 'duplicates', 'reports'])
        button('tab-' + id, () => { tab = id; render(); });
    el('project-select').onchange = async () => { pid = value('project-select'); selected = ''; reviewer = ''; await refresh().catch(fail); };
    el('reviewer-select').onchange = async () => { reviewer = value('reviewer-select'); await refresh().catch(fail); };
    el('blinded').onchange = async () => { const checked = el('blinded').checked; if (!checked && !confirm('Disable blinding? Other reviewers’ decisions, notes, counts and exports will become visible on this computer.')) {
        el('blinded').checked = true;
        return;
    } blinded = checked; await refresh().catch(fail); };
    if (tab === 'discover')
        renderDiscovery();
    else if (tab === 'screen')
        renderScreen();
    else if (tab === 'duplicates')
        renderDuplicates();
    else
        renderReports();
}
let discoveryCriteria = { provider: 'crossref', mode: 'keyword', query: '', year_from: '', year_to: '', journal: '', oa: false };
let discoveryPage = null, discoverySelected = new Set(), discoveryBusy = false, discoveryStatus = '', discoveryError = false;
let discoveryGeneration = 0;
function articleAccess(r) { return `${safeUrl(r.oa_url || '') ? `<a target="_blank" rel="noopener noreferrer" href="${safeUrl(r.oa_url)}">Free full-text webpage ↗</a>` : ''}${safeUrl(r.pdf_url || '') ? `<a target="_blank" rel="noopener noreferrer" href="${safeUrl(r.pdf_url)}">Provider-reported OA PDF ↗</a>` : ''}`; }
function renderDiscovery() {
    const c = discoveryCriteria, result = discoveryPage;
    el('view-body').innerHTML = `<main class="content discovery"><div class="eyebrow">Scholarly discovery</div><h1>Find articles for your review</h1><p>Search live scholarly providers through your local backend. Discovery supplements a documented, comprehensive database search; keep your full strategy, dates and database exports.</p><form id="discovery-form"><div class="search-grid"><div><label for="discovery-provider">Provider</label><select id="discovery-provider">${['crossref', 'openalex', 'pubmed'].map(p => `<option value="${p}" ${c.provider === p ? 'selected' : ''}>${{ crossref: 'Crossref', openalex: 'OpenAlex', pubmed: 'PubMed' }[p]}</option>`).join('')}</select></div><div><label for="discovery-mode">Search type</label><select id="discovery-mode">${[['keyword', 'Keywords'], ['title', 'Title'], ['doi', 'DOI lookup']].map(([v, n]) => `<option value="${v}" ${c.mode === v ? 'selected' : ''}>${n}</option>`).join('')}</select></div><div class="search-term"><label for="discovery-query">Keywords, title or DOI</label><input id="discovery-query" maxlength="500" required value="${escape(c.query)}" placeholder="e.g. community gardening wellbeing"></div><div><label for="discovery-from">From year</label><input id="discovery-from" type="number" min="1000" max="2100" value="${escape(c.year_from)}"></div><div><label for="discovery-to">To year</label><input id="discovery-to" type="number" min="1000" max="2100" value="${escape(c.year_to)}"></div><div class="search-term"><label for="discovery-journal">Journal filter</label><input id="discovery-journal" maxlength="200" value="${escape(c.journal)}" placeholder="Crossref: ISSN · OpenAlex: ISSN/source ID · PubMed: name/ISSN"></div></div><label class="chart-state"><input id="discovery-oa" type="checkbox" ${c.oa ? 'checked' : ''}> Free / open-access only (OpenAlex or PubMed)</label><p><small>DOI lookup requires cleared filters. Crossref journal filter uses ISSN; OpenAlex uses ISSN or source ID. PubMed accepts a journal name or ISSN.</small></p><button id="run-discovery" type="submit" ${discoveryBusy ? 'disabled' : ''}>${discoveryBusy ? 'Searching scholarly provider…' : 'Search articles'}</button></form><div class="notice ${discoveryError ? 'error' : ''}" role="status" aria-live="polite">${escape(discoveryStatus || 'No search yet. Missing metadata will be labelled; no synthetic results are used here.')}</div>${result ? `<p>${result.total.toLocaleString()} provider matches · Page ${result.page} · ${result.cached ? 'Cached retrieval' : 'Live retrieval'} ${escape(new Date(result.retrieved_at).toLocaleString())}</p>${result.notes.map(n => `<p class="muted">${escape(n)}</p>`).join('')}<div class="import-bar"><label for="discovery-project">Import into project</label><select id="discovery-project">${projects.filter(p => !p.archived && !p.demo).map(p => `<option value="${p.id}" ${p.id === pid ? 'selected' : ''}>${escape(p.name)}</option>`).join('')}</select><button id="select-discovery" class="secondary" ${discoveryBusy ? 'disabled' : ''}>Select page</button><button id="clear-discovery" class="secondary" ${discoveryBusy ? 'disabled' : ''}>Clear selection</button><button id="import-discovery" ${discoveryBusy || !discoverySelected.size ? 'disabled' : ''}>${discoveryBusy ? 'Working…' : `Import selected (${discoverySelected.size})`}</button></div><div class="search-results" aria-busy="${discoveryBusy}">${result.records.map(r => `<article class="card"><label class="article-select"><input type="checkbox" data-discovery="${r.result_id}" ${discoverySelected.has(r.result_id) ? 'checked' : ''} ${discoveryBusy ? 'disabled' : ''}> Select article</label><h2>${escape(r.title || 'Title not supplied')}</h2><p>${escape(r.author || 'Authors not supplied')}<br>${escape(r.year || 'Year not supplied')} · ${escape(r.journal || 'Journal not supplied')}</p><span class="badge">${escape(r.provider)}</span><span class="badge">${r.is_oa === true ? 'Provider reports open access' : r.is_oa === false ? 'Provider reports closed access' : 'Open-access status unknown'}</span><p><small>DOI: ${escape(r.doi || 'not supplied')} · PMID: ${escape(r.pmid || 'not supplied')}<br>Provider ID: ${escape(r.provider_id || 'not supplied')}</small></p><div class="links">${r.doi ? `<a target="_blank" rel="noopener noreferrer" href="https://doi.org/${encodeURIComponent(r.doi)}">DOI ↗</a>` : ''}${safeUrl(r.url) ? `<a target="_blank" rel="noopener noreferrer" href="${safeUrl(r.url)}">Article / publisher webpage ↗</a>` : ''}${articleAccess(r)}</div>${!r.oa_url && !r.pdf_url ? '<p class="muted">No free full-text link supplied. Access may require a subscription.</p>' : ''}${!r.pdf_url ? '<small>No downloadable OA PDF supplied. Manual PDF upload remains available in Screening.</small>' : ''}<details><summary>${r.abstract ? 'Available abstract' : 'Abstract not supplied'}</summary><p class="abstract">${escape(r.abstract || 'The provider did not supply an abstract. Consult the article webpage before screening.')}</p></details></article>`).join('') || '<div class="card">No articles found. Try fewer filters, different terms or another provider.</div>'}</div><div class="actions"><button id="discovery-prev" class="secondary" ${result.page <= 1 || discoveryBusy ? 'disabled' : ''}>Previous page</button><button id="discovery-next" class="secondary" ${!result.has_more || discoveryBusy ? 'disabled' : ''}>Next page</button></div>` : ''}<div class="notice">Metadata and abstracts may have separate copyright restrictions. Full-text links do not grant reuse rights. <a href="https://www.ncbi.nlm.nih.gov/About/disclaimer.html" target="_blank" rel="noopener noreferrer">NCBI disclaimer and copyright</a>. No paywalls are bypassed.</div></main>`;
    const form = el('discovery-form');
    form.onsubmit = e => { e.preventDefault(); if (discoveryBusy)
        return; discoveryCriteria = { provider: value('discovery-provider'), mode: value('discovery-mode'), query: value('discovery-query'), year_from: value('discovery-from'), year_to: value('discovery-to'), journal: value('discovery-journal'), oa: el('discovery-oa').checked }; runDiscovery(1).catch(fail); };
    document.querySelectorAll('[data-discovery]').forEach(n => n.onchange = () => { if (n.checked)
        discoverySelected.add(n.dataset.discovery);
    else
        discoverySelected.delete(n.dataset.discovery); const b = el('import-discovery'); b.textContent = `Import selected (${discoverySelected.size})`; b.disabled = !discoverySelected.size || discoveryBusy; });
    button('select-discovery', () => { result?.records.forEach(r => discoverySelected.add(r.result_id)); renderDiscovery(); });
    button('clear-discovery', () => { discoverySelected.clear(); renderDiscovery(); });
    button('discovery-prev', () => runDiscovery(result.page - 1));
    button('discovery-next', () => runDiscovery(result.page + 1));
    button('import-discovery', () => importDiscovery());
}
async function runDiscovery(page) {
    const generation = ++discoveryGeneration;
    discoveryBusy = true;
    discoveryStatus = 'Contacting the scholarly provider…';
    discoveryError = false;
    discoveryPage = null;
    discoverySelected.clear();
    renderDiscovery();
    try {
        const result = await api('discovery/search', { ...discoveryCriteria, page });
        if (generation !== discoveryGeneration)
            return;
        discoveryPage = result;
        discoveryStatus = result.records.length ? 'Select articles and choose a project to import.' : 'No articles found. Try different terms or fewer filters.';
    }
    catch (e) {
        discoveryStatus = e instanceof Error ? e.message : String(e);
        discoveryError = true;
    }
    finally {
        if (generation === discoveryGeneration) {
            discoveryBusy = false;
            if (tab === 'discover' && view)
                renderDiscovery();
        }
    }
}
async function importDiscovery(ids = Array.from(discoverySelected), allow_uncertain = false, target = value('discovery-project')) {
    if (!target)
        throw new Error('Create an active non-demo project first.');
    const search_id = discoveryPage.search_id;
    discoveryBusy = true;
    renderDiscovery();
    try {
        const report = await api('discovery/import', { project: target, search_id, result_ids: ids, allow_uncertain });
        discoverySelected.clear();
        discoveryStatus = `Imported ${report.imported.length}; exact duplicates ${report.duplicates.length}; awaiting review ${report.uncertain.length}; failures ${report.failures.length}.`;
        await refresh();
        showModal(`<h2>Article import report</h2><p>${escape(discoveryStatus)}</p>${report.imported.map(r => `<p>Imported: ${escape(r.title)}</p>`).join('')}${report.duplicates.map(r => `<p>Skipped duplicate (${escape(r.reason)}): ${escape(r.title)}. Retrieval provenance preserved.</p>`).join('')}${report.failures.map(r => `<p class="error">${escape(r.reason)}</p>`).join('')}${report.uncertain.map(r => `<div class="pair"><h3>${escape(r.title)}</h3><p>Possible matches in the project:</p>${r.matches.map(m => `<p>${escape(m.title)} · ${escape(m.year || 'year missing')} (${Math.round(m.score * 100)}% title similarity)</p>`).join('')}</div>`).join('')}${report.uncertain.length ? '<p>These articles have not been imported. Inspect the titles and years above. Import as separate records if they are distinct; the Duplicates tab permits reversible merges later.</p><button id="confirm-uncertain">Import uncertain articles as separate records</button>' : ''}`);
        button('confirm-uncertain', async () => { if (confirm('Import these possible matches as separate citations after reviewing them?'))
            await importDiscovery(report.uncertain.map(r => r.result_id), true, target); });
    }
    finally {
        discoveryBusy = false;
        if (tab === 'discover' && view)
            renderDiscovery();
    }
}
function currentDecision(rid) { return view.decisions.filter(d => d.record === rid && d.reviewer === reviewer && d.stage === (view.project.stage === 'fulltext' ? 'fulltext' : 'abstract') && !d.adjudication).at(-1); }
function renderScreen() {
    const v = view, p = v.project, stage = p.stage === 'fulltext' ? 'fulltext' : 'abstract';
    const records = v.records.filter(r => !r.merged_into && (!query || `${r.title} ${r.author} ${r.abstract}`.toLowerCase().includes(query.toLowerCase())) && (filter === 'all' || (filter === 'pending' ? !currentDecision(r.id) : filter === 'conflict' ? r.outcome[stage] === 'conflict' : currentDecision(r.id)?.choice === filter)));
    const r = v.records.find(x => x.id === selected && !x.merged_into), d = r ? currentDecision(r.id) : undefined;
    const progress = v.counts.own_progress[stage];
    el('view-body').innerHTML = `<main class="workspace"><aside class="pane list-pane"><div class="eyebrow">Record library</div><h2>${v.counts.active_records} active records</h2><small>${blinded ? 'Your' : 'Visible'} screening progress: ${progress} / ${v.counts.active_records}</small><progress class="progress" aria-label="Screening progress" max="${Math.max(v.counts.active_records, 1)}" value="${progress}">${progress}</progress><label for="search" class="sr">Search records</label><input id="search" placeholder="Search titles, authors, abstracts" value="${escape(query)}"><label for="filter" class="sr">Filter decisions</label><select id="filter"><option value="all">All records</option>${['pending', 'include', 'exclude', 'maybe', ...(!blinded ? ['conflict'] : [])].map(f => `<option value="${f}" ${filter === f ? 'selected' : ''}>${f === 'pending' ? 'Not yet screened' : f[0].toUpperCase() + f.slice(1)}</option>`).join('')}</select><div id="record-list">${records.map(x => `<button class="record ${x.id === selected ? 'selected' : ''}" data-record="${x.id}"><span>${escape(x.title)}</span><span class="meta">${escape(x.author || 'Author missing')} · ${escape(x.year || 'Year missing')}</span><span class="badge ${escape(x.outcome[stage])}">${escape(x.outcome[stage])}</span></button>`).join('') || '<p class="muted">No matching records. Adjust filters or import a RIS, BibTeX, or CSV file.</p>'}</div></aside><section class="pane article">${r ? `<div class="eyebrow">${p.stage === 'chart' ? 'Data charting' : stage === 'fulltext' ? 'Full-text review' : 'Title & abstract screening'}</div><h1 class="article-title">${escape(r.title)}</h1><p class="muted">${escape(r.author || 'Author not supplied')} · ${escape(r.year || 'Year not supplied')} · ${escape(r.journal || 'Journal not supplied')}</p><div class="links">${r.doi ? `<a target="_blank" rel="noopener noreferrer" href="https://doi.org/${encodeURIComponent(r.doi)}">Open DOI ↗</a>` : ''}${safeUrl(r.url) ? `<a target="_blank" rel="noopener noreferrer" href="${safeUrl(r.url)}">Publisher link ↗</a>` : ''}${articleAccess(r)}</div><div class="actions"><button id="abstract-mode" class="secondary small">Abstract</button><button id="pdf-mode" class="secondary small">Attached PDFs (${v.pdfs.filter(f => f.record === r.id).length})</button><button id="attach" class="secondary small">Attach PDF</button></div>${pdfMode ? pdfPanel(r) : `<h3>Abstract</h3><p class="abstract">${escape(r.abstract || 'No abstract was imported. Attach a PDF or consult the DOI/publisher link before making your decision.')}</p>`}<details><summary>Source provenance (${r.provenance.length})</summary>${r.provenance.map(x => `<p><strong>${escape(x.source)}</strong><br>Batch: ${escape(x.batch)}<br>Record: ${escape(x.id)}</p><pre>${escape(JSON.stringify(x.raw, null, 2))}</pre>`).join('')}</details><details><summary>Review question & eligibility criteria</summary><p>${escape(p.question || 'Add your question in Project settings.')}</p><p>${escape(p.criteria || 'Add eligibility criteria in Project settings.')}</p></details></section><aside class="pane controls">${p.stage === 'chart' ? chartPanel(r) : decisionPanel(r, d)}</aside>` : '<div class="empty"><h2>Your review begins with records.</h2><p>Import a search export or try the synthetic demo from the project menu.</p></div><aside class="pane controls"><p>Select an article to start screening.</p></aside>'}</main>`;
    el('search').oninput = () => { query = value('search'); const start = el('search').selectionStart; renderScreen(); el('search').focus(); el('search').setSelectionRange(start, start); };
    el('filter').onchange = () => { filter = value('filter'); renderScreen(); };
    document.querySelectorAll('[data-record]').forEach(b => b.onclick = () => { selected = b.dataset.record; pdfMode = false; renderScreen(); });
    if (!r)
        return;
    button('abstract-mode', () => { pdfMode = false; renderScreen(); });
    button('pdf-mode', () => { pdfMode = true; renderScreen(); });
    button('attach', attachDialog);
    if (p.stage === 'chart')
        button('save-chart', saveChart);
    else {
        for (const choice of ['include', 'exclude', 'maybe'])
            button('decision-' + choice, () => saveDecision(choice));
        button('adjudicate', () => saveDecision(value('adjudication-choice'), true));
    }
}
function pdfPanel(r) { const pdfs = view.pdfs.filter(x => x.record === r.id); return pdfs.length ? pdfs.map(f => `<h3>${escape(f.name)}</h3><iframe title="PDF: ${escape(f.name)}" src="/api/pdf?project=${pid}&id=${f.id}"></iframe><a class="button secondary small" target="_blank" rel="noopener noreferrer" href="/api/pdf?project=${pid}&id=${f.id}">Open PDF in browser ↗</a>`).join('') : '<div class="notice">No PDF attached. Use Attach PDF to store a lawful local copy. DOI and publisher pages may require access rights. Article search can discover provider-reported free full-text webpages and open-access PDF links. A webpage is not a PDF; some articles require subscription access.</div>'; }
function decisionPanel(r, d) {
    const stage = view.project.stage === 'fulltext' ? 'fulltext' : 'abstract';
    const history = view.decisions.filter(x => x.record === r.id && x.stage === stage);
    const adjudicator = view.reviewers.find(x => x.id === reviewer)?.role === 'adjudicator';
    return `<div class="eyebrow">Make a decision</div><h2>${stage === 'fulltext' ? 'Full text' : 'Title & abstract'}</h2><p class="muted">${blinded ? 'Only your decisions are visible.' : 'Other reviewer decisions are visible.'}</p><label for="reason">Exclusion reason</label><input id="reason" value="${escape(d?.reason || '')}" placeholder="Required for Exclude"><label for="labels">Labels (comma separated)</label><input id="labels" value="${escape(d?.labels.join(', ') || '')}" placeholder="e.g. population, follow-up"><label for="notes">Your screening notes</label><textarea id="notes" placeholder="Record your reasoning…">${escape(d?.notes || '')}</textarea><div class="decision-buttons"><button id="decision-include" ${view.project.archived ? 'disabled' : ''}>Include <small>1</small></button><button id="decision-exclude" class="exclude" ${view.project.archived ? 'disabled' : ''}>Exclude <small>2</small></button><button id="decision-maybe" class="maybe" ${view.project.archived ? 'disabled' : ''}>Maybe <small>3</small></button></div><small>Keys 1 / 2 / 3 save a decision. J / K move between records. Shortcuts pause while typing.</small>${!blinded && r.outcome[stage] === 'conflict' ? `<div class="notice">Reviewers disagree. ${adjudicator ? 'Choose a resolution below.' : 'Select an adjudicator profile to resolve.'}</div>${adjudicator ? '<label for="adjudication-choice">Adjudicator decision</label><select id="adjudication-choice"><option value="include">Include</option><option value="exclude">Exclude</option><option value="maybe">Maybe</option></select><button id="adjudicate">Save resolution</button>' : ''}` : ''}<details open><summary>${blinded ? 'Your' : 'Visible'} decision history</summary>${history.map(x => `<div class="history"><strong>${escape(x.reviewer_name)} · ${escape(x.choice)}${x.adjudication ? ' · resolution' : ''}</strong><br><small>${escape(new Date(x.timestamp).toLocaleString())}</small><p>${escape(x.reason)} ${escape(x.notes)}</p><small>${escape(x.labels.join(', '))}</small></div>`).join('') || '<p>No decisions yet.</p>'}</details><div class="notice">Local profiles are not secure accounts and do not provide online collaboration.</div>`;
}
async function saveDecision(choice, adjudication = false) { if (!selected)
    return; await mutate('decision', { record: selected, reviewer, stage: view.project.stage === 'fulltext' ? 'fulltext' : 'abstract', choice, reason: value('reason'), notes: value('notes'), labels: value('labels').split(',').map(x => x.trim()).filter(Boolean), adjudication }); }
function chartPanel(r) { const c = view.charts.filter(x => x.record === r.id && x.reviewer === reviewer).at(-1); return `<div class="eyebrow">Scoping review</div><h2>Data charting</h2><p class="muted">Missing information and not applicable are stored separately.</p>${view.project.fields.map((f, i) => { const v = c?.values[f]; return `<div class="chart-field"><label for="chart-${i}">${escape(f)}</label><select id="chart-status-${i}" aria-label="${escape(f)} status">${[['missing', 'Missing / not reported'], ['value', 'Value recorded'], ['na', 'Not applicable']].map(([id, name]) => `<option value="${id}" ${v?.status === id ? 'selected' : ''}>${name}</option>`).join('')}</select><textarea id="chart-${i}" placeholder="Enter extracted information">${escape(v?.value || '')}</textarea></div>`; }).join('')}<button id="save-chart" ${view.project.archived ? 'disabled' : ''}>Save charting</button><p><small>Fields can be customised in Project settings. Earlier chart versions remain in the audit trail.</small></p>`; }
async function saveChart() { const values = {}; view.project.fields.forEach((f, i) => { const status = value('chart-status-' + i); values[f] = { status, value: status === 'value' ? value('chart-' + i) : '' }; }); await mutate('chart', { record: selected, reviewer, values }); }
function settingsDialog() { const p = view.project; showModal(`<h2>Project settings</h2><label for="setting-name">Name</label><input id="setting-name" value="${escape(p.name)}"><label for="question">Review question</label><textarea id="question">${escape(p.question)}</textarea><label for="criteria">Eligibility criteria</label><textarea id="criteria">${escape(p.criteria)}</textarea><label for="stage">Screening stage</label><select id="stage">${[['abstract', 'Title & abstract'], ['fulltext', 'Full text'], ['chart', 'Data charting']].map(([id, name]) => `<option value="${id}" ${p.stage === id ? 'selected' : ''}>${name}</option>`).join('')}</select><label for="fields">Chart fields (one per line)</label><textarea id="fields">${escape(p.fields.join('\n'))}</textarea><p><small>Removing a field hides it from the current form; earlier data remains preserved and exported.</small></p><div class="actions"><button id="save-settings" ${p.archived ? 'disabled' : ''}>Save settings</button><button id="archive" class="secondary">${p.archived ? 'Restore to active' : 'Archive project'}</button></div>`); button('save-settings', async () => { await mutate('update', { changes: { name: value('setting-name'), question: value('question'), criteria: value('criteria'), stage: value('stage'), fields: value('fields').split('\n').map(x => x.trim()).filter(Boolean) } }); modal.close(); }); button('archive', async () => { if (!p.archived && !confirm('Archive this project? It will remain readable and backed up, but editing will be disabled.'))
    return; await mutate('update', { changes: { archived: !p.archived }, confirmed: true }); modal.close(); }); }
function reviewerDialog() { showModal('<h2>Add a local reviewer profile</h2><p>Profiles keep decisions independent. They are not secure accounts and offer no online collaboration.</p><label for="profile-name">Profile name</label><input id="profile-name"><label for="profile-role">Role</label><select id="profile-role"><option value="reviewer">Reviewer</option><option value="adjudicator">Adjudicator</option></select><div class="actions"><button id="save-profile">Add profile</button></div>'); button('save-profile', async () => { await mutate('reviewer', { name: value('profile-name'), role: value('profile-role') }); modal.close(); }); }
function csvHeaders(text) { const output = []; let field = '', quoted = false; for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
        if (quoted && text[i + 1] === '"') {
            field += '"';
            i++;
        }
        else
            quoted = !quoted;
    }
    else if (c === ',' && !quoted) {
        output.push(field);
        field = '';
    }
    else if ((c === '\n' || c === '\r') && !quoted)
        break;
    else
        field += c;
} output.push(field); return output.map(s => s.replace(/^\ufeff/, '')); }
function importDialog() { showModal('<h2>Import search results</h2><p class="muted">Original records, source database and import batch are preserved. Invalid batches are rejected without partial imports.</p><label for="source">Source database / collection</label><input id="source" placeholder="e.g. PubMed · search 2026-10-09"><label for="import-format">Format</label><select id="import-format"><option value="ris">RIS</option><option value="bib">BibTeX</option><option value="csv">CSV</option></select><label for="import-file">UTF-8 bibliography file</label><input id="import-file" type="file" accept=".ris,.bib,.csv,.txt"><div id="mapping"></div><div class="actions"><button id="do-import">Import records</button></div>'); let text = '', headers = []; const updateMapping = () => { el('mapping').innerHTML = value('import-format') === 'csv' && headers.length ? `<h3>Map CSV columns</h3><div class="mapping">${['title', 'author', 'year', 'abstract', 'doi', 'url'].map(f => `<div><label for="map-${f}">${f}${f === 'title' ? ' (required)' : ''}</label><select id="map-${f}"><option value="">Not mapped</option>${headers.map(h => `<option value="${escape(h)}" ${h.toLowerCase() === f ? 'selected' : ''}>${escape(h)}</option>`).join('')}</select></div>`).join('')}</div>` : ''; }; el('import-file').onchange = async () => { const f = el('import-file').files?.[0]; if (!f)
    return; text = await f.text(); const ext = f.name.split('.').at(-1); if (['ris', 'bib', 'csv'].includes(ext || ''))
    el('import-format').value = ext; headers = csvHeaders(text); updateMapping(); }; el('import-format').onchange = updateMapping; button('do-import', async () => { if (!text)
    throw new Error('Select a bibliography file first.'); const format = value('import-format'), mapping = {}; if (format === 'csv')
    for (const f of ['title', 'author', 'year', 'abstract', 'doi', 'url'])
        mapping[f] = value('map-' + f); const result = await api('import', { project: pid, text, format, source: value('source'), mapping }); modal.close(); await refresh(); message(`Imported ${result.count} records. Inspect the Duplicates tab before confirming any merge.`); }); }
function attachDialog() { showModal('<h2>Attach a lawful local PDF</h2><p>Choose a PDF you have permission to use. The file is copied into this project’s local database and included in backups.</p><label for="pdf-file">PDF file (maximum 25 MiB)</label><input id="pdf-file" type="file" accept="application/pdf,.pdf"><div class="actions"><button id="save-pdf">Attach PDF</button></div>'); button('save-pdf', async () => { const f = el('pdf-file').files?.[0]; if (!f)
    throw new Error('Choose a PDF first.'); if (f.size > 25 * 1024 * 1024)
    throw new Error('Choose a PDF smaller than 25 MiB.'); const bytes = new Uint8Array(await f.arrayBuffer()); let binary = ''; for (let i = 0; i < bytes.length; i += 8192)
    binary += String.fromCharCode(...bytes.subarray(i, i + 8192)); await mutate('attach', { record: selected, reviewer, name: f.name, content: btoa(binary) }); modal.close(); pdfMode = true; render(); }); }
function renderDuplicates() {
    const v = view, record = (id) => v.records.find(r => r.id === id);
    el('view-body').innerHTML = `<main class="content"><h1>Inspect duplicate candidates</h1><p class="muted">Matching DOI or ≥90% normalised title similarity proposes a pair. You decide whether to merge. Raw sources, PDFs, charting and decision histories stay intact.</p><div class="card">${v.duplicates.map((d, i) => `<div class="pair"><span class="badge">${d.reason} · ${Math.round(d.score * 100)}%</span><h3>${escape(record(d.keep).title)}</h3><p>${escape(record(d.keep).author)} · ${escape(record(d.keep).year)} · ${escape(record(d.keep).source)}<br>DOI: ${escape(record(d.keep).doi || 'missing')}</p><h3>${escape(record(d.other).title)}</h3><p>${escape(record(d.other).author)} · ${escape(record(d.other).year)} · ${escape(record(d.other).source)}<br>DOI: ${escape(record(d.other).doi || 'missing')}</p><button id="inspect-${i}" class="secondary small">Inspect original records</button> <button id="merge-${i}" class="small" ${v.project.archived ? 'disabled' : ''}>Confirm merge</button></div>`).join('') || '<p>No proposed duplicates. Import records to compare DOI and title similarity.</p>'}</div><h2>Confirmed merges</h2><div class="card">${v.records.filter(r => r.merged_into).map((r, i) => `<div class="pair"><h3>${escape(r.title)}</h3><p>Merged into: ${escape(record(r.merged_into).title)}</p><button id="undo-${i}" class="secondary small" ${v.project.archived ? 'disabled' : ''}>Undo merge</button></div>`).join('') || '<p>No records have been merged.</p>'}</div><div class="notice">Merge links group provenance, rather than overwriting metadata. Decisions and PDFs on the secondary record remain on that original record and reappear when the merge is undone.</div></main>`;
    v.duplicates.forEach((d, i) => { button('inspect-' + i, () => showModal(`<h2>Original records</h2><pre>${escape(JSON.stringify([record(d.keep).provenance, record(d.other).provenance], null, 2))}</pre>`)); button('merge-' + i, async () => { if (confirm('Merge these citations? The first record will remain active. The second record’s independent decisions and attachments will be preserved but excluded from active screening until undone.'))
        await mutate('merge', { ...d, confirmed: true }); }); });
    v.records.filter(r => r.merged_into).forEach((r, i) => button('undo-' + i, async () => { if (confirm('Undo this merge and return the secondary citation to screening?'))
        await mutate('merge', { keep: r.merged_into, other: r.id, undo: true, confirmed: true }); }));
}
function renderReports() { const v = view; el('view-body').innerHTML = `<main class="content"><h1>Exports & review counts</h1><p class="muted">A transparent record of your process. Counts are defined in documentation; they are not a claim of PRISMA or JBI compliance.</p><div class="cards">${[['Imported records', v.counts.imported_records], ['Duplicate records removed', v.counts.duplicate_records_removed], ['Active records', v.counts.active_records], ['Attached reports (PDFs)', v.counts.attached_reports], ['Studies', 'Not modelled']].map(([name, n]) => `<div class="card"><h3>${name}</h3><div class="count">${n}</div></div>`).join('')}</div><div class="notice">Records are citations; reports are attached PDF files. This version does not group reports into studies. One attached file is counted as one report, even if its content overlaps another file. Counts may require manual reconciliation for publication.</div>${blinded ? '<div class="notice">Blinding is on. Disable it to reveal project-level screening counts, audit history, exports and backups. Only your progress is shown in screening.</div>' : `<h2>Current screening outcomes</h2><div class="cards">${['abstract', 'fulltext'].map(stage => `<div class="card"><h3>${stage === 'abstract' ? 'Title & abstract' : 'Full text'} — active records</h3>${['pending', 'include', 'exclude', 'maybe', 'conflict'].map(s => `<p>${s}: <strong>${v.counts[stage + '_' + s]}</strong></p>`).join('')}</div>`).join('')}</div><h2>Download your data</h2><div class="actions">${['records', 'decisions', 'charted', 'audit', 'counts'].map(c => `<a class="button secondary" href="/api/export?project=${pid}&category=${c}&blinded=false">${c} CSV</a>`).join('')}<a class="button" href="/api/backup?project=${pid}&blinded=false">Project backup (with PDFs)</a></div><p><small>CSV uses UTF-8 with an Excel-compatible BOM. Decision and chart exports include all historical versions. Spreadsheet formula prefixes are escaped.</small></p><details><summary>Audit history (${v.audit.length} events)</summary>${v.audit.slice().reverse().map(a => `<div class="history"><strong>${escape(a.action)}</strong> · ${escape(a.reviewer)}<br><small>${escape(new Date(a.timestamp).toLocaleString())}</small><pre>${escape(JSON.stringify(a.details, null, 2))}</pre></div>`).join('')}</details>`}<button id="restore" class="secondary">Restore a project backup</button></main>`; button('restore', restoreDialog); }
function restoreDialog() { showModal('<h2>Restore project backup</h2><p>Restore creates a separate project. It includes original records, reviewer histories, audit events and attached PDFs. Existing projects remain intact.</p><label for="backup-file">redreview JSON backup</label><input id="backup-file" type="file" accept=".json,application/json"><div class="actions"><button id="do-restore">Validate & restore</button></div>'); button('do-restore', async () => { const f = el('backup-file').files?.[0]; if (!f)
    throw new Error('Select a redreview backup first.'); if (f.size > 95 * 1024 * 1024)
    throw new Error('This backup exceeds the v1 95 MiB restore limit.'); let backup; try {
    backup = JSON.parse(await f.text());
}
catch {
    throw new Error('This is not valid JSON. Select an unmodified redreview backup.');
} if (!confirm('Create a separate restored project from this backup?'))
    return; const p = await api('restore', { backup, confirmed: true }); pid = p.id; reviewer = ''; selected = ''; modal.close(); await refresh(); message('Backup restored into a separate project.'); }); }
document.addEventListener('keydown', e => { if (e.repeat || modal.open || ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName) || e.ctrlKey || e.metaKey || e.altKey || !view || tab !== 'screen')
    return; if (['1', '2', '3'].includes(e.key) && view.project.stage !== 'chart' && !view.project.archived && selected) {
    e.preventDefault();
    saveDecision({ '1': 'include', '2': 'exclude', '3': 'maybe' }[e.key]).catch(fail);
} if (['j', 'k'].includes(e.key)) {
    const visible = Array.from(document.querySelectorAll('[data-record]'));
    const i = visible.findIndex(x => x.dataset.record === selected);
    visible[i + (e.key === 'j' ? 1 : -1)]?.click();
} });
async function init() { token = (await api('session')).token; await refresh(); }
init().catch(fail);
export {};
