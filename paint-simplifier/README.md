# Block-In Studio

A local-first web app that turns photos into paintable block-in studies with limited values, big readable shapes, and aggressive detail removal.

Built for painters who want a starting reference — not a finished painting.

## Features

- **Master Painter Presets:** Sargent (bold block-in), Impressionist (broken color), Graphic Poster (flat shapes)
- **Value grouping (2–10):** Smart k-means clustering on luminance, not even math steps
- **Shape Build Level:** From bold block-in to full structure detail
- **Modes:** Grayscale for value planning, Color for color masses
- **Edges:** Soft (painterly) to Graphic (hard) edge control
- **PNG export** at full resolution

## Quick start

1. Double-click **run_local.bat**
2. Browser opens to `http://127.0.0.1:589`
3. Upload a photo, pick a preset, adjust sliders, export PNG

### Requirements

- Windows 10/11
- Python 3.11+ (with the `py` launcher — comes with standard Python install)

The batch file creates a virtual environment and installs dependencies automatically on first run.

### Manual start

```
cd paint-simplifier
py -m venv venv
venv\Scripts\activate
pip install -r backend\requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 589
```

Then open http://127.0.0.1:589 in your browser.

## Project structure

```
paint-simplifier/
├── backend/
│   ├── main.py           # FastAPI server + API routes
│   ├── processor.py      # Image processing pipeline
│   ├── presets.py         # Master painter preset definitions
│   ├── color_modes.py    # Grayscale & Color renderers
│   ├── guide.py          # Guide overlay system
│   ├── utils.py          # IO, resize, caching
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── uploads/              # Temp uploads (gitignored)
├── outputs/              # Exports (gitignored)
└── run_local.bat
```

## Design principles

- **Economy:** Drop unnecessary micro-detail; keep only what describes form
- **Notan / limited values:** Fewer values = clearer foundational shapes
- **Grayscale first:** Assess shape and composition before introducing color
- **Structured color:** When used, color is simplified and snapped to value groups

## Deployment

Same codebase deploys to any host (Railway, Render, etc.). Set `PORT` env var and serve.
