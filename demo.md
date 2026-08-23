---
title: "Feature Tour Demo"
author: "Imanol Schlag"
date: "2026-08-02"
aspect_ratio: "16:9"
bibliography: demo-refs.bib
citation_style: author-year
footer:
  left: "Feature Tour Demo"
  center: "[Imanol Schlag](https://ischlag.github.io)"
  right: "{n}/{N}"
---

# Feature Tour Demo

Every feature on one pass, course-flavoured

Imanol Schlag - ETH Zurich AI Center

---

## Outline

```outline
```

<div class="colloquium-footnote">
Auto-generated from section-break slides; entries are clickable #n deep links.
</div>

---

## Navigating these slides

| Action | Input |
|--------|-------|
| Next / previous | Arrow keys, Space, PgUp/PgDn, swipe |
| Click zones | Left third back, right two-thirds forward |
| First / last | Home / End |
| Fullscreen | F |
| Jump to slide | Type the number, or `#n` in the URL |
| PDF | Ctrl+P in the browser, or `colloquium export` |

---

<!-- layout: section-break -->

## Layouts and text

---

## Bullets with incremental reveal

<!-- animate: bullets -->
<!-- notes: This slide demos animate:bullets and speaker notes. Press arrow keys to reveal. -->

- Slides are plain markdown, separated by `---`
- Per-slide config via HTML comments: layout, columns, align, notes
- This list reveals bullet by bullet (animate directive)
- Speaker notes exist on this slide but stay hidden in presentation

---

## Step markers and text sizes

This content is visible immediately.

<!-- step -->

<span class="text-2xl">Steps reveal arbitrary blocks on click.</span>

<!-- step -->

<div class="text-sm">

- Dense small text for fine details (`text-sm`)
- Eight sizes from `text-xs` to `text-4xl`

</div>

---

<!-- columns: 60/40 -->

## Two columns, 60/40

### Left: the argument

Pretraining gives you a glorified autocomplete.
Post-training makes it useful: instructions,
preferences, reasoning, tools.

|||

### Right: the numbers

| Stage | Tokens |
|-------|--------|
| Pretrain | 15T |
| SFT | 1B |
| RL | 100M |

---

<!-- layout: section-break -->

## Math, code, charts

---

## LaTeX math via KaTeX

Inline: gradients $\nabla_\theta \mathcal{L}$, expectations $\mathbb{E}_{x \sim p}[\log p_\theta(x)]$, spectral norm $\sigma_{\max}(W)$.

Display:

$$\mathcal{L}(\theta) = -\frac{1}{N} \sum_{i=1}^{N} \log p_\theta(y_i \mid x_i)$$

The RLHF objective [@christiano2017; @ouyang2022]:

$$\max_\theta \; \mathbb{E}_{y \sim \pi_\theta}[r(y)] - \beta \, \mathrm{KL}(\pi_\theta \| \pi_{\mathrm{ref}})$$

---

<!-- layout: code -->

## Code with syntax highlighting

```python
import torch.distributed as dist

dist.init_process_group("nccl")
model = torch.nn.parallel.DistributedDataParallel(
    model, device_ids=[local_rank]
)
for batch in loader:
    loss = model(batch).loss
    loss.backward()
    optimizer.step()
```

---

## Live charts (Chart.js)

```chart
type: line
height: 420
data:
  labels: [0, 10, 20, 30, 40, 50, 60]
  datasets:
    - label: AdamW
      data: [4.1, 3.2, 2.9, 2.75, 2.66, 2.61, 2.58]
      color: "#d29922"
    - label: Muon
      data: [4.1, 3.05, 2.78, 2.62, 2.54, 2.49, 2.46]
      color: "#2f81f7"
options:
  scales:
    y:
      ticks:
        suffix: " nats"
```

---

<!-- layout: section-break -->

## LLM-specific blocks

---

## Conversation bubbles

```conversation
size: 0.9
messages:
  - role: system
    content: "You are a helpful assistant developed by the Swiss AI Initiative."
  - role: user
    content: "What is a chat template?"
  - role: assistant
    model: "Apertus 1.5 70B"
    content: "A chat template is two functions: **render** (messages to tokens) and **parse** (tokens back to structure). Roles and tools are conventions over special tokens."
```

---

## Free placement

Normal content flows as usual. ```` ```place ```` blocks pin images and text
anywhere in slide percent coordinates and can crop images non-destructively.

```place
x: 52
y: 18
w: 44
src: examples/rows-and-columns/rlhf_timeline_tikz.png
crop: [0.05, 0.1, 0.6, 0.8]
```

```place
x: 52
y: 78
w: 44
size: 0.7
align: center
text: |
  Cropped to the left 60% of the original, placed at x=52%, w=44%.
```

```place
x: 4
y: 62
w: 40
size: 0.85
text: |
  **Placed text** with $e^{i\pi}+1=0$ and a list:
  - no column needed
  - edited visually with `colloquium edit`
```

---

<!-- columns: 2 -->

## Callout boxes

```box
title: Core idea
tone: accent
content: |
  One flat token stream.
  Messages are an API fiction.
```

|||

```box
title: Caveats
tone: surface
compact: true
content: |
  - Serving must match training
  - One owner per special token
```

---

## Footnotes and citations

Scratch files are deleted after 30 days without access.^[Touch files periodically: `find . -exec touch {} \;`]

Preference tuning follows [@ouyang2022]; the Swiss stack is documented in [@apertus2025].

<!-- footnote: Citations collect into an auto-generated references slide at the end. -->

---

# Thanks

These slides are built with colloquium, [Nathan Lambert](https://natolambert.com)'s markdown-native slide tool

[github.com/natolambert/colloquium](https://github.com/natolambert/colloquium)

---

<!-- after: references -->

## Backup: appendix slide

This slide sits after the auto-generated references and is excluded from the `{N}` slide count in the footer.
