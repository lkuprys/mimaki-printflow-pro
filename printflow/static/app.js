let appConfig = { inbox_folder: "", products: [] };
let selectedProductId = null;
let activeFilePath = null;
let activePreviews = null;
let activeLayer = "composite";
let activeChokeWhite = 1;

document.addEventListener("DOMContentLoaded", () => {
  initApp();
});

async function initApp() {
  await loadAppConfig();
  initInbox();
  initDropzone();
  initLayerTabs();
  initControls();
  initModals();
  initWebSocket();
}

// ==========================================
// 1. CONFIG & PRODUCTS
// ==========================================
async function loadAppConfig() {
  try {
    const res = await fetch("/api/config");
    appConfig = await res.json();
    renderProductsGrid();
    document.getElementById("inbox-folder-label").textContent = appConfig.inbox_folder || "Nenustatytas";
  } catch (err) {
    console.error("Failed to load config:", err);
  }
}

function renderProductsGrid() {
  const container = document.getElementById("products-grid");
  container.innerHTML = "";

  (appConfig.products || []).forEach((p, idx) => {
    if (idx === 0 && !selectedProductId) {
      selectedProductId = p.id;
    }

    const card = document.createElement("div");
    card.className = `preset-card p-3.5 rounded-xl border border-slate-800 bg-slate-800/40 cursor-pointer flex flex-col justify-between ${
      p.id === selectedProductId ? "active" : ""
    }`;
    card.onclick = () => selectProduct(p.id);

    const layerPills = (p.layers || [])
      .map((l) => `<span class="text-[9px] uppercase font-bold px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 border border-slate-600/50">${l}</span>`)
      .join(" ");

    card.innerHTML = `
      <div class="flex items-start gap-2.5 mb-2">
        <div class="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-400 flex items-center justify-center text-sm flex-shrink-0">
          <i class="fa-solid fa-box"></i>
        </div>
        <div>
          <h4 class="text-xs font-bold text-white tracking-tight">${p.name}</h4>
          <p class="text-[10px] text-slate-400 font-mono mt-0.5">Raktas: ${p.keyword || "-"}</p>
        </div>
      </div>
      <div class="flex items-center justify-between mt-1 pt-2 border-t border-slate-700/40">
        <span class="text-[10px] text-slate-400">Choke: ${p.choke_white_px || 1}px</span>
        <div class="flex items-center gap-1">${layerPills}</div>
      </div>
    `;
    container.appendChild(card);
  });

  updateSelectedProductText();
}

function selectProduct(id) {
  selectedProductId = id;
  const p = (appConfig.products || []).find((x) => x.id === id);
  if (p && p.choke_white_px !== undefined) {
    activeChokeWhite = p.choke_white_px;
    updateChokeButtonsUI(activeChokeWhite);
  }
  document.querySelectorAll(".preset-card").forEach((c, idx) => {
    c.classList.toggle("active", (appConfig.products || [])[idx]?.id === id);
  });
  updateSelectedProductText();
}

function updateSelectedProductText() {
  const p = (appConfig.products || []).find((x) => x.id === selectedProductId);
  const textEl = document.getElementById("selected-product-text");
  if (p && textEl) {
    textEl.textContent = `Režimas: ${p.name}`;
  }
}

// ==========================================
// 2. INBOX LIST
// ==========================================
async function initInbox() {
  document.getElementById("btn-refresh-inbox").onclick = loadInboxFiles;
  await loadInboxFiles();
}

