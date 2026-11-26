import {
  renderChartInWorker
} from "./chunk-TT4ZO6VU.js";
import {
  useXlsxMessages
} from "./chunk-MNIFKMIL.js";
import {
  officeFontFallback
} from "./chunk-QXXS4J36.js";
import "./chunk-67TEHWH5.js";

// src/shared-chart.tsx
import * as React2 from "react";

// src/chart-interaction.tsx
import * as React from "react";
function resolveChartElementTarget(target) {
  if (!(target instanceof Element)) {
    return null;
  }
  if (target.closest("[data-chart-effect]")) {
    return null;
  }
  return target.closest("[data-xlsx-chart-series-index],[data-xlsx-chart-element-kind='legend']");
}
function resolveChartSelectionFromTarget(chart, target, selectedChartElement) {
  const element = resolveChartElementTarget(target);
  if (!element) {
    return { chartId: chart.id, kind: "chart" };
  }
  if (element.dataset.xlsxChartElementKind === "legend") {
    return { chartId: chart.id, kind: "legend" };
  }
  const seriesIndex = Number(element.dataset.xlsxChartSeriesIndex);
  if (!Number.isInteger(seriesIndex) || seriesIndex < 0 || seriesIndex >= chart.series.length) {
    return null;
  }
  const series = chart.series[seriesIndex];
  if (!series) {
    return null;
  }
  const rawPointIndex = element.dataset.xlsxChartPointIndex;
  const rawElementKind = element.dataset.xlsxChartElementKind;
  if (rawElementKind === "legendEntry" && !(selectedChartElement?.chartId === chart.id && (selectedChartElement.kind === "legend" || selectedChartElement.kind === "legendEntry"))) {
    return { chartId: chart.id, kind: "legend" };
  }
  const pointIndex = rawPointIndex == null || rawPointIndex === "" ? null : Number(rawPointIndex);
  const hasPoint = pointIndex != null && Number.isInteger(pointIndex) && pointIndex >= 0;
  const sameSelectedSeries = selectedChartElement?.chartId === chart.id && selectedChartElement.kind !== "chart" && selectedChartElement.kind !== "legend" && selectedChartElement.seriesIndex === seriesIndex;
  if (hasPoint && rawElementKind !== "legendEntry" && sameSelectedSeries) {
    return {
      chartId: chart.id,
      kind: "point",
      pointIndex,
      seriesId: series.id,
      seriesIndex
    };
  }
  if (rawElementKind === "legendEntry") {
    const rawLegendIndex = element.dataset.xlsxChartLegendIndex;
    const legendIndex = rawLegendIndex == null || rawLegendIndex === "" ? void 0 : Number(rawLegendIndex);
    return {
      chartId: chart.id,
      kind: "legendEntry",
      seriesId: series.id,
      seriesIndex,
      ...legendIndex != null && Number.isInteger(legendIndex) && legendIndex >= 0 ? { legendIndex } : {}
    };
  }
  return {
    chartId: chart.id,
    kind: "series",
    seriesId: series.id,
    seriesIndex
  };
}
function useChartEvents({
  chart,
  onChartElementPointerDown,
  onChartElementDoubleClick,
  selectedChartElement
}) {
  const handlePointerDown = React.useCallback((event) => {
    const selection = resolveChartSelectionFromTarget(chart, event.target, selectedChartElement);
    if (!selection) {
      return;
    }
    if (resolveChartElementTarget(event.target)) {
      event.stopPropagation();
    }
    onChartElementPointerDown?.(selection, event);
  }, [chart, onChartElementPointerDown, selectedChartElement]);
  const handleDoubleClick = React.useCallback((event) => {
    const selection = resolveChartSelectionFromTarget(chart, event.target, selectedChartElement);
    if (!selection) {
      return;
    }
    if (resolveChartElementTarget(event.target)) {
      event.stopPropagation();
    }
    onChartElementDoubleClick?.(selection, event);
  }, [chart, onChartElementDoubleClick, selectedChartElement]);
  return { handlePointerDown, handleDoubleClick };
}

