/**
 * Supply Chain Traceability System - Frontend Application Logic
 * Interacts with FastAPI backend, MongoDB, Neo4j, and Redis.
 * BCSE406L - NoSQL Databases
 */

const API_BASE = '/api/v1';

// Global state
let currentTab = 'tab-overview';
let networkInstance = null;

let productState = { skip: 0, limit: 15, total: 0, search: '' };
let batchState = { skip: 0, limit: 15, total: 0, search: '' };
let actorState = { skip: 0, limit: 15, total: 0, search: '', role: '' };
let eventState = { skip: 0, limit: 15, total: 0, batchId: '', bizStep: '', eventType: '' };

let deleteTarget = { type: null, id: null };

// ---------------- TAB NAVIGATION ----------------

function switchTab(tabId) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));

  const target = document.getElementById(tabId);
  const btn = document.getElementById('btn-' + tabId);
  if (target) target.classList.remove('hidden');
  if (btn) btn.classList.add('active');

  currentTab = tabId;

  if (tabId === 'tab-products') loadProducts();
  if (tabId === 'tab-batches') loadBatches();
  if (tabId === 'tab-actors') loadActors();
  if (tabId === 'tab-events') loadEvents();
  if (tabId === 'tab-overview') refreshOverviewMetrics();
}

// ---------------- NOTIFICATIONS ----------------

function showNotification(message, type = 'success') {
  const banner = document.getElementById('notification-banner');
  const text = document.getElementById('notification-text');
  banner.className = `mb-4 p-4 rounded-lg flex items-center justify-between text-sm shadow-sm transition-all duration-300 ${
    type === 'error' ? 'bg-red-50 text-red-800 border border-red-200' : 'bg-emerald-50 text-emerald-800 border border-emerald-200'
  }`;
  text.textContent = message;
  banner.classList.remove('hidden');
  setTimeout(dismissNotification, 6000);
}

function dismissNotification() {
  document.getElementById('notification-banner').classList.add('hidden');
}

// ---------------- SYSTEM HEALTH & METRICS ----------------

async function checkHealth() {
  try {
    const res = await fetch('/health');
    const data = await res.json();
    updateBadge('badge-api', data.services?.api === 'healthy');
    updateBadge('badge-mongo', data.services?.mongodb?.status === 'healthy');
    updateBadge('badge-neo4j', data.services?.neo4j?.status === 'healthy');
    updateBadge('badge-redis', data.services?.redis?.status === 'healthy');
  } catch (err) {
    updateBadge('badge-api', false);
    updateBadge('badge-mongo', false);
    updateBadge('badge-neo4j', false);
    updateBadge('badge-redis', false);
  }
}

function updateBadge(id, isHealthy) {
  const el = document.getElementById(id);
  if (!el) return;
  const dot = el.querySelector('span');
  if (isHealthy) {
    el.className = 'px-2.5 py-1 rounded-full bg-emerald-950/40 border border-emerald-500/30 text-emerald-300 flex items-center space-x-1.5';
    dot.className = 'w-2 h-2 rounded-full bg-emerald-400 pulse-dot';
  } else {
    el.className = 'px-2.5 py-1 rounded-full bg-rose-950/40 border border-rose-500/30 text-rose-300 flex items-center space-x-1.5';
    dot.className = 'w-2 h-2 rounded-full bg-rose-400';
  }
}

