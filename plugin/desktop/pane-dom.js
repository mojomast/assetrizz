/** Assetrizz compose view. No imports: the desktop bundle inlines this file. */

function mountPane(root, state, actions, css) {
  if (!root) return;
  ensurePaneStyle(css);
  const model = state && typeof state === "object" ? state : {};
  root.textContent = "";
  root.className = "az-host";
  const pane = el("section", "az");
  pane.setAttribute("aria-label", "Assetrizz composer");
  root.appendChild(pane);

  if (model.backend === "loading") {
    pane.appendChild(emptyBlock("Assetrizz", "Looking for the compose pane backend."));
    return;
  }
  if (model.backend === "offline") {
    pane.appendChild(
      emptyBlock(
        "Assetrizz is offline",
        model.message ||
          "Enable the assetrizz plugin, then rescan. The search and scene tools still run without this pane."
      )
    );
    return;
  }
  if (model.catalogOk === false) {
    pane.appendChild(
      emptyBlock(
        "Catalog not found",
        model.message ||
          "The bundled catalog is missing. Reinstall the plugin/ directory, or point Library path at a checkout that has db/assets.db.xz."
      )
    );
    return;
  }

  pane.appendChild(header(model));
  const body = el("div", "az-body");
  body.appendChild(stage(model));
  body.appendChild(side(model, actions));
  pane.appendChild(body);
  pane.appendChild(footer(model));
}

function header(model) {
  const top = el("div", "az-top");
  const brand = el("div", "az-brand");
  brand.appendChild(el("div", "az-mark"));
  const names = el("div");
  names.appendChild(el("p", "az-kicker", "Assetrizz"));
  const scene = model.scene || {};
  names.appendChild(el("h1", "az-title", scene.id || "No scene yet"));
  brand.appendChild(names);
  top.appendChild(brand);
  const status = model.live ? "live" : model.backend === "ready" ? "ready" : "offline";
  const live = el("div", "az-live is-" + status);
  live.appendChild(el("i", "az-dot"));
  const label = scene.id
    ? (scene.width || "?") + "×" + (scene.height || "?") + " · " + (scene.layer_count || 0) + " layers"
    : "Idle";
  live.appendChild(document.createTextNode(label));
  top.appendChild(live);
  return top;
}

function stage(model) {
  const wrap = el("div", "az-stage");
  const canvas = el("div", "az-canvas");
  const src = model.previewUrl;
  if (src) {
    const img = el("img");
    img.alt = "Current scene preview";
    img.src = src;
    canvas.appendChild(img);
  } else if (!model.scene) {
    canvas.appendChild(
      el("div", "az-fallback", "Ask the agent to create a scene, then place assets. The preview appears here.")
    );
  } else {
    canvas.appendChild(el("div", "az-fallback", "Rendering a preview…"));
  }
  wrap.appendChild(canvas);
  return wrap;
}

function side(model, actions) {
  const sideEl = el("div", "az-side");
  sideEl.appendChild(searchBox(model, actions));
  sideEl.appendChild(grid(model));
  sideEl.appendChild(layers(model));
  sideEl.appendChild(libraryPanel(model, actions));
  return sideEl;
}

function searchBox(model, actions) {
  const form = el("form", "az-search");
  const input = el("input");
  input.type = "search";
  input.placeholder = "Search assets";
  input.value = model.query || "";
  input.setAttribute("aria-label", "Search assets");
  const filters = el("div", "az-filters");
  const style = selectBox("style", "All styles", (model.styles || []).map(optName), model.style);
  const category = selectBox(
    "category",
    "All categories",
    (model.categories || []).map(optName),
    model.category
  );
  filters.appendChild(style);
  filters.appendChild(category);
  form.appendChild(input);
  form.appendChild(filters);
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (actions && typeof actions.onSearch === "function") {
      actions.onSearch(input.value, style.value, category.value);
    }
  });
  style.addEventListener("change", function () {
    if (actions && typeof actions.onSearch === "function") {
      actions.onSearch(input.value, style.value, category.value);
    }
  });
  category.addEventListener("change", function () {
    if (actions && typeof actions.onSearch === "function") {
      actions.onSearch(input.value, style.value, category.value);
    }
  });
  return form;
}

function optName(item) {
  if (typeof item === "string") return item;
  return (item && (item.name || item.style || item.category)) || "";
}

function selectBox(name, emptyLabel, values, current) {
  const select = el("select");
  select.name = name;
  select.setAttribute("aria-label", name);
  const first = el("option");
  first.value = "";
  first.textContent = emptyLabel;
  select.appendChild(first);
  (values || []).forEach(function (value) {
    if (!value) return;
    const option = el("option");
    option.value = value;
    option.textContent = value;
    if (value === current) option.selected = true;
    select.appendChild(option);
  });
  return select;
}

