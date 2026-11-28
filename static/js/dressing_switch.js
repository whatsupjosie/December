/* PubCast dressing-room switch: a labeled tab on the right edge of the screen that
 * moves between the boudoir (Primp, makeup) and the mirror and stage (Avatar Foundry),
 * so an avatar can be adjusted and made up back and forth while it is being designed.
 *
 * Each page passes beforeLeave(): it keeps that page's work in progress in this browser
 * tab and returns true, or returns false to stay. The page it opens restores the work.
 * Icons are drawn here (no image files): a makeup brush and a tailor's dress form.
 */
(function () {
  'use strict';

  const ICONS = {
    // Makeup brush (blush brush): rounded handle top right, metal ferrule, full domed bristle tuft.
    brush: '<svg viewBox="0 0 32 32" aria-hidden="true" focusable="false"><g transform="rotate(45 16 16)">' +
      '<path d="M15.1 1.6C15.1.8 16.9.8 16.9 1.6L17.6 14.4H14.4Z" fill="currentColor"/>' +
      '<rect x="13.5" y="14" width="5" height="4.2" rx=".7" fill="currentColor" opacity=".7"/>' +
      '<path d="M13.7 18.2C10.8 19.8 9.6 23 10.3 26 10.9 28.6 13.6 31 16 32 18.4 31 21.1 28.6 21.7 26 22.4 23 21.2 19.8 18.3 18.2Z" fill="currentColor"/>' +
      '<path d="M15.2 19.4 13.2 28.2M16 19.4V30.2M16.8 19.4 18.8 28.2" fill="none" stroke="var(--dsw-bg)" stroke-width=".8" stroke-linecap="round" opacity=".55"/>' +
      '</g></svg>',
    // Lipstick: case, gold ring, bullet with the slanted tip.
    lipstick: '<svg viewBox="0 0 32 32" aria-hidden="true" focusable="false"><g transform="rotate(20 16 16)">' +
      '<path d="M12.6 9.2C12.6 6.6 13.4 3.8 16.6 1.8 18.6 1.8 19.4 3.4 19.4 5.4V13.2H12.6Z" fill="currentColor"/>' +
      '<path d="M16.4 3.4C15.2 4.6 14.6 6.4 14.5 8.4" fill="none" stroke="var(--dsw-bg)" stroke-width=".9" stroke-linecap="round" opacity=".5"/>' +
      '<rect x="11.4" y="13.2" width="9.2" height="3.4" rx=".6" fill="currentColor" opacity=".7"/>' +
      '<rect x="10.4" y="16.6" width="11.2" height="13.6" rx="1.4" fill="currentColor"/>' +
      '<path d="M10.8 19.4H21.2" fill="none" stroke="var(--dsw-bg)" stroke-width=".9" opacity=".6"/>' +
      '</g></svg>',
    // Tailor's dress form: neck knob, shoulders, bust, waist and hips, pole and three-legged stand.
    mannequin: '<svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">' +
      '<circle cx="16" cy="3.2" r="1.6" fill="currentColor"/>' +
      '<path d="M14.7 4.4h2.6v2.8h-2.6z" fill="currentColor"/>' +
      '<path d="M13.6 6.8C11.6 7 10 7.6 9.6 9 9.2 10.6 9.4 12.2 10.2 13.4 10.9 14.4 11.6 14.9 11.6 15.8 11.6 17 10.2 18 10 19.8 10 20.4 10.4 20.8 11 20.8H21C21.6 20.8 22 20.4 22 19.8 21.8 18 20.4 17 20.4 15.8 20.4 14.9 21.1 14.4 21.8 13.4 22.6 12.2 22.8 10.6 22.4 9 22 7.6 20.4 7 18.4 6.8Z" fill="currentColor"/>' +
      '<path d="M16 7.6V20.2" fill="none" stroke="var(--dsw-bg)" stroke-width=".9" stroke-dasharray="1.4 1.2" opacity=".75"/>' +
      '<path d="M16 20.8V27.4M16 27.4 10.6 30.6M16 27.4 21.4 30.6M16 27.4V30.8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>' +
      '</svg>',
  };

  // The page keeps a strip clear on the right (body.dsw-reserve), so the tab
  // never sits over a control. The tab stays vertically centred at every size,
  // clear of the bottom corners where other floating buttons live.
  // Josie's art (static/img/dressing_switch/, cut from brush_and_mannequin_original.png).
  const ART = {brush: '/static/img/dressing_switch/brush.png', mannequin: '/static/img/dressing_switch/mannequin.png'};

  const STYLE = `
body.dsw-reserve{padding-right:88px}
.dsw-tab{position:fixed;right:0;top:50%;transform:translateY(-50%);z-index:2147483000;
  display:flex;flex-direction:column;align-items:center;gap:6px;width:82px;padding:12px 6px 12px 8px;
  border:2px solid var(--dsw-line);border-right:0;border-radius:12px 0 0 12px;
  background:var(--dsw-bg);color:var(--dsw-ink);font:600 12px/1.2 system-ui,-apple-system,"Segoe UI",Arial,sans-serif;
  text-align:center;cursor:pointer;box-shadow:-4px 0 18px rgba(0,0,0,.45)}
.dsw-tab svg{width:42px;height:42px;color:var(--dsw-icon)}
.dsw-tab .dsw-art{height:64px;width:auto;display:block;filter:drop-shadow(0 1px 2px rgba(0,0,0,.5))}
.dsw-tab:hover{background:var(--dsw-hover)}
.dsw-tab:focus-visible{outline:2px solid var(--dsw-icon);outline-offset:2px}
.dsw-tab[aria-busy=true]{opacity:.6;cursor:progress}
@media (max-width:600px){body.dsw-reserve{padding-right:60px}.dsw-tab{width:56px;padding:10px 4px 10px 5px;font-size:10px}.dsw-tab svg{width:32px;height:32px}.dsw-tab .dsw-art{height:44px}}`;

  function mount(options) {
    const o = Object.assign({icon: 'brush', label: '', title: '', href: '', theme: {}, beforeLeave: null}, options);
    if (!(ICONS[o.icon] || ART[o.icon]) || !o.href || !o.label) throw new Error('dressing switch: icon, label and href are required');
    if (!document.getElementById('dsw-style')) {
      const style = document.createElement('style'); style.id = 'dsw-style'; style.textContent = STYLE;
      document.head.append(style);
    }
    // Pink and black (Josie, 2026-11-27), the same on both pages.
    const t = Object.assign({bg: '#0a0809', ink: '#f4a7c6', icon: '#f4a7c6', line: '#f4a7c6', hover: '#1f1419'}, o.theme);
    const tab = document.createElement('button');
    tab.type = 'button'; tab.className = 'dsw-tab'; tab.id = 'dressing-switch';
    tab.title = o.title || o.label; tab.setAttribute('aria-label', o.title || o.label);
    for (const [k, v] of Object.entries(t)) tab.style.setProperty('--dsw-' + k, v);
    if (ART[o.icon]) {
      const img = document.createElement('img'); img.src = ART[o.icon]; img.alt = ''; img.className = 'dsw-art';
      img.decoding = 'async'; img.draggable = false; tab.append(img);
    } else tab.innerHTML = ICONS[o.icon];
    const text = document.createElement('span'); text.textContent = o.label; tab.append(text);
    tab.addEventListener('click', async () => {
      if (tab.getAttribute('aria-busy') === 'true') return;
      tab.setAttribute('aria-busy', 'true');
      try {
        if (o.beforeLeave && !(await o.beforeLeave())) return;
        location.assign(o.href);   // same window, so a Counter tray stays a tray
      } finally { tab.setAttribute('aria-busy', 'false'); }
    });
    document.body.classList.add('dsw-reserve');
    document.body.append(tab);
    return tab;
  }

  window.PubCastDressingSwitch = Object.freeze({mount, ICONS, ART});
})();
