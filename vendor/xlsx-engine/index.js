import {
  XLSX_MAX_COLUMNS,
  XLSX_MAX_ROWS,
  applyChartSeriesFormula,
  buildChartSeriesFormula,
  emuToPixels,
  findIntersectingPivot,
  loadSpreadsheetFonts,
  loadWorkbookChartAssets,
  loadWorkbookImageAssets,
  localizeCellNumber,
  parseLocaleNumber,
  parseXlsxRange,
  pivotWorkbook,
  pxToOfficeColumnWidth,
  pxToSheetColumnWidth,
  readPivotTables,
  rectToImageAnchor,
  refreshChartRenderSource,
  refreshWorkbookFormControls,
  resizeImageRect,
  resolveContentSheetAxisPixels,
  resolveRenderedSheetAxisPixels,
  resolveSheetColumnWidthPixels,
  resolveSheetRowHeightPixels,
  resolveWorkbookColor,
  resolveWorkbookFillStyle,
  resolveWorksheetDefaultColumnWidthPixels,
  resolveWorksheetDefaultRowHeightPixels,
  resolveWorksheetMergeMetadata,
  restoreWorkerImageBlobs,
  revokeWorkbookImageAssets,
  safeCalculate,
  tryRecalculate,
  updateWorkbookChartAnchor,
  updateWorkbookChartDefinition,
  updateWorkbookImageAnchor,
  xlsxAnchorToDukeDrawingAnchor
} from "./chunk-2TLD35UF.js";
import {
  formatMessage,
  mergeMessages,
  resolveMessages,
  useXlsxMessages
} from "./chunk-MNIFKMIL.js";
import "./chunk-QXXS4J36.js";
import {
  configureWorkbookArchiveDecoder,
  configureWorkbookXmlDecoder,
  parseWorkbookXml,
  restoreWorkbookXmlRecords,
  serializeWorkbookXml
} from "./chunk-67TEHWH5.js";

// src/selection-ranges.ts
function resolveFreezePanesCell(activeCell, selection) {
  if (activeCell && selection && (activeCell.row < selection.start.row || activeCell.col < selection.start.col)) {
    return selection.start;
  }
  return activeCell;
}
function subtractRange(area, cut) {
  const top = Math.max(area.start.row, cut.start.row);
  const bottom = Math.min(area.end.row, cut.end.row);
  const left = Math.max(area.start.col, cut.start.col);
  const right = Math.min(area.end.col, cut.end.col);
  if (top > bottom || left > right) return [area];
  const remaining = [];
  if (area.start.row < top) remaining.push({ start: area.start, end: { row: top - 1, col: area.end.col } });
  if (bottom < area.end.row) remaining.push({ start: { row: bottom + 1, col: area.start.col }, end: area.end });
  if (area.start.col < left) remaining.push({ start: { row: top, col: area.start.col }, end: { row: bottom, col: left - 1 } });
  if (right < area.end.col) remaining.push({ start: { row: top, col: right + 1 }, end: { row: bottom, col: area.end.col } });
  return remaining;
}
function addSelectionRange(areas, range) {
  return [...areas.flatMap((area) => subtractRange(area, range)), range];
}
function clipboardBands(areas) {
  const first = areas[0];
  if (!first) return null;
  const sameExtent = (axis) => areas.every((area) => area.start[axis] === first.start[axis] && area.end[axis] === first.end[axis]);
  const bands = (axis, ranges) => ranges.map((range) => ({ start: range.start[axis], end: range.end[axis] })).sort((a, b) => a.start - b.start);
  if (sameExtent("col")) return { rows: bands("row", areas), cols: bands("col", [first]) };
  if (sameExtent("row")) return { rows: bands("row", [first]), cols: bands("col", areas) };
  return null;
}
function* bandIndices(bands) {
  let offset = 0;
  for (const band of bands) {
    for (let index = band.start; index <= band.end; index++) {
      yield { index, offset: offset++, remaining: band.end - index + 1 };
    }
  }
}

// src/read-only-layout.ts
function changedVisibilityRanges(existing, ranges, hidden, fromSelection) {
  if (!hidden && !existing.size) return [];
  let firstVisible = 0;
  if (!hidden && fromSelection) {
    while (existing.has(firstVisible)) firstVisible++;
  }
  const changed = [];
  for (const range of ranges) {
    const start = firstVisible > 0 && range.start === firstVisible ? 0 : range.start;
    for (let index = start; index <= range.end; index++) {
      if (existing.has(index) !== hidden) {
        changed.push({ start, end: range.end });
        break;
      }
    }
  }
  return changed;
}
function nextVisibleIndex(index, limit, isHidden) {
  let next = index;
  while (next < limit && isHidden(next)) next++;
  if (next < limit) return next;
  next = index - 1;
  while (next >= 0 && isHidden(next)) next--;
  return next;
}
function visibleAxis(hidden, max, originalIndices, originalSizes, overrides, defaultSize) {
  const indices = [];
  const sizes = [];
  let offset = 0;
  for (let index = 0; index <= max; index++) {
    const originalSize = originalIndices[offset] === index ? originalSizes[offset++] : void 0;
    if (hidden.has(index)) continue;
    indices.push(index);
    sizes.push(originalSize ?? overrides[index] ?? defaultSize);
  }
  return { indices, sizes };
}
function applyReadOnlyLayout(sheet, layout) {
  if (!layout) return sheet;
  const view = { ...sheet };
  if (layout.freezePanes !== void 0) view.freezePanes = layout.freezePanes;
  if (layout.hiddenRows) {
    const rows = visibleAxis(
      layout.hiddenRows,
      sheet.maxUsedRow,
      sheet.visibleRows,
      sheet.rowHeights,
      sheet.rowHeightOverridesPx,
      sheet.defaultRowHeightPx
    );
    view.hiddenRows = Array.from(layout.hiddenRows).sort((a, b) => a - b);
    view.visibleRows = rows.indices;
    view.rowHeights = rows.sizes;
    view.rowCount = rows.indices.length;
  }
  if (layout.hiddenCols) {
    const cols = visibleAxis(
      layout.hiddenCols,
      sheet.maxUsedCol,
      sheet.visibleCols,
      sheet.colWidths,
      sheet.colWidthOverridesPx,
      sheet.defaultColWidthPx
    );
    view.hiddenCols = Array.from(layout.hiddenCols).sort((a, b) => a - b);
    view.visibleCols = cols.indices;
    view.colWidths = cols.sizes;
    view.colCount = cols.indices.length;
  }
  return view;
}

// src/merged-range-lookup.ts
function createMergedRangeLookup(ranges) {
  const normalizedRanges = [];
  for (const range of ranges) {
    const startRow = Math.min(range.start.row, range.end.row);
    const endRow = Math.max(range.start.row, range.end.row);
    const startCol = Math.min(range.start.col, range.end.col);
    const endCol = Math.max(range.start.col, range.end.col);
    if (![startRow, endRow, startCol, endCol].every((value) => Number.isInteger(value) && value >= 0) || startRow === endRow && startCol === endCol) {
      continue;
    }
    normalizedRanges.push({
      end: { col: endCol, row: endRow },
      start: { col: startCol, row: startRow }
    });
  }
  normalizedRanges.sort((a, b) => a.start.row - b.start.row || a.start.col - b.start.col);
  const buildNode = (start, end) => {
    if (start >= end) return null;
    const middle = start + end >>> 1;
    const range = normalizedRanges[middle];
    const left = buildNode(start, middle);
    const right = buildNode(middle + 1, end);
    return {
      range,
      left,
      right,
      bounds: {
        start: {
          row: normalizedRanges[start].start.row,
          col: Math.min(range.start.col, left?.bounds.start.col ?? Infinity, right?.bounds.start.col ?? Infinity)
        },
        end: {
          row: Math.max(range.end.row, left?.bounds.end.row ?? -1, right?.bounds.end.row ?? -1),
          col: Math.max(range.end.col, left?.bounds.end.col ?? -1, right?.bounds.end.col ?? -1)
        }
      }
    };
  };
  const root = buildNode(0, normalizedRanges.length);
  const contains = (range, cell) => cell.row >= range.start.row && cell.row <= range.end.row && cell.col >= range.start.col && cell.col <= range.end.col;
  const find = (node, cell) => {
    if (!node || !contains(node.bounds, cell)) return null;
    if (contains(node.range, cell)) {
      return node.range;
    }
    return find(node.left, cell) ?? find(node.right, cell);
  };
  return (cell) => find(root, cell);
}

// src/drawing-clipboard.ts
import { strFromU8, strToU8, unzipSync } from "fflate";
var R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
var PKG = "http://schemas.openxmlformats.org/package/2006/relationships";
var XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing";
var CT = "http://schemas.openxmlformats.org/package/2006/content-types";
var relPath = (path) => path.replace(/([^/]+)$/, "_rels/$1.rels");
var resolve = (path, target) => new URL(target, `https://xlsx.invalid/${path}`).pathname.slice(1);
var elements = (node) => [node, ...Array.from(node.children).flatMap(elements)];
function findDrawingAnchor(assets, charts, kind, id) {
  const origin = kind === "image" ? assets.imageOriginsById.get(id) : charts.chartOriginsById.get(id);
  if (!origin || !assets.archive[origin.drawingPath]) return null;
  const document2 = parseWorkbookXml(strFromU8(assets.archive[origin.drawingPath]));
  const anchors = Array.from(document2.documentElement.children).filter((node) => /^(twoCell|oneCell|absolute)Anchor$/.test(node.localName));
  const candidates = kind === "image" ? anchors : anchors.filter((node) => elements(node).some((child2) => child2.localName === "chart"));
  const anchor = candidates[origin.anchorIndex];
  if (!anchor || elements(anchor).some((node) => node.localName === "grpSp")) return null;
  return { document: document2, anchor, anchors, origin };
}
function pasteDrawingClipboard(assets, clipboard, sheetIndex, name, placement) {
  const suffix = crypto.randomUUID().replaceAll("-", "");
  const origin = assets.sheetOrigins[sheetIndex] ??= { workbookSheetIndex: sheetIndex, attachments: [] };
  const attachment = origin.attachments[0] ?? { drawingPath: `xl/drawings/drawing-${suffix}.xml`, drawingRelsPath: null, mediaPaths: [] };
  if (!origin.attachments.length) origin.attachments.push(attachment);
  const path = attachment.drawingPath;
  const document2 = assets.archive[path] ? parseWorkbookXml(strFromU8(assets.archive[path])) : parseWorkbookXml(`<xdr:wsDr xmlns:xdr="${XDR}" xmlns:r="${R}"/>`);
  const relationships = assets.archive[relPath(path)] ? parseWorkbookXml(strFromU8(assets.archive[relPath(path)])) : parseWorkbookXml(`<Relationships xmlns="${PKG}"/>`);
  const types = parseWorkbookXml(strFromU8(assets.archive["[Content_Types].xml"]));
  const sourceTypes = parseWorkbookXml(strFromU8(clipboard.archive["[Content_Types].xml"]));
  const addType = (part, type) => {
    const node = types.createElementNS(CT, "Override");
    node.setAttribute("PartName", `/${part}`);
    node.setAttribute("ContentType", type);
    types.documentElement.appendChild(node);
  };
  if (!assets.archive[path]) addType(path, "application/vnd.openxmlformats-officedocument.drawing+xml");
  const copies = /* @__PURE__ */ new Map();
  const copyPart = (source) => {
    if (copies.has(source)) return copies.get(source);
    const bytes = clipboard.archive[source];
    if (!bytes) throw new Error("A drawing resource is missing.");
    const target = source.replace(/(\.[^/.]+)$/, `-${suffix}$1`);
    copies.set(source, target);
    assets.archive[target] = bytes.slice();
    assets.dirtyArchivePaths.add(target);
    const type = Array.from(sourceTypes.documentElement.children).find((node) => node.getAttribute("PartName") === `/${source}`) ?? Array.from(sourceTypes.documentElement.children).find((node) => node.getAttribute("Extension") === source.split(".").at(-1));
    if (type) addType(target, type.getAttribute("ContentType"));
    if (clipboard.archive[relPath(source)]) {
      const rels = parseWorkbookXml(strFromU8(clipboard.archive[relPath(source)]));
      for (const rel of Array.from(rels.documentElement.children)) if (rel.getAttribute("TargetMode") !== "External") {
        rel.setAttribute("Target", `/${copyPart(resolve(source, rel.getAttribute("Target")))}`);
      }
      assets.archive[relPath(target)] = strToU8(serializeWorkbookXml(rels));
      assets.dirtyArchivePaths.add(relPath(target));
    }
    return target;
  };
  const anchor = document2.importNode(parseWorkbookXml(clipboard.anchor).documentElement, true);
  let nextId = Math.max(0, ...elements(document2.documentElement).filter((node) => node.localName === "cNvPr").map((node) => Number(node.getAttribute("id")))) + 1;
  for (const node of elements(anchor)) if (node.localName === "cNvPr") {
    node.setAttribute("id", String(nextId++));
    node.setAttribute("name", name);
  }
  const usedIds = new Set(Array.from(relationships.documentElement.children).map((node) => node.getAttribute("Id")));
  const sourceRels = parseWorkbookXml(strFromU8(clipboard.archive[relPath(clipboard.drawingPath)]));
  const remapped = /* @__PURE__ */ new Map();
  for (const sourceRel of Array.from(sourceRels.documentElement.children)) {
    let index = 1;
    while (usedIds.has(`rId${index}`)) index++;
    const id = `rId${index}`;
    usedIds.add(id);
    const rel = relationships.importNode(sourceRel, true);
    rel.setAttribute("Id", id);
    if (rel.getAttribute("TargetMode") !== "External") rel.setAttribute("Target", `/${copyPart(resolve(clipboard.drawingPath, rel.getAttribute("Target")))}`);
    relationships.documentElement.appendChild(rel);
    remapped.set(sourceRel.getAttribute("Id"), id);
  }
  for (const node of elements(anchor)) {
    for (const attr of Array.from(node.attributes)) if (attr.namespaceURI === R && remapped.has(attr.value)) node.setAttributeNS(R, attr.name, remapped.get(attr.value));
  }
  if (placement?.kind === "one-cell") {
    const from = placement.from;
    const marker = `<xdr:from><xdr:col>${from.col}</xdr:col><xdr:colOff>${from.colOffsetEmu}</xdr:colOff><xdr:row>${from.row}</xdr:row><xdr:rowOff>${from.rowOffsetEmu}</xdr:rowOff></xdr:from>`;
    const container = parseWorkbookXml(`<xdr:oneCellAnchor xmlns:xdr="${XDR}">${marker}<xdr:ext cx="${placement.sizeEmu.cx}" cy="${placement.sizeEmu.cy}"/></xdr:oneCellAnchor>`).documentElement;
    for (const node of Array.from(anchor.children)) if (!["from", "to", "pos", "ext"].includes(node.localName)) container.appendChild(node);
    document2.documentElement.appendChild(document2.importNode(container, true));
  } else document2.documentElement.appendChild(anchor);
  for (const [entry, doc] of [[path, document2], [relPath(path), relationships], ["[Content_Types].xml", types]]) {
    assets.archive[entry] = strToU8(serializeWorkbookXml(doc));
    assets.dirtyArchivePaths.add(entry);
  }
}
var DRAWING_CLIPBOARD_TYPES = ["web data/shadow-workbook", "data/shadow-workbook"];
var RANGE_CLIPBOARD_TYPE = "application/x-react-xlsx-range+json";
function convertDrawingNamespace(source) {
  const document2 = source.ownerDocument;
  const node = document2.createElementNS(XDR, `xdr:${source.localName}`);
  for (const attr of Array.from(source.attributes)) {
    if (!attr.name.startsWith("xmlns")) node.setAttributeNS(attr.namespaceURI, attr.name, attr.value);
  }
  for (const child2 of Array.from(source.children)) {
    if (child2.localName === "txSp") {
      const body = Array.from(child2.children).find((node2) => node2.localName === "txBody");
      if (body) node.appendChild(convertDrawingNamespace(body));
      continue;
    }
    const structural = ["sp", "pic", "graphicFrame", "grpSp", "cxnSp", "nvGraphicFramePr", "nvPicPr", "nvSpPr", "nvGrpSpPr", "nvCxnSpPr", "cNvPr", "cNvGraphicFramePr", "cNvPicPr", "cNvSpPr", "cNvGrpSpPr", "cNvCxnSpPr", "spPr", "grpSpPr", "blipFill", "txBody", "style"].includes(child2.localName) || child2.localName === "xfrm" && source.localName === "graphicFrame";
    node.appendChild(structural ? convertDrawingNamespace(child2) : child2.cloneNode(true));
  }
  if (node.localName === "graphicFrame") {
    const transform = Array.from(node.children).find((child2) => child2.localName === "xfrm");
    if (transform) node.insertBefore(transform, node.children[1] ?? null);
  }
  return node;
}
function decodeExcelDrawingClipboard(input) {
  if (input.length > 32 * 1024 * 1024) return null;
  let value = {};
  let bytes;
  if (typeof input !== "string" && input[0] === 80 && input[1] === 75) bytes = input;
  else {
    try {
      const json = (typeof input === "string" ? input : strFromU8(input)).replace(/^\uFEFF/, "").replace(/\0+$/, "");
      const parsed = JSON.parse(json);
      if (!parsed || typeof parsed !== "object" || !("shadowWorkbookBase64" in parsed) || typeof parsed.shadowWorkbookBase64 !== "string") return null;
      value = parsed;
      bytes = Uint8Array.from(atob(parsed.shadowWorkbookBase64), (character) => character.charCodeAt(0));
    } catch {
      return null;
    }
  }
  let expandedSize = 0;
  const archive = unzipSync(bytes, { filter: (entry) => {
    expandedSize += entry.originalSize;
    if (expandedSize > 64 * 1024 * 1024) throw new Error("The copied drawing is too large.");
    return true;
  } });
  if (!archive["_rels/.rels"] || !archive["[Content_Types].xml"]) return null;
  const rootRels = parseWorkbookXml(strFromU8(archive["_rels/.rels"]));
  const drawingRel = Array.from(rootRels.documentElement.children).find((node) => node.getAttribute("Type") === `${R}/drawing` && node.getAttribute("TargetMode") !== "External");
  if (!drawingRel) return null;
  const drawingPath = resolve("", drawingRel.getAttribute("Target"));
  if (!archive[drawingPath]) return null;
  archive[relPath(drawingPath)] ??= strToU8(`<Relationships xmlns="${PKG}"/>`);
  const drawing = parseWorkbookXml(strFromU8(archive[drawingPath]));
  let anchor = elements(drawing.documentElement).find((node) => /^(twoCell|oneCell|absolute)Anchor$/.test(node.localName));
  if (!anchor) {
    const canvas = elements(drawing.documentElement).find((node) => node.localName === "lockedCanvas");
    const objects = canvas && Array.from(canvas.children).filter((node) => ["graphicFrame", "pic", "sp", "cxnSp", "grpSp"].includes(node.localName));
    if (objects?.length !== 1) return null;
    const object = objects[0];
    const extent2 = elements(object).find((node) => node.localName === "ext" && node.parentElement?.localName === "xfrm");
    anchor = parseWorkbookXml(`<xdr:oneCellAnchor xmlns:xdr="${XDR}"><xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>0</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:ext cx="${Number(extent2?.getAttribute("cx")) || 4572e3}" cy="${Number(extent2?.getAttribute("cy")) || 2743200}"/><xdr:clientData/></xdr:oneCellAnchor>`).documentElement;
    anchor.insertBefore(anchor.ownerDocument.importNode(convertDrawingNamespace(object), true), Array.from(anchor.children).at(-1));
  }
  const nodes = elements(anchor);
  const grouped = nodes.some((node) => node.localName === "grpSp");
  if (grouped && nodes.some((node) => node.localName === "graphicFrame")) return null;
  const kind = nodes.some((node) => node.localName === "chart") ? "chart" : nodes.some((node) => ["sp", "cxnSp", "grpSp"].includes(node.localName)) ? "shape" : nodes.some((node) => node.localName === "pic") ? "image" : null;
  if (!kind) return null;
  const marker = (name) => {
    const node = Array.from(anchor.children).find((child2) => child2.localName === name);
    const number = (key) => Number(node && Array.from(node.children).find((child2) => child2.localName === key)?.textContent) || 0;
    return { x: number("col") * 64 * 9525 + number("colOff"), y: number("row") * 20 * 9525 + number("rowOff") };
  };
  const extent = Array.from(anchor.children).find((node) => node.localName === "ext");
  const from = marker("from");
  const to = marker("to");
  const supplied = "drawingSizeEmu" in value ? value.drawingSizeEmu : void 0;
  const sizeEmu = { cx: Math.max(9525, Math.min(1e8, Number(supplied?.cx) || Number(extent?.getAttribute("cx")) || to.x - from.x || 4572e3)), cy: Math.max(9525, Math.min(1e8, Number(supplied?.cy) || Number(extent?.getAttribute("cy")) || to.y - from.y || 2743200)) };
  return { kind, anchor: serializeWorkbookXml(anchor), drawingPath, archive, sizeEmu };
}
async function imageDrawingClipboard(blob) {
  if (blob.size > 32 * 1024 * 1024) throw new Error("The copied image is too large.");
  const bitmap = await createImageBitmap(blob);
  let png = blob;
  const sizeEmu = { cx: bitmap.width * 9525, cy: bitmap.height * 9525 };
  try {
    if (bitmap.width * bitmap.height > 16e6) throw new Error("The copied image is too large.");
    if (blob.type !== "image/png") {
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Image pasting is unavailable.");
      context.drawImage(bitmap, 0, 0);
      png = await new Promise((resolve2, reject) => canvas.toBlob((value) => value ? resolve2(value) : reject(new Error("Image pasting failed.")), "image/png"));
    }
  } finally {
    bitmap.close();
  }
  const drawingPath = "xl/drawings/clipboard.xml";
  const archive = {
    "[Content_Types].xml": strToU8(`<Types xmlns="${CT}"><Default Extension="png" ContentType="image/png"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/></Types>`),
    [relPath(drawingPath)]: strToU8(`<Relationships xmlns="${PKG}"><Relationship Id="rId1" Type="${R}/image" Target="../media/clipboard.png"/></Relationships>`),
    "xl/media/clipboard.png": new Uint8Array(await png.arrayBuffer())
  };
  const anchor = `<xdr:oneCellAnchor xmlns:xdr="${XDR}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="${R}"><xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>0</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:ext cx="${sizeEmu.cx}" cy="${sizeEmu.cy}"/><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="1" name="Picture"/><xdr:cNvPicPr/></xdr:nvPicPr><xdr:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill><xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="${sizeEmu.cx}" cy="${sizeEmu.cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:oneCellAnchor>`;
  return { kind: "image", drawingPath, anchor, archive, sizeEmu };
}
async function readBrowserClipboard(transfer) {
  let text = transfer?.getData("text/plain") || void 0;
  let structured = transfer?.getData(RANGE_CLIPBOARD_TYPE) || void 0;
  let html = transfer?.getData("text/html") ?? "";
  const payloads = DRAWING_CLIPBOARD_TYPES.map((type) => transfer?.getData(type)).filter((value) => Boolean(value));
  const images = Array.from(transfer?.items ?? []).filter((item) => item.kind === "file" && item.type.startsWith("image/")).map((item) => item.getAsFile()).filter((file) => file !== null);
  const previews = [...images];
  if (transfer && !payloads.length && (structured || text && (!images.length || /<table[\s>]/i.test(html)))) {
    return { drawing: null, structured, text };
  }
  if (typeof navigator !== "undefined" && navigator.clipboard?.read) {
    try {
      const items = await navigator.clipboard.read();
      for (const item of items) {
        for (const type of item.types) {
          if (DRAWING_CLIPBOARD_TYPES.includes(type)) payloads.push(await item.getType(type));
          else if (type === `web ${RANGE_CLIPBOARD_TYPE}` || type === RANGE_CLIPBOARD_TYPE) structured ??= await (await item.getType(type)).text();
          else if (type === "text/plain") text ??= await (await item.getType(type)).text();
          else if (type === "text/html" && !html) html = await (await item.getType(type)).text();
          else if (type.startsWith("image/")) previews.push(await item.getType(type));
        }
      }
    } catch (error) {
      if (!transfer) throw error;
    }
  } else if (!transfer && typeof navigator !== "undefined" && navigator.clipboard?.readText) {
    text = await navigator.clipboard.readText();
  }
  for (const payload of payloads) {
    try {
      const drawing = decodeExcelDrawingClipboard(typeof payload === "string" ? payload : new Uint8Array(await payload.arrayBuffer()));
      if (drawing) return { drawing };
    } catch {
    }
  }
  if (payloads.length || !text && !structured && !/<table[\s>]/i.test(html)) {
    for (const preview of previews) {
      try {
        return { drawing: await imageDrawingClipboard(preview) };
      } catch {
      }
    }
  }
  return { drawing: null, structured, text };
}

// src/drawing-order.ts
import { strFromU8 as strFromU82, strToU8 as strToU82 } from "fflate";
function prepareDrawingOrder(assets, charts, kind, id, order) {
  const origin = kind === "image" ? assets.imageOriginsById.get(id) : charts.chartOriginsById.get(id);
  if (!origin) return null;
  const attachments = assets.sheetOrigins[origin.workbookSheetIndex]?.attachments;
  if (attachments?.length !== 1) return null;
  const bytes = assets.archive[origin.drawingPath];
  if (!bytes) return null;
  const document2 = parseWorkbookXml(strFromU82(bytes));
  const anchors = Array.from(document2.documentElement.children).filter((node) => /^(twoCell|oneCell|absolute)Anchor$/.test(node.localName));
  const chartAnchors = anchors.filter((node) => node.getElementsByTagNameNS("*", "chart").length > 0);
  const anchor = kind === "image" ? anchors[origin.anchorIndex] : chartAnchors[origin.anchorIndex];
  const from = anchors.indexOf(anchor);
  if (from < 0 || Array.from(anchor.children).some((node) => node.localName === "grpSp")) return null;
  const to = order === "bringToFront" ? anchors.length - 1 : order === "sendToBack" ? 0 : Math.max(0, Math.min(anchors.length - 1, from + (order === "bringForward" ? 1 : -1)));
  if (from === to) return null;
  const next = [...anchors];
  next.splice(from, 1);
  next.splice(to, 0, anchor);
  return {
    from,
    to,
    sheetIndex: origin.workbookSheetIndex,
    commit() {
      const following = anchors.at(-1)?.nextSibling ?? null;
      for (const node of next) document2.documentElement.insertBefore(node, following);
      assets.archive[origin.drawingPath] = strToU82(serializeWorkbookXml(document2));
      assets.dirtyArchivePaths.add(origin.drawingPath);
    }
  };
}

// src/chart-types.ts
var options = [];
function add(family, id, label, chartType, node, rest = {}) {
  options.push({ family, id, label, chartType, node, ...rest });
}
for (const family of ["Column", "Bar"]) {
  for (const is3d of [false, true]) {
    for (const [suffix, label, grouping] of [["Clustered", "Clustered", "clustered"], ["Stacked", "Stacked", "stacked"], ["PercentStacked", "100% Stacked", "percentStacked"]]) {
      add(family, `${family}${suffix}${is3d ? "3D" : ""}`, `${is3d ? "3-D " : ""}${label} ${family}`, `${family}${suffix}`, is3d ? "bar3DChart" : "barChart", { grouping, is3d, barDir: family === "Bar" ? "bar" : "col" });
    }
  }
}
for (const family of ["Line", "Area"]) {
  for (const [suffix, label, grouping] of [["", family, "standard"], ["Stacked", `Stacked ${family}`, "stacked"], ["PercentStacked", `100% Stacked ${family}`, "percentStacked"]]) {
    add(family, `${family}${suffix}`, label, `${family}${suffix}`, `${family.toLowerCase()}Chart`, { grouping, marker: false });
    if (family === "Line") add(family, `${family}${suffix}Markers`, `${label} with Markers`, `${family}${suffix}`, "lineChart", { grouping, marker: true });
    if (family === "Area" || suffix === "") add(family, `${family}${suffix}3D`, `3-D ${label}`, `${family}${suffix}`, `${family.toLowerCase()}3DChart`, { grouping, is3d: true });
  }
}
add("Pie", "Pie", "Pie", "Pie", "pieChart");
add("Pie", "Pie3D", "3-D Pie", "Pie3D", "pie3DChart", { is3d: true });
add("Pie", "PieOfPie", "Pie of Pie", "BarOfPie", "ofPieChart", { ofPieType: "pie" });
add("Pie", "BarOfPie", "Bar of Pie", "BarOfPie", "ofPieChart", { ofPieType: "bar" });
add("Pie", "Doughnut", "Doughnut", "Doughnut", "doughnutChart");
for (const [id, label, scatterStyle, marker] of [
  ["Scatter", "Scatter", "marker", true],
  ["ScatterSmoothMarkers", "Scatter with Smooth Lines and Markers", "smoothMarker", true],
  ["ScatterSmooth", "Scatter with Smooth Lines", "smooth", false],
  ["ScatterLinesMarkers", "Scatter with Straight Lines and Markers", "lineMarker", true],
  ["ScatterLines", "Scatter with Straight Lines", "line", false]
]) add("XY (Scatter)", id, label, id.startsWith("ScatterSmooth") ? "ScatterSmooth" : id.startsWith("ScatterLines") ? "ScatterLines" : "Scatter", "scatterChart", { scatterStyle, marker });
add("XY (Scatter)", "Bubble", "Bubble", "Bubble", "bubbleChart", { bubble3d: false });
add("XY (Scatter)", "Bubble3D", "3-D Bubble", "Bubble", "bubbleChart", { bubble3d: true });
for (const [id, label, count] of [["StockHLC", "High-Low-Close", 3], ["StockOHLC", "Open-High-Low-Close", 4], ["StockVHLC", "Volume-High-Low-Close", 4], ["StockVOHLC", "Volume-Open-High-Low-Close", 5]]) {
  add("Stock", id, label, "Stock", "stockChart", { stockSeries: count });
}
for (const is3d of [true, false]) for (const wireframe of [false, true]) {
  add("Surface", `Surface${is3d ? "3D" : "Contour"}${wireframe ? "Wireframe" : ""}`, `${wireframe ? "Wireframe " : ""}${is3d ? "3-D Surface" : "Contour"}`, "Surface", is3d ? "surface3DChart" : "surfaceChart", { is3d, wireframe });
}
for (const [id, label, radarStyle] of [["Radar", "Radar", "standard"], ["RadarMarkers", "Radar with Markers", "marker"], ["RadarFilled", "Filled Radar", "filled"]]) {
  add("Radar", id, label, "Radar", "radarChart", { radarStyle, marker: radarStyle === "marker" });
}
add("Combo", "ColumnLine", "Clustered Column \u2013 Line", "ColumnClustered", "barChart", { grouping: "clustered", barDir: "col", combo: true });
for (const [family, id, layout] of [["Treemap", "Treemap", "treemap"], ["Sunburst", "Sunburst", "sunburst"], ["Histogram", "Histogram", "clusteredColumn"], ["Histogram", "Pareto", "paretoLine"], ["Box & Whisker", "BoxWhisker", "boxWhisker"], ["Waterfall", "Waterfall", "waterfall"], ["Funnel", "Funnel", "funnel"], ["Map", "RegionMap", "regionMap"]]) {
  add(family, id, id === "BoxWhisker" ? "Box & Whisker" : id === "RegionMap" ? "Filled Map" : id, id, "", { layout });
}
var chartTypeOptions = options;
function chartTypeUnavailable(chart, option) {
  if (chart.editable === false || !chart.chartPath) return true;
  if (chart.raw?.pivotSource) return !["ColumnClustered", "ColumnStacked", "ColumnPercentStacked", "BarClustered", "BarStacked", "BarPercentStacked", "Line", "LineStacked", "Area", "AreaStacked", "AreaPercentStacked", "Pie", "Doughnut"].includes(option.id);
  if (option.stockSeries && chart.series.length !== option.stockSeries) return true;
  if (option.combo && chart.series.length < 2) return true;
  return false;
}

// src/chart-type-edit.ts
import { strFromU8 as strFromU83, strToU8 as strToU83 } from "fflate";
var C = "http://schemas.openxmlformats.org/drawingml/2006/chart";
var CX = "http://schemas.microsoft.com/office/drawing/2014/chartex";
var A = "http://schemas.openxmlformats.org/drawingml/2006/main";
var R2 = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
var classicRelationship = `${R2}/chart`;
var modernRelationship = "http://schemas.microsoft.com/office/2014/relationships/chartEx";
var CS = "http://schemas.microsoft.com/office/drawing/2012/chartStyle";
var children = (node, name) => Array.from(node.children).filter((child2) => child2.localName === name);
var child = (node, name) => children(node, name)[0];
var escape = (value) => String(value).replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" })[character]);
function dataXml(name, reference, values, numeric) {
  const type = numeric ? "num" : "str";
  const points = values.map((value, index) => value == null ? "" : `<c:pt idx="${index}"><c:v>${escape(numeric ? Number(value) || 0 : value)}</c:v></c:pt>`).join("");
  const cache = `${numeric ? "<c:formatCode>General</c:formatCode>" : ""}<c:ptCount val="${values.length}"/>${points}`;
  return `<c:${name}>${reference?.formula ? `<c:${type}Ref><c:f>${escape(reference.formula.replace(/^=/, ""))}</c:f><c:${type}Cache>${cache}</c:${type}Cache></c:${type}Ref>` : `<c:${type}Lit>${cache}</c:${type}Lit>`}</c:${name}>`;
}
function seriesXml(series, index, option, original) {
  const xy = option.node === "scatterChart" || option.node === "bubbleChart";
  const surface = option.node.startsWith("surface");
  const marker = ["lineChart", "line3DChart", "scatterChart", "radarChart", "stockChart"].includes(option.node);
  const originalTitle = original && child(original, "tx");
  const title = originalTitle ? serializeWorkbookXml(originalTitle) : series.name ? `<c:tx><c:v>${escape(series.name)}</c:v></c:tx>` : "";
  const appearance = original && child(original, "spPr");
  let style = appearance ? serializeWorkbookXml(appearance) : "";
  if (option.scatterStyle === "marker") {
    const node = appearance?.cloneNode(true) ?? parseWorkbookXml(`<c:spPr xmlns:c="${C}" xmlns:a="${A}"/>`).documentElement;
    const line = child(node, "ln");
    if (line) node.removeChild(line);
    const noLine = parseWorkbookXml(`<a:ln xmlns:a="${A}"><a:noFill/></a:ln>`).documentElement;
    node.appendChild(node.ownerDocument.importNode(noLine, true));
    style = serializeWorkbookXml(node);
  }
  const categoryValues = xy && !series.categories.every((value) => value == null || typeof value === "number") ? series.values.map((_, i) => i + 1) : series.categories;
  const categoryReference = xy && categoryValues !== series.categories ? null : series.categoriesRef;
  const points = !surface && original ? children(original, "dPt").map((node) => serializeWorkbookXml(node)).join("") : "";
  const labels = !surface && original && child(original, "dLbls");
  return `<c:ser><c:idx val="${index}"/><c:order val="${index}"/>${title}${style}` + (marker ? `<c:marker><c:symbol val="${option.marker ? "circle" : "none"}"/></c:marker>` : "") + points + (labels ? serializeWorkbookXml(labels) : "") + dataXml(xy ? "xVal" : "cat", categoryReference, categoryValues, xy || categoryValues.every((value) => value == null || typeof value === "number")) + dataXml(xy ? "yVal" : "val", series.valuesRef, series.values, true) + (option.node === "bubbleChart" ? dataXml("bubbleSize", series.bubbleSizeRef, series.bubbleSizes?.length ? series.bubbleSizes : series.values.map(() => 1), true) + `<c:bubble3D val="${option.bubble3d ? 1 : 0}"/>` : "") + (option.node === "scatterChart" || option.node === "lineChart" || option.node === "line3DChart" ? `<c:smooth val="${option.scatterStyle?.startsWith("smooth") ? 1 : 0}"/>` : "") + "</c:ser>";
}
function axisXml(kind, id, crossId, position, percent = false, hidden = false) {
  return `<c:${kind}><c:axId val="${id}"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="${hidden ? 1 : 0}"/><c:axPos val="${position}"/>` + (kind === "valAx" ? `<c:majorGridlines/><c:numFmt formatCode="${percent ? "0%" : "General"}" sourceLinked="${percent ? 0 : 1}"/>` : "") + `<c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="${crossId}"/><c:crosses val="autoZero"/>` + (kind === "catAx" ? '<c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/>' : kind === "valAx" ? '<c:crossBetween val="between"/>' : "") + `</c:${kind}>`;
}
function classicPlotXml(chart, option, originals) {
  const noAxes = /^(pie|ofPie|doughnut)/.test(option.node);
  const xy = option.node === "scatterChart" || option.node === "bubbleChart";
  const thirdAxis = option.node === "line3DChart" || option.node.startsWith("surface");
  const axisIds = noAxes ? [] : thirdAxis ? [1e5, 100001, 100002] : [1e5, 100001];
  const buildGroup = (selection, type, startIndex = 0, groupAxes = axisIds) => {
    let xml = `<c:${type.node}>`;
    if (type.barDir) xml += `<c:barDir val="${type.barDir}"/>`;
    if (type.grouping) xml += `<c:grouping val="${type.grouping}"/>`;
    if (type.scatterStyle) xml += `<c:scatterStyle val="${type.scatterStyle}"/>`;
    if (type.radarStyle) xml += `<c:radarStyle val="${type.radarStyle}"/>`;
    if (type.ofPieType) xml += `<c:ofPieType val="${type.ofPieType}"/>`;
    if (type.node.startsWith("surface")) xml += `<c:wireframe val="${type.wireframe ? 1 : 0}"/>`;
    else if (type.node !== "stockChart") xml += `<c:varyColors val="${noAxes ? 1 : 0}"/>`;
    xml += selection.map((series, index) => seriesXml(series, startIndex + index, type, originals[startIndex + index])).join("");
    if (type.node === "barChart" || type.node === "bar3DChart") xml += '<c:gapWidth val="150"/>';
    if (type.node === "barChart" && type.grouping?.includes("tacked")) xml += '<c:overlap val="100"/>';
    if (type.node === "doughnutChart") xml += '<c:holeSize val="50"/>';
    if (type.node === "bubbleChart") xml += '<c:bubbleScale val="100"/><c:showNegBubbles val="0"/><c:sizeRepresents val="area"/>';
    if (type.node === "stockChart") {
      xml += "<c:hiLowLines/>";
      if (selection.length === 4) xml += '<c:upDownBars><c:gapWidth val="150"/><c:upBars/><c:downBars/></c:upDownBars>';
    }
    xml += groupAxes.map((id) => `<c:axId val="${id}"/>`).join("");
    return xml + `</c:${type.node}>`;
  };
  const volume = option.id === "StockVHLC" || option.id === "StockVOHLC";
  let groups = option.combo ? buildGroup(chart.series.slice(0, -1), option) + buildGroup(chart.series.slice(-1), { ...option, node: "lineChart", barDir: void 0, grouping: "standard" }, chart.series.length - 1) : volume ? buildGroup(chart.series.slice(0, 1), { ...option, node: "barChart", grouping: "clustered", barDir: "col" }) + buildGroup(chart.series.slice(1), option, 1, [100003, 100004]) : buildGroup(chart.series, option);
  if (!noAxes) {
    groups += axisXml(xy ? "valAx" : "catAx", 1e5, 100001, option.barDir === "bar" ? "l" : "b") + axisXml("valAx", 100001, 1e5, option.barDir === "bar" ? "b" : "l", option.grouping === "percentStacked");
    if (thirdAxis) groups += axisXml("serAx", 100002, 100001, "b");
    if (volume) groups += axisXml("catAx", 100003, 100004, "b", false, true) + axisXml("valAx", 100004, 100003, "r");
  }
  return `<c:plotArea><c:layout/>${groups}</c:plotArea>`;
}
function modernChartXml(chart, option) {
  const dimension = (kind, type, ref, values) => `<cx:${kind} type="${type}">${ref?.formula ? `<cx:f>${escape(ref.formula.replace(/^=/, ""))}</cx:f>` : ""}<cx:lvl ptCount="${values.length}"${kind === "numDim" ? ' formatCode="General"' : ""}>${values.map((value, index) => value == null ? "" : `<cx:pt idx="${index}">${escape(value)}</cx:pt>`).join("")}</cx:lvl></cx:${kind}>`;
  const data = chart.series.map((series2, index) => `<cx:data id="${index}">` + dimension("strDim", "cat", series2.categoriesRef, series2.categories) + dimension("numDim", ["treemap", "sunburst"].includes(option.layout) ? "size" : "val", series2.valuesRef, series2.values) + "</cx:data>").join("");
  const histogram = option.id === "Histogram" || option.id === "Pareto";
  const noAxes = ["treemap", "sunburst", "funnel", "regionMap"].includes(option.layout);
  const series = chart.series.map((entry, index) => `<cx:series uniqueId="{${crypto.randomUUID().toUpperCase()}}" formatIdx="${index}" layoutId="${histogram ? "clusteredColumn" : option.layout}">` + (entry.name ? `<cx:tx><cx:txData><cx:v>${escape(entry.name)}</cx:v></cx:txData></cx:tx>` : "") + `<cx:dataId val="${index}"/>` + (histogram ? '<cx:layoutPr><cx:binning intervalClosed="r"><cx:binCount val="10"/></cx:binning></cx:layoutPr>' : "") + (noAxes ? "" : '<cx:axisId val="0"/><cx:axisId val="1"/>') + "</cx:series>" + (option.id === "Pareto" ? `<cx:series layoutId="paretoLine" ownerIdx="${index * 2}"><cx:dataId val="${index}"/><cx:axisId val="0"/><cx:axisId val="2"/></cx:series>` : "")).join("");
  const axis = (id, category = false) => `<cx:axis id="${id}"><cx:${category ? 'catScaling gapWidth="1"' : "valScaling"}/><cx:majorTickMarks type="none"/><cx:minorTickMarks type="none"/><cx:tickLabels/></cx:axis>`;
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cx:chartSpace xmlns:cx="${CX}" xmlns:a="${A}" xmlns:r="${R2}"><cx:chartData>${data}</cx:chartData><cx:chart>` + (chart.title ? `<cx:title pos="t" align="ctr" overlay="0"><cx:tx><cx:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>${escape(chart.title)}</a:t></a:r></a:p></cx:rich></cx:tx></cx:title>` : "") + `<cx:plotArea><cx:plotAreaRegion><cx:plotSurface/>${series}</cx:plotAreaRegion>${noAxes ? "" : axis(0, true) + axis(1) + (option.id === "Pareto" ? axis(2) : "")}</cx:plotArea><cx:legend pos="r" align="ctr" overlay="0"/></cx:chart></cx:chartSpace>`;
}
function ensureModernChartStyles(assets, chartPath) {
  const path = chartPath.replace(/([^/]+)$/, "_rels/$1.rels");
  const relationships = parseWorkbookXml(assets.archive[path] ? strFromU83(assets.archive[path]) : '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>');
  const types = parseWorkbookXml(strFromU83(assets.archive["[Content_Types].xml"]));
  const names = ["axisTitle", "categoryAxis", "chartArea", "dataLabel", "dataLabelCallout", "dataPoint", "dataPoint3D", "dataPointLine", "dataPointMarker", "dataPointMarkerLayout", "dataPointWireframe", "dataTable", "downBar", "dropLine", "errorBar", "floor", "gridlineMajor", "gridlineMinor", "hiLoLine", "leaderLine", "legend", "plotArea", "plotArea3D", "seriesAxis", "seriesLine", "title", "trendline", "trendlineLabel", "upBar", "valueAxis", "wall"];
  const style = `<cs:chartStyle xmlns:cs="${CS}" xmlns:a="${A}" id="201">${names.map((name) => name === "dataPointMarkerLayout" ? '<cs:dataPointMarkerLayout symbol="circle" size="5"/>' : `<cs:${name}><cs:lnRef idx="0"/><cs:fillRef idx="0"/><cs:effectRef idx="0"/><cs:fontRef idx="minor"><a:schemeClr val="tx1"/></cs:fontRef>${name.startsWith("dataPoint") ? '<cs:spPr><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></cs:spPr>' : ""}</cs:${name}>`).join("")}</cs:chartStyle>`;
  const colors = `<cs:colorStyle xmlns:cs="${CS}" xmlns:a="${A}" meth="cycle" id="10">${[1, 2, 3, 4, 5, 6].map((index) => `<a:schemeClr val="accent${index}"/>`).join("")}<cs:variation/></cs:colorStyle>`;
  for (const [kind, xml, contentType] of [["chartStyle", style, "chartstyle"], ["chartColorStyle", colors, "chartcolorstyle"]]) {
    const type = `http://schemas.microsoft.com/office/2011/relationships/${kind}`;
    if (Array.from(relationships.documentElement.children).some((node) => node.getAttribute("Type") === type)) continue;
    const part = chartPath.replace(/\.xml$/, `-${kind}-${crypto.randomUUID()}.xml`);
    const rel = relationships.createElementNS(relationships.documentElement.namespaceURI, "Relationship");
    rel.setAttribute("Id", `rId${crypto.randomUUID()}`);
    rel.setAttribute("Type", type);
    rel.setAttribute("Target", `/${part}`);
    relationships.documentElement.appendChild(rel);
    const override = types.createElementNS(types.documentElement.namespaceURI, "Override");
    override.setAttribute("PartName", `/${part}`);
    override.setAttribute("ContentType", `application/vnd.ms-office.${contentType}+xml`);
    types.documentElement.appendChild(override);
    assets.archive[part] = strToU83(xml);
    assets.dirtyArchivePaths.add(part);
  }
  assets.archive[path] = strToU83(serializeWorkbookXml(relationships));
  assets.dirtyArchivePaths.add(path);
  assets.archive["[Content_Types].xml"] = strToU83(serializeWorkbookXml(types));
  assets.dirtyArchivePaths.add("[Content_Types].xml");
}
function changeWorkbookChartType(assets, origin, chart, option) {
  if (!origin.chartPath) throw new Error("The chart has no editable source.");
  const old = parseWorkbookXml(strFromU83(assets.archive[origin.chartPath]));
  const isModern = old.documentElement.namespaceURI === CX;
  const nextModern = Boolean(option.layout);
  let xml;
  if (nextModern) xml = modernChartXml(chart, option);
  else {
    const document2 = isModern ? parseWorkbookXml(`<c:chartSpace xmlns:c="${C}" xmlns:a="${A}" xmlns:r="${R2}"><c:chart>${chart.title ? `<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>${escape(chart.title)}</a:t></a:r></a:p></c:rich></c:tx></c:title>` : ""}<c:plotArea/><c:legend><c:legendPos val="r"/></c:legend></c:chart></c:chartSpace>`) : old;
    const chartNode = child(document2.documentElement, "chart");
    if (!chartNode) throw new Error("The chart source is invalid.");
    const plot = child(chartNode, "plotArea");
    if (!plot) throw new Error("The chart has no plot area.");
    const originals = Array.from(plot.children).flatMap((node) => children(node, "ser"));
    const nextPlot = parseWorkbookXml(`<c:chartSpace xmlns:c="${C}" xmlns:a="${A}" xmlns:r="${R2}">${classicPlotXml(chart, option, originals)}</c:chartSpace>`).documentElement.firstElementChild;
    const appearance = child(plot, "spPr");
    if (appearance) nextPlot.appendChild(appearance.cloneNode(true));
    plot.parentNode.insertBefore(document2.importNode(nextPlot, true), plot);
    plot.parentNode.removeChild(plot);
    for (const node of Array.from(chartNode.children)) if (["view3D", "floor", "sideWall", "backWall"].includes(node.localName)) chartNode.removeChild(node);
    if (option.is3d) {
      const view = parseWorkbookXml(`<c:view3D xmlns:c="${C}"><c:rotX val="15"/><c:rotY val="20"/><c:rAngAx val="1"/></c:view3D>`).documentElement;
      chartNode.insertBefore(document2.importNode(view, true), child(chartNode, "plotArea"));
    }
    xml = serializeWorkbookXml(document2);
  }
  assets.archive[origin.chartPath] = strToU83(xml);
  assets.dirtyArchivePaths.add(origin.chartPath);
  if (nextModern) ensureModernChartStyles(assets, origin.chartPath);
  if (isModern !== nextModern) {
    const drawing = parseWorkbookXml(strFromU83(assets.archive[origin.drawingPath]));
    const relPath2 = origin.drawingPath.replace(/([^/]+)$/, "_rels/$1.rels");
    const relationships = parseWorkbookXml(strFromU83(assets.archive[relPath2]));
    const rel = Array.from(relationships.documentElement.children).find((node) => {
      const target = node.getAttribute("Target");
      return target && new URL(target, `https://xlsx.invalid/${origin.drawingPath}`).pathname.slice(1) === origin.chartPath;
    });
    if (!rel) throw new Error("The chart relationship is missing.");
    rel.setAttribute("Type", nextModern ? modernRelationship : classicRelationship);
    const chartReference = Array.from(drawing.getElementsByTagNameNS(isModern ? CX : C, "chart")).find((node) => node.getAttributeNS(R2, "id") === rel.getAttribute("Id"));
    if (!chartReference?.parentNode) throw new Error("The chart drawing is missing.");
    const replacement = drawing.createElementNS(nextModern ? CX : C, nextModern ? "cx:chart" : "c:chart");
    replacement.setAttributeNS(R2, "r:id", rel.getAttribute("Id"));
    chartReference.parentElement?.setAttribute("uri", nextModern ? CX : C);
    chartReference.parentNode.insertBefore(replacement, chartReference);
    chartReference.parentNode.removeChild(chartReference);
    const frame = replacement.parentElement?.parentElement?.parentElement;
    if (frame?.localName === "graphicFrame") {
      const MC = "http://schemas.openxmlformats.org/markup-compatibility/2006";
      if (nextModern && frame.parentElement?.namespaceURI !== MC) {
        const alternate = drawing.createElementNS(MC, "mc:AlternateContent");
        const choice = drawing.createElementNS(MC, "mc:Choice");
        choice.setAttribute("xmlns:cx1", "http://schemas.microsoft.com/office/drawing/2015/9/8/chartex");
        choice.setAttribute("Requires", "cx1");
        frame.parentNode.insertBefore(alternate, frame);
        alternate.appendChild(choice);
        choice.appendChild(frame);
        const fallback = drawing.createElementNS(MC, "mc:Fallback");
        const shape = parseWorkbookXml(`<xdr:sp xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="${A}"><xdr:nvSpPr><xdr:cNvPr id="0" name=""/><xdr:cNvSpPr><a:spLocks noTextEdit="1"/></xdr:cNvSpPr></xdr:nvSpPr><xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr><xdr:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>This chart requires a newer version of Excel.</a:t></a:r></a:p></xdr:txBody></xdr:sp>`).documentElement;
        fallback.appendChild(drawing.importNode(shape, true));
        alternate.appendChild(fallback);
      } else if (!nextModern && frame.parentElement?.localName === "Choice") {
        const alternate = frame.parentElement.parentElement;
        alternate.parentNode.insertBefore(frame, alternate);
        alternate.parentNode.removeChild(alternate);
      }
    }
    const types = parseWorkbookXml(strFromU83(assets.archive["[Content_Types].xml"]));
    const contentType = Array.from(types.documentElement.children).find((node) => node.getAttribute("PartName") === `/${origin.chartPath}`);
    if (!contentType) throw new Error("The chart content type is missing.");
    contentType.setAttribute("ContentType", nextModern ? "application/vnd.ms-office.chartex+xml" : "application/vnd.openxmlformats-officedocument.drawingml.chart+xml");
    for (const [path, doc] of [[origin.drawingPath, drawing], [relPath2, relationships], ["[Content_Types].xml", types]]) {
      assets.archive[path] = strToU83(serializeWorkbookXml(doc));
      assets.dirtyArchivePaths.add(path);
    }
  }
}

// src/formula-references.ts
var REFERENCE_COLORS = ["#3472c9", "#c53645", "#9b4dbb", "#258447", "#b97812", "#16858e"];
var CELL = String.raw`\$?[A-Z]{1,3}\$?[1-9]\d{0,6}`;
var COLUMN = String.raw`\$?[A-Z]{1,3}`;
var ROW = String.raw`\$?[1-9]\d{0,6}`;
var SHEET = String.raw`(?:'(?:[^']|'')+'|[\p{L}\p{N}_\\.]+)!`;
var REFERENCE = new RegExp(
  `(?:${SHEET})?(?:${CELL}(?:\\s*:\\s*${CELL})?|${COLUMN}\\s*:\\s*${COLUMN}|${ROW}\\s*:\\s*${ROW})`,
  "iyu"
);
var NAME_CHARACTER = /[\p{L}\p{N}_.$\\]/u;
function getFormulaReferences(value, sheetName) {
  if (!/^[=+-]/.test(value)) return [];
  const references = [];
  const colors = /* @__PURE__ */ new Map();
  let index = value.startsWith("=") ? 1 : 0;
  while (index < value.length) {
    if (value[index] === '"') {
      index += 1;
      while (index < value.length) {
        if (value[index++] === '"') {
          if (value[index] !== '"') break;
          index += 1;
        }
      }
      continue;
    }
    if (value[index] === "[") {
      let depth = 1;
      while (++index < value.length && depth) {
        if (value[index] === "[") depth += 1;
        if (value[index] === "]") depth -= 1;
      }
      while (index < value.length && /[^\s+\-*/^&=<>(),;]/.test(value[index])) index += 1;
      continue;
    }
    if (NAME_CHARACTER.test(value[index - 1])) {
      index += 1;
      continue;
    }
    REFERENCE.lastIndex = index;
    const match = REFERENCE.exec(value);
    if (match) {
      const end = index + match[0].length;
      const previous = value[index - 1];
      const next = value[end];
      const parsed = parseXlsxRange(match[0].replace(/\s*:\s*/g, ":"));
      if (parsed && !NAME_CHARACTER.test(previous) && previous !== "]" && previous !== "!" && previous !== ":" && (!next || !NAME_CHARACTER.test(next) && !/[!\[]/.test(next)) && !/^\s*\(/.test(value.slice(end))) {
        const { range } = parsed;
        const key = `${(parsed.sheetName ?? sheetName).toLowerCase()}:${range.start.row},${range.start.col}:${range.end.row},${range.end.col}`;
        let color = colors.get(key);
        if (!color) {
          color = REFERENCE_COLORS[colors.size % REFERENCE_COLORS.length];
          colors.set(key, color);
        }
        references.push({ ...parsed, start: index, end, color });
      }
      index = end;
    } else if (value[index] === "'") {
      index += 1;
      while (index < value.length) {
        if (value[index++] === "'") {
          if (value[index] !== "'") break;
          index += 1;
        }
      }
    } else {
      index += 1;
    }
  }
  return references;
}

// src/cell-input.ts
function isTextCell(worksheet, cell) {
  const style = worksheet.getCellStyleAt(cell.row, cell.col);
  return style?.numberFormat?.formatString === "@" || style?.numberFormat?.id === 49;
}
function coerceUserEnteredValue(value, locale = "en-US", source = "edit") {
  if (source === "edit" && value.startsWith("'")) return value.slice(1);
  const trimmed = value.trim();
  if (!trimmed) return value;
  if (/^(true|false)$/i.test(trimmed)) return trimmed.toLowerCase() === "true";
  const localized = parseLocaleNumber(trimmed, locale);
  if (localized !== void 0) return localized;
  if (/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(trimmed)) {
    const number = Number(trimmed);
    if (Number.isFinite(number)) return number;
  }
  return value;
}
function getUserEnteredFormula(value, locale = "en-US") {
  if (value.startsWith("=") && value.length > 1) return value;
  if (/^[+-].+/.test(value) && typeof coerceUserEnteredValue(value, locale) !== "number") return `=${value}`;
  return null;
}
function applyInputNumberFormat(worksheet, cell, input) {
  const style = worksheet.getCellStyleAt(cell.row, cell.col);
  const format = style?.numberFormat;
  if (format?.formatString && format.formatString.toLowerCase() !== "general") return;
  const formatString = /^[+-]?(?:\d+\.?\d*|\.\d+)[eE][+-]?\d+$/.test(input.trim()) ? "0.00E+00" : /^=\s*(?:DATE|TODAY)\s*\(/i.test(input) ? "m/d/yy" : void 0;
  if (formatString) worksheet.setCellStyleAt(cell.row, cell.col, { ...style, numberFormat: { formatString } });
}
function normalizeFormulaReferences(formula) {
  for (const reference of getFormulaReferences(formula, "").reverse()) {
    const token = formula.slice(reference.start, reference.end);
    const separator = token.lastIndexOf("!") + 1;
    formula = formula.slice(0, reference.start) + token.slice(0, separator) + token.slice(separator).toUpperCase().replace(/\s*:\s*/g, ":") + formula.slice(reference.end);
  }
  return formula;
}
function parseClipboardText(text) {
  const normalized = text.replace(/\r\n?/g, "\n");
  const rows = [];
  let row2 = [];
  let offset = 0;
  while (offset < normalized.length) {
    let value = "";
    if (normalized[offset] === '"') {
      const quoted = /^"((?:[^"]|"")*)"(?=\t|\n|$)/.exec(normalized.slice(offset));
      if (quoted) {
        value = quoted[1].replace(/""/g, '"');
        offset += quoted[0].length;
      }
    }
    while (offset < normalized.length && normalized[offset] !== "	" && normalized[offset] !== "\n") value += normalized[offset++];
    row2.push(value);
    const delimiter = normalized[offset++];
    if (delimiter === "\n" || delimiter === void 0) {
      rows.push(row2);
      row2 = [];
    } else if (offset === normalized.length) row2.push("");
  }
  if (row2.length) rows.push(row2);
  return rows;
}
function quoteClipboardField(value) {
  return /[\t\r\n"]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

// src/controller.tsx
import * as React from "react";
import { XlsxFileSizeLimitExceededError } from "@extend-ai/react-xlsx/internal";
import { XlsxFileSizeLimitExceededError as XlsxFileSizeLimitExceededError2 } from "@extend-ai/react-xlsx/internal";

// src/range-highlight.ts
function expandHighlightedRange(range, mergedRanges) {
  const expanded = { start: { ...range.start }, end: { ...range.end } };
  let changed;
  do {
    changed = false;
    for (const merged of mergedRanges) {
      if (merged.end.row < expanded.start.row || merged.start.row > expanded.end.row || merged.end.col < expanded.start.col || merged.start.col > expanded.end.col) {
        continue;
      }
      const startRow = Math.min(expanded.start.row, merged.start.row);
      const startCol = Math.min(expanded.start.col, merged.start.col);
      const endRow = Math.max(expanded.end.row, merged.end.row);
      const endCol = Math.max(expanded.end.col, merged.end.col);
      if (startRow !== expanded.start.row || startCol !== expanded.start.col || endRow !== expanded.end.row || endCol !== expanded.end.col) {
        expanded.start = { row: startRow, col: startCol };
        expanded.end = { row: endRow, col: endCol };
        changed = true;
      }
    }
  } while (changed);
  return expanded;
}

// src/controller.tsx
import { getSheetsWasmModule } from "@extend-ai/react-xlsx/internal";

// src/worker-client.ts
import { getConfiguredWorkerWasmSource } from "@extend-ai/react-xlsx/internal";
var columnFontMeasurements = /* @__PURE__ */ new Map();
function createAbortError() {
  if (typeof DOMException !== "undefined") {
    return new DOMException("Aborted", "AbortError");
  }
  const error = new Error("Aborted");
  error.name = "AbortError";
  return error;
}
var XlsxWorkerUnavailableError = class extends Error {
  constructor(message) {
    super(message);
    this.name = "XlsxWorkerUnavailableError";
  }
};
var XlsxWorkerClient = class {
  worker = null;
  mainRuntime = null;
  mainLoad = null;
  loadPayload = null;
  nextRequestId = 1;
  pendingRequests = /* @__PURE__ */ new Map();
  disposed = false;
  failure = null;
  startupTimer = null;
  constructor(useWorker = true) {
    if (!useWorker || typeof Worker === "undefined") return;
    try {
      this.worker = new Worker(new URL("./xlsx-worker.js", import.meta.url), { type: "module" });
    } catch {
      return;
    }
    this.worker.addEventListener("message", this.handleMessage);
    this.worker.addEventListener("error", this.handleError);
    this.worker.addEventListener("messageerror", this.handleError);
    this.startupTimer = setTimeout(() => {
      this.fail(new XlsxWorkerUnavailableError("The workbook worker did not start in time."));
    }, 15e3);
  }
  dispose() {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.stopWorker();
    const abortError = createAbortError();
    for (const request of this.pendingRequests.values()) {
      request.reject(abortError);
    }
    this.pendingRequests.clear();
    void this.mainRuntime?.then((runtime) => runtime.dispose(), () => void 0);
    this.loadPayload = null;
  }
  stopWorker() {
    if (this.startupTimer !== null) clearTimeout(this.startupTimer);
    this.startupTimer = null;
    this.worker?.removeEventListener("message", this.handleMessage);
    this.worker?.removeEventListener("error", this.handleError);
    this.worker?.removeEventListener("messageerror", this.handleError);
    this.worker?.terminate();
  }
  async loadWorkbook(buffer, skipXmlParsing = false, showHiddenSheets = false, includeSnapshot = false) {
    this.loadPayload = { buffer, columnFontMeasurements: Array.from(columnFontMeasurements), includeSnapshot, showHiddenSheets, skipXmlParsing };
    const result = await this.withFallback(async () => {
      const workerBuffer = cloneArrayBufferForTransfer(buffer);
      return this.request({
        id: 0,
        payload: { ...this.loadPayload, buffer: workerBuffer, wasmSource: await getConfiguredWorkerWasmSource() },
        type: "load"
      }, [workerBuffer]);
    }, () => this.loadOnMainThread());
    restoreWorkerImageBlobs(result.imageAssets, result.imageBlobs);
    delete result.imageBlobs;
    for (const [key, value] of result.columnFontMeasurements) columnFontMeasurements.set(key, value);
    while (columnFontMeasurements.size > 256) columnFontMeasurements.delete(columnFontMeasurements.keys().next().value);
    return result;
  }
  getCellSnapshot(workbookSheetIndex, row2, col, locale) {
    return this.requestWithFallback({
      id: 0,
      payload: { col, row: row2, workbookSheetIndex, locale },
      type: "getCellSnapshot"
    });
  }
  renderChart = (...payload) => this.requestWithFallback({ id: 0, type: "renderChart", payload });
  exportWorkbook(snapshot, assets, origins) {
    return this.requestWithFallback({ id: 0, type: "export", payload: { snapshot, assets, origins } });
  }
  getRowsBatch(workbookSheetIndex, startRow, rowCount, locale) {
    return this.requestWithFallback({
      id: 0,
      payload: { rowCount, startRow, workbookSheetIndex, locale },
      type: "getRowsBatch"
    });
  }
  getAutofitCells(workbookSheetIndex, axis, index, locale) {
    return this.requestWithFallback({
      id: 0,
      payload: { workbookSheetIndex, axis, index, locale },
      type: "getAutofitCells"
    });
  }
  async withFallback(runWorker, runMain) {
    if (this.disposed) throw createAbortError();
    if (this.worker && !this.failure) {
      try {
        return await runWorker();
      } catch (error) {
        if (this.disposed || error instanceof Error && error.name === "AbortError") throw error;
        this.fail(new XlsxWorkerUnavailableError("The workbook worker is unavailable; using the main thread."));
      }
    }
    if (this.disposed) throw createAbortError();
    return runMain();
  }
  async getMainRuntime() {
    if (this.disposed) throw createAbortError();
    this.mainRuntime ??= import("./workbook-runtime-BAAYDYYK.js").then(({ createWorkbookRuntime }) => createWorkbookRuntime());
    const runtime = await this.mainRuntime;
    if (this.disposed) {
      runtime.dispose();
      throw createAbortError();
    }
    return runtime;
  }
  loadOnMainThread() {
    this.mainLoad ??= (async () => {
      const runtime = await this.getMainRuntime();
      if (!this.loadPayload) throw createAbortError();
      const result = await runtime.handleMessage({ id: 0, type: "load", payload: { ...this.loadPayload, includeSnapshot: true } });
      if (this.disposed) {
        runtime.dispose();
        throw createAbortError();
      }
      return result;
    })();
    return this.mainLoad;
  }
  requestWithFallback(message) {
    return this.withFallback(() => this.request(message), async () => {
      const runtime = await this.getMainRuntime();
      if (this.loadPayload) await this.loadOnMainThread();
      if (this.disposed) throw createAbortError();
      return await runtime.handleMessage(message);
    });
  }
  request(message, transfer = []) {
    return new Promise((resolve2, reject) => {
      if (this.disposed) {
        reject(createAbortError());
        return;
      }
      if (this.failure) {
        reject(this.failure);
        return;
      }
      const id = this.nextRequestId;
      this.nextRequestId += 1;
      this.pendingRequests.set(id, { reject, resolve: resolve2 });
      try {
        this.worker.postMessage({ ...message, id }, transfer);
      } catch {
        this.fail(new XlsxWorkerUnavailableError("The workbook worker could not receive a request."));
      }
    });
  }
  handleError = () => {
    this.fail(new XlsxWorkerUnavailableError("The workbook worker failed."));
  };
  fail(error) {
    if (this.disposed || this.failure) return;
    this.failure = error;
    this.stopWorker();
    for (const request of this.pendingRequests.values()) {
      request.reject(error);
    }
    this.pendingRequests.clear();
  }
  handleMessage = (event) => {
    const message = event.data;
    if ("type" in message) {
      if (this.startupTimer !== null) clearTimeout(this.startupTimer);
      this.startupTimer = null;
      return;
    }
    const request = this.pendingRequests.get(message.id);
    if (!request) {
      return;
    }
    this.pendingRequests.delete(message.id);
    if (!message.success) {
      request.reject(new Error(message.error));
      return;
    }
    request.resolve(message.result);
  };
};
function cloneArrayBufferForTransfer(buffer) {
  return buffer.slice(0);
}

// src/controller.tsx
var DEFAULT_ROW_HEIGHT = 24;
var DEFAULT_COL_WIDTH = 80;
var XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
var CSV_MIME_TYPE = "text/csv;charset=utf-8";
var MIN_ROW_HEIGHT_PX = 16;
var GRID_HEADER_HEIGHT = 24;
var GRID_ROW_HEADER_WIDTH = 40;
var HISTORY_LIMIT = 100;
var INTERNAL_CLIPBOARD_MIME = "application/x-react-xlsx-range+json";
var DEFAULT_DEFER_LOADING_ABOVE_BYTES = 0;
var DEFAULT_MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024;
var DEFAULT_ZOOM_SCALE = 100;
var MIN_ZOOM_SCALE = 10;
var MAX_ZOOM_SCALE = 400;
var ZOOM_STEP = 10;
var DEFAULT_ZOOM_TAB_KEY = "__default__";
function normalizeWorksheetVisibility(value) {
  return value === "hidden" || value === "veryHidden" ? value : "visible";
}
function clampZoomScale(zoomScale) {
  if (!Number.isFinite(zoomScale)) {
    return DEFAULT_ZOOM_SCALE;
  }
  return Math.min(MAX_ZOOM_SCALE, Math.max(MIN_ZOOM_SCALE, Math.round(zoomScale)));
}
function resolveDefaultZoomScale(activeTab, activeSheet) {
  if (activeTab?.kind !== "sheet") {
    return DEFAULT_ZOOM_SCALE;
  }
  return clampZoomScale(activeSheet?.zoomScale ?? DEFAULT_ZOOM_SCALE);
}
function resolveWorksheetZoomScale(worksheet, sheetState) {
  const candidates = [
    typeof sheetState?.zoomScale === "number" ? sheetState.zoomScale : void 0,
    typeof worksheet.zoomScale === "number" ? worksheet.zoomScale : void 0
  ];
  const value = candidates.find((entry) => typeof entry === "number" && Number.isFinite(entry) && entry > 0);
  return clampZoomScale(value ?? DEFAULT_ZOOM_SCALE);
}
function resolveNextZoomScale(currentZoomScale, direction) {
  if (direction > 0) {
    return Math.min(
      MAX_ZOOM_SCALE,
      currentZoomScale % ZOOM_STEP === 0 ? currentZoomScale + ZOOM_STEP : Math.ceil(currentZoomScale / ZOOM_STEP) * ZOOM_STEP
    );
  }
  return Math.max(
    MIN_ZOOM_SCALE,
    currentZoomScale % ZOOM_STEP === 0 ? currentZoomScale - ZOOM_STEP : Math.floor(currentZoomScale / ZOOM_STEP) * ZOOM_STEP
  );
}
function resolveDisplayFileName(src, fileName) {
  if (typeof fileName === "string" && fileName.trim().length > 0) {
    return fileName.trim();
  }
  if (!src) {
    return "Workbook.xlsx";
  }
  const pathWithoutQuery = src.split("?")[0] ?? "";
  const pathSegments = pathWithoutQuery.split("/");
  const lastSegment = pathSegments[pathSegments.length - 1] ?? "";
  if (!lastSegment) {
    return "Workbook.xlsx";
  }
  try {
    return decodeURIComponent(lastSegment);
  } catch {
    return lastSegment;
  }
}
function resolveSheetDisplayUsedRange(usedRange, sheetState) {
  const [minRow, minCol, maxRow, maxCol] = usedRange;
  const maxContentRow = sheetState?.maxContentRow ?? -1;
  const maxContentCol = sheetState?.maxContentCol ?? -1;
  const maxVerticalMergeEndRow = sheetState?.maxVerticalMergeEndRow ?? -1;
  const maxHorizontalMergeEndCol = sheetState?.maxHorizontalMergeEndCol ?? -1;
  const maxMeaningfulRow = Math.max(maxContentRow, maxVerticalMergeEndRow);
  const maxMeaningfulCol = Math.max(maxContentCol, maxHorizontalMergeEndCol);
  if (maxMeaningfulRow < 0 && maxMeaningfulCol < 0) {
    return usedRange;
  }
  return [
    sheetState?.minContentRow !== void 0 && sheetState.minContentRow >= 0 ? Math.min(minRow, sheetState.minContentRow) : minRow,
    sheetState?.minContentCol !== void 0 && sheetState.minContentCol >= 0 ? Math.min(minCol, sheetState.minContentCol) : minCol,
    maxMeaningfulRow >= 0 ? maxContentRow >= 0 ? Math.min(maxRow, maxMeaningfulRow) : Math.max(maxRow, maxMeaningfulRow) : maxRow,
    maxMeaningfulCol >= 0 ? maxContentCol >= 0 ? Math.min(maxCol, maxMeaningfulCol) : Math.max(maxCol, maxMeaningfulCol) : maxCol
  ];
}
function buildSheetList(workbook, sheetStatesByWorkbookSheetIndex, themePalette, styleById, namedCellStyleByName, tableStyleByName, showHiddenSheets = false) {
  const sheets = [];
  for (let index = 0; index < workbook.sheetCount; index += 1) {
    const worksheet = workbook.getSheet(index);
    const sheetState = sheetStatesByWorkbookSheetIndex?.[index] ?? null;
    const mergeMetadata = resolveWorksheetMergeMetadata(worksheet);
    const effectiveSheetState = {
      ...sheetState,
      ...mergeMetadata
    };
    const defaultColWidthPx = sheetState?.defaultColWidthPx ?? resolveWorksheetDefaultColumnWidthPixels(
      worksheet,
      sheetState?.columnWidthCharacterWidthPx,
      DEFAULT_COL_WIDTH
    );
    const defaultRowHeightPx = sheetState?.defaultRowHeightPx ?? resolveWorksheetDefaultRowHeightPixels(
      worksheet,
      DEFAULT_ROW_HEIGHT
    );
    const visibility = normalizeWorksheetVisibility(worksheet.visibility);
    if (!showHiddenSheets && visibility !== "visible") {
      continue;
    }
    const resolveColumnWidthPx = (col) => {
      const width = worksheet.getColumnWidth(col);
      if (width !== void 0 && width !== null) {
        return resolveSheetColumnWidthPixels(width, sheetState?.columnWidthCharacterWidthPx);
      }
      return sheetState?.colWidthOverridesPx?.[col] ?? defaultColWidthPx;
    };
    const resolveRowHeightPx = (row2) => {
      const height = worksheet.getRowHeight(row2);
      if (height !== void 0 && height !== null) {
        return Math.max(Math.round(height * 1.33), MIN_ROW_HEIGHT_PX);
      }
      return sheetState?.rowHeightOverridesPx?.[row2] ?? defaultRowHeightPx;
    };
    const usedRange = worksheet.usedRange();
    if (!usedRange) {
      sheets.push({
        autoFilterRanges: sheetState?.autoFilterRanges ?? [],
        cachedFormulaValues: sheetState?.cachedFormulaValues ?? {},
        columnWidthCharacterWidthPx: sheetState?.columnWidthCharacterWidthPx,
        colWidthOverridesPx: sheetState?.colWidthOverridesPx ?? {},
        colStyleIds: sheetState?.colStyleIds ?? {},
        conditionalFormatRules: sheetState?.conditionalFormatRules ?? [],
        dataValidations: parseWorksheetDataValidations(worksheet),
        officeLayout: sheetState?.officeLayout,
        defaultColWidthPx,
        defaultRowHeightPx,
        freezePanes: parseWorksheetFreezePanes(worksheet),
        hasHorizontalMerges: mergeMetadata.hasHorizontalMerges,
        hasVerticalMerges: mergeMetadata.hasVerticalMerges,
        maxHorizontalMergeEndCol: mergeMetadata.maxHorizontalMergeEndCol,
        maxVerticalMergeEndRow: mergeMetadata.maxVerticalMergeEndRow,
        mergedRanges: mergeMetadata.mergedRanges,
        hiddenCols: Array.from(worksheet.hiddenColumns),
        hiddenRows: Array.from(worksheet.hiddenRows),
        minUsedCol: -1,
        minUsedRow: -1,
        maxUsedCol: -1,
        maxUsedRow: -1,
        name: worksheet.name,
        visibility,
        namedCellStyleByName: namedCellStyleByName ?? {},
        rowCount: 0,
        colCount: 0,
        rowHeightOverridesPx: sheetState?.rowHeightOverridesPx ?? {},
        rowStyleIds: sheetState?.rowStyleIds ?? {},
        cellStyleIds: sheetState?.cellStyleIds ?? {},
        styleById: styleById ?? {},
        sparklines: sheetState?.sparklines ?? [],
        tableStyleByName: tableStyleByName ?? {},
        visibleRows: [],
        visibleCols: [],
        colWidths: [],
        rowHeights: [],
        showGridLines: sheetState?.showGridLines ?? true,
        themePalette: themePalette ?? { colorsByIndex: {} },
        workbookSheetIndex: index,
        zoomScale: resolveWorksheetZoomScale(worksheet, sheetState)
      });
      continue;
    }
    const [minRow, minCol, maxRow, maxCol] = resolveSheetDisplayUsedRange(usedRange, effectiveSheetState);
    let visibleRowsCache = null;
    let visibleColsCache = null;
    let rowHeightsCache = null;
    let colWidthsCache = null;
    const getVisibleRows = () => {
      if (visibleRowsCache) {
        return visibleRowsCache;
      }
      const nextVisibleRows = [];
      for (let row2 = 0; row2 <= maxRow; row2 += 1) {
        if (!worksheet.isRowHidden(row2)) {
          nextVisibleRows.push(row2);
        }
      }
      visibleRowsCache = nextVisibleRows;
      return nextVisibleRows;
    };
    const getVisibleCols = () => {
      if (visibleColsCache) {
        return visibleColsCache;
      }
      const nextVisibleCols = [];
      for (let col = 0; col <= maxCol; col += 1) {
        if (!worksheet.isColumnHidden(col)) {
          nextVisibleCols.push(col);
        }
      }
      visibleColsCache = nextVisibleCols;
      return nextVisibleCols;
    };
    const getRowHeights = () => {
      if (rowHeightsCache) {
        return rowHeightsCache;
      }
      rowHeightsCache = getVisibleRows().map(resolveRowHeightPx);
      return rowHeightsCache;
    };
    const getColWidths = () => {
      if (colWidthsCache) {
        return colWidthsCache;
      }
      colWidthsCache = getVisibleCols().map(resolveColumnWidthPx);
      return colWidthsCache;
    };
    const sheet = {
      autoFilterRanges: sheetState?.autoFilterRanges ?? [],
      cachedFormulaValues: sheetState?.cachedFormulaValues ?? {},
      columnWidthCharacterWidthPx: sheetState?.columnWidthCharacterWidthPx,
      colWidthOverridesPx: sheetState?.colWidthOverridesPx ?? {},
      colStyleIds: sheetState?.colStyleIds ?? {},
      conditionalFormatRules: sheetState?.conditionalFormatRules ?? [],
      dataValidations: parseWorksheetDataValidations(worksheet),
      officeLayout: sheetState?.officeLayout,
      defaultColWidthPx,
      defaultRowHeightPx,
      freezePanes: parseWorksheetFreezePanes(worksheet),
      hasHorizontalMerges: mergeMetadata.hasHorizontalMerges,
      hasVerticalMerges: mergeMetadata.hasVerticalMerges,
      maxHorizontalMergeEndCol: mergeMetadata.maxHorizontalMergeEndCol,
      maxVerticalMergeEndRow: mergeMetadata.maxVerticalMergeEndRow,
      mergedRanges: mergeMetadata.mergedRanges,
      hiddenCols: Array.from(worksheet.hiddenColumns),
      hiddenRows: Array.from(worksheet.hiddenRows),
      minUsedCol: minCol,
      minUsedRow: minRow,
      maxUsedCol: maxCol,
      maxUsedRow: maxRow,
      name: worksheet.name,
      visibility,
      namedCellStyleByName: namedCellStyleByName ?? {},
      rowHeightOverridesPx: sheetState?.rowHeightOverridesPx ?? {},
      rowStyleIds: sheetState?.rowStyleIds ?? {},
      cellStyleIds: sheetState?.cellStyleIds ?? {},
      showGridLines: sheetState?.showGridLines ?? true,
      styleById: styleById ?? {},
      sparklines: sheetState?.sparklines ?? [],
      tableStyleByName: tableStyleByName ?? {},
      themePalette: themePalette ?? { colorsByIndex: {} },
      workbookSheetIndex: index,
      zoomScale: resolveWorksheetZoomScale(worksheet, sheetState),
      get rowCount() {
        return getVisibleRows().length;
      },
      get colCount() {
        return getVisibleCols().length;
      },
      get visibleRows() {
        return getVisibleRows();
      },
      get visibleCols() {
        return getVisibleCols();
      },
      get colWidths() {
        return getColWidths();
      },
      get rowHeights() {
        return getRowHeights();
      }
    };
    sheets.push(sheet);
  }
  return sheets;
}
function buildVisibleSheetIndexMap(sheets) {
  return new Map(sheets.map((sheet, index) => [sheet.workbookSheetIndex, index]));
}
function resolveInheritedCellStyle(sheet, row2, col) {
  if (!sheet) {
    return null;
  }
  const rowStyleId = sheet.rowStyleIds[row2];
  if (rowStyleId !== void 0) {
    return sheet.styleById[rowStyleId] ?? null;
  }
  const colStyleId = sheet.colStyleIds[col];
  if (colStyleId !== void 0) {
    return sheet.styleById[colStyleId] ?? null;
  }
  return null;
}
function columnLabel(col) {
  let label = "";
  let nextValue = col;
  while (nextValue >= 0) {
    label = String.fromCharCode(65 + nextValue % 26) + label;
    nextValue = Math.floor(nextValue / 26) - 1;
  }
  return label;
}
function cellAddressToA1(cell) {
  return `${columnLabel(cell.col)}${cell.row + 1}`;
}
function parseA1CellReference(reference) {
  const match = /^([A-Z]+)(\d+)$/i.exec(reference.trim());
  if (!match) {
    return null;
  }
  const [, columnPart, rowPart] = match;
  let col = 0;
  for (const char of columnPart.toUpperCase()) {
    col = col * 26 + (char.charCodeAt(0) - 64);
  }
  return {
    col: col - 1,
    row: Number(rowPart) - 1
  };
}
function parseA1RangeReference(reference) {
  const [startRef, endRef = startRef] = reference.split(":");
  const start = parseA1CellReference(startRef ?? "");
  const end = parseA1CellReference(endRef ?? "");
  if (!start || !end) {
    return null;
  }
  return normalizeRange({ start, end });
}
function resolveWorkbookReference(workbook, defaultWorkbookSheetIndex, rawReference, resolvingNamedRange = false) {
  const reference = rawReference.trim().replace(/^=/, "");
  if (!reference) {
    return null;
  }
  let workbookSheetIndex = defaultWorkbookSheetIndex;
  let rangeReference = reference;
  const bangIndex = reference.lastIndexOf("!");
  if (bangIndex >= 0) {
    let sheetName = reference.slice(0, bangIndex).trim();
    rangeReference = reference.slice(bangIndex + 1).trim();
    if (sheetName.startsWith("'") && sheetName.endsWith("'")) {
      sheetName = sheetName.slice(1, -1).replace(/''/g, "'");
    }
    const resolvedSheetIndex = workbook.sheetIndex(sheetName);
    if (resolvedSheetIndex === void 0) {
      return null;
    }
    workbookSheetIndex = resolvedSheetIndex;
  } else if (!resolvingNamedRange) {
    const namedRange = workbook.getNamedRange(reference);
    if (namedRange) {
      return resolveWorkbookReference(workbook, defaultWorkbookSheetIndex, namedRange, true);
    }
  }
  const range = parseA1RangeReference(rangeReference.replace(/\$/g, ""));
  if (!range || workbookSheetIndex < 0 || workbookSheetIndex >= workbook.sheetCount) {
    return null;
  }
  try {
    return {
      range,
      workbookSheetIndex,
      worksheet: workbook.getSheet(workbookSheetIndex)
    };
  } catch {
    return null;
  }
}
function parseColorHex(hex) {
  const normalized = hex?.replace(/^#/, "");
  return normalized && /^[0-9a-f]{6}$/i.test(normalized) ? [0, 2, 4].map((offset) => Number.parseInt(normalized.slice(offset, offset + 2), 16)) : null;
}
function xlsxColorToDukeColor(color) {
  if (!color) {
    return void 0;
  }
  const normalizedHex = color.hex?.replace(/^#/, "");
  const colorType = color.colorType ?? (normalizedHex?.length === 8 ? "argb" : normalizedHex?.length === 6 ? "rgb" : void 0) ?? (color.r !== void 0 && color.g !== void 0 && color.b !== void 0 ? color.a !== void 0 ? "argb" : "rgb" : void 0) ?? (color.themeIndex !== void 0 ? "theme" : color.paletteIndex !== void 0 ? "indexed" : void 0);
  switch (colorType) {
    case "auto":
      return { colorType: "auto" };
    case "rgb": {
      const channels = color.r !== void 0 && color.g !== void 0 && color.b !== void 0 ? [color.r, color.g, color.b] : parseColorHex(color.hex);
      return channels ? { b: channels[2], colorType: "rgb", g: channels[1], r: channels[0] } : void 0;
    }
    case "argb": {
      const normalized = color.hex?.replace(/^#/, "");
      const channels = normalized && /^[0-9a-f]{8}$/i.test(normalized) ? [0, 2, 4, 6].map((offset) => Number.parseInt(normalized.slice(offset, offset + 2), 16)) : color.a !== void 0 && color.r !== void 0 && color.g !== void 0 && color.b !== void 0 ? [color.a, color.r, color.g, color.b] : null;
      return channels ? { a: channels[0], b: channels[3], colorType: "argb", g: channels[2], r: channels[1] } : void 0;
    }
    case "theme":
      return color.themeIndex === void 0 ? void 0 : { colorType: "theme", index: color.themeIndex, tint: color.tint ?? 0 };
    case "indexed":
      return color.paletteIndex === void 0 ? void 0 : { colorType: "indexed", index: color.paletteIndex };
  }
}
function xlsxFontToDukeFont(font) {
  return {
    bold: font.bold,
    charset: font.charset,
    color: xlsxColorToDukeColor(font.color),
    family: font.family,
    italic: font.italic,
    name: font.name,
    scheme: font.scheme,
    size: font.size,
    strikethrough: font.strikethrough,
    underline: font.underline,
    verticalAlign: font.verticalAlign
  };
}
function xlsxCaptionToDukeText(caption) {
  if (typeof caption === "string") {
    return { runs: [{ text: caption }] };
  }
  return {
    horizontalAlignment: caption.horizontalAlignment,
    runs: caption.runs.map((run) => ({
      font: run.font ? xlsxFontToDukeFont(run.font) : void 0,
      text: run.text
    })),
    verticalAlignment: caption.verticalAlignment
  };
}
function xlsxFormControlKindToDukeKind(kind) {
  switch (kind.kind) {
    case "button":
    case "label":
      return { caption: xlsxCaptionToDukeText(kind.caption), kind: kind.kind };
    case "checkbox":
      return { ...kind, caption: xlsxCaptionToDukeText(kind.caption) };
    case "optionButton":
      return { ...kind, caption: xlsxCaptionToDukeText(kind.caption) };
    case "groupBox":
      return { ...kind, caption: xlsxCaptionToDukeText(kind.caption) };
    case "editbox":
      return {
        caption: xlsxCaptionToDukeText(kind.caption),
        kind: "unknown",
        legacyObjectType: kind.legacyObjectType,
        objectType: "EditBox"
      };
    case "unknown":
      return {
        caption: kind.caption ? xlsxCaptionToDukeText(kind.caption) : void 0,
        kind: "unknown",
        legacyObjectType: kind.legacyObjectType,
        objectType: kind.objectType
      };
    default:
      return { ...kind };
  }
}
function dukeFormControlKindToInput(kind) {
  if (kind.kind === "optionButton") {
    return { ...kind, state: kind.state === "checked" ? "checked" : "unchecked" };
  }
  if (kind.kind === "unknown") {
    return {
      caption: kind.caption,
      kind: "unknown",
      legacyObjectType: kind.legacyObjectType,
      objectType: kind.objectType
    };
  }
  return { ...kind };
}
function formControlInputFromDukeControl(control2) {
  return {
    altText: control2.altText,
    ...control2.anchor ? { anchor: control2.anchor } : { transform: control2.transform },
    formControl: {
      kind: dukeFormControlKindToInput(control2.formControl.kind),
      macroName: control2.formControl.macroName,
      rawClientData: control2.formControl.rawClientData,
      rawObj: control2.formControl.rawObj,
      rawProperties: control2.formControl.rawProperties
    },
    hidden: control2.hidden,
    kind: "formControl",
    locked: control2.locked,
    name: control2.name,
    printable: control2.printable,
    title: control2.title
  };
}
function xlsxFormControlInputToDukeDrawing(input) {
  return {
    altText: input.altText,
    anchor: xlsxAnchorToDukeDrawingAnchor(input.anchor, input.editAs),
    formControl: {
      kind: xlsxFormControlKindToDukeKind(input.kind),
      macroName: input.macroName,
      rawClientData: input.rawClientData ?? [],
      rawObj: input.kind.kind === "editbox" || input.kind.kind === "unknown" ? input.kind.rawObj : void 0,
      rawProperties: input.kind.kind === "editbox" || input.kind.kind === "unknown" ? input.kind.rawProperties ?? [] : []
    },
    hidden: input.hidden,
    kind: "formControl",
    locked: input.locked,
    name: input.name,
    printable: input.printable,
    title: input.title
  };
}
function reconcileCheckedOptionButtons(worksheet) {
  const checkedPaths = worksheet.formControls.flatMap((control2) => control2.formControl.kind.kind === "optionButton" && control2.formControl.kind.state === "checked" ? [control2.drawingPath] : []);
  for (const path of checkedPaths) {
    const current = worksheet.formControls.find((control2) => control2.drawingPath.length === path.length && control2.drawingPath.every((segment, index) => segment === path[index]));
    if (current?.formControl.kind.kind === "optionButton" && current.formControl.kind.state === "checked") {
      worksheet.setFormControlCheckState(current.drawingPath, "checked");
    }
  }
}
function formControlLinkTouchesPivot(workbook, pivots, sourceSheetIndex, kind) {
  if (!pivots.length || !("cellLink" in kind) || !kind.cellLink) return false;
  const names = workbook.namedRanges;
  const sheetNames = workbook.sheetNames;
  const resolve2 = (reference, sheetIndex, depth) => {
    if (depth === 0) return false;
    let address2 = reference.trim().replace(/^=\s*/, "");
    const separator = address2.lastIndexOf("!");
    if (separator >= 0) {
      const rawSheet = address2.slice(0, separator).trim();
      const sheetName = rawSheet.startsWith("'") && rawSheet.endsWith("'") ? rawSheet.slice(1, -1).replace(/''/g, "'") : rawSheet;
      sheetIndex = sheetNames.findIndex((name) => name.toLowerCase() === sheetName.toLowerCase());
      if (sheetIndex < 0) return false;
      address2 = address2.slice(separator + 1);
    }
    const parsed = parseXlsxRange(address2);
    if (parsed?.kind === "cells" && !parsed.sheetName && parsed.range.start.row === parsed.range.end.row && parsed.range.start.col === parsed.range.end.col) {
      return Boolean(findIntersectingPivot(pivots, sheetNames[sheetIndex], parsed.range));
    }
    const matching = names.filter((name) => name.name.toLowerCase() === address2.toLowerCase());
    const named = matching.find((name) => name.sheetIndex === sheetIndex) ?? matching.find((name) => name.sheetIndex == null);
    return named ? resolve2(named.refersTo, sheetIndex, depth - 1) : false;
  };
  return resolve2(kind.cellLink, sourceSheetIndex, 4);
}
function formControlInteractionChanged(current, next) {
  if (current.kind !== next.kind) {
    return true;
  }
  if ("cellLink" in current && "cellLink" in next && current.cellLink !== next.cellLink) {
    return true;
  }
  switch (current.kind) {
    case "checkbox":
    case "optionButton":
      return next.kind === current.kind && current.state !== next.state;
    case "dropdown":
      return next.kind === "dropdown" && current.selected !== next.selected;
    case "listBox":
      return next.kind === "listBox" && (current.selection !== next.selection || current.selected.length !== (next.selected?.length ?? 0) || current.selected.some((value, index) => value !== next.selected?.[index]));
    case "scrollbar":
    case "spinner":
      return next.kind === current.kind && current.value !== next.value;
    default:
      return false;
  }
}
function parseWorksheetFreezePanes(worksheet) {
  const rawFreezePanes = worksheet.freezePanes;
  const row2 = typeof rawFreezePanes?.row === "number" && rawFreezePanes.row >= 0 ? rawFreezePanes.row : null;
  const col = typeof rawFreezePanes?.col === "number" && rawFreezePanes.col >= 0 ? rawFreezePanes.col : null;
  if (row2 === null && col === null) {
    return null;
  }
  return {
    col: col ?? 0,
    row: row2 ?? 0
  };
}
function parseWorksheetDataValidations(worksheet) {
  const rawDataValidations = Array.isArray(worksheet.dataValidations) ? worksheet.dataValidations : [];
  return rawDataValidations.flatMap((entry) => {
    if (!entry || typeof entry !== "object") {
      return [];
    }
    const validation = entry;
    const ranges = Array.isArray(validation.ranges) ? validation.ranges.flatMap((range) => {
      if (typeof range !== "string") {
        return [];
      }
      const parsedRange = parseA1RangeReference(range);
      return parsedRange ? [parsedRange] : [];
    }) : [];
    const validationType = typeof validation.validationType === "string" ? validation.validationType : null;
    if (!validationType || ranges.length === 0) {
      return [];
    }
    return [{
      allowBlank: typeof validation.allowBlank === "boolean" ? validation.allowBlank : void 0,
      errorMessage: typeof validation.errorMessage === "string" ? validation.errorMessage : void 0,
      errorStyle: typeof validation.errorStyle === "string" ? validation.errorStyle : void 0,
      inputMessage: typeof validation.inputMessage === "string" ? validation.inputMessage : void 0,
      listSource: typeof validation.listSource === "string" ? validation.listSource : void 0,
      ranges,
      showDropdown: typeof validation.showDropdown === "boolean" ? validation.showDropdown : void 0,
      showErrorAlert: typeof validation.showErrorAlert === "boolean" ? validation.showErrorAlert : void 0,
      showInputMessage: typeof validation.showInputMessage === "boolean" ? validation.showInputMessage : void 0,
      validationType
    }];
  });
}
function normalizeRange(range) {
  return {
    start: {
      row: Math.min(range.start.row, range.end.row),
      col: Math.min(range.start.col, range.end.col)
    },
    end: {
      row: Math.max(range.start.row, range.end.row),
      col: Math.max(range.start.col, range.end.col)
    }
  };
}
function rangeToA1(range) {
  const normalized = normalizeRange(range);
  const start = cellAddressToA1(normalized.start);
  const end = cellAddressToA1(normalized.end);
  return start === end ? start : `${start}:${end}`;
}
function rangeContainsCell(range, cell) {
  const normalized = normalizeRange(range);
  return cell.row >= normalized.start.row && cell.row <= normalized.end.row && cell.col >= normalized.start.col && cell.col <= normalized.end.col;
}
function rangesIntersect(a, b) {
  return a.start.row <= b.end.row && a.end.row >= b.start.row && a.start.col <= b.end.col && a.end.col >= b.start.col;
}
function mapWorksheetTables(worksheet, autoFilterRanges = []) {
  const rawTables = worksheet?.tables ?? [];
  const mappedTables = rawTables.flatMap((table, index) => {
    const rawColumns = Array.isArray(table.columns) ? table.columns : [];
    const rawName = typeof table.name === "string" ? table.name : `Table${index + 1}`;
    const rawDisplayName = typeof table.displayName === "string" ? table.displayName : typeof table.name === "string" ? table.name : `Table ${index + 1}`;
    const rawReference = typeof table.reference === "string" ? table.reference : "";
    const reference = rawReference;
    const parsedRange = parseA1RangeReference(reference);
    if (!parsedRange) {
      return [];
    }
    return [{
      columns: rawColumns.map((column, columnIndex) => ({
        id: typeof column.id === "number" ? column.id ?? columnIndex + 1 : columnIndex + 1,
        index: columnIndex,
        name: typeof column.name === "string" ? column.name ?? `Column ${columnIndex + 1}` : `Column ${columnIndex + 1}`
      })),
      displayName: rawDisplayName,
      end: parsedRange.end,
      headerRowCount: resolveWorkbookTableCount(table.headerRowCount, 1),
      headerRowCellStyle: typeof table.headerRowCellStyle === "string" ? table.headerRowCellStyle : void 0,
      name: rawName,
      reference,
      start: parsedRange.start,
      styleInfo: table.styleInfo,
      totalsRowCount: resolveWorkbookTableCount(table.totalsRowCount, 0),
      totalsRowShown: resolveWorkbookTableBoolean(table.totalsRowShown)
    }];
  });
  const existingReferences = new Set(mappedTables.map((table) => table.reference));
  const mappedAutoFilterTables = autoFilterRanges.flatMap((range, index) => {
    const reference = rangeToA1(range);
    if (existingReferences.has(reference)) {
      return [];
    }
    const columnCount = Math.max(0, range.end.col - range.start.col + 1);
    const columns = Array.from({ length: columnCount }, (_, columnIndex) => {
      const headerValue = worksheet ? decodeHtmlEntities(worksheet.getFormattedValueAt(range.start.row, range.start.col + columnIndex) ?? "") : "";
      return {
        id: columnIndex + 1,
        index: columnIndex,
        name: headerValue.trim().length > 0 ? headerValue : `Column ${columnIndex + 1}`
      };
    });
    return [{
      columns,
      displayName: `AutoFilter ${index + 1}`,
      end: range.end,
      headerRowCount: 1,
      name: `__autofilter_${index + 1}_${reference}`,
      reference,
      start: range.start,
      totalsRowCount: 0,
      totalsRowShown: false
    }];
  });
  return [...mappedTables, ...mappedAutoFilterTables];
}
function resolveWorkbookTableCount(value, fallback) {
  if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10);
    if (Number.isFinite(parsed) && parsed >= 0) {
      return parsed;
    }
  }
  return fallback;
}
function resolveWorkbookTableBoolean(value) {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    return value !== 0;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "0" || normalized === "false" || normalized === "") {
      return false;
    }
    if (normalized === "1" || normalized === "true") {
      return true;
    }
  }
  return false;
}
function fileStem(fileName) {
  const normalized = fileName.trim();
  const lastDot = normalized.lastIndexOf(".");
  return lastDot > 0 ? normalized.slice(0, lastDot) : normalized;
}
function pxToSheetRowHeight(heightPx) {
  return Math.max(heightPx, MIN_ROW_HEIGHT_PX) / 1.33;
}
function cssColor(color) {
  if (!color?.hex) {
    return null;
  }
  const hex = String(color.hex);
  const rgb = hex.length === 8 ? hex.slice(2) : hex;
  return `#${rgb}`;
}
function mapBorder(edge) {
  const color = cssColor(edge.color) ?? "#000000";
  const widthMap = {
    dashed: "1px",
    dotted: "1px",
    double: "3px",
    hair: "1px",
    medium: "2px",
    thick: "3px",
    thin: "1px"
  };
  const styleMap = {
    dashDot: "dashed",
    dashDotDot: "dotted",
    dashed: "dashed",
    dotted: "dotted",
    double: "double",
    hair: "solid",
    medium: "solid",
    mediumDashDot: "dashed",
    mediumDashDotDot: "dotted",
    mediumDashed: "dashed",
    slantDashDot: "dashed",
    thick: "solid",
    thin: "solid"
  };
  return `${widthMap[edge.style] ?? "1px"} ${styleMap[edge.style] ?? "solid"} ${color}`;
}
function decodeHtmlEntities(value) {
  return value.replace(/&quot;/g, '"').replace(/&#34;/g, '"').replace(/&apos;/g, "'").replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}
function pushHistoryEntry(stack2, entry) {
  stack2.push(entry);
  if (stack2.length > HISTORY_LIMIT) {
    stack2.shift();
  }
}
function normalizeCellValue(value) {
  return value ?? "";
}
function cloneCellStyle(style) {
  if (!style || typeof style !== "object") {
    return style;
  }
  if (typeof structuredClone === "function") {
    try {
      return structuredClone(style);
    } catch {
    }
  }
  try {
    return JSON.parse(JSON.stringify(style));
  } catch {
    return style;
  }
}
function applyCellMutationState(worksheet, cell, state) {
  if (state.formula) {
    worksheet.setFormula(cellAddressToA1(cell), state.formula);
  } else if (state.valueSnapshot) {
    worksheet.restoreValueSnapshotAt(cell.row, cell.col, state.valueSnapshot);
  } else {
    worksheet.setCell(cellAddressToA1(cell), normalizeCellValue(state.value));
  }
  if (state.style && typeof state.style === "object") {
    worksheet.setCellStyleAt(cell.row, cell.col, state.style);
  }
}
function escapeHtml(value) {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function createAbortError2() {
  if (typeof DOMException !== "undefined") {
    return new DOMException("Aborted", "AbortError");
  }
  const error = new Error("Aborted");
  error.name = "AbortError";
  return error;
}
function isAbortError(error) {
  return error instanceof Error && error.name === "AbortError";
}
async function resolveWorkbookBuffer({ file, src }, signal) {
  let buffer;
  if (signal?.aborted) {
    throw createAbortError2();
  }
  if (file) {
    buffer = file;
  } else if (src) {
    let response;
    try {
      response = await fetch(src, { signal });
    } catch (error) {
      if (isAbortError(error)) {
        throw error;
      }
      throw new Error(
        "Failed to fetch workbook. The remote URL may be blocked by CORS, unavailable, or not directly downloadable from the browser."
      );
    }
    if (!response.ok) {
      throw new Error(`Failed to fetch workbook (status ${response.status})`);
    }
    buffer = await response.arrayBuffer();
  } else {
    throw new Error("Either `file` or `src` must be provided.");
  }
  return buffer;
}
function downloadArrayBuffer(file, fileName) {
  const blob = new Blob([file], { type: XLSX_MIME_TYPE });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = fileName;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}
function downloadBytes(bytes, fileName, mimeType) {
  const normalizedBytes = new Uint8Array(bytes.byteLength);
  normalizedBytes.set(bytes);
  const blob = new Blob([normalizedBytes], { type: mimeType });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = fileName;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}
function downloadText(text, fileName, mimeType) {
  const blob = new Blob([text], { type: mimeType });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = fileName;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
}
function downloadUrl(src, fileName) {
  const anchor = document.createElement("a");
  anchor.href = src;
  anchor.download = fileName;
  anchor.rel = "noreferrer";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
}
function useXlsxViewerController(options2) {
  const {
    allowFreezeInReadOnly = false,
    allowHideInReadOnly = false,
    allowResizeInReadOnly = false,
    deferLoadingAboveBytes = DEFAULT_DEFER_LOADING_ABOVE_BYTES,
    file,
    fileName,
    locale = "en-US",
    messages: messageOverrides,
    maxFileSizeBytes = DEFAULT_MAX_FILE_SIZE_BYTES,
    readOnly: requestedReadOnly = false,
    readOnlyAboveBytes = 0,
    showHiddenSheets = false,
    skipXmlParsing = false,
    src,
    useWorker = true
  } = options2;
  const messages = React.useMemo(() => resolveMessages(locale, messageOverrides), [locale, messageOverrides]);
  const [isLoading, setIsLoading] = React.useState(Boolean(file ?? src));
  const [error, setError] = React.useState(null);
  const [workbook, setWorkbook] = React.useState(null);
  const [readOnlyLayouts, setReadOnlyLayouts] = React.useState({});
  const [workbookSheets, setSheets] = React.useState([]);
  const [chartsByWorkbookSheetIndex, setChartsByWorkbookSheetIndex] = React.useState([]);
  const [chartsheets, setChartsheets] = React.useState([]);
  const [tabs, setTabs] = React.useState([]);
  const [isChartsLoading, setIsChartsLoading] = React.useState(false);
  const [workerTablesByWorkbookSheetIndex, setWorkerTablesByWorkbookSheetIndex] = React.useState([]);
  const [pivotTables, setPivotTables] = React.useState([]);
  const [pivotFieldListVisible, setPivotFieldListVisibleState] = React.useState(false);
  const pivotFieldListRequestedRef = React.useRef(true);
  const setPivotFieldListVisible = React.useCallback((visible) => {
    pivotFieldListRequestedRef.current = visible;
    setPivotFieldListVisibleState(visible);
  }, []);
  const [formControlsByWorkbookSheetIndex, setFormControlsByWorkbookSheetIndex] = React.useState([]);
  const [imagesByWorkbookSheetIndex, setImagesByWorkbookSheetIndex] = React.useState([]);
  const [shapesByWorkbookSheetIndex, setShapesByWorkbookSheetIndex] = React.useState([]);
  const [activeSheetIndex, setActiveSheetIndexState] = React.useState(0);
  const [activeTabIndex, setActiveTabIndexState] = React.useState(0);
  const [zoomScaleOverridesByTabId, setZoomScaleOverridesByTabId] = React.useState({});
  const [activeCell, setActiveCell] = React.useState(null);
  const [selectionRanges, setSelectionRanges] = React.useState([]);
  const selection = selectionRanges.at(-1) ?? null;
  const setSelection = React.useCallback((range) => {
    setSelectionRanges(range ? [range] : []);
  }, []);
  const [highlightedRanges, setHighlightedRanges] = React.useState([]);
  const [selectedChartId, setSelectedChartId] = React.useState(null);
  const [selectedChartElement, setSelectedChartElement] = React.useState(null);
  const [selectedImageId, setSelectedImageId] = React.useState(null);
  const [revision, setRevision] = React.useState(0);
  const selectionAnchorRef = React.useRef(null);
  const undoStackRef = React.useRef([]);
  const redoStackRef = React.useRef([]);
  const isApplyingHistoryRef = React.useRef(false);
  const [historyRevision, setHistoryRevision] = React.useState(0);
  const [shouldAutoCalculate, setShouldAutoCalculate] = React.useState(false);
  const [workerCellSnapshotRevision, setWorkerCellSnapshotRevision] = React.useState(0);
  const [isWorkerBacked, setIsWorkerBacked] = React.useState(false);
  const [sortState, setSortState] = React.useState(null);
  const [forcedReadOnly, setForcedReadOnly] = React.useState(false);
  const releaseXmlRecordsRef = React.useRef(null);
  const loadGenerationRef = React.useRef(0);
  const deferredBufferRef = React.useRef(null);
  const [deferredLoadFileSize, setDeferredLoadFileSize] = React.useState(null);
  const retainedObjectUrlsRef = React.useRef(/* @__PURE__ */ new Set());
  const imageAssetsRef = React.useRef(null);
  const chartAssetsRef = React.useRef(null);
  const chartLoadRequestTokenRef = React.useRef(0);
  const chartDisplayFallbackCleanupRef = React.useRef(null);
  const sheetOriginsRef = React.useRef([]);
  const workerClientRef = React.useRef(null);
  const workerCellSnapshotCacheRef = React.useRef(/* @__PURE__ */ new Map());
  const displayFileName = React.useMemo(() => resolveDisplayFileName(src, fileName), [fileName, src]);
  const shouldDeferLoading = deferLoadingAboveBytes > 0;
  const readOnly = requestedReadOnly || forcedReadOnly;
  const sheets = React.useMemo(() => readOnly ? workbookSheets.map((sheet) => applyReadOnlyLayout(sheet, readOnlyLayouts[sheet.workbookSheetIndex])) : workbookSheets, [readOnly, readOnlyLayouts, workbookSheets]);
  const drawingMutationEpoch = React.useRef(0);
  const drawingMutationState = React.useRef({ workbook, revision, readOnly, activeCell, activeSheetIndex });
  drawingMutationState.current = { workbook, revision, readOnly, activeCell, activeSheetIndex };
  const canResize = !readOnly || requestedReadOnly && allowResizeInReadOnly && !forcedReadOnly;
  const shouldForceReadOnlyForBuffer = React.useCallback((bufferByteLength) => !requestedReadOnly && readOnlyAboveBytes > 0 && bufferByteLength > readOnlyAboveBytes, [readOnlyAboveBytes, requestedReadOnly]);
  const disposeWorkerClient = React.useCallback(() => {
    workerClientRef.current?.dispose();
    workerClientRef.current = null;
  }, []);
  const getWorkerClient = React.useCallback(() => {
    if (!workerClientRef.current) {
      workerClientRef.current = new XlsxWorkerClient(useWorker);
    }
    return workerClientRef.current;
  }, [useWorker]);
  const clearImageAssets = React.useCallback(() => {
    releaseXmlRecordsRef.current?.();
    releaseXmlRecordsRef.current = null;
    for (const url of retainedObjectUrlsRef.current) URL.revokeObjectURL(url);
    retainedObjectUrlsRef.current.clear();
    revokeWorkbookImageAssets(imageAssetsRef.current);
    imageAssetsRef.current = null;
    sheetOriginsRef.current = [];
    setFormControlsByWorkbookSheetIndex([]);
    setImagesByWorkbookSheetIndex([]);
    setShapesByWorkbookSheetIndex([]);
  }, []);
  const clearChartAssets = React.useCallback(() => {
    chartLoadRequestTokenRef.current += 1;
    chartDisplayFallbackCleanupRef.current?.();
    chartDisplayFallbackCleanupRef.current = null;
    chartAssetsRef.current = null;
    setChartsByWorkbookSheetIndex([]);
    setChartsheets([]);
    setTabs([]);
    setIsChartsLoading(false);
  }, []);
  const setImageAssets = React.useCallback((assets) => {
    for (const url of imageAssetsRef.current?.objectUrls ?? []) retainedObjectUrlsRef.current.add(url);
    imageAssetsRef.current = assets;
    sheetOriginsRef.current = assets?.sheetOrigins.slice() ?? [];
    setFormControlsByWorkbookSheetIndex(assets?.formControlsByWorkbookSheetIndex ?? []);
    setImagesByWorkbookSheetIndex(assets?.imagesByWorkbookSheetIndex ?? []);
    setShapesByWorkbookSheetIndex(assets?.shapesByWorkbookSheetIndex ?? []);
  }, []);
  const setChartAssets = React.useCallback((assets) => {
    const previous = chartAssetsRef.current;
    if (assets && previous && assets !== previous) {
      const byPath = new Map(previous.chartsByWorkbookSheetIndex.flat().filter((chart) => chart.chartPath).map((chart) => [chart.chartPath, chart]));
      const used = new Set([...byPath.values()].map((chart) => chart.id));
      const origins = /* @__PURE__ */ new Map();
      assets.chartsByWorkbookSheetIndex = assets.chartsByWorkbookSheetIndex.map((charts2) => charts2.map((chart) => {
        const prior = chart.chartPath ? byPath.get(chart.chartPath) : void 0;
        const oldId = chart.id;
        const id = prior?.id ?? (used.has(oldId) ? `chart-${crypto.randomUUID()}` : oldId);
        used.add(id);
        const origin = assets.chartOriginsById.get(oldId);
        if (origin) origins.set(id, origin);
        if (oldId === id) return chart;
        const series = chart.series.map((entry, index) => ({ ...entry, id: `${id}-series-${index}` }));
        let ordinal = 0;
        return { ...chart, id, series, typeGroups: chart.typeGroups?.map((group) => ({ ...group, series: group.series.map(() => series[ordinal++]) })) };
      }));
      assets.chartOriginsById = origins;
      for (const sheet of assets.chartsheets) sheet.chartIds = assets.chartsByWorkbookSheetIndex[sheet.workbookSheetIndex ?? -1]?.map((chart) => chart.id) ?? sheet.chartIds;
    }
    chartAssetsRef.current = assets;
    setChartsByWorkbookSheetIndex(assets?.chartsByWorkbookSheetIndex ?? []);
    setChartsheets(assets?.chartsheets ?? []);
    setTabs(assets?.tabs ?? []);
    setIsChartsLoading(false);
  }, []);
  const ensureChartAssetsHydrated = React.useCallback((targetWorkbook, targetSheets) => {
    const currentAssets = chartAssetsRef.current;
    if (currentAssets && (currentAssets.chartOriginsById.size > 0 || !targetWorkbook || !imageAssetsRef.current)) {
      return currentAssets;
    }
    if (!targetWorkbook || !imageAssetsRef.current) {
      return chartAssetsRef.current;
    }
    const assets = loadWorkbookChartAssets(
      targetWorkbook,
      imageAssetsRef.current,
      buildVisibleSheetIndexMap(targetSheets),
      showHiddenSheets
    );
    chartAssetsRef.current = assets;
    return assets;
  }, [showHiddenSheets]);
  const loadPreparedWorkbook = React.useCallback(async (buffer, isCurrent = () => true) => {
    const defaultFonts = loadSpreadsheetFonts(["Calibri", "Arial"]);
    const forced = shouldForceReadOnlyForBuffer(buffer.byteLength);
    const editable = !requestedReadOnly && !forced;
    const snapshot = await getWorkerClient().loadWorkbook(buffer, skipXmlParsing, showHiddenSheets, editable || !useWorker);
    if (!isCurrent()) return;
    await Promise.all([defaultFonts, loadSpreadsheetFonts(snapshot.fontFamilies)]);
    if (!isCurrent()) return;
    const nextWorkbook = snapshot.workbookSnapshot ? (await getSheetsWasmModule()).Workbook.fromSnapshot(snapshot.workbookSnapshot) : null;
    if (!isCurrent()) {
      nextWorkbook?.free();
      return;
    }
    releaseXmlRecordsRef.current?.();
    releaseXmlRecordsRef.current = restoreWorkbookXmlRecords(snapshot.xmlRecords);
    setForcedReadOnly(forced);
    setImageAssets(snapshot.imageAssets);
    setWorkbook(nextWorkbook);
    setSheets(snapshot.sheets);
    setChartAssets({ chartsByWorkbookSheetIndex: snapshot.chartsByWorkbookSheetIndex, chartsheets: snapshot.chartsheets, tabs: snapshot.tabs, chartOriginsById: snapshot.chartOriginsById });
    setFormControlsByWorkbookSheetIndex(snapshot.formControlsByWorkbookSheetIndex);
    setWorkerTablesByWorkbookSheetIndex(snapshot.tablesByWorkbookSheetIndex);
    setPivotTables(snapshot.pivotTables);
    setShouldAutoCalculate(editable && snapshot.shouldAutoCalculate);
    setIsWorkerBacked(!nextWorkbook);
    setSortState(null);
    setIsLoading(false);
  }, [getWorkerClient, requestedReadOnly, setChartAssets, setImageAssets, shouldForceReadOnlyForBuffer, showHiddenSheets, skipXmlParsing, useWorker]);
  const refreshWorkbookState = React.useCallback((targetWorkbook) => {
    setPivotTables(readPivotTables(targetWorkbook));
    const currentFormControls = imageAssetsRef.current?.formControlsByWorkbookSheetIndex ?? [];
    const nextFormControls = refreshWorkbookFormControls(
      targetWorkbook,
      currentFormControls,
      imageAssetsRef.current?.themePalette
    );
    if (imageAssetsRef.current) {
      imageAssetsRef.current.formControlsByWorkbookSheetIndex = nextFormControls;
    }
    setFormControlsByWorkbookSheetIndex(nextFormControls);
    const nextSheets = buildSheetList(
      targetWorkbook,
      imageAssetsRef.current?.sheetStatesByWorkbookSheetIndex,
      imageAssetsRef.current?.themePalette,
      imageAssetsRef.current?.styleById,
      imageAssetsRef.current?.namedCellStyleByName,
      imageAssetsRef.current?.tableStyleByName,
      showHiddenSheets
    );
    setSheets(nextSheets);
    setChartAssets(
      loadWorkbookChartAssets(
        targetWorkbook,
        imageAssetsRef.current,
        buildVisibleSheetIndexMap(nextSheets),
        showHiddenSheets
      )
    );
    setRevision((current) => current + 1);
  }, [setChartAssets, showHiddenSheets]);
  React.useEffect(() => () => {
    releaseXmlRecordsRef.current?.();
    releaseXmlRecordsRef.current = null;
    chartDisplayFallbackCleanupRef.current?.();
    chartDisplayFallbackCleanupRef.current = null;
    for (const url of retainedObjectUrlsRef.current) URL.revokeObjectURL(url);
    retainedObjectUrlsRef.current.clear();
    revokeWorkbookImageAssets(imageAssetsRef.current);
    disposeWorkerClient();
  }, [disposeWorkerClient]);
  React.useEffect(() => {
    loadGenerationRef.current += 1;
    setReadOnlyLayouts({});
    if (!file && !src) {
      disposeWorkerClient();
      setForcedReadOnly(false);
      setWorkbook(null);
      setPivotTables([]);
      setSheets([]);
      clearChartAssets();
      setWorkerTablesByWorkbookSheetIndex([]);
      clearImageAssets();
      setError(null);
      setIsLoading(false);
      setIsWorkerBacked(false);
      deferredBufferRef.current = null;
      setDeferredLoadFileSize(null);
      setActiveSheetIndexState(0);
      setActiveTabIndexState(0);
      setActiveCell(null);
      setSelection(null);
      setHighlightedRanges([]);
      setSelectedChartId(null);
      setSelectedChartElement(null);
      setSelectedImageId(null);
      selectionAnchorRef.current = null;
      undoStackRef.current = [];
      redoStackRef.current = [];
      setHistoryRevision(0);
      setShouldAutoCalculate(false);
      workerCellSnapshotCacheRef.current.clear();
      setWorkerCellSnapshotRevision(0);
      setSortState(null);
      setZoomScaleOverridesByTabId({});
      setRevision(0);
      return;
    }
    let isCurrent = true;
    const abortController = new AbortController();
    setIsLoading(true);
    setError(null);
    clearImageAssets();
    clearChartAssets();
    setWorkerTablesByWorkbookSheetIndex([]);
    setIsWorkerBacked(false);
    deferredBufferRef.current = null;
    setDeferredLoadFileSize(null);
    setActiveSheetIndexState(0);
    setActiveTabIndexState(0);
    setActiveCell(null);
    setSelection(null);
    setHighlightedRanges([]);
    setSelectedChartId(null);
    setSelectedChartElement(null);
    setSelectedImageId(null);
    selectionAnchorRef.current = null;
    undoStackRef.current = [];
    redoStackRef.current = [];
    setHistoryRevision(0);
    setShouldAutoCalculate(false);
    workerCellSnapshotCacheRef.current.clear();
    setWorkerCellSnapshotRevision(0);
    setSortState(null);
    setZoomScaleOverridesByTabId({});
    setRevision(0);
    disposeWorkerClient();
    void resolveWorkbookBuffer({ file, src }, abortController.signal).then(async (buffer) => {
      if (!isCurrent || abortController.signal.aborted) {
        return;
      }
      if (maxFileSizeBytes > 0 && buffer.byteLength > maxFileSizeBytes) {
        throw new XlsxFileSizeLimitExceededError(buffer.byteLength, maxFileSizeBytes);
      }
      if (shouldDeferLoading && buffer.byteLength > deferLoadingAboveBytes) {
        deferredBufferRef.current = buffer;
        setDeferredLoadFileSize(buffer.byteLength);
        setWorkbook(null);
        setPivotTables([]);
        setSheets([]);
        clearChartAssets();
        setWorkerTablesByWorkbookSheetIndex([]);
        setIsLoading(false);
        return;
      }
      await loadPreparedWorkbook(buffer, () => isCurrent && !abortController.signal.aborted);
    }).catch((nextError) => {
      if (!isCurrent || isAbortError(nextError)) {
        return;
      }
      setWorkbook(null);
      setPivotTables([]);
      setSheets([]);
      clearChartAssets();
      setWorkerTablesByWorkbookSheetIndex([]);
      clearImageAssets();
      setShouldAutoCalculate(false);
      setIsWorkerBacked(false);
      setSortState(null);
      setError(nextError instanceof Error ? nextError : new Error("Could not load workbook."));
      setIsLoading(false);
    });
    return () => {
      isCurrent = false;
      loadGenerationRef.current += 1;
      abortController.abort();
      disposeWorkerClient();
    };
  }, [
    clearChartAssets,
    clearImageAssets,
    deferLoadingAboveBytes,
    disposeWorkerClient,
    file,
    getWorkerClient,
    loadPreparedWorkbook,
    maxFileSizeBytes,
    setImageAssets,
    shouldDeferLoading,
    shouldForceReadOnlyForBuffer,
    src,
    showHiddenSheets
  ]);
  const activeTab = tabs[activeTabIndex] ?? null;
  const activeSheet = activeTab?.kind === "sheet" ? sheets[activeTab.sheetIndex ?? -1] ?? null : null;
  const deferredMetadataCell = React.useDeferredValue(activeCell);
  const deferredMetadataSheet = React.useDeferredValue(activeSheet);
  const activeZoomTabKey = activeTab?.id ?? DEFAULT_ZOOM_TAB_KEY;
  const defaultZoomScale = React.useMemo(
    () => resolveDefaultZoomScale(activeTab, activeSheet),
    [activeSheet, activeTab]
  );
  const zoomScale = React.useMemo(
    () => clampZoomScale(zoomScaleOverridesByTabId[activeZoomTabKey] ?? defaultZoomScale),
    [activeZoomTabKey, defaultZoomScale, zoomScaleOverridesByTabId]
  );
  const canZoomIn = zoomScale < MAX_ZOOM_SCALE;
  const canZoomOut = zoomScale > MIN_ZOOM_SCALE;
  React.useEffect(() => {
    setActiveCell(null);
    setSelection(null);
    setSelectedChartId(null);
    setSelectedChartElement(null);
    setSelectedImageId(null);
    selectionAnchorRef.current = null;
    setSortState(null);
  }, [activeTabIndex]);
  const setActiveSheetIndex = React.useCallback((index) => {
    setActiveSheetIndexState((currentIndex) => {
      if (index < 0 || index >= sheets.length) {
        return currentIndex;
      }
      const targetSheet = sheets[index];
      const tabIndex = tabs.findIndex((tab) => tab.kind === "sheet" && tab.workbookSheetIndex === targetSheet?.workbookSheetIndex);
      if (tabIndex >= 0) {
        setActiveTabIndexState(tabIndex);
      }
      return index;
    });
  }, [sheets, tabs]);
  const setActiveTabIndex = React.useCallback((index) => {
    setActiveTabIndexState((currentIndex) => {
      if (index < 0 || index >= tabs.length) {
        return currentIndex;
      }
      const targetTab = tabs[index];
      if (targetTab?.kind === "sheet" && typeof targetTab.sheetIndex === "number") {
        setActiveSheetIndexState(targetTab.sheetIndex);
      }
      return index;
    });
  }, [tabs]);
  const highlightRanges = React.useCallback((references, options3 = {}) => {
    const inputs = typeof references === "string" ? [references] : references;
    if (!Array.isArray(inputs) || isLoading || error) {
      return false;
    }
    const nextHighlights = [];
    let firstSheetIndex = activeSheetIndex;
    for (const reference of inputs) {
      const parsed = parseXlsxRange(reference);
      if (!parsed) {
        return false;
      }
      const requestedSheetName = parsed.sheetName?.toLowerCase();
      const sheetIndex = requestedSheetName === void 0 ? options3.sheetIndex ?? activeSheetIndex : sheets.findIndex((sheet2) => sheet2.name.toLowerCase() === requestedSheetName);
      const sheet = Number.isInteger(sheetIndex) ? sheets[sheetIndex] : void 0;
      if (!sheet) {
        return false;
      }
      if (nextHighlights.length === 0) {
        firstSheetIndex = sheetIndex;
      }
      nextHighlights.push({
        ...parsed,
        autoScroll: nextHighlights.length === 0 && (options3.autoScroll ?? true),
        sheetName: sheet.name,
        workbookSheetIndex: sheet.workbookSheetIndex
      });
    }
    setHighlightedRanges(nextHighlights);
    if (nextHighlights[0]?.autoScroll) {
      setActiveSheetIndex(firstSheetIndex);
    }
    return true;
  }, [activeSheetIndex, error, isLoading, setActiveSheetIndex, sheets]);
  const clearHighlightedRanges = React.useCallback(() => setHighlightedRanges([]), []);
  const setZoomScale = React.useCallback((nextZoomScale) => {
    const normalizedZoomScale = clampZoomScale(nextZoomScale);
    setZoomScaleOverridesByTabId((current) => {
      if (current[activeZoomTabKey] === normalizedZoomScale) {
        return current;
      }
      return {
        ...current,
        [activeZoomTabKey]: normalizedZoomScale
      };
    });
  }, [activeZoomTabKey]);
  const resetZoom = React.useCallback(() => {
    setZoomScaleOverridesByTabId((current) => {
      if (current[activeZoomTabKey] === void 0) {
        return current;
      }
      const next = { ...current };
      delete next[activeZoomTabKey];
      return next;
    });
  }, [activeZoomTabKey]);
  const zoomIn = React.useCallback(() => {
    setZoomScale(resolveNextZoomScale(zoomScale, 1));
  }, [setZoomScale, zoomScale]);
  const zoomOut = React.useCallback(() => {
    setZoomScale(resolveNextZoomScale(zoomScale, -1));
  }, [setZoomScale, zoomScale]);
  React.useEffect(() => {
    setActiveTabIndexState((current) => {
      if (tabs.length === 0) {
        return 0;
      }
      return Math.min(current, tabs.length - 1);
    });
  }, [tabs.length]);
  const continueDeferredLoad = React.useCallback(() => {
    const buffer = deferredBufferRef.current;
    if (!buffer) return;
    if (maxFileSizeBytes > 0 && buffer.byteLength > maxFileSizeBytes) {
      setError(new XlsxFileSizeLimitExceededError(buffer.byteLength, maxFileSizeBytes));
      return;
    }
    const generation = loadGenerationRef.current;
    const isCurrent = () => generation === loadGenerationRef.current;
    deferredBufferRef.current = null;
    setDeferredLoadFileSize(null);
    setIsLoading(true);
    setError(null);
    void loadPreparedWorkbook(buffer, isCurrent).catch((nextError) => {
      if (!isCurrent()) return;
      setWorkbook(null);
      setPivotTables([]);
      setSheets([]);
      clearChartAssets();
      clearImageAssets();
      setWorkerTablesByWorkbookSheetIndex([]);
      setShouldAutoCalculate(false);
      setIsWorkerBacked(false);
      setError(nextError instanceof Error ? nextError : new Error("Could not load workbook."));
      setIsLoading(false);
    });
  }, [clearChartAssets, clearImageAssets, loadPreparedWorkbook, maxFileSizeBytes]);
  const maybeRecalculateWorkbook = React.useCallback((targetWorkbook) => {
    if (!shouldAutoCalculate) {
      return;
    }
    const result = tryRecalculate(targetWorkbook);
    if (!result.calculated) {
      setShouldAutoCalculate(false);
    }
  }, [shouldAutoCalculate]);
  const getActiveWorksheet = React.useCallback(() => {
    if (!workbook || !activeSheet) {
      return null;
    }
    return workbook.getSheet(activeSheet.workbookSheetIndex);
  }, [activeSheet, workbook]);
  const getFormControlWorksheet = React.useCallback((sheetIndex = activeSheetIndex) => {
    const targetSheet = sheets[sheetIndex];
    if (!workbook || !targetSheet) {
      return null;
    }
    try {
      return {
        workbookSheetIndex: targetSheet.workbookSheetIndex,
        worksheet: workbook.getSheet(targetSheet.workbookSheetIndex)
      };
    } catch {
      return null;
    }
  }, [activeSheetIndex, sheets, workbook]);
  const tables = React.useMemo(
    () => isWorkerBacked ? workerTablesByWorkbookSheetIndex[activeSheet?.workbookSheetIndex ?? -1] ?? [] : mapWorksheetTables(getActiveWorksheet(), activeSheet?.autoFilterRanges ?? []),
    [activeSheet?.autoFilterRanges, activeSheet?.workbookSheetIndex, getActiveWorksheet, isWorkerBacked, revision, workerTablesByWorkbookSheetIndex]
  );
  const getCellSnapshotAsync = React.useCallback((workbookSheetIndex, row2, col) => {
    if (!isWorkerBacked) {
      return Promise.resolve({
        displayValue: "",
        formula: ""
      });
    }
    return getWorkerClient().getCellSnapshot(workbookSheetIndex, row2, col, locale);
  }, [getWorkerClient, isWorkerBacked, locale]);
  const getRowsBatchAsync = React.useCallback((workbookSheetIndex, startRow, rowCount) => {
    if (!isWorkerBacked) {
      return Promise.resolve(null);
    }
    return getWorkerClient().getRowsBatch(workbookSheetIndex, startRow, rowCount, locale);
  }, [getWorkerClient, isWorkerBacked, locale]);
  const getAutofitCellsAsync = React.useCallback((workbookSheetIndex, axis, index) => getWorkerClient().getAutofitCells(workbookSheetIndex, axis, index, locale), [getWorkerClient, locale]);
  const visibleSheetIndexByWorkbookSheetIndex = React.useMemo(
    () => new Map(sheets.map((sheet, index) => [sheet.workbookSheetIndex, index])),
    [sheets]
  );
  const mapPublicChart = React.useCallback((chart) => {
    const visibleSheetIndex = visibleSheetIndexByWorkbookSheetIndex.get(chart.workbookSheetIndex);
    return {
      ...chart,
      sheetIndex: visibleSheetIndex ?? chart.workbookSheetIndex
    };
  }, [visibleSheetIndexByWorkbookSheetIndex]);
  const mapPublicImage = React.useCallback((image) => {
    const visibleSheetIndex = visibleSheetIndexByWorkbookSheetIndex.get(image.workbookSheetIndex);
    return {
      ...image,
      sheetIndex: visibleSheetIndex ?? image.workbookSheetIndex
    };
  }, [visibleSheetIndexByWorkbookSheetIndex]);
  const mapPublicFormControl = React.useCallback((control2) => {
    const visibleSheetIndex = visibleSheetIndexByWorkbookSheetIndex.get(control2.workbookSheetIndex);
    return {
      ...control2,
      sheetIndex: visibleSheetIndex ?? control2.workbookSheetIndex
    };
  }, [visibleSheetIndexByWorkbookSheetIndex]);
  const publicChartsByWorkbookSheetIndex = React.useMemo(
    () => chartsByWorkbookSheetIndex.map((sheetCharts) => sheetCharts.map(mapPublicChart)),
    [chartsByWorkbookSheetIndex, mapPublicChart]
  );
  const publicChartById = React.useMemo(() => {
    const lookup = /* @__PURE__ */ new Map();
    for (const sheetCharts of publicChartsByWorkbookSheetIndex) {
      for (const chart of sheetCharts) {
        lookup.set(chart.id, chart);
      }
    }
    return lookup;
  }, [publicChartsByWorkbookSheetIndex]);
  const getSheetCharts = React.useCallback((sheetIndex = activeSheetIndex) => {
    const targetSheet = sheets[sheetIndex];
    if (!targetSheet) {
      return [];
    }
    return publicChartsByWorkbookSheetIndex[targetSheet.workbookSheetIndex] ?? [];
  }, [activeSheetIndex, publicChartsByWorkbookSheetIndex, sheets]);
  const getChartById = React.useCallback((id) => {
    return publicChartById.get(id) ?? null;
  }, [publicChartById]);
  const getChartsheetById = React.useCallback((id) => chartsheets.find((chartsheet) => chartsheet.id === id) ?? null, [chartsheets]);
  const charts = React.useMemo(() => {
    if (activeTab?.kind === "chartsheet" && typeof activeTab.chartsheetIndex === "number") {
      const chartsheet = chartsheets[activeTab.chartsheetIndex];
      return (chartsheet?.chartIds ?? []).map((id) => getChartById(id)).filter((value) => Boolean(value));
    }
    return getSheetCharts(activeSheetIndex);
  }, [activeSheetIndex, activeTab, chartsheets, getChartById, getSheetCharts]);
  const selectedChart = React.useMemo(
    () => selectedChartId ? getChartById(selectedChartId) : null,
    [getChartById, selectedChartId]
  );
  React.useEffect(() => {
    if (!selectedChartId) {
      if (selectedChartElement) {
        setSelectedChartElement(null);
      }
      return;
    }
    if (!selectedChart) {
      setSelectedChartId(null);
      setSelectedChartElement(null);
      return;
    }
    if (!selectedChartElement) {
      setSelectedChartElement({ chartId: selectedChartId, kind: "chart" });
      return;
    }
    if (selectedChartElement.chartId !== selectedChartId) {
      setSelectedChartElement({ chartId: selectedChartId, kind: "chart" });
      return;
    }
    if (selectedChartElement.kind !== "chart" && selectedChartElement.kind !== "legend") {
      const selectedSeries = selectedChart.series[selectedChartElement.seriesIndex];
      if (!selectedSeries || selectedSeries.id !== selectedChartElement.seriesId) {
        setSelectedChartElement({ chartId: selectedChartId, kind: "chart" });
      }
    }
  }, [selectedChart, selectedChartElement, selectedChartId]);
  const selectChart = React.useCallback((id) => {
    setSelectedImageId(null);
    setSelectedChartId(id);
    setSelectedChartElement(id ? { chartId: id, kind: "chart" } : null);
  }, []);
  const clearSelectedChart = React.useCallback(() => {
    setSelectedChartId(null);
    setSelectedChartElement(null);
  }, []);
  const clearSelectedChartElement = React.useCallback(() => {
    setSelectedChartElement(selectedChartId ? { chartId: selectedChartId, kind: "chart" } : null);
  }, [selectedChartId]);
  const selectChartElement = React.useCallback((selection2) => {
    setSelectedImageId(null);
    setSelectedChartId(selection2?.chartId ?? null);
    setSelectedChartElement(selection2);
  }, []);
  const getSheetImages = React.useCallback((sheetIndex = activeSheetIndex) => {
    const targetSheet = sheets[sheetIndex];
    if (!targetSheet) {
      return [];
    }
    return (imagesByWorkbookSheetIndex[targetSheet.workbookSheetIndex] ?? []).map(mapPublicImage);
  }, [activeSheetIndex, imagesByWorkbookSheetIndex, mapPublicImage, sheets]);
  const images = React.useMemo(() => getSheetImages(activeSheetIndex), [activeSheetIndex, getSheetImages]);
  const getSheetFormControls = React.useCallback((sheetIndex = activeSheetIndex) => {
    const targetSheet = sheets[sheetIndex];
    if (!targetSheet) {
      return [];
    }
    return (formControlsByWorkbookSheetIndex[targetSheet.workbookSheetIndex] ?? []).map(mapPublicFormControl);
  }, [activeSheetIndex, formControlsByWorkbookSheetIndex, mapPublicFormControl, sheets]);
  const formControls = React.useMemo(() => getSheetFormControls(activeSheetIndex), [activeSheetIndex, getSheetFormControls]);
  const getFormControlItems = React.useCallback((controlIndex, sheetIndex = activeSheetIndex) => {
    const target = getFormControlWorksheet(sheetIndex);
    if (!workbook || !target) {
      const targetSheet = sheets[sheetIndex];
      if (!targetSheet) {
        return [];
      }
      const control3 = (formControlsByWorkbookSheetIndex[targetSheet.workbookSheetIndex] ?? []).find((entry) => entry.controlIndex === controlIndex);
      return control3?.items?.slice() ?? [];
    }
    const control2 = target.worksheet.formControls[controlIndex];
    const kind = control2?.formControl.kind;
    const inputRange = kind?.kind === "listBox" || kind?.kind === "dropdown" ? kind.inputRange : void 0;
    if (!inputRange) {
      return [];
    }
    const source = resolveWorkbookReference(workbook, target.workbookSheetIndex, inputRange);
    if (!source) {
      return [];
    }
    const items = [];
    for (let row2 = source.range.start.row; row2 <= source.range.end.row; row2 += 1) {
      for (let col = source.range.start.col; col <= source.range.end.col; col += 1) {
        items.push(source.worksheet.getFormattedValueAt(row2, col));
      }
    }
    return items;
  }, [activeSheetIndex, formControlsByWorkbookSheetIndex, getFormControlWorksheet, sheets, workbook]);
  const getSheetShapes = React.useCallback((sheetIndex = activeSheetIndex) => {
    const targetSheet = sheets[sheetIndex];
    if (!targetSheet) {
      return [];
    }
    return (shapesByWorkbookSheetIndex[targetSheet.workbookSheetIndex] ?? []).map((shape) => {
      const visibleSheetIndex = visibleSheetIndexByWorkbookSheetIndex.get(shape.workbookSheetIndex);
      return {
        ...shape,
        sheetIndex: visibleSheetIndex ?? shape.workbookSheetIndex
      };
    });
  }, [activeSheetIndex, shapesByWorkbookSheetIndex, sheets, visibleSheetIndexByWorkbookSheetIndex]);
  const shapes = React.useMemo(() => getSheetShapes(activeSheetIndex), [activeSheetIndex, getSheetShapes]);
  const getImageById = React.useCallback((id) => {
    for (const sheetImages of imagesByWorkbookSheetIndex) {
      const match = sheetImages?.find((image) => image.id === id);
      if (match) {
        return mapPublicImage(match);
      }
    }
    return null;
  }, [imagesByWorkbookSheetIndex, mapPublicImage]);
  const selectedImage = React.useMemo(
    () => selectedImageId ? getImageById(selectedImageId) : null,
    [getImageById, selectedImageId]
  );
  const selectImage = React.useCallback((id) => {
    setSelectedChartId(null);
    setSelectedChartElement(null);
    setSelectedImageId(id);
  }, []);
  const clearSelectedImage = React.useCallback(() => {
    setSelectedImageId(null);
  }, []);
  const getColumnWidthPx = React.useCallback((worksheet, col) => {
    const sheetState = imageAssetsRef.current?.sheetStatesByWorkbookSheetIndex[activeSheet?.workbookSheetIndex ?? -1] ?? null;
    const width = worksheet.getColumnWidth(col);
    const showGridLines = activeSheet?.showGridLines ?? true;
    if (width !== void 0 && width !== null) {
      return resolveRenderedSheetAxisPixels(
        resolveSheetColumnWidthPixels(width, sheetState?.columnWidthCharacterWidthPx),
        showGridLines
      );
    }
    return resolveRenderedSheetAxisPixels(
      sheetState?.colWidthOverridesPx?.[col] ?? sheetState?.defaultColWidthPx ?? DEFAULT_COL_WIDTH,
      showGridLines
    );
  }, [activeSheet?.showGridLines, activeSheet?.workbookSheetIndex]);
  const getRowHeightPx = React.useCallback((worksheet, row2) => {
    const sheetState = imageAssetsRef.current?.sheetStatesByWorkbookSheetIndex[activeSheet?.workbookSheetIndex ?? -1] ?? null;
    const height = worksheet.getRowHeight(row2);
    const showGridLines = activeSheet?.showGridLines ?? true;
    if (height !== void 0 && height !== null) {
      return resolveRenderedSheetAxisPixels(resolveSheetRowHeightPixels(height), showGridLines);
    }
    return resolveRenderedSheetAxisPixels(
      sheetState?.rowHeightOverridesPx?.[row2] ?? sheetState?.defaultRowHeightPx ?? DEFAULT_ROW_HEIGHT,
      showGridLines
    );
  }, [activeSheet?.showGridLines, activeSheet?.workbookSheetIndex]);
  const getCellDisplayValue2 = React.useCallback((cell) => {
    if (cell && activeSheet) {
      const workerSnapshot = workerCellSnapshotCacheRef.current.get(`${locale}:${activeSheet.workbookSheetIndex}:${cell.row}:${cell.col}`);
      if (workerSnapshot) {
        return workerSnapshot.displayValue;
      }
    }
    const worksheet = getActiveWorksheet();
    if (!worksheet || !cell) {
      return "";
    }
    const formula = worksheet.getFormulaAt(cell.row, cell.col);
    const cachedFormulaValue = formula ? activeSheet?.cachedFormulaValues?.[cellAddressToA1(cell)] : void 0;
    const formatted = worksheet.getFormattedValueAt(cell.row, cell.col);
    if (formatted && !(formula && cachedFormulaValue !== void 0 && formatted.startsWith("#"))) {
      return localizeCellNumber(worksheet, cell.row, cell.col, decodeHtmlEntities(formatted), locale);
    }
    const calculated = worksheet.getCalculatedValueAt(cell.row, cell.col);
    if (formula && cachedFormulaValue !== void 0 && calculated.is_error) {
      return cachedFormulaValue;
    }
    if (calculated.is_error) {
      return calculated.asError() ?? "";
    }
    if (calculated.is_empty) {
      return "";
    }
    return calculated.toString();
  }, [activeSheet, getActiveWorksheet, locale]);
  const getCellFormula = React.useCallback((cell) => {
    if (cell && activeSheet) {
      const workerSnapshot = workerCellSnapshotCacheRef.current.get(`${locale}:${activeSheet.workbookSheetIndex}:${cell.row}:${cell.col}`);
      if (workerSnapshot) {
        return workerSnapshot.formula;
      }
    }
    const worksheet = getActiveWorksheet();
    if (!worksheet || !cell) {
      return "";
    }
    return worksheet.getFormulaAt(cell.row, cell.col) ?? "";
  }, [activeSheet, getActiveWorksheet, locale]);
  const getClipboardData = React.useCallback(() => {
    const worksheet = getActiveWorksheet();
    const bands = clipboardBands(selectionRanges);
    if (!worksheet || !bands) return null;
    const rows = [];
    const htmlRows = [];
    const payload = {
      cells: [],
      cols: bands.cols.reduce((total, band) => total + band.end - band.start + 1, 0),
      merges: [],
      rows: bands.rows.reduce((total, band) => total + band.end - band.start + 1, 0)
    };
    for (const { index: row2, offset: rowOffset, remaining: rowsRemaining } of bandIndices(bands.rows)) {
      const textCells = [];
      const htmlCells = [];
      for (const { index: col, offset: colOffset, remaining: colsRemaining } of bandIndices(bands.cols)) {
        if (worksheet.isMergedSecondary(row2, col)) {
          textCells.push("");
          continue;
        }
        const formula = worksheet.getFormulaAt(row2, col) ?? null;
        const value = getCellDisplayValue2({ row: row2, col });
        const merge = worksheet.getMergeSpan(row2, col);
        const rawStyle = worksheet.getCellStyleAt(row2, col) ?? resolveInheritedCellStyle(activeSheet, row2, col);
        const cellStyles = [
          "padding:2px 4px",
          "white-space:pre-wrap",
          "vertical-align:top"
        ];
        const fill = rawStyle?.fill;
        if (fill) {
          const fillStyle = resolveWorkbookFillStyle(fill, activeSheet?.themePalette);
          if (fillStyle.backgroundColor && fillStyle.backgroundColor.toLowerCase() !== "#ffffff") {
            cellStyles.push(`background-color:${fillStyle.backgroundColor}`);
          }
          if (fillStyle.backgroundImage) {
            cellStyles.push(`background-image:${fillStyle.backgroundImage}`);
          }
        }
        const font = rawStyle?.font;
        if (font) {
          if (font.bold) {
            cellStyles.push("font-weight:700");
          }
          if (font.italic) {
            cellStyles.push("font-style:italic");
          }
          if (font.underline && font.underline !== "none") {
            cellStyles.push("text-decoration:underline");
          }
          if (font.strikethrough) {
            cellStyles.push("text-decoration:line-through");
          }
          const fontColor = resolveWorkbookColor(font.color, activeSheet?.themePalette);
          if (fontColor) {
            cellStyles.push(`color:${fontColor}`);
          }
          if (typeof font.size === "number") {
            cellStyles.push(`font-size:${font.size}pt`);
          }
        }
        const alignment = rawStyle?.alignment;
        if (alignment?.horizontal && alignment.horizontal !== "general") {
          cellStyles.push(`text-align:${String(alignment.horizontal)}`);
        }
        if (alignment?.wrapText) {
          cellStyles.push("white-space:pre-wrap");
          cellStyles.push("word-break:break-word");
        }
        const border = rawStyle?.border;
        if (border?.top?.style && border.top.style !== "none") {
          cellStyles.push(`border-top:${mapBorder(border.top)}`);
        }
        if (border?.right?.style && border.right.style !== "none") {
          cellStyles.push(`border-right:${mapBorder(border.right)}`);
        }
        if (border?.bottom?.style && border.bottom.style !== "none") {
          cellStyles.push(`border-bottom:${mapBorder(border.bottom)}`);
        }
        if (border?.left?.style && border.left.style !== "none") {
          cellStyles.push(`border-left:${mapBorder(border.left)}`);
        }
        const rowSpan = Math.min(merge?.rowSpan ?? 1, rowsRemaining);
        const colSpan = Math.min(merge?.colSpan ?? 1, colsRemaining);
        payload.cells.push({
          colOffset,
          formula,
          rowOffset,
          value
        });
        if (rowSpan > 1 || colSpan > 1) {
          payload.merges.push({
            colOffset,
            colSpan,
            rowOffset,
            rowSpan
          });
        }
        textCells.push(quoteClipboardField(value));
        htmlCells.push(
          `<td${rowSpan > 1 ? ` rowspan="${rowSpan}"` : ""}${colSpan > 1 ? ` colspan="${colSpan}"` : ""} style="${escapeHtml(cellStyles.join(";"))}">${escapeHtml(value)}</td>`
        );
      }
      rows.push(textCells.join("	"));
      htmlRows.push(`<tr>${htmlCells.join("")}</tr>`);
    }
    return {
      html: `<table style="border-collapse:collapse">${htmlRows.join("")}</table>`,
      structured: JSON.stringify(payload),
      text: rows.join("\n")
    };
  }, [activeSheet, getActiveWorksheet, getCellDisplayValue2, selectionRanges]);
  React.useEffect(() => {
    if (!isWorkerBacked || !deferredMetadataSheet || !deferredMetadataCell) {
      return;
    }
    const cacheKey = `${locale}:${deferredMetadataSheet.workbookSheetIndex}:${deferredMetadataCell.row}:${deferredMetadataCell.col}`;
    if (workerCellSnapshotCacheRef.current.has(cacheKey)) {
      return;
    }
    let isCurrent = true;
    void getCellSnapshotAsync(deferredMetadataSheet.workbookSheetIndex, deferredMetadataCell.row, deferredMetadataCell.col).then((snapshot) => {
      if (!isCurrent) {
        return;
      }
      workerCellSnapshotCacheRef.current.set(cacheKey, snapshot);
      setWorkerCellSnapshotRevision((current) => current + 1);
    }).catch(() => {
      if (!isCurrent) {
        return;
      }
      workerCellSnapshotCacheRef.current.set(cacheKey, {
        displayValue: "",
        formula: ""
      });
      setWorkerCellSnapshotRevision((current) => current + 1);
    });
    return () => {
      isCurrent = false;
    };
  }, [deferredMetadataCell, deferredMetadataSheet, getCellSnapshotAsync, isWorkerBacked, locale]);
  const activeCellAddress = React.useMemo(() => activeCell ? cellAddressToA1(activeCell) : null, [activeCell]);
  const selectedRangeAddress = React.useMemo(() => selectionRanges.map(rangeToA1).join(",") || null, [selectionRanges]);
  const selectedValue = React.useMemo(
    () => getCellDisplayValue2(deferredMetadataCell),
    [deferredMetadataCell, getCellDisplayValue2, revision, workerCellSnapshotRevision]
  );
  const selectedCellFormula = React.useMemo(
    () => getCellFormula(deferredMetadataCell),
    [deferredMetadataCell, getCellFormula, revision, workerCellSnapshotRevision]
  );
  const getChartSeriesFormula = React.useCallback((chartId, seriesIndex) => buildChartSeriesFormula(getChartById(chartId), seriesIndex), [getChartById]);
  const selectedChartFormula = React.useMemo(() => {
    if (!selectedChartElement || selectedChartElement.kind === "chart" || selectedChartElement.kind === "legend" || selectedChartElement.seriesIndex < 0) {
      return null;
    }
    return getChartSeriesFormula(selectedChartElement.chartId, selectedChartElement.seriesIndex);
  }, [getChartSeriesFormula, selectedChartElement]);
  const selectedFormulaTarget = React.useMemo(() => {
    if (selectedChartFormula && selectedChartElement && selectedChartElement.kind !== "chart" && selectedChartElement.kind !== "legend") {
      return {
        chartId: selectedChartElement.chartId,
        kind: "chartSeries",
        seriesId: selectedChartElement.seriesId,
        seriesIndex: selectedChartElement.seriesIndex
      };
    }
    return {
      cell: deferredMetadataCell,
      kind: "cell"
    };
  }, [deferredMetadataCell, selectedChartElement, selectedChartFormula]);
  const selectedFormula = selectedChartFormula ?? selectedCellFormula;
  const isLoadDeferred = deferredLoadFileSize !== null;
  const canLoadDeferred = !isLoading && isLoadDeferred;
  const canUndo = !readOnly && undoStackRef.current.length > 0;
  const canRedo = !readOnly && redoStackRef.current.length > 0;
  const renderChartAsync = React.useCallback((...args) => getWorkerClient().renderChart(...args), [getWorkerClient]);
  const createSavedWorkbookBytes = React.useCallback((targetWorkbook) => {
    return getWorkerClient().exportWorkbook(targetWorkbook.exportSnapshot(), imageAssetsRef.current, sheetOriginsRef.current);
  }, [getWorkerClient]);
  const createHistoryEntry = React.useCallback(() => {
    if (!workbook) {
      return null;
    }
    return {
      kind: "snapshot",
      activeCell,
      activeSheetIndex,
      bytes: workbook.exportSnapshot(),
      assets: imageAssetsRef.current ? structuredClone(imageAssetsRef.current) : null,
      origins: structuredClone(sheetOriginsRef.current),
      selectionRanges,
      sortState
    };
  }, [activeCell, activeSheetIndex, selectionRanges, sortState, workbook]);
  const captureCellMutationState = React.useCallback((cell) => {
    const worksheet = getActiveWorksheet();
    if (!worksheet) {
      return null;
    }
    return {
      formula: worksheet.getFormulaAt(cell.row, cell.col) ?? null,
      style: worksheet.getCellStyleAt(cell.row, cell.col),
      valueSnapshot: worksheet.getValueSnapshotAt(cell.row, cell.col),
      value: worksheet.getCellAt(cell.row, cell.col).toJs()
    };
  }, [getActiveWorksheet]);
  const restoreHistoryEntry = React.useCallback(async (entry) => {
    const wasmModule = await getSheetsWasmModule();
    const nextWorkbook = wasmModule.Workbook.fromSnapshot(entry.bytes);
    const nextImageAssets = entry.assets ? structuredClone(entry.assets) : null;
    const nextSheets = buildSheetList(
      nextWorkbook,
      nextImageAssets?.sheetStatesByWorkbookSheetIndex,
      nextImageAssets?.themePalette,
      nextImageAssets?.styleById,
      nextImageAssets?.namedCellStyleByName,
      nextImageAssets?.tableStyleByName,
      showHiddenSheets
    );
    const nextSheetIndex = Math.max(0, Math.min(entry.activeSheetIndex, Math.max(0, nextSheets.length - 1)));
    setError(null);
    setIsLoading(false);
    setImageAssets(nextImageAssets);
    sheetOriginsRef.current = structuredClone(entry.origins);
    setWorkbook(nextWorkbook);
    setSheets(nextSheets);
    setPivotTables(readPivotTables(nextWorkbook));
    const nextChartAssets = loadWorkbookChartAssets(nextWorkbook, nextImageAssets, buildVisibleSheetIndexMap(nextSheets), showHiddenSheets);
    setChartAssets(nextChartAssets);
    setActiveSheetIndexState(nextSheetIndex);
    const nextTabIndex = nextChartAssets.tabs.findIndex((tab) => tab.kind === "sheet" && tab.sheetIndex === nextSheetIndex);
    if (nextTabIndex >= 0) {
      setActiveTabIndexState(nextTabIndex);
    }
    setActiveCell(entry.activeCell);
    setSelectionRanges(entry.selectionRanges);
    setSortState(entry.sortState);
    selectionAnchorRef.current = entry.selectionRanges.at(-1)?.start ?? entry.activeCell;
    setRevision((current) => current + 1);
  }, [setChartAssets, setImageAssets]);
  const applyCellEditHistoryEntry = React.useCallback((entry, direction) => {
    if (!workbook) {
      return;
    }
    const worksheet = workbook.getSheet(entry.sheetIndex);
    const visibleSheetIndex = sheets.findIndex((sheet) => sheet.workbookSheetIndex === entry.sheetIndex);
    const targetState = direction === "undo" ? entry.before : entry.after;
    isApplyingHistoryRef.current = true;
    applyCellMutationState(worksheet, entry.cell, targetState);
    maybeRecalculateWorkbook(workbook);
    refreshWorkbookState(workbook);
    const nextActiveCell = direction === "undo" ? entry.activeCellBefore : entry.activeCellAfter;
    const nextSelection = direction === "undo" ? entry.selectionBefore : entry.selectionAfter;
    if (visibleSheetIndex >= 0) {
      setActiveSheetIndexState(visibleSheetIndex);
    }
    setActiveCell(nextActiveCell);
    setSelectionRanges(nextSelection);
    selectionAnchorRef.current = nextSelection.at(-1)?.start ?? nextActiveCell;
    isApplyingHistoryRef.current = false;
  }, [maybeRecalculateWorkbook, refreshWorkbookState, sheets, workbook]);
  const applyRangeEditHistoryEntry = React.useCallback((entry, direction) => {
    if (!workbook) {
      return;
    }
    const worksheet = workbook.getSheet(entry.sheetIndex);
    const visibleSheetIndex = sheets.findIndex((sheet) => sheet.workbookSheetIndex === entry.sheetIndex);
    isApplyingHistoryRef.current = true;
    for (const mutation of entry.mutations) {
      applyCellMutationState(worksheet, mutation.cell, direction === "undo" ? mutation.before : mutation.after);
    }
    setSortState(direction === "undo" ? entry.sortStateBefore : entry.sortStateAfter);
    maybeRecalculateWorkbook(workbook);
    refreshWorkbookState(workbook);
    const nextActiveCell = direction === "undo" ? entry.activeCellBefore : entry.activeCellAfter;
    const nextSelection = direction === "undo" ? entry.selectionBefore : entry.selectionAfter;
    if (visibleSheetIndex >= 0) {
      setActiveSheetIndexState(visibleSheetIndex);
    }
    setActiveCell(nextActiveCell);
    setSelectionRanges(nextSelection);
    selectionAnchorRef.current = nextSelection.at(-1)?.start ?? nextActiveCell;
    isApplyingHistoryRef.current = false;
  }, [maybeRecalculateWorkbook, refreshWorkbookState, sheets, workbook]);
  const recordHistoryBeforeMutation = React.useCallback(() => {
    if (isApplyingHistoryRef.current) {
      return;
    }
    const snapshot = createHistoryEntry();
    if (!snapshot) {
      return;
    }
    pushHistoryEntry(undoStackRef.current, snapshot);
    redoStackRef.current = [];
    setHistoryRevision((current) => current + 1);
  }, [createHistoryEntry]);
  const getPivotSourceFields = React.useCallback((source) => {
    if (!workbook) throw new Error("Load an editable workbook to inspect a pivot source.");
    return pivotWorkbook(workbook).getPivotSourceFields(source);
  }, [workbook]);
  const getPivotTableAtCell = React.useCallback((cell, sheetName = activeSheet?.name) => findIntersectingPivot(pivotTables, sheetName, { start: cell, end: cell }), [activeSheet?.name, pivotTables]);
  React.useEffect(() => {
    const insidePivot = activeCell && !selectedChartId && !selectedImageId && getPivotTableAtCell(activeCell);
    setPivotFieldListVisibleState(Boolean(pivotFieldListRequestedRef.current && insidePivot));
  }, [activeCell?.row, activeCell?.col, activeSheet?.name, getPivotTableAtCell, selectedChartId, selectedImageId]);
  const intersectsPivot = React.useCallback((range) => Boolean(findIntersectingPivot(pivotTables, activeSheet?.name, range)), [activeSheet?.name, pivotTables]);
  const calculateForPivotMutation = React.useCallback((target, preserveSavedValues = true) => {
    const snapshot = preserveSavedValues ? target.exportSnapshot() : null;
    const result = safeCalculate(target, snapshot ? { reparse: () => target.constructor.fromSnapshot(snapshot) } : {});
    if (!result.calculated) {
      if (result.workbook !== target) result.workbook.free();
      throw new Error("The workbook formulas could not be recalculated safely. The pivot table and existing values have been kept.");
    }
  }, []);
  const commitPivotMutation = React.useCallback((mutate, recalculate2 = true) => {
    if (readOnly) throw new Error("Enable editing to change pivot tables.");
    if (!workbook) throw new Error("Load a workbook before changing pivot tables.");
    const before = createHistoryEntry();
    const next = workbook.constructor.fromSnapshot(before?.bytes ?? workbook.exportSnapshot());
    let result;
    try {
      if (recalculate2) calculateForPivotMutation(next);
      result = mutate(next);
      if (recalculate2) calculateForPivotMutation(next, false);
    } catch (error2) {
      next.free();
      throw error2;
    }
    if (before) {
      pushHistoryEntry(undoStackRef.current, before);
      redoStackRef.current = [];
      setHistoryRevision((current) => current + 1);
    }
    if (recalculate2) {
      for (const sheet of imageAssetsRef.current?.sheetStatesByWorkbookSheetIndex ?? []) if (sheet) sheet.cachedFormulaValues = {};
    }
    setWorkbook(next);
    refreshWorkbookState(next);
    return result;
  }, [calculateForPivotMutation, createHistoryEntry, readOnly, refreshWorkbookState, workbook]);
  const upsertPivotTable = React.useCallback((input) => {
    return commitPivotMutation((target) => pivotWorkbook(target).upsertPivotTable(input));
  }, [commitPivotMutation]);
  const refreshPivotTable = React.useCallback((id) => commitPivotMutation((target) => pivotWorkbook(target).refreshPivotTable(id), true), [commitPivotMutation]);
  const createPivotChart = React.useCallback((id, options3 = {}) => commitPivotMutation((target) => pivotWorkbook(target).createPivotChart(id, { ...options3, workbookName: `${fileStem(displayFileName)}.xlsx` }), false), [commitPivotMutation, displayFileName]);
  const togglePivotGroup = React.useCallback((id, toggle) => {
    const pivot = pivotTables.find((item) => item.id === id);
    if (!pivot) throw new Error("The pivot table no longer exists.");
    return upsertPivotTable({
      ...pivot,
      [toggle.axis]: pivot[toggle.axis].map((field, depth) => field.field === toggle.field && (toggle.depth === void 0 || toggle.depth === depth) ? {
        ...field,
        collapsed: field.collapsed.includes(toggle.key) ? field.collapsed.filter((key) => key !== toggle.key) : [...field.collapsed, toggle.key]
      } : field)
    });
  }, [pivotTables, upsertPivotTable]);
  const removePivotTable = React.useCallback((id) => {
    if (!pivotTables.some((pivot) => pivot.id === id)) return false;
    return commitPivotMutation((target) => pivotWorkbook(target).removePivotTable(id));
  }, [commitPivotMutation, pivotTables]);
  const refreshAllPivotTables = React.useCallback(() => {
    if (readOnly) throw new Error("Enable editing to refresh pivot tables.");
    if (!workbook) throw new Error("Load a workbook before refreshing pivot tables.");
    if (!pivotTables.length) return [];
    const before = createHistoryEntry();
    const next = workbook.constructor.fromSnapshot(workbook.exportSnapshot());
    try {
      calculateForPivotMutation(next);
      const engine = pivotWorkbook(next);
      for (const pivot of engine.pivotTables) {
        engine.refreshPivotTable(pivot.id);
        calculateForPivotMutation(next, false);
      }
    } catch (error2) {
      next.free();
      throw error2;
    }
    if (before) {
      pushHistoryEntry(undoStackRef.current, before);
      redoStackRef.current = [];
      setHistoryRevision((current) => current + 1);
    }
    for (const sheet of imageAssetsRef.current?.sheetStatesByWorkbookSheetIndex ?? []) if (sheet) sheet.cachedFormulaValues = {};
    setWorkbook(next);
    refreshWorkbookState(next);
    return pivotWorkbook(next).pivotTables;
  }, [calculateForPivotMutation, createHistoryEntry, pivotTables.length, readOnly, refreshWorkbookState, workbook]);
  const pivotDrillDown = React.useCallback((id, row2, col) => {
    if (!workbook) throw new Error("Load an editable workbook to inspect pivot details.");
    return pivotWorkbook(workbook).pivotDrillDown(id, row2, col);
  }, [workbook]);
  const showPivotDetails = React.useCallback((id, row2, col) => {
    if (readOnly) throw new Error("Enable editing to create a details worksheet.");
    if (!workbook) throw new Error("Load a workbook before inspecting pivot details.");
    const details = pivotWorkbook(workbook).pivotDrillDown(id, row2, col);
    if (!details.rows.length) throw new Error("This pivot cell has no source records to display.");
    const before = createHistoryEntry();
    const next = workbook.constructor.fromSnapshot(workbook.exportSnapshot());
    let name = "Details";
    let suffix = 2;
    while (next.sheetNames.some((sheet) => sheet.toLowerCase() === name.toLowerCase())) name = `Details ${suffix++}`;
    try {
      const sheet = next.getSheet(next.addSheet(name));
      for (let col2 = 0; col2 < details.fields.length; col2++) {
        sheet.setCell(cellAddressToA1({ row: 0, col: col2 }), details.fields[col2]);
        sheet.setCellStyleAt(0, col2, { font: { bold: true } });
      }
      for (let row3 = 0; row3 < details.rows.length; row3++) {
        for (let col2 = 0; col2 < details.fields.length; col2++) {
          sheet.setCell(cellAddressToA1({ row: row3 + 1, col: col2 }), details.rows[row3][col2] ?? "");
        }
      }
    } catch (error2) {
      next.free();
      throw error2;
    }
    if (before) {
      pushHistoryEntry(undoStackRef.current, before);
      redoStackRef.current = [];
      setHistoryRevision((current) => current + 1);
    }
    sheetOriginsRef.current = [...sheetOriginsRef.current, null];
    setWorkbook(next);
    refreshWorkbookState(next);
    setActiveSheetIndexState(sheets.length);
    setActiveTabIndexState(tabs.length);
    return name;
  }, [createHistoryEntry, readOnly, refreshWorkbookState, sheets.length, tabs.length, workbook]);
  const addFormControl = React.useCallback((input, sheetIndex = activeSheetIndex) => {
    const target = getFormControlWorksheet(sheetIndex);
    if (readOnly || !workbook || !target) {
      return null;
    }
    if (formControlLinkTouchesPivot(workbook, pivotTables, target.workbookSheetIndex, xlsxFormControlKindToDukeKind(input.kind))) {
      return null;
    }
    recordHistoryBeforeMutation();
    target.worksheet.addDrawing(xlsxFormControlInputToDukeDrawing(input));
    const controlIndex = target.worksheet.formControlCount - 1;
    const addedControl = target.worksheet.formControls[controlIndex];
    const addedKind = addedControl?.formControl.kind;
    if (addedControl && (addedKind?.kind === "checkbox" || addedKind?.kind === "optionButton")) {
      target.worksheet.setFormControlCheckState(addedControl.drawingPath, addedKind.state);
    } else if (addedKind?.kind === "groupBox") {
      reconcileCheckedOptionButtons(target.worksheet);
    } else if (addedKind && "cellLink" in addedKind && addedKind.cellLink) {
      workbook.syncFormControls();
    }
    maybeRecalculateWorkbook(workbook);
    refreshWorkbookState(workbook);
    return controlIndex;
  }, [activeSheetIndex, getFormControlWorksheet, maybeRecalculateWorkbook, pivotTables, readOnly, recordHistoryBeforeMutation, refreshWorkbookState, workbook]);
  const updateFormControl = React.useCallback((controlIndex, patch, sheetIndex = activeSheetIndex) => {
    const target = getFormControlWorksheet(sheetIndex);
    const currentControl = target?.worksheet.formControls[controlIndex];
    if (readOnly || !workbook || !target || !currentControl) {
      return false;
    }
    const currentInput = formControlInputFromDukeControl(currentControl);
    if (currentInput.kind !== "formControl" || !currentControl.anchor) {
      return false;
    }
    const nextAnchor = patch.anchor ? xlsxAnchorToDukeDrawingAnchor(
      patch.anchor,
      patch.editAs ?? (currentControl.anchor.type === "twoCell" ? currentControl.anchor.editAs : void 0)
    ) : patch.editAs !== void 0 && currentControl.anchor.type === "twoCell" ? { ...currentControl.anchor, editAs: patch.editAs } : currentControl.anchor;
    let nextKind = patch.kind ? xlsxFormControlKindToDukeKind(patch.kind) : dukeFormControlKindToInput(currentControl.formControl.kind);
    if (formControlInteractionChanged(currentControl.formControl.kind, nextKind) && formControlLinkTouchesPivot(workbook, pivotTables, target.workbookSheetIndex, nextKind)) {
      return false;
    }
    if (currentControl.formControl.kind.kind === "unknown" && nextKind.kind === "unknown") {
      nextKind = {
        ...nextKind,
        legacyObjectType: nextKind.legacyObjectType ?? currentControl.formControl.kind.legacyObjectType
      };
    }
    const patchedRawObj = patch.kind?.kind === "editbox" || patch.kind?.kind === "unknown" ? patch.kind.rawObj : void 0;
    const patchedRawProperties = patch.kind?.kind === "editbox" || patch.kind?.kind === "unknown" ? patch.kind.rawProperties : void 0;
    const nextInput = {
      altText: "altText" in patch ? patch.altText : currentControl.altText,
      anchor: nextAnchor,
      formControl: {
        ...currentInput.formControl,
        kind: nextKind,
        macroName: "macroName" in patch ? patch.macroName : currentControl.formControl.macroName,
        rawClientData: "rawClientData" in patch ? patch.rawClientData : currentControl.formControl.rawClientData,
        rawObj: patchedRawObj ?? currentControl.formControl.rawObj,
        rawProperties: patchedRawProperties ?? currentControl.formControl.rawProperties
      },
      hidden: "hidden" in patch ? patch.hidden : currentControl.hidden,
      kind: "formControl",
      locked: "locked" in patch ? patch.locked : currentControl.locked,
      name: "name" in patch ? patch.name : currentControl.name,
      printable: "printable" in patch ? patch.printable : currentControl.printable,
      title: "title" in patch ? patch.title : currentControl.title
    };
    recordHistoryBeforeMutation();
    target.worksheet.setDrawing(currentControl.drawingPath, nextInput);
    const updatedControl = target.worksheet.formControls[controlIndex];
    const updatedKind = updatedControl?.formControl.kind;
    const interactionChanged = updatedKind ? formControlInteractionChanged(currentControl.formControl.kind, updatedKind) : false;
    const groupTopologyChanged = patch.anchor !== void 0 || updatedKind !== void 0 && updatedKind.kind !== currentControl.formControl.kind.kind && (updatedKind.kind === "groupBox" || currentControl.formControl.kind.kind === "groupBox");
    if (interactionChanged && updatedControl && (updatedKind?.kind === "checkbox" || updatedKind?.kind === "optionButton")) {
      target.worksheet.setFormControlCheckState(updatedControl.drawingPath, updatedKind.state);
    } else if (groupTopologyChanged) {
      reconcileCheckedOptionButtons(target.worksheet);
    } else if (interactionChanged && updatedKind && "cellLink" in updatedKind && updatedKind.cellLink) {
      workbook.syncFormControls();
    }
    maybeRecalculateWorkbook(workbook);
    refreshWorkbookState(workbook);
    return true;
  }, [activeSheetIndex, getFormControlWorksheet, maybeRecalculateWorkbook, pivotTables, readOnly, recordHistoryBeforeMutation, refreshWorkbookState, workbook]);
  const removeFormControl = React.useCallback((controlIndex, sheetIndex = activeSheetIndex) => {
    const target = getFormControlWorksheet(sheetIndex);
    if (readOnly || !workbook || !target || !target.worksheet.formControls[controlIndex]) {
      return false;
    }
    recordHistoryBeforeMutation();
    const removedControl = target.worksheet.formControls[controlIndex];
    const removedKind = removedControl.formControl.kind.kind;
    target.worksheet.removeDrawing(removedControl.drawingPath);
    if (removedKind === "groupBox" || removedKind === "optionButton") {
      reconcileCheckedOptionButtons(target.worksheet);
      maybeRecalculateWorkbook(workbook);
    }
    refreshWorkbookState(workbook);
    return true;
  }, [activeSheetIndex, getFormControlWorksheet, maybeRecalculateWorkbook, readOnly, recordHistoryBeforeMutation, refreshWorkbookState, workbook]);
  const recordCellEditHistory = React.useCallback((cell, before, after) => {
    if (!activeSheet || isApplyingHistoryRef.current) {
      return;
    }
    pushHistoryEntry(undoStackRef.current, {
      kind: "cell-edit",
      activeCellAfter: cell,
      activeCellBefore: activeCell,
      after,
      before,
      cell,
      selectionAfter: [{ start: cell, end: cell }],
      selectionBefore: selectionRanges,
      sheetIndex: activeSheet.workbookSheetIndex
    });
    redoStackRef.current = [];
    setHistoryRevision((current) => current + 1);
  }, [activeCell, activeSheet, selectionRanges]);
  const recordRangeEditHistory = React.useCallback((mutations, selectionAfter, activeCellAfter, sortStateAfter = sortState) => {
    if (!activeSheet || isApplyingHistoryRef.current || mutations.length === 0 && sortStateAfter === sortState) {
      return;
    }
    pushHistoryEntry(undoStackRef.current, {
      kind: "range-edit",
      activeCellAfter,
      activeCellBefore: activeCell,
      mutations,
      selectionAfter,
      selectionBefore: selectionRanges,
      sheetIndex: activeSheet.workbookSheetIndex,
      sortStateAfter,
      sortStateBefore: sortState
    });
    redoStackRef.current = [];
    setHistoryRevision((current) => current + 1);
  }, [activeCell, activeSheet, selectionRanges, sortState]);
  const sortTable = React.useCallback((tableName, columnIndex, direction) => {
    const worksheet = getActiveWorksheet();
    const targetTable = tables.find((table) => table.name === tableName || table.displayName === tableName);
    if (!worksheet || !workbook || !activeSheet || !targetTable) {
      return;
    }
    if (intersectsPivot({ start: targetTable.start, end: targetTable.end })) return;
    const dataStartRow = targetTable.start.row + Math.max(targetTable.headerRowCount, 1);
    const totalsRowOffset = targetTable.totalsRowCount;
    const dataEndRow = targetTable.end.row - totalsRowOffset;
    const startCol = targetTable.start.col;
    const endCol = targetTable.end.col;
    const sortCol = startCol + columnIndex;
    if (columnIndex < 0 || sortCol > endCol || dataStartRow > dataEndRow) {
      return;
    }
    const rows = [];
    for (let row2 = dataStartRow; row2 <= dataEndRow; row2 += 1) {
      const cells = [];
      for (let col = startCol; col <= endCol; col += 1) {
        cells.push({
          formula: worksheet.getFormulaAt(row2, col) ?? null,
          style: worksheet.getCellStyleAt(row2, col),
          value: worksheet.getCellAt(row2, col).toJs()
        });
      }
      const calculated = worksheet.getCalculatedValueAt(row2, sortCol);
      const formatted = decodeHtmlEntities(worksheet.getFormattedValueAt(row2, sortCol) ?? "");
      rows.push({
        cells,
        index: row2,
        sortBoolean: calculated.is_boolean ? calculated.asBoolean() : void 0,
        sortEmpty: calculated.is_empty || formatted.length === 0,
        sortNumber: calculated.is_number ? calculated.asNumber() : void 0,
        sortText: calculated.is_text ? calculated.asText() ?? formatted : formatted
      });
    }
    const sortedRows = [...rows].sort((left, right) => {
      if (left.sortEmpty !== right.sortEmpty) {
        return left.sortEmpty ? 1 : -1;
      }
      if (left.sortNumber !== void 0 && right.sortNumber !== void 0) {
        return direction === "ascending" ? left.sortNumber - right.sortNumber : right.sortNumber - left.sortNumber;
      }
      if (left.sortBoolean !== void 0 && right.sortBoolean !== void 0) {
        const leftValue = left.sortBoolean ? 1 : 0;
        const rightValue = right.sortBoolean ? 1 : 0;
        return direction === "ascending" ? leftValue - rightValue : rightValue - leftValue;
      }
      const comparedText = left.sortText.localeCompare(right.sortText, void 0, { numeric: true, sensitivity: "base" });
      return direction === "ascending" ? comparedText : -comparedText;
    });
    const nextSortState = { columnIndex, direction, tableName: targetTable.name };
    if (sortedRows.every((row2, index) => row2.index === rows[index]?.index)) {
      if (sortState?.tableName === targetTable.name && sortState.columnIndex === columnIndex && sortState.direction === direction) {
        return;
      }
      setSortState(nextSortState);
      recordRangeEditHistory([], selectionRanges, activeCell, nextSortState);
      return;
    }
    const mutations = [];
    for (let rowOffset = 0; rowOffset < rows.length; rowOffset += 1) {
      const targetRow = dataStartRow + rowOffset;
      const sourceRow = sortedRows[rowOffset];
      const beforeRow = rows[rowOffset];
      if (!sourceRow || !beforeRow) {
        continue;
      }
      for (let colOffset = 0; colOffset <= endCol - startCol; colOffset += 1) {
        const before = beforeRow.cells[colOffset];
        const after = sourceRow.cells[colOffset];
        if (!before || !after) {
          continue;
        }
        const cell = { row: targetRow, col: startCol + colOffset };
        applyCellMutationState(worksheet, cell, after);
        mutations.push({
          after,
          before,
          cell
        });
      }
    }
    maybeRecalculateWorkbook(workbook);
    refreshWorkbookState(workbook);
    setSortState(nextSortState);
    recordRangeEditHistory(mutations, selectionRanges, activeCell, nextSortState);
  }, [
    intersectsPivot,
    activeCell,
    activeSheet,
    getActiveWorksheet,
    maybeRecalculateWorkbook,
    readOnly,
    recordRangeEditHistory,
    refreshWorkbookState,
    selectionRanges,
    sortState,
    tables,
    workbook
  ]);
  const getXlsxBytes = React.useCallback(async () => {
    if (!workbook) {
      return null;
    }
    return createSavedWorkbookBytes(workbook);
  }, [createSavedWorkbookBytes, workbook]);
  const exportXlsx = React.useCallback(async () => {
    const bytes = await getXlsxBytes();
    if (!bytes) {
      return;
    }
    downloadBytes(bytes, `${fileStem(displayFileName)}.xlsx`, XLSX_MIME_TYPE);
  }, [displayFileName, getXlsxBytes]);
  const download = React.useCallback(async () => {
    if (workbook) {
      await exportXlsx();
    } else if (file) {
      downloadArrayBuffer(file, displayFileName);
    } else if (src) {
      downloadUrl(src, displayFileName);
    }
  }, [displayFileName, exportXlsx, file, src, workbook]);
  const exportCsv = React.useCallback(() => {
    if (!workbook) {
      return;
    }
    const activeSheetName = activeSheet?.name ?? "sheet";
    downloadText(workbook.saveCsvString(), `${fileStem(displayFileName)}-${activeSheetName}.csv`, CSV_MIME_TYPE);
  }, [activeSheet?.name, displayFileName, workbook]);
  const recalculate = React.useCallback(() => {
    if (!workbook) {
      return;
    }
    const result = tryRecalculate(workbook);
    if (result.calculated) {
      refreshWorkbookState(workbook);
      return;
    }
    setShouldAutoCalculate(false);
  }, [refreshWorkbookState, workbook]);
  const applyReadOnlyResizeOverride = React.useCallback((axis, indices, sizePx) => {
    if (!activeSheet) return;
    const contentSizePx = activeSheet.officeLayout ? sizePx : resolveContentSheetAxisPixels(sizePx, activeSheet.showGridLines);
    const selected = new Set(indices);
    setSheets((current) => current.map((sheet) => {
      if (sheet.workbookSheetIndex !== activeSheet.workbookSheetIndex) return sheet;
      const isRow = axis === "row";
      const overrides = { ...isRow ? sheet.rowHeightOverridesPx : sheet.colWidthOverridesPx };
      for (const index of selected) overrides[index] = contentSizePx;
      const visible = isRow ? sheet.visibleRows : sheet.visibleCols;
      const sizes = (isRow ? sheet.rowHeights : sheet.colWidths).map((size, offset) => selected.has(visible[offset]) ? contentSizePx : size);
      return isRow ? { ...sheet, rowHeightOverridesPx: overrides, rowHeights: sizes } : { ...sheet, colWidthOverridesPx: overrides, colWidths: sizes };
    }));
    setRevision((current) => current + 1);
  }, [activeSheet]);
  const canChangeVisibility = Boolean(activeSheet && !isLoading && (readOnly ? allowHideInReadOnly : workbook));
  const canChangeFreezePanes = Boolean(activeSheet && !isLoading && (readOnly ? allowFreezeInReadOnly : workbook));
  const activeLayout = activeSheet && readOnly ? readOnlyLayouts[activeSheet.workbookSheetIndex] : void 0;
  React.useEffect(() => {
    if (!activeCell || !activeLayout) return;
    const { hiddenRows, hiddenCols } = activeLayout;
    const row2 = hiddenRows?.has(activeCell.row) ? nextVisibleIndex(activeCell.row, XLSX_MAX_ROWS, (index) => hiddenRows.has(index)) : activeCell.row;
    const col = hiddenCols?.has(activeCell.col) ? nextVisibleIndex(activeCell.col, XLSX_MAX_COLUMNS, (index) => hiddenCols.has(index)) : activeCell.col;
    if (row2 === activeCell.row && col === activeCell.col) return;
    const cell = row2 < 0 || col < 0 ? null : { row: row2, col };
    setActiveCell(cell);
    setSelection(cell && { start: cell, end: cell });
    selectionAnchorRef.current = cell;
  }, [activeCell, activeLayout, setSelection]);
  const setAxisHidden = React.useCallback((axis, hidden, start, end = start) => {
    if (!canChangeVisibility || !activeSheet) return;
    const limit = axis === "row" ? XLSX_MAX_ROWS : XLSX_MAX_COLUMNS;
    const fromSelection = start === void 0 && end === void 0;
    const ranges = fromSelection ? selectionRanges.map((area) => ({ start: area.start[axis], end: area.end[axis] })) : [{ start: start ?? -1, end: end ?? -1 }];
    if (!ranges.length || ranges.some((range) => !Number.isInteger(range.start) || !Number.isInteger(range.end) || range.start < 0 || range.end < range.start || range.end >= limit)) return;
    const sheetIndex = activeSheet.workbookSheetIndex;
    if (readOnly) {
      const key = axis === "row" ? "hiddenRows" : "hiddenCols";
      setReadOnlyLayouts((current) => {
        const layout = current[sheetIndex];
        const existing = layout?.[key] ?? new Set(activeSheet[key]);
        const changes = changedVisibilityRanges(existing, ranges, hidden, fromSelection);
        if (!changes.length) return current;
        const next = new Set(existing);
        for (const range of changes) {
          for (let index = range.start; index <= range.end; index++) {
            if (hidden) next.add(index);
            else next.delete(index);
          }
        }
        return { ...current, [sheetIndex]: { ...layout, [key]: next } };
      });
      return;
    }
    if (!workbook) return;
    const worksheet = workbook.getSheet(sheetIndex);
    try {
      const existing = new Set(axis === "row" ? worksheet.hiddenRows : worksheet.hiddenColumns);
      const changes = changedVisibilityRanges(existing, ranges, hidden, fromSelection);
      if (!changes.length) return;
      recordHistoryBeforeMutation();
      for (const range of changes) {
        if (axis === "row") worksheet.setRowsHidden(range.start, range.end, hidden);
        else worksheet.setColumnsHidden(range.start, range.end, hidden);
      }
      if (hidden && activeCell && changes.some((range) => range.start <= activeCell[axis] && activeCell[axis] <= range.end)) {
        const index = nextVisibleIndex(
          activeCell[axis],
          limit,
          (value) => axis === "row" ? worksheet.isRowHidden(value) : worksheet.isColumnHidden(value)
        );
        if (index >= 0) {
          const cell = { ...activeCell, [axis]: index };
          setActiveCell(cell);
          setSelection({ start: cell, end: cell });
          selectionAnchorRef.current = cell;
        }
      }
      refreshWorkbookState(workbook);
    } finally {
      worksheet.free();
    }
  }, [activeCell, activeSheet, canChangeVisibility, readOnly, recordHistoryBeforeMutation, refreshWorkbookState, selectionRanges, setSelection, workbook]);
  const hideRows = React.useCallback((start, end) => setAxisHidden("row", true, start, end), [setAxisHidden]);
  const unhideRows = React.useCallback((start, end) => setAxisHidden("row", false, start, end), [setAxisHidden]);
  const hideColumns = React.useCallback((start, end) => setAxisHidden("col", true, start, end), [setAxisHidden]);
  const unhideColumns = React.useCallback((start, end) => setAxisHidden("col", false, start, end), [setAxisHidden]);
  const setFreezeBoundary = React.useCallback((cell) => {
    if (!canChangeFreezePanes || !activeSheet) return;
    const { row: row2, col } = cell;
    if (!Number.isInteger(row2) || row2 < 0 || row2 >= XLSX_MAX_ROWS || !Number.isInteger(col) || col < 0 || col >= XLSX_MAX_COLUMNS) return;
    const sheetIndex = activeSheet.workbookSheetIndex;
    if (readOnly) {
      const freezePanes2 = row2 || col ? { row: row2, col } : null;
      setReadOnlyLayouts((current) => ({ ...current, [sheetIndex]: { ...current[sheetIndex], freezePanes: freezePanes2 } }));
      return;
    }
    if (!workbook) return;
    const worksheet = workbook.getSheet(sheetIndex);
    try {
      const current = parseWorksheetFreezePanes(worksheet);
      if (row2 === (current?.row ?? 0) && col === (current?.col ?? 0)) return;
      recordHistoryBeforeMutation();
      worksheet.setFreezePanes(row2, col);
      refreshWorkbookState(workbook);
    } finally {
      worksheet.free();
    }
  }, [activeSheet, canChangeFreezePanes, readOnly, recordHistoryBeforeMutation, refreshWorkbookState, workbook]);
  const freezeCell = resolveFreezePanesCell(activeCell, selection);
  const canFreezePanes = Boolean(canChangeFreezePanes && freezeCell && (freezeCell.row > 0 || freezeCell.col > 0));
  const freezePanes = React.useCallback((cell = freezeCell) => {
    if (cell) setFreezeBoundary(cell);
  }, [freezeCell, setFreezeBoundary]);
  const unfreezePanes = React.useCallback(() => setFreezeBoundary({ row: 0, col: 0 }), [setFreezeBoundary]);
  const resizeAxis = React.useCallback((axis, target, sizePx) => {
    if (!canResize || !activeSheet || !Number.isFinite(sizePx)) return;
    const indices = typeof target === "number" ? [target] : target;
    const limit = axis === "row" ? XLSX_MAX_ROWS : XLSX_MAX_COLUMNS;
    if (!indices.length || indices.some((index) => !Number.isInteger(index) || index < 0 || index >= limit)) return;
    if (isWorkerBacked) {
      applyReadOnlyResizeOverride(axis, indices, sizePx);
      return;
    }
    if (!workbook) return;
    const worksheet = workbook.getSheet(activeSheet.workbookSheetIndex);
    try {
      recordHistoryBeforeMutation();
      const contentPx = resolveContentSheetAxisPixels(sizePx, activeSheet.showGridLines);
      if (axis === "row") {
        const points = activeSheet.officeLayout ? Math.max(sizePx, MIN_ROW_HEIGHT_PX) * 3 / 4 : pxToSheetRowHeight(contentPx);
        for (const index of indices) worksheet.setRowHeight(index, points);
      } else {
        const width = activeSheet.officeLayout ? pxToOfficeColumnWidth(sizePx, activeSheet.officeLayout.columnDigitWidthPt) : pxToSheetColumnWidth(contentPx, activeSheet.columnWidthCharacterWidthPx);
        for (const index of indices) worksheet.setColumnWidth(index, width);
      }
      refreshWorkbookState(workbook);
    } finally {
      worksheet.free();
    }
  }, [activeSheet, applyReadOnlyResizeOverride, canResize, isWorkerBacked, recordHistoryBeforeMutation, refreshWorkbookState, workbook]);
  const resizeColumn = React.useCallback((col, widthPx) => resizeAxis("column", col, widthPx), [resizeAxis]);
  const resizeRow = React.useCallback((row2, heightPx) => resizeAxis("row", row2, heightPx), [resizeAxis]);
  const resolveAnchoredObjectRect = React.useCallback((anchor, worksheet) => {
    const resolveAxisSum = (index, getSize) => {
      let total = 0;
      for (let cursor = 0; cursor < index; cursor += 1) {
        total += getSize(cursor);
      }
      return total;
    };
    if (anchor.kind === "absolute") {
      return {
        height: anchor.sizeEmu.cy / 9525,
        left: GRID_ROW_HEADER_WIDTH + anchor.positionEmu.x / 9525,
        top: GRID_HEADER_HEIGHT + anchor.positionEmu.y / 9525,
        width: anchor.sizeEmu.cx / 9525
      };
    }
    const left = GRID_ROW_HEADER_WIDTH + resolveAxisSum(anchor.from.col, (col) => getColumnWidthPx(worksheet, col)) + anchor.from.colOffsetEmu / 9525;
    const top = GRID_HEADER_HEIGHT + resolveAxisSum(anchor.from.row, (row2) => getRowHeightPx(worksheet, row2)) + anchor.from.rowOffsetEmu / 9525;
    if (anchor.kind === "one-cell") {
      return {
        height: anchor.sizeEmu.cy / 9525,
        left,
        top,
        width: anchor.sizeEmu.cx / 9525
      };
    }
    const right = GRID_ROW_HEADER_WIDTH + resolveAxisSum(anchor.to.col, (col) => getColumnWidthPx(worksheet, col)) + anchor.to.colOffsetEmu / 9525;
    const bottom = GRID_HEADER_HEIGHT + resolveAxisSum(anchor.to.row, (row2) => getRowHeightPx(worksheet, row2)) + anchor.to.rowOffsetEmu / 9525;
    return {
      height: Math.max(1, bottom - top),
      left,
      top,
      width: Math.max(1, right - left)
    };
  }, [getColumnWidthPx, getRowHeightPx]);
  const setChartRect = React.useCallback((id, rect, layout) => {
    const hydratedChartAssets = ensureChartAssetsHydrated(workbook, sheets);
    if (readOnly || !workbook || !activeSheet) {
      return;
    }
    const worksheet = workbook.getSheet(activeSheet.workbookSheetIndex);
    const currentChart = getChartById(id);
    if (!currentChart || currentChart.editable === false || currentChart.workbookSheetIndex !== activeSheet.workbookSheetIndex) {
      return;
    }
    const nextAnchor = rectToImageAnchor(rect, currentChart.anchor, {
      contentOffsetLeft: GRID_ROW_HEADER_WIDTH,
      contentOffsetTop: GRID_HEADER_HEIGHT,
      getColumnWidthPx: (col) => layout?.columnWidths[col] ?? getColumnWidthPx(worksheet, col),
      getRowHeightPx: (row2) => layout?.rowHeights[row2] ?? getRowHeightPx(worksheet, row2)
    });
    if (currentChart.raw?.pivotSource && currentChart.name) {
      commitPivotMutation((target) => pivotWorkbook(target).updatePivotChart(worksheet.name, currentChart.name, {
        anchor: xlsxAnchorToDukeDrawingAnchor(nextAnchor)
      }), false);
      return;
    }
    if (!imageAssetsRef.current || !hydratedChartAssets) return;
    recordHistoryBeforeMutation();
    if (!updateWorkbookChartAnchor(imageAssetsRef.current, hydratedChartAssets, id, nextAnchor)) return;
    hydratedChartAssets.chartsByWorkbookSheetIndex = hydratedChartAssets.chartsByWorkbookSheetIndex.map((sheetCharts) => sheetCharts.map((chart) => chart.id === id ? { ...chart, anchor: nextAnchor } : chart));
    setChartsByWorkbookSheetIndex((current) => current.map((sheetCharts) => sheetCharts.map((chart) => chart.id === id ? { ...chart, anchor: nextAnchor } : chart)));
    setRevision((current) => current + 1);
  }, [
    activeSheet,
    commitPivotMutation,
    getChartById,
    getColumnWidthPx,
    getRowHeightPx,
    ensureChartAssetsHydrated,
    readOnly,
    recordHistoryBeforeMutation,
    sheets,
    workbook
  ]);
  const setImageRect = React.useCallback((id, rect, layout) => {
    if (readOnly || !workbook || !activeSheet || !imageAssetsRef.current) {
      return;
    }
    const worksheet = workbook.getSheet(activeSheet.workbookSheetIndex);
    const currentImage = getImageById(id);
    if (!currentImage || currentImage.editable === false || currentImage.workbookSheetIndex !== activeSheet.workbookSheetIndex) {
      return;
    }
    const nextAnchor = rectToImageAnchor(rect, currentImage.anchor, {
      contentOffsetLeft: GRID_ROW_HEADER_WIDTH,
      contentOffsetTop: GRID_HEADER_HEIGHT,
      getColumnWidthPx: (col) => layout?.columnWidths[col] ?? getColumnWidthPx(worksheet, col),
      getRowHeightPx: (row2) => layout?.rowHeights[row2] ?? getRowHeightPx(worksheet, row2)
    });
    recordHistoryBeforeMutation();
    if (!updateWorkbookImageAnchor(imageAssetsRef.current, id, nextAnchor)) {
      return;
    }
    setImagesByWorkbookSheetIndex([...imageAssetsRef.current.imagesByWorkbookSheetIndex]);
    setRevision((current) => current + 1);
  }, [
    activeSheet,
    getColumnWidthPx,
    getImageById,
    getRowHeightPx,
    readOnly,
    recordHistoryBeforeMutation,
    workbook
  ]);
  const moveChartBy = React.useCallback((id, deltaX, deltaY) => {
    const currentChart = getChartById(id);
    if (!currentChart || currentChart.editable === false) {
      return;
    }
    const worksheet = getActiveWorksheet();
    if (!worksheet) {
      return;
    }
    const currentRect = resolveAnchoredObjectRect(currentChart.anchor, worksheet);
    setChartRect(id, {
      ...currentRect,
      left: currentRect.left + deltaX,
      top: currentRect.top + deltaY
    });
  }, [getActiveWorksheet, getChartById, resolveAnchoredObjectRect, setChartRect]);
  const moveImageBy = React.useCallback((id, deltaX, deltaY) => {
    const currentImage = getImageById(id);
    if (!currentImage || currentImage.editable === false) {
      return;
    }
    const currentRect = (() => {
      const worksheet = getActiveWorksheet();
      if (!worksheet) {
        return null;
      }
      const resolveAxisSum = (index, getSize) => {
        let total = 0;
        for (let cursor = 0; cursor < index; cursor += 1) {
          total += getSize(cursor);
        }
        return total;
      };
      if (currentImage.anchor.kind === "absolute") {
        return {
          height: currentImage.anchor.sizeEmu.cy / 9525,
          left: GRID_ROW_HEADER_WIDTH + currentImage.anchor.positionEmu.x / 9525,
          top: GRID_HEADER_HEIGHT + currentImage.anchor.positionEmu.y / 9525,
          width: currentImage.anchor.sizeEmu.cx / 9525
        };
      }
      const left = GRID_ROW_HEADER_WIDTH + resolveAxisSum(currentImage.anchor.from.col, (col) => getColumnWidthPx(worksheet, col)) + currentImage.anchor.from.colOffsetEmu / 9525;
      const top = GRID_HEADER_HEIGHT + resolveAxisSum(currentImage.anchor.from.row, (row2) => getRowHeightPx(worksheet, row2)) + currentImage.anchor.from.rowOffsetEmu / 9525;
      if (currentImage.anchor.kind === "one-cell") {
        return {
          height: currentImage.anchor.sizeEmu.cy / 9525,
          left,
          top,
          width: currentImage.anchor.sizeEmu.cx / 9525
        };
      }
      const right = GRID_ROW_HEADER_WIDTH + resolveAxisSum(currentImage.anchor.to.col, (col) => getColumnWidthPx(worksheet, col)) + currentImage.anchor.to.colOffsetEmu / 9525;
      const bottom = GRID_HEADER_HEIGHT + resolveAxisSum(currentImage.anchor.to.row, (row2) => getRowHeightPx(worksheet, row2)) + currentImage.anchor.to.rowOffsetEmu / 9525;
      return {
        height: Math.max(1, bottom - top),
        left,
        top,
        width: Math.max(1, right - left)
      };
    })();
    if (!currentRect) {
      return;
    }
    setImageRect(id, {
      ...currentRect,
      left: currentRect.left + deltaX,
      top: currentRect.top + deltaY
    });
  }, [getActiveWorksheet, getColumnWidthPx, getImageById, getRowHeightPx, setImageRect]);
  const resizeChartBy = React.useCallback((id, handle, deltaX, deltaY) => {
    const currentChart = getChartById(id);
    if (!currentChart || currentChart.editable === false) {
      return;
    }
    const worksheet = getActiveWorksheet();
    if (!worksheet) {
      return;
    }
    const currentRect = resolveAnchoredObjectRect(currentChart.anchor, worksheet);
    setChartRect(id, resizeImageRect(currentRect, handle, deltaX, deltaY, 48));
  }, [getActiveWorksheet, getChartById, resolveAnchoredObjectRect, setChartRect]);
  const resizeImageBy = React.useCallback((id, handle, deltaX, deltaY) => {
    const currentImage = getImageById(id);
    if (!currentImage || currentImage.editable === false) {
      return;
    }
    const worksheet = getActiveWorksheet();
    if (!worksheet) {
      return;
    }
    const resolveAxisSum = (index, getSize) => {
      let total = 0;
      for (let cursor = 0; cursor < index; cursor += 1) {
        total += getSize(cursor);
      }
      return total;
    };
    const left = currentImage.anchor.kind === "absolute" ? GRID_ROW_HEADER_WIDTH + currentImage.anchor.positionEmu.x / 9525 : GRID_ROW_HEADER_WIDTH + resolveAxisSum(currentImage.anchor.from.col, (col) => getColumnWidthPx(worksheet, col)) + currentImage.anchor.from.colOffsetEmu / 9525;
    const top = currentImage.anchor.kind === "absolute" ? GRID_HEADER_HEIGHT + currentImage.anchor.positionEmu.y / 9525 : GRID_HEADER_HEIGHT + resolveAxisSum(currentImage.anchor.from.row, (row2) => getRowHeightPx(worksheet, row2)) + currentImage.anchor.from.rowOffsetEmu / 9525;
    const width = currentImage.anchor.kind === "two-cell" ? Math.max(
      1,
      GRID_ROW_HEADER_WIDTH + resolveAxisSum(currentImage.anchor.to.col, (col) => getColumnWidthPx(worksheet, col)) + currentImage.anchor.to.colOffsetEmu / 9525 - left
    ) : currentImage.anchor.sizeEmu.cx / 9525;
    const height = currentImage.anchor.kind === "two-cell" ? Math.max(
      1,
      GRID_HEADER_HEIGHT + resolveAxisSum(currentImage.anchor.to.row, (row2) => getRowHeightPx(worksheet, row2)) + currentImage.anchor.to.rowOffsetEmu / 9525 - top
    ) : currentImage.anchor.sizeEmu.cy / 9525;
    const nextRect = resizeImageRect({ height, left, top, width }, handle, deltaX, deltaY);
    setImageRect(id, nextRect);
  }, [getActiveWorksheet, getColumnWidthPx, getImageById, getRowHeightPx, setImageRect]);
  const commitDrawingArchiveMutation = React.useCallback(async (mutate, target) => {
    if (readOnly || !workbook || !imageAssetsRef.current) return false;
    const currentCharts = ensureChartAssetsHydrated(workbook, sheets);
    if (!currentCharts) return false;
    const state = drawingMutationState.current;
    const epoch = ++drawingMutationEpoch.current;
    const generation = loadGenerationRef.current;
    const before = createHistoryEntry();
    if (!before) return false;
    const assets = structuredClone(imageAssetsRef.current);
    if (!mutate(assets, structuredClone(currentCharts))) return false;
    const bytes = await getWorkerClient().exportWorkbook(before.bytes, assets, assets.sheetOrigins);
    const wasm = await getSheetsWasmModule();
    configureWorkbookArchiveDecoder(wasm.decodeArchive);
    configureWorkbookXmlDecoder(wasm.parseXmlTree);
    const next = wasm.Workbook.fromBytes(bytes);
    let nextAssets = null;
    let published = false;
    try {
      nextAssets = await loadWorkbookImageAssets(bytes, next);
      const latest = drawingMutationState.current;
      if (epoch !== drawingMutationEpoch.current || generation !== loadGenerationRef.current || latest.workbook !== state.workbook || latest.revision !== state.revision || latest.readOnly) {
        revokeWorkbookImageAssets(nextAssets);
        next.free();
        return false;
      }
      pushHistoryEntry(undoStackRef.current, before);
      redoStackRef.current = [];
      setHistoryRevision((current) => current + 1);
      drawingMutationEpoch.current++;
      published = true;
      setImageAssets(nextAssets);
      setWorkbook(next);
      refreshWorkbookState(next);
      setSelectedImageId(null);
      setSelectedChartId(null);
      setSelectedChartElement(null);
      if (target.kind === "chart") {
        const chart = chartAssetsRef.current?.chartsByWorkbookSheetIndex.flat().find((chart2) => target.path ? chart2.chartPath === target.path : chart2.name === target.name);
        setSelectedChartId(chart?.id ?? null);
        setSelectedChartElement(chart ? { kind: "chart", chartId: chart.id } : null);
      } else if (target.kind === "image") {
        const image = nextAssets?.imagesByWorkbookSheetIndex.flat().find((image2) => image2.name === target.name);
        setSelectedImageId(image?.id ?? null);
      }
      return true;
    } catch (cause) {
      if (!published) {
        revokeWorkbookImageAssets(nextAssets);
        next.free();
      }
      throw cause;
    }
  }, [createHistoryEntry, ensureChartAssetsHydrated, getWorkerClient, readOnly, refreshWorkbookState, setImageAssets, sheets, workbook]);
  const pasteDrawing = React.useCallback(async (data) => {
    if (readOnly || !activeSheet || !workbook) return false;
    const name = `${data.kind === "chart" ? "Chart" : data.kind === "shape" ? "Shape" : "Picture"} ${crypto.randomUUID().slice(0, 8)}`;
    const cell = activeCell ?? { row: 0, col: 0 };
    const placement = { kind: "one-cell", from: { ...cell, colOffsetEmu: 0, rowOffsetEmu: 0 }, sizeEmu: data.sizeEmu ?? { cx: 4572e3, cy: 2743200 } };
    return commitDrawingArchiveMutation((assets) => {
      pasteDrawingClipboard(assets, data, activeSheet.workbookSheetIndex, name, placement);
      return true;
    }, { kind: data.kind, name });
  }, [activeCell, activeSheet, commitDrawingArchiveMutation, readOnly, workbook]);
  const pasteDrawingFromClipboard = React.useCallback(async (input) => {
    if (readOnly || !activeSheet || !workbook) return false;
    const state = drawingMutationState.current;
    const generation = loadGenerationRef.current;
    const data = input === void 0 ? (await readBrowserClipboard()).drawing : typeof input === "string" ? decodeExcelDrawingClipboard(input) : input.type.startsWith("image/") ? await imageDrawingClipboard(input) : decodeExcelDrawingClipboard(new Uint8Array(await input.arrayBuffer()));
    const latest = drawingMutationState.current;
    if (!data || generation !== loadGenerationRef.current || latest.workbook !== state.workbook || latest.revision !== state.revision || latest.readOnly || latest.activeSheetIndex !== state.activeSheetIndex || latest.activeCell?.row !== state.activeCell?.row || latest.activeCell?.col !== state.activeCell?.col) return false;
    return pasteDrawing(data);
  }, [activeSheet, pasteDrawing, readOnly, workbook]);
  const arrangeDrawing = React.useCallback(async (kind, id, order) => {
    const assets = imageAssetsRef.current;
    const charts2 = ensureChartAssetsHydrated(workbook, sheets);
    const drawing = kind === "image" ? getImageById(id) : getChartById(id);
    if (readOnly || !workbook || !assets || !charts2 || !drawing || drawing.editable === false) return false;
    const plan = prepareDrawingOrder(assets, charts2, kind, id, order);
    if (!plan) return false;
    const mapIndex = (index) => index === plan.from ? plan.to : plan.from < plan.to && index > plan.from && index <= plan.to ? index - 1 : plan.from > plan.to && index >= plan.to && index < plan.from ? index + 1 : index;
    const chartIndices = new Map(Array.from(charts2.chartOriginsById, ([chartId, origin]) => {
      const found = findDrawingAnchor(assets, charts2, "chart", chartId);
      return [chartId, found && origin.workbookSheetIndex === plan.sheetIndex ? mapIndex(found.anchors.indexOf(found.anchor)) : null];
    }));
    recordHistoryBeforeMutation();
    workbook.getSheet(plan.sheetIndex).moveDrawing(plan.from, plan.to);
    plan.commit();
    const orderedCharts = [...chartIndices].filter((entry) => entry[1] !== null).sort((a, b) => a[1] - b[1]);
    orderedCharts.forEach(([chartId], index) => {
      charts2.chartOriginsById.get(chartId).anchorIndex = index;
    });
    charts2.chartsByWorkbookSheetIndex = charts2.chartsByWorkbookSheetIndex.map((items, sheetIndex) => sheetIndex !== plan.sheetIndex ? items : items.map((chart) => ({ ...chart, zIndex: (chartIndices.get(chart.id) ?? chart.zIndex - 1) + 1 })));
    for (const origin of assets.imageOriginsById.values()) if (origin.workbookSheetIndex === plan.sheetIndex) origin.anchorIndex = mapIndex(origin.anchorIndex);
    const updateOrder = (items) => items.map((sheet, index) => index !== plan.sheetIndex ? sheet : sheet.map((item) => ({ ...item, zIndex: mapIndex(Math.floor(item.zIndex) - 1) + 1 + item.zIndex % 1 })));
    assets.imagesByWorkbookSheetIndex = updateOrder(assets.imagesByWorkbookSheetIndex);
    assets.shapesByWorkbookSheetIndex = updateOrder(assets.shapesByWorkbookSheetIndex);
    assets.formControlsByWorkbookSheetIndex = updateOrder(assets.formControlsByWorkbookSheetIndex);
    setImagesByWorkbookSheetIndex(assets.imagesByWorkbookSheetIndex);
    setShapesByWorkbookSheetIndex(assets.shapesByWorkbookSheetIndex);
    setFormControlsByWorkbookSheetIndex(assets.formControlsByWorkbookSheetIndex);
    setChartsByWorkbookSheetIndex(charts2.chartsByWorkbookSheetIndex);
    setRevision((current) => current + 1);
    return true;
  }, [ensureChartAssetsHydrated, getChartById, getImageById, readOnly, recordHistoryBeforeMutation, sheets, workbook]);
  const changeChartType = React.useCallback(async (id, type) => {
    const chart = getChartById(id);
    const option = chartTypeOptions.find((option2) => option2.id === type);
    if (readOnly || !chart || !option || chartTypeUnavailable(chart, option)) return false;
    if (chart.raw?.pivotSource) {
      if (!workbook || !chart.name) return false;
      commitPivotMutation((target) => pivotWorkbook(target).updatePivotChart(workbook.getSheet(chart.workbookSheetIndex).name, chart.name, { chartType: option.chartType }), false);
      return true;
    }
    const assets = imageAssetsRef.current;
    const charts2 = ensureChartAssetsHydrated(workbook, sheets);
    if (readOnly || !workbook || !assets || !charts2) return false;
    const origin = charts2.chartOriginsById.get(id);
    const found = findDrawingAnchor(assets, charts2, "chart", id);
    if (!origin || !found) return false;
    const index = found.anchors.indexOf(found.anchor);
    const native = workbook.getSheet(chart.workbookSheetIndex).drawings[index];
    if (!native || !native.anchor || native.kind !== "chart" && native.kind !== "chartEx") return false;
    const nextAssets = { ...assets, archive: { ...assets.archive }, dirtyArchivePaths: new Set(assets.dirtyArchivePaths) };
    changeWorkbookChartType(nextAssets, origin, chart, option);
    recordHistoryBeforeMutation();
    const base = { anchor: native.anchor, name: native.name, hidden: native.hidden, locked: native.locked, printable: native.printable };
    const input = option.layout ? { ...base, kind: "chartEx", chartEx: { layout: option.layout, title: { text: chart.title } } } : { ...base, kind: "chart", chart: { ...native.kind === "chart" ? native.chart : {}, chartType: option.chartType } };
    workbook.getSheet(chart.workbookSheetIndex).setDrawing([index], input);
    assets.archive = nextAssets.archive;
    assets.dirtyArchivePaths = nextAssets.dirtyArchivePaths;
    origin.chartKind = option.layout ? "modern" : "classic";
    const nextChart = refreshChartRenderSource({ ...chart, chartType: option.chartType, chartExLayout: option.layout, is3d: option.is3d, typeGroups: void 0 }, assets, workbook);
    charts2.chartsByWorkbookSheetIndex = charts2.chartsByWorkbookSheetIndex.map((items) => items.map((item) => item.id === id ? nextChart : item));
    setChartsByWorkbookSheetIndex(charts2.chartsByWorkbookSheetIndex);
    setSelectedChartElement({ kind: "chart", chartId: id });
    setRevision((current) => current + 1);
    return true;
  }, [commitPivotMutation, ensureChartAssetsHydrated, getChartById, readOnly, recordHistoryBeforeMutation, sheets, workbook]);
  const updateChart = React.useCallback((id, patch) => {
    const currentChart = getChartById(id);
    const hydratedChartAssets = ensureChartAssetsHydrated(workbook, sheets);
    if (readOnly || !currentChart) {
      return;
    }
    if (currentChart.raw?.pivotSource) {
      if (!workbook || !currentChart.name) return;
      if (Object.keys(patch).some((key) => !["title", "chartType", "anchor"].includes(key))) {
        throw new Error("Change PivotChart data through the pivot table field settings.");
      }
      const sheetName = workbook.getSheet(currentChart.workbookSheetIndex).name;
      commitPivotMutation((target) => pivotWorkbook(target).updatePivotChart(sheetName, currentChart.name, {
        title: patch.title,
        chartType: patch.chartType,
        anchor: patch.anchor ? xlsxAnchorToDukeDrawingAnchor(patch.anchor) : void 0
      }), false);
      return;
    }
    recordHistoryBeforeMutation();
    if (patch.anchor && imageAssetsRef.current && hydratedChartAssets) {
      updateWorkbookChartAnchor(imageAssetsRef.current, hydratedChartAssets, id, patch.anchor);
    }
    if (imageAssetsRef.current && hydratedChartAssets) {
      updateWorkbookChartDefinition(imageAssetsRef.current, hydratedChartAssets, id, patch);
    }
    setChartsByWorkbookSheetIndex((current) => current.map((sheetCharts) => sheetCharts.map((chart) => {
      if (chart.id !== id) return chart;
      const nextChart = { ...chart, ...patch, renderSource: patch.renderSource ?? chart.renderSource };
      return imageAssetsRef.current ? refreshChartRenderSource(nextChart, imageAssetsRef.current, workbook) : nextChart;
    })));
    setRevision((current) => current + 1);
  }, [commitPivotMutation, ensureChartAssetsHydrated, getChartById, readOnly, recordHistoryBeforeMutation, sheets, workbook]);
  const setChartSeriesFormula = React.useCallback((chartId, seriesIndex, formula) => {
    if (readOnly) {
      return false;
    }
    const chart = getChartById(chartId);
    if (!chart || chart.editable === false || chart.raw?.pivotSource) {
      return false;
    }
    const nextChart = applyChartSeriesFormula(chart, seriesIndex, formula, workbook);
    if (!nextChart) {
      return false;
    }
    updateChart(chartId, {
      series: nextChart.series,
      typeGroups: nextChart.typeGroups,
      raw: nextChart.raw
    });
    const selectedSeries = nextChart.series[seriesIndex];
    if (selectedSeries) {
      setSelectedChartElement((current) => current && current.chartId === chartId && current.kind !== "chart" ? {
        ...current,
        seriesId: selectedSeries.id,
        seriesIndex
      } : current);
    }
    return true;
  }, [getChartById, readOnly, updateChart, workbook]);
  const findSelectionMerge = React.useMemo(() => createMergedRangeLookup(activeSheet?.mergedRanges ?? []), [activeSheet?.mergedRanges]);
  const selectCell = React.useCallback((cell, options3) => {
    const merged = findSelectionMerge(cell);
    const anchorCell = merged?.start ?? cell;
    setSelectedChartId(null);
    setSelectedChartElement(null);
    setSelectedImageId(null);
    setActiveCell(anchorCell);
    if (options3?.extend && selectionAnchorRef.current) {
      setSelection(expandHighlightedRange(normalizeRange({ start: selectionAnchorRef.current, end: cell }), activeSheet?.mergedRanges ?? []));
      return;
    }
    selectionAnchorRef.current = anchorCell;
    setSelection(merged ?? { start: cell, end: cell });
  }, [activeSheet?.mergedRanges, findSelectionMerge]);
  const selectRanges = React.useCallback((ranges, activeCorner = "end") => {
    const areas = ranges.reduce((previous, range) => addSelectionRange(previous, normalizeRange(range)), []);
    const active = areas.at(-1);
    setSelectedChartId(null);
    setSelectedChartElement(null);
    setSelectedImageId(null);
    selectionAnchorRef.current = active?.start ?? null;
    const cell = active?.[activeCorner];
    setActiveCell(cell ? findSelectionMerge(cell)?.start ?? cell : null);
    setSelectionRanges(areas);
  }, [findSelectionMerge]);
  const selectRange = React.useCallback((range) => {
    selectRanges([expandHighlightedRange(normalizeRange(range), activeSheet?.mergedRanges ?? [])]);
  }, [activeSheet?.mergedRanges, selectRanges]);
  const clearSelection = React.useCallback(() => {
    selectionAnchorRef.current = null;
    setActiveCell(null);
    setSelection(null);
    setSelectedChartId(null);
    setSelectedChartElement(null);
    setSelectedImageId(null);
  }, []);
  const clearSelectedCells = React.useCallback(() => {
    const worksheet = getActiveWorksheet();
    if (readOnly || !worksheet || !workbook || !selectionRanges.length || selectionRanges.some(intersectsPivot)) return;
    const mutations = [];
    for (const area of selectionRanges) {
      for (let row2 = area.start.row; row2 <= area.end.row; row2 += 1) {
        for (let col = area.start.col; col <= area.end.col; col += 1) {
          if (worksheet.isMergedSecondary(row2, col)) {
            continue;
          }
          const cell = { row: row2, col };
          const before = captureCellMutationState(cell);
          if (!before) {
            continue;
          }
          worksheet.setCell(cellAddressToA1({ row: row2, col }), "");
          const after = captureCellMutationState(cell);
          if (!after) {
            continue;
          }
          mutations.push({
            after,
            before,
            cell
          });
        }
      }
    }
    maybeRecalculateWorkbook(workbook);
    refreshWorkbookState(workbook);
    recordRangeEditHistory(mutations, selectionRanges, activeCell);
  }, [
    intersectsPivot,
    activeCell,
    captureCellMutationState,
    getActiveWorksheet,
    maybeRecalculateWorkbook,
    readOnly,
    recordRangeEditHistory,
    refreshWorkbookState,
    selectionRanges,
    workbook
  ]);
  const setCellValue = React.useCallback((cell, value) => {
    const worksheet = getActiveWorksheet();
    if (readOnly || !worksheet || !workbook || getPivotTableAtCell(cell)) {
      return;
    }
    const before = captureCellMutationState(cell);
    if (!before) {
      return;
    }
    if (locale !== "en-US" && value === getCellDisplayValue2(cell)) return;
    const nextValue = isTextCell(worksheet, cell) ? value.startsWith("'") ? value.slice(1) : value : coerceUserEnteredValue(value, locale);
    worksheet.setCell(cellAddressToA1(cell), nextValue);
    if (typeof nextValue === "number") applyInputNumberFormat(worksheet, cell, value);
    const after = captureCellMutationState(cell);
    if (!after) {
      return;
    }
    maybeRecalculateWorkbook(workbook);
    refreshWorkbookState(workbook);
    recordCellEditHistory(cell, before, after);
  }, [getPivotTableAtCell, captureCellMutationState, getActiveWorksheet, getCellDisplayValue2, locale, maybeRecalculateWorkbook, readOnly, recordCellEditHistory, refreshWorkbookState, workbook]);
  const setCellFormula = React.useCallback((cell, formula) => {
    const worksheet = getActiveWorksheet();
    if (readOnly || !worksheet || !workbook || getPivotTableAtCell(cell)) {
      return;
    }
    const before = captureCellMutationState(cell);
    if (!before) {
      return;
    }
    const trimmedFormula = formula.trim();
    if (!formula.trim()) {
      worksheet.setCell(cellAddressToA1(cell), "");
    } else {
      worksheet.setFormula(cellAddressToA1(cell), normalizeFormulaReferences(formula));
      applyInputNumberFormat(worksheet, cell, formula);
    }
    const after = captureCellMutationState(cell);
    if (!after) {
      return;
    }
    maybeRecalculateWorkbook(workbook);
    refreshWorkbookState(workbook);
    recordCellEditHistory(cell, before, after);
  }, [getPivotTableAtCell, captureCellMutationState, getActiveWorksheet, maybeRecalculateWorkbook, readOnly, recordCellEditHistory, refreshWorkbookState, workbook]);
  const setCellStyle = React.useCallback((cell, style) => {
    const worksheet = getActiveWorksheet();
    if (readOnly || !worksheet || !workbook) {
      return;
    }
    const before = captureCellMutationState(cell);
    if (!before) {
      return;
    }
    worksheet.setCellStyleAt(cell.row, cell.col, style);
    const after = captureCellMutationState(cell);
    if (!after) {
      return;
    }
    refreshWorkbookState(workbook);
    recordCellEditHistory(cell, before, after);
  }, [captureCellMutationState, getActiveWorksheet, readOnly, recordCellEditHistory, refreshWorkbookState, workbook]);
  const setCellStyles = React.useCallback((updates) => {
    const worksheet = getActiveWorksheet();
    if (readOnly || !worksheet || !workbook) return;
    const beforeStates = /* @__PURE__ */ new Map();
    for (const { cell, style } of updates) {
      const key = `${cell.row}:${cell.col}`;
      if (!beforeStates.has(key)) {
        const before = captureCellMutationState(cell);
        if (!before) continue;
        beforeStates.set(key, { cell: { ...cell }, before });
      }
      worksheet.setCellStyleAt(cell.row, cell.col, style);
    }
    if (!beforeStates.size) return;
    const mutations = [];
    for (const { cell, before } of beforeStates.values()) {
      const after = captureCellMutationState(cell);
      if (after) mutations.push({ cell, before, after });
    }
    refreshWorkbookState(workbook);
    recordRangeEditHistory(mutations, selectionRanges, activeCell);
  }, [activeCell, captureCellMutationState, getActiveWorksheet, readOnly, recordRangeEditHistory, refreshWorkbookState, selectionRanges, workbook]);
  const setSelectedCellValue = React.useCallback((value) => {
    if (!activeCell) {
      return;
    }
    setCellValue(activeCell, value);
  }, [activeCell, setCellValue]);
  const setSelectedCellFormula = React.useCallback((formula) => {
    if (!activeCell) {
      return;
    }
    setCellFormula(activeCell, formula);
  }, [activeCell, setCellFormula]);
  const setSelectedFormula = React.useCallback((formula) => {
    if (selectedFormulaTarget?.kind === "chartSeries") {
      return setChartSeriesFormula(selectedFormulaTarget.chartId, selectedFormulaTarget.seriesIndex, formula);
    }
    if (readOnly || !activeCell || getPivotTableAtCell(activeCell)) {
      return false;
    }
    setCellFormula(activeCell, formula);
    return true;
  }, [readOnly, getPivotTableAtCell, activeCell, selectedFormulaTarget, setCellFormula, setChartSeriesFormula]);
  const setSelectedCellStyle = React.useCallback((style) => {
    if (!activeCell) {
      return;
    }
    setCellStyle(activeCell, style);
  }, [activeCell, setCellStyle]);
  const setRangeStyle = React.useCallback((range, style) => {
    const worksheet = getActiveWorksheet();
    if (readOnly || !worksheet || !workbook) {
      return;
    }
    const areas = "start" in range ? [normalizeRange(range)] : range.map(normalizeRange);
    const beforeStates = [];
    for (const area of areas) {
      for (let row2 = area.start.row; row2 <= area.end.row; row2 += 1) {
        for (let col = area.start.col; col <= area.end.col; col += 1) {
          const cell = { row: row2, col };
          const before = captureCellMutationState(cell);
          if (!before) {
            continue;
          }
          beforeStates.push({
            before,
            cell
          });
        }
      }
    }
    if (beforeStates.length === 0) {
      return;
    }
    for (const area of areas) worksheet.setRangeStyle(rangeToA1(area), style);
    const mutations = [];
    for (const mutation of beforeStates) {
      const after = captureCellMutationState(mutation.cell);
      if (!after) {
        continue;
      }
      mutations.push({
        after,
        before: mutation.before,
        cell: mutation.cell
      });
    }
    refreshWorkbookState(workbook);
    recordRangeEditHistory(mutations, selectionRanges, activeCell);
  }, [activeCell, captureCellMutationState, getActiveWorksheet, readOnly, recordRangeEditHistory, refreshWorkbookState, selectionRanges, workbook]);
  const fillSelection = React.useCallback((targetRange) => {
    const worksheet = getActiveWorksheet();
    if (readOnly || !worksheet || !workbook || !selection || selectionRanges.length > 1) {
      return;
    }
    if (intersectsPivot(targetRange)) return;
    const sourceRange = normalizeRange(selection);
    const nextRange = normalizeRange(targetRange);
    const sourceHeight = sourceRange.end.row - sourceRange.start.row + 1;
    const sourceWidth = sourceRange.end.col - sourceRange.start.col + 1;
    if (sourceHeight <= 0 || sourceWidth <= 0) {
      return;
    }
    const mutations = [];
    for (let row2 = nextRange.start.row; row2 <= nextRange.end.row; row2 += 1) {
      for (let col = nextRange.start.col; col <= nextRange.end.col; col += 1) {
        if (rangeContainsCell(sourceRange, { row: row2, col })) {
          continue;
        }
        const targetCell = { row: row2, col };
        const before = captureCellMutationState(targetCell);
        if (!before) {
          continue;
        }
        const sourceRow = sourceRange.start.row + (row2 - nextRange.start.row) % sourceHeight;
        const sourceCol = sourceRange.start.col + (col - nextRange.start.col) % sourceWidth;
        const sourceFormula = worksheet.getFormulaAt(sourceRow, sourceCol);
        const sourceStyle = cloneCellStyle(worksheet.getCellStyleAt(sourceRow, sourceCol));
        if (sourceFormula) {
          worksheet.setFormula(cellAddressToA1(targetCell), sourceFormula);
        } else {
          const sourceValue = normalizeCellValue(worksheet.getCellAt(sourceRow, sourceCol).toJs());
          worksheet.setCell(cellAddressToA1(targetCell), sourceValue);
        }
        if (sourceStyle && typeof sourceStyle === "object") {
          worksheet.setCellStyleAt(targetCell.row, targetCell.col, sourceStyle);
        }
        const after = captureCellMutationState(targetCell);
        if (!after) {
          continue;
        }
        mutations.push({
          after,
          before,
          cell: targetCell
        });
      }
    }
    maybeRecalculateWorkbook(workbook);
    refreshWorkbookState(workbook);
    setSelection(nextRange);
    setActiveCell(nextRange.end);
    selectionAnchorRef.current = nextRange.start;
    recordRangeEditHistory(mutations, [nextRange], nextRange.end);
  }, [intersectsPivot, captureCellMutationState, getActiveWorksheet, maybeRecalculateWorkbook, readOnly, recordRangeEditHistory, refreshWorkbookState, selection, selectionRanges, workbook]);
  const mergeSelection = React.useCallback((mode = "cells") => {
    const worksheet = getActiveWorksheet();
    if (readOnly || !worksheet || !selection || selectionRanges.length > 1 || !workbook) {
      return;
    }
    if (intersectsPivot(selection)) return;
    const mergedRanges = resolveWorksheetMergeMetadata(worksheet).mergedRanges;
    const range = expandHighlightedRange(normalizeRange(selection), mergedRanges);
    const isSingleCell = range.start.row === range.end.row && range.start.col === range.end.col;
    if (isSingleCell && mode !== "center" || mode === "across" && range.start.col === range.end.col) {
      return;
    }
    recordHistoryBeforeMutation();
    for (const merged of mergedRanges) {
      if (rangesIntersect(range, merged)) {
        worksheet.unmergeCells(rangeToA1(merged));
      }
    }
    if (mode === "across") {
      for (let row2 = range.start.row; row2 <= range.end.row; row2 += 1) {
        worksheet.mergeCells(rangeToA1({
          start: { row: row2, col: range.start.col },
          end: { row: row2, col: range.end.col }
        }));
      }
    } else {
      if (!isSingleCell) worksheet.mergeCells(rangeToA1(range));
      if (mode === "center") {
        worksheet.setCellStyleAt(range.start.row, range.start.col, { alignment: { horizontal: "center" } });
      }
    }
    refreshWorkbookState(workbook);
    selectionAnchorRef.current = range.start;
    setSelection(range);
    setActiveCell(range.start);
  }, [intersectsPivot, getActiveWorksheet, readOnly, recordHistoryBeforeMutation, refreshWorkbookState, selection, selectionRanges, workbook]);
  const unmergeSelection = React.useCallback(() => {
    const worksheet = getActiveWorksheet();
    if (readOnly || !worksheet || !selection || selectionRanges.length > 1 || !workbook) {
      return;
    }
    const range = normalizeRange(selection);
    if (intersectsPivot(selection)) return;
    const mergedRanges = resolveWorksheetMergeMetadata(worksheet).mergedRanges.filter((merged) => rangesIntersect(range, merged));
    if (mergedRanges.length === 0) return;
    recordHistoryBeforeMutation();
    for (const merged of mergedRanges) {
      worksheet.unmergeCells(rangeToA1(merged));
    }
    refreshWorkbookState(workbook);
  }, [intersectsPivot, getActiveWorksheet, readOnly, recordHistoryBeforeMutation, refreshWorkbookState, selection, selectionRanges, workbook]);
  const addSheet = React.useCallback((name) => {
    if (readOnly || !workbook) {
      return;
    }
    recordHistoryBeforeMutation();
    const baseName = name?.trim() || "Sheet";
    let candidate = baseName;
    let counter = 2;
    while (workbook.sheetIndex(candidate) !== void 0) {
      candidate = `${baseName} ${counter}`;
      counter += 1;
    }
    workbook.addSheet(candidate);
    sheetOriginsRef.current = [...sheetOriginsRef.current, null];
    setFormControlsByWorkbookSheetIndex((current) => [...current, []]);
    setImagesByWorkbookSheetIndex((current) => [...current, []]);
    setShapesByWorkbookSheetIndex((current) => [...current, []]);
    if (imageAssetsRef.current) {
      imageAssetsRef.current.formControlsByWorkbookSheetIndex = [
        ...imageAssetsRef.current.formControlsByWorkbookSheetIndex,
        []
      ];
    }
    const nextSheets = buildSheetList(
      workbook,
      imageAssetsRef.current?.sheetStatesByWorkbookSheetIndex,
      imageAssetsRef.current?.themePalette,
      imageAssetsRef.current?.styleById,
      imageAssetsRef.current?.namedCellStyleByName,
      imageAssetsRef.current?.tableStyleByName,
      showHiddenSheets
    );
    setSheets(nextSheets);
    const nextChartAssets = imageAssetsRef.current ? loadWorkbookChartAssets(workbook, imageAssetsRef.current, buildVisibleSheetIndexMap(nextSheets), showHiddenSheets) : null;
    if (imageAssetsRef.current) {
      setChartAssets(nextChartAssets);
    }
    const nextIndex = nextSheets.findIndex((sheet) => sheet.name === candidate);
    setActiveSheetIndexState(nextIndex >= 0 ? nextIndex : 0);
    const nextTabIndex = nextChartAssets?.tabs.findIndex((tab) => tab.kind === "sheet" && tab.name === candidate) ?? -1;
    if (nextTabIndex >= 0) {
      setActiveTabIndexState(nextTabIndex);
    }
    setRevision((current) => current + 1);
  }, [readOnly, recordHistoryBeforeMutation, setChartAssets, workbook]);
  const removeActiveSheet = React.useCallback(() => {
    if (readOnly || !workbook || !activeSheet) {
      return;
    }
    recordHistoryBeforeMutation();
    workbook.removeSheet(activeSheet.workbookSheetIndex);
    setPivotTables(readPivotTables(workbook));
    sheetOriginsRef.current = sheetOriginsRef.current.filter((_, index) => index !== activeSheet.workbookSheetIndex);
    setFormControlsByWorkbookSheetIndex((current) => current.filter((_, index) => index !== activeSheet.workbookSheetIndex));
    setImagesByWorkbookSheetIndex((current) => current.filter((_, index) => index !== activeSheet.workbookSheetIndex));
    setShapesByWorkbookSheetIndex((current) => current.filter((_, index) => index !== activeSheet.workbookSheetIndex));
    if (imageAssetsRef.current) {
      imageAssetsRef.current.formControlsByWorkbookSheetIndex = imageAssetsRef.current.formControlsByWorkbookSheetIndex.filter(
        (_, index) => index !== activeSheet.workbookSheetIndex
      );
      imageAssetsRef.current.sheetStatesByWorkbookSheetIndex = imageAssetsRef.current.sheetStatesByWorkbookSheetIndex.filter(
        (_, index) => index !== activeSheet.workbookSheetIndex
      );
    }
    const nextSheets = buildSheetList(
      workbook,
      imageAssetsRef.current?.sheetStatesByWorkbookSheetIndex,
      imageAssetsRef.current?.themePalette,
      imageAssetsRef.current?.styleById,
      imageAssetsRef.current?.namedCellStyleByName,
      imageAssetsRef.current?.tableStyleByName,
      showHiddenSheets
    );
    setSheets(nextSheets);
    if (imageAssetsRef.current) {
      setChartAssets(loadWorkbookChartAssets(workbook, imageAssetsRef.current, buildVisibleSheetIndexMap(nextSheets), showHiddenSheets));
    }
    setActiveSheetIndexState((current) => Math.max(0, Math.min(current, nextSheets.length - 1)));
    setRevision((current) => current + 1);
  }, [activeSheet, readOnly, recordHistoryBeforeMutation, setChartAssets, workbook]);
  const defineNamedRange = React.useCallback((name, range) => {
    if (readOnly || !workbook) {
      return;
    }
    const trimmed = name.trim();
    if (!trimmed) {
      return;
    }
    const targetRange = range ?? (selectionRanges.length === 1 ? selection : null);
    if (!targetRange) {
      return;
    }
    recordHistoryBeforeMutation();
    workbook.defineName(trimmed, rangeToA1(targetRange));
    setRevision((current) => current + 1);
  }, [readOnly, recordHistoryBeforeMutation, selection, selectionRanges, workbook]);
  const pasteText = React.useCallback((text) => {
    const worksheet = getActiveWorksheet();
    const targetCell = activeCell ?? selection?.start ?? null;
    if (readOnly || !worksheet || !workbook || !targetCell || selectionRanges.length > 1 || !text) {
      return false;
    }
    const grid = parseClipboardText(text);
    if (grid.length === 0 || grid.every((row2) => row2.length === 0)) {
      return false;
    }
    if (intersectsPivot({ start: targetCell, end: { row: targetCell.row + grid.length - 1, col: targetCell.col + Math.max(...grid.map((row2) => row2.length)) - 1 } })) return false;
    const mutations = [];
    for (let rowIndex = 0; rowIndex < grid.length; rowIndex += 1) {
      const row2 = grid[rowIndex] ?? [];
      for (let colIndex = 0; colIndex < row2.length; colIndex += 1) {
        const rawValue = row2[colIndex] ?? "";
        const nextCell = {
          col: targetCell.col + colIndex,
          row: targetCell.row + rowIndex
        };
        const before = captureCellMutationState(nextCell);
        if (!before) {
          continue;
        }
        const textCell = isTextCell(worksheet, nextCell);
        const formula = textCell ? null : getUserEnteredFormula(rawValue, locale);
        if (formula) {
          worksheet.setFormula(cellAddressToA1(nextCell), normalizeFormulaReferences(formula));
          applyInputNumberFormat(worksheet, nextCell, formula);
          const after = captureCellMutationState(nextCell);
          if (!after) {
            continue;
          }
          mutations.push({
            after,
            before,
            cell: nextCell
          });
        } else {
          const nextValue = textCell ? rawValue : coerceUserEnteredValue(rawValue, locale, "paste");
          worksheet.setCell(cellAddressToA1(nextCell), nextValue);
          if (typeof nextValue === "number") applyInputNumberFormat(worksheet, nextCell, rawValue);
          const after = captureCellMutationState(nextCell);
          if (!after) {
            continue;
          }
          mutations.push({
            after,
            before,
            cell: nextCell
          });
        }
      }
    }
    maybeRecalculateWorkbook(workbook);
    refreshWorkbookState(workbook);
    const nextRange = normalizeRange({
      start: targetCell,
      end: {
        col: targetCell.col + Math.max(0, Math.max(...grid.map((row2) => row2.length), 1) - 1),
        row: targetCell.row + grid.length - 1
      }
    });
    setActiveCell(targetCell);
    setSelection(nextRange);
    selectionAnchorRef.current = targetCell;
    recordRangeEditHistory(mutations, [nextRange], targetCell);
    return true;
  }, [intersectsPivot, activeCell, captureCellMutationState, getActiveWorksheet, locale, maybeRecalculateWorkbook, readOnly, recordRangeEditHistory, refreshWorkbookState, selection, selectionRanges, workbook]);
  const pasteStructuredClipboardData = React.useCallback((serializedPayload) => {
    const worksheet = getActiveWorksheet();
    const targetCell = activeCell ?? selection?.start ?? null;
    if (readOnly || !worksheet || !workbook || !targetCell || selectionRanges.length > 1 || !serializedPayload) {
      return false;
    }
    let payload;
    try {
      payload = JSON.parse(serializedPayload);
    } catch {
      return false;
    }
    if (!Array.isArray(payload.cells) || payload.cells.length === 0) {
      return false;
    }
    if (payload.cells.some((cell) => intersectsPivot({
      start: { row: targetCell.row + cell.rowOffset, col: targetCell.col + cell.colOffset },
      end: { row: targetCell.row + cell.rowOffset, col: targetCell.col + cell.colOffset }
    })) || (Array.isArray(payload.merges) ? payload.merges : []).some((merge) => intersectsPivot({
      start: { row: targetCell.row + merge.rowOffset, col: targetCell.col + merge.colOffset },
      end: { row: targetCell.row + merge.rowOffset + merge.rowSpan - 1, col: targetCell.col + merge.colOffset + merge.colSpan - 1 }
    }))) return false;
    const hasMergeOperations = Array.isArray(payload.merges) && payload.merges.some((merge) => (merge.rowSpan ?? 1) > 1 || (merge.colSpan ?? 1) > 1);
    const mutations = [];
    if (hasMergeOperations) {
      recordHistoryBeforeMutation();
    }
    for (const cell of payload.cells) {
      const nextCell = {
        col: targetCell.col + cell.colOffset,
        row: targetCell.row + cell.rowOffset
      };
      const before = hasMergeOperations ? null : captureCellMutationState(nextCell);
      if (cell.formula) {
        worksheet.setFormula(cellAddressToA1(nextCell), cell.formula);
        if (before) {
          const after = captureCellMutationState(nextCell);
          if (!after) {
            continue;
          }
          mutations.push({
            after,
            before,
            cell: nextCell
          });
        }
      } else {
        worksheet.setCell(cellAddressToA1(nextCell), cell.value);
        if (before) {
          const after = captureCellMutationState(nextCell);
          if (!after) {
            continue;
          }
          mutations.push({
            after,
            before,
            cell: nextCell
          });
        }
      }
    }
    if (Array.isArray(payload.merges)) {
      for (const merge of payload.merges) {
        if ((merge.rowSpan ?? 1) <= 1 && (merge.colSpan ?? 1) <= 1) {
          continue;
        }
        const mergeRange = normalizeRange({
          start: {
            col: targetCell.col + merge.colOffset,
            row: targetCell.row + merge.rowOffset
          },
          end: {
            col: targetCell.col + merge.colOffset + merge.colSpan - 1,
            row: targetCell.row + merge.rowOffset + merge.rowSpan - 1
          }
        });
        worksheet.mergeCells(rangeToA1(mergeRange));
      }
    }
    maybeRecalculateWorkbook(workbook);
    refreshWorkbookState(workbook);
    const nextRange = normalizeRange({
      start: targetCell,
      end: {
        col: targetCell.col + Math.max((payload.cols ?? 1) - 1, 0),
        row: targetCell.row + Math.max((payload.rows ?? 1) - 1, 0)
      }
    });
    setActiveCell(targetCell);
    setSelection(nextRange);
    selectionAnchorRef.current = targetCell;
    if (!hasMergeOperations) {
      recordRangeEditHistory(mutations, [nextRange], targetCell);
    }
    return true;
  }, [
    intersectsPivot,
    activeCell,
    captureCellMutationState,
    getActiveWorksheet,
    maybeRecalculateWorkbook,
    readOnly,
    recordHistoryBeforeMutation,
    recordRangeEditHistory,
    refreshWorkbookState,
    selection,
    selectionRanges,
    workbook
  ]);
  const copySelectionToClipboard = React.useCallback(async () => {
    if (typeof navigator === "undefined" || !navigator.clipboard) {
      return false;
    }
    if (isWorkerBacked && activeSheet) {
      const bands = clipboardBands(selectionRanges);
      if (!bands) return false;
      const textPromise = (async () => {
        const lines = [];
        for (const band of bands.rows) {
          for (let startRow = band.start; startRow <= band.end; startRow += 128) {
            const count = Math.min(128, band.end - startRow + 1);
            const batch = await getRowsBatchAsync(activeSheet.workbookSheetIndex, startRow, count);
            if (!batch) throw new Error("Unable to read the selected cells.");
            const values = /* @__PURE__ */ new Map();
            for (const entry of batch) {
              for (const cell of entry.cells ?? []) {
                if (cell.isMergedSecondary) continue;
                const value = String(cell.value ?? "");
                const cached = cell.formula ? activeSheet.cachedFormulaValues[cellAddressToA1({ row: entry.index, col: cell.col })] : void 0;
                values.set(`${entry.index}:${cell.col}`, decodeHtmlEntities(cached !== void 0 && value.startsWith("#") ? cached : value));
              }
            }
            for (let row2 = startRow; row2 < startRow + count; row2++) {
              const cells = [];
              for (const { index: col } of bandIndices(bands.cols)) cells.push(values.get(`${row2}:${col}`) ?? "");
              lines.push(cells.join("	"));
            }
          }
        }
        return lines.join("\n");
      })();
      if (typeof ClipboardItem === "function" && navigator.clipboard.write) {
        await navigator.clipboard.write([new ClipboardItem({
          "text/plain": textPromise.then((text) => new Blob([text], { type: "text/plain" }))
        })]);
      } else {
        await navigator.clipboard.writeText(await textPromise);
      }
      return true;
    }
    const clipboardData = getClipboardData();
    if (!clipboardData) return false;
    if (typeof ClipboardItem === "function" && navigator.clipboard.write) {
      const customType = `web ${INTERNAL_CLIPBOARD_MIME}`;
      try {
        await navigator.clipboard.write([new ClipboardItem({
          [customType]: new Blob([clipboardData.structured], { type: INTERNAL_CLIPBOARD_MIME }),
          "text/html": new Blob([clipboardData.html], { type: "text/html" }),
          "text/plain": new Blob([clipboardData.text], { type: "text/plain" })
        })]);
        return true;
      } catch (error2) {
        if (!(error2 instanceof TypeError) && (!(error2 instanceof DOMException) || error2.name !== "NotAllowedError" && error2.name !== "NotSupportedError")) {
          throw error2;
        }
        await navigator.clipboard.write([new ClipboardItem({
          "text/html": new Blob([clipboardData.html], { type: "text/html" }),
          "text/plain": new Blob([clipboardData.text], { type: "text/plain" })
        })]);
        return true;
      }
    }
    await navigator.clipboard.writeText(clipboardData.text);
    return true;
  }, [activeSheet, getClipboardData, getRowsBatchAsync, isWorkerBacked, selectionRanges]);
  const pasteFromClipboard = React.useCallback(async (clipboardData) => {
    if (readOnly) return false;
    const state = drawingMutationState.current;
    const generation = loadGenerationRef.current;
    const data = await readBrowserClipboard(clipboardData);
    const latest = drawingMutationState.current;
    if (generation !== loadGenerationRef.current || latest.workbook !== state.workbook || latest.revision !== state.revision || latest.readOnly || latest.activeSheetIndex !== state.activeSheetIndex || latest.activeCell?.row !== state.activeCell?.row || latest.activeCell?.col !== state.activeCell?.col) return false;
    if (data.drawing) return pasteDrawing(data.drawing);
    if (data.structured && pasteStructuredClipboardData(data.structured)) return true;
    return Boolean(data.text) && pasteText(data.text);
  }, [pasteDrawing, pasteStructuredClipboardData, pasteText, readOnly]);
  const undo = React.useCallback(() => {
    if (readOnly || !workbook || undoStackRef.current.length === 0) {
      return;
    }
    const entry = undoStackRef.current.pop();
    if (!entry) {
      return;
    }
    if (entry.kind === "cell-edit") {
      pushHistoryEntry(redoStackRef.current, entry);
      setHistoryRevision((current) => current + 1);
      applyCellEditHistoryEntry(entry, "undo");
      return;
    }
    if (entry.kind === "range-edit") {
      pushHistoryEntry(redoStackRef.current, entry);
      setHistoryRevision((current) => current + 1);
      applyRangeEditHistoryEntry(entry, "undo");
      return;
    }
    const currentSnapshot = createHistoryEntry();
    if (currentSnapshot) {
      pushHistoryEntry(redoStackRef.current, currentSnapshot);
    }
    setHistoryRevision((current) => current + 1);
    void restoreHistoryEntry(entry);
  }, [applyCellEditHistoryEntry, applyRangeEditHistoryEntry, createHistoryEntry, readOnly, restoreHistoryEntry, workbook]);
  const redo = React.useCallback(() => {
    if (readOnly || !workbook || redoStackRef.current.length === 0) {
      return;
    }
    const entry = redoStackRef.current.pop();
    if (!entry) {
      return;
    }
    if (entry.kind === "cell-edit") {
      pushHistoryEntry(undoStackRef.current, entry);
      setHistoryRevision((current) => current + 1);
      applyCellEditHistoryEntry(entry, "redo");
      return;
    }
    if (entry.kind === "range-edit") {
      pushHistoryEntry(undoStackRef.current, entry);
      setHistoryRevision((current) => current + 1);
      applyRangeEditHistoryEntry(entry, "redo");
      return;
    }
    const currentSnapshot = createHistoryEntry();
    if (currentSnapshot) {
      pushHistoryEntry(undoStackRef.current, currentSnapshot);
    }
    setHistoryRevision((current) => current + 1);
    void restoreHistoryEntry(entry);
  }, [applyCellEditHistoryEntry, applyRangeEditHistoryEntry, createHistoryEntry, readOnly, restoreHistoryEntry, workbook]);
  return React.useMemo(
    () => ({
      activeCell,
      activeCellAddress,
      activeSheet,
      activeSheetIndex,
      activeTab,
      activeTabIndex,
      addFormControl,
      addSheet,
      canRedo,
      canDownload: Boolean(file ?? src),
      canExport: Boolean(workbook),
      canLoadDeferred,
      canResize,
      canUndo,
      canZoomIn,
      canZoomOut,
      charts,
      chartsheets,
      clearSelectedChart,
      clearSelectedChartElement,
      clearSelectedCells,
      clearSelectedImage,
      clearSelection,
      clearHighlightedRanges,
      highlightRanges,
      highlightedRanges,
      continueDeferredLoad,
      copySelectionToClipboard,
      defaultZoomScale,
      deferredLoadFileSize,
      defineNamedRange,
      displayFileName,
      locale,
      messages,
      download,
      arrangeDrawing,
      pasteDrawingFromClipboard,
      changeChartType,
      exportCsv,
      exportXlsx,
      getXlsxBytes,
      renderChartAsync,
      error,
      fillSelection,
      formControls,
      getChartById,
      getChartSeriesFormula,
      getChartsheetById,
      getImageById,
      getSheetCharts,
      getSheetFormControls,
      getSheetImages,
      getSheetShapes,
      pivotTables,
      pivotFieldListVisible,
      setPivotFieldListVisible,
      getPivotSourceFields,
      getPivotTableAtCell,
      upsertPivotTable,
      refreshPivotTable,
      refreshAllPivotTables,
      removePivotTable,
      pivotDrillDown,
      showPivotDetails,
      createPivotChart,
      togglePivotGroup,
      file,
      getClipboardData,
      getCellDisplayValue: getCellDisplayValue2,
      getCellFormula,
      getFormControlItems,
      getCellSnapshotAsync: isWorkerBacked ? getCellSnapshotAsync : void 0,
      getActiveWorksheet,
      getRowsBatchAsync: isWorkerBacked ? getRowsBatchAsync : void 0,
      getAutofitCellsAsync: isWorkerBacked ? getAutofitCellsAsync : void 0,
      images,
      isLoadDeferred,
      isLoading,
      isChartsLoading,
      isWorkerBacked,
      mergeSelection,
      maxZoomScale: MAX_ZOOM_SCALE,
      minZoomScale: MIN_ZOOM_SCALE,
      moveChartBy,
      moveImageBy,
      pasteFromClipboard,
      pasteStructuredClipboardData,
      pasteText,
      removeActiveSheet,
      removeFormControl,
      readOnly,
      recalculate,
      redo,
      resetZoom,
      revision,
      resizeChartBy,
      resizeImageBy,
      frozenPanes: activeSheet?.freezePanes ?? null,
      canChangeFreezePanes,
      canChangeVisibility,
      canFreezePanes,
      hideRows,
      unhideRows,
      hideColumns,
      unhideColumns,
      freezePanes,
      unfreezePanes,
      resizeColumn,
      resizeRow,
      setCellFormula,
      setCellStyle,
      setCellStyles,
      setCellValue,
      setRangeStyle,
      setSelectedFormula,
      setZoomScale,
      setChartRect,
      setChartSeriesFormula,
      setImageRect,
      selectedChart,
      selectedChartElement,
      selectedChartFormula,
      selectedChartId,
      selectedCellFormula,
      selectedFormula,
      selectedFormulaTarget,
      selectedImage,
      selectedImageId,
      selectedRangeAddress,
      selectedValue,
      selectCell,
      selectChart,
      selectChartElement,
      selectImage,
      selectRange,
      selectRanges,
      selectionRanges,
      selection,
      setActiveSheetIndex,
      setActiveTabIndex,
      setSelectedCellFormula,
      setSelectedCellStyle,
      setSelectedCellValue,
      sheets,
      shapes,
      src,
      sortState,
      sortTable,
      tabs,
      tables,
      undo,
      unmergeSelection,
      updateChart,
      updateFormControl,
      workbook,
      zoomIn,
      zoomOut,
      zoomScale
    }),
    [
      activeCell,
      activeCellAddress,
      activeSheet,
      activeSheetIndex,
      activeTab,
      activeTabIndex,
      addFormControl,
      addSheet,
      canLoadDeferred,
      canRedo,
      canResize,
      canUndo,
      canZoomIn,
      canZoomOut,
      charts,
      chartsheets,
      clearSelectedChart,
      clearSelectedChartElement,
      clearSelectedCells,
      clearSelectedImage,
      continueDeferredLoad,
      clearHighlightedRanges,
      highlightRanges,
      highlightedRanges,
      copySelectionToClipboard,
      defaultZoomScale,
      deferredLoadFileSize,
      defineNamedRange,
      displayFileName,
      locale,
      messages,
      download,
      arrangeDrawing,
      pasteDrawingFromClipboard,
      changeChartType,
      error,
      exportCsv,
      exportXlsx,
      getXlsxBytes,
      renderChartAsync,
      file,
      fillSelection,
      formControls,
      getChartById,
      getChartSeriesFormula,
      getChartsheetById,
      getImageById,
      getSheetCharts,
      getSheetFormControls,
      getSheetImages,
      getSheetShapes,
      pivotTables,
      pivotFieldListVisible,
      setPivotFieldListVisible,
      getPivotSourceFields,
      getPivotTableAtCell,
      upsertPivotTable,
      refreshPivotTable,
      refreshAllPivotTables,
      removePivotTable,
      pivotDrillDown,
      showPivotDetails,
      createPivotChart,
      togglePivotGroup,
      getClipboardData,
      getCellDisplayValue2,
      getCellFormula,
      getFormControlItems,
      getCellSnapshotAsync,
      getActiveWorksheet,
      historyRevision,
      formControls,
      images,
      isLoadDeferred,
      isLoading,
      isChartsLoading,
      isWorkerBacked,
      mergeSelection,
      resetZoom,
      moveChartBy,
      moveImageBy,
      pasteFromClipboard,
      pasteStructuredClipboardData,
      pasteText,
      removeActiveSheet,
      removeFormControl,
      readOnly,
      recalculate,
      redo,
      revision,
      resizeChartBy,
      resizeImageBy,
      canChangeFreezePanes,
      canChangeVisibility,
      canFreezePanes,
      hideRows,
      unhideRows,
      hideColumns,
      unhideColumns,
      freezePanes,
      unfreezePanes,
      resizeColumn,
      resizeRow,
      setCellFormula,
      setCellStyle,
      setCellStyles,
      setCellValue,
      setRangeStyle,
      setSelectedFormula,
      setZoomScale,
      setChartRect,
      setChartSeriesFormula,
      setImageRect,
      selectedChart,
      selectedChartElement,
      selectedChartFormula,
      selectedChartId,
      selectedCellFormula,
      selectedFormula,
      selectedFormulaTarget,
      selectedImage,
      selectedImageId,
      selectedRangeAddress,
      selectedValue,
      selectCell,
      selectChart,
      selectChartElement,
      selectImage,
      selectRange,
      selectRanges,
      selectionRanges,
      selection,
      setActiveSheetIndex,
      setActiveTabIndex,
      setSelectedCellFormula,
      setSelectedCellStyle,
      setSelectedCellValue,
      sheets,
      shapes,
      sortState,
      sortTable,
      src,
      getAutofitCellsAsync,
      getRowsBatchAsync,
      tabs,
      tables,
      undo,
      unmergeSelection,
      updateChart,
      updateFormControl,
      workbook,
      zoomIn,
      zoomOut,
      zoomScale
    ]
  );
}

// src/index.ts
import { initWasm, parseXlsxRange as parseXlsxRange2, setWasmSource, XlsxFileSizeLimitExceededError as XlsxFileSizeLimitExceededError3 } from "@extend-ai/react-xlsx/vanilla";

// src/react-viewer.tsx
import * as React16 from "react";
import { createPortal as createPortal7 } from "react-dom";
import { __createContentNode, __createContentRoot, __createControlledViewer } from "@extend-ai/react-xlsx/internal";

// src/XlsxViewer.tsx
import * as React15 from "react";
import { createPortal as createPortal6 } from "react-dom";

// src/cell-editor.tsx
import * as React2 from "react";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
function CellEditor({
  value,
  wrapText,
  references,
  inputRef,
  editorRef,
  onFocusOverlay,
  canvasText = false,
  canvasOffset,
  paintCanvasText,
  style,
  onChange,
  onBlur,
  onCommit,
  onCancel,
  onNavigate
}) {
  const rootRef = React2.useRef(null);
  const messages = useXlsxMessages();
  const mirrorRef = React2.useRef(null);
  const textRef = React2.useRef(null);
  const baselineRef = React2.useRef(null);
  const plainTextRef = React2.useRef(null);
  const canvasRef = React2.useRef(null);
  const textareaRef = React2.useRef(null);
  const baselineOffsetRef = React2.useRef(0);
  const measuringContextRef = React2.useRef(null);
  const [bounds, setBounds] = React2.useState({ width: 0, height: 0, cellWidth: 0 });
  React2.useLayoutEffect(() => {
    const root = rootRef.current;
    const anchor = root?.parentElement;
    const viewport = root?.closest('[role="grid"]');
    if (!root || !anchor || !viewport) {
      return;
    }
    const updateBounds = () => {
      const anchorRect = anchor.getBoundingClientRect();
      const viewportRect = viewport.getBoundingClientRect();
      const anchorWidth = parseFloat(getComputedStyle(anchor).width) || anchor.offsetWidth;
      const scale = anchorWidth ? anchorRect.width / anchorWidth : 1;
      const viewportScale = viewport.offsetWidth ? viewportRect.width / viewport.offsetWidth : 1;
      const viewportRight = viewportRect.right - (viewport.offsetWidth - viewport.clientWidth - viewport.clientLeft) * viewportScale;
      const width = Math.max(anchor.clientWidth, (viewportRight - anchorRect.left) / (scale || 1));
      const height = anchorRect.height / (scale || 1);
      const cellWidth = anchorRect.width / (scale || 1);
      setBounds((previous) => previous.width === width && previous.height === height && previous.cellWidth === cellWidth ? previous : { width, height, cellWidth });
    };
    updateBounds();
    const observer = new ResizeObserver(updateBounds);
    observer.observe(viewport);
    observer.observe(anchor);
    viewport.addEventListener("scroll", updateBounds);
    return () => {
      observer.disconnect();
      viewport.removeEventListener("scroll", updateBounds);
    };
  }, []);
  React2.useLayoutEffect(() => {
    const text = textRef.current;
    const textarea = textareaRef.current;
    const root = rootRef.current;
    const baseline = baselineRef.current;
    const mirror = mirrorRef.current;
    if (!text || !textarea || !root || !baseline || !mirror) return;
    const computedStyle = getComputedStyle(text);
    const lineHeight = parseFloat(computedStyle.lineHeight) || parseFloat(computedStyle.fontSize) * 1.2;
    const rootRect = root.getBoundingClientRect();
    const scale = rootRect.width / parseFloat(getComputedStyle(root).width) || 1;
    const editorTextTop = Math.max(0, (text.getBoundingClientRect().top - rootRect.top) / scale - baselineOffsetRef.current);
    textarea.style.paddingTop = `${editorTextTop}px`;
    let baselineOffset = 0;
    if (canvasText) {
      const context = measuringContextRef.current ??= document.createElement("canvas").getContext("2d");
      if (context) {
        context.font = computedStyle.font;
        context.textBaseline = "alphabetic";
        const alphabetic = context.measureText("M");
        context.textBaseline = "middle";
        const middle = context.measureText("M");
        const browserBaseline = (baseline.getBoundingClientRect().top - rootRect.top) / scale - baselineOffsetRef.current;
        baselineOffset = editorTextTop + lineHeight / 2 + alphabetic.actualBoundingBoxAscent - middle.actualBoundingBoxAscent - browserBaseline;
      }
    }
    baselineOffsetRef.current = baselineOffset;
    root.style.setProperty("--xlsx-editor-baseline-offset", `${baselineOffset}px`);
    const canvas = canvasRef.current;
    if (canvas && paintCanvasText) {
      const dpr = window.devicePixelRatio || 1;
      const offsetX = (canvasOffset?.left ?? 0) * dpr % 1 / dpr;
      const offsetY = (canvasOffset?.top ?? 0) * dpr % 1 / dpr;
      const width = rootRect.width / scale;
      const height = rootRect.height / scale;
      canvas.width = Math.ceil((width + offsetX) * dpr);
      canvas.height = Math.ceil((height + offsetY) * dpr);
      canvas.style.width = `${canvas.width / dpr}px`;
      canvas.style.height = `${canvas.height / dpr}px`;
      canvas.style.left = `${-offsetX}px`;
      canvas.style.top = `${-offsetY}px`;
      const context = canvas.getContext("2d");
      if (context) {
        const node = plainTextRef.current?.firstChild;
        const lines = [];
        if (node) {
          const range = document.createRange();
          const length = node.textContent?.length ?? 0;
          let start = 0;
          while (start < length) {
            range.setStart(node, start);
            range.setEnd(node, start + 1);
            const top = range.getBoundingClientRect().top;
            let low = start + 1;
            let high = length;
            while (low < high) {
              const middle = Math.floor((low + high) / 2);
              range.setStart(node, middle);
              range.setEnd(node, middle + 1);
              if (Math.abs(range.getBoundingClientRect().top - top) < 1) low = middle + 1;
              else high = middle;
            }
            lines.push({ start, text: value.slice(start, low).replace(/\r?\n$/, "") });
            start = low;
          }
        }
        context.scale(dpr, dpr);
        context.translate(offsetX, offsetY);
        paintCanvasText(context, width, height, lines, editorTextTop);
      }
    }
  });
  const parts = [];
  let offset = 0;
  for (const reference of references) {
    parts.push(value.slice(offset, reference.start));
    parts.push(/* @__PURE__ */ jsx("span", { style: { color: reference.color }, children: value.slice(reference.start, reference.end) }, reference.start));
    offset = reference.end;
  }
  parts.push(value.slice(offset));
  return /* @__PURE__ */ jsxs(
    "div",
    {
      ref: (element) => {
        rootRef.current = element;
        if (typeof editorRef === "function") editorRef(element);
        else if (editorRef) editorRef.current = element;
      },
      "data-xlsx-cell-editor": "",
      onPointerDown: (event) => event.stopPropagation(),
      onClick: (event) => event.stopPropagation(),
      onDoubleClick: (event) => event.stopPropagation(),
      style: {
        ...style,
        boxSizing: "border-box",
        position: "absolute",
        top: 0,
        left: 0,
        minHeight: "100%",
        minWidth: "100%",
        width: wrapText ? "100%" : "max-content",
        maxWidth: wrapText ? "100%" : bounds.width || "100%",
        textAlign: style.textAlign ?? "left",
        whiteSpace: "pre-wrap",
        wordBreak: "normal",
        overflowWrap: "anywhere",
        padding: 0,
        lineHeight: style.lineHeight ?? "inherit",
        overflow: "hidden"
      },
      children: [
        /* @__PURE__ */ jsx(
          "div",
          {
            ref: mirrorRef,
            "aria-hidden": "true",
            "data-xlsx-formula-text": "",
            style: {
              boxSizing: "border-box",
              padding: style.padding,
              minHeight: bounds.height,
              display: "flex",
              flexDirection: "column",
              justifyContent: style.verticalAlign === "top" ? "flex-start" : style.verticalAlign === "middle" ? "center" : "flex-end",
              overflow: "hidden",
              visibility: paintCanvasText ? "hidden" : void 0,
              pointerEvents: "none"
            },
            children: /* @__PURE__ */ jsxs("span", { ref: textRef, style: { display: "block", transform: "translateY(var(--xlsx-editor-baseline-offset, 0px))" }, children: [
              /* @__PURE__ */ jsx("span", { ref: baselineRef, style: { display: "inline-block", width: 0, height: 0, verticalAlign: "baseline" } }),
              paintCanvasText ? /* @__PURE__ */ jsx("span", { ref: plainTextRef, children: !value || /[\r\n]$/.test(value) ? value + "\u200B" : value }) : /* @__PURE__ */ jsxs(Fragment, { children: [
                parts,
                "\u200B"
              ] })
            ] })
          }
        ),
        paintCanvasText ? /* @__PURE__ */ jsx("canvas", { ref: canvasRef, "data-xlsx-formula-text": "", "aria-hidden": "true", style: { position: "absolute", pointerEvents: "none" } }) : null,
        /* @__PURE__ */ jsx(
          "textarea",
          {
            ref: (element) => {
              textareaRef.current = element;
              if (typeof inputRef === "function") inputRef(element);
              else if (inputRef) inputRef.current = element;
            },
            "aria-label": messages.editCell,
            "aria-keyshortcuts": onFocusOverlay ? "Alt+ArrowDown" : void 0,
            autoFocus: true,
            autoComplete: "off",
            spellCheck: false,
            rows: 1,
            value,
            onBlur,
            onChange: (event) => onChange(event.target.value),
            onScroll: (event) => {
              if (mirrorRef.current) mirrorRef.current.scrollTop = event.currentTarget.scrollTop;
            },
            onKeyDown: (event) => {
              event.stopPropagation();
              if (event.nativeEvent.isComposing) return;
              if (event.key === "ArrowDown" && event.altKey && onFocusOverlay?.()) {
                event.preventDefault();
              } else if (event.key === "Enter" && !event.altKey) {
                event.preventDefault();
                onCommit();
              } else if (event.key === "Escape") {
                event.preventDefault();
                onCancel();
              } else if (event.key === "Tab") {
                event.preventDefault();
                onNavigate(event.shiftKey ? "ArrowLeft" : "ArrowRight", event.currentTarget.value);
              } else if ((event.key === "ArrowDown" || event.key === "ArrowUp") && event.currentTarget.clientHeight < parseFloat(getComputedStyle(event.currentTarget).lineHeight) * 2) {
                event.preventDefault();
                onNavigate(event.key, event.currentTarget.value);
              }
            },
            style: {
              position: "absolute",
              inset: 0,
              background: "transparent",
              border: 0,
              boxSizing: "border-box",
              color: "transparent",
              caretColor: style.color ?? "currentColor",
              font: "inherit",
              lineHeight: "inherit",
              letterSpacing: "inherit",
              textAlign: "inherit",
              height: "100%",
              width: "100%",
              minWidth: 0,
              whiteSpace: "pre-wrap",
              wordBreak: "normal",
              overflowWrap: "anywhere",
              resize: "none",
              overflow: "hidden",
              padding: style.padding,
              margin: 0,
              outline: "none",
              transform: "translateY(var(--xlsx-editor-baseline-offset, 0px))"
            }
          }
        )
      ]
    }
  );
}

// src/cell-editor-overlay.tsx
import * as React3 from "react";
import { createPortal } from "react-dom";
import { jsx as jsx2 } from "react/jsx-runtime";

// src/selection-popover.tsx
import * as React4 from "react";
import { createPortal as createPortal2 } from "react-dom";
import { jsx as jsx3 } from "react/jsx-runtime";

// src/cell-editor-session.ts
import * as React5 from "react";

// src/cell-alignment.ts
function getCellGeneralAlignment(worksheet, row2, col) {
  const value = worksheet.getCalculatedValueAt(row2, col);
  try {
    if (value.is_number) return "right";
    if (value.is_boolean || value.is_error) return "center";
    return "left";
  } finally {
    value.free();
  }
}

// src/header-size-dialog.tsx
import * as React6 from "react";
import { createPortal as createPortal3 } from "react-dom";
import { jsx as jsx4, jsxs as jsxs2 } from "react/jsx-runtime";

// src/context-menu.tsx
import * as React8 from "react";
import { createPortal as createPortal4 } from "react-dom";

// src/viewer-palette.ts
var LIGHT_PALETTE = {
  border: "#e4e4e7",
  buttonSurface: "#ffffff",
  buttonText: "#18181b",
  canvas: "#fafafa",
  danger: "#dc2626",
  headerSurface: "#f4f4f5",
  headerText: "#71717a",
  mutedSurface: "#f5f5f5",
  mutedText: "#71717a",
  rowHeaderSurface: "#f4f4f5",
  shadow: "0 1px 2px rgba(0, 0, 0, 0.04)",
  sheetActiveSurface: "#ffffff",
  sheetActiveText: "#18181b",
  sheetInactiveSurface: "#e4e4e7",
  sheetInactiveText: "#52525b",
  strongBorder: "#d4d4d8",
  subtleSurface: "#fafafa",
  surface: "#ffffff",
  text: "#18181b",
  toolbarSurface: "#f5f5f5"
};
var DARK_PALETTE = {
  border: "rgba(255, 255, 255, 0.10)",
  buttonSurface: "rgba(255, 255, 255, 0.06)",
  buttonText: "#f4f4f5",
  canvas: "#09090b",
  danger: "#f87171",
  headerSurface: "#18181b",
  headerText: "#a1a1aa",
  mutedSurface: "#111113",
  mutedText: "#a1a1aa",
  rowHeaderSurface: "#18181b",
  shadow: "0 1px 2px rgba(0, 0, 0, 0.28)",
  sheetActiveSurface: "#27272a",
  sheetActiveText: "#fafafa",
  sheetInactiveSurface: "#18181b",
  sheetInactiveText: "#a1a1aa",
  strongBorder: "rgba(255, 255, 255, 0.16)",
  subtleSurface: "#101012",
  surface: "#111113",
  text: "#f4f4f5",
  toolbarSurface: "#101012"
};
function isDarkViewerPalette(palette) {
  return palette.surface === DARK_PALETTE.surface;
}
function resolveViewerPalette(isDark = false, headerBackgroundColor, headerTextColor) {
  const basePalette = isDark ? DARK_PALETTE : LIGHT_PALETTE;
  if (headerBackgroundColor === void 0 && headerTextColor === void 0) {
    return basePalette;
  }
  return {
    ...basePalette,
    headerSurface: headerBackgroundColor ?? basePalette.headerSurface,
    headerText: headerTextColor ?? basePalette.headerText,
    rowHeaderSurface: headerBackgroundColor ?? basePalette.rowHeaderSurface
  };
}

// src/context-menu-items.tsx
import * as React7 from "react";
import { Fragment as Fragment3, jsx as jsx5, jsxs as jsxs3 } from "react/jsx-runtime";

// src/context-menu.tsx
import { jsx as jsx6, jsxs as jsxs4 } from "react/jsx-runtime";

// src/pivot-controls.tsx
import * as React9 from "react";
import { Fragment as Fragment5, jsx as jsx7, jsxs as jsxs5 } from "react/jsx-runtime";

// src/pivot-header-controls.tsx
import * as React10 from "react";
import { createPortal as createPortal5 } from "react-dom";
import { Fragment as Fragment7, jsx as jsx8, jsxs as jsxs6 } from "react/jsx-runtime";

// src/pivot-editor.ts
import * as React11 from "react";
function address(row2, col) {
  let letters = "";
  for (let n = col + 1; n > 0; n = Math.floor((n - 1) / 26)) letters = String.fromCharCode(65 + (n - 1) % 26) + letters;
  return `${letters}${row2 + 1}`;
}
function newAxis(field) {
  return { field, sort: "ascending", subtotals: true, collapsed: [] };
}
function newValue(field) {
  const aggregation = field.dataType === "number" ? "sum" : "count";
  return { field: field.index, name: `${aggregation === "sum" ? "Sum" : "Count"} of ${field.name}`, aggregation, showAs: "normal" };
}
function copyPivot(pivot) {
  return structuredClone(pivot);
}
function usePivotTableEditor(viewer, options2 = {}) {
  const open = viewer.pivotFieldListVisible;
  const setOpen = viewer.setPivotFieldListVisible;
  const [draft, setDraft] = React11.useState(null);
  const [dirty, setDirty] = React11.useState(false);
  const [error, setError] = React11.useState(null);
  const [status, setStatus] = React11.useState(null);
  const [details, setDetails] = React11.useState(null);
  const [detailContext, setDetailContext] = React11.useState(null);
  const [loadedSource, setLoadedSource] = React11.useState("");
  const [savedDefinition, setSavedDefinition] = React11.useState("");
  const [pendingFocus, setPendingFocus] = React11.useState(null);
  const sourceNeedsLoad = Boolean(draft && JSON.stringify(draft.source) !== loadedSource);
  const stale = Boolean(dirty && draft?.id && savedDefinition !== JSON.stringify(viewer.pivotTables.find((pivot) => pivot.id === draft.id) ?? null));
  const run = React11.useCallback((action) => {
    setError(null);
    setStatus(null);
    try {
      action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setOpen(true);
    }
  }, []);
  React11.useEffect(() => {
    if (options2.enabled === false) return;
    setDraft(null);
    setDirty(false);
    setError(null);
    setStatus(null);
    setDetails(null);
    setDetailContext(null);
    setLoadedSource("");
    setSavedDefinition("");
    setPendingFocus(null);
    if (options2.initialOpen !== void 0) setOpen(options2.initialOpen);
  }, [viewer.src, viewer.file]);
  React11.useEffect(() => {
    if (options2.enabled === false || dirty || !draft?.id) return;
    const current = viewer.pivotTables.find((pivot) => pivot.id === draft.id);
    setDraft(current ? copyPivot(current) : null);
    if (current) {
      setLoadedSource(JSON.stringify(current.source));
      setSavedDefinition(JSON.stringify(current));
    }
  }, [viewer.pivotTables]);
  React11.useEffect(() => {
    if (options2.enabled === false || options2.autoSelect === false || dirty || pendingFocus || !viewer.activeCell || !viewer.activeSheet) return;
    const current = viewer.getPivotTableAtCell(viewer.activeCell, viewer.activeSheet.name);
    if (!current || current.id === draft?.id) return;
    setDraft(copyPivot(current));
    setLoadedSource(JSON.stringify(current.source));
    setSavedDefinition(JSON.stringify(current));
    setError(null);
    setStatus(null);
    setDetails(null);
  }, [viewer.activeCell?.row, viewer.activeCell?.col, viewer.activeSheet?.name, viewer.pivotTables, options2.autoSelect, options2.enabled]);
  React11.useEffect(() => {
    if (!pendingFocus || viewer.activeSheet?.name.toLowerCase() !== pendingFocus.sheet.toLowerCase()) return;
    viewer.selectCell({ row: pendingFocus.row, col: pendingFocus.col });
    setPendingFocus(null);
  }, [pendingFocus, viewer.activeSheet?.name, viewer.selectCell]);
  const focus = (pivot) => {
    const sheetIndex = viewer.sheets.findIndex((sheet) => sheet.name.toLowerCase() === pivot.target.sheet.toLowerCase());
    if (sheetIndex >= 0) viewer.setActiveSheetIndex(sheetIndex);
    const parsed = parseXlsxRange(pivot.outputRange || pivot.target.cell);
    if (parsed) setPendingFocus({ sheet: pivot.target.sheet, ...parsed.range.start });
  };
  const select = (id) => run(() => {
    if (dirty) throw new Error("Apply or discard your changes before switching PivotTables.");
    const pivot = viewer.pivotTables.find((item) => item.id === id);
    if (!pivot) return;
    setDraft(copyPivot(pivot));
    setLoadedSource(JSON.stringify(pivot.source));
    setSavedDefinition(JSON.stringify(pivot));
    setDirty(false);
    setDetails(null);
    setOpen(true);
    focus(pivot);
  });
  const edit = (change) => {
    if (options2.enabled === false || viewer.readOnly || draft?.unsupportedFeatures.length) return;
    setDraft((current) => current ? change(current) : current);
    setDirty(true);
    setStatus(null);
    setError(null);
    setDetails(null);
  };
  const create = () => run(() => {
    if (dirty) throw new Error("Apply or discard your current changes before creating another PivotTable.");
    if (!viewer.activeSheet || viewer.readOnly) return;
    const sheet = viewer.activeSheet;
    const selected = viewer.selection;
    const sourceRange = selected && (selected.start.row !== selected.end.row || selected.start.col !== selected.end.col) ? `${address(selected.start.row, selected.start.col)}:${address(selected.end.row, selected.end.col)}` : `${address(sheet.minUsedRow, sheet.minUsedCol)}:${address(sheet.maxUsedRow, sheet.maxUsedCol)}`;
    let index = 1;
    while (viewer.pivotTables.some((pivot) => pivot.name === `PivotTable${index}`)) index++;
    const next = {
      id: "",
      name: `PivotTable${index}`,
      source: { sheet: sheet.name, range: sourceRange },
      target: { sheet: sheet.name, cell: address(sheet.minUsedRow, Math.min(sheet.maxUsedCol + 3, 16383)) },
      rows: [],
      columns: [],
      values: [],
      filters: [],
      reportFilters: [],
      calculatedItems: [],
      layout: "compact",
      repeatLabels: false,
      rowGrandTotals: true,
      columnGrandTotals: true,
      subtotalsPosition: "bottom",
      styleName: "PivotStyleLight16",
      fields: [],
      unsupportedFeatures: [],
      refreshOnLoad: false,
      valuesOnRows: false
    };
    setDraft(next);
    setDirty(true);
    setOpen(true);
    setDetails(null);
    setSavedDefinition("");
    const fields = viewer.getPivotSourceFields(next.source);
    next.fields = fields;
    setLoadedSource(JSON.stringify(next.source));
    setDraft({ ...next });
  });
  const readFields = () => run(() => {
    if (!draft) return;
    const fields = viewer.getPivotSourceFields(draft.source);
    setLoadedSource(JSON.stringify(draft.source));
    const sameSchema = fields.length === draft.fields.length && fields.every((field, index) => field.name === draft.fields[index]?.name);
    edit((pivot) => ({ ...pivot, fields, ...sameSchema ? {} : { rows: [], columns: [], values: [], filters: [], reportFilters: [], calculatedItems: [] } }));
    setStatus(sameSchema ? "Source fields updated." : "Fields loaded. Choose the fields to summarize.");
  });
  const apply = () => run(() => {
    if (!draft) return;
    if (stale) throw new Error("This PivotTable changed while you were editing. Discard your draft to load its current definition.");
    if (sourceNeedsLoad) throw new Error("Load the source fields on the Source tab before applying these changes.");
    const result = viewer.upsertPivotTable(draft);
    setDraft(copyPivot(result));
    setLoadedSource(JSON.stringify(result.source));
    setSavedDefinition(JSON.stringify(result));
    setDirty(false);
    setStatus("PivotTable updated.");
    setDetails(null);
    focus(result);
  });
  const refresh = (all = false) => run(() => {
    if (dirty) throw new Error("Apply or discard your field changes before refreshing.");
    if (all) {
      const refreshed = viewer.refreshAllPivotTables();
      setStatus(`${refreshed.length} PivotTable${refreshed.length === 1 ? "" : "s"} refreshed.`);
    } else if (draft?.id) {
      const refreshed = viewer.refreshPivotTable(draft.id);
      setDraft(copyPivot(refreshed));
      setLoadedSource(JSON.stringify(refreshed.source));
      setSavedDefinition(JSON.stringify(refreshed));
      setDirty(false);
      setStatus("PivotTable refreshed from its source.");
    }
    setDetails(null);
  });
  const remove = () => run(() => {
    if (dirty) throw new Error("Apply or discard your changes before removing the report.");
    if (!draft?.id) return;
    if (viewer.removePivotTable(draft.id)) {
      setDraft(null);
      setDirty(false);
      setStatus("PivotTable removed. Undo restores it.");
      setDetails(null);
    }
  });
  const reset = () => run(() => {
    const saved = viewer.pivotTables.find((pivot) => pivot.id === draft?.id);
    setDraft(saved ? copyPivot(saved) : null);
    setLoadedSource(saved ? JSON.stringify(saved.source) : "");
    setSavedDefinition(saved ? JSON.stringify(saved) : "");
    setDirty(false);
    setDetails(null);
  });
  const showDetails = () => run(() => {
    if (!draft?.id || !viewer.activeCell) return;
    if (viewer.activeSheet?.name.toLowerCase() !== draft.target.sheet.toLowerCase()) throw new Error("Select a value cell inside this PivotTable first.");
    setDetails(viewer.pivotDrillDown(draft.id, viewer.activeCell.row, viewer.activeCell.col));
    setDetailContext({ id: draft.id, row: viewer.activeCell.row, col: viewer.activeCell.col });
    setOpen(true);
  });
  const uniqueValue = (pivot, field) => {
    const value = newValue(field);
    let name = value.name;
    for (let index = 2; pivot.values.some((item) => item.name.toLocaleLowerCase() === name.toLocaleLowerCase()); index++) name = `${value.name} ${index}`;
    return { ...value, name };
  };
  const replaceValues = (pivot, values) => {
    const mapIndex = (index) => values.indexOf(pivot.values[index]);
    const updateAxis = (axis) => {
      if (axis.sort !== "valueAscending" && axis.sort !== "valueDescending") return axis;
      const index = mapIndex(axis.sortMeasure ?? 0);
      return index < 0 ? { ...axis, sort: "ascending", sortMeasure: null } : { ...axis, sortMeasure: index };
    };
    return {
      ...pivot,
      values,
      rows: pivot.rows.map(updateAxis),
      columns: pivot.columns.map(updateAxis),
      filters: pivot.filters.flatMap((filter) => {
        if (filter.kind !== "value" && filter.kind !== "top10") return [filter];
        const measure = mapIndex(filter.measure);
        return measure < 0 ? [] : [{ ...filter, measure }];
      }),
      ...pivot.charts ? { charts: pivot.charts.map((chart) => chart.measure == null ? chart : { ...chart, measure: mapIndex(chart.measure) < 0 ? null : mapIndex(chart.measure) }) } : {}
    };
  };
  const addField = (area, field) => edit((pivot) => {
    const source = pivot.fields.find((item) => item.index === field);
    if (!source) return pivot;
    if (area === "values") return { ...pivot, values: [...pivot.values, uniqueValue(pivot, source)] };
    const next = { ...pivot, rows: pivot.rows.filter((item) => item.field !== field), columns: pivot.columns.filter((item) => item.field !== field), reportFilters: pivot.reportFilters.filter((item) => item !== field) };
    return area === "reportFilters" ? { ...next, reportFilters: [...next.reportFilters, field] } : { ...next, [area]: [...next[area], newAxis(field)] };
  });
  const removeField = (area, index) => edit((pivot) => area === "values" ? replaceValues(pivot, pivot.values.filter((_, position) => position !== index)) : { ...pivot, [area]: pivot[area].filter((_, position) => position !== index) });
  const moveField = (fromArea, fromIndex, toArea, toIndex) => {
    if (fromArea === "values" && toArea !== "values" && draft?.values[fromIndex]?.formula?.trim()) {
      run(() => {
        throw new Error("Calculated fields can only be placed in Values.");
      });
      return;
    }
    edit((pivot) => {
      const entry = pivot[fromArea][fromIndex];
      if (entry === void 0 || fromArea === "values" && toArea !== "values" && typeof entry === "object" && "formula" in entry && entry.formula?.trim()) return pivot;
      if (fromArea === toArea) {
        const entries2 = [...pivot[fromArea]];
        entries2.splice(fromIndex, 1);
        entries2.splice(Math.max(0, Math.min(toIndex ?? entries2.length, entries2.length)), 0, entry);
        return fromArea === "values" ? replaceValues(pivot, entries2) : { ...pivot, [fromArea]: entries2 };
      }
      const field = typeof entry === "number" ? entry : entry.field;
      const source = pivot.fields.find((item) => item.index === field);
      if (!source) return pivot;
      let next = fromArea === "values" ? replaceValues(pivot, pivot.values.filter((_, index) => index !== fromIndex)) : { ...pivot, [fromArea]: pivot[fromArea].filter((_, index) => index !== fromIndex) };
      if (toArea === "values") {
        const values = [...next.values];
        values.splice(Math.max(0, Math.min(toIndex ?? values.length, values.length)), 0, uniqueValue(next, source));
        return replaceValues(next, values);
      }
      next = { ...next, rows: next.rows.filter((item) => item.field !== field), columns: next.columns.filter((item) => item.field !== field), reportFilters: next.reportFilters.filter((item) => item !== field) };
      const entries = [...next[toArea]];
      const added = toArea === "reportFilters" ? field : fromArea === "rows" || fromArea === "columns" ? entry : newAxis(field);
      entries.splice(Math.max(0, Math.min(toIndex ?? entries.length, entries.length)), 0, added);
      return { ...next, [toArea]: entries };
    });
  };
  return { viewer, readOnly: viewer.readOnly || Boolean(draft?.unsupportedFeatures.length), open, setOpen, draft, dirty, edit, select, create, apply, reset, remove, refresh, readFields, addField, removeField, moveField, details, detailContext, showDetails, clearDetails: () => {
    setDetails(null);
    setDetailContext(null);
  }, sourceNeedsLoad, stale, error, status, run };
}

// src/pivot-field-list.tsx
import * as React12 from "react";
import { Fragment as Fragment8, jsx as jsx9, jsxs as jsxs7 } from "react/jsx-runtime";
var AREAS = ["reportFilters", "columns", "rows", "values"];
var AREA_NAMES = { reportFilters: "Filters", columns: "Columns", rows: "Rows", values: "Values" };
var AGGREGATIONS = [["sum", "Sum"], ["count", "Count"], ["average", "Average"], ["max", "Max"], ["min", "Min"], ["product", "Product"], ["countNums", "Count Numbers"], ["stdDev", "StdDev"], ["stdDevp", "StdDevp"], ["var", "Var"], ["varp", "Varp"]];
var SHOW_AS = [["normal", "No calculation"], ["percentOfGrandTotal", "% of grand total"], ["percentOfRowTotal", "% of row total"], ["percentOfColumnTotal", "% of column total"], ["percentOfParentRowTotal", "% of parent row total"], ["percentOfParentColumnTotal", "% of parent column total"], ["percent", "% of"], ["difference", "Difference from"], ["percentDifference", "% difference from"], ["runningTotal", "Running total in"], ["percentRunningTotal", "% running total in"], ["rankAscending", "Rank smallest to largest"], ["rankDescending", "Rank largest to smallest"], ["index", "Index"]];
var OPERATORS = [["equal", "Equals"], ["notEqual", "Does not equal"], ["contains", "Contains"], ["notContains", "Does not contain"], ["beginsWith", "Begins with"], ["notBeginsWith", "Does not begin with"], ["endsWith", "Ends with"], ["notEndsWith", "Does not end with"], ["greaterThan", "Greater than"], ["greaterThanOrEqual", "Greater than or equal to"], ["lessThan", "Less than"], ["lessThanOrEqual", "Less than or equal to"], ["between", "Between"], ["notBetween", "Not between"]];
var DATE_UNITS = ["years", "quarters", "months", "days", "hours", "minutes", "seconds"];
var CHART_TYPES = [["ColumnClustered", "Clustered column"], ["ColumnStacked", "Stacked column"], ["ColumnPercentStacked", "100% stacked column"], ["BarClustered", "Clustered bar"], ["BarStacked", "Stacked bar"], ["BarPercentStacked", "100% stacked bar"], ["Line", "Line"], ["LineStacked", "Stacked line"], ["Area", "Area"], ["AreaStacked", "Stacked area"], ["AreaPercentStacked", "100% stacked area"], ["Pie", "Pie"], ["Doughnut", "Doughnut"]];
var DRAG_TYPE = "application/x-react-xlsx-pivot-field";
var FORMULA_HELP = "Supported functions: SUM, PRODUCT, AVERAGE, MIN, MAX, ABS, ROUND, SQRT. Use +, -, *, /, ^, %, and parentheses.";
var stack = { display: "flex", flexDirection: "column", gap: 10, minWidth: 0 };
var row = { display: "flex", alignItems: "center", gap: 6, minWidth: 0 };
var hint = { color: "var(--xlsx-pivot-muted)", fontSize: 11, lineHeight: 1.5, margin: 0 };
var control = { boxSizing: "border-box", width: "100%", minWidth: 0, minHeight: 30, border: "1px solid var(--xlsx-pivot-border)", borderRadius: 3, background: "var(--xlsx-pivot-input)", color: "inherit", padding: "4px 7px", font: "inherit" };
function fieldName(pivot, index) {
  return pivot.fields.find((field) => field.index === index)?.name ?? `Field ${index + 1}`;
}
function fieldIndex(pivot, area, index) {
  return area === "reportFilters" ? pivot.reportFilters[index] : pivot[area][index]?.field;
}
function sourceFieldIndex(pivot, area, index) {
  return area === "values" && pivot.values[index]?.formula?.trim() ? void 0 : fieldIndex(pivot, area, index);
}
function groupingUnit(axis) {
  return axis?.grouping ? axis.grouping.kind === "date" ? axis.grouping.unit : axis.grouping.kind : null;
}
function Action({ children: children2, primary, style, ...props }) {
  return /* @__PURE__ */ jsx9("button", { type: "button", ...props, style: { ...control, width: "auto", cursor: props.disabled ? "default" : "pointer", opacity: props.disabled ? 0.55 : 1, ...primary ? { background: "var(--xlsx-pivot-accent)", borderColor: "var(--xlsx-pivot-accent)", color: "#fff" } : {}, ...style }, children: children2 });
}
function Text({ label, value, onChange, ...props }) {
  return /* @__PURE__ */ jsxs7("label", { style: { ...stack, gap: 4 }, children: [
    /* @__PURE__ */ jsx9("span", { children: label }),
    /* @__PURE__ */ jsx9("input", { ...props, style: { ...control, ...props.style }, value, onChange: (event) => onChange(event.target.value) })
  ] });
}
function Choice({ label, value, options: options2, onChange, placeholder, disabled }) {
  return /* @__PURE__ */ jsxs7("label", { style: { ...stack, gap: 4 }, children: [
    /* @__PURE__ */ jsx9("span", { children: label }),
    /* @__PURE__ */ jsxs7("select", { disabled, style: control, value, onChange: (event) => onChange(event.target.value), children: [
      placeholder ? /* @__PURE__ */ jsx9("option", { value: "", children: placeholder }) : null,
      options2.map(([key, text]) => /* @__PURE__ */ jsx9("option", { value: key, children: text }, key))
    ] })
  ] });
}
function Check({ label, checked, onChange, disabled }) {
  return /* @__PURE__ */ jsxs7("label", { style: { ...row, alignItems: "flex-start", cursor: disabled ? "default" : "pointer", paddingBlock: 2 }, children: [
    /* @__PURE__ */ jsx9("input", { type: "checkbox", disabled, checked, onChange: (event) => onChange(event.target.checked), style: { margin: "2px 0 0", accentColor: "var(--xlsx-pivot-accent)", flexShrink: 0 } }),
    /* @__PURE__ */ jsx9("span", { style: { overflowWrap: "anywhere" }, children: label })
  ] });
}
function Section({ title, children: children2 }) {
  return /* @__PURE__ */ jsxs7("details", { style: { borderTop: "1px solid var(--xlsx-pivot-border)" }, children: [
    /* @__PURE__ */ jsx9("summary", { style: { cursor: "pointer", fontWeight: 600, padding: "11px 12px", userSelect: "none" }, children: title }),
    /* @__PURE__ */ jsx9("div", { style: { ...stack, padding: "0 12px 12px" }, children: children2 })
  ] });
}
function Members({ items, selected, onChange, label = "Items" }) {
  const [search, setSearch] = React12.useState("");
  const visible = items.filter((item) => item.caption.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  const keys = new Set(selected);
  return /* @__PURE__ */ jsxs7("div", { style: { ...stack, gap: 6 }, children: [
    /* @__PURE__ */ jsx9(Text, { label: `Search ${label.toLowerCase()}`, type: "search", value: search, onChange: setSearch }),
    /* @__PURE__ */ jsxs7("div", { style: { ...row, flexWrap: "wrap" }, children: [
      /* @__PURE__ */ jsx9(Action, { onClick: () => onChange(items.map((item) => item.key)), children: "Select all" }),
      /* @__PURE__ */ jsx9(Action, { onClick: () => onChange([]), children: "Clear" }),
      /* @__PURE__ */ jsxs7("span", { style: hint, children: [
        keys.size,
        " selected"
      ] })
    ] }),
    /* @__PURE__ */ jsxs7("div", { role: "group", "aria-label": label, style: { maxHeight: 150, overflowY: "auto", padding: "4px 6px", border: "1px solid var(--xlsx-pivot-border)" }, children: [
      visible.slice(0, 200).map((item) => /* @__PURE__ */ jsx9(Check, { label: item.caption || "(blank)", checked: keys.has(item.key), onChange: (checked) => onChange(checked ? [...keys, item.key] : selected.filter((key) => key !== item.key)) }, item.key)),
      !visible.length ? /* @__PURE__ */ jsx9("p", { style: hint, children: "No matching items." }) : null,
      visible.length > 200 ? /* @__PURE__ */ jsxs7("p", { style: hint, children: [
        "Search to narrow ",
        visible.length.toLocaleString(),
        " items."
      ] }) : null
    ] })
  ] });
}
function ValueSettings({ pivot, value, onChange }) {
  const axes = [...pivot.rows, ...pivot.columns];
  const needsBase = ["percent", "difference", "percentDifference", "runningTotal", "percentRunningTotal", "rankAscending", "rankDescending"].includes(value.showAs);
  const needsItem = ["percent", "difference", "percentDifference"].includes(value.showAs);
  const baseAxes = axes.filter((axis) => axis.field === value.baseField);
  const base = baseAxes.find((axis) => groupingUnit(axis) === (value.baseGroupingUnit ?? null)) ?? baseAxes[0];
  const source = pivot.fields.find((field) => field.index === value.baseField);
  return /* @__PURE__ */ jsxs7(Fragment8, { children: [
    /* @__PURE__ */ jsx9(Text, { label: "Custom name", value: value.name, onChange: (name) => onChange({ ...value, name }) }),
    /* @__PURE__ */ jsx9(Choice, { label: "Summarize values by", value: value.aggregation, options: AGGREGATIONS, onChange: (aggregation) => onChange({ ...value, aggregation }) }),
    /* @__PURE__ */ jsx9(Choice, { label: "Show values as", value: value.showAs, options: SHOW_AS, onChange: (showAs) => onChange({ ...value, showAs, baseField: value.baseField ?? axes[0]?.field }) }),
    needsBase ? /* @__PURE__ */ jsx9(Choice, { label: "Base field", value: value.baseField == null ? "" : String(value.baseField), placeholder: "Choose a field", options: pivot.fields.filter((field) => axes.some((axis) => axis.field === field.index)).map((field) => [String(field.index), field.name]), onChange: (field) => onChange({ ...value, baseField: Number(field), baseGroupingUnit: null, baseItem: null }) }) : null,
    needsBase && baseAxes.length > 1 ? /* @__PURE__ */ jsx9(Choice, { label: "Base grouping level", value: value.baseGroupingUnit ?? groupingUnit(base) ?? "", options: baseAxes.map((axis) => [groupingUnit(axis) ?? "", axis.name || groupingUnit(axis) || "Source items"]), onChange: (unit) => onChange({ ...value, baseGroupingUnit: unit || null, baseItem: null }) }) : null,
    needsItem ? /* @__PURE__ */ jsx9(Choice, { label: "Base item", value: value.baseItem ?? "previous", options: [["previous", "(previous)"], ["next", "(next)"], ...(base?.items?.length ? base.items : source?.items ?? []).map((item) => [item.key, item.caption])], onChange: (baseItem) => onChange({ ...value, baseItem }) }) : null,
    /* @__PURE__ */ jsx9(Text, { label: "Number format", value: value.numberFormat ?? "", placeholder: "General", onChange: (numberFormat) => onChange({ ...value, numberFormat: numberFormat || null }) }),
    /* @__PURE__ */ jsx9(Text, { label: "Calculated field formula", value: value.formula ?? "", placeholder: "Leave blank for a source field", onChange: (formula) => onChange({ ...value, formula: formula || null }) }),
    /* @__PURE__ */ jsx9("p", { style: hint, children: "Use field names in formulas. Enclose names containing spaces in single quotes or square brackets." }),
    /* @__PURE__ */ jsx9("p", { style: hint, children: FORMULA_HELP })
  ] });
}
function AxisSettings({ pivot, axis, onChange, onAddDateLevel }) {
  const source = pivot.fields.find((field) => field.index === axis.field);
  const grouping = axis.grouping;
  const updateGrouping = (patch) => onChange({ ...axis, grouping: { ...grouping, ...patch }, items: [], collapsed: [] });
  const availableUnits = DATE_UNITS.filter((unit) => ![...pivot.rows, ...pivot.columns].some((field) => field.field === axis.field && field.grouping?.kind === "date" && field.grouping.unit === unit));
  return /* @__PURE__ */ jsxs7(Fragment8, { children: [
    /* @__PURE__ */ jsx9(Text, { label: "Custom name", value: axis.name ?? "", placeholder: source?.name, onChange: (name) => onChange({ ...axis, name: name || null }) }),
    /* @__PURE__ */ jsx9(Choice, { label: "Sort", value: axis.sort, options: [["ascending", "Ascending (A to Z)"], ["descending", "Descending (Z to A)"], ["manual", "Source order"], ["valueAscending", "Smallest to largest by value"], ["valueDescending", "Largest to smallest by value"]], onChange: (sort) => onChange({ ...axis, sort, sortMeasure: axis.sortMeasure ?? 0 }) }),
    axis.sort.startsWith("value") ? /* @__PURE__ */ jsx9(Choice, { label: "Sort by value", value: String(axis.sortMeasure ?? 0), options: pivot.values.map((value, index) => [String(index), value.name]), onChange: (sortMeasure) => onChange({ ...axis, sortMeasure: Number(sortMeasure) }) }) : null,
    /* @__PURE__ */ jsx9(Check, { label: "Show subtotals", checked: axis.subtotals, onChange: (subtotals) => onChange({ ...axis, subtotals }) }),
    axis.subtotals ? /* @__PURE__ */ jsxs7("details", { children: [
      /* @__PURE__ */ jsx9("summary", { style: { cursor: "pointer" }, children: "Custom subtotal functions" }),
      /* @__PURE__ */ jsx9("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 3, marginTop: 6 }, children: AGGREGATIONS.map(([value, label]) => /* @__PURE__ */ jsx9(Check, { label, checked: axis.subtotalFunctions?.includes(value) ?? false, onChange: (checked) => onChange({ ...axis, subtotalFunctions: checked ? [...axis.subtotalFunctions ?? [], value] : axis.subtotalFunctions?.filter((item) => item !== value) }) }, value)) }),
      /* @__PURE__ */ jsx9("p", { style: hint, children: "Leave unchecked to use the value field\u2019s summary function." })
    ] }) : null,
    /* @__PURE__ */ jsx9(Check, { label: "Show items with no data", checked: axis.showItemsWithNoData ?? false, onChange: (showItemsWithNoData) => onChange({ ...axis, showItemsWithNoData }) }),
    /* @__PURE__ */ jsx9(Choice, { label: "Grouping", value: grouping?.kind ?? "none", options: [["none", "None"], ["number", "Numeric intervals"], ["date", "Date intervals"], ["manual", "Named groups"]], onChange: (kind) => onChange({ ...axis, grouping: kind === "none" ? null : { kind, unit: "months", interval: 1, groups: [] }, items: [], collapsed: [] }) }),
    grouping?.kind === "date" ? /* @__PURE__ */ jsx9(Choice, { label: "Group dates by", value: grouping.unit, options: DATE_UNITS.map((unit) => [unit, unit[0].toUpperCase() + unit.slice(1)]), onChange: (unit) => updateGrouping({ unit }) }) : null,
    grouping && grouping.kind !== "manual" ? /* @__PURE__ */ jsxs7(Fragment8, { children: [
      /* @__PURE__ */ jsx9(Text, { label: "Interval", type: "number", min: 1e-6, step: "any", value: String(grouping.interval), onChange: (interval) => updateGrouping({ interval: Number(interval) }) }),
      /* @__PURE__ */ jsxs7("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }, children: [
        /* @__PURE__ */ jsx9(Text, { label: "Starting at", type: "number", step: "any", placeholder: "Automatic", value: grouping.start == null ? "" : String(grouping.start), onChange: (start) => updateGrouping({ start: start === "" ? null : Number(start) }) }),
        /* @__PURE__ */ jsx9(Text, { label: "Ending at", type: "number", step: "any", placeholder: "Automatic", value: grouping.end == null ? "" : String(grouping.end), onChange: (end) => updateGrouping({ end: end === "" ? null : Number(end) }) })
      ] }),
      grouping.kind === "date" ? /* @__PURE__ */ jsx9("p", { style: hint, children: "Optional bounds use Excel date serial values." }) : null
    ] }) : null,
    grouping?.kind === "date" && availableUnits.length ? /* @__PURE__ */ jsx9(Choice, { label: "Add date grouping level", value: "", placeholder: "Choose a level", options: availableUnits.map((unit) => [unit, unit[0].toUpperCase() + unit.slice(1)]), onChange: (unit) => onAddDateLevel(unit) }) : null,
    grouping?.kind === "manual" ? /* @__PURE__ */ jsxs7(Fragment8, { children: [
      grouping.groups.map((group, index) => /* @__PURE__ */ jsxs7("div", { style: { ...stack, borderTop: "1px solid var(--xlsx-pivot-border)", paddingTop: 8 }, children: [
        /* @__PURE__ */ jsx9(Text, { label: "Group name", value: group.name, onChange: (name) => updateGrouping({ groups: grouping.groups.map((item, position) => position === index ? { ...item, name } : item) }) }),
        /* @__PURE__ */ jsx9(Members, { items: source?.items ?? [], selected: group.members, onChange: (members) => updateGrouping({ groups: grouping.groups.map((item, position) => position === index ? { ...item, members } : item) }) }),
        /* @__PURE__ */ jsx9(Action, { onClick: () => updateGrouping({ groups: grouping.groups.filter((_, position) => position !== index) }), children: "Remove group" })
      ] }, index)),
      /* @__PURE__ */ jsx9(Action, { onClick: () => updateGrouping({ groups: [...grouping.groups, { name: `Group ${grouping.groups.length + 1}`, members: [] }] }), children: "Add named group" })
    ] }) : null,
    /* @__PURE__ */ jsxs7("details", { children: [
      /* @__PURE__ */ jsx9("summary", { style: { cursor: "pointer" }, children: "Collapse members" }),
      /* @__PURE__ */ jsx9("div", { style: { paddingTop: 8 }, children: grouping && !axis.items?.length ? /* @__PURE__ */ jsx9("p", { style: hint, children: "Apply grouping to load its members." }) : /* @__PURE__ */ jsx9(Members, { label: "Members to collapse", items: axis.items?.length ? axis.items : source?.items ?? [], selected: axis.collapsed, onChange: (collapsed) => onChange({ ...axis, collapsed }) }) })
    ] })
  ] });
}
function FieldFilters({ editor, pivot, field, axis }) {
  const source = pivot.fields.find((item) => item.index === field);
  const filterAxis = axis ?? [...pivot.rows, ...pivot.columns].find((item) => item.field === field && item.grouping);
  const unit = groupingUnit(filterAxis);
  const members = filterAxis?.items?.length ? filterAxis.items : source?.items ?? [];
  const filters = pivot.filters.map((filter, index) => ({ filter, index })).filter(({ filter }) => filter.field === field && (filter.groupingUnit ?? null) === unit);
  const kinds = [["members", "Select items"], ["label", "Label filter"], ["value", "Value filter"], ["top10", "Top / bottom filter"]];
  const update = (index, next) => editor.edit((current) => ({ ...current, filters: current.filters.flatMap((filter, position) => position === index ? next ? [next] : [] : [filter]) }));
  return /* @__PURE__ */ jsxs7("div", { style: { ...stack, paddingTop: 10, borderTop: "1px solid var(--xlsx-pivot-border)" }, children: [
    /* @__PURE__ */ jsxs7("strong", { children: [
      "Field filters",
      unit ? ` \xB7 ${unit}` : ""
    ] }),
    filterAxis?.grouping && !filterAxis.items?.length ? /* @__PURE__ */ jsx9("p", { style: hint, children: "Apply grouping before selecting its members." }) : null,
    filters.map(({ filter, index }) => /* @__PURE__ */ jsxs7("div", { style: { ...stack, paddingBlock: 8, borderTop: "1px solid var(--xlsx-pivot-border)" }, children: [
      /* @__PURE__ */ jsxs7("div", { style: { ...row, justifyContent: "space-between" }, children: [
        /* @__PURE__ */ jsx9("span", { children: kinds.find(([kind]) => kind === filter.kind)?.[1] }),
        /* @__PURE__ */ jsx9(Action, { "aria-label": `Remove ${filter.kind} filter`, onClick: () => update(index, null), children: "\xD7" })
      ] }),
      filter.kind === "members" ? /* @__PURE__ */ jsx9(Members, { items: members, selected: filter.values, onChange: (values) => update(index, { ...filter, values }) }) : null,
      filter.kind === "label" || filter.kind === "value" ? /* @__PURE__ */ jsxs7(Fragment8, { children: [
        /* @__PURE__ */ jsx9(Choice, { label: "Condition", value: filter.operator, options: filter.kind === "value" ? OPERATORS.filter(([operator]) => !/contains|begins|ends/i.test(operator)) : OPERATORS, onChange: (operator) => update(index, { ...filter, operator }) }),
        /* @__PURE__ */ jsx9(Text, { label: "Value", type: filter.kind === "value" ? "number" : "text", value: filter.value, onChange: (value) => update(index, { ...filter, value }) }),
        filter.operator === "between" || filter.operator === "notBetween" ? /* @__PURE__ */ jsx9(Text, { label: "And", type: filter.kind === "value" ? "number" : "text", value: filter.value2, onChange: (value2) => update(index, { ...filter, value2 }) }) : null
      ] }) : null,
      filter.kind === "top10" ? /* @__PURE__ */ jsxs7(Fragment8, { children: [
        /* @__PURE__ */ jsx9(Choice, { label: "Show", value: filter.top ? "top" : "bottom", options: [["top", "Top"], ["bottom", "Bottom"]], onChange: (top) => update(index, { ...filter, top: top === "top" }) }),
        /* @__PURE__ */ jsx9(Text, { label: "Amount", type: "number", min: 1, value: String(filter.count), onChange: (count) => update(index, { ...filter, count: Number(count) }) }),
        /* @__PURE__ */ jsx9(Choice, { label: "Unit", value: filter.percent ? "percent" : "items", options: [["items", "Items"], ["percent", "Percent"]], onChange: (percent) => update(index, { ...filter, percent: percent === "percent" }) })
      ] }) : null,
      filter.kind === "value" || filter.kind === "top10" ? /* @__PURE__ */ jsx9(Choice, { label: "By value", value: String(filter.measure), options: pivot.values.map((value, position) => [String(position), value.name]), onChange: (measure) => update(index, { ...filter, measure: Number(measure) }) }) : null
    ] }, index)),
    /* @__PURE__ */ jsx9(Choice, { label: "Add filter", value: "", placeholder: "Choose a filter", options: kinds.filter(([kind]) => !filters.some(({ filter }) => filter.kind === kind)), onChange: (kind) => editor.edit((current) => ({ ...current, filters: [...current.filters, { field, groupingUnit: unit, kind, values: kind === "members" ? members.map((member) => member.key) : [], operator: "equal", value: "", value2: "", measure: 0, top: true, count: 10, percent: false }] })) })
  ] });
}
function Advanced({ editor, pivot }) {
  const [chartType, setChartType] = React12.useState("ColumnClustered");
  const [chartCell, setChartCell] = React12.useState("I2");
  const [chartTitle, setChartTitle] = React12.useState("");
  const [chartMeasure, setChartMeasure] = React12.useState("");
  const [chartSheet, setChartSheet] = React12.useState("");
  const [chartWidth, setChartWidth] = React12.useState("560");
  const [chartHeight, setChartHeight] = React12.useState("340");
  const update = (patch) => editor.edit((current) => ({ ...current, ...patch }));
  const sheets = editor.viewer.sheets.map((sheet) => [sheet.name, sheet.name]);
  return /* @__PURE__ */ jsxs7(Fragment8, { children: [
    /* @__PURE__ */ jsxs7(Section, { title: "Source and location", children: [
      /* @__PURE__ */ jsx9(Text, { label: "PivotTable name", value: pivot.name, onChange: (name) => update({ name }) }),
      /* @__PURE__ */ jsx9(Choice, { label: "Source worksheet", value: pivot.source.sheet, options: sheets, onChange: (sheet) => update({ source: { ...pivot.source, sheet } }) }),
      /* @__PURE__ */ jsx9(Text, { label: "Source range", value: pivot.source.range, onChange: (range) => update({ source: { ...pivot.source, range } }) }),
      /* @__PURE__ */ jsx9(Text, { label: "Source table name (optional)", value: pivot.source.table ?? "", onChange: (table) => update({ source: { ...pivot.source, table: table || null } }) }),
      /* @__PURE__ */ jsx9(Action, { onClick: editor.readFields, children: "Load source fields" }),
      /* @__PURE__ */ jsx9(Choice, { label: "Destination worksheet", value: pivot.target.sheet, options: sheets, onChange: (sheet) => update({ target: { ...pivot.target, sheet } }) }),
      /* @__PURE__ */ jsx9(Text, { label: "Destination cell", value: pivot.target.cell, onChange: (cell) => update({ target: { ...pivot.target, cell } }) })
    ] }),
    /* @__PURE__ */ jsxs7(Section, { title: "Layout and format", children: [
      /* @__PURE__ */ jsx9(Choice, { label: "Report layout", value: pivot.layout, options: [["compact", "Compact form"], ["outline", "Outline form"], ["tabular", "Tabular form"]], onChange: (layout) => update({ layout }) }),
      /* @__PURE__ */ jsx9(Choice, { label: "Multiple value fields", value: pivot.valuesOnRows ? "rows" : "columns", options: [["columns", "Show values in columns"], ["rows", "Show values in rows"]], onChange: (value) => update({ valuesOnRows: value === "rows" }) }),
      /* @__PURE__ */ jsx9(Check, { label: "Repeat item labels", checked: pivot.repeatLabels, onChange: (repeatLabels) => update({ repeatLabels }) }),
      /* @__PURE__ */ jsx9(Choice, { label: "Subtotals", value: pivot.subtotalsPosition, options: [["top", "At top of group"], ["bottom", "At bottom of group"], ["none", "Do not show"]], onChange: (subtotalsPosition) => update({ subtotalsPosition }) }),
      /* @__PURE__ */ jsx9(Check, { label: "Grand totals for rows", checked: pivot.rowGrandTotals, onChange: (rowGrandTotals) => update({ rowGrandTotals }) }),
      /* @__PURE__ */ jsx9(Check, { label: "Grand totals for columns", checked: pivot.columnGrandTotals, onChange: (columnGrandTotals) => update({ columnGrandTotals }) }),
      /* @__PURE__ */ jsx9(Text, { label: "PivotTable style", value: pivot.styleName, onChange: (styleName) => update({ styleName }) }),
      /* @__PURE__ */ jsx9(Check, { label: "Preserve cell formatting", checked: pivot.preserveFormatting ?? true, onChange: (preserveFormatting) => update({ preserveFormatting }) }),
      /* @__PURE__ */ jsx9(Check, { label: "Refresh when opened in Excel", checked: pivot.refreshOnLoad, onChange: (refreshOnLoad) => update({ refreshOnLoad }) })
    ] }),
    /* @__PURE__ */ jsxs7(Section, { title: "Calculated fields and items", children: [
      /* @__PURE__ */ jsx9(Action, { disabled: !pivot.fields.length, onClick: () => editor.edit((current) => ({ ...current, values: [...current.values, { field: current.fields[0].index, name: `Calculated ${current.values.length + 1}`, aggregation: "sum", showAs: "normal", formula: "0" }] })), children: "Add calculated field" }),
      /* @__PURE__ */ jsx9("p", { style: hint, children: "Edit the new field\u2019s formula in its Values settings." }),
      /* @__PURE__ */ jsx9("p", { style: hint, children: FORMULA_HELP }),
      pivot.calculatedItems.map((item, index) => /* @__PURE__ */ jsxs7("div", { style: { ...stack, paddingTop: 8, borderTop: "1px solid var(--xlsx-pivot-border)" }, children: [
        /* @__PURE__ */ jsx9(Choice, { label: "Field", value: String(item.field), options: pivot.fields.map((field) => [String(field.index), field.name]), onChange: (field) => update({ calculatedItems: pivot.calculatedItems.map((entry, position) => position === index ? { ...entry, field: Number(field) } : entry) }) }),
        /* @__PURE__ */ jsx9(Text, { label: "Item name", value: item.name, onChange: (name) => update({ calculatedItems: pivot.calculatedItems.map((entry, position) => position === index ? { ...entry, name } : entry) }) }),
        /* @__PURE__ */ jsx9(Text, { label: "Formula", value: item.formula, onChange: (formula) => update({ calculatedItems: pivot.calculatedItems.map((entry, position) => position === index ? { ...entry, formula } : entry) }) }),
        /* @__PURE__ */ jsx9(Action, { onClick: () => update({ calculatedItems: pivot.calculatedItems.filter((_, position) => position !== index) }), children: "Remove calculated item" })
      ] }, index)),
      /* @__PURE__ */ jsx9(Action, { disabled: !pivot.fields.length, onClick: () => update({ calculatedItems: [...pivot.calculatedItems, { field: pivot.rows[0]?.field ?? pivot.fields[0].index, name: `Calculated item ${pivot.calculatedItems.length + 1}`, formula: "0" }] }), children: "Add calculated item" })
    ] }),
    /* @__PURE__ */ jsxs7(Section, { title: "PivotChart", children: [
      pivot.charts?.length ? /* @__PURE__ */ jsxs7("p", { style: hint, children: [
        pivot.charts.length,
        " linked chart",
        pivot.charts.length === 1 ? "" : "s",
        ". Refreshing the PivotTable updates their values."
      ] }) : null,
      /* @__PURE__ */ jsx9(Choice, { label: "Chart type", value: chartType, options: CHART_TYPES, onChange: (value) => setChartType(value) }),
      /* @__PURE__ */ jsx9(Text, { label: "Title", value: chartTitle, placeholder: pivot.name, onChange: setChartTitle }),
      /* @__PURE__ */ jsx9(Choice, { label: "Chart worksheet", value: chartSheet || pivot.target.sheet, options: sheets, onChange: setChartSheet }),
      /* @__PURE__ */ jsx9(Text, { label: "Top-left cell", value: chartCell, onChange: setChartCell }),
      /* @__PURE__ */ jsxs7("div", { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }, children: [
        /* @__PURE__ */ jsx9(Text, { label: "Width (px)", type: "number", min: 80, max: 1e4, value: chartWidth, onChange: setChartWidth }),
        /* @__PURE__ */ jsx9(Text, { label: "Height (px)", type: "number", min: 80, max: 1e4, value: chartHeight, onChange: setChartHeight })
      ] }),
      /* @__PURE__ */ jsx9(Choice, { label: "Values", value: chartMeasure, options: [["", "All value fields"], ...pivot.values.map((value, index) => [String(index), value.name])], onChange: setChartMeasure }),
      chartType === "Pie" || chartType === "Doughnut" ? /* @__PURE__ */ jsx9("p", { style: hint, children: "Pie and doughnut charts display the first series." }) : null,
      /* @__PURE__ */ jsx9(Action, { disabled: !pivot.id || editor.dirty || !pivot.values.length, onClick: () => editor.run(() => {
        editor.viewer.createPivotChart(pivot.id, { chartType, sheet: chartSheet || pivot.target.sheet, cell: chartCell, title: chartTitle || pivot.name, width: Number(chartWidth), height: Number(chartHeight), measure: chartMeasure ? Number(chartMeasure) : null });
      }), children: "Insert PivotChart" }),
      editor.dirty ? /* @__PURE__ */ jsx9("p", { style: hint, children: "Apply field changes before inserting a chart." }) : null
    ] })
  ] });
}
function DefaultXlsxPivotTableFieldList({ editor, isDark = false, className, style }) {
  const paneRef = React12.useRef(null);
  const [placement, setPlacement] = React12.useState({ overlay: false, top: 0, width: 324 });
  const [search, setSearch] = React12.useState("");
  const [selected, setSelected] = React12.useState(null);
  const [dragOver, setDragOver] = React12.useState(null);
  const [announcement, setAnnouncement] = React12.useState("");
  const titleId = React12.useId();
  const settingsId = React12.useId();
  const pivot = editor.draft;
  const disabled = editor.readOnly || Boolean(pivot?.unsupportedFeatures.length) || editor.sourceNeedsLoad;
  React12.useEffect(() => {
    setSelected(null);
    setSearch("");
  }, [pivot?.id]);
  React12.useEffect(() => {
    const parent = paneRef.current?.parentElement;
    if (!parent) return;
    const viewer = parent.closest(".react-xlsx-viewer");
    const measure = () => {
      const bounds = parent.getBoundingClientRect();
      const next = { overlay: Boolean(viewer && bounds.width < 640), top: viewer ? bounds.top - viewer.getBoundingClientRect().top : 0, width: Math.min(324, bounds.width) };
      setPlacement((current) => current.overlay === next.overlay && current.top === next.top && current.width === next.width ? current : next);
    };
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(parent);
    if (viewer) observer?.observe(viewer);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);
  const selectedField = pivot && selected ? fieldIndex(pivot, selected.area, selected.index) : void 0;
  const selectedCalculated = Boolean(pivot && selected?.area === "values" && pivot.values[selected.index]?.formula?.trim());
  const theme = {
    "--xlsx-pivot-bg": isDark ? "#242729" : "#fafbfa",
    "--xlsx-pivot-input": isDark ? "#303437" : "#ffffff",
    "--xlsx-pivot-border": isDark ? "#50575a" : "#ccd2cf",
    "--xlsx-pivot-muted": isDark ? "#bcc5c0" : "#5d6962",
    "--xlsx-pivot-accent": isDark ? "#27845d" : "#217346",
    "--xlsx-pivot-hover": isDark ? "#35483d" : "#edf5ef"
  };
  const move = (from, to, index) => {
    if (from.area === "values" && to !== "values" && pivot?.values[from.index]?.formula?.trim()) {
      setAnnouncement("Calculated fields stay in the Values area.");
      return;
    }
    editor.moveField(from.area, from.index, to, index);
    setSelected(null);
    setAnnouncement(`Field moved to ${AREA_NAMES[to]}.`);
  };
  const drop = (event, area, index) => {
    event.preventDefault();
    event.stopPropagation();
    setDragOver(null);
    if (disabled) return;
    try {
      const data = JSON.parse(event.dataTransfer.getData(DRAG_TYPE));
      if ("field" in data && Number.isInteger(data.field) && pivot?.fields.some((field) => field.index === data.field)) {
        editor.addField(area, data.field);
        setAnnouncement(`Field added to ${AREA_NAMES[area]}.`);
      } else if ("area" in data && AREAS.includes(data.area) && Number.isInteger(data.index) && pivot && data.index >= 0 && data.index < pivot[data.area].length) move(data, area, index);
    } catch {
      setAnnouncement("The field could not be moved.");
    }
  };
  const drag = (event, data) => {
    event.dataTransfer.setData(DRAG_TYPE, JSON.stringify(data));
    event.dataTransfer.effectAllowed = "move";
  };
  return /* @__PURE__ */ jsxs7("aside", { ref: paneRef, "aria-labelledby": titleId, className, style: { ...theme, boxSizing: "border-box", display: "flex", flexDirection: "column", width: placement.width, minWidth: 0, maxWidth: "100%", height: "100%", minHeight: 0, flexShrink: 0, borderInlineStart: "1px solid var(--xlsx-pivot-border)", background: "var(--xlsx-pivot-bg)", color: isDark ? "#edf2ef" : "#202a24", font: "12px/1.4 system-ui, sans-serif", ...placement.overlay ? { position: "absolute", insetInlineEnd: 0, top: placement.top, bottom: 0, height: "auto", zIndex: 20, boxShadow: "-6px 0 18px #0002" } : {}, ...style }, children: [
    /* @__PURE__ */ jsxs7("header", { style: { ...row, justifyContent: "space-between", padding: "10px 12px", borderBottom: "1px solid var(--xlsx-pivot-border)" }, children: [
      /* @__PURE__ */ jsx9("h2", { id: titleId, style: { margin: 0, fontSize: 16, fontWeight: 600 }, children: "PivotTable Fields" }),
      /* @__PURE__ */ jsx9(Action, { "aria-label": "Close PivotTable field list", onClick: () => editor.setOpen(false), style: { border: 0, background: "transparent", fontSize: 20, lineHeight: 1, padding: "2px 6px" }, children: "\xD7" })
    ] }),
    /* @__PURE__ */ jsxs7("div", { style: { overflowY: "auto", flex: 1, minHeight: 0 }, children: [
      /* @__PURE__ */ jsxs7("div", { style: { ...stack, padding: 12 }, children: [
        /* @__PURE__ */ jsxs7("div", { style: { ...row, alignItems: "end" }, children: [
          /* @__PURE__ */ jsx9("div", { style: { flex: 1, minWidth: 0 }, children: /* @__PURE__ */ jsx9(Choice, { label: "PivotTable", value: pivot?.id ?? "", placeholder: pivot && !pivot.id ? pivot.name : "Choose a PivotTable", options: editor.viewer.pivotTables.map((item) => [item.id, item.name]), onChange: editor.select, disabled: editor.dirty }) }),
          /* @__PURE__ */ jsx9(Action, { disabled: editor.viewer.readOnly || editor.dirty, onClick: editor.create, children: "New" })
        ] }),
        editor.error ? /* @__PURE__ */ jsx9("p", { role: "alert", style: { margin: 0, color: isDark ? "#ffb7b0" : "#a704", overflowWrap: "anywhere" }, children: editor.error }) : null,
        editor.status ? /* @__PURE__ */ jsx9("p", { role: "status", style: hint, children: editor.status }) : null,
        editor.stale ? /* @__PURE__ */ jsx9("p", { role: "alert", style: hint, children: "The worksheet changed while you were editing. Discard these changes to load the current PivotTable." }) : null,
        editor.sourceNeedsLoad ? /* @__PURE__ */ jsx9("p", { role: "status", style: hint, children: "The source changed. Load its fields under Source and location." }) : null,
        pivot?.unsupportedFeatures.length ? /* @__PURE__ */ jsxs7("p", { style: hint, children: [
          "This PivotTable is preserved for Excel. Editing is unavailable for: ",
          pivot.unsupportedFeatures.join(", "),
          "."
        ] }) : null,
        editor.viewer.readOnly ? /* @__PURE__ */ jsx9("p", { style: hint, children: "Enable workbook editing to change this PivotTable." }) : null
      ] }),
      pivot ? /* @__PURE__ */ jsxs7(Fragment8, { children: [
        /* @__PURE__ */ jsxs7("fieldset", { disabled, style: { margin: 0, padding: "0 12px 12px", border: 0, minWidth: 0 }, children: [
          /* @__PURE__ */ jsx9("legend", { style: { padding: 0, fontWeight: 600, marginBottom: 8 }, children: "Choose fields to add to report" }),
          /* @__PURE__ */ jsx9("input", { "aria-label": "Search PivotTable fields", type: "search", placeholder: "Search fields", value: search, onChange: (event) => setSearch(event.target.value), style: { ...control, marginBottom: 6 } }),
          /* @__PURE__ */ jsxs7("div", { role: "group", "aria-label": "Source fields", style: { maxHeight: 190, overflowY: "auto", border: "1px solid var(--xlsx-pivot-border)", padding: "5px 7px", background: "var(--xlsx-pivot-input)" }, children: [
            pivot.fields.filter((field) => field.name.toLocaleLowerCase().includes(search.toLocaleLowerCase())).map((field) => {
              const checked = AREAS.some((area) => pivot[area].some((_, index) => sourceFieldIndex(pivot, area, index) === field.index));
              return /* @__PURE__ */ jsx9("div", { draggable: !disabled, onDragStart: (event) => drag(event, { field: field.index }), style: { padding: "2px 0" }, children: /* @__PURE__ */ jsx9(Check, { label: field.name, checked, onChange: (value) => {
                if (value) editor.addField(field.dataType === "number" ? "values" : "rows", field.index);
                else {
                  for (const area of AREAS) for (let index = pivot[area].length - 1; index >= 0; index--) if (sourceFieldIndex(pivot, area, index) === field.index) editor.removeField(area, index);
                  editor.edit((current) => ({ ...current, filters: current.filters.filter((item) => item.field !== field.index) }));
                }
                setSelected(null);
              } }) }, field.index);
            }),
            !pivot.fields.length ? /* @__PURE__ */ jsx9("p", { style: hint, children: "Load source fields to begin." }) : !pivot.fields.some((field) => field.name.toLocaleLowerCase().includes(search.toLocaleLowerCase())) ? /* @__PURE__ */ jsx9("p", { style: hint, children: "No matching fields." }) : null
          ] }),
          /* @__PURE__ */ jsx9("p", { style: { ...hint, marginBlock: "10px 6px" }, children: "Drag fields between the areas below." }),
          /* @__PURE__ */ jsx9("div", { style: { display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 8 }, children: AREAS.map((area) => /* @__PURE__ */ jsxs7("section", { "aria-label": `${AREA_NAMES[area]} fields`, onDragOver: (event) => {
            if (!disabled && event.dataTransfer.types.includes(DRAG_TYPE)) {
              event.preventDefault();
              setDragOver(area);
            }
          }, onDragLeave: (event) => {
            if (!event.currentTarget.contains(event.relatedTarget)) setDragOver(null);
          }, onDrop: (event) => drop(event, area), style: { minHeight: 94, minWidth: 0, border: `1px solid ${dragOver === area ? "var(--xlsx-pivot-accent)" : "var(--xlsx-pivot-border)"}`, background: dragOver === area ? "var(--xlsx-pivot-hover)" : "var(--xlsx-pivot-input)" }, children: [
            /* @__PURE__ */ jsxs7("h3", { style: { margin: 0, padding: "5px 6px", fontSize: 11, fontWeight: 600, borderBottom: "1px solid var(--xlsx-pivot-border)", background: "var(--xlsx-pivot-bg)" }, children: [
              area === "values" ? "\u03A3 " : "",
              AREA_NAMES[area]
            ] }),
            /* @__PURE__ */ jsxs7("div", { style: { padding: 4 }, children: [
              pivot[area].map((_, index) => {
                const field = fieldIndex(pivot, area, index);
                const name = area === "values" ? pivot.values[index].name : area === "reportFilters" ? fieldName(pivot, field) : pivot[area][index].name || fieldName(pivot, field);
                const active = selected?.area === area && selected.index === index;
                return /* @__PURE__ */ jsx9("div", { draggable: !disabled, onDragStart: (event) => drag(event, { area, index }), onDrop: (event) => drop(event, area, index), style: { marginBottom: 3 }, children: /* @__PURE__ */ jsxs7("button", { type: "button", "aria-expanded": active, "aria-controls": settingsId, title: `${name} settings. Alt+Up or Alt+Down reorders the field.`, onClick: () => setSelected(active ? null : { area, index }), onKeyDown: (event) => {
                  if (!event.altKey || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
                  event.preventDefault();
                  const position = index + (event.key === "ArrowUp" ? -1 : 1);
                  if (position >= 0 && position < pivot[area].length) move({ area, index }, area, position);
                }, style: { ...control, ...row, textAlign: "start", justifyContent: "space-between", background: active ? "var(--xlsx-pivot-hover)" : "var(--xlsx-pivot-bg)", padding: "4px 5px", cursor: "pointer", fontSize: 11 }, children: [
                  /* @__PURE__ */ jsx9("span", { style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, children: name }),
                  /* @__PURE__ */ jsx9("span", { "aria-hidden": "true", children: "\u25BE" })
                ] }) }, `${field}-${index}`);
              }),
              !pivot[area].length ? /* @__PURE__ */ jsx9("p", { style: { ...hint, padding: "5px 3px", fontSize: 10 }, children: "Drop fields here" }) : null
            ] })
          ] }, area)) }),
          /* @__PURE__ */ jsx9("p", { style: { ...hint, marginTop: 6 }, children: "Select a field for settings and keyboard move controls." }),
          selected && selectedField !== void 0 ? /* @__PURE__ */ jsxs7("section", { id: settingsId, "aria-label": "Field settings", style: { ...stack, marginTop: 12, paddingTop: 10, borderTop: "2px solid var(--xlsx-pivot-accent)" }, children: [
            /* @__PURE__ */ jsxs7("div", { style: { ...row, justifyContent: "space-between" }, children: [
              /* @__PURE__ */ jsxs7("strong", { style: { overflowWrap: "anywhere" }, children: [
                selected.area === "values" ? pivot.values[selected.index].name : fieldName(pivot, selectedField),
                " settings"
              ] }),
              /* @__PURE__ */ jsx9(Action, { "aria-label": "Close field settings", onClick: () => setSelected(null), children: "\xD7" })
            ] }),
            selectedCalculated ? /* @__PURE__ */ jsx9("p", { style: hint, children: "Calculated fields stay in the Values area." }) : /* @__PURE__ */ jsx9(Choice, { label: "Move to", value: selected.area, options: AREAS.map((area) => [area, AREA_NAMES[area]]), onChange: (area) => move(selected, area) }),
            /* @__PURE__ */ jsxs7("div", { style: { ...row, flexWrap: "wrap" }, children: [
              /* @__PURE__ */ jsx9(Action, { disabled: selected.index === 0, onClick: () => move(selected, selected.area, selected.index - 1), children: "Move up" }),
              /* @__PURE__ */ jsx9(Action, { disabled: selected.index === pivot[selected.area].length - 1, onClick: () => move(selected, selected.area, selected.index + 1), children: "Move down" }),
              /* @__PURE__ */ jsx9(Action, { onClick: () => {
                editor.removeField(selected.area, selected.index);
                setSelected(null);
              }, children: "Remove field" })
            ] }),
            selected.area === "values" ? /* @__PURE__ */ jsx9(ValueSettings, { pivot, value: pivot.values[selected.index], onChange: (value) => editor.edit((current) => ({ ...current, values: current.values.map((item, index) => index === selected.index ? value : item) })) }) : selected.area === "rows" || selected.area === "columns" ? /* @__PURE__ */ jsx9(AxisSettings, { pivot, axis: pivot[selected.area][selected.index], onChange: (axis) => editor.edit((current) => ({ ...current, [selected.area]: current[selected.area].map((item, index) => index === selected.index ? axis : item) })), onAddDateLevel: (unit) => editor.edit((current) => {
              const area = selected.area;
              const axis = current[area][selected.index];
              return { ...current, [area]: [...current[area].slice(0, selected.index + 1), { ...axis, name: unit[0].toUpperCase() + unit.slice(1), grouping: { ...axis.grouping, kind: "date", unit }, items: [], collapsed: [] }, ...current[area].slice(selected.index + 1)] };
            }) }) : null,
            selected.area !== "values" ? /* @__PURE__ */ jsx9(FieldFilters, { editor, pivot, field: selectedField, axis: selected.area === "rows" || selected.area === "columns" ? pivot[selected.area][selected.index] : void 0 }) : null
          ] }) : null
        ] }),
        /* @__PURE__ */ jsx9("fieldset", { disabled: editor.readOnly || Boolean(pivot.unsupportedFeatures.length), style: { margin: 0, padding: 0, minWidth: 0, border: 0 }, children: /* @__PURE__ */ jsx9(Advanced, { editor, pivot }) }),
        /* @__PURE__ */ jsxs7(Section, { title: "Refresh and details", children: [
          /* @__PURE__ */ jsxs7("div", { style: { ...row, flexWrap: "wrap" }, children: [
            /* @__PURE__ */ jsx9(Action, { disabled: disabled || editor.dirty || !pivot.id, onClick: () => editor.refresh(), children: "Refresh" }),
            /* @__PURE__ */ jsx9(Action, { disabled: editor.readOnly || editor.dirty || !editor.viewer.pivotTables.length, onClick: () => editor.refresh(true), children: "Refresh all" }),
            /* @__PURE__ */ jsx9(Action, { disabled: disabled || editor.dirty || !pivot.id, onClick: editor.showDetails, children: "Show details" })
          ] }),
          /* @__PURE__ */ jsx9("p", { style: hint, children: "Select a value cell in the report to inspect its source records." }),
          editor.details ? /* @__PURE__ */ jsxs7(Fragment8, { children: [
            /* @__PURE__ */ jsxs7("div", { style: { ...row, justifyContent: "space-between" }, children: [
              /* @__PURE__ */ jsxs7("span", { children: [
                editor.details.rows.length.toLocaleString(),
                " records"
              ] }),
              /* @__PURE__ */ jsx9(Action, { onClick: editor.clearDetails, children: "Close details" })
            ] }),
            /* @__PURE__ */ jsx9("div", { style: { maxHeight: 210, overflow: "auto", border: "1px solid var(--xlsx-pivot-border)" }, children: /* @__PURE__ */ jsxs7("table", { style: { borderCollapse: "collapse", fontSize: 11 }, children: [
              /* @__PURE__ */ jsx9("thead", { children: /* @__PURE__ */ jsx9("tr", { children: editor.details.fields.map((field, index) => /* @__PURE__ */ jsx9("th", { scope: "col", style: { padding: "5px 7px", textAlign: "start", whiteSpace: "nowrap", borderBottom: "1px solid var(--xlsx-pivot-border)" }, children: field }, index)) }) }),
              /* @__PURE__ */ jsx9("tbody", { children: editor.details.rows.slice(0, 100).map((record, index) => /* @__PURE__ */ jsx9("tr", { children: record.map((value, column) => /* @__PURE__ */ jsx9("td", { style: { padding: "4px 7px", whiteSpace: "nowrap", borderBottom: "1px solid var(--xlsx-pivot-border)" }, children: value == null ? "" : String(value) }, column)) }, index)) })
            ] }) }),
            editor.details.rows.length > 100 ? /* @__PURE__ */ jsx9("p", { style: hint, children: "Showing the first 100 records. Create a detail worksheet to see all records." }) : null,
            /* @__PURE__ */ jsx9(Action, { disabled: editor.readOnly || !editor.detailContext, onClick: () => editor.run(() => {
              const context = editor.detailContext;
              if (context) editor.viewer.showPivotDetails(context.id, context.row, context.col);
            }), children: "Create detail worksheet" })
          ] }) : null,
          /* @__PURE__ */ jsx9(Action, { disabled: editor.readOnly || editor.dirty || !pivot.id, onClick: editor.remove, children: "Remove PivotTable" })
        ] })
      ] }) : /* @__PURE__ */ jsxs7("div", { style: { ...stack, padding: "4px 12px 20px" }, children: [
        /* @__PURE__ */ jsx9("p", { style: hint, children: "Select a PivotTable cell to arrange its fields, or create a PivotTable from the selected data." }),
        /* @__PURE__ */ jsx9(Action, { primary: true, disabled: editor.readOnly || !editor.viewer.activeSheet, onClick: editor.create, children: "Create PivotTable" })
      ] })
    ] }),
    pivot ? /* @__PURE__ */ jsx9("footer", { style: { ...stack, gap: 7, padding: "10px 12px", borderTop: "1px solid var(--xlsx-pivot-border)" }, children: /* @__PURE__ */ jsxs7("div", { style: { ...row, justifyContent: "space-between" }, children: [
      /* @__PURE__ */ jsx9("span", { style: hint, children: editor.dirty ? "Changes pending" : "Report is up to date" }),
      /* @__PURE__ */ jsxs7("div", { style: row, children: [
        /* @__PURE__ */ jsx9(Action, { disabled: !editor.dirty, onClick: editor.reset, children: "Discard" }),
        /* @__PURE__ */ jsx9(Action, { primary: true, disabled: disabled || !editor.dirty || editor.stale, onClick: editor.apply, children: "Apply" })
      ] })
    ] }) }) : null,
    /* @__PURE__ */ jsx9("span", { role: "status", "aria-live": "polite", style: { position: "absolute", width: 1, height: 1, overflow: "hidden", clipPath: "inset(50%)", whiteSpace: "nowrap" }, children: announcement })
  ] });
}

// src/lazy-chart.tsx
import * as React14 from "react";

// src/chart-loader.ts
function createChartModule(importModule) {
  const initialSnapshot = { module: null, error: null };
  let snapshot = initialSnapshot;
  let promise;
  const listeners = /* @__PURE__ */ new Set();
  const publish = (next) => {
    snapshot = next;
    listeners.forEach((listener) => listener());
  };
  return {
    load: () => promise ??= importModule().then((module) => {
      publish({ module, error: null });
      return module;
    }, (error) => {
      publish({ module: null, error: error instanceof Error ? error : new Error("Unable to load chart module.") });
      throw error;
    }),
    getSnapshot: () => snapshot,
    getServerSnapshot: () => initialSnapshot,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    }
  };
}
var officeChartRenderer = createChartModule(async () => {
  const { SharedChartSvg } = await import("./shared-chart-24MCGSFJ.js");
  return { renderer: null, SharedChartSvg };
});

// src/use-chart-module.ts
import * as React13 from "react";

// src/lazy-chart.tsx
import { Fragment as Fragment9, jsx as jsx10 } from "react/jsx-runtime";

// src/picture-paint.ts
function resolvePicturePaintRect(image, rect) {
  const bounds = image.paintBounds;
  if (!bounds || bounds.layoutWidthPx <= 0 || bounds.layoutHeightPx <= 0) return rect;
  const scaleX = rect.width / bounds.layoutWidthPx;
  const scaleY = rect.height / bounds.layoutHeightPx;
  return {
    left: rect.left + bounds.xPx * scaleX,
    top: rect.top + bounds.yPx * scaleY,
    width: bounds.widthPx * scaleX,
    height: bounds.heightPx * scaleY
  };
}

// src/XlsxViewer.tsx
import { Fragment as Fragment11, jsx as jsx11, jsxs as jsxs8 } from "react/jsx-runtime";
var DEFAULT_ROW_HEIGHT2 = 24;
var DEFAULT_COL_WIDTH2 = 80;
var MAX_AUTOFIT_ROW_HEIGHT_PX = 409 * (4 / 3);
var HEADER_HEIGHT = 24;
var ROW_HEADER_WIDTH = 40;
var HEADER_RESIZE_HANDLE_PX = 8;
var CANVAS_VIEWPORT_OVERSCAN_PX = 480;
var CANVAS_SCROLL_BUFFER_PX = 480;
var CANVAS_DEFERRED_VIEWPORT_SYNC_THRESHOLD_PX = CANVAS_SCROLL_BUFFER_PX - 96;
var CANVAS_IMMEDIATE_VIEWPORT_SYNC_THRESHOLD_PX = CANVAS_SCROLL_BUFFER_PX * 1.5;
var CANVAS_DIRTY_CELL_CULL_MARGIN_PX = CANVAS_VIEWPORT_OVERSCAN_PX * 2;
var THUMBNAIL_DEFAULT_MAX_DIMENSION = 192;
var THUMBNAIL_FALLBACK_ROWS = 12;
var THUMBNAIL_FALLBACK_COLS = 8;
var THUMBNAIL_MAX_ROWS = 200;
var THUMBNAIL_MAX_COLS = 80;
var THUMBNAIL_MAX_SOURCE_HEIGHT_PX = 900;
var THUMBNAIL_MAX_SOURCE_WIDTH_PX = 1440;
var SHEET_SURFACE = "#ffffff";
var DEFAULT_CELL_PADDING = "0 4px";
var CANVAS_CELL_STYLE_CACHE_LIMIT = 4096;
var CANVAS_TEXT_MEASURE_CACHE_LIMIT = 2e4;
var CANVAS_TEXT_TRUNCATE_CACHE_LIMIT = 4096;
var CANVAS_TEXT_WRAP_CACHE_LIMIT = 2048;
var CANVAS_PATH2D_CACHE_LIMIT = 512;
var canvasCellStyleCache = /* @__PURE__ */ new Map();
var canvasTextMeasureCache = /* @__PURE__ */ new Map();
var canvasTextTruncateCache = /* @__PURE__ */ new Map();
var canvasTextWrapCache = /* @__PURE__ */ new Map();
var canvasPath2DCache = /* @__PURE__ */ new Map();
function rememberBoundedCacheValue(cache, key, value, limit) {
  if (cache.size >= limit) {
    const oldestKey = cache.keys().next().value;
    if (oldestKey !== void 0) {
      cache.delete(oldestKey);
    }
  }
  cache.set(key, value);
  return value;
}
function roundCanvasCacheWidth(width) {
  return Math.round(width * 4) / 4;
}
function measureCanvasTextWidth(context, text) {
  if (text.length === 0) {
    return 0;
  }
  const cacheKey = `${context.font}\0${text}`;
  const cached = canvasTextMeasureCache.get(cacheKey);
  if (cached !== void 0) {
    return cached;
  }
  return rememberBoundedCacheValue(
    canvasTextMeasureCache,
    cacheKey,
    context.measureText(text).width,
    CANVAS_TEXT_MEASURE_CACHE_LIMIT
  );
}
function drawCanvasTextDecorations(context, {
  align,
  color,
  decoration,
  ellipsize = false,
  lineThroughY,
  maxWidth,
  text,
  textX,
  underlineY,
  zoomFactor
}) {
  if (!decoration || text.length === 0) {
    return;
  }
  const measured = ellipsize && maxWidth !== void 0 ? Math.min(maxWidth, measureCanvasTextWidth(context, text)) : measureCanvasTextWidth(context, text);
  const startX = align === "right" ? textX - measured : align === "center" ? textX - measured / 2 : textX;
  context.strokeStyle = color;
  context.lineWidth = Math.max(1, zoomFactor * 0.75);
  if (decoration.includes("underline")) {
    context.beginPath();
    context.moveTo(startX, underlineY);
    context.lineTo(startX + measured, underlineY);
    context.stroke();
  }
  if (decoration.includes("line-through")) {
    context.beginPath();
    context.moveTo(startX, lineThroughY);
    context.lineTo(startX + measured, lineThroughY);
    context.stroke();
  }
}
function getCachedCanvasPath2D(path) {
  if (typeof Path2D === "undefined") {
    return null;
  }
  const cached = canvasPath2DCache.get(path);
  if (cached) {
    return cached;
  }
  return rememberBoundedCacheValue(canvasPath2DCache, path, new Path2D(path), CANVAS_PATH2D_CACHE_LIMIT);
}
function scaleCssLengthExpression(value, scale) {
  if (scale === 1) {
    return value;
  }
  return value.replace(/(-?\d*\.?\d+)(px|pt)\b/g, (_, rawNumber, unit) => {
    const nextValue = Number.parseFloat(rawNumber);
    if (!Number.isFinite(nextValue)) {
      return `${rawNumber}${unit}`;
    }
    return `${nextValue * scale}${unit}`;
  });
}
function parseCanvasLength(value, fallback = 0) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const match = value.match(/-?\d*\.?\d+/);
    if (match) {
      const parsed = Number.parseFloat(match[0]);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }
  return fallback;
}
function resolveCanvasPadding(padding) {
  if (typeof padding === "number") {
    return {
      bottom: padding,
      left: padding,
      right: padding,
      top: padding
    };
  }
  if (typeof padding === "string") {
    const parts = padding.trim().split(/\s+/).map((part) => parseCanvasLength(part, 0));
    if (parts.length === 1) {
      const [value = 0] = parts;
      return {
        bottom: value,
        left: value,
        right: value,
        top: value
      };
    }
    if (parts.length === 2) {
      const [vertical = 0, horizontal = 0] = parts;
      return {
        bottom: vertical,
        left: horizontal,
        right: horizontal,
        top: vertical
      };
    }
    if (parts.length === 3) {
      const [top2 = 0, horizontal = 0, bottom2 = 0] = parts;
      return {
        bottom: bottom2,
        left: horizontal,
        right: horizontal,
        top: top2
      };
    }
    const [top = 0, right = 0, bottom = 0, left = 0] = parts;
    return {
      bottom,
      left,
      right,
      top
    };
  }
  return {
    bottom: 0,
    left: 0,
    right: 0,
    top: 0
  };
}
function resolveSpreadsheetTextRotation(textRotation) {
  if (typeof textRotation !== "number" || !Number.isFinite(textRotation)) {
    return null;
  }
  if (textRotation < 0 || textRotation > 180) {
    return null;
  }
  const excelDegrees = textRotation > 90 ? 90 - textRotation : textRotation;
  return -excelDegrees;
}
function resolveRotatedTextBounds(width, height, degrees) {
  const radians = degrees * Math.PI / 180;
  return {
    width: Math.abs(width * Math.cos(radians)) + Math.abs(height * Math.sin(radians)),
    height: Math.abs(width * Math.sin(radians)) + Math.abs(height * Math.cos(radians))
  };
}
function drawRotatedCellText(context, text, degrees, rect, align, verticalAlign, lineHeight) {
  const bounds = resolveRotatedTextBounds(context.measureText(text).width, lineHeight, degrees);
  const centerX = align === "right" ? rect.left + rect.width - bounds.width / 2 : align === "center" ? rect.left + rect.width / 2 : rect.left + bounds.width / 2;
  const centerY = verticalAlign === "top" ? rect.top + bounds.height / 2 : verticalAlign === "middle" ? rect.top + rect.height / 2 : rect.top + rect.height - bounds.height / 2;
  context.save();
  context.translate(centerX, centerY);
  context.rotate(degrees * Math.PI / 180);
  context.textAlign = "center";
  context.fillText(text, 0, 0);
  context.restore();
}
function resolveCanvasFont(style, fallbackSize = 12) {
  if (typeof style.font === "string" && style.font.trim().length > 0) {
    return style.font;
  }
  const fontStyle = typeof style.fontStyle === "string" && style.fontStyle.trim().length > 0 ? style.fontStyle : "normal";
  const fontSize = typeof style.fontSize === "string" && style.fontSize.trim().length > 0 ? style.fontSize : typeof style.fontSize === "number" && Number.isFinite(style.fontSize) ? `${style.fontSize}px` : `${fallbackSize}px`;
  const fontWeight = typeof style.fontWeight === "number" || typeof style.fontWeight === "string" ? String(style.fontWeight) : "400";
  const fontFamily = typeof style.fontFamily === "string" && style.fontFamily.trim().length > 0 ? style.fontFamily : "ui-sans-serif, system-ui, sans-serif";
  return `${fontStyle} ${fontWeight} ${fontSize} ${fontFamily}`;
}
function resolveCanvasFontWithPxSize(style, fontSizePx) {
  const fontStyle = typeof style.fontStyle === "string" && style.fontStyle.trim().length > 0 ? style.fontStyle : "normal";
  const fontWeight = typeof style.fontWeight === "number" || typeof style.fontWeight === "string" ? String(style.fontWeight) : "400";
  const fontFamily = typeof style.fontFamily === "string" && style.fontFamily.trim().length > 0 ? style.fontFamily : "ui-sans-serif, system-ui, sans-serif";
  return `${fontStyle} ${fontWeight} ${Math.max(1, fontSizePx)}px ${fontFamily}`;
}
function parseCanvasBorderDeclaration(borderValue) {
  if (typeof borderValue !== "string") {
    return null;
  }
  const trimmed = borderValue.trim();
  if (!trimmed || trimmed === "none") {
    return null;
  }
  const parts = trimmed.split(/\s+/);
  if (parts.length < 3) {
    return null;
  }
  const width = parseCanvasLength(parts[0], 1);
  const style = parts[1] ?? "solid";
  const color = parts.slice(2).join(" ");
  if (!Number.isFinite(width) || width <= 0 || !color) {
    return null;
  }
  return { color, style, width };
}
function applyCanvasBorderDash(context, style, width) {
  context.lineCap = "butt";
  if (style === "dashed") {
    context.setLineDash([Math.max(3, width * 3), Math.max(2, width * 2)]);
    return;
  }
  if (style === "dotted") {
    context.lineCap = "round";
    context.setLineDash([Math.max(0.01, width * 0.01), Math.max(2, width * 2.2)]);
    return;
  }
  context.setLineDash([]);
}
function strokeCanvasBorderSide(context, side, rect, border) {
  const strokeWidth = border.style === "double" ? border.width / 3 : border.width;
  const halfWidth = strokeWidth / 2;
  const left = rect.left;
  const right = rect.left + rect.width;
  const top = rect.top;
  const bottom = rect.top + rect.height;
  context.strokeStyle = border.color;
  context.lineWidth = border.width;
  applyCanvasBorderDash(context, border.style, border.width);
  const strokeLine = (offset = 0) => {
    context.beginPath();
    if (side === "top") {
      context.moveTo(left, top + halfWidth + offset);
      context.lineTo(right, top + halfWidth + offset);
    } else if (side === "bottom") {
      context.moveTo(left, bottom - halfWidth - offset);
      context.lineTo(right, bottom - halfWidth - offset);
    } else if (side === "left") {
      context.moveTo(left + halfWidth + offset, top);
      context.lineTo(left + halfWidth + offset, bottom);
    } else {
      context.moveTo(right - halfWidth - offset, top);
      context.lineTo(right - halfWidth - offset, bottom);
    }
    context.stroke();
  };
  if (border.style === "double") {
    const inset = border.width - strokeWidth;
    context.lineWidth = strokeWidth;
    context.setLineDash([]);
    strokeLine(0);
    strokeLine(inset);
  } else {
    strokeLine(0);
  }
  context.setLineDash([]);
  context.lineCap = "butt";
  context.lineWidth = 1;
}
function truncateCanvasText(context, text, maxWidth) {
  if (maxWidth <= 0 || text.length === 0) {
    return "";
  }
  const roundedMaxWidth = roundCanvasCacheWidth(maxWidth);
  const cacheKey = `${context.font}\0${roundedMaxWidth}\0${text}`;
  const cached = canvasTextTruncateCache.get(cacheKey);
  if (cached !== void 0) {
    return cached;
  }
  if (measureCanvasTextWidth(context, text) <= maxWidth) {
    rememberBoundedCacheValue(canvasTextTruncateCache, cacheKey, text, CANVAS_TEXT_TRUNCATE_CACHE_LIMIT);
    return text;
  }
  const ellipsis = "\u2026";
  let low = 0;
  let high = text.length;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    const candidate = `${text.slice(0, mid)}${ellipsis}`;
    if (measureCanvasTextWidth(context, candidate) <= maxWidth) {
      low = mid;
    } else {
      high = mid - 1;
    }
  }
  return rememberBoundedCacheValue(
    canvasTextTruncateCache,
    cacheKey,
    low <= 0 ? ellipsis : `${text.slice(0, low)}${ellipsis}`,
    CANVAS_TEXT_TRUNCATE_CACHE_LIMIT
  );
}
function resolveCanvasFontSizePx(style, fallbackSize = 12) {
  const rawFontSize = style.fontSize;
  if (typeof rawFontSize === "number" && Number.isFinite(rawFontSize)) {
    return rawFontSize;
  }
  if (typeof rawFontSize === "string") {
    const trimmed = rawFontSize.trim();
    const parsed = Number.parseFloat(trimmed);
    if (Number.isFinite(parsed)) {
      if (trimmed.endsWith("pt")) {
        return parsed * (96 / 72);
      }
      if (trimmed.endsWith("em") || trimmed.endsWith("rem")) {
        return parsed * 16;
      }
      return parsed;
    }
  }
  return fallbackSize;
}
function resolveCanvasLineHeight(style, fallbackFontSize = 12) {
  const fontSizePx = resolveCanvasFontSizePx(style, fallbackFontSize);
  const rawLineHeight = style.lineHeight;
  if (typeof rawLineHeight === "number" && Number.isFinite(rawLineHeight)) {
    return rawLineHeight > 4 ? rawLineHeight : rawLineHeight * fontSizePx;
  }
  if (typeof rawLineHeight === "string") {
    const trimmed = rawLineHeight.trim();
    if (!trimmed || trimmed === "normal") {
      return fontSizePx * 1.2;
    }
    const parsed = Number.parseFloat(trimmed);
    if (Number.isFinite(parsed)) {
      if (/^-?\d*\.?\d+$/.test(trimmed)) {
        return parsed > 4 ? parsed : parsed * fontSizePx;
      }
      if (trimmed.endsWith("pt")) {
        return parsed * (96 / 72);
      }
      if (trimmed.endsWith("em") || trimmed.endsWith("rem")) {
        return parsed * 16;
      }
      return parsed;
    }
  }
  return fontSizePx * 1.2;
}
function resolveCanvasTextMiddleY(verticalAlign, contentTop, contentHeight, lineHeight) {
  if (verticalAlign === "top") {
    return contentTop + lineHeight / 2;
  }
  if (verticalAlign === "middle") {
    return contentTop + contentHeight / 2;
  }
  return contentTop + contentHeight - lineHeight / 2;
}
function resolveCanvasWrapIndex(context, text, maxWidth) {
  if (text.length <= 1) {
    return text.length;
  }
  let low = 1;
  let high = text.length;
  let best = 1;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    const candidate = text.slice(0, mid);
    if (measureCanvasTextWidth(context, candidate) <= maxWidth) {
      best = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return best;
}
function wrapCanvasText(context, text, maxWidth) {
  if (text.length === 0) {
    return [""];
  }
  if (maxWidth <= 0) {
    return text.replace(/\r\n?/g, "\n").split("\n");
  }
  const normalized = text.replace(/\r\n?/g, "\n");
  const roundedMaxWidth = roundCanvasCacheWidth(maxWidth);
  const cacheKey = `${context.font}\0${roundedMaxWidth}\0${normalized}`;
  const cached = canvasTextWrapCache.get(cacheKey);
  if (cached) {
    return cached;
  }
  const paragraphs = normalized.split("\n");
  const lines = [];
  for (const paragraph of paragraphs) {
    if (paragraph.length === 0) {
      lines.push("");
      continue;
    }
    let remaining = paragraph;
    while (remaining.length > 0) {
      if (measureCanvasTextWidth(context, remaining) <= maxWidth) {
        lines.push(remaining);
        break;
      }
      const fit = Math.max(1, resolveCanvasWrapIndex(context, remaining, maxWidth));
      const candidate = remaining.slice(0, fit);
      const whitespaceIndex = fit < remaining.length ? Math.max(candidate.lastIndexOf(" "), candidate.lastIndexOf("	")) : -1;
      const breakIndex = whitespaceIndex > 0 ? whitespaceIndex : fit;
      const nextLine = remaining.slice(0, breakIndex);
      if (nextLine.length === 0) {
        lines.push(remaining.slice(0, fit));
        remaining = remaining.slice(fit);
        continue;
      }
      lines.push(nextLine.replace(/\s+$/g, ""));
      remaining = remaining.slice(breakIndex).replace(/^\s+/g, "");
    }
  }
  return rememberBoundedCacheValue(canvasTextWrapCache, cacheKey, lines, CANVAS_TEXT_WRAP_CACHE_LIMIT);
}
function buildCanvasCellStyleCache(style) {
  const cacheKey = [
    style.font,
    style.fontStyle,
    style.fontWeight,
    style.fontSize,
    style.fontFamily,
    style.borderTop,
    style.borderRight,
    style.borderBottom,
    style.borderLeft,
    style.padding,
    style.textAlign,
    style.color,
    style.textDecoration,
    style.textOverflow,
    style.whiteSpace
  ].map((value) => value == null ? "" : String(value)).join("");
  const cached = canvasCellStyleCache.get(cacheKey);
  if (cached) {
    return cached;
  }
  return rememberBoundedCacheValue(canvasCellStyleCache, cacheKey, {
    baseFont: resolveCanvasFont(style, 12),
    bottomBorder: parseCanvasBorderDeclaration(style.borderBottom),
    leftBorder: parseCanvasBorderDeclaration(style.borderLeft),
    padding: resolveCanvasPadding(style.padding),
    rightBorder: parseCanvasBorderDeclaration(style.borderRight),
    textAlign: style.textAlign === "right" || style.textAlign === "center" ? style.textAlign : "left",
    textColor: typeof style.color === "string" ? style.color : "#000000",
    textDecoration: typeof style.textDecoration === "string" ? style.textDecoration : void 0,
    textOverflowEllipsis: style.textOverflow === "ellipsis",
    topBorder: parseCanvasBorderDeclaration(style.borderTop),
    usesWrappedText: style.whiteSpace === "pre-wrap"
  }, CANVAS_CELL_STYLE_CACHE_LIMIT);
}
function splitCssGradientArgs(value) {
  const parts = [];
  let current = "";
  let depth = 0;
  for (const character of value) {
    if (character === "(") {
      depth += 1;
      current += character;
      continue;
    }
    if (character === ")") {
      depth = Math.max(0, depth - 1);
      current += character;
      continue;
    }
    if (character === "," && depth === 0) {
      parts.push(current.trim());
      current = "";
      continue;
    }
    current += character;
  }
  if (current.trim().length > 0) {
    parts.push(current.trim());
  }
  return parts;
}
function parseCanvasGradientStops(value) {
  return splitCssGradientArgs(value).map((part) => {
    const match = part.match(/^(.*?)(?:\s+(-?\d*\.?\d+)%)?$/);
    if (!match) {
      return null;
    }
    const color = match[1]?.trim();
    const percent = match[2] ? Number.parseFloat(match[2]) : Number.NaN;
    if (!color) {
      return null;
    }
    return {
      color,
      offset: Number.isFinite(percent) ? Math.max(0, Math.min(1, percent / 100)) : null
    };
  }).filter((stop) => Boolean(stop));
}
function resolveCanvasGradientFill(context, rect, backgroundImage) {
  const linearMatch = backgroundImage.match(/^linear-gradient\((.*)\)$/i);
  if (linearMatch) {
    const parts = splitCssGradientArgs(linearMatch[1] ?? "");
    if (parts.length >= 2) {
      const rawAngle = parts[0]?.trim() ?? "180deg";
      const angleMatch = rawAngle.match(/(-?\d*\.?\d+)deg/i);
      const cssAngle = angleMatch ? Number.parseFloat(angleMatch[1] ?? "180") : 180;
      const radians = (90 - cssAngle) * Math.PI / 180;
      const halfWidth = rect.width / 2;
      const halfHeight = rect.height / 2;
      const centerX = rect.left + halfWidth;
      const centerY = rect.top + halfHeight;
      const projectedHalfLength = Math.abs(Math.cos(radians) * halfWidth) + Math.abs(Math.sin(radians) * halfHeight);
      const startX = centerX - Math.cos(radians) * projectedHalfLength;
      const startY = centerY + Math.sin(radians) * projectedHalfLength;
      const endX = centerX + Math.cos(radians) * projectedHalfLength;
      const endY = centerY - Math.sin(radians) * projectedHalfLength;
      const gradient = context.createLinearGradient(startX, startY, endX, endY);
      const stops = parseCanvasGradientStops(parts.slice(1).join(","));
      if (stops.length > 0) {
        const normalizedStops = stops.map((stop, index) => ({
          color: stop.color,
          offset: stop.offset ?? (stops.length === 1 ? 0 : index / (stops.length - 1))
        }));
        normalizedStops.forEach((stop) => {
          gradient.addColorStop(stop.offset, stop.color);
        });
        return gradient;
      }
    }
  }
  const radialMatch = backgroundImage.match(/^radial-gradient\((.*)\)$/i);
  if (radialMatch) {
    const parts = splitCssGradientArgs(radialMatch[1] ?? "");
    const stopParts = parts[0]?.startsWith("circle") ? parts.slice(1) : parts;
    const gradient = context.createRadialGradient(
      rect.left + rect.width / 2,
      rect.top + rect.height / 2,
      0,
      rect.left + rect.width / 2,
      rect.top + rect.height / 2,
      Math.max(rect.width, rect.height) / 2
    );
    const stops = parseCanvasGradientStops(stopParts.join(","));
    if (stops.length > 0) {
      const normalizedStops = stops.map((stop, index) => ({
        color: stop.color,
        offset: stop.offset ?? (stops.length === 1 ? 0 : index / (stops.length - 1))
      }));
      normalizedStops.forEach((stop) => {
        gradient.addColorStop(stop.offset, stop.color);
      });
      return gradient;
    }
  }
  return null;
}
var DATA_BAR_INSET = 2;
var DATA_BAR_GRADIENT_TINT = 0.85;
function resolveCanvasDataBarFill(context, left, top, width, _height, dataBar) {
  if (dataBar.gradient === false) {
    return dataBar.color;
  }
  const gradient = context.createLinearGradient(left, top, left + width, top);
  gradient.addColorStop(0, dataBar.color);
  gradient.addColorStop(1, lightenColor(dataBar.color, DATA_BAR_GRADIENT_TINT));
  return gradient;
}
function drawCanvasConditionalIcon(context, icon, centerX, centerY, size) {
  context.save();
  if (icon.glyph) {
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillStyle = icon.color ?? icon.backgroundColor ?? "#6b7280";
    context.fillText(icon.glyph, centerX, centerY);
    context.restore();
    return;
  }
  if (icon.shape === "arrow") {
    const fill = icon.color ?? "#111827";
    const stroke = icon.borderColor ?? darkenColor(fill, 0.32);
    const scale = size / 16;
    context.translate(centerX, centerY);
    context.rotate((icon.rotationDeg ?? 0) * Math.PI / 180);
    context.translate(-8 * scale, -8 * scale);
    context.beginPath();
    context.moveTo(2.5 * scale, 8 * scale);
    context.lineTo(8.4 * scale, 2.4 * scale);
    context.lineTo(8.4 * scale, 5.2 * scale);
    context.lineTo(13.5 * scale, 5.2 * scale);
    context.lineTo(13.5 * scale, 10.8 * scale);
    context.lineTo(8.4 * scale, 10.8 * scale);
    context.lineTo(8.4 * scale, 13.6 * scale);
    context.closePath();
    context.fillStyle = fill;
    context.fill();
    context.strokeStyle = stroke;
    context.lineWidth = Math.max(1, 1.25 * scale);
    context.lineJoin = "round";
    context.stroke();
    context.restore();
    return;
  }
  context.beginPath();
  context.arc(centerX, centerY, size / 2, 0, Math.PI * 2);
  context.fillStyle = icon.color ?? icon.backgroundColor ?? "#6b7280";
  context.fill();
  context.restore();
}
function formatZoomScale(zoomScale, locale) {
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(zoomScale / 100);
}
function parseRgbColor(color) {
  const match = /^#?([0-9a-f]{6})$/i.exec(color);
  if (!match) {
    return null;
  }
  return {
    blue: Number.parseInt(match[1].slice(4, 6), 16),
    green: Number.parseInt(match[1].slice(2, 4), 16),
    red: Number.parseInt(match[1].slice(0, 2), 16)
  };
}
function mixRgbColor(color, mixWith, ratio) {
  const base = parseRgbColor(color);
  const target = parseRgbColor(mixWith);
  if (!base || !target) {
    return color;
  }
  const clamped = Math.max(0, Math.min(1, ratio));
  const mixChannel = (left, right) => Math.round(left + (right - left) * clamped);
  return `#${[
    mixChannel(base.red, target.red),
    mixChannel(base.green, target.green),
    mixChannel(base.blue, target.blue)
  ].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}
function lightenColor(color, ratio) {
  return mixRgbColor(color, "#ffffff", ratio);
}
function darkenColor(color, ratio) {
  return mixRgbColor(color, "#000000", ratio);
}
var ViewerContext = React15.createContext(null);
var ViewerAppearanceContext = React15.createContext({ isDark: false });
function ReferenceRangeHandles({ color, top = true, bottom = true, left = true, right = true }) {
  return /* @__PURE__ */ jsx11(Fragment11, { children: [top && "top", bottom && "bottom"].flatMap((vertical) => vertical ? [left && "left", right && "right"].map((horizontal) => horizontal ? /* @__PURE__ */ jsx11("span", { style: {
    position: "absolute",
    [vertical]: -4,
    [horizontal]: -4,
    width: 6,
    height: 6,
    backgroundColor: color,
    border: "1px solid white"
  } }, `${vertical}-${horizontal}`) : null) : []) });
}
function resolveDarkModeSurface(themePalette, palette) {
  return "hsl(225 4% 6%)";
}
function resolveSheetSurface(sheet, palette) {
  return paletteIsDark(palette) ? resolveDarkModeSurface(sheet?.themePalette, palette) : sheet?.themePalette.colorsByIndex[0] ?? SHEET_SURFACE;
}
function normalizeRange2(range) {
  return {
    start: {
      col: Math.min(range.start.col, range.end.col),
      row: Math.min(range.start.row, range.end.row)
    },
    end: {
      col: Math.max(range.start.col, range.end.col),
      row: Math.max(range.start.row, range.end.row)
    }
  };
}
function isSameCell(left, right) {
  return Boolean(left && right && left.row === right.row && left.col === right.col);
}
function isCellInRange(cell, range) {
  if (!range) {
    return false;
  }
  const normalized = normalizeRange2(range);
  return cell.row >= normalized.start.row && cell.row <= normalized.end.row && cell.col >= normalized.start.col && cell.col <= normalized.end.col;
}
function buildVisibleAxisIndices(precomputed, displayLimit, maxUsedIndex, hiddenIndices) {
  if (displayLimit <= 0) {
    return [];
  }
  const visible = precomputed.filter((index) => index < displayLimit);
  const appendStart = precomputed.length ? Math.max(0, maxUsedIndex + 1) : 0;
  for (let index = appendStart; index < displayLimit; index++) {
    if (!hiddenIndices?.has(index)) visible.push(index);
  }
  return visible;
}
function resolveAnchoredBounds(anchor) {
  if (anchor.kind === "absolute") {
    return null;
  }
  if (anchor.kind === "one-cell") {
    return {
      maxCol: anchor.from.col,
      maxRow: anchor.from.row,
      minCol: anchor.from.col,
      minRow: anchor.from.row
    };
  }
  return {
    maxCol: Math.max(anchor.from.col, anchor.to.col),
    maxRow: Math.max(anchor.from.row, anchor.to.row),
    minCol: Math.min(anchor.from.col, anchor.to.col),
    minRow: Math.min(anchor.from.row, anchor.to.row)
  };
}
function drawingLayer(zIndex) {
  return Math.round(zIndex * 1024);
}
function clampPercent(value, fallback) {
  if (!Number.isFinite(value)) {
    return fallback;
  }
  return Math.max(0, Math.min(100, value));
}
function resolveShapeAdjustment(shape, name, fallback) {
  const rawValue = shape.geometryAdjustments?.[name];
  if (typeof rawValue !== "number") {
    return fallback;
  }
  return clampPercent(rawValue / 1e3, fallback);
}
function buildClosedPath(points) {
  if (points.length === 0) {
    return "";
  }
  return points.map(([x, y], index) => `${index === 0 ? "M" : "L"} ${x} ${y}`).join(" ") + " Z";
}
function pointOnCircle(radius, angleDeg, center = 50) {
  const radians = angleDeg * (Math.PI / 180);
  return [
    center + Math.cos(radians) * radius,
    center + Math.sin(radians) * radius
  ];
}
function buildRegularPolygonPath(sides, rotationDeg = -90, radius = 50) {
  return buildClosedPath(
    Array.from({ length: sides }, (_, index) => pointOnCircle(radius, rotationDeg + 360 / sides * index))
  );
}
function buildStarPath(points, innerRadius, rotationDeg = -90, outerRadius = 50) {
  return buildClosedPath(
    Array.from({ length: points * 2 }, (_, index) => {
      const radius = index % 2 === 0 ? outerRadius : innerRadius;
      return pointOnCircle(radius, rotationDeg + 360 / (points * 2) * index);
    })
  );
}
function buildRoundRectPath(radius) {
  const cornerRadius = Math.max(0, Math.min(50, radius));
  const edge = 100 - cornerRadius;
  return [
    `M ${cornerRadius} 0`,
    `L ${edge} 0`,
    `Q 100 0 100 ${cornerRadius}`,
    `L 100 ${edge}`,
    `Q 100 100 ${edge} 100`,
    `L ${cornerRadius} 100`,
    `Q 0 100 0 ${edge}`,
    `L 0 ${cornerRadius}`,
    `Q 0 0 ${cornerRadius} 0`,
    "Z"
  ].join(" ");
}
function buildEllipsePath() {
  return "M 50 0 A 50 50 0 1 1 49.999 0 Z";
}
function buildPiePath(startAngleDeg, endAngleDeg) {
  const [startX, startY] = pointOnCircle(50, startAngleDeg);
  const [endX, endY] = pointOnCircle(50, endAngleDeg);
  const sweep = endAngleDeg >= startAngleDeg ? endAngleDeg - startAngleDeg : 360 - (startAngleDeg - endAngleDeg);
  const largeArcFlag = sweep > 180 ? 1 : 0;
  return [
    "M 50 50",
    `L ${startX} ${startY}`,
    `A 50 50 0 ${largeArcFlag} 1 ${endX} ${endY}`,
    "Z"
  ].join(" ");
}
function buildChordPath(startAngleDeg, endAngleDeg) {
  const [startX, startY] = pointOnCircle(50, startAngleDeg);
  const [endX, endY] = pointOnCircle(50, endAngleDeg);
  const sweep = endAngleDeg >= startAngleDeg ? endAngleDeg - startAngleDeg : 360 - (startAngleDeg - endAngleDeg);
  const largeArcFlag = sweep > 180 ? 1 : 0;
  return [
    `M ${startX} ${startY}`,
    `A 50 50 0 ${largeArcFlag} 1 ${endX} ${endY}`,
    "Z"
  ].join(" ");
}
function buildPlusPath(thickness) {
  const arm = Math.max(10, Math.min(40, thickness));
  const inner = 50 - arm / 2;
  const outer = 50 + arm / 2;
  return buildClosedPath([
    [inner, 0],
    [outer, 0],
    [outer, inner],
    [100, inner],
    [100, outer],
    [outer, outer],
    [outer, 100],
    [inner, 100],
    [inner, outer],
    [0, outer],
    [0, inner],
    [inner, inner]
  ]);
}
function buildPentagonArrowPath() {
  return buildClosedPath([
    [0, 20],
    [70, 20],
    [70, 0],
    [100, 50],
    [70, 100],
    [70, 80],
    [0, 80]
  ]);
}
function buildChevronArrowPath() {
  return buildClosedPath([
    [0, 20],
    [54, 20],
    [54, 0],
    [100, 50],
    [54, 100],
    [54, 80],
    [0, 80],
    [32, 50]
  ]);
}
function buildNotchedRightArrowPath(shape) {
  const headLength = resolveShapeAdjustment(shape, "adj2", 36);
  const shaftHalf = resolveShapeAdjustment(shape, "adj1", 20);
  const notchDepth = Math.min(24, headLength * 0.7);
  const bodyTop = 50 - shaftHalf;
  const bodyBottom = 50 + shaftHalf;
  const headStart = 100 - headLength;
  return buildClosedPath([
    [0, bodyTop],
    [headStart, bodyTop],
    [headStart, 0],
    [100, 50],
    [headStart, 100],
    [headStart, bodyBottom],
    [notchDepth, bodyBottom],
    [0, 50],
    [notchDepth, bodyTop]
  ]);
}
function buildStripedRightArrowPath(shape) {
  const headLength = resolveShapeAdjustment(shape, "adj2", 34);
  const shaftHalf = resolveShapeAdjustment(shape, "adj1", 20);
  const stripeWidth = 12;
  const bodyTop = 50 - shaftHalf;
  const bodyBottom = 50 + shaftHalf;
  const headStart = 100 - headLength;
  return [
    `M 0 ${bodyTop} L ${stripeWidth} ${bodyTop} L ${stripeWidth} ${bodyBottom} L 0 ${bodyBottom} Z`,
    buildClosedPath([
      [stripeWidth * 1.6, bodyTop],
      [headStart, bodyTop],
      [headStart, 0],
      [100, 50],
      [headStart, 100],
      [headStart, bodyBottom],
      [stripeWidth * 1.6, bodyBottom]
    ])
  ].join(" ");
}
function buildLeftUpArrowPath(shape) {
  const stemWidth = resolveShapeAdjustment(shape, "adj1", 28);
  const headLength = resolveShapeAdjustment(shape, "adj2", 34);
  return buildClosedPath([
    [100, 100 - stemWidth],
    [stemWidth, 100 - stemWidth],
    [stemWidth, 100],
    [0, 50],
    [stemWidth, 0],
    [stemWidth, headLength],
    [100, headLength]
  ]);
}
function buildBentUpArrowPath(shape) {
  const stemWidth = resolveShapeAdjustment(shape, "adj1", 26);
  const headLength = resolveShapeAdjustment(shape, "adj2", 28);
  const shaftHalf = resolveShapeAdjustment(shape, "adj3", 12);
  const verticalCenter = 50;
  const bodyTop = verticalCenter - shaftHalf;
  const bodyBottom = verticalCenter + shaftHalf;
  return buildClosedPath([
    [0, bodyTop],
    [100 - stemWidth, bodyTop],
    [100 - stemWidth, headLength],
    [100 - stemWidth * 0.5, headLength],
    [100, 0],
    [100 - stemWidth * 1.5, headLength],
    [100 - stemWidth, headLength],
    [100 - stemWidth, 100],
    [100 - stemWidth * 2, 100],
    [100 - stemWidth * 2, bodyBottom],
    [0, bodyBottom]
  ]);
}
function buildUturnArrowPath(shape) {
  const stemWidth = resolveShapeAdjustment(shape, "adj1", 22);
  const headLength = resolveShapeAdjustment(shape, "adj2", 28);
  return buildClosedPath([
    [100, 100],
    [100, 55],
    [45, 55],
    [45, 100],
    [0, 50],
    [45, 0],
    [45, 45],
    [100 - stemWidth, 45],
    [100 - stemWidth, 100]
  ]);
}
function buildLeftRightUpArrowPath(shape) {
  const headLength = resolveShapeAdjustment(shape, "adj2", 22);
  const shaftHalf = resolveShapeAdjustment(shape, "adj1", 16);
  const bodyTop = 50 - shaftHalf;
  const bodyBottom = 50 + shaftHalf;
  const bodyLeft = 50 - shaftHalf;
  const bodyRight = 50 + shaftHalf;
  return buildClosedPath([
    [headLength, bodyTop],
    [bodyLeft, bodyTop],
    [bodyLeft, headLength],
    [0, headLength],
    [50, 0],
    [100, headLength],
    [bodyRight, headLength],
    [bodyRight, bodyTop],
    [100 - headLength, bodyTop],
    [100 - headLength, 0],
    [100, 50],
    [100 - headLength, 100],
    [100 - headLength, bodyBottom],
    [headLength, bodyBottom],
    [headLength, 100],
    [0, 50],
    [headLength, 0]
  ]);
}
function buildQuadArrowPath(shape) {
  const headLength = resolveShapeAdjustment(shape, "adj2", 22);
  const shaftHalf = resolveShapeAdjustment(shape, "adj1", 14);
  const bodyLeft = 50 - shaftHalf;
  const bodyRight = 50 + shaftHalf;
  const bodyTop = 50 - shaftHalf;
  const bodyBottom = 50 + shaftHalf;
  return buildClosedPath([
    [bodyLeft, headLength],
    [headLength, headLength],
    [headLength, bodyTop],
    [0, 50],
    [headLength, 100 - bodyTop],
    [headLength, bodyBottom],
    [bodyLeft, bodyBottom],
    [bodyLeft, 100 - headLength],
    [bodyTop, 100 - headLength],
    [50, 100],
    [100 - bodyTop, 100 - headLength],
    [bodyRight, 100 - headLength],
    [bodyRight, bodyBottom],
    [100 - headLength, bodyBottom],
    [100 - headLength, 100 - bodyTop],
    [100, 50],
    [100 - headLength, bodyTop],
    [100 - headLength, headLength],
    [bodyRight, headLength],
    [bodyRight, bodyTop],
    [100 - bodyTop, headLength],
    [50, 0],
    [bodyTop, headLength],
    [bodyLeft, headLength]
  ]);
}
function buildHeartPath() {
  return [
    "M 50 92",
    "C 18 72 0 52 0 28",
    "C 0 10 14 0 28 0",
    "C 38 0 46 6 50 16",
    "C 54 6 62 0 72 0",
    "C 86 0 100 10 100 28",
    "C 100 52 82 72 50 92",
    "Z"
  ].join(" ");
}
function buildLightningBoltPath() {
  return buildClosedPath([
    [42, 0],
    [10, 58],
    [38, 58],
    [24, 100],
    [90, 36],
    [58, 36],
    [72, 0]
  ]);
}
function buildTeardropPath() {
  return [
    "M 50 0",
    "C 20 24 0 44 0 68",
    "C 0 86 14 100 32 100",
    "C 60 100 82 78 82 50",
    "C 82 26 68 10 50 0",
    "Z"
  ].join(" ");
}
function buildCloudPath() {
  return [
    "M 22 70",
    "C 8 70 0 62 0 50",
    "C 0 40 6 32 18 30",
    "C 20 16 30 8 44 8",
    "C 54 8 62 12 68 20",
    "C 72 14 80 12 88 14",
    "C 98 18 100 26 100 34",
    "C 100 44 94 50 88 52",
    "C 92 66 82 76 68 76",
    "C 62 84 52 88 42 88",
    "C 32 88 24 82 22 70",
    "Z"
  ].join(" ");
}
function buildRightArrowPath(shape) {
  const headLength = resolveShapeAdjustment(shape, "adj2", 38);
  const shaftHalf = resolveShapeAdjustment(shape, "adj1", 20);
  const bodyTop = 50 - shaftHalf;
  const bodyBottom = 50 + shaftHalf;
  const headStart = 100 - headLength;
  return buildClosedPath([
    [0, bodyTop],
    [headStart, bodyTop],
    [headStart, 0],
    [100, 50],
    [headStart, 100],
    [headStart, bodyBottom],
    [0, bodyBottom]
  ]);
}
function buildLeftArrowPath(shape) {
  const headLength = resolveShapeAdjustment(shape, "adj2", 38);
  const shaftHalf = resolveShapeAdjustment(shape, "adj1", 20);
  const bodyTop = 50 - shaftHalf;
  const bodyBottom = 50 + shaftHalf;
  const headEnd = headLength;
  return buildClosedPath([
    [100, bodyTop],
    [headEnd, bodyTop],
    [headEnd, 0],
    [0, 50],
    [headEnd, 100],
    [headEnd, bodyBottom],
    [100, bodyBottom]
  ]);
}
function buildUpArrowPath(shape) {
  const headLength = resolveShapeAdjustment(shape, "adj2", 38);
  const shaftHalf = resolveShapeAdjustment(shape, "adj1", 20);
  const bodyLeft = 50 - shaftHalf;
  const bodyRight = 50 + shaftHalf;
  const headEnd = headLength;
  return buildClosedPath([
    [bodyLeft, 100],
    [bodyLeft, headEnd],
    [0, headEnd],
    [50, 0],
    [100, headEnd],
    [bodyRight, headEnd],
    [bodyRight, 100]
  ]);
}
function buildDownArrowPath(shape) {
  const headLength = resolveShapeAdjustment(shape, "adj2", 38);
  const shaftHalf = resolveShapeAdjustment(shape, "adj1", 20);
  const bodyLeft = 50 - shaftHalf;
  const bodyRight = 50 + shaftHalf;
  const headStart = 100 - headLength;
  return buildClosedPath([
    [bodyLeft, 0],
    [bodyLeft, headStart],
    [0, headStart],
    [50, 100],
    [100, headStart],
    [bodyRight, headStart],
    [bodyRight, 0]
  ]);
}
function buildLeftRightArrowPath(shape) {
  const headLength = resolveShapeAdjustment(shape, "adj2", 24);
  const shaftHalf = resolveShapeAdjustment(shape, "adj1", 18);
  const bodyTop = 50 - shaftHalf;
  const bodyBottom = 50 + shaftHalf;
  return buildClosedPath([
    [headLength, bodyTop],
    [100 - headLength, bodyTop],
    [100 - headLength, 0],
    [100, 50],
    [100 - headLength, 100],
    [100 - headLength, bodyBottom],
    [headLength, bodyBottom],
    [headLength, 100],
    [0, 50],
    [headLength, 0]
  ]);
}
function buildUpDownArrowPath(shape) {
  const headLength = resolveShapeAdjustment(shape, "adj2", 24);
  const shaftHalf = resolveShapeAdjustment(shape, "adj1", 18);
  const bodyLeft = 50 - shaftHalf;
  const bodyRight = 50 + shaftHalf;
  return buildClosedPath([
    [bodyLeft, headLength],
    [bodyLeft, 100 - headLength],
    [0, 100 - headLength],
    [50, 100],
    [100, 100 - headLength],
    [bodyRight, 100 - headLength],
    [bodyRight, headLength],
    [100, headLength],
    [50, 0],
    [0, headLength]
  ]);
}
function buildBentArrowPath(shape) {
  const stemWidth = resolveShapeAdjustment(shape, "adj1", 25);
  const headLength = resolveShapeAdjustment(shape, "adj2", 27);
  const shaftHalf = resolveShapeAdjustment(shape, "adj3", 12.5);
  const bendY = resolveShapeAdjustment(shape, "adj4", 43.75);
  const bodyTop = bendY - shaftHalf;
  const bodyBottom = bendY + shaftHalf;
  const headStart = 100 - headLength;
  return buildClosedPath([
    [0, bodyTop],
    [headStart, bodyTop],
    [headStart, 0],
    [100, bendY],
    [headStart, 100],
    [headStart, bodyBottom],
    [stemWidth, bodyBottom],
    [stemWidth, 100],
    [0, 100]
  ]);
}
function buildPresetShapePath(shape) {
  switch (shape.geometry) {
    case "arc":
      return {
        path: "M 8 74 C 18 24 82 24 92 74",
        viewBox: { width: 100, height: 100 }
      };
    case "bentArrow":
      return {
        path: buildBentArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "bentUpArrow":
      return {
        path: buildBentUpArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "blockArc":
      return {
        path: "M 12 78 A 38 38 0 1 1 78 12 L 62 28 A 16 16 0 1 0 28 62 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "can":
      return {
        path: "M 18 14 C 18 6 82 6 82 14 L 82 86 C 82 94 18 94 18 86 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "chevron":
      return {
        path: "M 0 0 L 62 0 L 100 50 L 62 100 L 0 100 L 38 50 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "chevronArrow":
      return {
        path: buildChevronArrowPath(),
        viewBox: { width: 100, height: 100 }
      };
    case "chord":
      return {
        path: buildChordPath(-30, 210),
        viewBox: { width: 100, height: 100 }
      };
    case "cloud":
    case "cloudCallout":
      return {
        path: buildCloudPath(),
        viewBox: { width: 100, height: 100 }
      };
    case "diamond":
    case "flowChartDecision":
      return {
        path: "M 50 0 L 100 50 L 50 100 L 0 50 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "downArrow":
      return {
        path: buildDownArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "line":
      return {
        path: "M 0 0 L 100 100",
        viewBox: { width: 100, height: 100 }
      };
    case "ellipse":
    case "flowChartTerminator":
      return {
        path: buildEllipsePath(),
        viewBox: { width: 100, height: 100 }
      };
    case "flowChartAlternateProcess":
    case "flowChartDelay":
    case "roundRect":
      return {
        path: buildRoundRectPath(resolveShapeAdjustment(shape, "adj", 18)),
        viewBox: { width: 100, height: 100 }
      };
    case "flowChartCollate":
      return {
        path: "M 0 0 L 100 0 L 0 100 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "flowChartData":
    case "flowChartInputOutput":
      return {
        path: "M 24 0 L 100 0 L 76 100 L 0 100 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "flowChartDocument":
      return {
        path: "M 0 0 L 100 0 L 100 82 C 78 70 60 94 40 82 C 24 72 12 88 0 82 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "flowChartMagneticDisk":
      return {
        path: "M 18 14 C 18 6 82 6 82 14 L 82 86 C 82 94 18 94 18 86 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "flowChartManualInput":
      return {
        path: "M 16 0 L 100 0 L 84 100 L 0 100 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "flowChartPreparation":
    case "hexagon":
      return {
        path: "M 25 0 L 75 0 L 100 50 L 75 100 L 25 100 L 0 50 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "flowChartProcess":
    case "rect":
      return {
        path: "M 0 0 L 100 0 L 100 100 L 0 100 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "heart":
      return {
        path: buildHeartPath(),
        viewBox: { width: 100, height: 100 }
      };
    case "heptagon":
      return {
        path: buildRegularPolygonPath(7),
        viewBox: { width: 100, height: 100 }
      };
    case "homePlate":
    case "flowChartOffpageConnector":
      return {
        path: "M 0 0 L 70 0 L 100 50 L 70 100 L 0 100 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "leftArrow":
      return {
        path: buildLeftArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "leftBracket":
      return {
        path: "M 72 0 L 28 0 L 28 100 L 72 100",
        viewBox: { width: 100, height: 100 }
      };
    case "leftBrace":
      return {
        path: "M 82 0 C 46 0 52 24 52 38 C 52 46 46 50 24 50 C 46 50 52 54 52 62 C 52 76 46 100 82 100",
        viewBox: { width: 100, height: 100 }
      };
    case "leftRightArrowCallout":
      return {
        path: buildLeftRightArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "leftRightArrow":
      return {
        path: buildLeftRightArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "leftRightUpArrow":
      return {
        path: buildLeftRightUpArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "leftUpArrow":
      return {
        path: buildLeftUpArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "lightningBolt":
      return {
        path: buildLightningBoltPath(),
        viewBox: { width: 100, height: 100 }
      };
    case "mathPlus":
    case "plus":
      return {
        path: buildPlusPath(resolveShapeAdjustment(shape, "adj", 26)),
        viewBox: { width: 100, height: 100 }
      };
    case "cross":
      return {
        path: buildPlusPath(resolveShapeAdjustment(shape, "adj", 22)),
        viewBox: { width: 100, height: 100 }
      };
    case "mathMinus":
    case "minus":
      return {
        path: "M 0 40 L 100 40 L 100 60 L 0 60 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "mathMultiply":
    case "multiply":
      return {
        path: "M 18 0 L 50 32 L 82 0 L 100 18 L 68 50 L 100 82 L 82 100 L 50 68 L 18 100 L 0 82 L 32 50 L 0 18 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "mathDivide":
      return {
        path: "M 0 42 L 100 42 L 100 58 L 0 58 Z M 50 12 A 8 8 0 1 1 49.999 12 Z M 50 88 A 8 8 0 1 1 49.999 88 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "moon":
      return {
        path: "M 70 6 C 42 10 22 34 22 62 C 22 80 32 94 48 100 C 20 98 0 76 0 48 C 0 20 20 0 48 0 C 56 0 64 2 70 6 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "notchedRightArrow":
      return {
        path: buildNotchedRightArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "octagon":
      return {
        path: "M 30 0 L 70 0 L 100 30 L 100 70 L 70 100 L 30 100 L 0 70 L 0 30 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "parallelogram":
      return {
        path: "M 24 0 L 100 0 L 76 100 L 0 100 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "pentagon":
      return {
        path: "M 50 0 L 100 38 L 81 100 L 19 100 L 0 38 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "pie":
    case "pieWedge":
      return {
        path: buildPiePath(-35, 225),
        viewBox: { width: 100, height: 100 }
      };
    case "pentagonArrow":
      return {
        path: buildPentagonArrowPath(),
        viewBox: { width: 100, height: 100 }
      };
    case "plaque":
      return {
        path: "M 12 0 L 88 0 L 100 12 L 100 88 L 88 100 L 12 100 L 0 88 L 0 12 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "quadArrow":
      return {
        path: buildQuadArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "rightArrow":
      return {
        path: buildRightArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "rightArrowCallout":
      return {
        path: "M 0 18 L 62 18 L 62 0 L 100 50 L 62 100 L 62 82 L 0 82 L 0 18 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "rightBracket":
      return {
        path: "M 28 0 L 72 0 L 72 100 L 28 100",
        viewBox: { width: 100, height: 100 }
      };
    case "downArrowCallout":
      return {
        path: "M 18 0 L 82 0 L 82 58 L 100 58 L 50 100 L 0 58 L 18 58 L 18 0 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "rightBrace":
      return {
        path: "M 18 0 C 54 0 48 24 48 38 C 48 46 54 50 76 50 C 54 50 48 54 48 62 C 48 76 54 100 18 100",
        viewBox: { width: 100, height: 100 }
      };
    case "round1Rect":
      return {
        path: "M 18 0 L 100 0 L 100 100 L 18 100 Q 0 100 0 82 L 0 18 Q 0 0 18 0 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "round2DiagRect":
      return {
        path: "M 18 0 L 100 0 L 100 82 Q 100 100 82 100 L 0 100 L 0 18 Q 0 0 18 0 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "round2SameRect":
      return {
        path: "M 18 0 L 82 0 Q 100 0 100 18 L 100 82 Q 100 100 82 100 L 0 100 L 0 0 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "decagon":
      return {
        path: buildRegularPolygonPath(10),
        viewBox: { width: 100, height: 100 }
      };
    case "dodecagon":
      return {
        path: buildRegularPolygonPath(12),
        viewBox: { width: 100, height: 100 }
      };
    case "rtTriangle":
      return {
        path: "M 0 0 L 100 100 L 0 100 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "star4":
      return {
        path: buildStarPath(4, 20),
        viewBox: { width: 100, height: 100 }
      };
    case "star5":
      return {
        path: buildStarPath(5, 21),
        viewBox: { width: 100, height: 100 }
      };
    case "star6":
      return {
        path: buildStarPath(6, 23),
        viewBox: { width: 100, height: 100 }
      };
    case "star7":
      return {
        path: buildStarPath(7, 24),
        viewBox: { width: 100, height: 100 }
      };
    case "star8":
      return {
        path: buildStarPath(8, 25),
        viewBox: { width: 100, height: 100 }
      };
    case "star10":
      return {
        path: buildStarPath(10, 26),
        viewBox: { width: 100, height: 100 }
      };
    case "star12":
      return {
        path: buildStarPath(12, 26),
        viewBox: { width: 100, height: 100 }
      };
    case "star16":
      return {
        path: buildStarPath(16, 27),
        viewBox: { width: 100, height: 100 }
      };
    case "star24":
      return {
        path: buildStarPath(24, 28),
        viewBox: { width: 100, height: 100 }
      };
    case "star32":
      return {
        path: buildStarPath(32, 29),
        viewBox: { width: 100, height: 100 }
      };
    case "stripedRightArrow":
      return {
        path: buildStripedRightArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "sun":
      return {
        path: buildStarPath(12, 36),
        viewBox: { width: 100, height: 100 }
      };
    case "teardrop":
      return {
        path: buildTeardropPath(),
        viewBox: { width: 100, height: 100 }
      };
    case "triangle":
      return {
        path: "M 50 0 L 100 100 L 0 100 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "trapezoid":
      return {
        path: "M 20 0 L 80 0 L 100 100 L 0 100 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "upArrow":
      return {
        path: buildUpArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "upArrowCallout":
      return {
        path: "M 50 0 L 100 42 L 82 42 L 82 100 L 18 100 L 18 42 L 0 42 L 50 0 Z",
        viewBox: { width: 100, height: 100 }
      };
    case "upDownArrow":
      return {
        path: buildUpDownArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "upDownArrowCallout":
      return {
        path: buildUpDownArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    case "uturnArrow":
      return {
        path: buildUturnArrowPath(shape),
        viewBox: { width: 100, height: 100 }
      };
    default:
      return null;
  }
}
function resolveShapeVector(shape) {
  if (shape.svgPath && shape.svgViewBox) {
    return {
      path: shape.svgPath,
      viewBox: shape.svgViewBox
    };
  }
  return buildPresetShapePath(shape);
}
function drawCanvasRoundedRect(context, left, top, width, height, radius) {
  const safeRadius = Math.max(0, Math.min(radius, width / 2, height / 2));
  context.beginPath();
  context.moveTo(left + safeRadius, top);
  context.lineTo(left + width - safeRadius, top);
  context.quadraticCurveTo(left + width, top, left + width, top + safeRadius);
  context.lineTo(left + width, top + height - safeRadius);
  context.quadraticCurveTo(left + width, top + height, left + width - safeRadius, top + height);
  context.lineTo(left + safeRadius, top + height);
  context.quadraticCurveTo(left, top + height, left, top + height - safeRadius);
  context.lineTo(left, top + safeRadius);
  context.quadraticCurveTo(left, top, left + safeRadius, top);
  context.closePath();
}
function applyCanvasShapeDash(context, dash, lineWidth) {
  if (!dash) {
    context.setLineDash([]);
    return;
  }
  const unit = Math.max(1, lineWidth);
  switch (dash) {
    case "dash":
      context.setLineDash([4 * unit, 3 * unit]);
      break;
    case "dashDot":
      context.setLineDash([4 * unit, 2 * unit, unit, 2 * unit]);
      break;
    case "dot":
      context.setLineDash([unit, 2 * unit]);
      break;
    case "lgDash":
      context.setLineDash([8 * unit, 3 * unit]);
      break;
    default:
      context.setLineDash([]);
      break;
  }
}
function useViewerPalette(isDark = false, headerBackgroundColor, headerTextColor) {
  return React15.useMemo(
    () => resolveViewerPalette(isDark, headerBackgroundColor, headerTextColor),
    [headerBackgroundColor, headerTextColor, isDark]
  );
}
function normalizeThumbnailResolution(resolution) {
  if (typeof resolution === "number" && Number.isFinite(resolution) && resolution > 0) {
    return {
      maxHeight: resolution,
      maxWidth: resolution
    };
  }
  const resolvedObject = typeof resolution === "object" && resolution ? resolution : void 0;
  return {
    maxHeight: resolvedObject?.maxHeight && Number.isFinite(resolvedObject.maxHeight) && resolvedObject.maxHeight > 0 ? resolvedObject.maxHeight : THUMBNAIL_DEFAULT_MAX_DIMENSION,
    maxWidth: resolvedObject?.maxWidth && Number.isFinite(resolvedObject.maxWidth) && resolvedObject.maxWidth > 0 ? resolvedObject.maxWidth : THUMBNAIL_DEFAULT_MAX_DIMENSION
  };
}
function resolveThumbnailOutputSize(sourceWidth, sourceHeight, resolution) {
  const normalized = normalizeThumbnailResolution(resolution);
  const safeSourceWidth = Math.max(1, sourceWidth);
  const safeSourceHeight = Math.max(1, sourceHeight);
  const scale = Math.min(
    normalized.maxWidth / safeSourceWidth,
    normalized.maxHeight / safeSourceHeight,
    1
  );
  return {
    height: Math.max(1, Math.round(safeSourceHeight * scale)),
    maxHeight: normalized.maxHeight,
    maxWidth: normalized.maxWidth,
    scale,
    width: Math.max(1, Math.round(safeSourceWidth * scale))
  };
}
function resolveThumbnailAxisIndices({
  fallbackCount,
  getSizePx,
  maxCount,
  maxLogicalPixels,
  maxUsedIndex,
  minUsedIndex,
  precomputed
}) {
  const sourceIndices = precomputed.length > 0 ? precomputed : Array.from({
    length: Math.max(fallbackCount, Math.max(0, maxUsedIndex + 1))
  }, (_, index) => index);
  const hasUsedRange = maxUsedIndex >= minUsedIndex && maxUsedIndex >= 0;
  const preferredStart = hasUsedRange ? Math.max(0, minUsedIndex) : 0;
  const preferredEnd = hasUsedRange ? maxUsedIndex : Math.max(0, preferredStart + fallbackCount - 1);
  const picked = [];
  let totalSize = 0;
  for (const actualIndex of sourceIndices) {
    if (actualIndex < preferredStart) {
      continue;
    }
    if (hasUsedRange && actualIndex > preferredEnd) {
      break;
    }
    const size = Math.max(1, getSizePx(actualIndex));
    picked.push(actualIndex);
    totalSize += size;
    if (picked.length >= maxCount || totalSize >= maxLogicalPixels) {
      break;
    }
  }
  if (picked.length > 0) {
    return picked;
  }
  for (const actualIndex of sourceIndices) {
    const size = Math.max(1, getSizePx(actualIndex));
    picked.push(actualIndex);
    totalSize += size;
    if (picked.length >= fallbackCount || picked.length >= maxCount || totalSize >= maxLogicalPixels) {
      break;
    }
  }
  return picked.length > 0 ? picked : [0];
}
function buildThumbnailAxisItems(actualIndices, getSizePx) {
  const items = [];
  let offset = 0;
  for (const actualIndex of actualIndices) {
    const size = Math.max(1, getSizePx(actualIndex));
    items.push({
      actualIndex,
      size,
      start: offset
    });
    offset += size;
  }
  return {
    items,
    totalSize: offset
  };
}
function resolveThumbnailAxisAbsoluteOffset(actualIndices, getSizePx, actualIndex) {
  let total = 0;
  for (const candidate of actualIndices) {
    if (candidate >= actualIndex) {
      break;
    }
    total += Math.max(1, getSizePx(candidate));
  }
  return total;
}
function resolveThumbnailAxisMarkerOffset({
  actualIndex,
  actualIndices,
  getSizePx,
  offsetEmu,
  previewStartActualIndex
}) {
  return resolveThumbnailAxisAbsoluteOffset(actualIndices, getSizePx, actualIndex) - resolveThumbnailAxisAbsoluteOffset(actualIndices, getSizePx, previewStartActualIndex) + emuToPixels(offsetEmu);
}
function resolveThumbnailAnchoredRect(anchor, visibleRows, visibleCols, getRowHeightPx, getColWidthPx, previewRows, previewCols, options2) {
  const previewStartRow = previewRows[0] ?? 0;
  const previewStartCol = previewCols[0] ?? 0;
  const previewOriginX = resolveThumbnailAxisAbsoluteOffset(visibleCols, getColWidthPx, previewStartCol);
  const previewOriginY = resolveThumbnailAxisAbsoluteOffset(visibleRows, getRowHeightPx, previewStartRow);
  const resolveMarkerLeft = (col, colOffsetEmu) => options2.rowHeaderWidth + resolveThumbnailAxisMarkerOffset({
    actualIndex: col,
    actualIndices: visibleCols,
    getSizePx: getColWidthPx,
    offsetEmu: colOffsetEmu,
    previewStartActualIndex: previewStartCol
  });
  const resolveMarkerTop = (row2, rowOffsetEmu) => options2.headerHeight + resolveThumbnailAxisMarkerOffset({
    actualIndex: row2,
    actualIndices: visibleRows,
    getSizePx: getRowHeightPx,
    offsetEmu: rowOffsetEmu,
    previewStartActualIndex: previewStartRow
  });
  if (anchor.kind === "absolute") {
    return {
      height: Math.max(1, emuToPixels(anchor.sizeEmu.cy)),
      left: options2.rowHeaderWidth + emuToPixels(anchor.positionEmu.x) - previewOriginX,
      top: options2.headerHeight + emuToPixels(anchor.positionEmu.y) - previewOriginY,
      width: Math.max(1, emuToPixels(anchor.sizeEmu.cx))
    };
  }
  if (anchor.kind === "one-cell") {
    return {
      height: Math.max(1, emuToPixels(anchor.sizeEmu.cy)),
      left: resolveMarkerLeft(anchor.from.col, anchor.from.colOffsetEmu),
      top: resolveMarkerTop(anchor.from.row, anchor.from.rowOffsetEmu),
      width: Math.max(1, emuToPixels(anchor.sizeEmu.cx))
    };
  }
  const left = resolveMarkerLeft(anchor.from.col, anchor.from.colOffsetEmu);
  const top = resolveMarkerTop(anchor.from.row, anchor.from.rowOffsetEmu);
  const right = resolveMarkerLeft(anchor.to.col, anchor.to.colOffsetEmu);
  const bottom = resolveMarkerTop(anchor.to.row, anchor.to.rowOffsetEmu);
  return {
    height: Math.max(1, bottom - top),
    left,
    top,
    width: Math.max(1, right - left)
  };
}
function columnLabel2(col) {
  let label = "";
  let nextValue = col;
  while (nextValue >= 0) {
    label = String.fromCharCode(65 + nextValue % 26) + label;
    nextValue = Math.floor(nextValue / 26) - 1;
  }
  return label;
}
function cellAddressToA12(cell) {
  return `${columnLabel2(cell.col)}${cell.row + 1}`;
}
function parseA1CellReference2(reference) {
  const match = /^([A-Z]+)(\d+)$/i.exec(reference.trim());
  if (!match) {
    return null;
  }
  const [, columnPart, rowPart] = match;
  let col = 0;
  for (const char of columnPart.toUpperCase()) {
    col = col * 26 + (char.charCodeAt(0) - 64);
  }
  return {
    col: col - 1,
    row: Number(rowPart) - 1
  };
}
function resolveInheritedCellStyle2(sheet, row2, col) {
  if (!sheet) {
    return null;
  }
  const colStyleId = sheet.colStyleIds[col];
  const rowStyleId = sheet.rowStyleIds[row2];
  const colStyle = colStyleId !== void 0 ? sheet.styleById[colStyleId] ?? null : null;
  const rowStyle = rowStyleId !== void 0 ? sheet.styleById[rowStyleId] ?? null : null;
  return mergeResolvedCellStyle(colStyle, rowStyle, { replaceXfSubtrees: true });
}
function decodeHtmlEntities2(value) {
  return value.replace(/&quot;/g, '"').replace(/&#34;/g, '"').replace(/&apos;/g, "'").replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}
function mapBorder2(edge, themePalette) {
  const color = resolveWorkbookColor(edge.color, themePalette) ?? "#000";
  const widthMap = {
    dashed: "1px",
    dotted: "1px",
    double: "3px",
    hair: "0.5px",
    medium: "2px",
    thick: "3px",
    thin: "1px"
  };
  const styleMap = {
    dashDot: "dashed",
    dashDotDot: "dotted",
    dashed: "dashed",
    dotted: "dotted",
    double: "double",
    hair: "solid",
    medium: "solid",
    mediumDashDot: "dashed",
    mediumDashDotDot: "dotted",
    mediumDashed: "dashed",
    slantDashDot: "dashed",
    thick: "solid",
    thin: "solid"
  };
  return `${widthMap[edge.style] ?? "1px"} ${styleMap[edge.style] ?? "solid"} ${color}`;
}
function paletteIsDark(palette) {
  return isDarkViewerPalette(palette);
}
function parseHexColor(color) {
  const normalized = color.trim().toLowerCase();
  const hexMatch = /^#([0-9a-f]{6})$/.exec(normalized);
  if (hexMatch) {
    const hex = hexMatch[1];
    return [
      Number.parseInt(hex.slice(0, 2), 16),
      Number.parseInt(hex.slice(2, 4), 16),
      Number.parseInt(hex.slice(4, 6), 16)
    ];
  }
  const rgbMatch = /^rgb\(\s*(\d{1,3})\s*[,\s]\s*(\d{1,3})\s*[,\s]\s*(\d{1,3})\s*\)$/.exec(normalized);
  if (rgbMatch) {
    return [
      Math.max(0, Math.min(255, Number.parseInt(rgbMatch[1], 10))),
      Math.max(0, Math.min(255, Number.parseInt(rgbMatch[2], 10))),
      Math.max(0, Math.min(255, Number.parseInt(rgbMatch[3], 10)))
    ];
  }
  const hslMatch = /^hsl\(\s*(-?\d+(?:\.\d+)?)\s*(?:deg)?(?:\s+|,\s*)(\d+(?:\.\d+)?)%(?:\s+|,\s*)(\d+(?:\.\d+)?)%\s*\)$/.exec(normalized);
  if (!hslMatch) {
    return null;
  }
  const hue = (Number.parseFloat(hslMatch[1]) % 360 + 360) % 360 / 360;
  const saturation = Math.max(0, Math.min(1, Number.parseFloat(hslMatch[2]) / 100));
  const lightness = Math.max(0, Math.min(1, Number.parseFloat(hslMatch[3]) / 100));
  return hslToRgb(hue, saturation, lightness);
}
function relativeLuminance(color) {
  const rgb = parseHexColor(color);
  if (!rgb) {
    return null;
  }
  const [red, green, blue] = rgb.map((channel) => {
    const normalized = channel / 255;
    return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}
function contrastRatio(foreground, background) {
  const foregroundLuminance = relativeLuminance(foreground);
  const backgroundLuminance = relativeLuminance(background);
  if (foregroundLuminance === null || backgroundLuminance === null) {
    return null;
  }
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}
function resolveReadableTextColor(requestedColor, backgroundColor, palette) {
  if (!paletteIsDark(palette)) {
    return requestedColor ?? "#000000";
  }
  if (!requestedColor) {
    return palette.text;
  }
  const requestedContrast = contrastRatio(requestedColor, backgroundColor);
  const paletteContrast = contrastRatio(palette.text, backgroundColor);
  if (requestedContrast !== null && requestedContrast >= 4.5) {
    return requestedColor;
  }
  if (paletteContrast !== null && (requestedContrast === null || paletteContrast > requestedContrast)) {
    return palette.text;
  }
  return requestedColor;
}
function hueToRgb(p, q, t) {
  let nextT = t;
  if (nextT < 0) {
    nextT += 1;
  }
  if (nextT > 1) {
    nextT -= 1;
  }
  if (nextT < 1 / 6) {
    return p + (q - p) * 6 * nextT;
  }
  if (nextT < 1 / 2) {
    return q;
  }
  if (nextT < 2 / 3) {
    return p + (q - p) * (2 / 3 - nextT) * 6;
  }
  return p;
}
function hslToRgb(hue, saturation, lightness) {
  if (saturation === 0) {
    const gray = Math.round(lightness * 255);
    return [gray, gray, gray];
  }
  const q = lightness < 0.5 ? lightness * (1 + saturation) : lightness + saturation - lightness * saturation;
  const p = 2 * lightness - q;
  return [
    Math.round(hueToRgb(p, q, hue + 1 / 3) * 255),
    Math.round(hueToRgb(p, q, hue) * 255),
    Math.round(hueToRgb(p, q, hue - 1 / 3) * 255)
  ];
}
function escapeCssFontFamily(name) {
  return /[\s"'(),]/.test(name) ? `"${name.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"` : name;
}
function resolveSpreadsheetThemeFont(font, themePalette) {
  const scheme = typeof font?.scheme === "string" ? font.scheme : null;
  if (scheme === "major") {
    return themePalette?.majorLatinFont;
  }
  if (scheme === "minor") {
    return themePalette?.minorLatinFont;
  }
  return void 0;
}
function buildSpreadsheetFontFamily(font, themePalette) {
  const candidates = [
    typeof font?.name === "string" ? font.name.trim() : "",
    resolveSpreadsheetThemeFont(font, themePalette)?.trim() ?? ""
  ].filter((value, index, array) => value.length > 0 && array.indexOf(value) === index);
  if (candidates.length === 0) {
    return void 0;
  }
  const primaryFont = candidates[0]?.toLowerCase();
  if (primaryFont === "calibri") {
    return [
      "Calibri",
      "Carlito",
      '"React XLSX Carlito"',
      '"Aptos"',
      '"Segoe UI"',
      "Tahoma",
      "Arial",
      "sans-serif"
    ].join(", ");
  }
  return [
    ...candidates.map(escapeCssFontFamily),
    '"Segoe UI"',
    "Tahoma",
    "Arial",
    "sans-serif"
  ].join(", ");
}
function resolveSpreadsheetLineHeight(fontSizePt) {
  const sizePt = typeof fontSizePt === "number" && Number.isFinite(fontSizePt) ? fontSizePt : 11;
  if (sizePt <= 11) {
    return 1.2;
  }
  if (sizePt <= 14) {
    return 1.25;
  }
  return 1.3;
}
function buildGridlineShadow(color, options2) {
  const parts = [];
  if (options2?.right !== false) {
    parts.push(`inset -1px 0 0 ${color}`);
  }
  if (options2?.bottom !== false) {
    parts.push(`inset 0 -1px 0 ${color}`);
  }
  return parts.join(", ");
}
function buildCellStyle(style, palette, themePalette, options2) {
  const showGridLines = options2?.showGridLines ?? true;
  const baseSurface = paletteIsDark(palette) ? resolveDarkModeSurface(themePalette, palette) : themePalette?.colorsByIndex[0] ?? SHEET_SURFACE;
  const gridlineShadow = showGridLines ? buildGridlineShadow(palette.border) : void 0;
  const css = {
    backgroundColor: baseSurface,
    borderBottom: "none",
    borderRight: "none",
    boxShadow: gridlineShadow,
    color: resolveReadableTextColor(null, baseSurface, palette),
    fontFamily: buildSpreadsheetFontFamily({ scheme: "minor" }, themePalette) ?? '"Segoe UI", Tahoma, Arial, sans-serif',
    fontSize: "12px",
    lineHeight: String(resolveSpreadsheetLineHeight(11)),
    overflow: "hidden",
    padding: DEFAULT_CELL_PADDING,
    textAlign: options2?.generalAlignment ?? "left",
    textOverflow: "clip",
    verticalAlign: "bottom",
    whiteSpace: "nowrap"
  };
  if (!style) {
    return css;
  }
  const fill = style.fill;
  let resolvedFillColor = null;
  let hasExplicitFill = false;
  if (fill) {
    const fillStyle = resolveWorkbookFillStyle(fill, themePalette);
    if (fillStyle.backgroundColor || fillStyle.backgroundImage) {
      hasExplicitFill = true;
      resolvedFillColor = fillStyle.backgroundColor;
      if (fillStyle.backgroundColor) {
        css.backgroundColor = fillStyle.backgroundColor;
      }
      if (fillStyle.backgroundImage) {
        css.backgroundImage = fillStyle.backgroundImage;
      }
    }
  }
  const font = style.font;
  let resolvedFontColor = null;
  let resolvedFontSizePt = 11;
  if (font) {
    if (font.bold) {
      css.fontWeight = "bold";
    }
    if (font.italic) {
      css.fontStyle = "italic";
    }
    if (font.underline && font.underline !== "none") {
      css.textDecoration = "underline";
    }
    if (font.strikethrough) {
      css.textDecoration = `${css.textDecoration ?? ""} line-through`.trim();
    }
    const fontColor = resolveWorkbookColor(font.color, themePalette);
    if (fontColor) {
      resolvedFontColor = fontColor;
      css.color = fontColor;
    }
    if (typeof font.size === "number" && Number.isFinite(font.size) && font.size > 0) {
      resolvedFontSizePt = font.size;
      css.fontSize = `${font.size}pt`;
    }
    const fontFamily = buildSpreadsheetFontFamily(font, themePalette);
    if (fontFamily) {
      css.fontFamily = fontFamily;
    }
  }
  css.lineHeight = String(resolveSpreadsheetLineHeight(resolvedFontSizePt));
  if (paletteIsDark(palette) && !css.backgroundImage) {
    const effectiveBackgroundColor = typeof css.backgroundColor === "string" ? css.backgroundColor : baseSurface;
    css.color = resolveReadableTextColor(resolvedFontColor, effectiveBackgroundColor, palette);
  } else if (!hasExplicitFill) {
    css.color = resolveReadableTextColor(resolvedFontColor, baseSurface, palette);
  }
  const alignment = style.alignment;
  if (alignment) {
    if (alignment.horizontal && alignment.horizontal !== "general") {
      css.textAlign = alignment.horizontal;
    }
    if (alignment.vertical) {
      const verticalMap = {
        bottom: "bottom",
        center: "middle",
        top: "top"
      };
      const verticalValue = verticalMap[String(alignment.vertical)];
      if (verticalValue) {
        css.verticalAlign = verticalValue;
      }
    }
    if (alignment.wrapText) {
      css.whiteSpace = "pre-wrap";
      css.wordBreak = "break-word";
    }
  }
  const border = style.border;
  if (border) {
    const hasRightBorder = Boolean(border.right?.style && border.right.style !== "none");
    const hasBottomBorder = Boolean(border.bottom?.style && border.bottom.style !== "none");
    if (showGridLines && (hasRightBorder || hasBottomBorder)) {
      css.boxShadow = buildGridlineShadow(palette.border, {
        bottom: !hasBottomBorder,
        right: !hasRightBorder
      }) || void 0;
    }
    if (border.top?.style && border.top.style !== "none") {
      css.borderTop = mapBorder2(border.top, themePalette);
    }
    if (border.right?.style && border.right.style !== "none") {
      css.borderRight = mapBorder2(border.right, themePalette);
    }
    if (border.bottom?.style && border.bottom.style !== "none") {
      css.borderBottom = mapBorder2(border.bottom, themePalette);
    }
    if (border.left?.style && border.left.style !== "none") {
      css.borderLeft = mapBorder2(border.left, themePalette);
    }
  }
  return css;
}
var textMeasureCanvas = null;
function getHorizontalPadding(padding) {
  if (typeof padding !== "string") {
    return 8;
  }
  const values = padding.trim().split(/\s+/).map((value) => Number.parseFloat(value)).filter((value) => Number.isFinite(value));
  if (values.length === 1) {
    return values[0] * 2;
  }
  if (values.length === 2) {
    return values[1] * 2;
  }
  if (values.length === 3) {
    return values[1] * 2;
  }
  if (values.length >= 4) {
    return values[1] + values[3];
  }
  return 8;
}
function buildCanvasFont(style) {
  return resolveCanvasFont(style, 12);
}
function measureTextWidth(value, style) {
  if (!value) {
    return 0;
  }
  if (typeof document === "undefined") {
    return value.length * 7;
  }
  textMeasureCanvas ??= document.createElement("canvas");
  const context = textMeasureCanvas.getContext("2d", { alpha: false });
  if (!context) {
    return value.length * 7;
  }
  context.font = buildCanvasFont(style);
  return measureCanvasTextWidth(context, value);
}
function getCellDisplayValue(worksheet, row2, col, activeSheet, locale = "en-US") {
  const formula = worksheet.getFormulaAt(row2, col);
  const cachedFormulaValue = formula ? activeSheet?.cachedFormulaValues?.[cellAddressToA12({ row: row2, col })] : void 0;
  const formatted = worksheet.getFormattedValueAt(row2, col);
  if (formatted && !(formula && cachedFormulaValue !== void 0 && formatted.startsWith("#"))) {
    return localizeCellNumber(worksheet, row2, col, decodeHtmlEntities2(formatted), locale);
  }
  const cellValue = worksheet.getCalculatedValueAt(row2, col);
  if (formula && cachedFormulaValue !== void 0 && cellValue.is_error) {
    return cachedFormulaValue;
  }
  if (cellValue.is_error) {
    return cellValue.asError() ?? "";
  }
  if (cellValue.is_empty) {
    return "";
  }
  return cellValue.toString();
}
function getCellNumericValue(worksheet, row2, col) {
  const cellValue = worksheet.getCalculatedValueAt(row2, col);
  if (cellValue.is_number) {
    return cellValue.asNumber() ?? null;
  }
  if (cellValue.is_boolean) {
    return cellValue.asBoolean() ? 1 : 0;
  }
  if (cellValue.is_empty || cellValue.is_error) {
    return null;
  }
  const parsedValue = Number(cellValue.asText() ?? cellValue.toString());
  return Number.isFinite(parsedValue) ? parsedValue : null;
}
function getCellBooleanValue(worksheet, row2, col) {
  const cellValue = worksheet.getCalculatedValueAt(row2, col);
  if (cellValue.is_boolean) {
    return cellValue.asBoolean() ?? null;
  }
  if (cellValue.is_number) {
    const numeric = cellValue.asNumber();
    return numeric == null ? null : numeric !== 0;
  }
  const text = (cellValue.asText() ?? cellValue.toString()).trim().toLowerCase();
  if (text === "true") {
    return true;
  }
  if (text === "false") {
    return false;
  }
  return null;
}
function getBatchedCellNumericValue(cell) {
  if (!cell) {
    return null;
  }
  if (cell.numericValue !== void 0) return cell.numericValue;
  const text = cell.value.trim();
  if (text.length === 0) {
    return null;
  }
  if (text.toLowerCase() === "true") {
    return 1;
  }
  if (text.toLowerCase() === "false") {
    return 0;
  }
  const value = Number(text.replace(/,/g, ""));
  return Number.isFinite(value) ? value : null;
}
function getBatchedCellBooleanValue(cell) {
  if (!cell) {
    return null;
  }
  const text = cell.value.trim().toLowerCase();
  if (text.length === 0) {
    return null;
  }
  if (text === "true") {
    return true;
  }
  if (text === "false") {
    return false;
  }
  const value = Number(text);
  return Number.isFinite(value) ? value !== 0 : null;
}
function unescapeSheetNameReference(value) {
  const trimmed = value.trim();
  return trimmed.startsWith("'") && trimmed.endsWith("'") ? trimmed.slice(1, -1).replace(/''/g, "'") : trimmed;
}
function splitSheetFormulaReference(reference) {
  let inQuotes = false;
  for (let index = 0; index < reference.length; index += 1) {
    const character = reference[index];
    if (character === "'") {
      if (inQuotes && reference[index + 1] === "'") {
        index += 1;
        continue;
      }
      inQuotes = !inQuotes;
      continue;
    }
    if (character === "!" && !inQuotes) {
      return {
        range: reference.slice(index + 1),
        sheetName: unescapeSheetNameReference(reference.slice(0, index))
      };
    }
  }
  return null;
}
function clampSparklineValue(value, min, max) {
  if (max <= min) {
    return 0.5;
  }
  return Math.max(0, Math.min(1, (value - min) / (max - min)));
}
function renderSparkline(sparkline, values, palette) {
  const width = 100;
  const height = 18;
  const innerWidth2 = width - 2;
  const innerHeight2 = height - 4;
  const points = values.map((value, index) => ({ index, value })).filter((entry) => typeof entry.value === "number" && Number.isFinite(entry.value));
  if (points.length === 0) {
    return null;
  }
  const negativeColor = sparkline.negativeColor ?? "#c2410c";
  const seriesColor = sparkline.color ?? "#2563eb";
  const markerColor = sparkline.markerColor ?? seriesColor;
  if (sparkline.type === "winLoss") {
    const normalizedValues = points.map((entry) => ({ ...entry, value: entry.value >= 0 ? 1 : -1 }));
    const segmentWidth = Math.max(4, innerWidth2 / Math.max(normalizedValues.length * 1.9, 1));
    const gap = normalizedValues.length > 1 ? (innerWidth2 - segmentWidth * normalizedValues.length) / (normalizedValues.length - 1) : 0;
    const positiveY = 4.5;
    const negativeY = height - 4.5;
    return /* @__PURE__ */ jsx11("svg", { "aria-hidden": "true", height, style: { display: "block", overflow: "visible", width: "100%" }, viewBox: `0 0 ${width} ${height}`, width: "100%", children: normalizedValues.map((entry, index) => {
      const left = 1 + index * (segmentWidth + Math.max(0, gap));
      const y = entry.value >= 0 ? positiveY : negativeY;
      return /* @__PURE__ */ jsx11(
        "line",
        {
          stroke: seriesColor,
          strokeLinecap: "round",
          strokeWidth: 1.8,
          x1: left,
          x2: left + segmentWidth,
          y1: y,
          y2: y
        },
        `spark-winloss-${index}`
      );
    }) });
  }
  if (sparkline.type === "column") {
    const normalizedValues = points;
    const minValue2 = Math.min(0, ...normalizedValues.map((entry) => entry.value));
    const maxValue2 = Math.max(0, ...normalizedValues.map((entry) => entry.value));
    const zeroY = 2 + innerHeight2 - clampSparklineValue(0, minValue2, maxValue2) * innerHeight2;
    const barWidth = Math.max(2, innerWidth2 / Math.max(normalizedValues.length * 1.8, 1));
    const gap = normalizedValues.length > 1 ? (innerWidth2 - barWidth * normalizedValues.length) / (normalizedValues.length - 1) : 0;
    return /* @__PURE__ */ jsxs8("svg", { "aria-hidden": "true", height, style: { display: "block", overflow: "visible", width: "100%" }, viewBox: `0 0 ${width} ${height}`, width: "100%", children: [
      /* @__PURE__ */ jsx11("line", { stroke: palette.border, strokeWidth: 1, x1: 1, x2: width - 1, y1: zeroY, y2: zeroY }),
      normalizedValues.map((entry, index) => {
        const left = 1 + index * (barWidth + Math.max(0, gap));
        const y = 2 + innerHeight2 - clampSparklineValue(entry.value, minValue2, maxValue2) * innerHeight2;
        const top = Math.min(y, zeroY);
        const barHeight = Math.max(1, Math.abs(y - zeroY));
        const fill = entry.value < 0 ? negativeColor : seriesColor;
        return /* @__PURE__ */ jsx11(
          "rect",
          {
            fill,
            height: barHeight,
            rx: sparkline.type === "column" ? 0 : 0.8,
            ry: sparkline.type === "column" ? 0 : 0.8,
            width: barWidth,
            x: left,
            y: top
          },
          `spark-bar-${index}`
        );
      })
    ] });
  }
  const minValue = Math.min(...points.map((entry) => entry.value));
  const maxValue = Math.max(...points.map((entry) => entry.value));
  const xStep = points.length > 1 ? innerWidth2 / (points.length - 1) : 0;
  const path = points.map((entry, index) => {
    const x = 1 + index * xStep;
    const y = 2 + innerHeight2 - clampSparklineValue(entry.value, minValue, maxValue) * innerHeight2;
    return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(" ");
  const highValue = Math.max(...points.map((entry) => entry.value));
  const lowValue = Math.min(...points.map((entry) => entry.value));
  return /* @__PURE__ */ jsxs8("svg", { "aria-hidden": "true", height, style: { display: "block", overflow: "visible", width: "100%" }, viewBox: `0 0 ${width} ${height}`, width: "100%", children: [
    /* @__PURE__ */ jsx11("path", { d: path, fill: "none", stroke: seriesColor, strokeLinecap: "round", strokeLinejoin: "round", strokeWidth: 1.6 }),
    sparkline.markers ? points.map((entry, index) => {
      const x = 1 + index * xStep;
      const y = 2 + innerHeight2 - clampSparklineValue(entry.value, minValue, maxValue) * innerHeight2;
      let fill = markerColor;
      if (entry.value === highValue && sparkline.highColor) {
        fill = sparkline.highColor;
      } else if (entry.value === lowValue && sparkline.lowColor) {
        fill = sparkline.lowColor;
      } else if (index === 0 && sparkline.firstColor) {
        fill = sparkline.firstColor;
      } else if (index === points.length - 1 && sparkline.lastColor) {
        fill = sparkline.lastColor;
      } else if (entry.value < 0 && sparkline.negative && sparkline.negativeColor) {
        fill = sparkline.negativeColor;
      }
      return /* @__PURE__ */ jsx11("circle", { cx: x, cy: y, fill, r: 1.75 }, `spark-point-${index}`);
    }) : null
  ] });
}
function asNonNegativeInteger(value) {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}
function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}
function normalizeBatchedHyperlink(value) {
  const hyperlink = asRecord(value);
  if (!hyperlink) {
    return null;
  }
  return {
    location: typeof hyperlink.location === "string" ? hyperlink.location : void 0,
    target: typeof hyperlink.target === "string" ? hyperlink.target : void 0,
    tooltip: typeof hyperlink.tooltip === "string" ? hyperlink.tooltip : void 0
  };
}
function normalizeBatchedMergeSpan(value) {
  const mergeSpan = asRecord(value);
  if (!mergeSpan) {
    return null;
  }
  const rowSpan = asNonNegativeInteger(mergeSpan.rowSpan);
  const colSpan = asNonNegativeInteger(mergeSpan.colSpan);
  if (rowSpan === null && colSpan === null) {
    return null;
  }
  return {
    colSpan: colSpan ?? void 0,
    rowSpan: rowSpan ?? void 0
  };
}
function normalizeBatchedCellValue(rawValue, formula, row2, col, activeSheet) {
  const value = typeof rawValue === "string" ? decodeHtmlEntities2(rawValue) : rawValue === null || rawValue === void 0 ? "" : String(rawValue);
  const cachedFormulaValue = formula ? activeSheet?.cachedFormulaValues?.[cellAddressToA12({ row: row2, col })] : void 0;
  if (formula && cachedFormulaValue !== void 0 && value.startsWith("#")) {
    return cachedFormulaValue;
  }
  return value;
}
function buildWorksheetBatchWindow(rows, activeSheet, startRow, endRow) {
  const cells = /* @__PURE__ */ new Map();
  if (Array.isArray(rows)) {
    for (const rowEntry of rows) {
      const row2 = asNonNegativeInteger(rowEntry.index);
      if (row2 === null || !Array.isArray(rowEntry.cells)) {
        continue;
      }
      for (const cellEntry of rowEntry.cells) {
        const col = asNonNegativeInteger(cellEntry.col);
        if (col === null) {
          continue;
        }
        const formula = typeof cellEntry.formula === "string" ? cellEntry.formula : null;
        cells.set(`${row2}:${col}`, {
          formula,
          richText: cellEntry.richText,
          numericValue: typeof cellEntry.numericValue === "number" ? cellEntry.numericValue : cellEntry.numericValue === null ? null : void 0,
          generalAlignment: cellEntry.generalAlignment === "right" || cellEntry.generalAlignment === "center" ? cellEntry.generalAlignment : "left",
          hyperlink: normalizeBatchedHyperlink(cellEntry.hyperlink),
          isMergedSecondary: cellEntry.isMergedSecondary === true,
          mergeSpan: normalizeBatchedMergeSpan(cellEntry.mergeSpan),
          style: asRecord(cellEntry.style),
          value: normalizeBatchedCellValue(cellEntry.value, formula, row2, col, activeSheet)
        });
      }
    }
  }
  return {
    cells,
    endRow,
    startRow
  };
}
function mergeResolvedCellStyle(base, overlay, options2) {
  if (!base && !overlay) {
    return null;
  }
  const nextStyle = {
    ...base ?? {},
    ...overlay ?? {}
  };
  const baseAlignment = base?.alignment;
  const overlayAlignment = overlay?.alignment;
  if (baseAlignment || overlayAlignment) {
    nextStyle.alignment = {
      ...baseAlignment ?? {},
      ...overlayAlignment ?? {}
    };
  }
  const baseBorder = base?.border;
  const overlayBorder = overlay?.border;
  if (baseBorder || overlayBorder) {
    nextStyle.border = options2?.replaceXfSubtrees && overlayBorder ? overlayBorder : {
      ...baseBorder ?? {},
      ...overlayBorder ?? {}
    };
  }
  const baseFill = base?.fill;
  const overlayFill = overlay?.fill;
  if (baseFill || overlayFill) {
    nextStyle.fill = options2?.replaceXfSubtrees && overlayFill ? overlayFill : overlayFill ?? baseFill;
  }
  const baseFont = base?.font;
  const overlayFont = overlay?.font;
  if (baseFont || overlayFont) {
    nextStyle.font = options2?.replaceXfSubtrees && overlayFont ? overlayFont : {
      ...baseFont ?? {},
      ...overlayFont ?? {}
    };
  }
  return nextStyle;
}
function SegmentedControl({
  items,
  messages,
  onValueChange,
  palette,
  value
}) {
  return /* @__PURE__ */ jsx11(
    "div",
    {
      "aria-label": messages.workbookSheets,
      role: "tablist",
      style: {
        alignItems: "center",
        backgroundColor: palette.sheetInactiveSurface,
        border: `1px solid ${palette.strongBorder}`,
        borderRadius: 10,
        display: "inline-flex",
        gap: 2,
        minHeight: 36,
        padding: 2
      },
      children: items.map((item) => {
        const selected = item.id === value;
        const isHidden = item.visibility === "hidden" || item.visibility === "veryHidden";
        return /* @__PURE__ */ jsx11(
          "button",
          {
            "aria-selected": selected,
            onClick: () => onValueChange(item.id),
            role: "tab",
            style: {
              backgroundColor: selected ? palette.sheetActiveSurface : "transparent",
              border: "none",
              borderRadius: 8,
              boxShadow: selected ? palette.shadow : "none",
              color: selected ? palette.sheetActiveText : palette.sheetInactiveText,
              cursor: "pointer",
              fontSize: 12,
              fontWeight: selected ? 600 : 500,
              opacity: isHidden && !selected ? 0.68 : 1,
              padding: "7px 12px",
              transition: "background-color 120ms ease, color 120ms ease, box-shadow 120ms ease",
              whiteSpace: "nowrap"
            },
            title: item.title,
            type: "button",
            children: item.label
          },
          item.id
        );
      })
    }
  );
}
function DefaultToolbar({ controller, palette, pivotTableEditor }) {
  const {
    activeTabIndex,
    canDownload,
    canZoomIn,
    canZoomOut,
    defaultZoomScale,
    locale,
    messages,
    displayFileName,
    download,
    resetZoom,
    setActiveTabIndex,
    tabs,
    zoomIn,
    zoomOut,
    zoomScale
  } = controller;
  return /* @__PURE__ */ jsxs8(Fragment11, { children: [
    /* @__PURE__ */ jsxs8(
      "div",
      {
        style: {
          alignItems: "center",
          backgroundColor: palette.toolbarSurface,
          borderBottom: `1px solid ${palette.border}`,
          color: palette.text,
          display: "flex",
          gap: 12,
          justifyContent: "space-between",
          minHeight: 48,
          padding: "0 16px"
        },
        children: [
          /* @__PURE__ */ jsx11("div", { style: { minWidth: 0 }, children: /* @__PURE__ */ jsx11(
            "div",
            {
              style: {
                color: palette.text,
                fontSize: 14,
                fontWeight: 600,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap"
              },
              children: displayFileName
            }
          ) }),
          /* @__PURE__ */ jsxs8("div", { style: { alignItems: "center", display: "flex", gap: 8 }, children: [
            pivotTableEditor && (!controller.readOnly || controller.pivotTables.length > 0) ? /* @__PURE__ */ jsx11(
              "button",
              {
                "aria-label": messages.pivotTableFields,
                "aria-expanded": pivotTableEditor.open,
                disabled: !controller.activeSheet,
                onClick: () => {
                  if (!pivotTableEditor.draft && controller.pivotTables.length > 0) pivotTableEditor.select(controller.pivotTables[0].id);
                  else if (!pivotTableEditor.draft && !controller.readOnly) pivotTableEditor.create();
                  else pivotTableEditor.setOpen(!pivotTableEditor.open);
                },
                style: { background: palette.buttonSurface, border: `1px solid ${palette.strongBorder}`, borderRadius: 6, color: palette.buttonText, cursor: "pointer", padding: "6px 10px", fontSize: 12 },
                type: "button",
                children: "PivotTable"
              }
            ) : null,
            /* @__PURE__ */ jsxs8(
              "div",
              {
                style: {
                  alignItems: "center",
                  background: palette.buttonSurface,
                  border: `1px solid ${palette.strongBorder}`,
                  borderRadius: 8,
                  display: "flex",
                  overflow: "hidden"
                },
                children: [
                  /* @__PURE__ */ jsx11(
                    "button",
                    {
                      "aria-label": messages.zoomOut,
                      disabled: !canZoomOut,
                      onClick: zoomOut,
                      style: {
                        background: "transparent",
                        border: "none",
                        color: canZoomOut ? palette.buttonText : palette.mutedText,
                        cursor: canZoomOut ? "pointer" : "default",
                        fontSize: 14,
                        fontWeight: 600,
                        padding: "6px 10px"
                      },
                      type: "button",
                      children: "-"
                    }
                  ),
                  /* @__PURE__ */ jsx11(
                    "button",
                    {
                      "aria-label": messages.resetZoom,
                      onClick: resetZoom,
                      style: {
                        background: Math.round(zoomScale) === Math.round(defaultZoomScale) ? "transparent" : palette.subtleSurface,
                        border: "none",
                        borderLeft: `1px solid ${palette.strongBorder}`,
                        borderRight: `1px solid ${palette.strongBorder}`,
                        color: palette.buttonText,
                        cursor: "pointer",
                        fontSize: 12,
                        fontWeight: 600,
                        minWidth: 60,
                        padding: "6px 10px"
                      },
                      type: "button",
                      children: formatZoomScale(zoomScale, locale)
                    }
                  ),
                  /* @__PURE__ */ jsx11(
                    "button",
                    {
                      "aria-label": messages.zoomIn,
                      disabled: !canZoomIn,
                      onClick: zoomIn,
                      style: {
                        background: "transparent",
                        border: "none",
                        color: canZoomIn ? palette.buttonText : palette.mutedText,
                        cursor: canZoomIn ? "pointer" : "default",
                        fontSize: 14,
                        fontWeight: 600,
                        padding: "6px 10px"
                      },
                      type: "button",
                      children: "+"
                    }
                  )
                ]
              }
            ),
            canDownload ? /* @__PURE__ */ jsx11(
              "button",
              {
                "aria-label": messages.downloadWorkbook,
                onClick: download,
                style: {
                  alignItems: "center",
                  background: palette.buttonSurface,
                  border: `1px solid ${palette.strongBorder}`,
                  borderRadius: 8,
                  color: palette.buttonText,
                  cursor: "pointer",
                  display: "inline-flex",
                  fontSize: 16,
                  fontWeight: 500,
                  height: 32,
                  justifyContent: "center",
                  padding: 0,
                  width: 32
                },
                title: messages.downloadWorkbook,
                type: "button",
                children: "\u2193"
              }
            ) : null
          ] })
        ]
      }
    ),
    tabs.length > 1 ? /* @__PURE__ */ jsx11(
      "div",
      {
        style: {
          backgroundColor: palette.subtleSurface,
          borderBottom: `1px solid ${palette.border}`,
          overflowX: "auto",
          padding: "8px 12px"
        },
        children: /* @__PURE__ */ jsx11(
          SegmentedControl,
          {
            messages,
            items: tabs.map((tab, index) => ({
              id: String(index),
              label: tab.name,
              title: tab.visibility === "hidden" ? formatMessage(messages.hiddenSheet, { sheet: tab.name }) : tab.visibility === "veryHidden" ? formatMessage(messages.veryHiddenSheet, { sheet: tab.name }) : tab.name,
              visibility: tab.visibility
            })),
            onValueChange: (value) => setActiveTabIndex(Number(value)),
            palette,
            value: String(activeTabIndex)
          }
        )
      }
    ) : null
  ] });
}
function resolveRichCellRuns(raw, value, base, theme, zoom) {
  if (!Array.isArray(raw) || raw.length === 0 || raw.map((run) => run.text).join("") !== value) return void 0;
  return raw.map((run) => {
    const font = run.font;
    const style = { ...base };
    if (font) {
      const family = buildSpreadsheetFontFamily(font, theme);
      if (family) style.fontFamily = family;
      if (typeof font.size === "number" && font.size > 0) style.fontSize = font.size * (4 / 3) * zoom;
      if (typeof font.bold === "boolean") style.fontWeight = font.bold ? "bold" : "normal";
      if (typeof font.italic === "boolean") style.fontStyle = font.italic ? "italic" : "normal";
      const color = resolveWorkbookColor(font.color, theme);
      if (color) style.color = color;
      const decorations = new Set(String(base.textDecoration ?? "").split(/\s+/).filter(Boolean));
      if (font.underline != null) {
        decorations.delete("underline");
        if (font.underline !== "none") decorations.add("underline");
      }
      if (font.strikethrough != null) {
        decorations.delete("line-through");
        if (font.strikethrough) decorations.add("line-through");
      }
      style.textDecoration = [...decorations].join(" ") || "none";
      if (font.verticalAlign === "superscript" || font.verticalAlign === "subscript") {
        style.verticalAlign = font.verticalAlign === "superscript" ? "super" : "sub";
        style.fontSize = resolveCanvasFontSizePx(style, 14 * zoom) * 0.65;
      }
    }
    return { text: run.text, style };
  });
}
function renderRichCellText(cell) {
  const scale = cell.shrinkToFitFontSizePx === void 0 ? 1 : cell.shrinkToFitFontSizePx / resolveCanvasFontSizePx(cell.style, 14);
  return cell.richText ? cell.richText.map((run, index) => /* @__PURE__ */ jsx11("span", { style: {
    fontFamily: run.style.fontFamily,
    fontSize: resolveCanvasFontSizePx(run.style, 14) * scale,
    fontWeight: run.style.fontWeight,
    fontStyle: run.style.fontStyle,
    color: run.style.color,
    textDecoration: run.style.textDecoration,
    verticalAlign: run.style.verticalAlign === "super" || run.style.verticalAlign === "sub" ? run.style.verticalAlign : void 0
  }, children: run.text }, index)) : cell.value;
}
function measureCellTextWidth(cell) {
  return cell.richText ? cell.richText.reduce((sum, run) => sum + measureTextWidth(run.text, run.style), 0) : measureTextWidth(cell.value, cell.style);
}
var DOM_AUTOFIT_TEXT_PROPERTIES = {
  fontKerning: "font-kerning",
  fontStretch: "font-stretch",
  fontVariant: "font-variant",
  letterSpacing: "letter-spacing",
  overflowWrap: "overflow-wrap",
  tabSize: "tab-size",
  textTransform: "text-transform",
  whiteSpace: "white-space",
  wordBreak: "word-break",
  wordSpacing: "word-spacing"
};
var domAutofitTextProperties = Object.keys(DOM_AUTOFIT_TEXT_PROPERTIES);
function layoutRichCellLines(context, runs, scale, wrapWidth, splitLines) {
  const lines = [[]];
  let width = 0;
  for (const run of runs) {
    const style = { ...run.style, fontSize: resolveCanvasFontSizePx(run.style, 14) * scale };
    context.font = resolveCanvasFontWithPxSize(style, Number(style.fontSize));
    const height = resolveCanvasLineHeight(style, Number(style.fontSize));
    const parts = wrapWidth !== void 0 ? run.text.split(/(\r\n?|\n|[^\S\r\n]+|[^\s]+)/).filter(Boolean) : splitLines ? run.text.split(/(\r\n?|\n)/) : [run.text];
    for (const part of parts) {
      if (/^(?:\r\n?|\n)$/.test(part)) {
        lines.push([]);
        width = 0;
        continue;
      }
      const partWidth = context.measureText(part).width;
      if (wrapWidth !== void 0 && width > 0 && width + partWidth > wrapWidth) {
        lines.push([]);
        width = 0;
      }
      if (wrapWidth !== void 0 && partWidth > wrapWidth) {
        for (const character of part) {
          const characterWidth = context.measureText(character).width;
          if (width > 0 && width + characterWidth > wrapWidth) {
            lines.push([]);
            width = 0;
          }
          lines[lines.length - 1].push({ text: character, style, width: characterWidth, height });
          width += characterWidth;
        }
      } else {
        lines[lines.length - 1].push({ text: part, style, width: partWidth, height });
        width += partWidth;
      }
    }
  }
  return lines;
}
function measureRichLineHeights(lines, style, scale) {
  const baseHeight = resolveCanvasLineHeight(style, 14) * scale;
  return lines.map((line) => line.reduce((height, part) => Math.max(height, part.height), baseHeight));
}
function drawRichCellText(context, cell, rect) {
  if (!cell.richText) return;
  context.save();
  const naturalWidth = measureCellTextWidth(cell);
  const scale = cell.shrinkToFitFontSizePx !== void 0 ? cell.shrinkToFitFontSizePx / resolveCanvasFontSizePx(cell.style, 14) : cell.shrinkToFit && naturalWidth > rect.width ? Math.max(0.4, rect.width / naturalWidth) : 1;
  const wrap = !cell.textRotationDeg && (cell.style.whiteSpace === "pre-wrap" || cell.value.includes("\n"));
  const lines = layoutRichCellLines(context, cell.richText, scale, wrap ? rect.width : void 0, false);
  const heights = measureRichLineHeights(lines, cell.style, scale);
  const totalHeight = heights.reduce((sum, height) => sum + height, 0);
  let y = rect.top + (cell.style.verticalAlign === "top" ? 0 : cell.style.verticalAlign === "middle" ? (rect.height - totalHeight) / 2 : rect.height - totalHeight);
  if (cell.textRotationDeg) {
    context.translate(rect.left + rect.width / 2, rect.top + rect.height / 2);
    context.rotate(cell.textRotationDeg * Math.PI / 180);
    rect = { left: -naturalWidth * scale / 2, top: -totalHeight / 2, width: naturalWidth * scale, height: totalHeight };
    y = rect.top;
  }
  context.textBaseline = "middle";
  context.textAlign = "left";
  lines.forEach((line, index) => {
    const lineWidth = line.reduce((sum, part) => sum + part.width, 0);
    let x = rect.left + (cell.style.textAlign === "right" ? rect.width - lineWidth : cell.style.textAlign === "center" ? (rect.width - lineWidth) / 2 : 0);
    const height = heights[index];
    for (const part of line) {
      context.font = resolveCanvasFontWithPxSize(part.style, Number(part.style.fontSize));
      context.fillStyle = String(part.style.color ?? "#000000");
      const offset = part.style.verticalAlign === "super" ? -height * 0.25 : part.style.verticalAlign === "sub" ? height * 0.2 : 0;
      const middle = y + height / 2 + offset;
      context.fillText(part.text, x, middle);
      drawCanvasTextDecorations(context, { align: "left", color: String(part.style.color ?? "#000000"), decoration: String(part.style.textDecoration ?? ""), lineThroughY: middle, maxWidth: part.width, text: part.text, textX: x, underlineY: middle + height * 0.25, zoomFactor: 1 });
      x += part.width;
    }
    y += height;
  });
  context.restore();
}
function buildConditionalFormatRuleKey(rule) {
  return `${rule.kind}:${rule.priority}:${rule.ranges.map((range) => `${range.start.row}:${range.start.col}-${range.end.row}:${range.end.col}`).join("|")}`;
}
function resolveConditionalRuleThreshold(threshold, numericValues) {
  if (!threshold) {
    return null;
  }
  const fallbackValue = typeof threshold.value === "number" ? threshold.value : null;
  const thresholdType = threshold.type.trim().toLowerCase();
  if (thresholdType === "num" || thresholdType === "formula") {
    return fallbackValue;
  }
  if (numericValues.length === 0) {
    return fallbackValue;
  }
  const minValue = Math.min(...numericValues);
  const maxValue = Math.max(...numericValues);
  if (thresholdType === "min") {
    return minValue;
  }
  if (thresholdType === "max") {
    return maxValue;
  }
  if (thresholdType === "automin" || thresholdType === "automaticmin") {
    return Math.min(0, minValue);
  }
  if (thresholdType === "automax" || thresholdType === "automaticmax") {
    return Math.max(0, maxValue);
  }
  if ((thresholdType === "percent" || thresholdType === "percentile") && fallbackValue !== null) {
    return minValue + (maxValue - minValue) * (fallbackValue / 100);
  }
  return fallbackValue;
}
function parseConditionalFormulaLiteral(formula) {
  const trimmed = formula.trim();
  if (trimmed.length === 0) {
    return null;
  }
  const withoutEquals = trimmed.startsWith("=") ? trimmed.slice(1).trim() : trimmed;
  if (withoutEquals.startsWith('"') && withoutEquals.endsWith('"') && withoutEquals.length >= 2) {
    return withoutEquals.slice(1, -1).replace(/\"\"/g, '"');
  }
  const numeric = Number(withoutEquals.replace(/,/g, ""));
  if (Number.isFinite(numeric)) {
    return numeric;
  }
  return withoutEquals;
}
function resolveConditionalCellIsMatch(operator, left, right, numericValue, textValue) {
  const normalizedOperator = operator.trim();
  const normalizedText = textValue.trim();
  const parsedNumericText = Number(normalizedText.replace(/,/g, ""));
  const effectiveNumericValue = numericValue ?? (Number.isFinite(parsedNumericText) ? parsedNumericText : null);
  const cellIsTextComparable = effectiveNumericValue === null && normalizedText.length > 0;
  const compareComparable = (literal, predicate) => {
    if (typeof literal !== "number") {
      return false;
    }
    if (effectiveNumericValue !== null) {
      return predicate(effectiveNumericValue, literal);
    }
    if (cellIsTextComparable) {
      return predicate(1, 0);
    }
    return false;
  };
  switch (normalizedOperator) {
    case "greaterThan":
      return compareComparable(left, (cell, value) => cell > value);
    case "greaterThanOrEqual":
      return compareComparable(left, (cell, value) => cell >= value);
    case "lessThan":
      return compareComparable(left, (cell, value) => cell < value);
    case "lessThanOrEqual":
      return compareComparable(left, (cell, value) => cell <= value);
    case "between":
      if (typeof left !== "number" || typeof right !== "number") {
        return false;
      }
      if (effectiveNumericValue === null) {
        return false;
      }
      return effectiveNumericValue >= left && effectiveNumericValue <= right;
    case "notBetween":
      if (typeof left !== "number" || typeof right !== "number") {
        return false;
      }
      if (effectiveNumericValue === null) {
        return cellIsTextComparable;
      }
      return effectiveNumericValue < left || effectiveNumericValue > right;
    case "notEqual":
      if (typeof left === "number") {
        if (effectiveNumericValue !== null) {
          return effectiveNumericValue !== left;
        }
        return cellIsTextComparable;
      }
      return left !== null && normalizedText.toLowerCase() !== String(left).toLowerCase();
    case "equal":
    default:
      if (typeof left === "number") {
        if (effectiveNumericValue !== null) {
          return effectiveNumericValue === left;
        }
        return false;
      }
      return left !== null && normalizedText.toLowerCase() === String(left).toLowerCase();
  }
}
function resolveConditionalFormulaComparable(formula, worksheet, sheet, batchedCells) {
  const literal = parseConditionalFormulaLiteral(formula);
  if (typeof literal === "number") {
    return literal;
  }
  const normalized = formula.trim().replace(/^=/, "").trim();
  if (normalized.length === 0) {
    return literal;
  }
  const splitReference = splitSheetFormulaReference(normalized);
  const targetSheetName = splitReference?.sheetName ?? null;
  if (targetSheetName && sheet?.name && targetSheetName !== sheet.name) {
    return literal;
  }
  const cellRef = splitReference?.range ?? normalized;
  const cell = parseA1CellReference2(cellRef.replace(/\$/g, ""));
  if (!cell) {
    return literal;
  }
  if (worksheet) {
    const numeric = getCellNumericValue(worksheet, cell.row, cell.col);
    if (numeric !== null) {
      return numeric;
    }
    return getCellDisplayValue(worksheet, cell.row, cell.col, sheet);
  }
  if (batchedCells) {
    const batched = batchedCells.get(`${cell.row}:${cell.col}`);
    if (batched) {
      const numeric = getBatchedCellNumericValue(batched);
      if (numeric !== null) {
        return numeric;
      }
      return batched.value;
    }
  }
  return literal;
}
function normalizeConditionalTextOperand(value) {
  if (value === null || value === void 0) {
    return "";
  }
  return String(value).trim().toLowerCase();
}
function resolveConditionalStyledRuleMatch(rule, numericValue, textValue, worksheet, sheet, batchedCells) {
  const normalizedRuleType = rule.ruleType.trim().toLowerCase();
  const left = resolveConditionalFormulaComparable(rule.formulas?.[0] ?? "", worksheet, sheet, batchedCells);
  const right = resolveConditionalFormulaComparable(rule.formulas?.[1] ?? "", worksheet, sheet, batchedCells);
  if (normalizedRuleType === "cellis") {
    return resolveConditionalCellIsMatch(rule.operator ?? "equal", left, right, numericValue, textValue);
  }
  const normalizedCellText = textValue.trim().toLowerCase();
  const normalizedOperand = normalizeConditionalTextOperand(rule.text) || normalizeConditionalTextOperand(left);
  switch (normalizedRuleType) {
    case "beginwith":
    case "beginswith":
      return normalizedOperand.length > 0 && normalizedCellText.startsWith(normalizedOperand);
    case "endwith":
    case "endswith":
      return normalizedOperand.length > 0 && normalizedCellText.endsWith(normalizedOperand);
    case "containstext":
      return normalizedOperand.length > 0 && normalizedCellText.includes(normalizedOperand);
    case "notcontainstext":
      return normalizedOperand.length > 0 && !normalizedCellText.includes(normalizedOperand);
    default:
      return false;
  }
}
var styledConditionalRulesByRuleList = /* @__PURE__ */ new WeakMap();
function getStyledConditionalRules(rules) {
  let styledRules = styledConditionalRulesByRuleList.get(rules);
  if (!styledRules) {
    styledRules = rules.filter((rule) => rule.kind === "styled");
    styledConditionalRulesByRuleList.set(rules, styledRules);
  }
  return styledRules;
}
function resolveConditionalCellStyleForCell(row2, col, sheet, readNumericValue, readTextValue, worksheet, batchedCells) {
  const rules = sheet?.conditionalFormatRules;
  if (!sheet || !rules || rules.length === 0) {
    return null;
  }
  const styledRules = getStyledConditionalRules(rules);
  if (styledRules.length === 0) {
    return null;
  }
  const matchedStyles = [];
  let numericValue;
  let textValue;
  for (const rule of styledRules) {
    if (!rule.ranges.some((range) => isCellInRange({ row: row2, col }, range))) {
      continue;
    }
    if (numericValue === void 0) {
      numericValue = readNumericValue();
    }
    if (textValue === void 0) {
      textValue = readTextValue();
    }
    if (!resolveConditionalStyledRuleMatch(rule, numericValue, textValue, worksheet, sheet, batchedCells)) {
      continue;
    }
    matchedStyles.push(rule.style);
    if (rule.stopIfTrue) {
      break;
    }
  }
  if (matchedStyles.length === 0) {
    return null;
  }
  let resolved = null;
  for (let index = matchedStyles.length - 1; index >= 0; index -= 1) {
    resolved = mergeResolvedCellStyle(resolved, matchedStyles[index]);
  }
  return resolved;
}
function buildConditionalIcon(iconSet, iconId) {
  switch (iconSet) {
    case "NoIcons":
      return null;
    case "4TrafficLights": {
      const definitions = [
        { backgroundColor: "#111827", borderColor: "#6b7280" },
        { backgroundColor: "#22c55e", borderColor: "#166534" },
        { backgroundColor: "#ef4444", borderColor: "#991b1b" },
        { backgroundColor: "#facc15", borderColor: "#a704" }
      ];
      return definitions[iconId] ?? definitions[definitions.length - 1] ?? null;
    }
    case "3TrafficLights1":
    case "3TrafficLights2": {
      const definitions = [
        { backgroundColor: "#22c55e", borderColor: iconSet === "3TrafficLights2" ? "#111827" : "#166534" },
        { backgroundColor: "#facc15", borderColor: iconSet === "3TrafficLights2" ? "#111827" : "#a704" },
        { backgroundColor: "#ef4444", borderColor: iconSet === "3TrafficLights2" ? "#111827" : "#991b1b" }
      ];
      return definitions[iconId] ?? definitions[definitions.length - 1] ?? null;
    }
    case "4RedToBlack": {
      const definitions = [
        { backgroundColor: "#ef4444", borderColor: "#991b1b" },
        { backgroundColor: "#fca5a5", borderColor: "#b91c1c" },
        { backgroundColor: "#9ca3af", borderColor: "#4b5563" },
        { backgroundColor: "#111827", borderColor: "#6b7280" }
      ];
      return definitions[iconId] ?? definitions[definitions.length - 1] ?? null;
    }
    case "3Symbols":
      return [
        { backgroundColor: "#22c55e", color: "#ffffff", glyph: "\u2713" },
        { backgroundColor: "#facc15", color: "#111827", glyph: "!" },
        { backgroundColor: "#ef4444", color: "#ffffff", glyph: "\xD7" }
      ][iconId] ?? null;
    case "3Symbols2":
      return [
        { color: "#16a34a", glyph: "\u2713" },
        { color: "#ca8a04", glyph: "!" },
        { color: "#dc2626", glyph: "\xD7" }
      ][iconId] ?? null;
    case "3Signs":
      return [
        { backgroundColor: "#22c55e", borderColor: "#166534" },
        { backgroundColor: "#facc15", borderColor: "#a704", glyph: "\u25B2", color: "#111827" },
        { backgroundColor: "#ef4444", borderColor: "#991b1b", glyph: "\u25C6", color: "#ffffff" }
      ][iconId] ?? null;
    default:
      if (iconSet.includes("Arrows")) {
        const arrowColors = iconSet.includes("Gray") ? ["#9ca3af", "#9ca3af", "#9ca3af", "#9ca3af", "#9ca3af"] : ["#16a34a", "#ca8a04", "#ca8a04", "#ca8a04", "#dc2626"];
        const arrowRotations = iconSet.startsWith("3") ? [-90, 0, 90] : iconSet.startsWith("4") ? [-90, -35, 35, 90] : [-90, -35, 0, 35, 90];
        const resolvedIndex = Math.min(iconId, arrowColors.length - 1, arrowRotations.length - 1);
        return {
          borderColor: iconSet.includes("Gray") ? "#6b7280" : darkenColor(arrowColors[resolvedIndex] ?? "#16a34a", 0.34),
          color: arrowColors[resolvedIndex],
          rotationDeg: arrowRotations[resolvedIndex] ?? 0,
          shape: "arrow"
        };
      }
      return {
        backgroundColor: "#111827",
        borderColor: "#6b7280"
      };
  }
}
function renderConditionalIcon(icon, scale = 1) {
  const iconSize = 14 * scale;
  if (icon.shape === "arrow") {
    const fill = icon.color ?? "#111827";
    const stroke = icon.borderColor ?? darkenColor(fill, 0.32);
    return /* @__PURE__ */ jsx11(
      "svg",
      {
        "aria-hidden": "true",
        height: iconSize,
        style: { display: "block" },
        viewBox: "0 0 16 16",
        width: iconSize,
        children: /* @__PURE__ */ jsx11("g", { transform: `rotate(${icon.rotationDeg ?? 0} 8 8)`, children: /* @__PURE__ */ jsx11(
          "path",
          {
            d: "M2.5 8 L8.4 2.4 L8.4 5.2 L13.5 5.2 L13.5 10.8 L8.4 10.8 L8.4 13.6 Z",
            fill,
            stroke,
            strokeLinejoin: "round",
            strokeWidth: 1.25
          }
        ) })
      }
    );
  }
  if (icon.glyph) {
    return /* @__PURE__ */ jsx11(
      "span",
      {
        style: {
          alignItems: "center",
          color: icon.color ?? "#111827",
          display: "inline-flex",
          fontSize: 13 * scale,
          fontWeight: 700,
          height: iconSize,
          justifyContent: "center",
          lineHeight: 1,
          width: iconSize
        },
        children: icon.glyph
      }
    );
  }
  return /* @__PURE__ */ jsx11(
    "span",
    {
      style: {
        backgroundColor: icon.backgroundColor ?? "#111827",
        border: icon.borderColor ? `1px solid ${icon.borderColor}` : "none",
        borderRadius: "999px",
        display: "inline-block",
        height: 12 * scale,
        width: 12 * scale
      }
    }
  );
}
function isFormControlChecked(control2) {
  return control2.state ? control2.state === "checked" : Boolean(control2.checked);
}
function isFormControlMixed(control2) {
  return control2.state === "mixed";
}
function renderCheckboxControl(checked, palette, scale = 1, mixed = false) {
  const stroke = paletteIsDark(palette) ? "#cbd5e1" : "#475569";
  const fill = checked || mixed ? paletteIsDark(palette) ? "#60a5fa" : "#2563eb" : "transparent";
  const check = paletteIsDark(palette) ? "#020617" : "#ffffff";
  return /* @__PURE__ */ jsxs8("svg", { "aria-hidden": "true", height: 14 * scale, style: { display: "block" }, viewBox: "0 0 16 16", width: 14 * scale, children: [
    /* @__PURE__ */ jsx11("rect", { fill, height: 11, rx: 2, ry: 2, stroke, strokeWidth: 1.2, width: 11, x: 2.5, y: 2.5 }),
    mixed ? /* @__PURE__ */ jsx11("path", { d: "M5 8h6", fill: "none", stroke: check, strokeLinecap: "round", strokeWidth: 1.8 }) : checked ? /* @__PURE__ */ jsx11(
      "path",
      {
        d: "M5 8.1 7.1 10.2 11.3 5.8",
        fill: "none",
        stroke: check,
        strokeLinecap: "round",
        strokeLinejoin: "round",
        strokeWidth: 1.8
      }
    ) : null
  ] });
}
function resolveFormControlLabel(control2) {
  const label = control2.label ?? control2.name;
  if (!label) {
    return "";
  }
  const normalized = label.replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
  if (/^(option button|group box|check box|drop down|dropdown|list box|edit box|scroll bar|spinner|spin button|button)\s+\d+$/.test(normalized)) {
    return "";
  }
  return label.replace(/\u00a0/g, " ").replace(/^\s+/, "");
}
function drawStaticShapeText(context, shape, left, top, width, height, zoomFactor) {
  if (shape.paragraphs.length === 0) {
    return;
  }
  const inset = shape.textBox?.insetPx;
  const paddingLeft = (inset?.left ?? 6) * zoomFactor;
  const paddingRight = (inset?.right ?? 6) * zoomFactor;
  const paddingTop = (inset?.top ?? 4) * zoomFactor;
  const paddingBottom = (inset?.bottom ?? 4) * zoomFactor;
  const textLeft = left + paddingLeft;
  const textTop = top + paddingTop;
  const textWidth = Math.max(0, width - paddingLeft - paddingRight);
  const textHeight = Math.max(0, height - paddingTop - paddingBottom);
  if (textWidth <= 0 || textHeight <= 0) {
    return;
  }
  const lineMetrics = shape.paragraphs.map((paragraph) => {
    const lineHeight = Math.max(
      12 * zoomFactor,
      ...paragraph.runs.map((run) => (run.fontSizePt ?? 11) * 96 / 72 * zoomFactor * 1.2)
    );
    const widthPx = paragraph.runs.reduce((total, run) => {
      const fontSize = (run.fontSizePt ?? 11) * 96 / 72 * zoomFactor;
      context.font = `${run.italic ? "italic " : ""}${run.bold ? "700 " : "400 "}${fontSize}px ${run.fontFamily ?? "Calibri, sans-serif"}`;
      return total + measureCanvasTextWidth(context, run.text);
    }, 0);
    return { lineHeight, widthPx };
  });
  const totalTextHeight = lineMetrics.reduce((total, metric) => total + metric.lineHeight, 0);
  let y = textTop;
  if (shape.textBox?.verticalAlign === "middle") {
    y = textTop + Math.max(0, (textHeight - totalTextHeight) / 2);
  } else if (shape.textBox?.verticalAlign === "bottom") {
    y = textTop + Math.max(0, textHeight - totalTextHeight);
  }
  context.save();
  context.beginPath();
  context.rect(textLeft, textTop, textWidth, textHeight);
  context.clip();
  context.textBaseline = "middle";
  shape.paragraphs.forEach((paragraph, paragraphIndex) => {
    const metric = lineMetrics[paragraphIndex] ?? { lineHeight: 14 * zoomFactor, widthPx: 0 };
    let x = textLeft;
    const align = paragraph.align ?? shape.textBox?.horizontalAlign ?? "left";
    if (align === "center") {
      x = textLeft + Math.max(0, (textWidth - metric.widthPx) / 2);
    } else if (align === "right") {
      x = textLeft + Math.max(0, textWidth - metric.widthPx);
    }
    paragraph.runs.forEach((run) => {
      const fontSize = (run.fontSizePt ?? 11) * 96 / 72 * zoomFactor;
      context.font = `${run.italic ? "italic " : ""}${run.bold ? "700 " : "400 "}${fontSize}px ${run.fontFamily ?? "Calibri, sans-serif"}`;
      context.fillStyle = run.color ?? "#000000";
      context.textAlign = "left";
      const textY = y + metric.lineHeight / 2;
      context.fillText(run.text, x, textY);
      if (run.underline && run.text.length > 0) {
        const textWidthPx = measureCanvasTextWidth(context, run.text);
        context.strokeStyle = run.color ?? "#000000";
        context.lineWidth = Math.max(1, zoomFactor * 0.75);
        context.beginPath();
        context.moveTo(x, textY + Math.max(2, fontSize * 0.28));
        context.lineTo(x + textWidthPx, textY + Math.max(2, fontSize * 0.28));
        context.stroke();
      }
      x += measureCanvasTextWidth(context, run.text);
    });
    y += metric.lineHeight;
  });
  context.restore();
}
function drawStaticShape(context, shape, rect, zoomFactor) {
  const fillColor = shape.fill?.none ? "transparent" : shape.fill?.color ?? "transparent";
  const strokeColor = shape.stroke?.none ? "transparent" : shape.stroke?.color ?? "transparent";
  const lineWidth = Math.max(0, (shape.stroke?.widthPx ?? (shape.geometry === "line" ? 2 : 1)) * zoomFactor);
  const vectorShape = resolveShapeVector(shape);
  const opacity = Math.min(shape.fill?.opacity ?? 1, shape.stroke?.opacity ?? 1);
  context.save();
  context.translate(rect.left + rect.width / 2, rect.top + rect.height / 2);
  if (shape.rotationDeg) {
    context.rotate(shape.rotationDeg * Math.PI / 180);
  }
  context.scale(shape.flipH ? -1 : 1, shape.flipV ? -1 : 1);
  context.globalAlpha *= opacity;
  context.lineWidth = lineWidth;
  context.strokeStyle = strokeColor;
  context.fillStyle = fillColor;
  applyCanvasShapeDash(context, shape.stroke?.dash, lineWidth);
  const localLeft = -rect.width / 2;
  const localTop = -rect.height / 2;
  if (vectorShape && typeof Path2D !== "undefined") {
    context.save();
    context.translate(localLeft, localTop);
    context.scale(
      rect.width / Math.max(1, vectorShape.viewBox.width),
      rect.height / Math.max(1, vectorShape.viewBox.height)
    );
    const path = getCachedCanvasPath2D(vectorShape.path);
    if (!path) {
      context.restore();
      context.restore();
      return;
    }
    if (fillColor !== "transparent") {
      context.fill(path);
    }
    if (strokeColor !== "transparent" && lineWidth > 0) {
      context.stroke(path);
    }
    context.restore();
  } else if (shape.geometry === "ellipse") {
    context.beginPath();
    context.ellipse(0, 0, rect.width / 2, rect.height / 2, 0, 0, Math.PI * 2);
    if (fillColor !== "transparent") {
      context.fill();
    }
    if (strokeColor !== "transparent" && lineWidth > 0) {
      context.stroke();
    }
  } else {
    const radius = shape.geometry === "roundRect" ? 12 * zoomFactor : 0;
    drawCanvasRoundedRect(context, localLeft, localTop, rect.width, rect.height, radius);
    if (fillColor !== "transparent") {
      context.fill();
    }
    if (strokeColor !== "transparent" && lineWidth > 0) {
      context.stroke();
    }
  }
  drawStaticShapeText(context, shape, localLeft, localTop, rect.width, rect.height, zoomFactor);
  context.restore();
}
function drawStaticFormControl(context, control2, rect, palette, zoomFactor, sheetSurface = SHEET_SURFACE) {
  const label = resolveFormControlLabel(control2);
  const stroke = paletteIsDark(palette) ? "#cbd5e1" : "#475569";
  const textColor = control2.textColor ?? "#000000";
  const fontSizePx = Math.max(9 * zoomFactor, (control2.fontSizePt ?? 9) * 96 / 72 * zoomFactor);
  const iconSize = Math.min(14 * zoomFactor, Math.max(0, rect.height - 4 * zoomFactor));
  const controlChecked = isFormControlChecked(control2);
  const controlMixed = isFormControlMixed(control2);
  context.save();
  context.font = `400 ${fontSizePx}px ${control2.fontFamily ?? "Calibri, sans-serif"}`;
  context.textBaseline = "middle";
  context.fillStyle = textColor;
  context.strokeStyle = stroke;
  context.lineWidth = Math.max(1, zoomFactor);
  if (control2.kind === "group-box") {
    const labelInset = label ? Math.max(7, fontSizePx * 0.5) : 0;
    drawCanvasRoundedRect(context, rect.left, rect.top + labelInset, rect.width, Math.max(0, rect.height - labelInset), 2 * zoomFactor);
    context.stroke();
    if (label) {
      context.fillStyle = sheetSurface;
      const labelWidth = Math.min(rect.width - 16 * zoomFactor, measureCanvasTextWidth(context, label) + 8 * zoomFactor);
      context.fillRect(rect.left + 8 * zoomFactor, rect.top, labelWidth, fontSizePx * 1.2);
      context.fillStyle = textColor;
      context.textAlign = "left";
      context.fillText(label, rect.left + 12 * zoomFactor, rect.top + fontSizePx * 0.55);
    }
    context.restore();
    return;
  }
  if (control2.kind === "button" || control2.kind === "dropdown" || control2.kind === "editbox" || control2.kind === "listbox" || control2.kind === "scrollbar" || control2.kind === "spinner" || control2.kind === "unknown") {
    if (control2.kind === "button") {
      const gradient = context.createLinearGradient(rect.left, rect.top, rect.left, rect.top + rect.height);
      gradient.addColorStop(0, "#f8fafc");
      gradient.addColorStop(1, "#e2e8f0");
      context.fillStyle = gradient;
    } else {
      context.fillStyle = "transparent";
    }
    drawCanvasRoundedRect(context, rect.left, rect.top, rect.width, rect.height, control2.kind === "button" ? 4 * zoomFactor : 2 * zoomFactor);
    if (control2.kind === "button") {
      context.fill();
    }
    context.stroke();
  }
  let textLeft = rect.left + 2 * zoomFactor;
  const textRightInset = control2.kind === "dropdown" ? 18 * zoomFactor : 6 * zoomFactor;
  if (control2.kind === "checkbox") {
    context.strokeRect(rect.left + 2 * zoomFactor, rect.top + (rect.height - iconSize) / 2, iconSize, iconSize);
    if (controlChecked || controlMixed) {
      context.fillStyle = paletteIsDark(palette) ? "#60a5fa" : "#2563eb";
      context.fillRect(rect.left + 2 * zoomFactor + 1.5, rect.top + (rect.height - iconSize) / 2 + 1.5, Math.max(0, iconSize - 3), Math.max(0, iconSize - 3));
      context.strokeStyle = paletteIsDark(palette) ? "#020617" : "#ffffff";
      context.beginPath();
      if (controlMixed) {
        context.moveTo(rect.left + 2 * zoomFactor + iconSize * 0.25, rect.top + rect.height / 2);
        context.lineTo(rect.left + 2 * zoomFactor + iconSize * 0.75, rect.top + rect.height / 2);
      } else {
        context.moveTo(rect.left + 2 * zoomFactor + iconSize * 0.24, rect.top + rect.height / 2 + iconSize * 0.06);
        context.lineTo(rect.left + 2 * zoomFactor + iconSize * 0.45, rect.top + rect.height / 2 + iconSize * 0.26);
        context.lineTo(rect.left + 2 * zoomFactor + iconSize * 0.8, rect.top + rect.height / 2 - iconSize * 0.2);
      }
      context.stroke();
    }
    textLeft += iconSize + 4 * zoomFactor;
  } else if (control2.kind === "radio") {
    context.beginPath();
    context.arc(rect.left + 2 * zoomFactor + iconSize / 2, rect.top + rect.height / 2, iconSize / 2, 0, Math.PI * 2);
    context.stroke();
    if (controlChecked) {
      context.fillStyle = paletteIsDark(palette) ? "#60a5fa" : "#2563eb";
      context.beginPath();
      context.arc(rect.left + 2 * zoomFactor + iconSize / 2, rect.top + rect.height / 2, iconSize * 0.25, 0, Math.PI * 2);
      context.fill();
    }
    textLeft += iconSize + 4 * zoomFactor;
  }
  if (label) {
    const maxTextWidth = Math.max(0, rect.left + rect.width - textLeft - textRightInset);
    const text = truncateCanvasText(context, label, maxTextWidth);
    context.fillStyle = textColor;
    context.textAlign = control2.textAlign === "right" ? "right" : control2.textAlign === "center" ? "center" : "left";
    const textX = context.textAlign === "right" ? rect.left + rect.width - textRightInset : context.textAlign === "center" ? textLeft + maxTextWidth / 2 : textLeft;
    context.fillText(text, textX, rect.top + rect.height / 2);
  }
  if (control2.kind === "dropdown") {
    context.fillStyle = textColor;
    context.textAlign = "center";
    context.fillText("\u25BC", rect.left + rect.width - 10 * zoomFactor, rect.top + rect.height / 2);
  }
  context.restore();
}
function resolveConditionalDataBarForCell(row2, col, worksheet, sheet, metricsCache) {
  const rules = sheet?.conditionalFormatRules ?? [];
  const matchingRule = rules.find(
    (rule) => rule.kind === "dataBar" && rule.ranges.some((range) => isCellInRange({ row: row2, col }, range))
  );
  if (!matchingRule) {
    return null;
  }
  const numericValue = getCellNumericValue(worksheet, row2, col);
  if (numericValue === null) {
    return null;
  }
  const cacheKey = buildConditionalFormatRuleKey(matchingRule);
  let ruleValues = metricsCache.get(cacheKey);
  if (!ruleValues) {
    ruleValues = matchingRule.ranges.flatMap((range) => {
      const values = [];
      for (let targetRow = range.start.row; targetRow <= range.end.row; targetRow += 1) {
        for (let targetCol = range.start.col; targetCol <= range.end.col; targetCol += 1) {
          const value = getCellNumericValue(worksheet, targetRow, targetCol);
          if (value !== null) {
            values.push(value);
          }
        }
      }
      return values;
    });
    metricsCache.set(cacheKey, ruleValues);
  }
  const minValue = resolveConditionalRuleThreshold(matchingRule.cfvos[0], ruleValues);
  const maxValue = resolveConditionalRuleThreshold(matchingRule.cfvos[matchingRule.cfvos.length - 1], ruleValues);
  if (minValue === null || maxValue === null) {
    return null;
  }
  const minLength = Number.isFinite(matchingRule.minLength ?? Number.NaN) ? matchingRule.minLength ?? 10 : 10;
  const maxLength = Number.isFinite(matchingRule.maxLength ?? Number.NaN) ? matchingRule.maxLength ?? 90 : 90;
  const span = maxValue - minValue;
  const ratio = span === 0 ? numericValue >= maxValue ? 1 : 0 : (numericValue - minValue) / span;
  const widthPercent = minLength + Math.max(0, Math.min(1, ratio)) * (maxLength - minLength);
  const color = resolveWorkbookColor(matchingRule.color, sheet?.themePalette);
  if (!color || widthPercent <= 0) {
    return null;
  }
  return {
    axisColor: resolveWorkbookColor(matchingRule.axisColor, sheet?.themePalette) ?? void 0,
    border: matchingRule.border ?? void 0,
    borderColor: resolveWorkbookColor(matchingRule.borderColor, sheet?.themePalette) ?? void 0,
    color,
    gradient: matchingRule.gradient ?? void 0,
    negativeBorderColor: resolveWorkbookColor(matchingRule.negativeBorderColor, sheet?.themePalette) ?? void 0,
    negativeFillColor: resolveWorkbookColor(matchingRule.negativeFillColor, sheet?.themePalette) ?? void 0,
    widthPercent
  };
}
function resolveConditionalColorScaleForCell(row2, col, worksheet, sheet, metricsCache) {
  const rules = sheet?.conditionalFormatRules ?? [];
  const matchingRule = rules.find(
    (rule) => rule.kind === "colorScale" && rule.ranges.some((range) => isCellInRange({ row: row2, col }, range))
  );
  if (!matchingRule) {
    return null;
  }
  const numericValue = getCellNumericValue(worksheet, row2, col);
  if (numericValue === null) {
    return null;
  }
  const cacheKey = buildConditionalFormatRuleKey(matchingRule);
  let ruleValues = metricsCache.get(cacheKey);
  if (!ruleValues) {
    ruleValues = matchingRule.ranges.flatMap((range) => {
      const values = [];
      for (let targetRow = range.start.row; targetRow <= range.end.row; targetRow += 1) {
        for (let targetCol = range.start.col; targetCol <= range.end.col; targetCol += 1) {
          const value = getCellNumericValue(worksheet, targetRow, targetCol);
          if (value !== null) {
            values.push(value);
          }
        }
      }
      return values;
    });
    metricsCache.set(cacheKey, ruleValues);
  }
  const colors = matchingRule.colors.map((color) => resolveWorkbookColor(color, sheet?.themePalette)).filter((color) => typeof color === "string");
  const thresholds = matchingRule.cfvos.map((threshold) => resolveConditionalRuleThreshold(threshold, ruleValues)).filter((value) => typeof value === "number" && Number.isFinite(value));
  if (colors.length < 2 || thresholds.length < 2) {
    return null;
  }
  const segments = Math.min(colors.length, thresholds.length) - 1;
  let resolvedColor = colors[colors.length - 1];
  for (let index = 0; index < segments; index += 1) {
    const startValue = thresholds[index] ?? thresholds[0];
    const endValue = thresholds[index + 1] ?? thresholds[thresholds.length - 1];
    if (numericValue <= endValue || index === segments - 1) {
      const ratio = endValue === startValue ? 1 : (numericValue - startValue) / (endValue - startValue);
      resolvedColor = mixRgbColor(colors[index] ?? colors[0], colors[index + 1] ?? colors[colors.length - 1], Math.max(0, Math.min(1, ratio)));
      break;
    }
  }
  return { color: resolvedColor };
}
function resolveConditionalIconForCell(row2, col, worksheet, sheet, metricsCache) {
  const rules = sheet?.conditionalFormatRules ?? [];
  const matchingRule = rules.find(
    (rule) => rule.kind === "iconSet" && rule.ranges.some((range) => isCellInRange({ row: row2, col }, range))
  );
  if (!matchingRule) {
    return null;
  }
  const numericValue = getCellNumericValue(worksheet, row2, col);
  if (numericValue === null) {
    return null;
  }
  const cacheKey = buildConditionalFormatRuleKey(matchingRule);
  let ruleValues = metricsCache.get(cacheKey);
  if (!ruleValues) {
    ruleValues = matchingRule.ranges.flatMap((range) => {
      const values = [];
      for (let targetRow = range.start.row; targetRow <= range.end.row; targetRow += 1) {
        for (let targetCol = range.start.col; targetCol <= range.end.col; targetCol += 1) {
          const value = getCellNumericValue(worksheet, targetRow, targetCol);
          if (value !== null) {
            values.push(value);
          }
        }
      }
      return values;
    });
    metricsCache.set(cacheKey, ruleValues);
  }
  const thresholds = matchingRule.cfvos.map((threshold) => resolveConditionalRuleThreshold(threshold, ruleValues));
  let selectedIndex = 0;
  thresholds.forEach((threshold, index) => {
    if (threshold !== null && numericValue >= threshold) {
      selectedIndex = index;
    }
  });
  const iconIndex = matchingRule.reverse ? Math.max(0, matchingRule.icons.length - 1 - selectedIndex) : selectedIndex;
  const icon = matchingRule.icons[Math.min(iconIndex, matchingRule.icons.length - 1)];
  return icon ? buildConditionalIcon(icon.iconSet, icon.iconId) : null;
}
function resolveCellContentJustify(verticalAlign) {
  if (verticalAlign === "middle") {
    return "center";
  }
  if (verticalAlign === "top") {
    return "flex-start";
  }
  return "flex-end";
}
function resolveCellContentAlignItems(textAlign) {
  if (textAlign === "center") {
    return "center";
  }
  if (textAlign === "right" || textAlign === "end") {
    return "flex-end";
  }
  return "flex-start";
}
function GridRow({
  actualRow,
  editingCell,
  editingValue,
  formulaReferences,
  editorBoxShadow,
  editorRef,
  editorInputRef,
  cellEditorStyle,
  onFocusEditorOverlay,
  frozenRowHeaderZIndex,
  getCellData,
  headerLabelLiveScale,
  leadingSpacerWidth,
  onCellClick,
  onCellDoubleClick,
  onCellPointerDown,
  onEditingBlur,
  onEditingCancel,
  onEditingCommit,
  onEditingNavigate,
  onEditingValueChange,
  onRowHeaderRef,
  onRowPointerDown,
  onRowResizeDoubleClick,
  onRowResizePointerDown,
  palette,
  readOnly,
  renderCellAdornment,
  rowHeight,
  rowHeaderZIndex,
  rowHeaderWidth,
  stickyLeftByCol,
  stickyTop,
  trailingSpacerWidth,
  visibleCols,
  zoomFactor
}) {
  const gutterSeparatorShadow = `inset -1px 0 0 ${palette.border}, inset 0 -1px 0 ${palette.border}`;
  return /* @__PURE__ */ jsxs8("tr", { "data-xlsx-row": actualRow, style: { height: rowHeight }, children: [
    /* @__PURE__ */ jsxs8(
      "td",
      {
        ref: (element) => onRowHeaderRef(actualRow, element),
        onPointerDown: (event) => onRowPointerDown(event, actualRow),
        style: {
          backgroundColor: palette.rowHeaderSurface,
          borderBottom: "none",
          borderRight: "none",
          boxSizing: "border-box",
          boxShadow: gutterSeparatorShadow,
          color: palette.headerText,
          fontSize: scaleCssLengthExpression("11px", zoomFactor),
          height: rowHeight,
          left: 0,
          maxHeight: rowHeight,
          minWidth: rowHeaderWidth,
          padding: scaleCssLengthExpression("2px 4px", zoomFactor),
          position: "sticky",
          top: stickyTop,
          textAlign: "center",
          userSelect: "none",
          width: rowHeaderWidth,
          zIndex: stickyTop !== void 0 ? frozenRowHeaderZIndex : rowHeaderZIndex
        },
        children: [
          /* @__PURE__ */ jsx11("div", { style: { position: "relative" }, children: /* @__PURE__ */ jsx11(
            "span",
            {
              style: {
                display: "inline-block",
                transform: headerLabelLiveScale !== 1 ? `scale(${1 / headerLabelLiveScale})` : void 0,
                transformOrigin: "center center"
              },
              children: actualRow + 1
            }
          ) }),
          /* @__PURE__ */ jsx11(
            "div",
            {
              onDoubleClick: (event) => {
                event.stopPropagation();
                onRowResizeDoubleClick(actualRow);
              },
              onPointerDown: (event) => onRowResizePointerDown(event, actualRow, rowHeight),
              style: {
                bottom: 0,
                cursor: "row-resize",
                height: HEADER_RESIZE_HANDLE_PX,
                left: 0,
                position: "absolute",
                width: "100%",
                zIndex: 5
              }
            }
          )
        ]
      }
    ),
    leadingSpacerWidth > 0 ? /* @__PURE__ */ jsx11(
      "td",
      {
        "aria-hidden": "true",
        style: {
          backgroundColor: "transparent",
          border: "none",
          padding: 0,
          width: leadingSpacerWidth
        }
      }
    ) : null,
    visibleCols.map(({ actualCol, key }) => {
      const cellData = getCellData(actualRow, actualCol);
      if (cellData.isMergedSecondary) {
        return null;
      }
      const cell = { row: actualRow, col: actualCol };
      const isEditing = isSameCell(editingCell, cell);
      const isSpilling = Boolean(cellData.spillWidth && cellData.spillWidth > 0);
      const adornment = renderCellAdornment ? renderCellAdornment(cell) : null;
      const stickyLeft = stickyLeftByCol.get(actualCol);
      const validationRight = adornment ? 24 : 4;
      const cellStyle = {
        ...cellData.style,
        boxSizing: "border-box",
        cursor: isEditing ? "text" : cellData.hyperlink ? "pointer" : "cell"
      };
      if (!cellData.rowSpan) {
        cellStyle.height = rowHeight;
        cellStyle.maxHeight = rowHeight;
      }
      if (isSpilling) {
        cellStyle.position = "relative";
        cellStyle.zIndex = 2;
      }
      if (cellData.conditionalColorScale) {
        cellStyle.backgroundColor = cellData.conditionalColorScale.color;
      }
      if (cellData.conditionalColorScale || cellData.conditionalDataBar || cellData.conditionalIcon) {
        cellStyle.position = "relative";
      }
      if (cellData.chartHighlight) {
        cellStyle.position = cellStyle.position ?? "relative";
      }
      if (cellData.isTableHeader) {
        cellStyle.position = "relative";
        cellStyle.zIndex = Math.max(Number(cellStyle.zIndex ?? 0), 4);
      }
      if (stickyTop !== void 0) {
        cellStyle.position = "sticky";
        cellStyle.top = stickyTop;
        cellStyle.zIndex = Math.max(Number(cellStyle.zIndex ?? 0), 28);
      }
      if (stickyLeft !== void 0) {
        cellStyle.left = stickyLeft;
        cellStyle.position = "sticky";
        cellStyle.zIndex = Math.max(Number(cellStyle.zIndex ?? 0), stickyTop !== void 0 ? 30 : 24);
      }
      if (isSpilling) {
        cellStyle.overflow = "visible";
        cellStyle.textOverflow = "clip";
        cellStyle.position = cellStyle.position ?? "relative";
        cellStyle.zIndex = Math.max(Number(cellStyle.zIndex ?? 0), stickyTop !== void 0 ? 32 : 6);
      }
      if (isEditing) {
        cellStyle.padding = 0;
        cellStyle.position = stickyTop !== void 0 || stickyLeft !== void 0 ? "sticky" : "relative";
        cellStyle.overflow = "visible";
        cellStyle.zIndex = 42;
      }
      const cellContentStyle = {
        alignItems: "stretch",
        display: "flex",
        flexDirection: "column",
        font: "inherit",
        height: "100%",
        justifyContent: resolveCellContentJustify(cellStyle.verticalAlign),
        maxHeight: cellData.rowSpan ? void 0 : rowHeight,
        minHeight: 0,
        overflow: "hidden",
        pointerEvents: "none",
        textAlign: "inherit",
        textDecoration: "inherit",
        textOverflow: "inherit",
        whiteSpace: "inherit",
        width: "100%",
        wordBreak: "inherit"
      };
      const hasLineBreak = /[\r\n]/.test(cellData.value);
      const usesWrappedText = cellData.style.whiteSpace === "pre-wrap" || hasLineBreak;
      const wrappedTextStyle = usesWrappedText ? {
        display: "block",
        flex: "0 0 auto",
        maxWidth: "100%",
        minWidth: 0,
        whiteSpace: hasLineBreak && cellData.style.whiteSpace === "nowrap" ? "pre-wrap" : void 0
      } : null;
      if (usesWrappedText) {
        cellContentStyle.overflow = "clip";
      }
      const trailingInset = (adornment ? 20 : 0) + (cellData.pivotControlInset ?? 0);
      if (cellData.conditionalDataBar) {
        cellContentStyle.position = "relative";
        cellContentStyle.zIndex = 1;
      }
      if (cellData.chartHighlight) {
        cellContentStyle.position = cellContentStyle.position ?? "relative";
        cellContentStyle.zIndex = Math.max(Number(cellContentStyle.zIndex ?? 0), 1);
      }
      if (trailingInset > 0) {
        cellContentStyle.paddingRight = (trailingInset + 4) * zoomFactor;
      }
      if (cellData.conditionalIcon) {
        cellContentStyle.boxSizing = "border-box";
        cellContentStyle.paddingLeft = 18 * zoomFactor;
        cellContentStyle.position = "relative";
        cellContentStyle.zIndex = 1;
      }
      if (cellData.sparkline || cellData.checkboxState !== null) {
        cellContentStyle.alignItems = "center";
        cellContentStyle.justifyContent = "center";
      }
      if (cellData.textRotationDeg) {
        cellContentStyle.alignItems = resolveCellContentAlignItems(cellStyle.textAlign);
        cellContentStyle.overflow = "visible";
      }
      if (cellData.shrinkToFitFontSizePx) {
        cellContentStyle.fontSize = cellData.shrinkToFitFontSizePx;
        cellContentStyle.lineHeight = `${resolveCanvasLineHeight(cellData.style, cellData.shrinkToFitFontSizePx)}px`;
      }
      const rotatedTextWidth = cellData.textRotationDeg ? measureCellTextWidth(cellData) : 0;
      const rotatedTextHeight = resolveCanvasLineHeight(cellData.style, 12 * zoomFactor);
      const rotatedTextBounds = cellData.textRotationDeg ? resolveRotatedTextBounds(rotatedTextWidth, rotatedTextHeight, cellData.textRotationDeg) : null;
      const rotatedTextStyle = cellData.textRotationDeg ? {
        display: "inline-block",
        left: "50%",
        lineHeight: `${rotatedTextHeight}px`,
        maxWidth: "none",
        position: "absolute",
        top: "50%",
        transform: `translate(-50%, -50%) rotate(${cellData.textRotationDeg}deg)`,
        transformOrigin: "center center",
        whiteSpace: "nowrap",
        width: "max-content"
      } : null;
      const title = [cellData.hyperlink?.tooltip, cellData.validation?.message, cellData.value].filter((value, index, values) => typeof value === "string" && value.length > 0 && values.indexOf(value) === index).join("\n");
      return /* @__PURE__ */ jsxs8(
        "td",
        {
          "data-xlsx-cell": `${actualRow}:${actualCol}`,
          colSpan: cellData.colSpan,
          rowSpan: cellData.rowSpan,
          onDoubleClick: () => {
            if (readOnly) {
              return;
            }
            onCellDoubleClick(cell);
          },
          onClick: () => onCellClick(cell, cellData),
          onPointerDown: (event) => onCellPointerDown(event, cell),
          style: cellStyle,
          title,
          children: [
            cellData.chartHighlight ? /* @__PURE__ */ jsx11(
              "div",
              {
                "aria-hidden": "true",
                style: {
                  backgroundColor: cellData.chartHighlight.fillColor,
                  borderBottom: cellData.chartHighlight.borderBottom ? `2px solid ${cellData.chartHighlight.strokeColor}` : void 0,
                  borderLeft: cellData.chartHighlight.borderLeft ? `2px solid ${cellData.chartHighlight.strokeColor}` : void 0,
                  borderRight: cellData.chartHighlight.borderRight ? `2px solid ${cellData.chartHighlight.strokeColor}` : void 0,
                  borderTop: cellData.chartHighlight.borderTop ? `2px solid ${cellData.chartHighlight.strokeColor}` : void 0,
                  boxSizing: "border-box",
                  inset: 0,
                  pointerEvents: "none",
                  position: "absolute"
                },
                children: /* @__PURE__ */ jsx11(
                  ReferenceRangeHandles,
                  {
                    color: cellData.chartHighlight.strokeColor,
                    top: cellData.chartHighlight.borderTop,
                    bottom: cellData.chartHighlight.borderBottom,
                    left: cellData.chartHighlight.borderLeft,
                    right: cellData.chartHighlight.borderRight
                  }
                )
              }
            ) : null,
            cellData.conditionalDataBar ? /* @__PURE__ */ jsx11(
              "div",
              {
                "aria-hidden": "true",
                style: {
                  alignItems: "center",
                  display: "flex",
                  inset: DATA_BAR_INSET * zoomFactor,
                  pointerEvents: "none",
                  position: "absolute",
                  zIndex: 0
                },
                children: /* @__PURE__ */ jsx11(
                  "div",
                  {
                    style: {
                      background: cellData.conditionalDataBar.gradient === false ? cellData.conditionalDataBar.color : `linear-gradient(90deg, ${cellData.conditionalDataBar.color} 0%, ${lightenColor(cellData.conditionalDataBar.color, DATA_BAR_GRADIENT_TINT)} 100%)`,
                      border: cellData.conditionalDataBar.border !== false && cellData.conditionalDataBar.borderColor ? `1px solid ${cellData.conditionalDataBar.borderColor}` : "none",
                      boxSizing: "border-box",
                      height: "100%",
                      opacity: 1,
                      width: `${cellData.conditionalDataBar.widthPercent}%`
                    }
                  }
                )
              }
            ) : null,
            adornment,
            cellData.conditionalIcon ? /* @__PURE__ */ jsx11(
              "div",
              {
                "aria-hidden": "true",
                style: {
                  alignItems: "center",
                  display: "inline-flex",
                  justifyContent: "center",
                  pointerEvents: "none",
                  position: "absolute",
                  left: 4 * zoomFactor,
                  top: "50%",
                  transform: "translateY(-50%)",
                  zIndex: 2
                },
                children: renderConditionalIcon(cellData.conditionalIcon, zoomFactor)
              }
            ) : null,
            isSpilling && !isEditing ? /* @__PURE__ */ jsx11("div", { "aria-hidden": "true", style: {
              backgroundColor: cellStyle.backgroundColor ?? palette.surface,
              position: "absolute",
              left: cellData.spillSide === "left" ? cellData.spillOffsetX : "calc(100% - 1px)",
              top: 0,
              width: cellData.spillSide === "left" ? -(cellData.spillOffsetX ?? 0) + 1 : `calc(${(cellData.spillWidth ?? 0) + getHorizontalPadding(cellStyle.padding) + 1}px - 100%)`,
              height: "calc(100% - 1px)",
              pointerEvents: "none"
            } }) : null,
            isEditing ? /* @__PURE__ */ jsx11(
              CellEditor,
              {
                editorRef,
                inputRef: editorInputRef,
                onFocusOverlay: onFocusEditorOverlay,
                value: editingValue,
                wrapText: cellData.style.whiteSpace === "pre-wrap",
                references: formulaReferences,
                onBlur: onEditingBlur,
                onChange: onEditingValueChange,
                onCommit: onEditingCommit,
                onCancel: onEditingCancel,
                onNavigate: onEditingNavigate,
                style: {
                  backgroundColor: cellStyle.backgroundColor ?? palette.surface,
                  boxShadow: editorBoxShadow,
                  color: cellStyle.color ?? palette.text,
                  font: "inherit",
                  lineHeight: cellData.style.lineHeight,
                  verticalAlign: cellData.style.verticalAlign,
                  padding: cellData.style.padding,
                  ...cellEditorStyle
                }
              }
            ) : isSpilling ? /* @__PURE__ */ jsx11(
              "div",
              {
                style: {
                  left: cellData.spillOffsetX ?? 0,
                  maxWidth: cellData.spillWidth,
                  overflow: "visible",
                  pointerEvents: "none",
                  position: "relative",
                  whiteSpace: "inherit",
                  width: cellData.spillWidth
                },
                children: renderRichCellText(cellData)
              }
            ) : cellData.sparkline ? /* @__PURE__ */ jsx11(
              "div",
              {
                style: {
                  alignItems: "center",
                  display: "flex",
                  height: "100%",
                  justifyContent: "center",
                  pointerEvents: "none",
                  width: "100%"
                },
                children: renderSparkline(cellData.sparkline.config, cellData.sparkline.values, palette)
              }
            ) : cellData.checkboxState != null ? /* @__PURE__ */ jsx11(
              "div",
              {
                style: {
                  alignItems: "center",
                  display: "flex",
                  height: "100%",
                  justifyContent: "center",
                  pointerEvents: "none",
                  width: "100%"
                },
                children: renderCheckboxControl(cellData.checkboxState, palette, zoomFactor)
              }
            ) : /* @__PURE__ */ jsx11("div", { style: cellContentStyle, children: rotatedTextStyle ? /* @__PURE__ */ jsx11("span", { style: { ...rotatedTextBounds, flex: "0 0 auto", position: "relative" }, children: /* @__PURE__ */ jsx11("span", { style: rotatedTextStyle, children: renderRichCellText(cellData) }) }) : wrappedTextStyle ? /* @__PURE__ */ jsx11("span", { style: wrappedTextStyle, children: renderRichCellText(cellData) }) : renderRichCellText(cellData) })
          ]
        },
        key
      );
    }),
    trailingSpacerWidth > 0 ? /* @__PURE__ */ jsx11(
      "td",
      {
        "aria-hidden": "true",
        style: {
          backgroundColor: "transparent",
          border: "none",
          padding: 0,
          width: trailingSpacerWidth
        }
      }
    ) : null
  ] });
}
var MemoGridRow = React15.memo(GridRow, (prev, next) => {
  if (prev.actualRow !== next.actualRow || prev.rowHeight !== next.rowHeight || prev.headerLabelLiveScale !== next.headerLabelLiveScale || prev.palette !== next.palette || prev.readOnly !== next.readOnly || prev.visibleCols !== next.visibleCols || prev.leadingSpacerWidth !== next.leadingSpacerWidth || prev.rowHeaderWidth !== next.rowHeaderWidth || prev.stickyLeftByCol !== next.stickyLeftByCol || prev.stickyTop !== next.stickyTop || prev.trailingSpacerWidth !== next.trailingSpacerWidth || prev.zoomFactor !== next.zoomFactor || prev.getCellData !== next.getCellData || prev.onCellClick !== next.onCellClick || prev.onCellDoubleClick !== next.onCellDoubleClick || prev.onCellPointerDown !== next.onCellPointerDown || prev.onEditingBlur !== next.onEditingBlur || prev.onEditingCancel !== next.onEditingCancel || prev.onEditingCommit !== next.onEditingCommit || prev.onEditingNavigate !== next.onEditingNavigate || prev.onEditingValueChange !== next.onEditingValueChange || prev.onRowHeaderRef !== next.onRowHeaderRef || prev.onRowPointerDown !== next.onRowPointerDown || prev.onRowResizeDoubleClick !== next.onRowResizeDoubleClick || prev.onRowResizePointerDown !== next.onRowResizePointerDown || prev.renderCellAdornment !== next.renderCellAdornment || prev.cellEditorStyle !== next.cellEditorStyle || prev.onFocusEditorOverlay !== next.onFocusEditorOverlay) {
    return false;
  }
  const prevEditingCol = prev.editingCell?.row === prev.actualRow ? prev.editingCell.col : -1;
  const nextEditingCol = next.editingCell?.row === next.actualRow ? next.editingCell.col : -1;
  if (prevEditingCol !== nextEditingCol) {
    return false;
  }
  if (prevEditingCol !== -1 && (prev.editingValue !== next.editingValue || prev.formulaReferences !== next.formulaReferences || prev.editorBoxShadow !== next.editorBoxShadow)) {
    return false;
  }
  return true;
});
function XlsxViewerProviderWithInlineController({
  children: children2,
  isDark = false,
  ...options2
}) {
  const controller = useXlsxViewerController(options2);
  return /* @__PURE__ */ jsx11(ViewerAppearanceContext.Provider, { value: { isDark }, children: /* @__PURE__ */ jsx11(ViewerContext.Provider, { value: controller, children: children2 }) });
}
function XlsxViewerProvider({ children: children2, controller, isDark = false, ...options2 }) {
  if (controller) {
    return /* @__PURE__ */ jsx11(ViewerAppearanceContext.Provider, { value: { isDark }, children: /* @__PURE__ */ jsx11(ViewerContext.Provider, { value: controller, children: children2 }) });
  }
  return /* @__PURE__ */ jsx11(XlsxViewerProviderWithInlineController, { ...options2, isDark, children: children2 });
}
function useXlsxViewer() {
  const context = React15.useContext(ViewerContext);
  if (!context) {
    throw new Error("useXlsxViewer must be used inside XlsxViewer or XlsxViewerProvider.");
  }
  return context;
}
function useXlsxViewerSelection() {
  const {
    activeCell,
    activeCellAddress,
    clearSelection,
    selectedRangeAddress,
    selectCell,
    selectRange,
    selectRanges,
    selectionRanges,
    selection
  } = useXlsxViewer();
  return React15.useMemo(
    () => ({
      activeCell,
      activeCellAddress,
      clearSelection,
      selectedRangeAddress,
      selectCell,
      selectRange,
      selectRanges,
      selectionRanges,
      selection
    }),
    [activeCell, activeCellAddress, clearSelection, selectedRangeAddress, selectCell, selectRange, selectRanges, selectionRanges, selection]
  );
}
function useXlsxViewerLayout() {
  const { canChangeFreezePanes, canChangeVisibility, canFreezePanes, frozenPanes, hideRows, unhideRows, hideColumns, unhideColumns, freezePanes, unfreezePanes } = useXlsxViewer();
  return React15.useMemo(
    () => ({ canChangeFreezePanes, canChangeVisibility, canFreezePanes, frozenPanes, hideRows, unhideRows, hideColumns, unhideColumns, freezePanes, unfreezePanes }),
    [canChangeFreezePanes, canChangeVisibility, canFreezePanes, frozenPanes, hideRows, unhideRows, hideColumns, unhideColumns, freezePanes, unfreezePanes]
  );
}
function useXlsxViewerZoom() {
  const {
    canZoomIn,
    canZoomOut,
    defaultZoomScale,
    maxZoomScale,
    minZoomScale,
    resetZoom,
    setZoomScale,
    zoomIn,
    zoomOut,
    zoomScale
  } = useXlsxViewer();
  return React15.useMemo(
    () => ({
      canZoomIn,
      canZoomOut,
      defaultZoomScale,
      maxZoomScale,
      minZoomScale,
      resetZoom,
      setZoomScale,
      zoomIn,
      zoomOut,
      zoomScale
    }),
    [
      canZoomIn,
      canZoomOut,
      defaultZoomScale,
      maxZoomScale,
      minZoomScale,
      resetZoom,
      setZoomScale,
      zoomIn,
      zoomOut,
      zoomScale
    ]
  );
}
function useXlsxViewerEditing() {
  const {
    addFormControl,
    addSheet,
    canRedo,
    canUndo,
    clearSelectedCells,
    copySelectionToClipboard,
    defineNamedRange,
    fillSelection,
    formControls,
    getClipboardData,
    getCellDisplayValue: getCellDisplayValue2,
    getCellFormula,
    getFormControlItems,
    getSheetFormControls,
    mergeSelection,
    pasteFromClipboard,
    pasteStructuredClipboardData,
    pasteText,
    removeActiveSheet,
    removeFormControl,
    readOnly,
    redo,
    selectedCellFormula,
    selectedChartFormula,
    selectedFormula,
    selectedFormulaTarget,
    selectedValue,
    setCellFormula,
    setCellStyle,
    setCellStyles,
    setCellValue,
    setRangeStyle,
    setSelectedFormula,
    setSelectedCellFormula,
    setSelectedCellStyle,
    setSelectedCellValue,
    undo,
    unmergeSelection,
    updateFormControl
  } = useXlsxViewer();
  return React15.useMemo(
    () => ({
      addFormControl,
      addSheet,
      canRedo,
      canUndo,
      clearSelectedCells,
      copySelectionToClipboard,
      defineNamedRange,
      fillSelection,
      formControls,
      getClipboardData,
      getCellDisplayValue: getCellDisplayValue2,
      getCellFormula,
      getFormControlItems,
      getSheetFormControls,
      mergeSelection,
      pasteFromClipboard,
      pasteStructuredClipboardData,
      pasteText,
      removeActiveSheet,
      removeFormControl,
      readOnly,
      redo,
      selectedCellFormula,
      selectedChartFormula,
      selectedFormula,
      selectedFormulaTarget,
      selectedValue,
      setCellFormula,
      setCellStyle,
      setCellStyles,
      setCellValue,
      setRangeStyle,
      setSelectedFormula,
      setSelectedCellFormula,
      setSelectedCellStyle,
      setSelectedCellValue,
      undo,
      unmergeSelection,
      updateFormControl
    }),
    [
      addFormControl,
      addSheet,
      canRedo,
      canUndo,
      clearSelectedCells,
      copySelectionToClipboard,
      defineNamedRange,
      fillSelection,
      formControls,
      getClipboardData,
      getCellDisplayValue2,
      getCellFormula,
      getFormControlItems,
      getSheetFormControls,
      mergeSelection,
      pasteFromClipboard,
      pasteStructuredClipboardData,
      pasteText,
      removeActiveSheet,
      removeFormControl,
      readOnly,
      redo,
      selectedCellFormula,
      selectedChartFormula,
      selectedFormula,
      selectedFormulaTarget,
      selectedValue,
      setCellFormula,
      setCellStyle,
      setCellStyles,
      setCellValue,
      setRangeStyle,
      setSelectedFormula,
      setSelectedCellFormula,
      setSelectedCellStyle,
      setSelectedCellValue,
      undo,
      unmergeSelection,
      updateFormControl
    ]
  );
}
function useXlsxViewerTables() {
  const { sortState, sortTable, tables } = useXlsxViewer();
  return React15.useMemo(
    () => ({
      sortState,
      sortTable,
      tables
    }),
    [sortState, sortTable, tables]
  );
}
function useXlsxViewerPivots() {
  const { pivotTables, pivotFieldListVisible, setPivotFieldListVisible, getPivotSourceFields, getPivotTableAtCell, upsertPivotTable, refreshPivotTable, refreshAllPivotTables, removePivotTable, pivotDrillDown, showPivotDetails, createPivotChart, togglePivotGroup } = useXlsxViewer();
  return React15.useMemo(() => ({
    pivotTables,
    pivotFieldListVisible,
    setPivotFieldListVisible,
    getPivotSourceFields,
    getPivotTableAtCell,
    upsertPivotTable,
    refreshPivotTable,
    refreshAllPivotTables,
    removePivotTable,
    pivotDrillDown,
    showPivotDetails,
    createPivotChart,
    togglePivotGroup
  }), [pivotTables, pivotFieldListVisible, setPivotFieldListVisible, getPivotSourceFields, getPivotTableAtCell, upsertPivotTable, refreshPivotTable, refreshAllPivotTables, removePivotTable, pivotDrillDown, showPivotDetails, createPivotChart, togglePivotGroup]);
}
function useXlsxPivotTableEditor(options2) {
  return usePivotTableEditor(useXlsxViewer(), options2);
}
function useXlsxViewerImages() {
  const {
    arrangeDrawing,
    changeChartType,
    pasteDrawingFromClipboard,
    charts,
    clearSelectedChart,
    clearSelectedChartElement,
    clearSelectedImage,
    getChartById,
    getChartSeriesFormula,
    getSheetCharts,
    getImageById,
    getSheetImages,
    images,
    isChartsLoading,
    moveChartBy,
    moveImageBy,
    readOnly,
    resizeChartBy,
    resizeImageBy,
    selectedChart,
    selectedChartElement,
    selectedChartFormula,
    selectedChartId,
    selectedImage,
    selectedImageId,
    selectChart,
    selectChartElement,
    selectImage,
    setChartSeriesFormula,
    setChartRect,
    setImageRect,
    updateChart
  } = useXlsxViewer();
  return React15.useMemo(
    () => ({
      arrangeDrawing,
      changeChartType,
      pasteDrawingFromClipboard,
      charts,
      clearSelectedChart,
      clearSelectedChartElement,
      clearSelectedImage,
      getChartById,
      getChartSeriesFormula,
      getSheetCharts,
      getImageById,
      getSheetImages,
      images,
      isChartsLoading,
      moveChartBy,
      moveImageBy,
      readOnly,
      resizeChartBy,
      resizeImageBy,
      selectedChart,
      selectedChartElement,
      selectedChartFormula,
      selectedChartId,
      selectedImage,
      selectedImageId,
      selectChart,
      selectChartElement,
      selectImage,
      setChartSeriesFormula,
      setChartRect,
      setImageRect,
      updateChart
    }),
    [
      arrangeDrawing,
      changeChartType,
      pasteDrawingFromClipboard,
      charts,
      clearSelectedChart,
      clearSelectedChartElement,
      clearSelectedImage,
      getChartById,
      getChartSeriesFormula,
      getSheetCharts,
      getImageById,
      getSheetImages,
      images,
      isChartsLoading,
      moveChartBy,
      moveImageBy,
      readOnly,
      resizeChartBy,
      resizeImageBy,
      selectedChart,
      selectedChartElement,
      selectedChartFormula,
      selectedChartId,
      selectedImage,
      selectedImageId,
      selectChart,
      selectChartElement,
      selectImage,
      setChartSeriesFormula,
      setChartRect,
      setImageRect,
      updateChart
    ]
  );
}
function useXlsxViewerCharts() {
  const {
    activeTab,
    activeTabIndex,
    arrangeDrawing,
    changeChartType,
    pasteDrawingFromClipboard,
    charts,
    chartsheets,
    clearSelectedChart,
    clearSelectedChartElement,
    getChartById,
    getChartSeriesFormula,
    getChartsheetById,
    getSheetCharts,
    isChartsLoading,
    moveChartBy,
    readOnly,
    resizeChartBy,
    selectChart,
    selectedChart,
    selectedChartElement,
    selectedChartFormula,
    selectedChartId,
    selectChartElement,
    setActiveTabIndex,
    setChartSeriesFormula,
    setChartRect,
    tabs,
    updateChart
  } = useXlsxViewer();
  return React15.useMemo(
    () => ({
      activeTab,
      activeTabIndex,
      arrangeDrawing,
      changeChartType,
      pasteDrawingFromClipboard,
      charts,
      chartsheets,
      clearSelectedChart,
      clearSelectedChartElement,
      getChartById,
      getChartSeriesFormula,
      getChartsheetById,
      getSheetCharts,
      isChartsLoading,
      moveChartBy,
      readOnly,
      resizeChartBy,
      selectChart,
      selectedChart,
      selectedChartElement,
      selectedChartFormula,
      selectedChartId,
      selectChartElement,
      setActiveTabIndex,
      setChartSeriesFormula,
      setChartRect,
      tabs,
      updateChart
    }),
    [
      activeTab,
      activeTabIndex,
      arrangeDrawing,
      changeChartType,
      pasteDrawingFromClipboard,
      charts,
      chartsheets,
      clearSelectedChart,
      clearSelectedChartElement,
      getChartById,
      getChartSeriesFormula,
      getChartsheetById,
      getSheetCharts,
      isChartsLoading,
      moveChartBy,
      readOnly,
      resizeChartBy,
      selectChart,
      selectedChart,
      selectedChartElement,
      selectedChartFormula,
      selectedChartId,
      selectChartElement,
      setActiveTabIndex,
      setChartSeriesFormula,
      setChartRect,
      tabs,
      updateChart
    ]
  );
}
function useXlsxViewerThumbnails(options2 = {}) {
  const {
    getRowsBatchAsync,
    getSheetFormControls,
    getSheetImages,
    getSheetShapes,
    locale,
    workbook,
    sheets
  } = useXlsxViewer();
  const { headerBackgroundColor, headerTextColor, isDark } = React15.useContext(ViewerAppearanceContext);
  const palette = useViewerPalette(isDark, headerBackgroundColor, headerTextColor);
  const includeHeaders = options2.includeHeaders ?? true;
  const resolution = options2.resolution;
  const thumbnailImageCacheRef = React15.useRef(/* @__PURE__ */ new Map());
  const workerThumbnailRowBatchCacheRef = React15.useRef(/* @__PURE__ */ new Map());
  const workerThumbnailRowBatchRequestRef = React15.useRef(
    /* @__PURE__ */ new Map()
  );
  const isMountedRef = React15.useRef(false);
  const [thumbnailImageLoadVersion, setThumbnailImageLoadVersion] = React15.useState(0);
  const [workerThumbnailRowBatchVersion, setWorkerThumbnailRowBatchVersion] = React15.useState(0);
  React15.useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);
  React15.useEffect(() => {
    workerThumbnailRowBatchCacheRef.current.clear();
    workerThumbnailRowBatchRequestRef.current.clear();
    setWorkerThumbnailRowBatchVersion((version) => version + 1);
  }, [locale]);
  React15.useEffect(() => {
    const currentSheets = new Set(sheets);
    for (const sheet of workerThumbnailRowBatchCacheRef.current.keys()) {
      if (!currentSheets.has(sheet)) {
        workerThumbnailRowBatchCacheRef.current.delete(sheet);
      }
    }
    for (const sheet of workerThumbnailRowBatchRequestRef.current.keys()) {
      if (!currentSheets.has(sheet)) {
        workerThumbnailRowBatchRequestRef.current.delete(sheet);
      }
    }
  }, [sheets]);
  const getWorkerThumbnailRowBatch = React15.useCallback((sheet, startRow, endRow) => {
    const cachedBatch = workerThumbnailRowBatchCacheRef.current.get(sheet);
    if (cachedBatch && startRow >= cachedBatch.startRow && endRow <= cachedBatch.endRow) {
      return cachedBatch;
    }
    if (!getRowsBatchAsync) {
      return null;
    }
    const pendingRequest = workerThumbnailRowBatchRequestRef.current.get(sheet);
    if (!pendingRequest) {
      const request = {
        endRow: Math.max(endRow, cachedBatch?.endRow ?? endRow),
        startRow: Math.min(startRow, cachedBatch?.startRow ?? startRow)
      };
      workerThumbnailRowBatchRequestRef.current.set(sheet, request);
      void getRowsBatchAsync(
        sheet.workbookSheetIndex,
        request.startRow,
        request.endRow - request.startRow + 1
      ).then((rows) => {
        if (workerThumbnailRowBatchRequestRef.current.get(sheet) !== request) {
          return;
        }
        workerThumbnailRowBatchRequestRef.current.delete(sheet);
        if (!rows) {
          return;
        }
        workerThumbnailRowBatchCacheRef.current.set(
          sheet,
          buildWorksheetBatchWindow(rows, sheet, request.startRow, request.endRow)
        );
        if (isMountedRef.current) {
          setWorkerThumbnailRowBatchVersion((version) => version + 1);
        }
      }).catch(() => {
        if (workerThumbnailRowBatchRequestRef.current.get(sheet) === request) {
          workerThumbnailRowBatchRequestRef.current.delete(sheet);
        }
      });
    }
    return null;
  }, [getRowsBatchAsync]);
  const getThumbnailImage = React15.useCallback((image) => {
    if (typeof Image === "undefined") {
      return null;
    }
    const cacheKey = image.id;
    const cached = thumbnailImageCacheRef.current.get(cacheKey);
    if (cached && cached.src === image.src) {
      return cached.loaded && !cached.failed ? cached.image : null;
    }
    const imageElement = new Image();
    const entry = {
      failed: false,
      image: imageElement,
      loaded: false,
      src: image.src
    };
    thumbnailImageCacheRef.current.set(cacheKey, entry);
    imageElement.onload = () => {
      entry.loaded = true;
      if (isMountedRef.current) {
        setThumbnailImageLoadVersion((version) => version + 1);
      }
    };
    imageElement.onerror = () => {
      entry.failed = true;
      if (isMountedRef.current) {
        setThumbnailImageLoadVersion((version) => version + 1);
      }
    };
    imageElement.src = image.src;
    return null;
  }, []);
  const thumbnails = React15.useMemo(() => {
    return sheets.map((sheet, sheetIndex) => {
      const worksheet = workbook?.getSheet(sheet.workbookSheetIndex) ?? null;
      const sheetImages = getSheetImages(sheetIndex).filter((image) => image.src).sort((left, right) => left.zIndex - right.zIndex);
      const sheetShapes = getSheetShapes(sheetIndex);
      const sheetFormControls = getSheetFormControls(sheetIndex).filter((control2) => !control2.hidden);
      const drawingBounds = [
        ...sheetImages.map((image) => image.anchor),
        ...sheetShapes.map((shape) => shape.anchor),
        ...sheetFormControls.map((control2) => control2.anchor)
      ].reduce((bounds, anchor) => {
        const drawingBound = resolveAnchoredBounds(anchor) ?? {
          maxCol: 0,
          maxRow: 0,
          minCol: 0,
          minRow: 0
        };
        return {
          maxCol: Math.max(bounds?.maxCol ?? drawingBound.maxCol, drawingBound.maxCol),
          maxRow: Math.max(bounds?.maxRow ?? drawingBound.maxRow, drawingBound.maxRow),
          minCol: Math.min(bounds?.minCol ?? drawingBound.minCol, drawingBound.minCol),
          minRow: Math.min(bounds?.minRow ?? drawingBound.minRow, drawingBound.minRow)
        };
      }, null);
      const sheetMinUsedRow = (sheet.maxUsedRow ?? -1) >= (sheet.minUsedRow ?? 0) ? sheet.minUsedRow ?? 0 : void 0;
      const sheetMinUsedCol = (sheet.maxUsedCol ?? -1) >= (sheet.minUsedCol ?? 0) ? sheet.minUsedCol ?? 0 : void 0;
      const effectiveMinUsedRow = Math.max(0, Math.min(sheetMinUsedRow ?? drawingBounds?.minRow ?? 0, drawingBounds?.minRow ?? sheetMinUsedRow ?? 0));
      const effectiveMinUsedCol = Math.max(0, Math.min(sheetMinUsedCol ?? drawingBounds?.minCol ?? 0, drawingBounds?.minCol ?? sheetMinUsedCol ?? 0));
      const effectiveMaxUsedRow = Math.max(sheet.maxUsedRow ?? -1, drawingBounds?.maxRow ?? -1);
      const effectiveMaxUsedCol = Math.max(sheet.maxUsedCol ?? -1, drawingBounds?.maxCol ?? -1);
      const showGridLines = sheet.showGridLines ?? true;
      const hiddenRowSet = new Set(sheet.hiddenRows ?? []);
      const hiddenColSet = new Set(sheet.hiddenCols ?? []);
      const visibleRows = buildVisibleAxisIndices(
        sheet.visibleRows ?? [],
        Math.max(THUMBNAIL_FALLBACK_ROWS, effectiveMaxUsedRow + THUMBNAIL_FALLBACK_ROWS + 1),
        effectiveMaxUsedRow,
        hiddenRowSet
      );
      const visibleCols = buildVisibleAxisIndices(
        sheet.visibleCols ?? [],
        Math.max(THUMBNAIL_FALLBACK_COLS, effectiveMaxUsedCol + THUMBNAIL_FALLBACK_COLS + 1),
        effectiveMaxUsedCol,
        hiddenColSet
      );
      const resolveColumnWidthPx = (actualCol) => {
        if (worksheet && !hiddenColSet.has(actualCol)) {
          const width = worksheet.getColumnWidth(actualCol);
          if (width !== void 0 && width !== null) {
            return Math.max(
              resolveRenderedSheetAxisPixels(resolveSheetColumnWidthPixels(width, sheet.columnWidthCharacterWidthPx), showGridLines),
              DEFAULT_COL_WIDTH2 / 2
            );
          }
        }
        return Math.max(
          resolveRenderedSheetAxisPixels(
            sheet.colWidthOverridesPx[actualCol] ?? sheet.defaultColWidthPx ?? DEFAULT_COL_WIDTH2,
            showGridLines
          ),
          DEFAULT_COL_WIDTH2 / 2
        );
      };
      const resolveRowHeightPx = (actualRow) => {
        if (worksheet && !hiddenRowSet.has(actualRow)) {
          const height = worksheet.getRowHeight(actualRow);
          if (height !== void 0 && height !== null) {
            return Math.max(
              resolveRenderedSheetAxisPixels(resolveSheetRowHeightPixels(height), showGridLines),
              DEFAULT_ROW_HEIGHT2 / 1.5
            );
          }
        }
        return Math.max(
          resolveRenderedSheetAxisPixels(
            sheet.rowHeightOverridesPx[actualRow] ?? sheet.defaultRowHeightPx ?? DEFAULT_ROW_HEIGHT2,
            showGridLines
          ),
          DEFAULT_ROW_HEIGHT2 / 1.5
        );
      };
      const previewRows = resolveThumbnailAxisIndices({
        fallbackCount: THUMBNAIL_FALLBACK_ROWS,
        getSizePx: resolveRowHeightPx,
        maxCount: THUMBNAIL_MAX_ROWS,
        maxLogicalPixels: THUMBNAIL_MAX_SOURCE_HEIGHT_PX,
        maxUsedIndex: effectiveMaxUsedRow,
        minUsedIndex: effectiveMinUsedRow,
        precomputed: visibleRows
      });
      const previewCols = resolveThumbnailAxisIndices({
        fallbackCount: THUMBNAIL_FALLBACK_COLS,
        getSizePx: resolveColumnWidthPx,
        maxCount: THUMBNAIL_MAX_COLS,
        maxLogicalPixels: THUMBNAIL_MAX_SOURCE_WIDTH_PX,
        maxUsedIndex: effectiveMaxUsedCol,
        minUsedIndex: effectiveMinUsedCol,
        precomputed: visibleCols
      });
      const rowAxis = buildThumbnailAxisItems(previewRows, resolveRowHeightPx);
      const colAxis = buildThumbnailAxisItems(previewCols, resolveColumnWidthPx);
      const rowItemByActual = new Map(rowAxis.items.map((item) => [item.actualIndex, item]));
      const colItemByActual = new Map(colAxis.items.map((item) => [item.actualIndex, item]));
      const headerHeight = includeHeaders ? HEADER_HEIGHT : 0;
      const rowHeaderWidth = includeHeaders ? ROW_HEADER_WIDTH : 0;
      const sourceWidth = rowHeaderWidth + colAxis.totalSize;
      const sourceHeight = headerHeight + rowAxis.totalSize;
      const outputSize = resolveThumbnailOutputSize(sourceWidth, sourceHeight, resolution);
      const sourceRange = {
        start: {
          col: previewCols[0] ?? 0,
          row: previewRows[0] ?? 0
        },
        end: {
          col: previewCols[previewCols.length - 1] ?? 0,
          row: previewRows[previewRows.length - 1] ?? 0
        }
      };
      const sparklineByCell = new Map(
        (sheet.sparklines ?? []).map((sparkline) => [`${sparkline.target.row}:${sparkline.target.col}`, sparkline])
      );
      const thumbnailImageRects = sheetImages.map((image) => ({
        image,
        rect: resolveThumbnailAnchoredRect(
          image.anchor,
          visibleRows,
          visibleCols,
          resolveRowHeightPx,
          resolveColumnWidthPx,
          previewRows,
          previewCols,
          {
            headerHeight,
            rowHeaderWidth
          }
        )
      })).filter(({ rect }) => rect.left + rect.width >= rowHeaderWidth && rect.top + rect.height >= headerHeight && rect.left <= sourceWidth && rect.top <= sourceHeight);
      const thumbnailShapeRects = sheetShapes.map((shape) => ({
        rect: resolveThumbnailAnchoredRect(
          shape.anchor,
          visibleRows,
          visibleCols,
          resolveRowHeightPx,
          resolveColumnWidthPx,
          previewRows,
          previewCols,
          {
            headerHeight,
            rowHeaderWidth
          }
        ),
        shape
      })).filter(({ rect }) => rect.left + rect.width >= rowHeaderWidth && rect.top + rect.height >= headerHeight && rect.left <= sourceWidth && rect.top <= sourceHeight);
      const thumbnailFormControlRects = sheetFormControls.map((control2) => ({
        control: control2,
        rect: resolveThumbnailAnchoredRect(
          control2.anchor,
          visibleRows,
          visibleCols,
          resolveRowHeightPx,
          resolveColumnWidthPx,
          previewRows,
          previewCols,
          {
            headerHeight,
            rowHeaderWidth
          }
        )
      })).filter(({ rect }) => rect.left + rect.width >= rowHeaderWidth && rect.top + rect.height >= headerHeight && rect.left <= sourceWidth && rect.top <= sourceHeight);
      const thumbnailDrawingEntries = [
        ...thumbnailShapeRects.map(({ rect, shape }) => ({
          kind: "shape",
          rect,
          shape,
          zIndex: drawingLayer(shape.zIndex)
        })),
        ...thumbnailFormControlRects.map(({ control: control2, rect }) => ({
          control: control2,
          kind: "formControl",
          rect,
          zIndex: drawingLayer(control2.zIndex)
        })),
        ...thumbnailImageRects.map(({ image, rect }) => ({
          image,
          kind: "image",
          rect,
          zIndex: drawingLayer(image.zIndex)
        }))
      ].sort((left, right) => left.zIndex - right.zIndex);
      const paint = (canvas) => {
        if (!canvas) {
          return false;
        }
        const workerRowBatch = worksheet ? null : getWorkerThumbnailRowBatch(sheet, sourceRange.start.row, sourceRange.end.row);
        if (!worksheet && !workerRowBatch) {
          return false;
        }
        const context = canvas.getContext("2d", { alpha: false });
        if (!context) {
          return false;
        }
        const dpr = typeof window === "undefined" ? 1 : Math.max(1, window.devicePixelRatio || 1);
        const outputWidth = outputSize.width;
        const outputHeight = outputSize.height;
        const scale = outputSize.scale;
        const deviceWidth = Math.max(1, Math.round(outputWidth * dpr));
        const deviceHeight = Math.max(1, Math.round(outputHeight * dpr));
        if (canvas.width !== deviceWidth) {
          canvas.width = deviceWidth;
        }
        if (canvas.height !== deviceHeight) {
          canvas.height = deviceHeight;
        }
        if (canvas.style.width !== `${outputWidth}px`) {
          canvas.style.width = `${outputWidth}px`;
        }
        if (canvas.style.height !== `${outputHeight}px`) {
          canvas.style.height = `${outputHeight}px`;
        }
        context.setTransform(dpr * scale, 0, 0, dpr * scale, 0, 0);
        context.clearRect(0, 0, Math.max(1, sourceWidth), Math.max(1, sourceHeight));
        const thumbnailSheetSurface = resolveSheetSurface(sheet, palette);
        context.fillStyle = palette.canvas;
        context.fillRect(0, 0, Math.max(1, sourceWidth), Math.max(1, sourceHeight));
        context.fillStyle = thumbnailSheetSurface;
        context.fillRect(rowHeaderWidth, headerHeight, Math.max(1, colAxis.totalSize), Math.max(1, rowAxis.totalSize));
        if (includeHeaders) {
          context.fillStyle = palette.headerSurface;
          context.fillRect(rowHeaderWidth, 0, Math.max(1, colAxis.totalSize), headerHeight);
          context.fillStyle = palette.rowHeaderSurface;
          context.fillRect(0, headerHeight, rowHeaderWidth, Math.max(1, rowAxis.totalSize));
          context.fillRect(0, 0, rowHeaderWidth, headerHeight);
        }
        const conditionalFormatMetricsCache = /* @__PURE__ */ new Map();
        const cellRenderCache = /* @__PURE__ */ new Map();
        const getCellData = (row2, col) => {
          const cacheKey = `${row2}:${col}`;
          const cached = cellRenderCache.get(cacheKey);
          if (cached) {
            return cached;
          }
          const batchCoversRow = workerRowBatch ? row2 >= workerRowBatch.startRow && row2 <= workerRowBatch.endRow : false;
          const batchedCell = batchCoversRow ? workerRowBatch?.cells.get(cacheKey) : void 0;
          if (batchedCell?.isMergedSecondary || worksheet?.isMergedSecondary(row2, col)) {
            const mergedSecondaryData = {
              isMergedSecondary: true,
              style: {},
              value: ""
            };
            cellRenderCache.set(cacheKey, mergedSecondaryData);
            return mergedSecondaryData;
          }
          const merge = worksheet ? worksheet.getMergeSpan(row2, col) : batchedCell?.mergeSpan;
          const inheritedStyle = resolveInheritedCellStyle2(sheet, row2, col);
          const worksheetStyle = worksheet ? worksheet.getCellStyleAt(row2, col) ?? null : batchedCell?.style ?? null;
          const mergedStyle = mergeResolvedCellStyle(inheritedStyle, worksheetStyle, { replaceXfSubtrees: true });
          const conditionalCellStyle = resolveConditionalCellStyleForCell(
            row2,
            col,
            sheet,
            () => worksheet ? getCellNumericValue(worksheet, row2, col) : getBatchedCellNumericValue(batchedCell),
            () => worksheet ? getCellDisplayValue(worksheet, row2, col, sheet, locale) : batchedCell?.value ?? "",
            worksheet,
            workerRowBatch?.cells
          );
          const finalResolvedStyle = mergeResolvedCellStyle(mergedStyle, conditionalCellStyle);
          const alignment = finalResolvedStyle?.alignment;
          const sparkline = sparklineByCell.get(cacheKey) ?? null;
          const getNumericValue = (targetRow, targetCol) => worksheet ? getCellNumericValue(worksheet, targetRow, targetCol) : getBatchedCellNumericValue(workerRowBatch?.cells.get(`${targetRow}:${targetCol}`));
          const sparklineValues = sparkline ? sparkline.range.start.row === sparkline.range.end.row ? Array.from(
            { length: Math.abs(sparkline.range.end.col - sparkline.range.start.col) + 1 },
            (_, index) => getNumericValue(
              sparkline.range.start.row,
              Math.min(sparkline.range.start.col, sparkline.range.end.col) + index
            )
          ) : Array.from(
            { length: Math.abs(sparkline.range.end.row - sparkline.range.start.row) + 1 },
            (_, index) => getNumericValue(
              Math.min(sparkline.range.start.row, sparkline.range.end.row) + index,
              sparkline.range.start.col
            )
          ) : null;
          const checkboxState = finalResolvedStyle?.cellControl ? worksheet ? getCellBooleanValue(worksheet, row2, col) : getBatchedCellBooleanValue(batchedCell) : null;
          const nextData = {
            canvas: void 0,
            checkboxState,
            colSpan: merge?.colSpan,
            conditionalColorScale: worksheet ? resolveConditionalColorScaleForCell(row2, col, worksheet, sheet, conditionalFormatMetricsCache) : null,
            conditionalDataBar: worksheet ? resolveConditionalDataBarForCell(row2, col, worksheet, sheet, conditionalFormatMetricsCache) : null,
            conditionalIcon: worksheet ? resolveConditionalIconForCell(row2, col, worksheet, sheet, conditionalFormatMetricsCache) : null,
            isMergedSecondary: false,
            rowSpan: merge?.rowSpan,
            sparkline: sparkline && sparklineValues ? { config: sparkline, values: sparklineValues } : null,
            style: buildCellStyle(finalResolvedStyle, palette, sheet.themePalette, {
              generalAlignment: worksheet ? getCellGeneralAlignment(worksheet, row2, col) : batchedCell?.generalAlignment,
              showGridLines
            }),
            textRotationDeg: resolveSpreadsheetTextRotation(alignment?.rotation ?? alignment?.textRotation),
            value: sparkline ? "" : checkboxState !== null ? "" : worksheet ? getCellDisplayValue(worksheet, row2, col, sheet, locale) : batchedCell?.value ?? ""
          };
          nextData.richText = resolveRichCellRuns(
            worksheet ? worksheet.getRichTextAt(row2, col) : batchedCell?.richText,
            nextData.value,
            nextData.style,
            sheet.themePalette,
            1
          );
          nextData.canvas = buildCanvasCellStyleCache(nextData.style);
          cellRenderCache.set(cacheKey, nextData);
          return nextData;
        };
        for (const rowItem of rowAxis.items) {
          for (const colItem of colAxis.items) {
            const cellData = getCellData(rowItem.actualIndex, colItem.actualIndex);
            if (cellData.isMergedSecondary) {
              continue;
            }
            const colSpan = Math.max(1, cellData.colSpan ?? 1);
            const rowSpan = Math.max(1, cellData.rowSpan ?? 1);
            let width = colItem.size;
            let height = rowItem.size;
            for (let colOffset = 1; colOffset < colSpan; colOffset += 1) {
              const nextCol = colItemByActual.get(colItem.actualIndex + colOffset);
              width += nextCol?.size ?? 0;
            }
            for (let rowOffset = 1; rowOffset < rowSpan; rowOffset += 1) {
              const nextRow = rowItemByActual.get(rowItem.actualIndex + rowOffset);
              height += nextRow?.size ?? 0;
            }
            const rect = {
              height,
              left: rowHeaderWidth + colItem.start,
              top: headerHeight + rowItem.start,
              width
            };
            const canvasCellStyle = cellData.canvas ?? buildCanvasCellStyleCache(cellData.style);
            const gradientFill = typeof cellData.style.backgroundImage === "string" ? resolveCanvasGradientFill(context, rect, cellData.style.backgroundImage) : null;
            const fillColor = cellData.conditionalColorScale?.color ?? (typeof cellData.style.backgroundColor === "string" ? cellData.style.backgroundColor : thumbnailSheetSurface);
            context.fillStyle = gradientFill ?? fillColor;
            context.fillRect(rect.left, rect.top, rect.width, rect.height);
            if (cellData.conditionalDataBar) {
              const barLeft = rect.left + DATA_BAR_INSET;
              const barTop = rect.top + DATA_BAR_INSET;
              const barWidth = Math.max(0, (rect.width - DATA_BAR_INSET * 2) * (cellData.conditionalDataBar.widthPercent / 100));
              const barHeight = Math.max(0, rect.height - DATA_BAR_INSET * 2);
              if (barWidth > 0 && barHeight > 0) {
                context.fillStyle = resolveCanvasDataBarFill(
                  context,
                  barLeft,
                  barTop,
                  barWidth,
                  barHeight,
                  cellData.conditionalDataBar
                );
                context.fillRect(barLeft, barTop, barWidth, barHeight);
                if (cellData.conditionalDataBar.border !== false && cellData.conditionalDataBar.borderColor) {
                  context.strokeStyle = cellData.conditionalDataBar.borderColor;
                  context.lineWidth = 1;
                  context.strokeRect(barLeft + 0.5, barTop + 0.5, Math.max(0, barWidth - 1), Math.max(0, barHeight - 1));
                }
              }
            }
            if (showGridLines) {
              context.strokeStyle = palette.border;
              context.lineWidth = 1;
              context.beginPath();
              if (colItem.start === 0) {
                context.moveTo(rect.left + 0.5, rect.top);
                context.lineTo(rect.left + 0.5, rect.top + rect.height);
              }
              if (rowItem.start === 0) {
                context.moveTo(rect.left, rect.top + 0.5);
                context.lineTo(rect.left + rect.width, rect.top + 0.5);
              }
              context.moveTo(rect.left + rect.width - 0.5, rect.top);
              context.lineTo(rect.left + rect.width - 0.5, rect.top + rect.height);
              context.moveTo(rect.left, rect.top + rect.height - 0.5);
              context.lineTo(rect.left + rect.width, rect.top + rect.height - 0.5);
              context.stroke();
            }
            if (canvasCellStyle.topBorder) {
              strokeCanvasBorderSide(context, "top", rect, canvasCellStyle.topBorder);
            }
            if (canvasCellStyle.rightBorder) {
              strokeCanvasBorderSide(context, "right", rect, canvasCellStyle.rightBorder);
            }
            if (canvasCellStyle.bottomBorder) {
              strokeCanvasBorderSide(context, "bottom", rect, canvasCellStyle.bottomBorder);
            }
            if (canvasCellStyle.leftBorder) {
              strokeCanvasBorderSide(context, "left", rect, canvasCellStyle.leftBorder);
            }
            const rawText = cellData.value ?? "";
            const shouldDrawThumbnailContent = cellData.checkboxState != null || cellData.sparkline || rawText.length > 0 || cellData.conditionalIcon;
            if (!shouldDrawThumbnailContent) {
              continue;
            }
            const padding = canvasCellStyle.padding;
            const contentLeft = rect.left + padding.left;
            const contentTop = rect.top + padding.top;
            const contentWidth = Math.max(0, rect.width - padding.left - padding.right);
            const contentHeight = Math.max(0, rect.height - padding.top - padding.bottom);
            if (contentWidth <= 0 || contentHeight <= 0) {
              continue;
            }
            context.save();
            context.beginPath();
            context.rect(contentLeft, contentTop, contentWidth, contentHeight);
            context.clip();
            context.font = canvasCellStyle.baseFont;
            context.fillStyle = canvasCellStyle.textColor;
            context.textBaseline = "middle";
            if (cellData.checkboxState != null) {
              const boxSize = Math.min(14, contentWidth, contentHeight);
              const boxLeft = rect.left + (rect.width - boxSize) / 2;
              const boxTop = rect.top + (rect.height - boxSize) / 2;
              context.strokeStyle = paletteIsDark(palette) ? "#cbd5e1" : "#475569";
              context.lineWidth = 1.25;
              context.strokeRect(boxLeft, boxTop, boxSize, boxSize);
              if (cellData.checkboxState) {
                context.fillStyle = paletteIsDark(palette) ? "#60a5fa" : "#2563eb";
                context.fillRect(boxLeft + 1.5, boxTop + 1.5, Math.max(0, boxSize - 3), Math.max(0, boxSize - 3));
              }
            } else if (cellData.sparkline) {
              const sparkline = cellData.sparkline.config;
              const sparklineValues = cellData.sparkline.values;
              const points = sparklineValues.map((value, index) => ({ index, value })).filter((entry) => typeof entry.value === "number" && Number.isFinite(entry.value));
              if (points.length > 1) {
                const minValue = Math.min(...points.map((entry) => entry.value));
                const maxValue = Math.max(...points.map((entry) => entry.value));
                const sparkLeft = contentLeft + 1;
                const sparkTop = contentTop + 2;
                const sparkWidth = Math.max(1, contentWidth - 2);
                const sparkHeight = Math.max(1, contentHeight - 4);
                const xStep = points.length > 1 ? sparkWidth / (points.length - 1) : 0;
                context.strokeStyle = sparkline.color ?? "#2563eb";
                context.lineCap = "round";
                context.lineJoin = "round";
                context.lineWidth = 1.25;
                context.beginPath();
                points.forEach((entry, index) => {
                  const x = sparkLeft + index * xStep;
                  const y = sparkTop + sparkHeight - clampSparklineValue(entry.value, minValue, maxValue) * sparkHeight;
                  if (index === 0) {
                    context.moveTo(x, y);
                  } else {
                    context.lineTo(x, y);
                  }
                });
                context.stroke();
              }
            } else if (rawText.length > 0) {
              const align = canvasCellStyle.textAlign;
              context.textAlign = align;
              const leadingInset = cellData.conditionalIcon ? 18 : 0;
              const textLeft = contentLeft + leadingInset;
              const maxTextWidth = Math.max(0, contentWidth - leadingInset);
              const textX = align === "right" ? textLeft + maxTextWidth : align === "center" ? textLeft + maxTextWidth / 2 : textLeft;
              const singleLineHeight = resolveCanvasLineHeight(cellData.style, 12);
              if (cellData.richText) {
                drawRichCellText(context, cellData, { left: textLeft, top: contentTop, width: maxTextWidth, height: contentHeight });
              } else if (cellData.textRotationDeg) {
                drawRotatedCellText(context, rawText, cellData.textRotationDeg, {
                  left: textLeft,
                  top: contentTop,
                  width: maxTextWidth,
                  height: contentHeight
                }, align, cellData.style.verticalAlign, singleLineHeight);
              } else if (canvasCellStyle.usesWrappedText || rawText.includes("\n")) {
                const lines = wrapCanvasText(context, rawText, maxTextWidth);
                const lineHeight = resolveCanvasLineHeight(cellData.style, 12);
                const textBlockHeight = lines.length * lineHeight;
                let textBlockTop = contentTop;
                if (cellData.style.verticalAlign === "middle") {
                  textBlockTop = contentTop + (contentHeight - textBlockHeight) / 2;
                } else if (cellData.style.verticalAlign !== "top") {
                  textBlockTop = contentTop + contentHeight - textBlockHeight;
                }
                lines.forEach((line, lineIndex) => {
                  context.fillText(line, textX, textBlockTop + lineIndex * lineHeight + lineHeight / 2);
                });
              } else {
                const text = canvasCellStyle.textOverflowEllipsis ? truncateCanvasText(context, rawText, maxTextWidth) : rawText;
                context.fillText(text, textX, resolveCanvasTextMiddleY(cellData.style.verticalAlign, contentTop, contentHeight, singleLineHeight));
              }
            }
            if (cellData.conditionalIcon) {
              const iconSize = 10;
              const iconX = rect.left + padding.left;
              const iconY = rect.top + rect.height / 2;
              drawCanvasConditionalIcon(context, cellData.conditionalIcon, iconX + iconSize / 2, iconY, iconSize);
            }
            context.restore();
          }
        }
        if (thumbnailDrawingEntries.length > 0) {
          context.save();
          context.beginPath();
          context.rect(rowHeaderWidth, headerHeight, Math.max(1, colAxis.totalSize), Math.max(1, rowAxis.totalSize));
          context.clip();
          for (const entry of thumbnailDrawingEntries) {
            if (entry.kind === "shape") {
              drawStaticShape(context, entry.shape, entry.rect, 1);
            } else if (entry.kind === "formControl") {
              drawStaticFormControl(context, entry.control, entry.rect, palette, 1, thumbnailSheetSurface);
            } else {
              const imageElement = getThumbnailImage(entry.image);
              if (imageElement) {
                const paintRect = resolvePicturePaintRect(entry.image, entry.rect);
                context.drawImage(imageElement, paintRect.left, paintRect.top, paintRect.width, paintRect.height);
              }
            }
          }
          context.restore();
        }
        if (includeHeaders) {
          context.strokeStyle = palette.border;
          context.lineWidth = 1;
          context.font = "600 11px ui-sans-serif, system-ui, sans-serif";
          context.fillStyle = palette.headerText;
          context.textBaseline = "middle";
          for (const colItem of colAxis.items) {
            const left = rowHeaderWidth + colItem.start;
            context.beginPath();
            context.moveTo(left + colItem.size - 0.5, 0);
            context.lineTo(left + colItem.size - 0.5, headerHeight);
            context.moveTo(left, headerHeight - 0.5);
            context.lineTo(left + colItem.size, headerHeight - 0.5);
            context.stroke();
            context.textAlign = "center";
            context.fillText(columnLabel2(colItem.actualIndex), left + colItem.size / 2, headerHeight / 2);
          }
          for (const rowItem of rowAxis.items) {
            const top = headerHeight + rowItem.start;
            context.beginPath();
            context.moveTo(0, top + rowItem.size - 0.5);
            context.lineTo(rowHeaderWidth, top + rowItem.size - 0.5);
            context.moveTo(rowHeaderWidth - 0.5, top);
            context.lineTo(rowHeaderWidth - 0.5, top + rowItem.size);
            context.stroke();
            context.textAlign = "center";
            context.fillText(`${rowItem.actualIndex + 1}`, rowHeaderWidth / 2, top + rowItem.size / 2);
          }
          context.beginPath();
          context.moveTo(rowHeaderWidth - 0.5, 0);
          context.lineTo(rowHeaderWidth - 0.5, headerHeight);
          context.moveTo(0, headerHeight - 0.5);
          context.lineTo(rowHeaderWidth, headerHeight - 0.5);
          context.stroke();
        }
        return true;
      };
      const plan = {
        aspectRatio: sourceWidth / Math.max(1, sourceHeight),
        contentHeight: rowAxis.totalSize,
        contentWidth: colAxis.totalSize,
        height: outputSize.height,
        paint,
        sourceRange,
        width: outputSize.width
      };
      return {
        ...plan,
        sheet,
        sheetIndex,
        workbookSheetIndex: sheet.workbookSheetIndex
      };
    });
  }, [
    getSheetFormControls,
    getSheetImages,
    getSheetShapes,
    getWorkerThumbnailRowBatch,
    getThumbnailImage,
    includeHeaders,
    palette,
    resolution,
    sheets,
    thumbnailImageLoadVersion,
    workerThumbnailRowBatchVersion,
    locale,
    workbook
  ]);
  const paintThumbnail = React15.useCallback(
    (sheetIndex, canvas) => thumbnails[sheetIndex]?.paint(canvas) ?? false,
    [thumbnails]
  );
  return React15.useMemo(
    () => ({
      paintThumbnail,
      thumbnails
    }),
    [paintThumbnail, thumbnails]
  );
}
function DefaultXlsxToolbar({ pivotTableEditor } = {}) {
  const controller = useXlsxViewer();
  const { headerBackgroundColor, headerTextColor, isDark } = React15.useContext(ViewerAppearanceContext);
  const palette = useViewerPalette(isDark, headerBackgroundColor, headerTextColor);
  return /* @__PURE__ */ jsx11(DefaultToolbar, { controller, palette, pivotTableEditor });
}

// src/react-viewer.tsx
import { jsx as jsx12, jsxs as jsxs9 } from "react/jsx-runtime";
var SlotStore = class {
  slots = /* @__PURE__ */ new Map();
  listeners = /* @__PURE__ */ new Set();
  observer = null;
  revision = 0;
  scheduled = false;
  destroyed = false;
  subscribe = (listener) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  getSnapshot = () => this.revision;
  getServerSnapshot = () => 0;
  observe(element) {
    this.destroyed = false;
    const target = element.ownerDocument.documentElement;
    this.observer = new MutationObserver(() => this.sweep());
    this.observer.observe(target, { childList: true, subtree: true });
  }
  render(key, node, owner) {
    let slot = this.slots.get(key);
    if (!slot) {
      const host = owner.createElement("span");
      host.style.display = "contents";
      slot = { host, node, wasConnected: false };
      this.slots.set(key, slot);
    } else {
      slot.node = node;
    }
    this.notify();
    return __createContentNode(slot.host);
  }
  portals() {
    return Array.from(this.slots, ([key, slot]) => createPortal7(slot.node, slot.host, key));
  }
  destroy() {
    this.destroyed = true;
    this.observer?.disconnect();
    this.observer = null;
    this.slots.clear();
    this.listeners.clear();
  }
  sweep() {
    let changed = false;
    for (const [key, slot] of this.slots) {
      if (slot.host.isConnected) {
        slot.wasConnected = true;
      } else if (slot.wasConnected) {
        this.slots.delete(key);
        changed = true;
      }
    }
    if (changed) this.notify();
  }
  notify() {
    if (this.destroyed || this.scheduled) return;
    this.scheduled = true;
    queueMicrotask(() => {
      this.scheduled = false;
      if (this.destroyed) return;
      this.revision += 1;
      this.listeners.forEach((listener) => listener());
    });
  }
};
function RuntimeContent({ content }) {
  const hostRef = React16.useRef(null);
  const rootRef = React16.useRef(null);
  React16.useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const root = __createContentRoot(host);
    rootRef.current = root;
    return () => {
      rootRef.current = null;
      root.destroy();
    };
  }, []);
  React16.useLayoutEffect(() => {
    rootRef.current?.update(content);
  }, [content]);
  return /* @__PURE__ */ jsx12("span", { ref: hostRef, style: { display: "contents" } });
}
function renderOptions(props, controller, slots, owner) {
  const slot = (key, node) => slots.render(key, node, owner);
  const runtime = (node) => /* @__PURE__ */ jsx12(RuntimeContent, { content: node });
  const {
    emptyState,
    errorState,
    fileTooLargeState,
    loadingComponent,
    loadingState,
    renderActiveCellOverlay,
    renderCellEditorOverlay,
    renderSelectionPopover,
    renderChartLoading,
    renderContextMenu,
    renderFormControl,
    renderImage,
    renderImageSelection,
    renderScroller,
    renderTableHeaderMenu,
    renderPivotTableHeaderMenu,
    renderPivotTableControls,
    toolbar,
    ...other
  } = props;
  return {
    ...other,
    controller,
    emptyState: emptyState === void 0 ? void 0 : slot("empty", emptyState),
    loadingComponent: loadingComponent === void 0 ? void 0 : slot("loading-component", loadingComponent),
    loadingState: loadingState === void 0 ? void 0 : slot("loading", loadingState),
    errorState: errorState === void 0 ? void 0 : typeof errorState === "function" ? (error) => slot("error", errorState(error)) : slot("error", errorState),
    fileTooLargeState: fileTooLargeState === void 0 ? void 0 : typeof fileTooLargeState === "function" ? ({ defaultNode, ...rest }) => slot("too-large", fileTooLargeState({ ...rest, defaultNode: runtime(defaultNode) })) : slot("too-large", fileTooLargeState),
    toolbar: toolbar === void 0 ? void 0 : typeof toolbar === "function" ? (current) => slot("toolbar", toolbar(current)) : slot("toolbar", toolbar),
    renderActiveCellOverlay: renderActiveCellOverlay ? (value) => slot(`active:${value.cell.row}:${value.cell.col}`, renderActiveCellOverlay(value)) : void 0,
    renderSelectionPopover: renderSelectionPopover ? (value) => {
      const content = renderSelectionPopover(value);
      return content == null || content === false ? null : slot("selection-popover", content);
    } : void 0,
    renderCellEditorOverlay: renderCellEditorOverlay ? (value) => {
      const content = renderCellEditorOverlay(value);
      return content == null || content === false ? null : slot("cell-editor-overlay", content);
    } : void 0,
    renderChartLoading: renderChartLoading ? ({ defaultNode, ...value }) => slot(`chart:${value.chart.id}`, renderChartLoading({ ...value, defaultNode: runtime(defaultNode) })) : void 0,
    renderContextMenu: renderContextMenu ? ({ defaultNode, ...value }) => slot("context-menu", renderContextMenu({ ...value, defaultNode: runtime(defaultNode) })) : void 0,
    renderFormControl: renderFormControl ? (value) => slot(`control:${value.control.id}`, renderFormControl(value)) : void 0,
    renderImage: renderImage ? ({ defaultNode, ...value }) => slot(`image:${value.image.id}`, renderImage({ ...value, defaultNode: runtime(defaultNode) })) : void 0,
    renderImageSelection: renderImageSelection ? ({ defaultNode, ...value }) => slot(`image-selection:${value.image.id}`, renderImageSelection({ ...value, defaultNode: runtime(defaultNode) })) : void 0,
    renderScroller: renderScroller ? ({ children: children2, ...value }) => slot("scroller", renderScroller({ ...value, children: runtime(children2) })) : void 0,
    renderTableHeaderMenu: renderTableHeaderMenu ? (value) => slot(`table:${value.table.name}:${value.cell.row}:${value.cell.col}`, renderTableHeaderMenu({
      ...value,
      defaultNode: value.defaultNode ? runtime(value.defaultNode) : void 0,
      pivot: value.pivot ? { ...value.pivot, defaultNode: runtime(value.pivot.defaultNode) } : void 0
    })) : void 0,
    renderPivotTableControls: renderPivotTableControls ? ({ defaultNode, ...value }) => slot("pivot-table-controls", renderPivotTableControls({ ...value, defaultNode: runtime(defaultNode) })) : void 0,
    renderPivotTableHeaderMenu: renderPivotTableHeaderMenu ? ({ defaultNode, ...value }) => slot(`pivot-header:${value.pivot.id}:${value.header.row}:${value.header.col}`, renderPivotTableHeaderMenu({ ...value, defaultNode: runtime(defaultNode) })) : void 0
  };
}
function BoundViewer({ props, controller: sourceController }) {
  const messages = React16.useMemo(() => mergeMessages(sourceController.messages, props.messages), [sourceController.messages, props.messages]);
  const controller = React16.useMemo(() => ({ ...sourceController, messages }), [sourceController, messages]);
  const hostRef = React16.useRef(null);
  const viewerRef = React16.useRef(null);
  const slots = React16.useMemo(() => new SlotStore(), []);
  React16.useSyncExternalStore(slots.subscribe, slots.getSnapshot, slots.getServerSnapshot);
  React16.useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    slots.observe(host);
    const viewer = __createControlledViewer(host);
    viewerRef.current = viewer;
    return () => {
      viewerRef.current = null;
      viewer.destroy();
      slots.destroy();
    };
  }, [slots]);
  React16.useLayoutEffect(() => {
    const host = hostRef.current;
    if (host) viewerRef.current?.update(renderOptions(props, controller, slots, host.ownerDocument));
  }, [controller, props, slots]);
  return /* @__PURE__ */ jsx12(ViewerAppearanceContext.Provider, { value: {
    headerBackgroundColor: props.headerBackgroundColor,
    headerTextColor: props.headerTextColor,
    isDark: props.isDark ?? false
  }, children: /* @__PURE__ */ jsxs9(ViewerContext.Provider, { value: controller, children: [
    /* @__PURE__ */ jsx12("div", { ref: hostRef, style: { display: "contents" } }),
    slots.portals()
  ] }) });
}
function UncontrolledViewer(props) {
  const controller = useXlsxViewerController(props);
  return /* @__PURE__ */ jsx12(BoundViewer, { props, controller });
}
function XlsxViewer(props) {
  const context = React16.useContext(ViewerContext);
  const controller = props.controller ?? context;
  return controller ? /* @__PURE__ */ jsx12(BoundViewer, { props, controller }) : /* @__PURE__ */ jsx12(UncontrolledViewer, { ...props });
}
export {
  DefaultXlsxPivotTableFieldList,
  DefaultXlsxToolbar,
  XlsxFileSizeLimitExceededError3 as XlsxFileSizeLimitExceededError,
  XlsxViewer,
  XlsxViewerProvider,
  initWasm,
  parseXlsxRange2 as parseXlsxRange,
  setWasmSource,
  useXlsxPivotTableEditor,
  useXlsxViewer,
  useXlsxViewerCharts,
  useXlsxViewerController,
  useXlsxViewerEditing,
  useXlsxViewerImages,
  useXlsxViewerLayout,
  useXlsxViewerPivots,
  useXlsxViewerSelection,
  useXlsxViewerTables,
  useXlsxViewerThumbnails,
  useXlsxViewerZoom
};
//# sourceMappingURL=index.js.map