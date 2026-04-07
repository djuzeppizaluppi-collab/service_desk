function showToast(message) {
  alert(message);
}

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {})
  });
  return r.json();
}

async function deactivateUser(uid) {
  if (!confirm('Деактивировать пользователя?')) return;
  const d = await postJSON(`/admin/delete-user/${uid}`);
  if (d.success) location.reload(); else showToast(d.error || 'Ошибка');
}

async function resetPassword(uid) {
  const d = await postJSON(`/admin/reset-password/${uid}`);
  if (d.success) showToast(`Новый пароль: ${d.new_password}`); else showToast(d.error || 'Ошибка');
}

async function deleteCategory(uid) {
  if (!confirm('Деактивировать категорию/услугу?')) return;
  const d = await postJSON(`/admin/delete-category/${uid}`);
  if (d.success) location.reload(); else showToast(d.error || 'Ошибка');
}

async function createWorkGroup() {
  const name = document.getElementById('wg_name').value.trim();
  const desc = document.getElementById('wg_desc').value.trim();
  if (!name) return showToast('Введите название группы');
  const d = await postJSON('/admin/create-work-group', {group_name: name, group_description: desc});
  if (d.success) location.reload(); else showToast(d.error || 'Ошибка');
}

async function deleteWorkGroup(uid) {
  if (!confirm('Удалить рабочую группу?')) return;
  const d = await postJSON(`/admin/delete-work-group/${uid}`);
  if (d.success) location.reload(); else showToast(d.error || 'Ошибка');
}

async function createTicket() {
  const catalog_uid = document.getElementById('new_catalog_uid').value;
  const summary = document.getElementById('new_summary').value.trim();
  const description = document.getElementById('new_description').value.trim();
  const d = await postJSON('/api/tickets', {catalog_uid, summary, description});
  if (d.success) {
    showToast(`Заявка создана: ${d.ticket_number}`);
    window.location.reload();
  } else {
    showToast(d.error || 'Ошибка');
  }
}
