(() => {
  if (!window.location.pathname.startsWith('/outreach')) return;

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));

  const REVIEW_STATUSES = new Set([
    'queued',
    'researching',
    'review required',
    'draft ready',
    'approved',
  ]);

  let activeFilter = 'all';
  let reopening = false;

  function api(path, init = {}) {
    return fetch(path, {
      ...init,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(init.headers || {}),
      },
    }).then(async (response) => {
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || `API returned ${response.status}`);
      return body;
    });
  }

  function editorError(error) {
    const box = $('#editor-error');
    if (!box) return;
    box.textContent = error instanceof Error ? error.message : 'Outreach action failed.';
    box.classList.remove('hidden');
  }

  function selectedItemId() {
    return $('#editor-id')?.value || '';
  }

  function expectedVersion() {
    return Number($('#editor-version')?.value || 0);
  }

  function keepItemOpen(itemId) {
    if (itemId) sessionStorage.setItem('outreach-open-item', itemId);
  }

  function reloadWithItem(itemId) {
    keepItemOpen(itemId);
    window.location.reload();
  }

  function metricCard(metricId) {
    return document.getElementById(metricId)?.parentElement || null;
  }

  function makeMetricCard(metricId, label, filter) {
    const card = metricCard(metricId);
    if (!card || card.dataset.outreachEnhanced === 'true') return;
    card.dataset.outreachEnhanced = 'true';
    card.dataset.outreachFilter = filter;
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.style.cursor = 'pointer';
    card.classList.add('transition', 'hover:border-black/30', 'hover:shadow-sm');

    const labelNode = card.firstElementChild;
    if (labelNode) labelNode.textContent = label;

    const activate = () => activateFilter(filter);
    card.addEventListener('click', activate);
    card.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        activate();
      }
    });
  }

  function queueRows() {
    return $$('#queue-list [data-edit-id]');
  }

  function rowStatus(row) {
    const badge = row.querySelector('span');
    return (badge?.textContent || '').trim().toLowerCase();
  }

  function rowHasGmailDraft(row) {
    return row.textContent?.toLowerCase().includes('gmail draft created') || false;
  }

  function updateMetricCounts() {
    const rows = queueRows();
    const reviewCount = rows.filter((row) => REVIEW_STATUSES.has(rowStatus(row))).length;
    const gmailCount = rows.filter(rowHasGmailDraft).length;
    const contactedCount = rows.filter((row) => ['contacted', 'replied'].includes(rowStatus(row))).length;

    const review = $('#metric-queued');
    const gmail = $('#metric-ready');
    const contacted = $('#metric-contacted');
    if (review) review.textContent = String(reviewCount);
    if (gmail) gmail.textContent = String(gmailCount);
    if (contacted) contacted.textContent = String(contactedCount);
  }

  function applyQueueFilter() {
    const rows = queueRows();
    for (const row of rows) {
      const status = rowStatus(row);
      const visible = activeFilter === 'all'
        || (activeFilter === 'review' && REVIEW_STATUSES.has(status))
        || (activeFilter === 'gmail' && rowHasGmailDraft(row))
        || (activeFilter === 'contacted' && ['contacted', 'replied'].includes(status));
      row.classList.toggle('hidden', !visible);
    }

    for (const id of ['metric-candidates', 'metric-queued', 'metric-ready', 'metric-contacted']) {
      const card = metricCard(id);
      if (!card) continue;
      const selected = card.dataset.outreachFilter === activeFilter;
      card.classList.toggle('ring-2', selected);
      card.classList.toggle('ring-black/15', selected);
    }
  }

  function activateFilter(filter) {
    activeFilter = filter;
    applyQueueFilter();

    if (filter === 'all') {
      $('#candidate-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      $('#queue-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function enhanceMetrics() {
    makeMetricCard('metric-candidates', 'Candidates', 'all');
    makeMetricCard('metric-queued', 'In review', 'review');
    makeMetricCard('metric-ready', 'Gmail drafts', 'gmail');
    makeMetricCard('metric-contacted', 'Contacted', 'contacted');
    updateMetricCounts();
    applyQueueFilter();
  }

  function integrationConfigured(id) {
    const text = ($(id)?.textContent || '').toLowerCase();
    return text && !text.includes('not configured') && !text.endsWith('—');
  }

  function unlockEditor() {
    const editor = $('#editor-card');
    if (!editor || editor.classList.contains('hidden')) return;
    if (($('#editor-channel')?.textContent || '').trim().toLowerCase() !== 'email') return;

    const to = $('#editor-to');
    const subject = $('#editor-subject');
    const body = $('#editor-body');
    const generate = $('#generate-draft');
    const create = $('#create-gmail-draft');
    const verification = $('#editor-verification');
    const meta = ($('#editor-meta')?.textContent || '').toLowerCase();
    const hasGmailDraft = meta.includes('gmail draft created') && !meta.includes('no gmail draft created');

    if (to) to.disabled = false;
    if (subject) subject.disabled = false;
    if (body) body.disabled = false;

    if (generate) {
      generate.textContent = body?.value ? 'Regenerate draft' : 'Generate verified draft';
      generate.disabled = !integrationConfigured('#openrouter-status');
    }

    if (create) {
      if (hasGmailDraft) {
        create.textContent = 'Gmail draft synced';
        create.disabled = true;
      } else {
        create.textContent = 'Create Gmail draft';
        const verificationReady = ['verified', 'not_required'].includes(verification?.value || '');
        create.disabled = !integrationConfigured('#gmail-status')
          || !to?.value?.trim()
          || !subject?.value?.trim()
          || !body?.value?.trim()
          || !verificationReady;
      }
    }

    const note = $('#draft-action-note');
    if (note && hasGmailDraft) {
      note.textContent = 'This Gmail draft remains editable. Saving or regenerating here updates the existing Gmail draft in place; it does not create a duplicate.';
    }
  }

  function reopenSelectedItem() {
    if (reopening) return;
    const itemId = sessionStorage.getItem('outreach-open-item');
    if (!itemId) return;
    const row = document.querySelector(`[data-edit-id="${CSS.escape(itemId)}"]`);
    if (!row) return;
    reopening = true;
    sessionStorage.removeItem('outreach-open-item');
    row.click();
    setTimeout(() => {
      unlockEditor();
      reopening = false;
    }, 0);
  }

  document.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;

    if (target.closest('[data-edit-id]')) {
      setTimeout(unlockEditor, 0);
      return;
    }

    const generate = target.closest('#generate-draft');
    if (generate) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const itemId = selectedItemId();
      if (!itemId) return;
      generate.disabled = true;
      api(`/api/outreach/items/${encodeURIComponent(itemId)}/regenerate-synced`, {
        method: 'POST',
        body: JSON.stringify({ expected_version: expectedVersion() }),
      })
        .then(() => reloadWithItem(itemId))
        .catch((error) => {
          editorError(error);
          generate.disabled = false;
        });
      return;
    }

    const create = target.closest('#create-gmail-draft');
    if (create) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const itemId = selectedItemId();
      if (!itemId || create.disabled) return;
      create.disabled = true;
      api(`/api/outreach/items/${encodeURIComponent(itemId)}/review-gmail-draft`, {
        method: 'POST',
        body: JSON.stringify({
          expected_version: expectedVersion(),
          to_address: $('#editor-to')?.value || '',
          subject: $('#editor-subject')?.value || '',
          body: $('#editor-body')?.value || '',
        }),
      })
        .then(() => reloadWithItem(itemId))
        .catch((error) => {
          editorError(error);
          create.disabled = false;
        });
    }
  }, true);

  document.addEventListener('submit', (event) => {
    if (!(event.target instanceof HTMLFormElement) || event.target.id !== 'outreach-editor') return;
    event.preventDefault();
    event.stopImmediatePropagation();

    const itemId = selectedItemId();
    if (!itemId) return;
    api(`/api/outreach/items/${encodeURIComponent(itemId)}/save-synced`, {
      method: 'PATCH',
      body: JSON.stringify({
        expected_version: expectedVersion(),
        to_address: $('#editor-to')?.value || null,
        subject: $('#editor-subject')?.value || null,
        body: $('#editor-body')?.value || null,
        verification_status: $('#editor-verification')?.value || null,
        verification_note: $('#editor-verification-note')?.value || null,
        status: $('#editor-status')?.value || null,
      }),
    })
      .then(() => reloadWithItem(itemId))
      .catch(editorError);
  }, true);

  const queueObserver = new MutationObserver(() => {
    enhanceMetrics();
    reopenSelectedItem();
  });

  function init() {
    enhanceMetrics();
    const queue = $('#queue-list');
    if (queue) queueObserver.observe(queue, { childList: true, subtree: true });
    reopenSelectedItem();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();