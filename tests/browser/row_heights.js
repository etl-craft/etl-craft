() => {
  const selector = 'button,input,select,textarea,[role=combobox]';
  const skip = 'table,ul,ol,.react-flow,[role=tablist],[role=dialog],[role=listbox],[role=menu]';
  // A bordered wrapper marked data-control is one control: measure what the person sees.
  const seen = (el) => el.closest('[data-control]') || el;
  const controls = [...new Set([...document.querySelectorAll(selector)].filter((el) => {
    if (el.closest(skip) || ['checkbox', 'radio', 'hidden', 'file'].includes(el.type)) return false;
    if (['switch', 'tab', 'treeitem'].includes(el.getAttribute('role'))) return false;
    const box = seen(el).getBoundingClientRect();
    return box.width > 0 && box.height > 0 && !el.classList.contains('sr-only');
  }).map(seen))];
  const name = (el) => el.getAttribute('aria-label') || el.placeholder || el.textContent.trim().slice(0, 24) || el.tagName;
  const byHeight = new Map();
  for (const el of controls) {
    const height = Math.round(el.getBoundingClientRect().height);
    byHeight.set(height, [...(byHeight.get(height) || []), name(el)]);
  }
  if (byHeight.size < 2) return [];
  const sizes = [...byHeight.keys()].sort((a, b) => a - b);
  if (sizes[sizes.length - 1] - sizes[0] <= 1) return [];
  return [...byHeight].map(([height, names]) => height + 'px: ' + names.join(' | '));
}
