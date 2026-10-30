// Fills the live prices on the landing page from the same catalog the app and Sokosumi use.
try {
  const c = await (await fetch('api/config')).json();
  for (const el of document.querySelectorAll('[data-price]')) el.textContent = c.services[el.dataset.price]?.price.display || '';
} catch { for (const el of document.querySelectorAll('[data-price]')) el.textContent = 'see app'; }
