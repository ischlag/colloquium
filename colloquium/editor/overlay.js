// Editor overlay: runs in the editor page and drives the preview iframe.
// The iframe is same-origin, so we reach into its document for selection,
// drag and resize. Results are reported to Python via emitEvent().
//
// Element kinds and how they map to the markdown source:
//   place   ```place block (percent coordinates)          -> data-place-index
//   html    raw HTML with inline top/left (px)             -> document order
//   img     inline markdown/html image in the flow         -> document order
//   title   first h1/h2 of the slide
//   cell    a column/row cell (index), content = whole body
(function () {
  const SNAP = 0.5;          // percent grid for drag/resize
  const CENTER_SNAP = 1.0;   // percent tolerance for snapping to slide centre
  const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
  const PX_W = 12.8;         // slide-space px per percent (1280x720)
  const PX_H = 7.2;

  const state = {
    iframe: null,
    doc: null,
    slide: null,
    selection: null,   // primary {kind, index}
    extra: [],         // additional selected movable elements (multi-select)
    box: null,
    extraBoxes: [],
    guides: null,
    drag: null,
    editor: null,
    crop: null,
    suppressClick: 0,
  };

  const STYLE = `
    .ce-hover { outline: 1px dashed rgba(30, 120, 255, 0.55) !important; outline-offset: 2px; }
    .ce-selected-flow { outline: 2px solid rgba(30, 120, 255, 0.85) !important; outline-offset: 3px; }
    .colloquium-place, .ce-html-abs { cursor: move; }
    .ce-box { position: absolute; pointer-events: none; z-index: 1000; border: 2px solid #1e78ff; box-sizing: border-box; }
    .ce-box-extra { position: absolute; pointer-events: none; z-index: 999; border: 2px dashed #1e78ff; box-sizing: border-box; }
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
    .ce-editor { position: absolute; z-index: 1002; box-sizing: border-box; border: 2px solid #1e78ff; outline: none; background: rgba(255,255,255,0.97); color: #111; padding: 4px 6px; resize: none; overflow: auto; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 16px; line-height: 1.35; box-shadow: 0 4px 24px rgba(0,0,0,0.25); }
    .colloquium-place-layer { pointer-events: none; }
    .slide .colloquium-place-layer .colloquium-place { pointer-events: auto; }
    .ce-crop-ghost { position: absolute; opacity: 0.35; pointer-events: none; z-index: 1003; max-width: none; max-height: none; }
    .ce-crop-frame { position: absolute; z-index: 1004; box-sizing: border-box; border: 2px solid #ff8c1e; cursor: move; background: transparent; box-shadow: 0 0 0 9999px rgba(0,0,0,0.25); }
    .ce-crop-frame .ce-handle { border-color: #ff8c1e; }
    .ce-crop-hint { position: absolute; z-index: 1005; left: 50%; top: 8px; transform: translateX(-50%); font: 14px/1.4 system-ui, sans-serif; background: #ff8c1e; color: #fff; padding: 3px 10px; border-radius: 4px; pointer-events: none; }
  `;

  function emit(name, data) {
    if (typeof emitEvent === "function") emitEvent(name, data || {});
  }

  // ---------- geometry helpers ----------
  function slideRect() {
    return state.slide.getBoundingClientRect();
  }

  function toPercent(clientX, clientY) {
    const r = slideRect();
    return { x: ((clientX - r.left) / r.width) * 100, y: ((clientY - r.top) / r.height) * 100 };
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

  function sameSel(a, b) {
    return !!a && !!b && a.kind === b.kind && a.index === b.index;
  }

  function isMovable(sel) {
    return !!sel && (sel.kind === "place" || sel.kind === "html");
  }

  // ---------- element lookup ----------
  function placeEl(index) {
    return state.slide.querySelector('.colloquium-place[data-place-index="' + index + '"]');
  }

  function isEditorNode(el) {
    const cls = typeof el.className === "string" ? el.className : "";
    return cls.split(" ").some((c) => c.startsWith("ce-")) && !cls.includes("ce-html-abs") && !cls.includes("ce-hover") && !cls.includes("ce-selected-flow");
  }

  function htmlAbsEls() {
    return Array.from(state.slide.querySelectorAll("[style]")).filter((el) =>
      (el.style.top || el.style.left) &&
      !el.closest(".colloquium-place-layer") &&
      !isEditorNode(el) && !el.closest(".ce-box") &&
      el.tagName !== "SECTION"
    );
  }

  function htmlAbsOf(target) {
    let el = target;
    while (el && el !== state.slide) {
      if ((el.style.top || el.style.left) && !el.closest(".colloquium-place-layer") && !isEditorNode(el)) return el;
      el = el.parentElement;
    }
    return null;
  }

  function flowImgEls() {
    const content = state.slide.querySelector(".slide-content");
    if (!content) return [];
    return Array.from(content.querySelectorAll("img")).filter((img) =>
      !img.closest(".colloquium-place") && !img.classList.contains("colloquium-chart-print")
    );
  }

  function flowTarget(sel) {
    if (sel.kind === "title") return state.slide.querySelector("h1, h2");
    const content = state.slide.querySelector(".slide-content");
    if (!content) return null;
    if (sel.kind === "cell") {
      const cells = content.querySelectorAll(":scope > .col, :scope > .colloquium-row");
      return cells[sel.index] || content;
    }
    if (sel.kind === "img") return flowImgEls()[sel.index] || null;
    return content;
  }

  function elOf(sel) {
    if (!sel) return null;
    if (sel.kind === "place") return placeEl(sel.index);
    if (sel.kind === "html") return htmlAbsEls()[sel.index] || null;
    return flowTarget(sel);
  }

  function markHtmlAbs() {
    htmlAbsEls().forEach((el) => el.classList.add("ce-html-abs"));
  }

  // ---------- hit testing ----------
  function hitTest(target) {
    if (!state.slide.contains(target)) return null;
    if (target.closest(".ce-editor")) return null;
    const place = target.closest(".colloquium-place");
    if (place) return { kind: "place", index: parseInt(place.dataset.placeIndex, 10) };
    if (target.closest(".ce-box")) return state.selection;
    const abs = htmlAbsOf(target);
    if (abs) return { kind: "html", index: htmlAbsEls().indexOf(abs) };
    const heading = target.closest("h1, h2");
    if (heading && heading.parentElement === state.slide) return { kind: "title", index: 0 };
    const content = state.slide.querySelector(".slide-content");
    if (content && content.contains(target)) {
      const img = target.closest("img");
      if (img) {
        const k = flowImgEls().indexOf(img);
        if (k >= 0) return { kind: "img", index: k };
      }
      const cells = Array.from(content.querySelectorAll(":scope > .col, :scope > .colloquium-row"));
      for (let i = 0; i < cells.length; i++) {
        if (cells[i].contains(target)) return { kind: "cell", index: i };
      }
      return { kind: "content", index: 0 };
    }
    return { kind: "slide", index: 0 };
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

  function setBoxGeometry(box, p) {
    box.style.display = "block";
    box.style.left = p.x + "%";
    box.style.top = p.y + "%";
    box.style.width = p.w + "%";
    box.style.height = p.h + "%";
  }

  function updateBox(el) {
    const box = ensureBox();
    const p = elPercentBox(el);
    setBoxGeometry(box, p);
    const ro = box.querySelector(".ce-readout");
    if (state.selection && state.selection.kind === "html") {
      ro.textContent = `left ${Math.round(p.x * PX_W)}px  top ${Math.round(p.y * PX_H)}px  w ${Math.round(p.w * PX_W)}px`;
    } else if (state.selection && state.selection.kind === "img") {
      ro.textContent = `inline image  w ${Math.round(p.w * PX_W)}px  h ${Math.round(p.h * PX_H)}px  (drag to place freely)`;
    } else {
      ro.textContent = `x ${round(p.x)}  y ${round(p.y)}  w ${round(p.w)}  h ${round(p.h)}`;
    }
  }

  function clearExtraBoxes() {
    state.extraBoxes.forEach((b) => b.parentNode && b.parentNode.removeChild(b));
    state.extraBoxes = [];
  }

  function drawExtraBoxes() {
    clearExtraBoxes();
    state.extra.forEach((s) => {
      const e = elOf(s);
      if (!e) return;
      const b = state.doc.createElement("div");
      b.className = "ce-box-extra";
      setBoxGeometry(b, elPercentBox(e));
      state.slide.appendChild(b);
      state.extraBoxes.push(b);
    });
  }

  function hideBox() {
    if (state.box) state.box.style.display = "none";
    clearExtraBoxes();
  }

  function clearFlowSelection() {
    state.doc.querySelectorAll(".ce-selected-flow").forEach((el) => el.classList.remove("ce-selected-flow"));
  }

  function applySelection() {
    clearFlowSelection();
    hideBox();
    if (!state.slide) return;
    const sel = state.selection;
    if (!sel) return;
    if (isMovable(sel) || sel.kind === "img") {
      const el = elOf(sel);
      if (el) updateBox(el);
      drawExtraBoxes();
      return;
    }
    const target = flowTarget(sel);
    if (target) target.classList.add("ce-selected-flow");
  }

  function select(sel, notify, additive) {
    if (sel && sel.kind === "slide") sel = null;
    if (additive && sel && isMovable(sel) && isMovable(state.selection)) {
      if (sameSel(sel, state.selection)) {
        state.selection = state.extra.shift() || null;
      } else {
        const k = state.extra.findIndex((s) => sameSel(s, sel));
        if (k >= 0) state.extra.splice(k, 1);
        else state.extra.push(sel);
      }
    } else {
      state.selection = sel;
      state.extra = [];
    }
    applySelection();
    if (notify) emit("ce-select", selectionPayload());
  }

  function selectionPayload() {
    const sel = state.selection || { kind: "slide", index: 0 };
    const payload = { kind: sel.kind, index: sel.index, extra: state.extra.slice() };
    const el = elOf(sel);
    if (sel.kind === "img" && el) payload.box = elPercentBox(el);
    if (el && (sel.kind === "html" || sel.kind === "place")) {
      payload.font = parseFloat(state.doc.defaultView.getComputedStyle(el).fontSize) || 0;
    }
    return payload;
  }

  function allSelected() {
    return isMovable(state.selection) ? [state.selection].concat(state.extra) : [];
  }

  // ---------- geometry updates (batched) ----------
  function geometryItem(sel, el, box, opts) {
    opts = opts || {};
    if (sel.kind === "html") {
      const item = { kind: "html", index: sel.index, left: Math.round(box.x * PX_W), top: Math.round(box.y * PX_H) };
      if (opts.width) item.width = Math.round(box.w * PX_W);
      if (opts.height) item.height = Math.round(box.h * PX_H);
      return item;
    }
    const item = { kind: "place", index: sel.index, x: round(box.x), y: round(box.y), w: round(box.w) };
    const autoHeight = !el.style.height || el.getAttribute("data-auto-height") === "1";
    if (opts.height || (!autoHeight && !opts.clearHeight)) item.h = round(box.h);
    return item;
  }

  function emitGeometry(items) {
    if (items.length) emit("ce-geometry", { items: items });
  }

  function applyBoxToEl(sel, el, box, opts) {
    opts = opts || {};
    if (sel.kind === "html") {
      el.style.left = Math.round(box.x * PX_W) + "px";
      el.style.top = Math.round(box.y * PX_H) + "px";
      if (opts.width) { el.style.maxWidth = "none"; el.style.width = Math.round(box.w * PX_W) + "px"; }
      if (opts.height) el.style.height = Math.round(box.h * PX_H) + "px";
    } else {
      el.style.left = box.x + "%";
      el.style.top = box.y + "%";
      if (opts.width) el.style.width = box.w + "%";
      if (opts.height) el.style.height = box.h + "%";
    }
  }

  // ---------- mouse ----------
  function onMouseOver(e) {
    state.doc.querySelectorAll(".ce-hover").forEach((el) => el.classList.remove("ce-hover"));
    if (state.drag || state.editor || state.crop) return;
    const hit = hitTest(e.target);
    if (!hit || hit.kind === "slide") return;
    const el = elOf(hit);
    if (el && !sameSel(hit, state.selection)) el.classList.add("ce-hover");
  }

  function onClick(e) {
    if (state.crop) { e.preventDefault(); e.stopPropagation(); return; }
    if (state.suppressClick) {
      const fresh = Date.now() - state.suppressClick < 400;
      state.suppressClick = 0;
      if (fresh) { e.preventDefault(); e.stopPropagation(); return; }
    }
    if (state.editor) return;
    const hit = hitTest(e.target);
    if (!hit) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.shiftKey && isMovable(hit) && isMovable(state.selection)) {
      select(hit, true, true);
      return;
    }
    select(hit, true);
  }

  function onMouseDown(e) {
    if (e.button !== 0 || state.editor || state.crop) return;
    if (e.target.closest(".ce-box")) return;
    let el = e.target.closest(".colloquium-place");
    let sel = null;
    if (el && state.slide.contains(el)) {
      sel = { kind: "place", index: parseInt(el.dataset.placeIndex, 10) };
    } else {
      el = htmlAbsOf(e.target);
      if (!el) {
        const img = e.target.closest("img");
        const k = img ? flowImgEls().indexOf(img) : -1;
        if (k < 0) return;
        // Dragging an inline image lifts it out of the flow: on drop it becomes
        // a placed image at the drop position.
        if (!sameSel(state.selection, { kind: "img", index: k })) select({ kind: "img", index: k }, true);
        e.preventDefault();
        state.drag = { mode: "move-img", el: img, index: k, start: toPercent(e.clientX, e.clientY), orig: elPercentBox(img), moved: false };
        return;
      }
      sel = { kind: "html", index: htmlAbsEls().indexOf(el) };
    }
    if (e.shiftKey) return; // shift-click toggles membership on click
    const inGroup = allSelected().some((s) => sameSel(s, sel));
    if (!inGroup) select(sel, true);
    e.preventDefault();
    const members = allSelected().map((s) => ({ sel: s, el: elOf(s) })).filter((m) => m.el);
    const primary = members.find((m) => sameSel(m.sel, sel)) || members[0];
    members.forEach((m) => { m.orig = elPercentBox(m.el); });
    state.drag = {
      mode: "move", members: members, primary: primary, start: toPercent(e.clientX, e.clientY),
      orig: elPercentBox(primary.el), moved: false,
    };
  }

  function onHandleDown(e) {
    if (e.button !== 0 || !state.selection) return;
    if (!isMovable(state.selection) && state.selection.kind !== "img") return;
    const el = elOf(state.selection);
    if (!el) return;
    e.preventDefault();
    e.stopPropagation();
    const box = elPercentBox(el);
    if (state.selection.kind === "img") {
      state.drag = {
        mode: "resize-img", handle: e.currentTarget.dataset.handle, el: el, index: state.selection.index,
        start: toPercent(e.clientX, e.clientY), orig: box, moved: false, aspect: box.h > 0 ? box.w / box.h : 1,
      };
      return;
    }
    state.drag = {
      mode: "resize", handle: e.currentTarget.dataset.handle, el: el, sel: state.selection,
      start: toPercent(e.clientX, e.clientY), orig: box, moved: false,
      autoHeight: state.selection.kind === "html" || !el.style.height || el.getAttribute("data-auto-height") === "1",
      isImage: el.classList.contains("colloquium-place--image"),
      aspect: box.h > 0 ? box.w / box.h : 1,
    };
  }

  function showGuides(x, y, w, h) {
    if (!state.guides) return;
    state.guides.v.style.display = Math.abs(x + w / 2 - 50) < 0.05 ? "block" : "none";
    state.guides.h.style.display = Math.abs(y + h / 2 - 50) < 0.05 ? "block" : "none";
  }

  function onMouseMove(e) {
    const d = state.drag;
    if (!d) return;
    const cur = toPercent(e.clientX, e.clientY);
    const dx = cur.x - d.start.x;
    const dy = cur.y - d.start.y;
    if (Math.abs(dx) > 0.05 || Math.abs(dy) > 0.05) d.moved = true;

    if (d.mode === "move-img") {
      d.el.style.transform = `translate(${dx * PX_W}px, ${dy * PX_H}px)`;
      d.el.style.position = "relative";
      d.el.style.zIndex = "50";
      d.last = { x: d.orig.x + dx, y: d.orig.y + dy, w: d.orig.w, h: d.orig.h };
      updateBox(d.el);
      return;
    }
    if (d.mode === "resize-img") {
      const hnd = d.handle;
      let w = d.orig.w, h = d.orig.h;
      if (hnd.includes("e")) w = d.orig.w + dx;
      if (hnd.includes("w")) w = d.orig.w - dx;
      if (hnd.includes("s")) h = d.orig.h + dy;
      if (hnd.includes("n")) h = d.orig.h - dy;
      w = Math.max(2, w); h = Math.max(1, h);
      const vertical = hnd === "n" || hnd === "s";
      if (!vertical) {
        // corners and side handles scale by width, keeping the aspect ratio
        d.el.style.width = Math.round(w * PX_W) + "px";
        d.el.style.height = "auto";
        d.el.style.maxWidth = "none"; d.el.style.maxHeight = "none";
        d.last = { width: w * PX_W };
      } else {
        d.el.style.height = Math.round(h * PX_H) + "px";
        d.el.style.width = "auto";
        d.el.style.maxWidth = "none"; d.el.style.maxHeight = "none";
        d.last = { height: h * PX_H };
      }
      updateBox(d.el);
      return;
    }
    if (d.mode === "move") {
      let x = snap(d.orig.x + dx);
      let y = snap(d.orig.y + dy);
      if (!e.altKey) {
        if (Math.abs(x + d.orig.w / 2 - 50) < CENTER_SNAP) x = 50 - d.orig.w / 2;
        if (Math.abs(y + d.orig.h / 2 - 50) < CENTER_SNAP) y = 50 - d.orig.h / 2;
      }
      const sdx = x - d.orig.x;
      const sdy = y - d.orig.y;
      d.members.forEach((m) => {
        m.last = { x: m.orig.x + sdx, y: m.orig.y + sdy, w: m.orig.w, h: m.orig.h };
        applyBoxToEl(m.sel, m.el, m.last, {});
      });
      updateBox(d.primary.el);
      drawExtraBoxes();
      showGuides(x, y, d.orig.w, d.orig.h);
      return;
    }

    let x = d.orig.x, y = d.orig.y, w = d.orig.w, h = d.orig.h;
    const hnd = d.handle;
    const keepAspect = (d.isImage && hnd.length === 2) !== e.shiftKey;
    if (hnd.includes("e")) w = d.orig.w + dx;
    if (hnd.includes("s")) h = d.orig.h + dy;
    if (hnd.includes("w")) { w = d.orig.w - dx; x = d.orig.x + dx; }
    if (hnd.includes("n")) { h = d.orig.h - dy; y = d.orig.y + dy; }
    w = Math.max(2, w);
    h = Math.max(0.5, h);
    if (keepAspect && hnd.length === 2) {
      h = w / d.aspect;
      if (hnd.includes("n")) y = d.orig.y + d.orig.h - h;
    }
    w = snap(w); h = snap(h); x = snap(x); y = snap(y);
    const vertical = hnd.includes("n") || hnd.includes("s");
    d.heightExplicit = (!d.autoHeight || vertical) && !(d.isImage && hnd.length === 2 && d.autoHeight);
    if (d.sel.kind === "html") {
      applyBoxToEl(d.sel, d.el, { x, y, w, h }, { width: true, height: vertical });
    } else {
      applyBoxToEl(d.sel, d.el, { x, y, w, h }, { width: true, height: true });
    }
    d.last = { x, y, w, h };
    updateBox(d.el);
    showGuides(x, y, w, h);
  }

  function onMouseUp() {
    const d = state.drag;
    if (!d) return;
    state.drag = null;
    if (state.guides) { state.guides.v.style.display = "none"; state.guides.h.style.display = "none"; }
    if (!d.moved) {
      if (d.mode === "move-img") { d.el.style.transform = ""; d.el.style.position = ""; d.el.style.zIndex = ""; }
      return;
    }
    state.suppressClick = Date.now();
    if (d.mode === "move-img") {
      const p = d.last || d.orig;
      emit("ce-img-move", { index: d.index, x: round(p.x), y: round(p.y), w: round(p.w) });
      return;
    }
    if (d.mode === "resize-img") {
      const payload = { index: d.index };
      if (d.last && d.last.width) payload.width = Math.round(d.last.width);
      if (d.last && d.last.height) payload.height = Math.round(d.last.height);
      emit("ce-img-size", payload);
      return;
    }
    if (d.mode === "move") {
      emitGeometry(d.members.map((m) => geometryItem(m.sel, m.el, m.last || m.orig, {})));
      return;
    }
    const p = d.last || d.orig;
    emitGeometry([geometryItem(d.sel, d.el, p, { width: true, height: d.heightExplicit, clearHeight: !d.heightExplicit })]);
  }

  // ---------- keyboard ----------
  function onKeyDown(e) {
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea") return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (state.crop) {
      if (e.key === "Escape") { e.preventDefault(); cropCancel(); }
      else if (e.key === "Enter") { e.preventDefault(); cropCommit(); }
      return;
    }
    if (ctrl && e.shiftKey && (e.key === "v" || e.key === "V")) { e.preventDefault(); emit("ce-command", { name: "paste_inplace" }); return; }
    if (ctrl && (e.key === "z" || e.key === "Z")) { e.preventDefault(); emit("ce-command", { name: e.shiftKey ? "redo" : "undo" }); return; }
    if (ctrl && e.key === "y") { e.preventDefault(); emit("ce-command", { name: "redo" }); return; }
    if (ctrl && e.key === "v") { e.preventDefault(); emit("ce-command", { name: "paste" }); return; }
    if (!state.selection) return;
    if (ctrl && e.key === "c") { e.preventDefault(); emit("ce-command", { name: "copy", selection: allSelected() }); return; }
    if (ctrl && e.key === "d") { e.preventDefault(); emit("ce-command", { name: "duplicate", selection: allSelected() }); return; }
    if (ctrl && (e.key === "b" || e.key === "i")) { e.preventDefault(); format(e.key === "b" ? "bold" : "italic"); return; }
    if (ctrl && (e.key === "ArrowUp" || e.key === "ArrowDown") && isMovable(state.selection)) {
      e.preventDefault();
      const name = e.key === "ArrowUp" ? (e.shiftKey ? "front" : "forward") : (e.shiftKey ? "back" : "backward");
      emit("ce-command", { name: name, selection: [state.selection] });
      return;
    }
    if (e.key === "Enter" || e.key === "F2") { e.preventDefault(); requestEdit(state.selection); return; }
    if (e.key === "Escape") { select(null, true); return; }
    if (!isMovable(state.selection)) return;
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      emit("ce-command", { name: "delete", selection: allSelected() });
      return;
    }
    let dx = 0, dy = 0;
    const step = e.shiftKey ? 2 : 0.5;
    if (e.key === "ArrowLeft") dx = -step; else if (e.key === "ArrowRight") dx = step;
    else if (e.key === "ArrowUp") dy = -step; else if (e.key === "ArrowDown") dy = step;
    else return;
    e.preventDefault();
    nudge(dx, dy);
  }

  function nudge(dx, dy) {
    const items = [];
    allSelected().forEach((s) => {
      const el = elOf(s);
      if (!el) return;
      const b = elPercentBox(el);
      const nb = { x: b.x + dx, y: b.y + dy, w: b.w, h: b.h };
      applyBoxToEl(s, el, nb, {});
      items.push(geometryItem(s, el, nb, {}));
    });
    applySelection();
    emitGeometry(items);
  }

  // ---------- arrange (align / distribute) ----------
  function align(mode) {
    const members = allSelected().map((s) => ({ sel: s, el: elOf(s) })).filter((m) => m.el);
    if (!members.length) return;
    members.forEach((m) => { m.box = elPercentBox(m.el); });
    // Several elements align relative to their common bounding box, one to the slide.
    let ref = { x: 0, y: 0, w: 100, h: 100 };
    if (members.length > 1) {
      const x0 = Math.min(...members.map((m) => m.box.x)), y0 = Math.min(...members.map((m) => m.box.y));
      const x1 = Math.max(...members.map((m) => m.box.x + m.box.w)), y1 = Math.max(...members.map((m) => m.box.y + m.box.h));
      ref = { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
    }
    const items = [];
    members.forEach((m) => {
      const b = { x: m.box.x, y: m.box.y, w: m.box.w, h: m.box.h };
      if (mode === "left") b.x = ref.x;
      else if (mode === "center") b.x = ref.x + ref.w / 2 - b.w / 2;
      else if (mode === "right") b.x = ref.x + ref.w - b.w;
      else if (mode === "top") b.y = ref.y;
      else if (mode === "middle") b.y = ref.y + ref.h / 2 - b.h / 2;
      else if (mode === "bottom") b.y = ref.y + ref.h - b.h;
      b.x = round(b.x); b.y = round(b.y);
      applyBoxToEl(m.sel, m.el, b, {});
      items.push(geometryItem(m.sel, m.el, b, {}));
    });
    applySelection();
    emitGeometry(items);
  }

  function distribute(axis) {
    const members = allSelected().map((s) => ({ sel: s, el: elOf(s) })).filter((m) => m.el);
    if (members.length < 3) return;
    members.forEach((m) => { m.box = elPercentBox(m.el); });
    const key = axis === "x" ? "x" : "y";
    const size = axis === "x" ? "w" : "h";
    members.sort((a, b) => a.box[key] - b.box[key]);
    const first = members[0].box, last = members[members.length - 1].box;
    const total = members.reduce((acc, m) => acc + m.box[size], 0);
    const gap = (last[key] + last[size] - first[key] - total) / (members.length - 1);
    let pos = first[key];
    const items = [];
    members.forEach((m, i) => {
      const b = { x: m.box.x, y: m.box.y, w: m.box.w, h: m.box.h };
      if (i > 0 && i < members.length - 1) b[key] = round(pos);
      pos += b[size] + gap;
      applyBoxToEl(m.sel, m.el, b, {});
      items.push(geometryItem(m.sel, m.el, b, {}));
    });
    applySelection();
    emitGeometry(items);
  }

  // ---------- in-place source editor ----------
  function requestEdit(sel) {
    if (!sel || sel.kind === "slide" || sel.kind === "img") return;
    const el = elOf(sel);
    if (!el) return;
    if (sel.kind === "place" && el.classList.contains("colloquium-place--image")) return;
    emit("ce-edit-request", sel);
  }

  function openEditor(sel, value) {
    closeEditor(false);
    const el = elOf(sel);
    if (!el) return;
    const p = elPercentBox(el);
    const ta = state.doc.createElement("textarea");
    ta.className = "ce-editor";
    ta.value = value || "";
    const cs = state.doc.defaultView.getComputedStyle(el);
    ta.style.left = p.x + "%";
    ta.style.top = p.y + "%";
    ta.style.width = Math.max(p.w, 18) + "%";
    ta.style.minHeight = Math.max(p.h, 6) + "%";
    ta.style.fontSize = Math.max(14, Math.min(parseFloat(cs.fontSize) || 16, 28)) + "px";
    ta.rows = Math.max(2, (value || "").split("\n").length + 1);
    state.slide.appendChild(ta);
    state.editor = { sel: sel, ta: ta, original: value || "" };
    hideBox();
    ta.addEventListener("keydown", (e) => {
      e.stopPropagation();
      const ctrl = e.ctrlKey || e.metaKey;
      if (e.key === "Escape") { e.preventDefault(); closeEditor(false); }
      else if (e.key === "Enter" && ctrl) { e.preventDefault(); closeEditor(true); }
      else if (ctrl && e.key === "b") { e.preventDefault(); wrapSelection(ta, sel.kind, "bold"); }
      else if (ctrl && e.key === "i") { e.preventDefault(); wrapSelection(ta, sel.kind, "italic"); }
    });
    ta.addEventListener("blur", () => closeEditor(true));
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; });
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    ta.style.height = ta.scrollHeight + "px";
  }

  function closeEditor(commit) {
    const ed = state.editor;
    if (!ed) return;
    state.editor = null;
    const value = ed.ta.value;
    if (ed.ta.parentNode) ed.ta.parentNode.removeChild(ed.ta);
    applySelection();
    if (commit && value !== ed.original) emit("ce-edit-commit", { kind: ed.sel.kind, index: ed.sel.index, value: value });
  }

  function onDblClick(e) {
    if (state.editor || state.crop) return;
    const hit = hitTest(e.target);
    if (!hit || hit.kind === "slide") return;
    e.preventDefault();
    e.stopPropagation();
    if (!sameSel(hit, state.selection)) select(hit, true);
    requestEdit(hit);
  }

  // ---------- text formatting ----------
  const MARKS = {
    md: { bold: ["**", "**"], italic: ["*", "*"], code: ["`", "`"] },
    html: { bold: ["<b>", "</b>"], italic: ["<i>", "</i>"], code: ["<code>", "</code>"] },
  };

  function wrapSelection(ta, kind, fmt) {
    const m = (kind === "html" ? MARKS.html : MARKS.md)[fmt];
    if (!m) return;
    const a = ta.selectionStart, b = ta.selectionEnd;
    const v = ta.value;
    const inner = v.slice(a, b) || "text";
    // toggle off if already wrapped
    if (v.slice(a - m[0].length, a) === m[0] && v.slice(b, b + m[1].length) === m[1]) {
      ta.value = v.slice(0, a - m[0].length) + inner + v.slice(b + m[1].length);
      ta.setSelectionRange(a - m[0].length, b - m[0].length);
    } else {
      ta.value = v.slice(0, a) + m[0] + inner + m[1] + v.slice(b);
      ta.setSelectionRange(a + m[0].length, a + m[0].length + inner.length);
    }
    ta.focus();
  }

  function format(fmt) {
    if (state.editor) { wrapSelection(state.editor.ta, state.editor.sel.kind, fmt); return; }
    if (!state.selection) return;
    emit("ce-command", { name: "format", fmt: fmt, selection: [state.selection] });
  }

  // ---------- on-canvas crop ----------
  function parseCrop(el) {
    const c = (el.getAttribute("data-crop") || "").split(" ").map(parseFloat);
    return c.length === 4 && c.every((v) => !isNaN(v)) ? c : [0, 0, 1, 1];
  }

  function cropEnter() {
    const sel = state.selection;
    if (!sel || sel.kind !== "place") return;
    const el = placeEl(sel.index);
    const img = el && el.querySelector("img");
    if (!el || !img) return;
    closeEditor(false);
    const crop = parseCrop(el);
    const b = elPercentBox(el);
    const full = { x: b.x - (crop[0] / crop[2]) * b.w, y: b.y - (crop[1] / crop[3]) * b.h, w: b.w / crop[2], h: b.h / crop[3] };
    const ghost = state.doc.createElement("img");
    ghost.className = "ce-crop-ghost";
    ghost.src = img.src;
    const frame = state.doc.createElement("div");
    frame.className = "ce-crop-frame";
    HANDLES.forEach((h) => {
      const hd = state.doc.createElement("div");
      hd.className = "ce-handle ce-handle-" + h;
      hd.dataset.handle = h;
      hd.addEventListener("mousedown", (e) => cropDown(e, h));
      frame.appendChild(hd);
    });
    frame.addEventListener("mousedown", (e) => cropDown(e, null));
    const hint = state.doc.createElement("div");
    hint.className = "ce-crop-hint";
    hint.textContent = "Crop: drag handles to cut, drag inside to move the image. Enter applies, Esc cancels.";
    state.slide.appendChild(ghost);
    state.slide.appendChild(frame);
    state.slide.appendChild(hint);
    state.crop = { sel, el, img, ghost, frame, hint, full, box: { ...b }, autoHeight: !el.style.height || el.getAttribute("data-auto-height") === "1", drag: null };
    hideBox();
    cropRender();
    state.doc.addEventListener("mousemove", cropMove, true);
    state.doc.addEventListener("mouseup", cropUp, true);
  }

  function cropRender() {
    const c = state.crop;
    const f = c.full, b = c.box;
    c.ghost.style.left = f.x + "%"; c.ghost.style.top = f.y + "%";
    c.ghost.style.width = f.w + "%"; c.ghost.style.height = f.h + "%";
    c.frame.style.left = b.x + "%"; c.frame.style.top = b.y + "%";
    c.frame.style.width = b.w + "%"; c.frame.style.height = b.h + "%";
    // live preview on the real element
    const crop = cropValues();
    c.el.style.left = b.x + "%"; c.el.style.top = b.y + "%";
    c.el.style.width = b.w + "%"; c.el.style.height = b.h + "%";
    c.img.style.position = "absolute";
    c.img.style.width = (100 / crop[2]) + "%"; c.img.style.height = (100 / crop[3]) + "%";
    c.img.style.left = (-crop[0] / crop[2] * 100) + "%"; c.img.style.top = (-crop[1] / crop[3] * 100) + "%";
  }

  function cropValues() {
    const f = state.crop.full, b = state.crop.box;
    const clamp = (v) => Math.max(0, Math.min(1, v));
    return [clamp((b.x - f.x) / f.w), clamp((b.y - f.y) / f.h), Math.max(0.01, Math.min(1, b.w / f.w)), Math.max(0.01, Math.min(1, b.h / f.h))];
  }

  function cropDown(e, handle) {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const c = state.crop;
    c.drag = { handle, start: toPercent(e.clientX, e.clientY), box: { ...c.box }, full: { ...c.full } };
  }

  function cropMove(e) {
    const c = state.crop;
    if (!c || !c.drag) return;
    e.preventDefault();
    const cur = toPercent(e.clientX, e.clientY);
    const dx = cur.x - c.drag.start.x, dy = cur.y - c.drag.start.y;
    const f = c.drag.full, b0 = c.drag.box;
    if (!c.drag.handle) {
      // pan: move the full image under a fixed window, keep window inside image
      let nx = f.x + dx, ny = f.y + dy;
      nx = Math.min(b0.x, Math.max(b0.x + b0.w - f.w, nx));
      ny = Math.min(b0.y, Math.max(b0.y + b0.h - f.h, ny));
      c.full = { x: nx, y: ny, w: f.w, h: f.h };
    } else {
      const h = c.drag.handle;
      let x = b0.x, y = b0.y, w = b0.w, hh = b0.h;
      if (h.includes("e")) w = b0.w + dx;
      if (h.includes("s")) hh = b0.h + dy;
      if (h.includes("w")) { w = b0.w - dx; x = b0.x + dx; }
      if (h.includes("n")) { hh = b0.h - dy; y = b0.y + dy; }
      // window must stay inside the full image
      if (x < f.x) { w -= f.x - x; x = f.x; }
      if (y < f.y) { hh -= f.y - y; y = f.y; }
      if (x + w > f.x + f.w) w = f.x + f.w - x;
      if (y + hh > f.y + f.h) hh = f.y + f.h - y;
      w = Math.max(1, w); hh = Math.max(1, hh);
      c.box = { x, y, w, h: hh };
    }
    cropRender();
  }

  function cropUp() {
    if (state.crop && state.crop.drag) state.crop.drag = null;
  }

  function cropExit() {
    const c = state.crop;
    if (!c) return;
    state.doc.removeEventListener("mousemove", cropMove, true);
    state.doc.removeEventListener("mouseup", cropUp, true);
    [c.ghost, c.frame, c.hint].forEach((n) => n.parentNode && n.parentNode.removeChild(n));
    state.crop = null;
  }

  function cropCommit() {
    const c = state.crop;
    if (!c) return;
    const crop = cropValues().map((v) => Math.round(v * 10000) / 10000);
    const b = c.box;
    const payload = { index: c.sel.index, x: round(b.x), y: round(b.y), w: round(b.w), crop: crop };
    if (!c.autoHeight) payload.h = round(b.h);
    if (crop[0] === 0 && crop[1] === 0 && crop[2] === 1 && crop[3] === 1) payload.crop = null;
    cropExit();
    emit("ce-crop", payload);
    applySelection();
  }

  function cropCancel() {
    const c = state.crop;
    if (!c) return;
    cropExit();
    emit("ce-command", { name: "refresh" });
  }

  function resetSize() {
    const sel = state.selection;
    if (!sel || sel.kind !== "place") return;
    const el = placeEl(sel.index);
    const img = el && el.querySelector("img");
    if (!el || !img || !img.naturalWidth) return;
    const crop = parseCrop(el);
    const b = elPercentBox(el);
    const w = (img.naturalWidth * crop[2]) / 1280 * 100;
    emit("ce-geometry", { items: [{ kind: "place", index: sel.index, x: round(b.x), y: round(b.y), w: round(w) }] });
  }

  // ---------- binding ----------
  function bind() {
    const iframe = state.iframe;
    let doc;
    try { doc = iframe.contentDocument; } catch (err) { return; }
    if (!doc || !doc.body) return;
    state.doc = doc;
    state.box = null;
    state.extraBoxes = [];
    state.guides = null;
    state.editor = null;
    const style = doc.createElement("style");
    style.textContent = STYLE;
    doc.head.appendChild(style);
    const refreshSlide = () => {
      state.editor = null;
      state.crop = null;
      state.slide = doc.querySelector(".slide.active");
      if (state.slide) markHtmlAbs();
      applySelection();
    };
    refreshSlide();
    doc.addEventListener("click", onClick, true);
    doc.addEventListener("dblclick", onDblClick, true);
    doc.addEventListener("mousedown", onMouseDown, true);
    doc.addEventListener("mousemove", onMouseMove, true);
    doc.addEventListener("mouseup", onMouseUp, true);
    doc.addEventListener("mouseover", onMouseOver, true);
    doc.addEventListener("keydown", onKeyDown, true);
    iframe.contentWindow.addEventListener("hashchange", refreshSlide);
    iframe.contentWindow.addEventListener("resize", applySelection);
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
    select(sel, extra) {
      state.selection = sel && sel.kind !== "slide" ? sel : null;
      state.extra = (extra || []).filter((s) => isMovable(s));
      applySelection();
    },
    refresh() { applySelection(); },
    edit(sel) { requestEdit(sel); },
    openEditor(sel, value) { openEditor(sel, value); },
    align(mode) { align(mode); },
    distribute(axis) { distribute(axis); },
    htmlAbsCount() { return state.slide ? htmlAbsEls().length : 0; },
    format(fmt) { format(fmt); },
    cropEnter() { cropEnter(); },
    cropCommit() { cropCommit(); },
    cropCancel() { cropCancel(); },
    resetSize() { resetSize(); },
  };
})();