async function refreshOverviewMetrics() {
  checkHealth();
  try {
    const [pRes, bRes, aRes, eRes] = await Promise.all([
      fetch(`${API_BASE}/products?limit=1`),
      fetch(`${API_BASE}/batches?limit=1`),
      fetch(`${API_BASE}/actors?limit=1`),
      fetch(`${API_BASE}/events?limit=1`)
    ]);

    const pData = await pRes.json();
    const bData = await bRes.json();
    const aData = await aRes.json();
    const eData = await eRes.json();

    document.getElementById('stat-products').textContent = (pData.total || 413).toLocaleString();
    document.getElementById('stat-batches').textContent = (bData.total || 377).toLocaleString();
    document.getElementById('stat-actors').textContent = (aData.total || 214).toLocaleString();
    document.getElementById('stat-events').textContent = (eData.total || 5650).toLocaleString();

    document.getElementById('m-count-products').textContent = (pData.total || 413).toLocaleString();
    document.getElementById('m-count-batches').textContent = (bData.total || 377).toLocaleString();
    document.getElementById('m-count-actors').textContent = (aData.total || 214).toLocaleString();
    document.getElementById('m-count-events').textContent = (eData.total || 5650).toLocaleString();
  } catch (err) {
    console.error('Error refreshing metrics:', err);
  }
}

// ---------------- TRACEABILITY EXPLORER ----------------

function setTraceTarget(id) {
  document.getElementById('trace-input-id').value = id;
  executeTrace('forward');
}