// src/chart-selection.ts
var svgNamespace = "http://www.w3.org/2000/svg";
var geometrySelector = "path,rect,circle,ellipse,line,polyline,polygon";
var ownerSelector = "[data-chart-series]";
var selectionColor = "#3276b5";
var selectionHandleFill = "#cce7fc";
function keepHandleScreenSized(handle, owner, point) {
  const screen = owner.getScreenCTM();
  if (!screen) return;
  const inverse = screen.inverse();
  const { a, b, c, d } = inverse;
  if (![a, b, c, d].every(Number.isFinite)) return;
  const x = point.x - a * point.x - c * point.y;
  const y = point.y - b * point.x - d * point.y;
  handle.setAttribute("transform", `matrix(${a} ${b} ${c} ${d} ${x} ${y})`);
}
function selectionBounds(node) {
  const matrix = node.getScreenCTM();
  if (!matrix) return null;
  const inverse = matrix.inverse();
  const shapes = node.matches(geometrySelector + ",text,image") ? [node] : Array.from(node.querySelectorAll(geometrySelector + ",text,image"));
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const shape of shapes) {
    if (shape.closest("defs,[data-chart-effect]")) continue;
    try {
      const transform = shape.getScreenCTM();
      if (!transform) continue;
      const local = inverse.multiply(transform);
      const box = shape.getBBox();
      for (const [x, y] of [
        [box.x, box.y],
        [box.x + box.width, box.y],
        [box.x, box.y + box.height],
        [box.x + box.width, box.y + box.height]
      ]) {
        const p = new DOMPoint(x, y).matrixTransform(local);
        if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) continue;
        left = Math.min(left, p.x);
        top = Math.min(top, p.y);
        right = Math.max(right, p.x);
        bottom = Math.max(bottom, p.y);
      }
    } catch {
    }
  }
  if (!Number.isFinite(left)) return null;
  return { x: left, y: top, width: right - left, height: bottom - top };
}
function projectedOutline(node) {
  const matrix = node.getScreenCTM();
  if (!matrix) return [];
  let inverse;
  try {
    inverse = matrix.inverse();
  } catch {
    return [];
  }
  const points = [];
  for (const shape of node.querySelectorAll(geometrySelector)) {
    if (shape.closest("defs,[data-chart-effect]") || shape.getAttribute("fill") === "transparent") continue;
    const transform = shape.getScreenCTM();
    if (!transform) continue;
    const local = inverse.multiply(transform);
    const append = (x, y) => {
      const p = new DOMPoint(x, y).matrixTransform(local);
      if (Number.isFinite(p.x) && Number.isFinite(p.y)) points.push({ x: p.x, y: p.y });
    };
    if (shape instanceof SVGPolygonElement || shape instanceof SVGPolylineElement) {
      for (let i = 0; i < shape.points.numberOfItems; i++) {
        const p = shape.points.getItem(i);
        append(p.x, p.y);
      }
    } else {
      try {
        const length = shape.getTotalLength();
        const count = Math.min(128, Math.max(16, Math.ceil(length / 4)));
        for (let i = 0; i <= count; i++) {
          const p = shape.getPointAtLength(length * i / count);
          append(p.x, p.y);
        }
      } catch {
      }
    }
  }
  const vertices = Array.from(new Map(points.map((p) => [p.x.toFixed(3) + ":" + p.y.toFixed(3), p])).values());
  if (vertices.length <= 16) return vertices;
  vertices.sort((a, b) => a.x - b.x || a.y - b.y);
  const turn = (a, b, c) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  const hull = [];
  for (const p of vertices) {
    while (hull.length >= 2 && turn(hull[hull.length - 2], hull[hull.length - 1], p) <= 0.01) hull.pop();
    hull.push(p);
  }
  const lower = hull.length;
  for (let i = vertices.length - 2; i >= 0; i--) {
    const p = vertices[i];
    while (hull.length > lower && turn(hull[hull.length - 2], hull[hull.length - 1], p) <= 0.01) hull.pop();
    hull.push(p);
  }
  if (hull.length > 1) hull.pop();
  const stride = Math.max(1, Math.ceil(hull.length / 16));
  return hull.filter((_, i) => i % stride === 0);
}
function matchesSelection(node, selected) {
  if (Number(node.getAttribute("data-chart-series")) !== selected.seriesIndex) return false;
  const legend = node.getAttribute("data-chart-kind") === "legendEntry";
  if (selected.kind === "legendEntry") return legend && (selected.legendIndex == null || Number(node.getAttribute("data-xlsx-chart-legend-index")) === selected.legendIndex);
  if (legend) return false;
  return selected.kind !== "point" || node.hasAttribute("data-chart-point") && Number(node.getAttribute("data-chart-point")) === selected.pointIndex;
}
function wholeLegendHandles(svg) {
  const matrix = svg.getScreenCTM();
  if (!matrix) return null;
  const inverse = matrix.inverse();
  const points = [];
  for (const node of svg.querySelectorAll("[data-xlsx-chart-element-kind='legend'],[data-xlsx-chart-element-kind='legendEntry']")) {
    try {
      const transform = node.getScreenCTM();
      if (!transform) continue;
      const local = inverse.multiply(transform);
      const box = selectionBounds(node);
      if (!box) continue;
      for (const [x, y] of [
        [box.x, box.y],
        [box.x + box.width, box.y],
        [box.x, box.y + box.height],
        [box.x + box.width, box.y + box.height]
      ]) {
        const p = new DOMPoint(x, y).matrixTransform(local);
        if (Number.isFinite(p.x) && Number.isFinite(p.y)) points.push(p);
      }
    } catch {
    }
  }
  if (!points.length) return null;
  const left = Math.min(...points.map((p) => p.x)) - 2;
  const right = Math.max(...points.map((p) => p.x)) + 2;
  const top = Math.min(...points.map((p) => p.y)) - 2;
  const bottom = Math.max(...points.map((p) => p.y)) + 2;
  const middleX = (left + right) / 2;
  const middleY = (top + bottom) / 2;
  const group = document.createElementNS(svgNamespace, "g");
  group.setAttribute("data-xlsx-chart-selection-handles", "legend");
  group.setAttribute("pointer-events", "none");
  const outline = document.createElementNS(svgNamespace, "rect");
  outline.setAttribute("x", String(left));
  outline.setAttribute("y", String(top));
  outline.setAttribute("width", String(right - left));
  outline.setAttribute("height", String(bottom - top));
  outline.setAttribute("fill", "none");
  outline.setAttribute("stroke", "#a6a6a6");
  outline.setAttribute("stroke-width", "0.75");
  outline.setAttribute("vector-effect", "non-scaling-stroke");
  group.append(outline);
  for (const [x, y] of [
    [left, top],
    [middleX, top],
    [right, top],
    [left, middleY],
    [right, middleY],
    [left, bottom],
    [middleX, bottom],
    [right, bottom]
  ]) {
    const handle = document.createElementNS(svgNamespace, "rect");
    handle.setAttribute("x", String(x - 3));
    handle.setAttribute("y", String(y - 3));
    handle.setAttribute("width", "6");
    handle.setAttribute("height", "6");
    handle.setAttribute("fill", "#ffffff");
    handle.setAttribute("stroke", "#a6a6a6");
    handle.setAttribute("stroke-width", "0.75");
    handle.setAttribute("vector-effect", "non-scaling-stroke");
    keepHandleScreenSized(handle, svg, { x, y });
    group.append(handle);
  }
  return group;
}
function isPointAnchor(node, owner) {
  return node.localName === "circle" && node.getAttribute("fill") === "transparent" && owner.getAttribute("data-chart-kind") !== "bubble";
}
function outlineGeometry(node) {
  const outline = node.cloneNode(false);
  for (const { name } of Array.from(outline.attributes)) {
    if (name === "id" || name === "style" || name === "filter" || name.startsWith("data-")) outline.removeAttribute(name);
  }
  outline.setAttribute("data-xlsx-chart-selection-outline", "");
  outline.setAttribute("fill", "none");
  outline.setAttribute("stroke", selectionColor);
  outline.setAttribute("stroke-width", "1.25");
  outline.setAttribute("stroke-opacity", "1");
  outline.setAttribute("stroke-linejoin", "round");
  outline.setAttribute("stroke-linecap", "round");
  outline.removeAttribute("stroke-dasharray");
  outline.setAttribute("opacity", "1");
  outline.setAttribute("pointer-events", "none");
  outline.setAttribute("vector-effect", "non-scaling-stroke");
  return outline;
}
function pointHandles(node, points) {
  const group = document.createElementNS(svgNamespace, "g");
  group.setAttribute("data-xlsx-chart-selection-handles", "");
  group.setAttribute("pointer-events", "none");
  const clip = node.getAttribute("clip-path");
  if (clip) group.setAttribute("clip-path", clip);
  for (const point of points) {
    const handle = document.createElementNS(svgNamespace, "circle");
    handle.setAttribute("cx", String(point.x));
    handle.setAttribute("cy", String(point.y));
    handle.setAttribute("r", "3");
    handle.setAttribute("fill", selectionHandleFill);
    handle.setAttribute("stroke", selectionColor);
    handle.setAttribute("stroke-width", "1.1");
    handle.setAttribute("vector-effect", "non-scaling-stroke");
    keepHandleScreenSized(handle, node, point);
    group.append(handle);
  }
  return group;
}
function ownerHandles(node, is3d) {
  const kind = node.getAttribute("data-chart-kind");
  const x = Number(node.getAttribute("data-chart-x"));
  const y = Number(node.getAttribute("data-chart-y"));
  if ((kind === "point" || kind === "surfacePoint") && node.hasAttribute("data-chart-x") && node.hasAttribute("data-chart-y") && Number.isFinite(x) && Number.isFinite(y)) {
    return pointHandles(node, [{ x, y }]);
  }
  if (is3d && (kind === "bar3D" || kind === "slice")) {
    const outline = projectedOutline(node);
    if (outline.length) return pointHandles(node, outline);
  }
  try {
    const box = selectionBounds(node);
    if (!box) return null;
    if (![box.x, box.y, box.width, box.height].every(Number.isFinite) || box.width === 0 && box.height === 0) return null;
    return pointHandles(node, [
      { x: box.x, y: box.y },
      { x: box.x + box.width, y: box.y },
      { x: box.x, y: box.y + box.height },
      { x: box.x + box.width, y: box.y + box.height }
    ]);
  } catch {
    return null;
  }
}
function placeHandles(svg, node, handles) {
  const rootMatrix = svg.getScreenCTM();
  const nodeMatrix = node.getScreenCTM();
  if (!rootMatrix || !nodeMatrix) return false;
  const matrix = rootMatrix.inverse().multiply(nodeMatrix);
  if (![matrix.a, matrix.b, matrix.c, matrix.d, matrix.e, matrix.f].every(Number.isFinite)) return false;
  handles.setAttribute("transform", `matrix(${matrix.a} ${matrix.b} ${matrix.c} ${matrix.d} ${matrix.e} ${matrix.f})`);
  svg.append(handles);
  return true;
}
function applyChartSelection(svg, chartId, selected, is3d = false) {
  if (!selected || selected.chartId !== chartId || selected.kind === "chart") return;
  if (selected.kind === "legend") {
    const handles = wholeLegendHandles(svg);
    if (!handles) return;
    svg.append(handles);
    svg.setAttribute("data-xlsx-chart-selection", "legend");
    return () => {
      handles.remove();
      svg.removeAttribute("data-xlsx-chart-selection");
    };
  }
  const overlays = [];
  const owners = Array.from(svg.querySelectorAll(ownerSelector)).filter((node) => matchesSelection(node, selected));
  const geometry = Array.from(svg.querySelectorAll(geometrySelector));
  const ownersWithGeometry = /* @__PURE__ */ new Set();
  for (const node of geometry) {
    if (node.closest("defs,[data-chart-effect]")) continue;
    const owner = node.closest(ownerSelector);
    if (!owner || !matchesSelection(owner, selected)) continue;
    ownersWithGeometry.add(owner);
    if (is3d || owner.getAttribute("data-chart-kind") === "surfacePoint" || isPointAnchor(node, owner)) continue;
    const outline = outlineGeometry(node);
    node.after(outline);
    overlays.push(outline);
  }
  const handled = /* @__PURE__ */ new Set();
  for (const node of owners) {
    if (!ownersWithGeometry.has(node) && selected.kind !== "legendEntry") continue;
    const point = node.getAttribute("data-chart-point");
    const kind = node.getAttribute("data-chart-kind");
    if (point == null && selected.kind !== "legendEntry" && node.querySelector("[data-chart-point]")) continue;
    if ((kind === "point" || kind === "surfacePoint") && point != null) {
      const key = node.getAttribute("data-chart-series") + ":" + point;
      if (handled.has(key)) continue;
      handled.add(key);
    }
    const handles = ownerHandles(node, is3d);
    if (!handles) continue;
    if (!placeHandles(svg, node, handles)) continue;
    overlays.push(handles);
  }
  svg.setAttribute("data-xlsx-chart-selection", selected.kind);
  return () => {
    for (const overlay of overlays) overlay.remove();
    svg.removeAttribute("data-xlsx-chart-selection");
  };
}

