let assignTarget = null;

function openModal(id) { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }
function esc(s) { return (s || '').replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function prettyDate(v) { return v ? new Date(v).toLocaleString() : '—'; }

async function loadTickets(filter = 'all', userId = '') {
  const params = new URLSearchParams({ filter });
  if (userId) params.set('user_id', userId);
  const res = await fetch(`/api/tickets?${params.toString()}`);
  if (!res.ok) return;
  const tickets = await res.json();
  const tbody = document.querySelector('#queue tbody');
  tbody.innerHTML = '';
  if (!tickets.length) {
    tbody.innerHTML = '<tr><td colspan="7">No tasks found</td></tr>';
    return;
  }
  tbody.innerHTML = tickets.map(t => {
    const overdueClass = t.is_overdue ? ' class="overdue"' : '';
    return `<tr${overdueClass}>
      <td><a href="/ticket/${t.ticket_uid}">${esc(t.ticket_number)}</a></td>
      <td>${esc(t.summary)}</td>
      <td>
        <select onchange="changeStatus('${t.ticket_uid}', this.value)">
          ${['new','in_progress','resolved'].map(s => `<option value="${s}" ${s===t.status?'selected':''}>${s}</option>`).join('')}
        </select>
      </td>
      <td>${esc(t.performer || '—')}</td>
      <td>${prettyDate(t.deadline_at)}</td>
      <td>${esc(t.priority || 'medium')}</td>
      <td><button onclick="openAssign('${t.ticket_uid}')">Assign</button></td>
    </tr>`;
  }).join('');
}

async function applyFilter() {
  const f = document.getElementById('filter-select')?.value || 'all';
  const u = document.getElementById('user-select')?.value || '';
  await loadTickets(f, u);
}

async function loadUsers() {
  const res = await fetch('/api/specialists');
  if (!res.ok) return;
  const users = await res.json();
  const byPerformer = document.getElementById('user-select');
  const assignUser = document.getElementById('assign-user');
  if (!byPerformer || !assignUser) return;
  const options = users.map(u => `<option value="${u.user_uid}">${esc(u.full_name)}</option>`).join('');
  byPerformer.innerHTML = '<option value="">— by performer —</option>' + options;
  assignUser.innerHTML = '<option value="">Choose performer</option>' + options;
}

function openAssign(uid) {
  assignTarget = uid;
  openModal('assign-modal');
}

async function submitAssign() {
  if (!assignTarget) return;
  const performerUid = document.getElementById('assign-user').value;
  const res = await fetch(`/tickets/${assignTarget}/assign`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ performer_uid: performerUid })
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    alert(payload.error || 'Assignment failed');
    return;
  }
  closeModal('assign-modal');
  assignTarget = null;
  await applyFilter();
}

async function changeStatus(uid, status) {
  const res = await fetch(`/tickets/${uid}/status`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status })
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) alert(payload.error || 'Status update failed');
  await applyFilter();
}

async function pollNotifications() {
  const res = await fetch('/api/notifications');
  if (!res.ok) return;
  const data = await res.json();
  const badge = document.getElementById('notif-badge');
  const list = document.getElementById('notif-list');
  if (!badge || !list) return;
  badge.textContent = data.count;
  badge.classList.toggle('hidden', !data.count);
  list.innerHTML = data.items.length
    ? data.items.map(i => `<li><a href="/ticket/${i.ticket_uid}">${esc(i.message)}</a></li>`).join('')
    : '<li class="muted">No unread notifications</li>';
}

async function markNotificationsRead() {
  await fetch('/api/notifications/read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  await pollNotifications();
}

function toggleNotifDropdown() {
  const dd = document.getElementById('notif-dropdown');
  if (!dd) return;
  dd.classList.toggle('hidden');
  if (!dd.classList.contains('hidden')) markNotificationsRead();
}

document.addEventListener('DOMContentLoaded', async () => {
  await loadUsers();
  await applyFilter();
  document.getElementById('filter-select')?.addEventListener('change', applyFilter);
  document.getElementById('user-select')?.addEventListener('change', applyFilter);
  setInterval(pollNotifications, 15000);
  pollNotifications();
});
