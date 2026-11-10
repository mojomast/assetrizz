let transport = {
  rest: null,
  setInterval: null,
};

const thumbCache = {};
const thumbUrls = [];

function ComposerPane() {
  const rootRef = useRef(null);
  const [model, setModel] = useState({ backend: "loading" });
  const previewUrl = useRef("");
  const previewSha = useRef("");
  const queryRef = useRef({ q: "", style: "", category: "" });

  useEffect(() => {
    let stopped = false;

    function load() {
      const rest = transport.rest;
      if (typeof rest !== "function") {
        if (!stopped) {
          setModel({
            backend: "offline",
            message:
              "The compose pane can't reach the plugin backend. Enable assetrizz and rescan plugins. The two tools still run without this pane.",
          });
        }
        return Promise.resolve();
      }
      return Promise.resolve(rest("/status"))
        .then((status) => {
          const libraryOk = !status || status.library_ok !== false;
          const current = status && status.current;
          const sceneCall = libraryOk
            ? Promise.resolve(rest(current ? "/scene?name=" + encodeURIComponent(current) : "/scene"))
            : Promise.resolve(null);
          const previewCall =
            libraryOk && current
              ? Promise.resolve(
                  rest(
                    "/preview?name=" +
                      encodeURIComponent(current) +
                      (previewSha.current ? "&since=" + encodeURIComponent(previewSha.current) : "")
                  )
                )
              : Promise.resolve(null);
          const searchCall = libraryOk
            ? Promise.resolve(
                rest(
                  "/search?" +
                    toQuery({
                      q: queryRef.current.q,
                      style: queryRef.current.style,
                      category: queryRef.current.category,
                      limit: 24,
                    })
                )
              )
            : Promise.resolve({ items: [] });
          return Promise.all([Promise.resolve(status), sceneCall, previewCall, searchCall]);
        })
        .then((packed) => {
          if (stopped) return;
          const status = packed[0] || {};
          const sceneBody = packed[1] || {};
          const preview = packed[2];
          const found = packed[3] || {};
          if (status.library_ok === false) {
            setModel({
              backend: "ready",
              libraryOk: false,
              message: status.library_error || status.fix || "Library path is not set.",
            });
            return;
          }
          if (preview && preview.ok && preview.data && !preview.unchanged) {
            const next = blobUrlFromBase64(preview.data, preview.mime || "image/jpeg");
            revokeUrl(previewUrl.current);
            previewUrl.current = next;
            previewSha.current = preview.sha256 || "";
          } else if (preview && preview.ok && preview.unchanged) {
            previewSha.current = preview.sha256 || previewSha.current;
          }
          const items = Array.isArray(found.items) ? found.items : [];
          const stats = status.stats || {};
          const styles = (stats.styles && Array.isArray(status.styles) ? status.styles : null) || styleNames(status);
          setModel({
            backend: "ready",
            libraryOk: true,
            live: true,
            library: status.library || "",
            counts: stats,
            styles: styles,
            categories: categoryNames(status),
            scene: sceneBody && sceneBody.scene ? sceneBody.scene : null,
            previewUrl: previewUrl.current,
            assets: items.map((item) => ({
              slug: item.slug,
              id: item.id,
              thumb: thumbCache[item.slug] || "",
            })),
            query: queryRef.current.q,
            style: queryRef.current.style,
            category: queryRef.current.category,
          });
          hydrateThumbs(items, rest, function () {
            if (stopped) return;
            setModel(function (prev) {
              if (!prev || !Array.isArray(prev.assets)) return prev;
              return Object.assign({}, prev, {
                assets: prev.assets.map(function (item) {
                  return Object.assign({}, item, { thumb: thumbCache[item.slug] || item.thumb || "" });
                }),
              });
            });
          });
        })
        .catch((error) => {
          if (stopped) return;
          setModel({
            backend: "offline",
            message: (error && error.message) || "The compose pane could not refresh.",
          });
        });
    }

    load();
    let timer = null;
    if (typeof transport.setInterval === "function") {
      timer = transport.setInterval(function () {
        load();
      }, 1500);
    }
    return function () {
      stopped = true;
      if (typeof timer === "function") timer();
    };
  }, []);

  useEffect(() => {
    if (!rootRef.current) return;
    mountPane(
      rootRef.current,
      model,
      {
        onSearch(q, style, category) {
          queryRef.current = { q: q || "", style: style || "", category: category || "" };
          const rest = transport.rest;
          if (typeof rest !== "function") return;
          Promise.resolve(
            rest(
              "/search?" +
                toQuery({
                  q: queryRef.current.q,
                  style: queryRef.current.style,
                  category: queryRef.current.category,
                  limit: 24,
                })
            )
          ).then((found) => {
            const items = found && Array.isArray(found.items) ? found.items : [];
            setModel(function (prev) {
              return Object.assign({}, prev || {}, {
                query: queryRef.current.q,
                style: queryRef.current.style,
                category: queryRef.current.category,
                assets: items.map(function (item) {
                  return { slug: item.slug, id: item.id, thumb: thumbCache[item.slug] || "" };
                }),
              });
            });
            hydrateThumbs(items, rest, function () {
              setModel(function (prev) {
                if (!prev || !Array.isArray(prev.assets)) return prev;
                return Object.assign({}, prev, {
                  assets: prev.assets.map(function (item) {
                    return Object.assign({}, item, { thumb: thumbCache[item.slug] || item.thumb || "" });
                  }),
                });
              });
            });
          });
        },
      },
      PANE_CSS
    );
  }, [model]);

  return jsx("div", { ref: rootRef, className: "az-host" });
}

