// Editor overlay: runs in the editor page and drives the preview iframe.
// The iframe is same-origin, so we reach into its document for selection,
// drag and resize. Results are reported to Python via emitEvent().
(function () {
  const SNAP = 0.5;          // percent grid for drag/resize
  const CENTER_SNAP = 1.0;   // percent tolerance for snapping to slide centre
  const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

  const state = {
    iframe: null,
    doc: null,
    slide: null,
    selection: null,   // {kind: 'place'|'title'|'cell'|'content', index, cell}
    box: null,
    guides: null,
    drag: null,
    suppressClick: 0,
  };

  const STYLE = `
    .ce-hover { outline: 1px dashed rgba(30, 120, 255, 0.55) !important; outline-offset: 2px; }
    .ce-selected-flow { outline: 2px solid rgba(30, 120, 255, 0.85) !important; outline-offset: 3px; }
    .colloquium-place { cursor: move; }
    .ce-box { position: absolute; pointer-events: none; z-index: 1000; border: 2px solid #1e78ff; box-sizing: border-box; }
    .ce-handle { position: absolute; width: 12px; height: 12px; background: #fff; border: 2px solid #1e78ff; border-radius: 2px; pointer-events: auto; box-sizing: border-box; transform: translate(-50%, -50%); }
    .ce-handle-nw { left: 0; top: 0; cursor: nwse-resize; }
    .ce-handle-n { left: 50%; top: 0; cursor: ns-resize; }
    .ce-handle-ne { left: 100%; top: 0; cursor: nesw-resize; }
    .ce-handle-e { left: 100%; top: 50%; cursor: ew-resize; }
    .ce-handle-se { left: 100%; top: 100%; cursor: nwse-resize; }
    .ce-handle-s { left: 50%; top: 100%; cursor: ns-resize; }
    .ce-handle-sw { left: 0; top: 100%; cursor: nesw-resize; }
    .ce-handle-w { left: 0; top: 50%; cursor: ew-resize; }
    .ce-guide { position: absolute; pointer-events: none; z-index: 999; background: rgba(255, 70, 120, 0.8); display: none; }
    .ce-guide-v { top: 0; bottom: 0; width: 1px; left: 50%; }
    .ce-guide-h { left: 0; right: 0; height: 1px; top: 50%; }
    .ce-readout { position: absolute; pointer-events: none; z-index: 1001; font: 12px/1.4 system-ui, sans-serif; background: #1e78ff; color: #fff; padding: 1px 6px; border-radius: 3px; white-space: nowrap; transform: translateY(-100%); margin-top: -6px; }
    .colloquium-place-layer { pointer-events: none; }
    .slide .colloquium-place-layer .colloquium-place { pointer-events: auto; }
  `;

  function emit(name, data) {
    if (typeof emitEvent === "function") emitEvent(name, data || {});
  }

  function slideRect() {
    return state.slide.getBoundingClientRect();
  }

  function toPercent(clientX, clientY) {
    const r = slideRect();
    return {
      x: ((clientX - r.left) / r.width) * 100,
      y: ((clientY - r.top) / r.height) * 100,
    };
  }

  function elPercentBox(el) {
    const r = slideRect();
    const b = el.getBoundingClientRect();
    return {
      x: ((b.left - r.left) / r.width) * 100,
      y: ((b.top - r.top) / r.height) * 100,
      w: (b.width / r.width) * 100,
      h: (b.height / r.height) * 100,
    };
  }

  function snap(v) {
    return Math.round(v / SNAP) * SNAP;
  }

  function round(v) {
    return Math.round(v * 10) / 10;
  }

  // ---------- selection visuals ----------
  function ensureBox() {
    if (state.box && state.box.parentNode === state.slide) return state.box;
    const box = state.doc.createElement("div");
    box.className = "ce-box";
    HANDLES.forEach((h) => {
      const el = state.doc.createElement("div");
      el.className = "ce-handle ce-handle-" + h;
      el.dataset.handle = h;
      el.addEventListener("mousedown", onHandleDown);
      box.appendChild(el);
    });
    const readout = state.doc.createElement("div");
    readout.className = "ce-readout";
    box.appendChild(readout);
    state.slide.appendChild(box);
    state.box = box;

    const gv = state.doc.createElement("div");
    gv.className = "ce-guide ce-guide-v";
    const gh = state.doc.createElement("div");
    gh.className = "ce-guide ce-guide-h";
    state.slide.appendChild(gv);
    state.slide.appendChild(gh);
    state.guides = { v: gv, h: gh };
    return box;
  }

  function clearFlowSelection() {
    state.doc.querySelectorAll(".ce-selected-flow").forEach((el) => el.classList.remove("ce-selected-flow"));
  }

  function hideBox() {
    if (state.box) state.box.style.display = "none";
  }

  function placeEl(index) {
    return state.slide.querySelector('.colloquium-place[data-place-index="' + index + '"]');
  }

  function updateBox(el) {
    const box = ensureBox();
    const p = elPercentBox(el);
    box.style.display = "block";
    box.style.left = p.x + "%";
    box.style.top = p.y + "%";
    box.style.width = p.w + "%";
    box.style.height = p.h + "%";
    const ro = box.querySelector(".ce-readout");
    ro.textContent = `x ${round(p.x)}  y ${round(p.y)}  w ${round(p.w)}  h ${round(p.h)}`;
  }

  function applySelection() {
    clearFlowSelection();
    hideBox();
    const sel = state.selection;
    if (!sel || !state.slide) return;
    if (sel.kind === "place") {
      const el = placeEl(sel.index);
      if (el) updateBox(el);
      return;
    }
    const target = flowTarget(sel);
    if (target) target.classList.add("ce-selected-flow");
  }

  function flowTarget(sel) {
    if (sel.kind === "title") return state.slide.querySelector("h1, h2");
    const content = state.slide.querySelector(".slide-content");
    if (!content) return null;
    if (sel.kind === "cell") {
      const cells = content.querySelectorAll(":scope > .col, :scope > .colloquium-row");
      return cells[sel.index] || content;
    }
    return content;
  }

  // ---------- hit testing ----------
  function hitTest(target) {
    if (!state.slide.contains(target)) return null;
    const place = target.closest(".colloquium-place");
    if (place) return { kind: "place", index: parseInt(place.dataset.placeIndex, 10) };
    if (target.closest(".ce-box")) return state.selection;
    const heading = target.closest("h1, h2");
    if (heading && heading.parentElement === state.slide) return { kind: "title", index: 0 };
    const content = state.slide.querySelector(".slide-content");
    if (content && content.contains(target)) {
      const cells = Array.from(content.querySelectorAll(":scope > .col, :scope > .colloquium-row"));
      for (let i = 0; i < cells.length; i++) {
        if (cells[i].contains(target)) return { kind: "cell", index: i };
      }
      return { kind: "content", index: 0 };
    }
    return { kind: "slide", index: 0 };
  }

  // ---------- events inside the iframe ----------
  function onMouseOver(e) {
    state.doc.querySelectorAll(".ce-hover").forEach((el) => el.classList.remove("ce-hover"));
    if (state.drag) return;
    const hit = hitTest(e.target);
    if (!hit) return;
    let el = null;
    if (hit.kind === "place") el = placeEl(hit.index);
    else if (hit.kind !== "slide") el = flowTarget(hit);
    if (el && !(state.selection && sameSel(hit, state.selection))) el.classList.add("ce-hover");
  }

  function sameSel(a, b) {
    return a && b && a.kind === b.kind && a.index === b.index;
  }

  function onClick(e) {
    if (state.suppressClick) {
      // A drag just ended; swallow the click it generates (but only that one).
      const fresh = Date.now() - state.suppressClick < 400;
      state.suppressClick = false;
      if (fresh) {
        e.preventDefault();
        e.stopPropagation();
        return;
      }
    }
    const hit = hitTest(e.target);
    if (!hit) return;
    e.preventDefault();
    e.stopPropagation();
    select(hit, true);
  }

  function select(sel, notify) {
    state.selection = sel && sel.kind !== "slide" ? sel : null;
    applySelection();
    if (notify) emit("ce-select", state.selection || { kind: "slide", index: 0 });
  }

  function onMouseDown(e) {
    if (e.button !== 0) return;
    const place = e.target.closest(".colloquium-place");
    if (!place || !state.slide.contains(place)) return;
    const index = parseInt(place.dataset.placeIndex, 10);
    if (!(state.selection && state.selection.kind === "place" && state.selection.index === index)) {
      select({ kind: "place", index: index }, true);
    }
    e.preventDefault();
    const start = toPercent(e.clientX, e.clientY);
    const box = elPercentBox(place);
    state.drag = {
      mode: "move", el: place, index: index, start: start,
      orig: box, moved: false,
      autoHeight: !place.style.height || place.getAttribute("data-auto-height") === "1",
      aspect: box.h > 0 ? box.w / box.h : 1,
    };
  }

  function onHandleDown(e) {
    if (e.button !== 0 || !state.selection || state.selection.kind !== "place") return;
    const el = placeEl(state.selection.index);
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    const box = elPercentBox(el);
    state.drag = {
      mode: "resize", handle: e.currentTarget.dataset.handle, el: el,
      index: state.selection.index, start: toPercent(e.clientX, e.clientY),
      orig: box, moved: false,
      autoHeight: !el.style.height || el.getAttribute("data-auto-height") === "1",
      isImage: el.classList.contains("colloquium-place--image"),
      aspect: box.h > 0 ? box.w / box.h : 1,
    };
  }

  function showGuides(x, y, w, h) {
    if (!state.guides) return;
    const cx = x + w / 2;
    const cy = y + h / 2;
    state.guides.v.style.display = Math.abs(cx - 50) < 0.05 ? "block" : "none";
    state.guides.h.style.display = Math.abs(cy - 50) < 0.05 ? "block" : "none";
  }

  function onMouseMove(e) {
    const d = state.drag;
    if (!d) return;
    const cur = toPercent(e.clientX, e.clientY);
    let dx = cur.x - d.start.x;
    let dy = cur.y - d.start.y;
    if (Math.abs(dx) > 0.05 || Math.abs(dy) > 0.05) d.moved = true;
    let x = d.orig.x, y = d.orig.y, w = d.orig.w, h = d.orig.h;

    if (d.mode === "move") {
      x = snap(d.orig.x + dx);
      y = snap(d.orig.y + dy);
      if (!e.altKey) {
        if (Math.abs(x + w / 2 - 50) < CENTER_SNAP) x = 50 - w / 2;
        if (Math.abs(y + h / 2 - 50) < CENTER_SNAP) y = 50 - h / 2;
      }
    } else {
      const hnd = d.handle;
      const keepAspect = (d.isImage && hnd.length === 2) !== e.shiftKey;
      if (hnd.includes("e")) w = d.orig.w + dx;
      if (hnd.includes("s")) h = d.orig.h + dy;
      if (hnd.includes("w")) { w = d.orig.w - dx; x = d.orig.x + dx; }
      if (hnd.includes("n")) { h = d.orig.h - dy; y = d.orig.y + dy; }
      w = Math.max(2, w);
      h = Math.max(1, h);
      if (keepAspect && hnd.length === 2) {
        // corner drag on an image: width wins, height follows the aspect ratio
        h = w / d.aspect;
        if (hnd.includes("n")) y = d.orig.y + d.orig.h - h;
      }
      w = snap(w); h = snap(h); x = snap(x); y = snap(y);
    }

    d.el.style.left = x + "%";
    d.el.style.top = y + "%";
    d.el.style.width = w + "%";
    const heightExplicit = d.mode === "resize" && (!d.autoHeight || d.handle.includes("n") || d.handle.includes("s")) && !(d.isImage && d.handle.length === 2 && d.autoHeight);
    if (d.mode === "resize") {
      d.el.style.height = h + "%";
      d.heightExplicit = heightExplicit;
    }
    d.last = { x, y, w, h };
    updateBox(d.el);
    showGuides(x, y, w, h);
  }

  function onMouseUp(e) {
    const d = state.drag;
    if (!d) return;
    state.drag = null;
    if (state.guides) { state.guides.v.style.display = "none"; state.guides.h.style.display = "none"; }
    if (!d.moved) return;
    state.suppressClick = Date.now();
    const p = d.last || d.orig;
    const payload = { index: d.index, x: round(p.x), y: round(p.y), w: round(p.w) };
    if (d.mode === "resize") {
      if (d.heightExplicit) payload.h = round(p.h);
      else if (!d.autoHeight) payload.h = round(p.h);
    } else if (!d.autoHeight) {
      payload.h = round(p.h);
    }
    emit("ce-place-update", payload);
  }

  function onKeyDown(e) {
    if (!state.selection || state.selection.kind !== "place") return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea") return;
    const el = placeEl(state.selection.index);
    if (!el) return;
    const step = e.shiftKey ? 2 : 0.5;
    const p = elPercentBox(el);
    let dx = 0, dy = 0;
    if (e.key === "ArrowLeft") dx = -step;
    else if (e.key === "ArrowRight") dx = step;
    else if (e.key === "ArrowUp") dy = -step;
    else if (e.key === "ArrowDown") dy = step;
    else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      emit("ce-place-delete", { index: state.selection.index });
      return;
    } else if (e.key === "Escape") {
      select(null, true);
      return;
    } else return;
    e.preventDefault();
    const payload = { index: state.selection.index, x: round(p.x + dx), y: round(p.y + dy), w: round(p.w) };
    if (el.style.height && el.getAttribute("data-auto-height") !== "1") payload.h = round(p.h);
    el.style.left = payload.x + "%";
    el.style.top = payload.y + "%";
    updateBox(el);
    emit("ce-place-update", payload);
  }

  // ---------- binding ----------
  function bind() {
    const iframe = state.iframe;
    let doc;
    try { doc = iframe.contentDocument; } catch (err) { return; }
    if (!doc || !doc.body) return;
    state.doc = doc;
    state.box = null;
    state.guides = null;
    const style = doc.createElement("style");
    style.textContent = STYLE;
    doc.head.appendChild(style);
    const refreshSlide = () => {
      state.slide = doc.querySelector(".slide.active");
      applySelection();
    };
    refreshSlide();
    doc.addEventListener("click", onClick, true);
    doc.addEventListener("mousedown", onMouseDown, true);
    doc.addEventListener("mousemove", onMouseMove, true);
    doc.addEventListener("mouseup", onMouseUp, true);
    doc.addEventListener("mouseover", onMouseOver, true);
    doc.addEventListener("keydown", onKeyDown, true);
    iframe.contentWindow.addEventListener("hashchange", refreshSlide);
    iframe.contentWindow.addEventListener("resize", applySelection);
    // Images and fonts settle after load; re-fit the selection box a few times.
    [100, 400, 1000].forEach((t) => setTimeout(applySelection, t));
    emit("ce-ready", {});
  }

  window.colloquiumEditor = {
    attach(id) {
      const iframe = document.getElementById(id);
      if (!iframe) return;
      state.iframe = iframe;
      iframe.addEventListener("load", bind);
      if (iframe.contentDocument && iframe.contentDocument.readyState === "complete" && iframe.contentDocument.querySelector(".slide")) bind();
    },
    select(sel) {
      state.selection = sel && sel.kind !== "slide" ? sel : null;
      applySelection();
    },
    refresh() {
      applySelection();
    },
  };
})();