// src/shared-chart.tsx
import { Fragment, jsx } from "react/jsx-runtime";
var svgNamespace2 = "http://www.w3.org/2000/svg";
var allowedElements = /* @__PURE__ */ new Set([
  "svg",
  "g",
  "defs",
  "clipPath",
  "rect",
  "circle",
  "ellipse",
  "path",
  "line",
  "polyline",
  "polygon",
  "title",
  "desc",
  "text",
  "tspan",
  "linearGradient",
  "radialGradient",
  "stop",
  "pattern",
  "image",
  "filter",
  "feGaussianBlur",
  "feFlood",
  "feComposite",
  "feMorphology",
  "feDiffuseLighting",
  "feSpecularLighting",
  "feDistantLight",
  "use",
  "mask",
  "marker",
  "feColorMatrix",
  "feComponentTransfer",
  "feFuncR",
  "feFuncG",
  "feFuncB",
  "feFuncA",
  "feOffset",
  "feBlend"
]);
var plainAttributes = /* @__PURE__ */ new Set([
  "x",
  "y",
  "width",
  "height",
  "x1",
  "x2",
  "y1",
  "y2",
  "cx",
  "cy",
  "fx",
  "fy",
  "r",
  "rx",
  "ry",
  "fr",
  "viewBox",
  "preserveAspectRatio",
  "transform",
  "d",
  "points",
  "font-family",
  "font-weight",
  "font-style",
  "font-size",
  "font-style",
  "text-decoration",
  "text-anchor",
  "dominant-baseline",
  "stroke-linecap",
  "stroke-linejoin",
  "stroke-width",
  "stroke-dasharray",
  "stroke-miterlimit",
  "opacity",
  "fill-opacity",
  "stroke-opacity",
  "fill-rule",
  "clip-rule",
  "shape-rendering",
  "offset",
  "stop-opacity",
  "gradientUnits",
  "gradientTransform",
  "patternUnits",
  "patternContentUnits",
  "patternTransform",
  "color-interpolation",
  "maskUnits",
  "maskContentUnits",
  "markerUnits",
  "markerWidth",
  "markerHeight",
  "refX",
  "refY",
  "orient",
  "overflow",
  "xml:space",
  "dx",
  "dy",
  "type",
  "mode",
  "values",
  "slope",
  "intercept",
  "tableValues",
  "amplitude",
  "exponent",
  "filterUnits",
  "in",
  "in2",
  "result",
  "stdDeviation",
  "flood-color",
  "flood-opacity",
  "operator",
  "color-interpolation-filters",
  "radius",
  "surfaceScale",
  "diffuseConstant",
  "lighting-color",
  "specularConstant",
  "specularExponent",
  "azimuth",
  "elevation",
  "k1",
  "k2",
  "k3",
  "k4",
  "pointer-events",
  "data-chart-kind",
  "data-chart-series",
  "data-chart-point",
  "data-chart-x",
  "data-chart-y",
  "data-chart-effect",
  "data-chart-drawing"
]);
function safeChartSvg(markup, prefix, seriesCount, seriesMap, selectableSeries = true, pointMaps, depth = 0) {
  if (depth > 3 || markup.length > 128 * 1024 * 1024) return null;
  const svg = new DOMParser().parseFromString(markup, "image/svg+xml").documentElement;
  if (svg.localName !== "svg" || svg.namespaceURI !== svgNamespace2) return null;
  let legendIndex = 0;
  let imageIndex = 0;
  const ids = new Set(Array.from(svg.querySelectorAll("[id]"), (node) => node.id));
  for (const node of [svg, ...Array.from(svg.querySelectorAll("*"))]) {
    if (node.namespaceURI !== svgNamespace2 || !allowedElements.has(node.localName)) return null;
    for (const { name, value } of Array.from(node.attributes)) {
      if (name === "font-family") {
        const families = value.split(",").map((family) => family.trim());
        const unquote = (family) => family.replace(/^["']|["']$/g, "");
        const fallback = officeFontFallback(unquote(families[0] ?? ""));
        if (fallback && !families.some((family) => unquote(family) === fallback)) {
          families.splice(1, 0, JSON.stringify(fallback));
          node.setAttribute(name, families.join(", "));
        }
        continue;
      }
      if (plainAttributes.has(name) || name === "xmlns") continue;
      if (name === "id" && /^[\w-]+$/.test(value)) {
        node.setAttribute(name, prefix + value);
        continue;
      }
      if ((name === "href" || name === "xlink:href") && node.localName === "image" && /^data:image\/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/]+={0,2}$/.test(value)) {
        if (name !== "href") {
          node.removeAttribute(name);
          node.setAttribute("href", value);
        }
        continue;
      }
      if ((name === "href" || name === "xlink:href") && node.localName === "image" && value.startsWith("data:image/svg+xml;base64,")) {
        try {
          const bytes = Uint8Array.from(atob(value.slice("data:image/svg+xml;base64,".length)), (character) => character.charCodeAt(0));
          const nested = safeChartSvg(new TextDecoder().decode(bytes), `${prefix}image${imageIndex++}-`, 0, void 0, false, void 0, depth + 1);
          if (!nested) return null;
          const serialized = new TextEncoder().encode(new XMLSerializer().serializeToString(nested));
          const chunks = [];
          for (let offset = 0; offset < serialized.length; offset += 32768) chunks.push(String.fromCharCode(...serialized.subarray(offset, offset + 32768)));
          node.removeAttribute(name);
          node.setAttribute("href", `data:image/svg+xml;base64,${btoa(chunks.join(""))}`);
          continue;
        } catch {
          return null;
        }
      }
      if ((name === "href" || name === "xlink:href") && /^(linearGradient|radialGradient|use)$/.test(node.localName) && /^#[\w-]+$/.test(value) && ids.has(value.slice(1))) {
        node.removeAttribute(name);
        node.setAttribute("href", "#" + prefix + value.slice(1));
        continue;
      }
      if (["fill", "stroke", "stop-color", "clip-path", "filter", "mask", "marker-start", "marker-mid", "marker-end"].includes(name)) {
        const local = /^url\(#([\w-]+)\)$/.exec(value);
        if (local && ids.has(local[1])) {
          node.setAttribute(name, "url(#" + prefix + local[1] + ")");
          continue;
        }
        if (/^(?:#[\da-f]{3,8}|[a-z]+)$/i.test(value)) continue;
      }
      node.removeAttribute(name);
    }
    if (node.closest("defs,[data-chart-effect],[data-chart-drawing]")) {
      node.removeAttribute("data-chart-series");
      node.removeAttribute("data-chart-point");
      node.removeAttribute("data-chart-kind");
      node.style.pointerEvents = "none";
      continue;
    }
    if (node.getAttribute("data-chart-kind") === "legend" || node.getAttribute("data-chart-kind") === "legendEntry") {
      node.setAttribute("data-xlsx-chart-legend-index", String(legendIndex++));
    }
    if (node.getAttribute("data-chart-kind") === "legend") {
      node.setAttribute("data-xlsx-chart-element-kind", "legend");
      node.style.cursor = "pointer";
      node.style.pointerEvents = "all";
    }
    if (node.hasAttribute("data-chart-series")) {
      if (!selectableSeries && node.getAttribute("data-chart-kind") === "legendEntry") {
        node.setAttribute("data-xlsx-chart-element-kind", "legend");
        node.style.cursor = "pointer";
        node.style.pointerEvents = "all";
      }
      const sourceSeries = Number(node.getAttribute("data-chart-series"));
      const series = seriesMap ? seriesMap[sourceSeries] : sourceSeries;
      if (!selectableSeries || !Number.isInteger(sourceSeries) || sourceSeries < 0 || series == null || !Number.isInteger(series) || series < 0 || series >= seriesCount) {
        node.removeAttribute("data-chart-series");
        node.removeAttribute("data-chart-point");
        node.removeAttribute("data-chart-kind");
        continue;
      }
      node.setAttribute("data-chart-series", String(series));
      node.setAttribute("data-xlsx-chart-series-index", String(series));
      const point = node.getAttribute("data-chart-point");
      const originalPoint = point != null && point !== "" && Number.isInteger(Number(point)) && Number(point) >= 0 ? pointMaps ? pointMaps[sourceSeries]?.[Number(point)] : Number(point) : void 0;
      if (originalPoint != null && Number.isInteger(originalPoint) && originalPoint >= 0) {
        node.setAttribute("data-chart-point", String(originalPoint));
        node.setAttribute("data-xlsx-chart-point-index", String(originalPoint));
      } else {
        node.removeAttribute("data-chart-point");
      }
      const kind = node.getAttribute("data-chart-kind");
      if (kind === "legendEntry") node.setAttribute("data-xlsx-chart-element-kind", kind);
      const style = node.style;
      style.cursor = "pointer";
      style.pointerEvents = "all";
    }
  }
  return svg;
}
function SharedChartSvg(props) {
  const messages = useXlsxMessages();
  const { chart, rect, renderer, source, selectedChartElement, fallback, renderChartAsync } = props;
  const id = React2.useId();
  const width = Math.max(1, rect.width);
  const height = Math.max(1, rect.height);
  const [rendered, setRendered] = React2.useState(null);
  const renderChartRef = React2.useRef(chart);
  const previous = renderChartRef.current;
  if (Object.keys(chart).some((key) => !["anchor", "zIndex"].includes(key) && chart[key] !== previous[key]) || Object.keys(previous).some((key) => !["anchor", "zIndex"].includes(key) && !(key in chart))) renderChartRef.current = chart;
  const renderChart = renderChartRef.current;
  const isPending = rendered?.chart !== renderChart || rendered?.source !== source || rendered?.width !== width || rendered?.height !== height;
  const svg = rendered?.chart.id === chart.id ? rendered.svg : null;
  React2.useEffect(() => {
    let active = true;
    const request = renderer ? Promise.resolve(renderChartInWorker(renderer, renderChart, source, width, height)) : renderChartAsync?.(renderChart, source, width, height) ?? Promise.resolve(null);
    void request.then((result) => {
      if (!active) return;
      const nextSvg = result?.svg ? safeChartSvg(
        result.svg,
        "oc-" + id.replace(/[^\w-]/g, "") + "-",
        chart.series.length,
        source.sourceSeries?.map((series) => chart.series.findIndex((candidate) => candidate.id === series.id)),
        chart.chartType !== "Surface",
        result.pointMaps
      ) : null;
      setRendered({ chart: renderChart, source, width, height, svg: nextSvg });
    }).catch(() => {
      if (active) setRendered({ chart: renderChart, source, width, height, svg: null });
    });
    return () => {
      active = false;
    };
  }, [renderer, renderChart, source, width, height, id, renderChartAsync]);
  const graphics = React2.useRef(null);
  React2.useLayoutEffect(() => {
    if (!graphics.current || !svg) return;
    if (graphics.current.firstChild !== svg) graphics.current.replaceChildren(svg);
    let cleanup = applyChartSelection(svg, chart.id, selectedChartElement, chart.is3d);
    const viewport = graphics.current.ownerSVGElement;
    if (!viewport || !selectedChartElement || selectedChartElement.chartId !== chart.id || selectedChartElement.kind === "chart" || typeof ResizeObserver === "undefined") return cleanup;
    const observer = new ResizeObserver(() => {
      cleanup?.();
      cleanup = applyChartSelection(svg, chart.id, selectedChartElement, chart.is3d);
    });
    observer.observe(viewport);
    return () => {
      observer.disconnect();
      cleanup?.();
    };
  }, [svg, chart.id, chart.is3d, selectedChartElement]);
  const { handlePointerDown, handleDoubleClick } = useChartEvents(props);
  if (!svg && isPending) return /* @__PURE__ */ jsx(Fragment, { children: props.loadingFallback?.("renderer") ?? /* @__PURE__ */ jsx("div", { "aria-busy": "true" }) });
  if (!svg) return /* @__PURE__ */ jsx("div", { "data-xlsx-chart-fallback": "unsupported", style: { width: "100%", height: "100%" }, children: fallback });
  return /* @__PURE__ */ jsx(
    "svg",
    {
      "aria-label": chart.title ?? chart.name ?? messages.chart,
      "data-xlsx-chart-renderer": "office-charts",
      onDoubleClick: handleDoubleClick,
      onPointerDown: handlePointerDown,
      role: "img",
      style: { display: "block", height: "100%", pointerEvents: "auto", width: "100%" },
      viewBox: `0 0 ${width} ${height}`,
      children: /* @__PURE__ */ jsx("g", { ref: graphics })
    }
  );
}
export {
  SharedChartSvg
};
//# sourceMappingURL=shared-chart-24MCGSFJ.js.map