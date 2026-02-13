(function () {
  "use strict";

  var imageId = null;
  var debounceTimer = null;
  var DEBOUNCE_MS = 200;

  var LEVEL_NAMES = {1: "Block", 2: "Secondary", 3: "Structure", 4: "Full"};

  // Preset state
  var presets = [];         // loaded from /api/presets
  var currentPreset = null; // { key, name, description, defaults }

  // DOM refs
  var uploadBtn = document.getElementById("upload-btn");
  var uploadText = document.getElementById("upload-text");
  var uploadInfo = document.getElementById("upload-info");
  var presetSelector = document.getElementById("preset-selector");
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

  // Track whether user has manually changed sliders (overrides)
  var userOverrides = {};

  function getAppMode() {
    return document.querySelector('input[name="app-mode"]:checked').value;
  }

  function getColorMode() {
    return document.querySelector('input[name="color-mode"]:checked').value;
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
      preset: currentPreset ? currentPreset.key : "sargent",
      preserve_subject: preserveSubject.checked,
      guide_mode: isGuideMode(),
      overlays: {
        edges: isGuideMode() && overlayEdges.checked,
        shapes: isGuideMode() && overlayShapes.checked,
        focal: isGuideMode() && overlayFocal.checked,
      },
    };
  }

  // --- Preset system ---

  function loadPresets() {
    fetch("/api/presets")
      .then(function (res) { return res.json(); })
      .then(function (data) {
        presets = data;
        buildPresetUI();
        // Select first preset by default
        if (presets.length > 0) {
          selectPreset(presets[0].key, true);
        }
      })
      .catch(function (e) {
        console.error("Failed to load presets:", e);
        // Fallback: build a minimal sargent preset
        presets = [{
          key: "sargent", name: "Sargent",
          description: "Confident oil-paint block-in",
          defaults: { values: 4, build_level: 2, edge_strength: 40, color_mode: "grayscale" }
        }];
        buildPresetUI();
        selectPreset("sargent", true);
      });
  }

  function buildPresetUI() {
    presetSelector.innerHTML = "";
    presets.forEach(function (p) {
      var label = document.createElement("label");
      label.className = "preset-option";
      label.innerHTML =
        '<input type="radio" name="preset" value="' + p.key + '">' +
        '<span class="preset-option-content">' +
          '<span class="preset-name">' + p.name + '</span>' +
          '<span class="preset-desc">' + p.description + '</span>' +
        '</span>';
      presetSelector.appendChild(label);

      label.querySelector("input").addEventListener("change", function () {
        selectPreset(p.key, false);
      });
    });
  }

  function selectPreset(key, isInit) {
    currentPreset = null;
    for (var i = 0; i < presets.length; i++) {
      if (presets[i].key === key) {
        currentPreset = presets[i];
        break;
      }
    }
    if (!currentPreset) return;

    // Check the radio button
    var radio = presetSelector.querySelector('input[value="' + key + '"]');
    if (radio) radio.checked = true;

    // Apply preset defaults to sliders (reset overrides on preset change)
    // Preserve color mode — user's color/grayscale choice persists across presets
    if (!isInit) {
      var keepColorMode = userOverrides.color_mode;
      userOverrides = {};
      if (keepColorMode) userOverrides.color_mode = true;
    }
    applyPresetDefaults(currentPreset.defaults);

    if (imageId) {
      requestPreview();
    }
  }

  function applyPresetDefaults(defaults) {
    // Values slider
    if (!userOverrides.values) {
      valuesSlider.value = defaults.values;
      valuesDisplay.textContent = defaults.values;
    }

    // Build level slider
    if (!userOverrides.build_level) {
      levelSlider.value = defaults.build_level;
      levelDisplay.textContent = defaults.build_level;
    }

    // Edge strength slider
    if (!userOverrides.edge_strength) {
      edgeSlider.value = defaults.edge_strength;
      edgeDisplay.textContent = defaults.edge_strength;
    }

    // Color mode radio
    if (!userOverrides.color_mode) {
      var colorRadio = document.querySelector('input[name="color-mode"][value="' + defaults.color_mode + '"]');
      if (colorRadio) colorRadio.checked = true;
    }
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
    var presetName = currentPreset ? currentPreset.name : "Sargent";
    var modeStr = presetName + " / " + (isGuideMode() ? "Guide" : "Simplify") + " / " + modeName + " / L" + level + " " + LEVEL_NAMES[level];

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

  // --- Controls (sliders mark user overrides) ---

  valuesSlider.addEventListener("input", function () {
    valuesDisplay.textContent = this.value;
    userOverrides.values = true;
    requestPreview();
  });

  levelSlider.addEventListener("input", function () {
    levelDisplay.textContent = this.value;
    userOverrides.build_level = true;
    requestPreview();
  });

  edgeSlider.addEventListener("input", function () {
    edgeDisplay.textContent = this.value;
    userOverrides.edge_strength = true;
    requestPreview();
  });

  // Color mode toggle
  document.querySelectorAll('input[name="color-mode"]').forEach(function (r) {
    r.addEventListener("change", function () {
      userOverrides.color_mode = true;
      requestPreview();
    });
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
        a.download = "block_in_studio_export.png";
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

  // --- Init ---
  loadPresets();

})();