async function loadInboxFiles() {
  const container = document.getElementById("inbox-list");
  try {
    const res = await fetch("/api/inbox");
    const data = await res.json();
    const files = data.files || [];

    if (files.length === 0) {
      container.innerHTML = `<div class="p-3 text-center text-xs text-slate-500">Inbox aplankas tuščias (${data.inbox_folder})</div>`;
      return;
    }

    container.innerHTML = "";
    files.forEach((f) => {
      const item = document.createElement("div");
      item.className = "flex items-center justify-between p-2 rounded-lg bg-slate-950/60 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 cursor-pointer transition text-xs";
      
      let badge = "";
      if (f.matched_product_id) {
        const prod = appConfig.products.find(p => p.id === f.matched_product_id);
        badge = `<span class="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-bold ml-2">${prod ? prod.name : f.matched_product_id}</span>`;
      }

      item.innerHTML = `
        <div class="flex items-center gap-2 truncate pr-2">
          <i class="fa-solid fa-file-pdf text-emerald-400"></i>
          <span class="font-medium text-slate-200 truncate">${f.filename}</span>
          ${badge}
        </div>
        <div class="flex items-center gap-3 flex-shrink-0 text-slate-500 text-[10px]">
          <span>${f.size_mb} MB</span>
          <button class="px-2 py-0.5 rounded bg-emerald-600 hover:bg-emerald-500 text-slate-950 font-bold transition">Atidaryti</button>
        </div>
      `;
      item.onclick = () => selectInboxFile(f);
      container.appendChild(item);
    });
  } catch (err) {
    console.error("Inbox load error:", err);
  }
}

function selectInboxFile(f) {
  if (f.matched_product_id) {
    selectProduct(f.matched_product_id);
  }
  inspectFile(null, f.filename);
}

// ==========================================
// 3. FILE UPLOAD & INSPECT
// ==========================================
function initDropzone() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");

  dropzone.onclick = () => fileInput.click();
  dropzone.ondragover = (e) => {
    e.preventDefault();
    dropzone.classList.add("border-emerald-500", "bg-slate-900");
  };
  dropzone.ondragleave = () => {
    dropzone.classList.remove("border-emerald-500", "bg-slate-900");
  };
  dropzone.ondrop = (e) => {
    e.preventDefault();
    dropzone.classList.remove("border-emerald-500", "bg-slate-900");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      inspectFile(e.dataTransfer.files[0], null);
    }
  };
  fileInput.onchange = () => {
    if (fileInput.files && fileInput.files.length > 0) {
      inspectFile(fileInput.files[0], null);
    }
  };
}

async function inspectFile(fileObj, inboxFilename) {
  const spinner = document.getElementById("loading-spinner");
  spinner.classList.remove("hidden");

  const formData = new FormData();
  if (fileObj) formData.append("file", fileObj);
  if (inboxFilename) formData.append("inbox_filename", inboxFilename);
  formData.append("choke_pixels", activeChokeWhite);

  try {
    const res = await fetch("/api/inspect", { method: "POST", body: formData });
    const data = await res.json();
    spinner.classList.add("hidden");

    if (data.status === "ok") {
      activeFilePath = data.temp_file_id;
      activePreviews = data.previews;

      const badge = document.getElementById("active-filename-badge");
      badge.textContent = data.filename;
      badge.classList.remove("hidden");

      document.getElementById("dimensions-badge").textContent = `Matmenys: ${data.width_mm} x ${data.height_mm} mm (${data.width_px} x ${data.height_px} px)`;
      document.getElementById("job-name-input").value = data.filename.replace(/\.[^/.]+$/, "");
      document.getElementById("btn-dispatch").disabled = false;

      renderActiveLayer();
      logTerminal(`[INSPECT] Failas apdorotas: ${data.filename} (${data.elapsed_ms} ms)`);
    }
  } catch (err) {
    spinner.classList.add("hidden");
    console.error("Inspect error:", err);
  }
}

// ==========================================
// 4. LAYER TABS & INSPECTOR
// ==========================================
function initLayerTabs() {
  document.querySelectorAll(".layer-tab").forEach((btn) => {
    btn.onclick = () => {
      document.querySelectorAll(".layer-tab").forEach((b) => {
        b.classList.remove("bg-emerald-500", "text-slate-950", "shadow");
        b.classList.add("text-slate-300");
      });
      btn.classList.add("bg-emerald-500", "text-slate-950", "shadow");
      btn.classList.remove("text-slate-300");

      activeLayer = btn.dataset.layer;
      renderActiveLayer();
    };
  });
}

