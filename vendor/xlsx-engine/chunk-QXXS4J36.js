// ../../node_modules/.pnpm/@extend-ai+office-fonts@https+++github.com+extend-hq+rust-office+releases+download+office-fon_erenooq3df3zhb3ilqkrs3q35y/node_modules/@extend-ai/office-fonts/families.js
var families = [
  { id: "carlito", family: "Carlito", original: "Calibri", load: () => import("./carlito-data-WDJWVB7V.js") },
  { id: "arimo", family: "Arimo", original: "Arial", load: () => import("./arimo-data-GKF7MBKW.js") },
  { id: "tinos", family: "Tinos", original: "Times New Roman", load: () => import("./tinos-data-I2LYQJSE.js") },
  { id: "cousine", family: "Cousine", original: "Courier New", load: () => import("./cousine-data-ZHTHSRJH.js") }
];

// ../../node_modules/.pnpm/@extend-ai+office-fonts@https+++github.com+extend-hq+rust-office+releases+download+office-fon_erenooq3df3zhb3ilqkrs3q35y/node_modules/@extend-ai/office-fonts/runtime.js
var registry = /* @__PURE__ */ Symbol.for("@extend-ai/office-fonts/loads/v2");
var loads = globalThis[registry] ??= /* @__PURE__ */ new WeakMap();
var normalize = (family) => family.trim().replace(/^["']|["']$/g, "").toLowerCase();
var primary = (family) => family.split(",")[0];
var lookup = new Map(families.flatMap((family) => [family.original, family.family].map((name) => [normalize(name), family])));
var variants = [
  { style: "normal", weight: "400", suffix: "" },
  { style: "normal", weight: "700", suffix: " Bold" },
  { style: "italic", weight: "400", suffix: " Italic" },
  { style: "italic", weight: "700", suffix: " Bold Italic" }
];
function officeFontFallback(family) {
  return lookup.get(normalize(primary(family)))?.family;
}
function matches(face, family, variant) {
  const weight = face.weight === "normal" ? "400" : face.weight === "bold" ? "700" : face.weight;
  const range = weight.split(/\s+/).map(Number);
  return normalize(face.family) === normalize(family) && face.style === variant.style && Number(variant.weight) >= range[0] && Number(variant.weight) <= (range[1] ?? range[0]);
}
async function loadOfficeFonts(target = globalThis.document, requestedFamilies = ["Calibri"]) {
  const FontFaceClass = target?.defaultView?.FontFace ?? globalThis.FontFace;
  if (!target?.fonts || !FontFaceClass) return;
  const fonts = target.fonts;
  let entries = loads.get(fonts);
  if (!entries) loads.set(fonts, entries = /* @__PURE__ */ new Map());
  const selected = new Set([...requestedFamilies].map((name) => normalize(primary(name))));
  await Promise.all([...selected].map(async (key) => {
    const definition = lookup.get(key);
    if (!definition) return;
    const previous = entries.get(key);
    if (previous && (!previous.ready || previous.faces.every((face) => fonts.has(face)))) return previous.promise;
    const family = key === normalize(definition.original) ? definition.original : definition.family;
    const state = { ready: false, faces: [], promise: void 0 };
    state.promise = (async () => {
      const added = [];
      try {
        const results = await Promise.allSettled(variants.map(async (variant, index) => {
          const existing = [...fonts].filter((face2) => matches(face2, family, variant) && face2.status !== "error");
          if (existing.length) {
            const loaded = await Promise.allSettled(existing.map((face2) => face2.load()));
            const available = loaded.flatMap((result) => result.status === "fulfilled" ? [result.value] : []);
            if (available.length) return available;
          }
          let face;
          if (family === definition.original) {
            try {
              face = await new FontFaceClass(family, `local("${family}${variant.suffix}")`, variant).load();
            } catch {
              face = void 0;
            }
          }
          if (!face) {
            const { faces: assets } = await definition.load();
            face = new FontFaceClass(family, `url("${assets[index].source}")`, variant);
            fonts.add(face);
            added.push(face);
            await face.load();
          } else {
            fonts.add(face);
            added.push(face);
          }
          return [face];
        }));
        const failure = results.find((result) => result.status === "rejected");
        if (failure) throw failure.reason;
        state.faces = results.flatMap((result) => result.value);
        state.ready = true;
      } catch (error) {
        for (const face of added) fonts.delete(face);
        entries.delete(key);
        throw error;
      }
    })();
    entries.set(key, state);
    return state.promise;
  }));
}

export {
  officeFontFallback,
  loadOfficeFonts
};
//# sourceMappingURL=chunk-QXXS4J36.js.map