async function executeTrace(mode) {
  const targetId = document.getElementById('trace-input-id').value.trim();
  if (!targetId) {
    showNotification('Please enter a target Batch ID or Event Hash', 'error');
    return;
  }

  const provCard = document.getElementById('provenance-card');

  if (mode === 'provenance') {
    try {
      const res = await fetch(`${API_BASE}/trace/provenance/${encodeURIComponent(targetId)}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      renderProvenanceCard(data);
      provCard.classList.remove('hidden');
      renderTimeline(data.timeline || []);
    } catch (err) {
      showNotification(`Provenance failed: ${err.message}`, 'error');
    }
    return;
  }

  provCard.classList.add('hidden');

  try {
    const url = `${API_BASE}/trace/${mode}/${encodeURIComponent(targetId)}?max_depth=50`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    renderGraph(data.nodes || [], data.edges || []);
    renderTimeline(data.timeline || []);
    document.getElementById('graph-stats').textContent = `${data.nodes?.length || 0} nodes, ${data.edges?.length || 0} edges (Hops: ${data.total_hops})`;
    document.getElementById('timeline-count').textContent = `${data.timeline?.length || 0} events`;
  } catch (err) {
    showNotification(`Trace traversal failed: ${err.message}`, 'error');
  }
}

function renderProvenanceCard(data) {
  document.getElementById('prov-product-name').textContent = data.product_name || `Product ${data.gtin}`;
  document.getElementById('prov-batch-id').textContent = data.batch_id;
  document.getElementById('prov-event-count').textContent = data.total_events;

  const origin = data.origin_facility || {};
  document.getElementById('prov-origin-name').textContent = origin.name || 'Origin Farm / Harvester';
  document.getElementById('prov-origin-loc').textContent = `${origin.city || ''}, ${origin.state || ''}`;
  document.getElementById('prov-origin-time').textContent = data.origin_time || 'N/A';

  const latest = data.latest_facility || {};
  document.getElementById('prov-latest-name').textContent = latest.name || 'Receiving Facility';
  document.getElementById('prov-latest-step').textContent = `Business Step: ${data.latest_step || 'receiving'}`;
  document.getElementById('prov-latest-time').textContent = data.latest_time || 'N/A';

  const actorsList = document.getElementById('prov-actors-list');
  actorsList.innerHTML = (data.actors_involved || []).map(a => `
    <div class="px-2.5 py-1 rounded bg-white border text-xs shadow-sm flex items-center space-x-1.5">
      <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
      <span class="font-medium text-slate-800">${a.name}</span>
      <span class="text-[10px] text-slate-400">(${a.inferred_role})</span>
    </div>
  `).join('');
}

function renderGraph(nodes, edges) {
  const container = document.getElementById('network-container');

  const visNodes = nodes.map(n => {
    let color = '#38bdf8'; // sky
    let shape = 'dot';
    if (n.label === 'Location') { color = '#34d399'; shape = 'diamond'; }
    if (n.label === 'Batch') { color = '#818cf8'; shape = 'box'; }
    return {
      id: n.id,
      label: n.title,
      shape: shape,
      color: { background: color, border: '#1e293b' },
      font: { size: 11, color: '#1e293b' }
    };
  });

  const visEdges = edges.map(e => ({
    from: e.source,
    to: e.target,
    label: e.type,
    arrows: 'to',
    font: { size: 9, align: 'middle', color: '#64748b' },
    color: { color: '#94a3b8' }
  }));

  const data = { nodes: visNodes, edges: visEdges };
  const options = {
    physics: {
      stabilization: true,
      barnesHut: { springLength: 120, damping: 0.3 }
    },
    interaction: { hover: true, tooltipDelay: 200 }
  };

  if (networkInstance) networkInstance.destroy();
  networkInstance = new vis.Network(container, data, options);
}

function renderTimeline(timeline) {
  const container = document.getElementById('timeline-container');
  if (!timeline || timeline.length === 0) {
    container.innerHTML = '<p class="text-xs text-slate-400 text-center py-10">No events found.</p>';
    return;
  }

  container.innerHTML = timeline.map((ev, idx) => `
    <div class="p-3 rounded-lg border bg-white shadow-sm flex items-start space-x-3 text-xs">
      <div class="w-6 h-6 rounded-full bg-sky-100 text-sky-700 flex items-center justify-center font-bold text-[10px] flex-shrink-0 mt-0.5">
        ${idx + 1}
      </div>
      <div class="flex-1 min-w-0">
        <div class="flex justify-between items-center mb-0.5">
          <span class="font-bold text-slate-900 capitalize">${ev.biz_step}</span>
          <span class="text-[10px] text-slate-400">${ev.event_time ? new Date(ev.event_time).toLocaleDateString() : 'N/A'}</span>
        </div>
        <div class="text-slate-600 truncate">${ev.location_name || 'Location'}${ev.location_city ? ' &bull; ' + ev.location_city + ', ' + ev.location_state : ''}</div>
        <div class="text-[10px] font-mono text-slate-400 truncate mt-1">Hash: ${ev.canonical_hash}</div>
      </div>
    </div>
  `).join('');
}

// ---------------- PRODUCTS CRUD ----------------

async function loadProducts() {
  const tbody = document.getElementById('product-table-body');
  tbody.innerHTML = '<tr><td colspan="4" class="p-4 text-center text-slate-400">Loading products...</td></tr>';

  try {
    const url = `${API_BASE}/products?skip=${productState.skip}&limit=${productState.limit}&search=${encodeURIComponent(productState.search)}`;
    const res = await fetch(url);
    const data = await res.json();

    productState.total = data.total;
    document.getElementById('product-page-info').textContent = `Showing ${data.skip + 1}-${Math.min(data.skip + data.limit, data.total)} of ${data.total}`;

    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="p-4 text-center text-slate-400">No products found.</td></tr>';
      return;
    }

    tbody.innerHTML = data.items.map(p => `
      <tr class="hover:bg-slate-50 transition">
        <td class="p-3 font-mono font-medium text-slate-900">${p.product_id}</td>
        <td class="p-3">
          <div class="font-medium text-slate-800">${p.name}</div>
          <div class="text-[11px] text-slate-400 truncate max-w-xs">${p.description || ''}</div>
        </td>
        <td class="p-3">
          <span class="px-2 py-0.5 rounded text-[10px] font-bold ${p.data_origin === 'SOURCE' ? 'bg-sky-100 text-sky-800' : 'bg-purple-100 text-purple-800'}">
            ${p.data_origin}
          </span>
        </td>
        <td class="p-3 text-right space-x-1 whitespace-nowrap">
          <button onclick="editProduct('${p.product_id}', '${escapeAttr(p.name)}', '${escapeAttr(p.description || '')}')" class="px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700">Edit</button>
          <button onclick="confirmDelete('product', '${p.product_id}', 'Product ${p.product_id} (${escapeAttr(p.name)})')" class="px-2 py-1 rounded bg-rose-50 hover:bg-rose-100 text-rose-700">Delete</button>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="p-4 text-center text-red-500">Error loading products: ${err.message}</td></tr>`;
  }
}

function debounceProductSearch() {
  clearTimeout(window._pTimeout);
  window._pTimeout = setTimeout(() => {
    productState.search = document.getElementById('product-search').value.trim();
    productState.skip = 0;
    loadProducts();
  }, 300);
}

function prevProductPage() {
  if (productState.skip >= productState.limit) {
    productState.skip -= productState.limit;
    loadProducts();
  }
}

function nextProductPage() {
  if (productState.skip + productState.limit < productState.total) {
    productState.skip += productState.limit;
    loadProducts();
  }
}

function openProductModal(isEdit = false) {
  document.getElementById('modal-product-title').textContent = isEdit ? 'Edit Product' : 'Add New Product';
  document.getElementById('m-prod-id').disabled = isEdit;
  if (!isEdit) {
    document.getElementById('m-prod-id').value = '';
    document.getElementById('m-prod-name').value = '';
    document.getElementById('m-prod-desc').value = '';
  }
  openModal('modal-product');
}

function editProduct(id, name, desc) {
  document.getElementById('m-prod-id').value = id;
  document.getElementById('m-prod-name').value = name;
  document.getElementById('m-prod-desc').value = desc;
  openProductModal(true);
}

async function submitProductForm() {
  const id = document.getElementById('m-prod-id').value.trim();
  const name = document.getElementById('m-prod-name').value.trim();
  const desc = document.getElementById('m-prod-desc').value.trim();
  const isEdit = document.getElementById('m-prod-id').disabled;

  if (!id || !name) {
    showNotification('GTIN and Name are required.', 'error');
    return;
  }

  try {
    if (isEdit) {
      const res = await fetch(`${API_BASE}/products/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, description: desc })
      });
      if (!res.ok) throw new Error(await res.text());
      showNotification(`Product '${id}' updated successfully.`);
    } else {
      const res = await fetch(`${API_BASE}/products`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ product_id: id, name: name, description: desc })
      });
      if (!res.ok) throw new Error(await res.text());
      showNotification(`Product '${id}' registered successfully.`);
    }
    closeModal('modal-product');
    loadProducts();
  } catch (err) {
    showNotification(`Save failed: ${err.message}`, 'error');
  }
}