function renderActiveLayer() {
  if (!activePreviews) return;
  const placeholder = document.getElementById("inspector-placeholder");
  const imgEl = document.getElementById("inspector-img");

  placeholder.classList.add("hidden");
  imgEl.classList.remove("hidden");
  imgEl.src = activePreviews[activeLayer] || activePreviews["composite"];
}

// ==========================================
// 5. CONTROLS & DISPATCH
// ==========================================
function initControls() {
  // Choke buttons
  document.querySelectorAll(".btn-choke").forEach((btn) => {
    btn.onclick = () => {
      activeChokeWhite = parseInt(btn.dataset.px);
      updateChokeButtonsUI(activeChokeWhite);
      if (activeFilePath) {
        inspectFile(null, document.getElementById("active-filename-badge").textContent);
      }
    };
  });

  // Dispatch button
  document.getElementById("btn-dispatch").onclick = handleDispatch;
}

function updateChokeButtonsUI(val) {
  document.querySelectorAll(".btn-choke").forEach((b) => {
    const isCur = parseInt(b.dataset.px) === val;
    b.classList.toggle("bg-slate-700", isCur);
    b.classList.toggle("text-white", isCur);
    b.classList.toggle("text-slate-400", !isCur);
  });
}

async function handleDispatch() {
  const btn = document.getElementById("btn-dispatch");
  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner animate-spin text-lg"></i><span>Generuojamos Plokštės & Siunčiama...</span>`;

  const jobName = document.getElementById("job-name-input").value;
  const formData = new FormData();
  formData.append("file_path", activeFilePath);
  formData.append("product_id", selectedProductId);
  formData.append("job_name", jobName);
  formData.append("choke_white_override", activeChokeWhite);

  try {
    const res = await fetch("/api/dispatch", { method: "POST", body: formData });
    const data = await res.json();

    btn.innerHTML = `<i class="fa-solid fa-check text-xl"></i><span>SĖKMINGAI NUSIŲSTA Į HOT FOLDERIUS!</span>`;
    btn.classList.add("from-cyan-500", "to-blue-500");

    logTerminal(`[SPOOL] Sėkmingai paruošta ir nusiųsta: ${data.job_name} (${data.elapsed_ms} ms)`);
    (data.dispatched || []).forEach((d) => {
      logTerminal(`   -> ${d.layer}: ${d.destination}`);
    });

    setTimeout(() => {
      btn.innerHTML = `<i class="fa-solid fa-bolt text-lg"></i><span>SIŲSTI Į MIMAKI HOT FOLDERIUS</span>`;
      btn.classList.remove("from-cyan-500", "to-blue-500");
      btn.disabled = false;
    }, 3000);

    loadHistory();
  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = `<i class="fa-solid fa-triangle-exclamation text-lg"></i><span>KLAIDA</span>`;
    logTerminal(`[KLAIDA] Nepavyko nusiųsti: ${err.message}`);
  }
}

function logTerminal(msg) {
  const box = document.getElementById("dispatch-log");
  const row = document.createElement("div");
  row.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  box.appendChild(row);
  box.scrollTop = box.scrollHeight;
}

// ==========================================
// 6. CONFIGURATION MODAL (FULL CRUD)
// ==========================================
function initModals() {
  const modalConfig = document.getElementById("modal-config");
  document.getElementById("btn-open-config").onclick = () => {
    openConfigModal();
    modalConfig.classList.remove("hidden");
  };
  document.getElementById("btn-close-config").onclick = () => modalConfig.classList.add("hidden");
  document.getElementById("btn-cancel-config").onclick = () => modalConfig.classList.add("hidden");
  document.getElementById("btn-save-config").onclick = saveConfigFromModal;

  // History modal
  const modalHist = document.getElementById("modal-history");
  document.getElementById("btn-history").onclick = () => {
    modalHist.classList.remove("hidden");
    loadHistory();
  };
  document.getElementById("btn-close-history").onclick = () => modalHist.classList.add("hidden");

  // Add Product Button
  document.getElementById("btn-add-product").onclick = () => {
    const newProd = {
      id: "product_" + Date.now(),
      name: "Naujas Gaminys",
      keyword: "keyword",
      layers: ["White", "CMYK"],
      choke_white_px: 1,
      choke_primer_px: 0,
      hotfolders: { CMYK: "", White: "", Primer: "" }
    };
    appConfig.products.push(newProd);
    renderConfigModalProducts();
  };
}

