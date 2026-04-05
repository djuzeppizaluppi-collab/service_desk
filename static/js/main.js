/* =========================================================
   Service Desk v3 — main.js
   ========================================================= */

'use strict';

// ---- HTML escaping to prevent XSS when inserting user content into innerHTML ----
function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ---- Toast notifications ----
function showToast(msg, type = 'info', duration = 3500) {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span>${msg}</span>
    <button onclick="this.parentElement.remove()">×</button>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), duration);
}

// ---- Admin dropdown — click, not hover (Bug #2 fix) ----
document.addEventListener('DOMContentLoaded', function () {
  const btn  = document.getElementById('adminDropBtn');
  const menu = document.getElementById('adminDropMenu');

  if (btn && menu) {
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      const open = menu.classList.toggle('open');
      btn.querySelector('.chevron')?.setAttribute('data-feather', open ? 'chevron-up' : 'chevron-down');
      if (typeof feather !== 'undefined') feather.replace();
    });
    document.addEventListener('click', function () {
      menu.classList.remove('open');
    });
  }

  // ---- Notifications polling (Дор. #18) ----
  initNotifications();

  // ---- Ticket modal events ----
  initTicketModal();

  // ---- History toggle ----
  const ht = document.getElementById('historyToggle');
  if (ht) {
    ht.addEventListener('click', function () {
      const h = document.getElementById('modalHistory');
      h.style.display = h.style.display === 'none' ? '' : 'none';
    });
  }

  // ---- Flash auto-dismiss ----
  setTimeout(() => {
    document.querySelectorAll('.flash').forEach(f => f.remove());
  }, 5000);
});

// =========================================================
// NOTIFICATIONS
// =========================================================
let _notifInterval = null;

function initNotifications() {
  const btn     = document.getElementById('notifBtn');
  const panel   = document.getElementById('notifPanel');
  const overlay = document.getElementById('notifOverlay');
  if (!btn) return;

  btn.addEventListener('click', function (e) {
    e.stopPropagation();
    const open = panel.classList.toggle('open');
    if (open) {
      overlay.style.display = 'block';
      loadNotifications();
    } else {
      overlay.style.display = 'none';
    }
  });

  overlay.addEventListener('click', closeNotifications);

  document.getElementById('markAllRead')?.addEventListener('click', async function () {
    await fetch('/api/notifications/read', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({})
    });
    loadNotifications();
    updateBadge(0);
  });

  // Poll every 30s (Дор. #18)
  _notifInterval = setInterval(pollNotifications, 30000);
}

function closeNotifications() {
  document.getElementById('notifPanel')?.classList.remove('open');
  document.getElementById('notifOverlay').style.display = 'none';
}

async function loadNotifications() {
  try {
    const r = await fetch('/api/notifications');
    const d = await r.json();
    renderNotifications(d);
    updateBadge(d.count);
  } catch(e) {}
}

async function pollNotifications() {
  try {
    const r = await fetch('/api/notifications');
    const d = await r.json();
    updateBadge(d.count);
  } catch(e) {}
}

function renderNotifications(data) {
  const list = document.getElementById('notifList');
  if (!list) return;
  if (!data.items || !data.items.length) {
    list.innerHTML = '<div class="notif-empty">Нет новых уведомлений</div>';
    return;
  }
  list.innerHTML = data.items.map(n => `
    <div class="notif-item" onclick="notifClick('${esc(n.uid)}', '${esc(n.ticket_uid || '')}')">
      <div class="notif-msg">${esc(n.message)}</div>
      ${n.ticket_number ? `<div class="notif-num">${esc(n.ticket_number)}</div>` : ''}
      <div class="notif-date">${esc(n.created_at)}</div>
    </div>
  `).join('');
}

async function notifClick(uid, ticketUid) {
  await fetch('/api/notifications/read', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({uid})
  });
  closeNotifications();
  if (ticketUid) openTicket(ticketUid);
}

function updateBadge(count) {
  const badge = document.querySelector('.notif-badge');
  const btn   = document.getElementById('notifBtn');
  if (!btn) return;
  if (count > 0) {
    if (badge) {
      badge.textContent = count;
    } else {
      const b = document.createElement('span');
      b.className = 'notif-badge';
      b.textContent = count;
      btn.appendChild(b);
    }
  } else if (badge) {
    badge.remove();
  }
}

