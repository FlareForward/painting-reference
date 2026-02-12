(function () {
  "use strict";

  var imageId = null;
  var debounceTimer = null;
  var DEBOUNCE_MS = 200;

  var LEVEL_NAMES = {1: "Block", 2: "Secondary", 3: "Structure", 4: "Full"};

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
  var preserveSubject = document.getElementById("preserve-subject");
  var placeholder = document.getElementById("placeholder");
  var previewWrapper = document.getElementById("preview-wrapper");
  var resultPreview = document.getElementById("result-preview");
  var originalPreview = document.getElementById("original-preview");
  var viewResultBtn = document.getElementById("view-result-btn");
  var viewOriginalBtn = document.getElementById("view-original-btn");
  var resultLabel = document.getElementById("result-label");
  var spinner = document.getElementById("loading-spinner");
  var originalUrl = null;

  // AI Assist refs (local-only)
  var aiSection = document.getElementById("ai-section");
  var aiBtn = document.getElementById("ai-btn");
  var aiResults = document.getElementById("ai-results");
  var isLocalhost = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";

  function getAppMode() {
    return document.querySelector('input[name="app-mode"]:checked').value;
  }

  function getColorMode() {
    return document.querySelector('input[name="color-mode"]:checked').value;
  }

  function getStyleMode() {
    return document.querySelector('input[name="style-mode"]:checked').value;
  }

  function isGuideMode() {
    return getAppMode() === "guide";
  }

  function getParams() {
    return {
      image_id: imageId,
      values: parseInt(valuesSlider.value, 10),
      build_level: parseInt(levelSlider.value, 10),
      mode: getColorMode(),
      edge_strength: parseInt(edgeSlider.value, 10),
      style_mode: getStyleMode(),
      preserve_subject: preserveSubject.checked,
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

    // Store original for the Result/Original toggle
    if (originalUrl) URL.revokeObjectURL(originalUrl);
    originalUrl = URL.createObjectURL(file);

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
        if (isLocalhost && aiBtn) aiBtn.disabled = false;
        placeholder.style.display = "none";
        previewWrapper.style.display = "flex";
        originalPreview.src = originalUrl;
        showResult();
        requestPreview();
      })
      .catch(function (e) {
        uploadText.textContent = "Upload Image";
        uploadInfo.textContent = "Error: " + e.message;
      });
  });

  // --- Result / Original toggle ---

  function showResult() {
    resultPreview.style.display = "";
    originalPreview.style.display = "none";
    viewResultBtn.classList.add("active");
    viewOriginalBtn.classList.remove("active");
    resultLabel.style.display = "";
  }

  function showOriginal() {
    resultPreview.style.display = "none";
    originalPreview.style.display = "";
    viewOriginalBtn.classList.add("active");
    viewResultBtn.classList.remove("active");
    resultLabel.style.display = "none";
  }

  viewResultBtn.addEventListener("click", showResult);
  viewOriginalBtn.addEventListener("click", showOriginal);

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
    var modeName = params.mode.charAt(0).toUpperCase() + params.mode.slice(1);
    var styleName = getStyleMode().charAt(0).toUpperCase() + getStyleMode().slice(1);
    var modeStr = styleName + " / " + (isGuideMode() ? "Guide" : "Simplify") + " / " + modeName + " / L" + level + " " + LEVEL_NAMES[level];

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

  // Color mode toggle
  document.querySelectorAll('input[name="color-mode"]').forEach(function (r) {
    r.addEventListener("change", requestPreview);
  });

  // Style mode toggle
  document.querySelectorAll('input[name="style-mode"]').forEach(function (r) {
    r.addEventListener("change", requestPreview);
  });

  // App mode toggle: show/hide guide overlays
  document.querySelectorAll('input[name="app-mode"]').forEach(function (r) {
    r.addEventListener("change", function () {
      guideSection.style.display = isGuideMode() ? "flex" : "none";
      requestPreview();
    });
  });

  preserveSubject.addEventListener("change", requestPreview);

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

  // --- AI Assist (local-only) ---

  if (isLocalhost && aiSection) {
    aiSection.style.display = "flex";
  } else if (aiSection) {
    console.log("AI disabled: not running on localhost");
  }

  if (aiBtn) {
    aiBtn.addEventListener("click", function () {
      if (!imageId) return;
      aiBtn.disabled = true;
      aiBtn.textContent = "Analyzing...";
      aiBtn.classList.add("ai-loading");
      aiResults.style.display = "none";

      var params = getParams();
      var body = {
        image_id: imageId,
        values: params.values,
        build_level: params.build_level,
        mode: params.mode,
        edge_strength: params.edge_strength,
        style_mode: params.style_mode,
      };

      fetch("/api/ai-analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
        .then(function (res) {
          if (!res.ok) return res.json().then(function (err) { throw new Error(err.detail || "AI analysis failed"); });
          return res.json();
        })
        .then(function (data) {
          if (data.error) {
            throw new Error(data.error);
          }
          document.getElementById("ai-focal").textContent = data.focal || "—";
          document.getElementById("ai-values").textContent = data.values || "—";
          document.getElementById("ai-edges").textContent = data.edges || "—";
          document.getElementById("ai-simplification").textContent = data.simplification || "—";
          document.getElementById("ai-color").textContent = data.color || "—";
          aiResults.style.display = "block";
        })
        .catch(function (e) {
          document.getElementById("ai-focal").textContent = e.message;
          document.getElementById("ai-values").textContent = "";
          document.getElementById("ai-edges").textContent = "";
          document.getElementById("ai-simplification").textContent = "";
          document.getElementById("ai-color").textContent = "";
          aiResults.style.display = "block";
        })
        .finally(function () {
          aiBtn.disabled = false;
          aiBtn.textContent = "AI Assist";
          aiBtn.classList.remove("ai-loading");
        });
    });
  }
})();