function grid(model) {
  const gridEl = el("div", "az-grid");
  const items = Array.isArray(model.assets) ? model.assets : [];
  if (!items.length) {
    gridEl.appendChild(el("div", "az-quiet", "Search the library to browse sprites."));
    return gridEl;
  }
  items.slice(0, 24).forEach(function (item) {
    const card = el("figure", "az-card");
    const src = item.thumb;
    if (src) {
      const img = el("img");
      img.alt = item.slug || "asset";
      img.src = src;
      card.appendChild(img);
    } else {
      card.appendChild(el("div", "az-ph", "png"));
    }
    const cap = el("figcaption");
    cap.textContent = shortSlug(item.slug || "");
    cap.title = item.slug || "";
    card.appendChild(cap);
    gridEl.appendChild(card);
  });
  return gridEl;
}

function shortSlug(slug) {
  const parts = String(slug).split("/");
  return parts[parts.length - 1] || slug;
}

function layers(model) {
  const wrap = el("div", "az-layers");
  wrap.appendChild(el("p", "az-section-label", "Layers"));
  const rows = model.scene && Array.isArray(model.scene.layers) ? model.scene.layers.slice() : [];
  if (!rows.length) {
    wrap.appendChild(el("p", "az-quiet", "Nothing placed yet."));
    return wrap;
  }
  rows
    .slice()
    .reverse()
    .forEach(function (layer) {
      const row = el("div", "az-layer");
      row.appendChild(el("code", "", String(layer.id || "")));
      row.appendChild(el("span", "", shortSlug(layer.slug || "")));
      row.appendChild(el("em", "", "z " + (layer.z == null ? "0" : layer.z)));
      wrap.appendChild(row);
    });
  return wrap;
}

function footer(model) {
  const foot = el("div", "az-foot");
  const left = el("div");
  const lib = model.libraryInfo || {};
  const mode = lib.asset_mode || model.assetMode || "on_demand";
  if (model.library) {
    left.appendChild(document.createTextNode(mode + " · "));
    const strong = el("strong");
    strong.textContent = String(model.library);
    left.appendChild(strong);
  } else {
    left.textContent = mode + " · on-demand cache (no local library installed)";
  }
  const right = el("div");
  const disk = lib.disk || {};
  const parts = [];
  if (model.counts) parts.push(Number(model.counts.total_ok || 0).toLocaleString() + " assets");
  if (disk.local_label && disk.local_bytes) parts.push("local " + disk.local_label);
  if (disk.cache_label && disk.cache_bytes) parts.push("cache " + disk.cache_label);
  right.textContent = parts.join(" · ");
  foot.appendChild(left);
  foot.appendChild(right);
  return foot;
}

