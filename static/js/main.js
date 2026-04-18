let assignTarget = null;

const STATUSES = [
  { value: 'new',         label: 'Новая' },
  { value: 'in_progress', label: 'В работе' },
  { value: 'resolved',    label: 'Решена' },
];
const PRIORITY_LABELS = {
  low: 'Низкий', medium: 'Средний', high: 'Высокий', critical: 'Критический',
};

function openModal(id) { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }
function esc(s) { return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function prettyDate(v) { return v ? new Date(v).toLocaleString('ru-RU') : '—'; }

async function loadTickets(filter = 'all', userId = '', workGroupId = '') {
  const params = new URLSearchParams({ filter });
  if (userId) params.set('user_id', userId);
  if (workGroupId) params.set('work_group_uid', workGroupId);
  const res = await fetch(`/api/tickets?${params.toString()}`);
  if (!res.ok) return;
  const tickets = await res.json();
  const tbody = document.querySelector('#queue tbody');
  tbody.innerHTML = '';
  if (!tickets.length) {
    tbody.innerHTML = '<tr><td colspan="7">Задачи не найдены</td></tr>';
    return;
  }
  tbody.innerHTML = tickets.map(t => {
    const overdueClass = t.is_overdue ? ' class="overdue"' : '';
    return `<tr${overdueClass}>
      <td><a href="/ticket/${t.ticket_uid}">${esc(t.ticket_number)}</a></td>
      <td>${esc(t.summary)}</td>
      <td>
        <select onchange="changeStatus('${t.ticket_uid}', this.value)">
          ${STATUSES.map(s => `<option value="${s.value}" ${s.value===t.status?'selected':''}>${s.label}</option>`).join('')}
        </select>
      </td>
      <td>${esc(t.performer || '—')}</td>
      <td>${prettyDate(t.deadline_at)}</td>
      <td>${esc(PRIORITY_LABELS[t.priority] || t.priority || 'Средний')}</td>
      <td><button onclick="openAssign('${t.ticket_uid}')">Назначить</button></td>
    </tr>`;
  }).join('');
}

async function applyFilter() {
  const f  = document.getElementById('filter-select')?.value || 'all';
  const u  = document.getElementById('user-select')?.value  || '';
  const wg = document.getElementById('wg-select')?.value    || '';
  await loadTickets(f, u, wg);
}

async function loadUsers() {
  const res = await fetch('/api/specialists');
  if (!res.ok) return;
  const users = await res.json();
  const byPerformer = document.getElementById('user-select');
  const assignUser  = document.getElementById('assign-user');
  if (!byPerformer || !assignUser) return;
  const options = users.map(u => `<option value="${u.user_uid}">${esc(u.full_name)}</option>`).join('');
  byPerformer.innerHTML = '<option value="">— по исполнителю —</option>' + options;
  assignUser.innerHTML  = '<option value="">Выбрать исполнителя</option>' + options;
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
  const list  = document.getElementById('notif-list');
  if (!badge || !list) return;
  badge.textContent = data.count;
  badge.classList.toggle('hidden', !data.count);
  list.innerHTML = data.items.length
    ? data.items.map(i => `<li><a href="/ticket/${i.ticket_uid}">${esc(i.message)}</a></li>`).join('')
    : '<li class="muted">Нет непрочитанных уведомлений</li>';
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
  document.getElementById('wg-select')?.addEventListener('change', applyFilter);
  setInterval(pollNotifications, 15000);
  pollNotifications();
});
