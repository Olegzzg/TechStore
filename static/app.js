// Небольшие улучшения форм. Все проверки и права повторяются на сервере.
document.querySelectorAll('.show-password').forEach(button => {
  button.addEventListener('click', () => {
    const input = button.parentElement.querySelector('input');
    input.type = input.type === 'password' ? 'text' : 'password';
    button.setAttribute('aria-label', input.type === 'text' ? 'Скрыть пароль' : 'Показать пароль');
  });
});
document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
document.querySelectorAll('[data-remove]').forEach(button => {
  button.addEventListener('click', () => {
    button.form.querySelector('input[name="quantity"]').value = '0';
  });
});
document.querySelectorAll('img').forEach(img => {
  img.addEventListener('error', () => {
    if (!img.src.endsWith('/static/images/placeholder.svg')) img.src = '/static/images/placeholder.svg';
  });
});
