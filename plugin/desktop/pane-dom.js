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
  if (model.libraryOk === false) {
    pane.appendChild(
      emptyBlock(
        "Library not found",
        model.message ||
          "Point the Library path setting (or ASSETRIZZ_LIBRARY) at an assetrizz clone that has assets/ and db/assets.db.xz."
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
  left.innerHTML = model.library
    ? "Library <strong></strong>"
    : "Library path is not set";
  if (model.library) left.querySelector("strong").textContent = model.library;
  const right = el("div");
  right.textContent = model.counts
    ? Number(model.counts.total_ok || 0).toLocaleString() + " assets"
    : "";
  foot.appendChild(left);
  foot.appendChild(right);
  return foot;
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