// =========================================================
// TICKET MODAL
// =========================================================
let _currentTicketUid = null;
let _currentTicketData = null;
let _specialists = [];

function initTicketModal() {
  document.getElementById('ticketModalClose')?.addEventListener('click', closeTicketModal);
  document.getElementById('ticketModalOverlay')?.addEventListener('click', function (e) {
    if (e.target === this) closeTicketModal();
  });

  document.getElementById('btnComment')?.addEventListener('click', submitComment);
  document.getElementById('btnTake')?.addEventListener('click', takeTicket);
  document.getElementById('btnAssign')?.addEventListener('click', assignTicket);
  document.getElementById('btnStatus')?.addEventListener('click', changeStatus);
  document.getElementById('btnDelete')?.addEventListener('click', deleteTicket);
  document.getElementById('btnApprove')?.addEventListener('click', () => approveTicket('approved'));
  document.getElementById('btnReject')?.addEventListener('click', () => approveTicket('rejected'));
  document.getElementById('attachFileInput')?.addEventListener('change', uploadAttachments);
}

async function openTicket(uid) {
  _currentTicketUid = uid;
  document.getElementById('ticketModalOverlay').style.display = 'flex';
  // Reset
  document.getElementById('modalTitle').textContent = 'Загрузка...';
  document.getElementById('modalDescription').textContent = '';
  document.getElementById('modalComments').innerHTML = '';
  document.getElementById('modalHistory').innerHTML = '';
  document.getElementById('modalAttachments').innerHTML = '';

  // Load specialists once
  if (!_specialists.length) {
    try {
      const r = await fetch('/api/specialists');
      if (r.ok) _specialists = await r.json();
    } catch(e) {}
  }

  try {
    const r = await fetch(`/api/tickets/${uid}`);
    _currentTicketData = await r.json();
    renderTicketModal(_currentTicketData);
    if (typeof feather !== 'undefined') feather.replace();
  } catch(e) {
    showToast('Ошибка загрузки заявки', 'error');
  }
}

function closeTicketModal() {
  document.getElementById('ticketModalOverlay').style.display = 'none';
  _currentTicketUid = null;
  _currentTicketData = null;
}

const _statusLabels = {
  new: 'Новая', assigned: 'Назначено', in_progress: 'В работе',
  on_hold: 'Приостановлено', pending_approval: 'На согласовании',
  approved: 'Согласовано', rejected: 'Отклонено',
  resolved: 'Решена', closed: 'Закрыта', cancelled: 'Отменено',
};
const _priorityLabels = {
  low: 'Низкий', medium: 'Средний', high: 'Высокий', critical: 'Критический',
};