function libraryPanel(model, actions) {
  const wrap = el("div", "az-lib");
  wrap.appendChild(el("p", "az-section-label", "Local library"));
  const lib = model.libraryInfo || {};
  const job = (lib.job && typeof lib.job === "object") ? lib.job : {};
  const running = job.status === "running" || job.status === "starting";
  const disk = lib.disk || {};

  const summary = el("p", "az-lib-summary");
  const mode = lib.asset_mode || model.assetMode || "on_demand";
  let summaryText = "Mode: " + mode + ". Full library is " + (lib.total_label || "about 1.6 GB") + ".";
  if (disk.local_bytes) summaryText += " Local copy uses " + disk.local_label + ".";
  if (disk.cache_bytes) summaryText += " On-demand cache uses " + disk.cache_label + ".";
  summary.textContent = summaryText;
  wrap.appendChild(summary);

  if (lib.local_library_dir) {
    const dest = el("p", "az-quiet");
    dest.textContent = "Download folder: " + String(lib.local_library_dir);
    wrap.appendChild(dest);
  }

  const packs = Array.isArray(lib.packs) ? lib.packs : [];
  const selected = model.selectedPacks && typeof model.selectedPacks === "object" ? model.selectedPacks : {};
  const list = el("div", "az-packs");
  packs.forEach(function (pack) {
    if (!pack || !pack.name) return;
    const row = el("label", "az-pack");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = pack.name;
    box.checked = selected[pack.name] === true;
    box.disabled = running;
    box.addEventListener("change", function () {
      if (actions && typeof actions.onTogglePack === "function") {
        actions.onTogglePack(pack.name, box.checked);
      }
    });
    row.appendChild(box);
    const meta = el("span");
    const have = pack.downloaded ? " · " + pack.downloaded + "/" + pack.count + " on disk" : "";
    meta.textContent = pack.name + " · " + (pack.label || "") + " · " + Number(pack.count || 0).toLocaleString() + " PNGs" + have;
    row.appendChild(meta);
    list.appendChild(row);
  });
  if (packs.length) wrap.appendChild(list);

  const buttons = el("div", "az-lib-actions");
  const downloadAll = el("button", "az-btn");
  downloadAll.type = "button";
  downloadAll.textContent = "Download library (" + (lib.total_label || "1.6 GB") + ")";
  downloadAll.disabled = running;
  downloadAll.addEventListener("click", function () {
    if (actions && typeof actions.onDownload === "function") actions.onDownload(["*"]);
  });
  const downloadSel = el("button", "az-btn az-btn-ghost");
  downloadSel.type = "button";
  downloadSel.textContent = "Download selected packs";
  downloadSel.disabled = running;
  downloadSel.addEventListener("click", function () {
    const names = [];
    Object.keys(selected).forEach(function (name) {
      if (selected[name]) names.push(name);
    });
    if (!names.length) return;
    if (actions && typeof actions.onDownload === "function") actions.onDownload(names);
  });
  buttons.appendChild(downloadAll);
  buttons.appendChild(downloadSel);
  wrap.appendChild(buttons);

  if (running || job.status === "done" || job.status === "cancelled" || job.status === "error") {
    const progress = el("div", "az-progress");
    const total = Number(job.total || 0);
    const done = Number(job.done || 0);
    const pct = total ? Math.min(100, Math.round((done / total) * 100)) : (running ? 0 : 100);
    const bar = el("div", "az-progress-bar");
    const fill = el("div", "az-progress-fill");
    fill.style.width = String(pct) + "%";
    bar.appendChild(fill);
    progress.appendChild(bar);
    const label = el("p", "az-quiet");
    label.textContent = (job.message || job.status || "") + (total ? " (" + done + "/" + total + ")" : "");
    progress.appendChild(label);
    if (running) {
      const cancel = el("button", "az-btn az-btn-ghost");
      cancel.type = "button";
      cancel.textContent = "Cancel";
      cancel.addEventListener("click", function () {
        if (actions && typeof actions.onCancel === "function") actions.onCancel();
      });
      progress.appendChild(cancel);
    }
    wrap.appendChild(progress);
  }

  const danger = el("div", "az-lib-danger");
  if (model.removeConfirm) {
    const warn = el("p", "az-warn");
    warn.textContent = "Delete the local library at " + String(lib.local_library_dir || "the configured folder") + "? This cannot be undone. The source checkout will not be deleted.";
    danger.appendChild(warn);
    const confirm = el("button", "az-btn az-btn-danger");
    confirm.type = "button";
    confirm.textContent = "Confirm delete";
    confirm.addEventListener("click", function () {
      if (actions && typeof actions.onRemove === "function") actions.onRemove(true);
    });
    const abort = el("button", "az-btn az-btn-ghost");
    abort.type = "button";
    abort.textContent = "Keep library";
    abort.addEventListener("click", function () {
      if (actions && typeof actions.onRemove === "function") actions.onRemove(false);
    });
    danger.appendChild(confirm);
    danger.appendChild(abort);
  } else {
    const remove = el("button", "az-btn az-btn-ghost");
    remove.type = "button";
    remove.textContent = "Remove local library";
    remove.disabled = running || lib.can_remove === false;
    remove.title = lib.remove_blocked_reason || "";
    remove.addEventListener("click", function () {
      if (actions && typeof actions.onAskRemove === "function") actions.onAskRemove();
    });
    danger.appendChild(remove);
  }

  if (model.cacheConfirm) {
    const warn = el("p", "az-warn");
    warn.textContent = "Clear the on-demand cache (" + ((lib.disk && lib.disk.cache_label) || "cached PNGs") + ")?";
    danger.appendChild(warn);
    const confirm = el("button", "az-btn az-btn-danger");
    confirm.type = "button";
    confirm.textContent = "Confirm clear cache";
    confirm.addEventListener("click", function () {
      if (actions && typeof actions.onClearCache === "function") actions.onClearCache(true);
    });
    const abort = el("button", "az-btn az-btn-ghost");
    abort.type = "button";
    abort.textContent = "Keep cache";
    abort.addEventListener("click", function () {
      if (actions && typeof actions.onClearCache === "function") actions.onClearCache(false);
    });
    danger.appendChild(confirm);
    danger.appendChild(abort);
  } else {
    const clear = el("button", "az-btn az-btn-ghost");
    clear.type = "button";
    clear.textContent = "Clear on-demand cache";
    clear.disabled = running || !(disk.cache_bytes);
    clear.addEventListener("click", function () {
      if (actions && typeof actions.onAskClearCache === "function") actions.onAskClearCache();
    });
    danger.appendChild(clear);
  }
  wrap.appendChild(danger);
  return wrap;
}

function emptyBlock(title, copy) {
  const box = el("div", "az-empty");
  box.appendChild(el("h2", "", title));
  box.appendChild(el("p", "", copy));
  return box;
}

function ensurePaneStyle(css) {
  let style = document.getElementById("az-pane-style");
  if (!style) {
    style = document.createElement("style");
    style.id = "az-pane-style";
    document.head.appendChild(style);
  }
  if (typeof css === "string") style.textContent = css;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null && text !== "") node.textContent = text;
  return node;
}