function styleNames(status) {
  const rows = status && status.stats && Array.isArray(status.stats.styles) ? status.stats.styles : [];
  // status.stats is compacted and may only have counts; fall back to empty.
  if (rows.length && typeof rows[0] === "object") return rows.map(function (row) { return row.name; }).filter(Boolean);
  return [];
}

function categoryNames(status) {
  const rows = status && status.stats && Array.isArray(status.stats.categories) ? status.stats.categories : [];
  if (rows.length && typeof rows[0] === "object") return rows.map(function (row) { return row.name; }).filter(Boolean);
  return [];
}

function hydrateThumbs(items, rest, done) {
  if (typeof rest !== "function") return;
  let chain = Promise.resolve();
  (items || []).slice(0, 24).forEach(function (item) {
    if (!item || !item.slug || thumbCache[item.slug]) return;
    chain = chain
      .then(function () {
        return rest("/thumb?slug=" + encodeURIComponent(item.slug) + "&max_px=96");
      })
      .then(function (body) {
        if (body && body.ok && body.data) {
          const url = blobUrlFromBase64(body.data, body.mime || "image/jpeg");
          if (url) {
            thumbCache[item.slug] = url;
            thumbUrls.push(url);
          }
        }
      })
      .catch(function () {});
  });
  chain.then(function () {
    if (typeof done === "function") done();
  });
}

function toQuery(map) {
  const parts = [];
  Object.keys(map).forEach(function (key) {
    const value = map[key];
    if (value == null || value === "") return;
    parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(String(value)));
  });
  return parts.join("&");
}

function blobUrlFromBase64(data, mime) {
  if (typeof data !== "string" || !data) return "";
  if (
    typeof atob !== "function" ||
    typeof Blob === "undefined" ||
    typeof URL === "undefined" ||
    !URL.createObjectURL
  ) {
    return "";
  }
  const binary = atob(data);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], { type: mime || "image/jpeg" }));
  return url;
}

function revokeUrl(url) {
  if (url && typeof url === "string" && url.slice(0, 5) === "blob:" && typeof URL !== "undefined" && URL.revokeObjectURL) {
    URL.revokeObjectURL(url);
  }
}

function registerComposer(ctx) {
  if (!ctx || typeof ctx.register !== "function") return false;
  transport = {
    rest: typeof ctx.rest === "function" ? (path, opts) => ctx.rest(path, opts) : null,
    setInterval: typeof ctx.setInterval === "function" ? (fn, ms) => ctx.setInterval(fn, ms) : null,
  };
  if (typeof ctx.onDispose === "function") {
    ctx.onDispose(() => {
      const style = document.getElementById("az-pane-style");
      if (style) style.remove();
      revokeUrl(transport._preview);
      thumbUrls.forEach(revokeUrl);
    });
  }
  try {
    ctx.register({
      id: "composer",
      title: "Assetrizz",
      area: "panes",
      order: 44,
      data: { placement: "right", width: "780px" },
      render: () => jsx(ComposerPane, {}),
    });
  } catch (err) {
    return false;
  }
  return true;
}

export default {
  id: "assetrizz",
  name: "Assetrizz",
  defaultEnabled: true,
  register: registerComposer,
};
