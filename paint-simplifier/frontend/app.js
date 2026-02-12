(function () {
  "use strict";

  var imageId = null;
  var debounceTimer = null;
  var DEBOUNCE_MS = 200;

  var LEVEL_NAMES = {1: "Notan", 2: "Primary", 3: "Secondary", 4: "Structure", 5: "Full"};

  // DOM refs
  var uploadBtn = document.getElementById("upload-btn");
  var uploadText = document.getElementById("upload-text");
  var uploadInfo = document.getElementById("upload-info");
  var valuesSlider = document.getElementById("values-slider");
  var valuesDisplay = document.getElementById("values-display");
  var levelSlider = document.getElementById("level-slider");
  var levelDisplay = document.getElementById("level-display");
  var edgeSlider = document.getElementById("edge-slider");
  var edgeDisplay = document.getElementById("edge-display");
  var exportBtn = document.getElementById("export-btn");
  var guideSection = document.getElementById("guide-section");
  var overlayEdges = document.getElementById("overlay-edges");
  var overlayShapes = document.getElementById("overlay-shapes");
  var overlayFocal = document.getElementById("overlay-focal");
  var colorStrategySection = document.getElementById("color-strategy-section");
  var exaggerateCheckbox = document.getElementById("exaggerate-color");
  var placeholder = document.getElementById("placeholder");
  var previewWrapper = document.getElementById("preview-wrapper");
  var resultPreview = document.getElementById("result-preview");
  var resultLabel = document.getElementById("result-label");
  var spinner = document.getElementById("loading-spinner");

  function getAppMode() {
    return document.querySelector('input[name="app-mode"]:checked').value;
  }

  function getColorMode() {
    return document.querySelector('input[name="color-mode"]:checked').value;
  }

  function getColorStrategy() {
    return document.querySelector('input[name="color-strategy"]:checked').value;
  }

  function isGuideMode() {
    return getAppMode() === "guide";
  }

  function isColorMode() {
    return getColorMode() === "color";
  }

  function updateColorStrategyVisibility() {
    colorStrategySection.style.display = isColorMode() ? "flex" : "none";
  }

  function getParams() {
    return {
      image_id: imageId,
      values: parseInt(valuesSlider.value, 10),
      build_level: parseInt(levelSlider.value, 10),
      mode: getColorMode(),
      edge_strength: parseInt(edgeSlider.value, 10),
      color_strategy: isColorMode() ? getColorStrategy() : "painter",
      exaggerate: isColorMode() && exaggerateCheckbox.checked,
      guide_mode: isGuideMode(),
      overlays: {
        edges: isGuideMode() && overlayEdges.checked,
        shapes: isGuideMode() && overlayShapes.checked,
        focal: isGuideMode() && overlayFocal.checked,
      },
    };
  }

  // --- Upload ---

  uploadBtn.addEventListener("change", function () {
    var file = this.files[0];
    if (!file) return;

    var form = new FormData();
    form.append("file", file);

    uploadText.textContent = "Uploading...";
    fetch("/api/upload", { method: "POST", body: form })
      .then(function (res) {
        if (!res.ok) return res.json().then(function (err) { throw new Error(err.detail || "Upload failed"); });
        return res.json();
      })
      .then(function (data) {
        imageId = data.image_id;
        uploadText.textContent = "Change Image";
        uploadInfo.textContent = file.name + " (" + data.width + "\u00d7" + data.height + ")";
        exportBtn.disabled = false;
        placeholder.style.display = "none";
        previewWrapper.style.display = "flex";
        requestPreview();
      })
      .catch(function (e) {
        uploadText.textContent = "Upload Image";
        uploadInfo.textContent = "Error: " + e.message;
      });
  });

  // --- Preview ---

  function requestPreview() {
    if (!imageId) return;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(doPreview, DEBOUNCE_MS);
  }

  function doPreview() {
    if (!imageId) return;
    spinner.style.display = "flex";

    var params = getParams();
    var level = params.build_level;
    var modeName = params.mode === "bw" ? "B/W" : params.mode.charAt(0).toUpperCase() + params.mode.slice(1);
    var strategyStr = params.mode === "color" ? " (" + getColorStrategy() + ")" : "";
    var modeStr = (isGuideMode() ? "Guide" : "Simplify") + " / " + modeName + strategyStr + " / L" + level + " " + LEVEL_NAMES[level];

    fetch("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("Preview failed");
        return res.blob();
      })
      .then(function (blob) {
        resultPreview.style.opacity = "0";
        setTimeout(function () {
          resultPreview.src = URL.createObjectURL(blob);
          resultPreview.style.opacity = "1";
        }, 80);
        resultLabel.textContent = modeStr;
      })
      .catch(function (e) {
        console.error("Preview error:", e);
      })
      .finally(function () {
        spinner.style.display = "none";
      });
  }

  // --- Controls ---

  valuesSlider.addEventListener("input", function () {
    valuesDisplay.textContent = this.value;
    requestPreview();
  });

  levelSlider.addEventListener("input", function () {
    levelDisplay.textContent = this.value;
    requestPreview();
  });

  edgeSlider.addEventListener("input", function () {
    edgeDisplay.textContent = this.value;
    requestPreview();
  });

  // Color mode toggle: show/hide color strategy section
  document.querySelectorAll('input[name="color-mode"]').forEach(function (r) {
    r.addEventListener("change", function () {
      updateColorStrategyVisibility();
      requestPreview();
    });
  });

  // Color strategy + exaggeration
  document.querySelectorAll('input[name="color-strategy"]').forEach(function (r) {
    r.addEventListener("change", requestPreview);
  });
  exaggerateCheckbox.addEventListener("change", requestPreview);

  // App mode toggle: show/hide guide overlays
  document.querySelectorAll('input[name="app-mode"]').forEach(function (r) {
    r.addEventListener("change", function () {
      guideSection.style.display = isGuideMode() ? "flex" : "none";
      requestPreview();
    });
  });

  overlayEdges.addEventListener("change", requestPreview);
  overlayShapes.addEventListener("change", requestPreview);
  overlayFocal.addEventListener("change", requestPreview);

  // --- Export ---

  exportBtn.addEventListener("click", function () {
    if (!imageId) return;
    exportBtn.textContent = "Exporting...";
    exportBtn.disabled = true;

    fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(getParams()),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("Export failed");
        return res.blob();
      })
      .then(function (blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "paint_simplifier_export.png";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      })
      .catch(function (e) {
        alert("Export failed: " + e.message);
      })
      .finally(function () {
        exportBtn.textContent = "Export PNG";
        exportBtn.disabled = false;
      });
  });
})();