// ---------------- BATCHES CRUD ----------------

async function loadBatches() {
  const tbody = document.getElementById('batch-table-body');
  tbody.innerHTML = '<tr><td colspan="5" class="p-4 text-center text-slate-400">Loading batches...</td></tr>';

  try {
    const url = `${API_BASE}/batches?skip=${batchState.skip}&limit=${batchState.limit}&search=${encodeURIComponent(batchState.search)}`;
    const res = await fetch(url);
    const data = await res.json();

    batchState.total = data.total;
    document.getElementById('batch-page-info').textContent = `Showing ${data.skip + 1}-${Math.min(data.skip + data.limit, data.total)} of ${data.total}`;

    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="p-4 text-center text-slate-400">No batches found.</td></tr>';
      return;
    }

    tbody.innerHTML = data.items.map(b => `
      <tr class="hover:bg-slate-50 transition">
        <td class="p-3 font-mono font-medium text-slate-900">${b.batch_id}</td>
        <td class="p-3 font-mono text-slate-700">${b.lot_number}</td>
        <td class="p-3 font-mono text-slate-500">${b.product_id}</td>
        <td class="p-3">
          <span class="px-2 py-0.5 rounded text-[10px] font-bold ${b.data_origin === 'SOURCE' ? 'bg-sky-100 text-sky-800' : 'bg-purple-100 text-purple-800'}">
            ${b.data_origin}
          </span>
        </td>
        <td class="p-3 text-right space-x-1 whitespace-nowrap">
          <button onclick="setTraceTarget('${b.batch_id}'); switchTab('tab-trace')" class="px-2 py-1 rounded bg-sky-50 hover:bg-sky-100 text-sky-700 font-medium">Trace</button>
          <button onclick="confirmDelete('batch', '${b.batch_id}', 'Batch ${b.batch_id}')" class="px-2 py-1 rounded bg-rose-50 hover:bg-rose-100 text-rose-700">Delete</button>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="p-4 text-center text-red-500">Error loading batches: ${err.message}</td></tr>`;
  }
}

