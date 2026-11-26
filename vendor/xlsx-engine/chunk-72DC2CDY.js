// ../../node_modules/.pnpm/@extend-ai+duke-office-charts@https+++github.com+extend-hq+duke-office+releases+download+char_7niq74fludz35wmlgsesva5aya/node_modules/@extend-ai/duke-office-charts/browser/loader.js
async function embeddedModule(loadPayload) {
  const { default: base64 } = await loadPayload();
  const binary = atob(base64);
  const compressed = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) compressed[i] = binary.charCodeAt(i);
  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream, { headers: { "Content-Type": "application/wasm" } });
}
function createLoader(init, renderChartSvg, loadPayload) {
  const renderer = {
    renderChart(xml, options = {}) {
      return renderChartSvg(xml, JSON.stringify(options)) ?? null;
    }
  };
  let pending;
  return function loadOfficeCharts(source) {
    if (!pending) {
      const input = source ?? (typeof DecompressionStream === "function" ? embeddedModule(loadPayload) : void 0);
      pending = Promise.resolve(input).then((module) => init(module === void 0 ? void 0 : { module_or_path: module })).then(() => renderer).catch((error) => {
        pending = void 0;
        throw error;
      });
    }
    return pending;
  };
}

export {
  createLoader
};
//# sourceMappingURL=chunk-72DC2CDY.js.map