function renderTicketModal(t) {
  // Header
  document.getElementById('modalTicketNum').textContent = t.ticket_number;
  document.getElementById('modalTicketStatus').textContent = _statusLabels[t.status] || t.status;
  document.getElementById('modalTicketStatus').className = `modal-ticket-status status-badge status-${t.status}`;
  document.getElementById('modalTicketPriority').textContent = _priorityLabels[t.priority] || t.priority;
  document.getElementById('modalTicketPriority').className = `modal-ticket-priority priority-badge priority-${t.priority}`;

  document.getElementById('modalTitle').textContent = t.summary;
  document.getElementById('modalMeta').textContent =
    `${t.catalog} · Создана ${t.created_at} · ${t.requester}`;
  document.getElementById('modalDescription').textContent = t.description;

  // Sidebar
  document.getElementById('sidebarCatalog').textContent = t.catalog;
  document.getElementById('sidebarPriority').textContent = _priorityLabels[t.priority] || t.priority;
  document.getElementById('sidebarDeadline').innerHTML = t.deadline
    ? `<span class="${t.is_overdue ? 'overdue-text' : ''}">${t.deadline}${t.is_overdue ? ' ⚠' : ''}</span>`
    : '—';

  // Requester link (Дор. #16)
  const reqEl = document.getElementById('sidebarRequester');
  reqEl.textContent = t.requester;
  reqEl.href = `/user/${t.requester_uid}`;

  // Performer
  const perfEl = document.getElementById('sidebarPerformer');
  if (t.performer) {
    perfEl.innerHTML = `<a href="/user/${t.performer_uid}">${t.performer}</a>`;
  } else {
    perfEl.textContent = 'Не назначен';
  }

  // Status widget for sidebar
  const stWrap = document.getElementById('sidebarStatusWrap');
  stWrap.innerHTML = `<span class="status-badge status-${t.status}">${_statusLabels[t.status] || t.status}</span>`;

  // Actions
  const btnTake    = document.getElementById('btnTake');
  const assignWrap = document.getElementById('assignWrap');
  const statusWrap = document.getElementById('statusWrap');
  const btnDelete  = document.getElementById('btnDelete');

  if (btnTake) {
    btnTake.style.display = (!t.performer_uid && t.can_edit) ? '' : 'none';
  }
  if (assignWrap) {
    if (t.can_assign) {
      assignWrap.style.display = '';
      const sel = document.getElementById('assignSelect');
      sel.innerHTML = '<option value="">— Не назначено —</option>';
      _specialists.forEach(sp => {
        const opt = document.createElement('option');
        opt.value = sp.user_uid;
        opt.textContent = sp.full_name;
        if (sp.user_uid === t.performer_uid) opt.selected = true;
        sel.appendChild(opt);
      });
    } else {
      assignWrap.style.display = 'none';
    }
  }
  if (statusWrap) {
    statusWrap.style.display = t.can_edit ? '' : 'none';
    const sel = document.getElementById('statusSelect');
    if (sel) sel.value = t.status;
  }
  if (btnDelete) {
    btnDelete.style.display = t.can_edit ? '' : 'none';
  }

  // Approvals
  const appWrap = document.getElementById('modalApprovalsWrap');
  if (t.approvals && t.approvals.length) {
    appWrap.style.display = '';
    document.getElementById('modalApprovals').innerHTML = t.approvals.map(a => `
      <div class="approval-step approval-${a.status}">
        <span class="approval-step-name">${a.step}</span>
        <a href="/user/${a.approver_uid}" class="approval-approver">${a.approver}</a>
        <span class="approval-status-badge approval-status-${a.status}">
          ${a.status === 'pending' ? 'Ожидает' : a.status === 'approved' ? 'Согласовано' : 'Отклонено'}
        </span>
        ${a.comment ? `<span class="approval-comment">${a.comment}</span>` : ''}
        ${a.decided_at ? `<span class="approval-date">${a.decided_at}</span>` : ''}
      </div>
    `).join('');
  } else {
    appWrap.style.display = 'none';
  }
  const myApprActions = document.getElementById('myApprovalActions');
  if (myApprActions) {
    myApprActions.style.display = t.can_approve ? '' : 'none';
  }

  // Attachments
  const attContainer = document.getElementById('modalAttachments');
  document.getElementById('attachCount').textContent = t.attachments.length ? `(${t.attachments.length})` : '';
  attContainer.innerHTML = t.attachments.map(a => `
    <div class="attach-item">
      <a href="${a.url}" target="_blank" class="attach-name">
        <i data-feather="paperclip"></i> ${a.name}
      </a>
      <span class="attach-meta">${a.size} · ${a.uploader}</span>
    </div>
  `).join('');

  // Comments
  renderComments(t.comments);

  // History
  document.getElementById('modalHistory').innerHTML = t.history.length
    ? t.history.map(h => `
      <div class="history-item">
        <span class="history-field">${esc(h.field)}</span>
        <span class="history-arrow">→</span>
        <span class="history-new">${esc(h.new) || '—'}</span>
        <span class="history-by">${esc(h.by)}</span>
        <span class="history-date">${esc(h.date)}</span>
      </div>
    `).join('')
    : '<div class="history-empty">Нет истории</div>';
}

function renderComments(comments) {
  const el = document.getElementById('modalComments');
  if (!comments.length) {
    el.innerHTML = '<div class="comments-empty">Нет комментариев</div>';
    return;
  }
  el.innerHTML = comments.map(c => `
    <div class="comment ${c.is_internal ? 'comment-internal' : ''}">
      <div class="comment-header">
        <a href="/user/${esc(c.author_uid)}" class="comment-author">
          ${esc(c.author)}
        </a>
        ${c.is_internal ? '<span class="comment-internal-badge">Внутренний</span>' : ''}
        <span class="comment-date">${esc(c.created_at)}</span>
      </div>
      <div class="comment-text">${esc(c.text).replace(/\n/g, '<br>')}</div>
    </div>
  `).join('');
}

