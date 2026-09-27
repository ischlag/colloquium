"""Slide-list pane: the built deck shown as a contact sheet inside an iframe."""

THUMBS_CSS = """
html, body { background: #f7f8fa !important; margin: 0; padding: 8px 10px; overflow-y: auto !important; overflow-x: hidden; }
.colloquium-deck { position: static !important; transform: none !important; width: auto !important; height: auto !important; background: none !important; overflow: visible !important; padding: 6px 4px; counter-reset: ce-slide; }
.slide { display: flex !important; position: relative !important; zoom: 0.1555; margin: 0 0 70px 0; cursor: pointer; box-shadow: 0 0 0 8px #d7dbe2; counter-increment: ce-slide; overflow: visible !important; }
.slide.ce-current { box-shadow: 0 0 0 28px #1e78ff; }
.slide.ce-drop-before { box-shadow: 0 -60px 0 -20px #1e78ff, 0 0 0 8px #d7dbe2; }
.slide.ce-drop-after { box-shadow: 0 60px 0 -20px #1e78ff, 0 0 0 8px #d7dbe2; }
.slide::before { content: counter(ce-slide); position: absolute; right: 0; bottom: -64px; font: 700 52px/1 system-ui, sans-serif; color: #7b8496; z-index: 5; }
.slide--references::before { content: "refs"; }
.slide--master { counter-increment: none; outline: none !important; box-shadow: 0 0 0 8px #f4a300; }
.slide--master.ce-current { box-shadow: 0 0 0 28px #1e78ff; }
.slide--master::before { content: "theme"; position: absolute; left: auto; top: auto; right: 0; bottom: -64px; padding: 0; background: none; font: 700 52px/1 system-ui, sans-serif; color: #f4a300; text-align: right; }
.colloquium-present, .colloquium-progress, .colloquium-picker-trigger, .colloquium-toast, .colloquium-overflow-warn, .colloquium-picker-overlay { display: none !important; }
.slide * { pointer-events: none; }
.slide.ce-dragging { opacity: 0.4; }
"""

THUMBS_JS = """
(function () {
  function slides() { return Array.from(document.querySelectorAll('.colloquium-deck > .slide')); }
  function send(data) { parent.postMessage(Object.assign({ source: 'ce-thumbs' }, data), '*'); }
  let dragIndex = -1;
  window.ceHighlight = function (index) {
    slides().forEach((s, i) => s.classList.toggle('ce-current', i === index));
    const cur = slides()[index];
    if (cur) cur.scrollIntoView({ block: 'nearest' });
  };
  document.addEventListener('DOMContentLoaded', () => {
    slides().forEach((s, i) => {
      s.setAttribute('draggable', 'true');
      s.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); send({ type: 'click', index: i }); }, true);
      s.addEventListener('dragstart', (e) => { dragIndex = i; s.classList.add('ce-dragging'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(i)); });
      s.addEventListener('dragend', () => { dragIndex = -1; slides().forEach((x) => x.classList.remove('ce-dragging', 'ce-drop-before', 'ce-drop-after')); });
      s.addEventListener('dragover', (e) => {
        if (dragIndex < 0) return;
        e.preventDefault();
        const r = s.getBoundingClientRect();
        const after = e.clientY > r.top + r.height / 2;
        slides().forEach((x) => x.classList.remove('ce-drop-before', 'ce-drop-after'));
        s.classList.add(after ? 'ce-drop-after' : 'ce-drop-before');
      });
      s.addEventListener('drop', (e) => {
        e.preventDefault();
        if (dragIndex < 0) return;
        const r = s.getBoundingClientRect();
        const after = e.clientY > r.top + r.height / 2;
        let dst = i + (after ? 1 : 0);
        if (dragIndex < dst) dst -= 1;
        if (dst !== dragIndex) send({ type: 'move', src: dragIndex, dst: dst });
      });
    });
    send({ type: 'ready' });
  });
})();
"""


def thumbs_html(deck_html: str) -> str:
    """The built deck with every slide visible at thumbnail scale, clickable and draggable."""
    inject = f"<style>{THUMBS_CSS}</style><script>{THUMBS_JS}</script></head>"
    return deck_html.replace("</head>", inject, 1)
