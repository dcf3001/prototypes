// Static JS loaded on every page — only small shared utilities live here.
// Page-specific logic is in each template's {% block scripts %}.

// Prevent double-submit on any form with data-once attribute
document.addEventListener('submit', e => {
  const form = e.target;
  if (form.dataset.once !== undefined) {
    const btn = form.querySelector('[type=submit]');
    if (btn) { btn.disabled = true; btn.textContent = 'Please wait…'; }
  }
});
