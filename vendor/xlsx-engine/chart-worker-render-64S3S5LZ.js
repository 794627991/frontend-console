import {
  parseWorkbookXml,
  serializeWorkbookXml
} from "./chunk-X6HOZB4D.js";

// src/chart-data-projection.ts
var chartNamespace = "http://schemas.openxmlformats.org/drawingml/2006/chart";
function projectPoints(points, excluded) {
  const projected = [];
  const activeParents = /* @__PURE__ */ new Map();
  const previousParents = /* @__PURE__ */ new Map();
  for (const point of points) {
    const categories = point.categories ?? [];
    const ancestor = Math.max(0, ...categories.map((entry) => entry.level));
    for (const level of activeParents.keys()) if (level < ancestor) activeParents.delete(level);
    for (const entry of categories) if (entry.level > 0) activeParents.set(entry.level, entry.label);
    if (excluded.has(point.index)) continue;
    const projectedCategories = [...categories];
    let changedParent = false;
    for (const [level, label] of [...activeParents].sort(([a], [b]) => b - a)) {
      if (!projectedCategories.some((entry) => entry.level === level) && (changedParent || previousParents.get(level) !== label)) {
        projectedCategories.push({ level, label });
      }
      changedParent ||= previousParents.get(level) !== label;
      previousParents.set(level, label);
    }
    for (const level of previousParents.keys()) if (!activeParents.has(level)) previousParents.delete(level);
    projected.push({ ...point, index: projected.length, categories: projectedCategories });
  }
  return projected;
}
function projectChartData(xml, data, exclusions) {
  if (!exclusions.some((indices) => indices?.length)) return { xml, data, pointMaps: void 0 };
  const excluded = exclusions.map((indices) => new Set(indices ?? []));
  const pointMaps = data.series.map((series, index) => series.points.filter((point) => !excluded[index]?.has(point.index)).map((point) => point.index));
  const document = parseWorkbookXml(xml);
  if (document.getElementsByTagName("parsererror").length) throw new Error("Unable to read chart definition.");
  const seriesNodes = Array.from(document.getElementsByTagNameNS(chartNamespace, "ser"));
  if (seriesNodes.length !== data.series.length) return { xml, data, pointMaps: void 0 };
  const remapPointStyle = (node, inverse) => {
    const index = Array.from(node.children).find((child) => child.localName === "idx");
    if (!index) return;
    const projected = inverse.get(Number(index.getAttribute("val")));
    if (projected === void 0) node.remove();
    else index.setAttribute("val", String(projected));
  };
  for (const group of new Set(seriesNodes.map((series) => series.parentElement).filter((group2) => Boolean(group2)))) {
    const groupLabels = Array.from(group.children).find((node) => node.localName === "dLbls");
    const overrides = Array.from(groupLabels?.children ?? []).filter((node) => node.localName === "dLbl");
    if (!overrides.length) continue;
    const groupSeries = seriesNodes.filter((series) => series.parentElement === group);
    const maps = groupSeries.map((series) => pointMaps[seriesNodes.indexOf(series)]);
    if (maps.every((map) => JSON.stringify(map) === JSON.stringify(maps[0]))) {
      const inverse = new Map(maps[0].map((original, index) => [original, index]));
      overrides.forEach((node) => remapPointStyle(node, inverse));
      continue;
    }
    for (const series of groupSeries) {
      let labels = Array.from(series.children).find((node) => node.localName === "dLbls");
      if (!labels) {
        labels = document.createElementNS(chartNamespace, "c:dLbls");
        series.appendChild(labels);
      }
      const ownDefaults = new Set(Array.from(labels.children).filter((node) => node.localName !== "dLbl").map((node) => node.localName));
      for (const inherited of overrides) {
        const sourceIndex = Array.from(inherited.children).find((node) => node.localName === "idx")?.getAttribute("val");
        let target = Array.from(labels.children).find((node) => node.localName === "dLbl" && Array.from(node.children).some((child) => child.localName === "idx" && child.getAttribute("val") === sourceIndex));
        if (!target) {
          target = document.createElementNS(chartNamespace, "c:dLbl");
          labels.appendChild(target);
        }
        for (const property of Array.from(inherited.children)) {
          if (!ownDefaults.has(property.localName) && !Array.from(target.children).some((node) => node.localName === property.localName)) {
            target.appendChild(property.cloneNode(true));
          }
        }
      }
      for (const property of Array.from(groupLabels.children)) {
        if (property.localName !== "dLbl" && !ownDefaults.has(property.localName)) labels.appendChild(property.cloneNode(true));
      }
    }
    overrides.forEach((node) => node.remove());
  }
  for (const [ordinal, series] of seriesNodes.entries()) {
    const pointMap = pointMaps[ordinal];
    const inverse = new Map(pointMap.map((original, index) => [original, index]));
    const remap = (node, attribute) => {
      const original = Number(node.getAttribute(attribute));
      const index = inverse.get(original);
      if (index === void 0) node.remove();
      else node.setAttribute(attribute, String(index));
    };
    for (const node of Array.from(series.getElementsByTagNameNS(chartNamespace, "*"))) {
      if (node.localName !== "dPt" && node.localName !== "dLbl") continue;
      remapPointStyle(node, inverse);
    }
    for (const channel of Array.from(series.children)) {
      if (!["cat", "val", "xVal", "yVal", "bubbleSize", "errBars"].includes(channel.localName)) continue;
      for (const node of Array.from(channel.getElementsByTagNameNS(chartNamespace, "pt"))) remap(node, "idx");
      for (const node of Array.from(channel.getElementsByTagNameNS(chartNamespace, "ptCount"))) node.setAttribute("val", String(pointMap.length));
    }
    if (series.parentElement?.localName === "ofPieChart") {
      for (const node of Array.from(series.parentElement.getElementsByTagNameNS(chartNamespace, "secondPiePt"))) remap(node, "val");
    }
  }
  return {
    xml: serializeWorkbookXml(document),
    data: { ...data, series: data.series.map((series, index) => ({ ...series, points: projectPoints(series.points, excluded[index] ?? /* @__PURE__ */ new Set()) })) },
    pointMaps
  };
}