function openConfigModal() {
  document.getElementById("cfg-inbox-folder").value = appConfig.inbox_folder || "";
  renderConfigModalProducts();
  document.getElementById("cfg-status-text").textContent = "";
}

function renderConfigModalProducts() {
  const container = document.getElementById("cfg-products-container");
  container.innerHTML = "";

  (appConfig.products || []).forEach((p, idx) => {
    const card = document.createElement("div");
    card.className = "bg-slate-950 p-4 rounded-xl border border-slate-800 flex flex-col gap-3";

    const hasPrimer = (p.layers || []).includes("Primer");
    const hasWhite = (p.layers || []).includes("White");
    const hasCmyk = (p.layers || []).includes("CMYK");

    card.innerHTML = `
      <div class="flex items-center justify-between pb-2 border-b border-slate-800">
        <div class="flex items-center gap-2 flex-1 mr-4">
          <label class="text-[10px] uppercase font-bold text-slate-400">Pavadinimas:</label>
          <input type="text" class="cfg-prod-name flex-1 bg-slate-900 border border-slate-700 rounded px-2.5 py-1 text-xs font-bold text-white focus:outline-none" value="${p.name}">
        </div>
        <button class="text-rose-400 hover:text-rose-300 text-xs px-2 py-1 rounded bg-rose-500/10 border border-rose-500/20" onclick="deleteConfigProduct(${idx})">
          <i class="fa-solid fa-trash mr-1"></i> Ištrinti
        </button>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
        <div>
          <label class="text-[10px] uppercase font-bold text-slate-400 block mb-1">Raktinis Žodis (Atpažinimui iš failo):</label>
          <input type="text" class="cfg-prod-kw w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white" value="${p.keyword || ""}">
        </div>
        <div>
          <label class="text-[10px] uppercase font-bold text-slate-400 block mb-1">Reikalingi Sluoksniai:</label>
          <div class="flex items-center gap-4 mt-1">
            <label class="flex items-center gap-1.5 cursor-pointer text-slate-300">
              <input type="checkbox" class="cfg-layer-primer rounded" ${hasPrimer ? "checked" : ""}> Primer
            </label>
            <label class="flex items-center gap-1.5 cursor-pointer text-slate-300">
              <input type="checkbox" class="cfg-layer-white rounded" ${hasWhite ? "checked" : ""}> White
            </label>
            <label class="flex items-center gap-1.5 cursor-pointer text-slate-300">
              <input type="checkbox" class="cfg-layer-cmyk rounded" ${hasCmyk ? "checked" : ""}> CMYK
            </label>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-3 text-xs">
        <div>
          <label class="text-[10px] uppercase font-bold text-slate-400 block mb-1">Balto Choke (px):</label>
          <input type="number" min="0" max="20" class="cfg-prod-choke-w w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white" value="${p.choke_white_px ?? 1}">
        </div>
        <div>
          <label class="text-[10px] uppercase font-bold text-slate-400 block mb-1">Grunto Choke (px):</label>
          <input type="number" min="0" max="20" class="cfg-prod-choke-p w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white" value="${p.choke_primer_px ?? 0}">
        </div>
      </div>

      <div class="space-y-1.5 pt-2 border-t border-slate-800/60 text-xs">
        <label class="text-[10px] uppercase font-bold text-slate-400 block">Hot Folderių Keliai Šiam Gaminiui:</label>
        <div class="flex items-center gap-2">
          <span class="w-14 text-slate-400 font-mono text-[10px]">CMYK:</span>
          <input type="text" class="cfg-hf-cmyk flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs font-mono text-white" value="${p.hotfolders?.CMYK || ""}">
        </div>
        <div class="flex items-center gap-2">
          <span class="w-14 text-slate-400 font-mono text-[10px]">White:</span>
          <input type="text" class="cfg-hf-white flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs font-mono text-white" value="${p.hotfolders?.White || ""}">
        </div>
        <div class="flex items-center gap-2">
          <span class="w-14 text-slate-400 font-mono text-[10px]">Primer:</span>
          <input type="text" class="cfg-hf-primer flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs font-mono text-white" value="${p.hotfolders?.Primer || ""}">
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

function deleteConfigProduct(idx) {
  appConfig.products.splice(idx, 1);
  renderConfigModalProducts();
}

async function saveConfigFromModal() {
  const statusEl = document.getElementById("cfg-status-text");
  statusEl.textContent = "Saugoma...";

  const inboxFolder = document.getElementById("cfg-inbox-folder").value.trim();
  const productCards = document.querySelectorAll("#cfg-products-container > div");

  const updatedProducts = [];
  productCards.forEach((c, idx) => {
    const existing = appConfig.products[idx] || {};
    const name = c.querySelector(".cfg-prod-name").value.trim();
    const keyword = c.querySelector(".cfg-prod-kw").value.trim();
    
    const layers = [];
    if (c.querySelector(".cfg-layer-primer").checked) layers.push("Primer");
    if (c.querySelector(".cfg-layer-white").checked) layers.push("White");
    if (c.querySelector(".cfg-layer-cmyk").checked) layers.push("CMYK");

    const chokeW = parseInt(c.querySelector(".cfg-prod-choke-w").value) || 0;
    const chokeP = parseInt(c.querySelector(".cfg-prod-choke-p").value) || 0;

    const hfCmyk = c.querySelector(".cfg-hf-cmyk").value.trim();
    const hfWhite = c.querySelector(".cfg-hf-white").value.trim();
    const hfPrimer = c.querySelector(".cfg-hf-primer").value.trim();

    updatedProducts.push({
      id: existing.id || ("prod_" + Date.now() + "_" + idx),
      name: name || "Gaminys " + (idx + 1),
      keyword: keyword,
      layers: layers,
      choke_white_px: chokeW,
      choke_primer_px: chokeP,
      hotfolders: {
        CMYK: hfCmyk,
        White: hfWhite,
        Primer: hfPrimer
      }
    });
  });

  const payload = {
    inbox_folder: inboxFolder,
    products: updatedProducts
  };

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      statusEl.textContent = "Konfigūracija išsaugota sėkmingai!";
      setTimeout(() => {
        document.getElementById("modal-config").classList.add("hidden");
      }, 1000);
      await loadAppConfig();
      await loadInboxFiles();
    }
  } catch (err) {
    statusEl.textContent = "Klaida išsaugant konfigūraciją.";
  }
}

// ==========================================
// 7. HISTORY & WEBSOCKET
// ==========================================
async function loadHistory() {
  try {
    const res = await fetch("/api/history");
    const data = await res.json();
    document.getElementById("history-count").textContent = data.length;

    const tbody = document.getElementById("history-tbody");
    tbody.innerHTML = "";
    data.forEach((j) => {
      const tr = document.createElement("tr");
      tr.className = "border-b border-slate-800/60 hover:bg-slate-800/30";
      tr.innerHTML = `
        <td class="py-2.5 text-slate-400 font-mono">${j.timestamp}</td>
        <td class="py-2.5 font-bold text-white">${j.job_name}</td>
        <td class="py-2.5 text-slate-300">${j.product_name}</td>
        <td class="py-2.5"><span class="px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">${j.layers.join(", ")}</span></td>
        <td class="py-2.5 text-right"><span class="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-bold border border-emerald-500/20">SPOOLINTA (${j.elapsed_ms}ms)</span></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {}
}

function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.event === "job_dispatched") {
      loadHistory();
    }
  };
}
