# Paint Simplifier – Implementation Plan

**Status:** Planning only. No implementation changes yet.  
**Last updated:** 2025-02-12

---

## 1. Architecture decision (final)

Build as a **local-first web app**, structured so it can be deployed publicly later without a rewrite.

| Goal | How |
|------|-----|
| Runs on your computer now | Local server (e.g. Python HTTP server) |
| Share with family | Same machine or simple port/share |
| Deploy online later | One command → Railway or similar |
| Windows `.exe` later | Optional wrapper (e.g. PyInstaller + embedded server) |

---

## 2. Folder structure (for future deployment)

```
paint-simplifier/
│
├── backend/
│   ├── main.py          # HTTP server, routes, upload handling
│   ├── processor.py     # Pipeline: load → value groups → merge → smooth → color → render
│   ├── color_modes.py   # B/W, Grayscale, Color (and edge: Soft/Hard)
│   └── utils.py         # Resize, I/O, safe paths
│
├── frontend/
│   ├── index.html
│   ├── app.js           # UI, preview fetch, export
│   └── style.css
│
├── uploads/             # Temp uploads (gitignore)
├── outputs/             # Exports (gitignore or optional)
└── run_local.bat        # Start server + open http://localhost:8000
```

Clean separation keeps backend/frontend deployable as-is (e.g. static frontend + API).

---

## 3. Processing engine design (painter abstraction, not a filter)

Pipeline (all deterministic and controllable):

| Step | Purpose |
|------|--------|
| 1. Load image | Decode, validate, get dimensions |
| 2. Resize for preview | Fast UI feedback |
| 3. Convert to value groups | 2–10 levels, controllable |
| 4. Merge small regions | Reduce noise; amount tied to “Abstraction” |
| 5. Smooth shapes | Optional smoothing for paint-friendly edges |
| 6. Apply color mode | B/W, Grayscale, or Color + edge (Soft/Hard) |
| 7. Render preview | Return image for UI |
| 8. Export full resolution | Run same pipeline at full res, output PNG |

No ML; full control over value count, abstraction strength, and color/edge.

---

## 4. UI layout (simple and fast)

- **Left:** Controls  
- **Right:** Live preview (updates on change)

Controls:

- **[ Upload Image ]**
- **VALUES:** 2 — 10 (slider or input)
- **ABSTRACTION:** Low — High (slider)
- **MODE:** B/W | Grayscale | Color (radio)
- **EDGE:** Soft | Hard (radio)
- **[ Export PNG ]**

Preview updates instantly (debounced if needed for perf).

---

## 5. Local run experience

1. User double-clicks **run_local.bat**.
2. Backend starts (e.g. port 8000).
3. Browser opens `http://localhost:8000`.
4. User: upload photo → adjust sliders/mode → export PNG.

No extra install steps after initial setup (Python + deps).

---

## 6. Performance targets

| Metric | Target |
|--------|--------|
| Preview render | &lt; 1 s |
| Full export | 2–4 s |
| Large images | Handled safely (resize/limits if needed) |

---

## 7. Future deploy path (no rewrite)

- Deploy backend + static frontend to Railway (or any host).
- Same codebase; env/config for port and base URL.
- Later optional: Windows exe wrapper, public instance, presets.

---

## 8. Open design decisions (to confirm before build)

### 8.1 Abstraction behavior

When **Abstraction** is increased, should the engine:

- **A. Merge shapes aggressively**  
  Remove small details quickly; fewer, larger shapes as you go high.

- **B. Merge slowly**  
  Keep structure longer; more gradual simplification.

*Your sample suggested A; please confirm.*

### 8.2 Value grouping

How should value levels (2–10) be distributed?

- **A. Evenly (mathematical)**  
  Equal steps in luminance (e.g. 0–25%, 25–50%, …).

- **B. Smart grouping (painting-oriented)**  
  Group by perceptually meaningful bands (e.g. shadows, midtones, highlights) for better painting reference.

*Smart grouping (B) is usually better for painting; confirm preference.*

---

## 9. Next steps (after decisions)

1. Confirm choices for §8.1 and §8.2.
2. Create repo structure (§2), then implement backend pipeline (§3) and minimal API.
3. Implement frontend (§4) and wire to backend.
4. Add **run_local.bat** and verify local flow (§5).
5. Tune for performance targets (§6).

No implementation work until these are agreed.