// src/chart-worker-render.ts
function renderChartInWorker(renderer, chart, source, width, height) {
  try {
    const data = {
      title: chart.title,
      series: (source.sourceSeries ?? chart.series).map((series, ordinal) => {
        const chartType = source.seriesTypes?.[ordinal] ?? source.kind;
        const xy = chartType === "scatter" || chartType === "bubble";
        const indexedX = source.indexedXSeries?.[ordinal] === true;
        const numericCategories = series.raw?.chartCategoryNumericValues;
        const useNumericCategories = source.dateCategorySeries?.[ordinal] === true || xy && !indexedX;
        const hierarchy = series.raw?.chartExHierarchyCategories;
        const colorStrings = series.raw?.chartExColorStrings;
        const classicHierarchy = series.raw?.chartHierarchyCategories;
        return {
          chartType,
          name: series.name,
          points: Array.from({ length: Math.max(series.values.length, indexedX ? 0 : series.categories.length, series.bubbleSizes?.length ?? 0) }, (_, index) => {
            const value = series.values[index];
            const label = useNumericCategories && numericCategories?.[index] != null ? numericCategories[index] : series.categories[index];
            const bubble = series.bubbleSizes?.[index];
            return {
              index,
              value: xy ? void 0 : colorStrings?.[index] ?? (value == null ? null : String(value)),
              x: indexedX ? String(index + 1) : xy && label != null ? String(label) : void 0,
              y: xy && value != null ? String(value) : void 0,
              bubbleSize: bubble == null ? void 0 : String(bubble),
              categories: xy ? [] : hierarchy?.[index]?.length ? [...hierarchy[index]].reverse().map((label2, level) => ({ level, label: label2 })) : classicHierarchy?.[index]?.length ? classicHierarchy[index] : series.categories.length || series.categoriesRef?.formula ? [{ level: 0, label: label == null ? "" : String(label) }] : []
            };
          })
        };
      })
    };
    const projected = projectChartData(source.xml, data, (source.sourceSeries ?? chart.series).map((series) => series.raw?.chartExcludedPointIndices));
    const svg = renderer.renderChart(projected.xml, {
      themeColors: source.themeColors,
      themeXml: source.themeXml,
      themeOverrideXml: source.themeOverrideXml,
      styleXml: source.styleXml,
      colorStyleXml: source.colorStyleXml,
      images: source.images,
      drawings: source.drawings,
      width,
      height,
      interactive: true,
      spreadsheetDefaults: true,
      fontFamily: chart.fontFamily,
      data: projected.data
    });
    return { svg, pointMaps: projected.pointMaps };
  } catch {
    return null;
  }
}
export {
  renderChartInWorker
};
//# sourceMappingURL=chart-worker-render-64S3S5LZ.js.map