function openModal(id) { document.getElementById(id).style.display = 'flex'; }
function closeModal(id) { document.getElementById(id).style.display = 'none'; }
async function resetPassword(uid) {
  const r = await fetch(`/admin/reset-password/${uid}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
  });
  const d = await r.json();
  alert(d.success ? `Новый пароль: ${d.new_password}` : d.error || 'Ошибка');
}