function debounceBatchSearch() {
  clearTimeout(window._bTimeout);
  window._bTimeout = setTimeout(() => {
    batchState.search = document.getElementById('batch-search').value.trim();
    batchState.skip = 0;
    loadBatches();
  }, 300);
}

function prevBatchPage() {
  if (batchState.skip >= batchState.limit) {
    batchState.skip -= batchState.limit;
    loadBatches();
  }
}

function nextBatchPage() {
  if (batchState.skip + batchState.limit < batchState.total) {
    batchState.skip += batchState.limit;
    loadBatches();
  }
}

function openBatchModal() {
  document.getElementById('m-batch-gtin').value = '';
  document.getElementById('m-batch-lot').value = '';
  document.getElementById('m-batch-origin').value = '';
  openModal('modal-batch');
}

async function submitBatchForm() {
  const gtin = document.getElementById('m-batch-gtin').value.trim();
  const lot = document.getElementById('m-batch-lot').value.trim();
  const origin = document.getElementById('m-batch-origin').value.trim();

  if (!gtin || !lot) {
    showNotification('Product GTIN and Lot Number are required.', 'error');
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/batches`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product_id: gtin,
        lot_number: lot,
        origin_location_id: origin || null
      })
    });
    if (!res.ok) throw new Error(await res.text());
    showNotification(`Batch '${gtin}:${lot}' created successfully.`);
    closeModal('modal-batch');
    loadBatches();
  } catch (err) {
    showNotification(`Create batch failed: ${err.message}`, 'error');
  }
}

// ---------------- ACTORS / FACILITIES CRUD ----------------

async function loadActors() {
  const tbody = document.getElementById('actor-table-body');
  tbody.innerHTML = '<tr><td colspan="5" class="p-4 text-center text-slate-400">Loading facilities...</td></tr>';

  try {
    const url = `${API_BASE}/actors?skip=${actorState.skip}&limit=${actorState.limit}&search=${encodeURIComponent(actorState.search)}&role=${encodeURIComponent(actorState.role)}`;
    const res = await fetch(url);
    const data = await res.json();

    actorState.total = data.total;
    document.getElementById('actor-page-info').textContent = `Showing ${data.skip + 1}-${Math.min(data.skip + data.limit, data.total)} of ${data.total}`;

    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="p-4 text-center text-slate-400">No facilities found.</td></tr>';
      return;
    }

    tbody.innerHTML = data.items.map(a => `
      <tr class="hover:bg-slate-50 transition">
        <td class="p-3 font-medium text-slate-900">${a.name}</td>
        <td class="p-3 font-mono text-[11px] text-slate-500">${a.actor_id}</td>
        <td class="p-3 text-slate-600">${a.address?.city || ''}, ${a.address?.state || ''}</td>
        <td class="p-3">
          <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800">
            ${a.inferred_role || 'DISTRIBUTOR'}
          </span>
        </td>
        <td class="p-3 text-right space-x-1 whitespace-nowrap">
          <button onclick="confirmDelete('actor', '${encodeURIComponent(a.actor_id)}', 'Facility ${escapeAttr(a.name)}')" class="px-2 py-1 rounded bg-rose-50 hover:bg-rose-100 text-rose-700">Delete</button>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="p-4 text-center text-red-500">Error loading facilities: ${err.message}</td></tr>`;
  }
}

function debounceActorSearch() {
  clearTimeout(window._aTimeout);
  window._aTimeout = setTimeout(() => {
    actorState.search = document.getElementById('actor-search').value.trim();
    actorState.skip = 0;
    loadActors();
  }, 300);
}

function filterActorsByRole() {
  actorState.role = document.getElementById('actor-role-filter').value;
  actorState.skip = 0;
  loadActors();
}

function prevActorPage() {
  if (actorState.skip >= actorState.limit) {
    actorState.skip -= actorState.limit;
    loadActors();
  }
}

function nextActorPage() {
  if (actorState.skip + actorState.limit < actorState.total) {
    actorState.skip += actorState.limit;
    loadActors();
  }
}

function openActorModal() {
  document.getElementById('m-actor-id').value = '';
  document.getElementById('m-actor-name').value = '';
  document.getElementById('m-actor-city').value = '';
  document.getElementById('m-actor-state').value = '';
  document.getElementById('m-actor-lat').value = '';
  document.getElementById('m-actor-lon').value = '';
  openModal('modal-actor');
}

async function submitActorForm() {
  const id = document.getElementById('m-actor-id').value.trim();
  const name = document.getElementById('m-actor-name').value.trim();
  const city = document.getElementById('m-actor-city').value.trim();
  const state = document.getElementById('m-actor-state').value.trim();
  const lat = document.getElementById('m-actor-lat').value.trim();
  const lon = document.getElementById('m-actor-lon').value.trim();
  const role = document.getElementById('m-actor-role').value;

  if (!id || !name) {
    showNotification('GLN ID and Facility Name are required.', 'error');
    return;
  }

  const payload = {
    actor_id: id,
    name: name,
    address: { city: city, state: state, country_code: 'US' },
    role: role
  };
  if (lat && lon) {
    payload.latitude = parseFloat(lat);
    payload.longitude = parseFloat(lon);
  }

  try {
    const res = await fetch(`${API_BASE}/actors`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error(await res.text());
    showNotification(`Facility '${name}' registered successfully.`);
    closeModal('modal-actor');
    loadActors();
  } catch (err) {
    showNotification(`Save facility failed: ${err.message}`, 'error');
  }
}

// ---------------- TRACE EVENTS (APPEND-ONLY) ----------------

async function loadEvents() {
  const tbody = document.getElementById('event-table-body');
  tbody.innerHTML = '<tr><td colspan="6" class="p-4 text-center text-slate-400">Loading events...</td></tr>';

  try {
    const url = `${API_BASE}/events?skip=${eventState.skip}&limit=${eventState.limit}&batch_id=${encodeURIComponent(eventState.batchId)}&biz_step=${encodeURIComponent(eventState.bizStep)}&event_type=${encodeURIComponent(eventState.eventType)}`;
    const res = await fetch(url);
    const data = await res.json();

    eventState.total = data.total;
    document.getElementById('event-page-info').textContent = `Showing ${data.skip + 1}-${Math.min(data.skip + data.limit, data.total)} of ${data.total}`;

    if (!data.items || data.items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="p-4 text-center text-slate-400">No events match filter.</td></tr>';
      return;
    }

    tbody.innerHTML = data.items.map(e => `
      <tr class="hover:bg-slate-50 transition">
        <td class="p-3 font-mono text-[11px] font-bold text-slate-900">${e.canonical_hash.substring(0, 16)}...</td>
        <td class="p-3">${e.event_type}</td>
        <td class="p-3">
          <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-sky-100 text-sky-800 capitalize">${e.biz_step}</span>
        </td>
        <td class="p-3 text-[11px] text-slate-500">${e.event_time ? new Date(e.event_time).toLocaleString() : 'N/A'}</td>
        <td class="p-3 font-mono text-[11px] text-slate-600">${e.batch_ids?.join(', ') || 'N/A'}</td>
        <td class="p-3 text-right">
          <button onclick="viewRawEvent('${e.canonical_hash}')" class="px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700">JSON</button>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="p-4 text-center text-red-500">Error loading events: ${err.message}</td></tr>`;
  }
}

function debounceEventSearch() {
  clearTimeout(window._eTimeout);
  window._eTimeout = setTimeout(() => {
    eventState.batchId = document.getElementById('event-batch-filter').value.trim();
    eventState.skip = 0;
    loadEvents();
  }, 300);
}

function filterEvents() {
  eventState.bizStep = document.getElementById('event-bizstep-filter').value;
  eventState.eventType = document.getElementById('event-type-filter').value;
  eventState.skip = 0;
  loadEvents();
}

function prevEventPage() {
  if (eventState.skip >= eventState.limit) {
    eventState.skip -= eventState.limit;
    loadEvents();
  }
}

function nextEventPage() {
  if (eventState.skip + eventState.limit < eventState.total) {
    eventState.skip += eventState.limit;
    loadEvents();
  }
}

async function viewRawEvent(hash) {
  try {
    const res = await fetch(`${API_BASE}/events/${hash}`);
    const data = await res.json();
    document.getElementById('json-modal-title').textContent = `EPCIS Event: ${hash}`;
    document.getElementById('json-payload-viewer').textContent = JSON.stringify(data.raw_epcis_payload || data, null, 2);
    openModal('modal-json');
  } catch (err) {
    showNotification(`Failed to load event: ${err.message}`, 'error');
  }
}

function openAppendEventModal() {
  document.getElementById('m-ev-loc').value = '';
  document.getElementById('m-ev-batch').value = '';
  document.getElementById('m-ev-prev').value = '';
  openModal('modal-event');
}

async function submitEventForm() {
  const type = document.getElementById('m-ev-type').value;
  const step = document.getElementById('m-ev-step').value;
  const loc = document.getElementById('m-ev-loc').value.trim();
  const batch = document.getElementById('m-ev-batch').value.trim();
  const prev = document.getElementById('m-ev-prev').value.trim();

  if (!loc) {
    showNotification('Location GLN is required', 'error');
    return;
  }

  const payload = {
    event_type: type,
    biz_step: step,
    action: 'ADD',
    location_id: loc,
    batch_ids: batch ? [batch] : [],
    prev_event_ids: prev ? [prev] : []
  };

  try {
    const res = await fetch(`${API_BASE}/events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error(await res.text());
    showNotification('Event appended to immutable historical log.');
    closeModal('modal-event');
    loadEvents();
  } catch (err) {
    showNotification(`Append failed: ${err.message}`, 'error');
  }
}

