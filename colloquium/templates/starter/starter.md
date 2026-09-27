---
title: "Starter deck"
author: "Your name"
footer:
  right: "{n}/{N}"
custom_css: |
  :root {
    --colloquium-accent: #0f3460;
  }
---

<!-- master: true -->

```place
src: assets/logo.png
x: 91.5
y: 4
w: 5.5
```

```place
x: 3
y: 92.5
w: 40
size: 0.7
style: "color: #6b7280"
text: |
  Your name · Event · 2026
```

<!-- notes: Theme slide. It is never shown in the presentation. Everything placed here (the logo, the footer text) repeats on every slide behind the content; drag it here and it moves everywhere. Give an element a z-index to put it in front. The inspector on this slide is the Theme panel: colours, fonts, background image, raw custom CSS. A slide opts out of theme elements with master: off (the title slide does). -->

---

<!-- layout: title -->
<!-- master: off -->

# Starter deck

Markdown slides you can edit by hand, with an agent, or by dragging things around in `colloquium edit`.

<!-- notes: A title slide. Double-click the title or the subtitle to edit them in place. This slide has master: off, so the theme-slide elements are not stamped on it. Speaker notes like this one are hidden in the presentation and edited from the inspector. -->

---

## Content flows, objects float

<!-- columns: 55/45 -->

Everything on this slide is plain markdown in `starter.md`.

- Click a paragraph or list to select it, double-click to edit its text
- Drag it and it lifts out of the flow into a placed object
- Drag the blue divider between the columns to change the split
- Select a cell (click empty space) and use the toolbar to align or colour it

|||

<!-- cell-style: text-align: center -->

![City skyline at dusk](assets/skyline.png)

*Inline image: the handles resize it in place, dragging it out places it freely.*

<!-- notes: Columns come from the columns directive; the cell-style comment centres the right cell. Blocks are ordinary markdown until you drag them: then they become a place block at the drop position, and the markdown diff is only that block. -->

---

## Free placement

Placed elements are `place` blocks with `x`, `y`, `w` in percent of the slide. They can be images (with a non-destructive crop), text boxes, or shapes, and they can be grouped.

```place
src: assets/skyline.png
x: 6
y: 34
w: 38
crop: [0.18, 0.08, 0.64, 0.7]
```

```place
x: 52
y: 36
w: 30
h: 13
shape: rounded
fill: "#0f3460"
stroke: "#0f3460"
group: g1
style: "color: #ffffff"
text: |
  **A group of three**
```

```place
x: 47.5
y: 52
w: 4.5
h: 11
shape: arrow
flip: true
stroke: "#0f3460"
stroke_width: 3
group: g1
```

```place
x: 52
y: 58
w: 36
size: 0.85
group: g1
text: |
  Shape, arrow and this text move and resize together. Click selects the group, Alt+click one member, Ctrl+Shift+G ungroups. The photo on the left is cropped: select it and press Crop to change the window; the original file is untouched.
```

<!-- notes: Try: drag the photo, resize it from a corner (aspect kept), press Crop; select the group and scale it from a corner; Ctrl+D duplicates, Ctrl+Up/Down changes stacking order, arrow keys nudge. Add image / Add text / Add shape in the header create new placed elements. -->
