// Users page (administrator only): add, rename, reset password, disable / enable.
import { api } from './api.js';
import { confirmDialog, el, openModal, reloadWith, showFieldErrors, toast } from './ui.js';

const form = document.getElementById('user-form');
const usernameInput = document.getElementById('user-username');
const fullNameInput = document.getElementById('user-full-name');

// Username: letters only, forced to uppercase while typing.
usernameInput.addEventListener('input', () => {
  usernameInput.value = usernameInput.value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3);
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const username = usernameInput.value.trim().toUpperCase();
  const fullName = fullNameInput.value.trim();
  const errors = {};
  if (!/^[A-Z]{3}$/.test(username)) errors.username = 'Username must be 3 uppercase English letters (e.g. ABC).';
  if (!fullName) errors.full_name = 'Full name is required.';
  showFieldErrors(form, errors);
  if (Object.keys(errors).length) return;

  try {
    await api.post('/api/users', { username, full_name: fullName });
    reloadWith(`User ${username} created. They log in with the default password, then set their own.`);
  } catch (err) {
    showFieldErrors(form, err.fields && Object.keys(err.fields).length ? err.fields : { username: err.message });
  }
});

const rowOf = (btn) => btn.closest('tr');

document.querySelectorAll('.js-reset-user').forEach((btn) => btn.addEventListener('click', async () => {
  const { userId, username } = rowOf(btn).dataset;
  const ok = await confirmDialog({
    title: 'Reset password?',
    message: `Reset ${username}'s password to the default password? They will have to set a new one at next login.`,
    confirmText: 'Reset password',
    danger: false,
  });
  if (!ok) return;
  try {
    await api.post(`/api/users/${userId}/reset-password`);
    reloadWith(`${username}'s password was reset to the default password.`);
  } catch (err) {
    toast(err.message, 'error');
  }
}));

document.querySelectorAll('.js-toggle-user').forEach((btn) => btn.addEventListener('click', async () => {
  const { userId, username, active } = rowOf(btn).dataset;
  const disabling = active === 'true';
  if (disabling) {
    const ok = await confirmDialog({
      title: 'Disable user?',
      message: `${username} will be logged out and cannot log in until you enable the account again.`,
      confirmText: 'Disable',
    });
    if (!ok) return;
  }
  try {
    await api.put(`/api/users/${userId}`, { active: !disabling });
    reloadWith(`${username} ${disabling ? 'disabled' : 'enabled'}.`);
  } catch (err) {
    toast(err.message, 'error');
  }
}));

document.querySelectorAll('.js-rename-user').forEach((btn) => btn.addEventListener('click', () => {
  const { userId, username, fullName } = rowOf(btn).dataset;
  const input = el('input', { id: 'rename-user', name: 'full_name', class: 'input', maxlength: 120, value: fullName });
  const renameForm = el('form', { id: 'rename-user-form', novalidate: true },
    el('div', { class: 'field' }, el('label', { for: 'rename-user' }, 'Full name'), input));
  const cancel = el('button', { type: 'button', class: 'btn' }, 'Cancel');
  const save = el('button', { type: 'submit', form: 'rename-user-form', class: 'btn btn-primary' }, 'Save');
  const m = openModal({ title: `Rename ${username}`, size: 'sm', body: renameForm, footer: [cancel, save] });
  cancel.addEventListener('click', m.close);
  input.focus();
  input.select();
  renameForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = input.value.trim();
    if (!name) return showFieldErrors(renameForm, { full_name: 'Full name is required.' });
    save.disabled = true;
    try {
      await api.put(`/api/users/${userId}`, { full_name: name });
      reloadWith(`${username} renamed.`);
    } catch (err) {
      showFieldErrors(renameForm, err.fields && Object.keys(err.fields).length ? err.fields : { full_name: err.message });
      save.disabled = false;
    }
  });
}));