// ---------------- PUBLIC QR LOOKUP ----------------

async function verifyPublicQR() {
  const bid = document.getElementById('public-qr-input').value.trim();
  if (!bid) return;

  try {
    const res = await fetch(`${API_BASE}/public/trace/${encodeURIComponent(bid)}`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    document.getElementById('qr-product-name').textContent = data.product_name;
    document.getElementById('qr-batch-id').textContent = data.batch_id;
    document.getElementById('qr-origin-farm').textContent = data.verified_origin_facility || 'N/A';
    document.getElementById('qr-origin-location').textContent = data.origin_location || 'N/A';
    document.getElementById('qr-harvest-date').textContent = data.harvest_date || 'N/A';
    document.getElementById('qr-custody-count').textContent = `${data.handling_facilities_count} facilities`;
    document.getElementById('qr-data-origin').textContent = data.data_origin;
    document.getElementById('qr-status').textContent = data.current_status || 'verified';
    document.getElementById('public-card').classList.remove('hidden');
  } catch (err) {
    showNotification(`QR lookup failed: ${err.message}`, 'error');
  }
}

// ---------------- COLD CHAIN TELEMATICS ----------------

async function runColdChainAudit() {
  const bid = document.getElementById('coldchain-batch-input').value.trim();
  const sim = document.getElementById('chk-simulate-coldchain').checked;
  if (!bid) return;

  try {
    const res = await fetch(`${API_BASE}/cold-chain/${encodeURIComponent(bid)}?include_simulated=${sim}`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    const pill = document.getElementById('coldchain-status-pill');
    pill.textContent = data.status;
    if (data.status === 'VIOLATION_DETECTED') {
      pill.className = 'px-3 py-1 rounded-full text-xs font-bold bg-rose-100 text-rose-800';
    } else if (data.status === 'NORMAL') {
      pill.className = 'px-3 py-1 rounded-full text-xs font-bold bg-emerald-100 text-emerald-800';
    } else {
      pill.className = 'px-3 py-1 rounded-full text-xs font-bold bg-slate-200 text-slate-700';
    }

    document.getElementById('coldchain-origin-pill').textContent = data.data_origin;
    document.getElementById('coldchain-message').textContent = data.message;

    const rangeSpan = document.getElementById('coldchain-range');
    if (data.temperature_range_celsius) {
      rangeSpan.textContent = `Range: ${data.temperature_range_celsius.min}°C - ${data.temperature_range_celsius.max}°C (Threshold: ${data.temperature_range_celsius.safe_max_threshold}°C)`;
    } else {
      rangeSpan.textContent = '';
    }

    const tableWrapper = document.getElementById('coldchain-table-wrapper');
    const tbody = document.getElementById('coldchain-readings-body');

    if (data.readings && data.readings.length > 0) {
      tableWrapper.classList.remove('hidden');
      tbody.innerHTML = data.readings.map(r => `
        <tr class="hover:bg-slate-50">
          <td class="p-2.5 text-slate-500">${new Date(r.timestamp).toLocaleString()}</td>
          <td class="p-2.5 font-medium text-slate-800">${r.facility_name}</td>
          <td class="p-2.5 font-bold ${r.temperature_celsius > 7.0 ? 'text-rose-600' : 'text-slate-800'}">${r.temperature_celsius}°C</td>
          <td class="p-2.5 text-slate-600">${r.humidity_percent}%</td>
          <td class="p-2.5 font-bold ${r.status === 'EXCURSION' ? 'text-rose-600' : 'text-emerald-600'}">${r.status}</td>
          <td class="p-2.5"><span class="px-1.5 py-0.5 rounded text-[10px] bg-purple-100 text-purple-800 font-bold">${r.data_origin}</span></td>
        </tr>
      `).join('');
    } else {
      tableWrapper.classList.add('hidden');
      tbody.innerHTML = '';
    }
  } catch (err) {
    showNotification(`Cold chain audit failed: ${err.message}`, 'error');
  }
}

// ---------------- EXPORT ----------------

function exportData(format) {
  window.open(`${API_BASE}/export/events?format=${format}&limit=5000`, '_blank');
}

// ---------------- CONFIRMATION & DELETIONS ----------------

function confirmDelete(type, id, label) {
  deleteTarget = { type, id };
  document.getElementById('delete-confirm-message').textContent = `Are you sure you want to delete ${label}?`;
  document.getElementById('btn-confirm-delete').onclick = executeDelete;
  openModal('modal-delete');
}

async function executeDelete() {
  const { type, id } = deleteTarget;
  closeModal('modal-delete');

  try {
    let url = '';
    if (type === 'product') url = `${API_BASE}/products/${id}`;
    if (type === 'batch') url = `${API_BASE}/batches/${id}`;
    if (type === 'actor') url = `${API_BASE}/actors/${id}`;

    const res = await fetch(url, { method: 'DELETE' });
    const result = await res.json();

    if (!res.ok) {
      // Reference violation or conflict
      throw new Error(result.detail || 'Deletion failed');
    }

    showNotification(result.message || 'Record deleted successfully.');
    if (type === 'product') loadProducts();
    if (type === 'batch') loadBatches();
    if (type === 'actor') loadActors();
  } catch (err) {
    showNotification(`Deletion rejected: ${err.message}`, 'error');
  }
}

// ---------------- MODAL UTILITIES ----------------

function openModal(id) {
  document.getElementById(id).classList.remove('hidden');
}

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

function escapeAttr(str) {
  return (str || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// ---------------- INITIALIZATION ----------------

document.addEventListener('DOMContentLoaded', () => {
  refreshOverviewMetrics();
});