// ---- Actions ----
async function takeTicket() {
  const r = await apiTicketAction({action: 'take'});
  if (r.success) { showToast('Заявка взята в работу', 'success'); reloadTicket(); }
  else showToast(r.error || 'Ошибка', 'error');
}

async function assignTicket() {
  const uid = document.getElementById('assignSelect').value;
  const r = await apiTicketAction({action: 'assign', performer_uid: uid || null});
  if (r.success) { showToast('Исполнитель назначен', 'success'); reloadTicket(); }
  else showToast(r.error || 'Ошибка', 'error');
}

async function changeStatus() {
  const status = document.getElementById('statusSelect').value;
  const r = await apiTicketAction({action: 'status', status});
  if (r.success) { showToast('Статус обновлён', 'success'); reloadTicket(); }
  else showToast(r.error || 'Ошибка', 'error');
}

async function deleteTicket() {
  if (!confirm('Удалить заявку? Это действие необратимо.')) return;
  const r = await apiTicketAction({action: 'delete'});
  if (r.success) {
    closeTicketModal();
    showToast('Заявка удалена', 'success');
    setTimeout(() => location.reload(), 800);
  } else showToast(r.error || 'Ошибка', 'error');
}

async function approveTicket(decision) {
  const comment = document.getElementById('approvalComment').value.trim();
  const uid = _currentTicketData?.my_approval_uid;
  const r = await apiTicketAction({action: 'approve', approval_uid: uid, decision, comment});
  if (r.success) { showToast('Решение сохранено', 'success'); reloadTicket(); }
  else showToast(r.error || 'Ошибка', 'error');
}

async function submitComment() {
  const text = document.getElementById('commentText').value.trim();
  if (!text) { showToast('Введите комментарий', 'error'); return; }
  const is_internal = document.getElementById('commentInternal')?.checked || false;
  try {
    const r = await fetch(`/api/tickets/${_currentTicketUid}/comment`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text, is_internal})
    });
    const d = await r.json();
    if (d.success) {
      document.getElementById('commentText').value = '';
      if (document.getElementById('commentInternal'))
        document.getElementById('commentInternal').checked = false;
      // Append comment to list without reload
      const cur = _currentTicketData?.comments || [];
      cur.push(d.comment);
      renderComments(cur);
      showToast('Комментарий добавлен', 'success');
    } else showToast(d.error || 'Ошибка', 'error');
  } catch(e) { showToast('Ошибка сети', 'error'); }
}

async function uploadAttachments(e) {
  const files = e.target.files;
  if (!files.length) return;
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch(`/api/tickets/${_currentTicketUid}/attach`, {method: 'POST', body: fd});
      const d = await r.json();
      if (d.success) {
        showToast(`Файл ${file.name} прикреплён`, 'success');
        reloadTicket();
      } else showToast(d.error || 'Ошибка загрузки', 'error');
    } catch(e) { showToast('Ошибка загрузки', 'error'); }
  }
  e.target.value = '';
}

async function apiTicketAction(payload) {
  try {
    const r = await fetch(`/api/tickets/${_currentTicketUid}/update`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    return await r.json();
  } catch(e) {
    return {error: 'Ошибка сети'};
  }
}

async function reloadTicket() {
  if (!_currentTicketUid) return;
  try {
    const r = await fetch(`/api/tickets/${_currentTicketUid}`);
    _currentTicketData = await r.json();
    renderTicketModal(_currentTicketData);
    if (typeof feather !== 'undefined') feather.replace();
    // Also update kanban card if present
    const card = document.querySelector(`.kanban-card[data-uid="${_currentTicketUid}"]`);
    if (card) {
      const statusBadge = card.querySelector('.status-badge');
      if (statusBadge && _currentTicketData.status) {
        statusBadge.textContent = _statusLabels[_currentTicketData.status] || _currentTicketData.status;
        statusBadge.className = `status-badge status-${_currentTicketData.status}`;
      }
    }
  } catch(e) {}
}
