import {
  loadOfficeFonts
} from "./chunk-QXXS4J36.js";
import {
  decodeWorkbookArchive,
  parseWorkbookXml,
  serializeWorkbookXml
} from "./chunk-67TEHWH5.js";

// src/range-reference.ts
var XLSX_MAX_ROWS = 1048576;
var XLSX_MAX_COLUMNS = 16384;
function parseColumn(value) {
  let column = 0;
  for (const character of value.toUpperCase()) {
    column = column * 26 + character.charCodeAt(0) - 64;
  }
  return column > 0 && column <= XLSX_MAX_COLUMNS ? column - 1 : null;
}
function parseRow(value) {
  const row = Number(value);
  return row > 0 && row <= XLSX_MAX_ROWS ? row - 1 : null;
}
function parseCell(value) {
  const match = /^\$?([a-z]{1,3})\$?([1-9]\d{0,6})$/i.exec(value);
  if (!match) {
    return null;
  }
  const col = parseColumn(match[1]);
  const row = parseRow(match[2]);
  return col === null || row === null ? null : { col, row };
}
function parseXlsxRange(reference) {
  if (typeof reference !== "string") {
    return null;
  }
  let address = reference.trim().replace(/^=\s*/, "");
  let sheetName = null;
  if (address.startsWith("'")) {
    const match = /^'((?:[^']|'')+)'!(.+)$/.exec(address);
    if (!match) {
      return null;
    }
    sheetName = match[1].replace(/''/g, "'");
    address = match[2];
  } else if (address.includes("!")) {
    const match = /^([^\s'!\[\]:*?/\\+,;(){}=<>"&^%\-]+)!(.+)$/.exec(address);
    if (!match) {
      return null;
    }
    sheetName = match[1];
    address = match[2];
  }
  if (sheetName !== null && (sheetName.length > 31 || /[\[\]:*?/\\\u0000-\u001f]/.test(sheetName) || sheetName.startsWith("'") || sheetName.endsWith("'"))) {
    return null;
  }
  const parts = address.split(":");
  if (parts.length > 2) {
    return null;
  }
  const start = parseCell(parts[0]);
  const end = parseCell(parts[1] ?? parts[0]);
  if (start && end) {
    return {
      kind: "cells",
      range: {
        start: { col: Math.min(start.col, end.col), row: Math.min(start.row, end.row) },
        end: { col: Math.max(start.col, end.col), row: Math.max(start.row, end.row) }
      },
      sheetName
    };
  }
  const columns = /^\$?([a-z]{1,3}):\$?([a-z]{1,3})$/i.exec(address);
  if (columns) {
    const first = parseColumn(columns[1]);
    const last = parseColumn(columns[2]);
    if (first !== null && last !== null) {
      return {
        kind: "columns",
        range: {
          start: { col: Math.min(first, last), row: 0 },
          end: { col: Math.max(first, last), row: XLSX_MAX_ROWS - 1 }
        },
        sheetName
      };
    }
  }
  const rows = /^\$?([1-9]\d{0,6}):\$?([1-9]\d{0,6})$/.exec(address);
  if (rows) {
    const first = parseRow(rows[1]);
    const last = parseRow(rows[2]);
    if (first !== null && last !== null) {
      return {
        kind: "rows",
        range: {
          start: { col: 0, row: Math.min(first, last) },
          end: { col: XLSX_MAX_COLUMNS - 1, row: Math.max(first, last) }
        },
        sheetName
      };
    }
  }
  return null;
}

// src/pivots.ts
function pivotWorkbook(workbook) {
  const candidate = workbook;
  if (typeof candidate.upsertPivotTable !== "function") {
    throw new Error("Pivot tables require the current bundled spreadsheet runtime.");
  }
  return candidate;
}
function readPivotTables(workbook) {
  const pivots = workbook.pivotTables;
  return Array.isArray(pivots) ? pivots : [];
}
function findIntersectingPivot(pivots, sheetName, range) {
  if (!sheetName) return null;
  const top = Math.min(range.start.row, range.end.row);
  const bottom = Math.max(range.start.row, range.end.row);
  const left = Math.min(range.start.col, range.end.col);
  const right = Math.max(range.start.col, range.end.col);
  return pivots.find((pivot) => {
    if (pivot.target.sheet.toLowerCase() !== sheetName.toLowerCase() || !pivot.outputRange) return false;
    const bounds = parseXlsxRange(pivot.outputRange)?.range;
    return bounds && top <= bounds.end.row && bottom >= bounds.start.row && left <= bounds.end.col && right >= bounds.start.col;
  }) ?? null;
}

// src/workbook-object-urls.ts
var workerBlobs = /* @__PURE__ */ new Map();
function createWorkbookObjectUrl(blob) {
  const url = URL.createObjectURL(blob);
  if (typeof document === "undefined") workerBlobs.set(url, blob);
  return url;
}
function revokeWorkbookObjectUrl(url) {
  workerBlobs.delete(url);
  URL.revokeObjectURL(url);
}
function takeWorkerImageBlobs(urls) {
  return urls.flatMap((url) => {
    const blob = workerBlobs.get(url);
    workerBlobs.delete(url);
    return blob ? [[url, blob]] : [];
  });
}
function restoreWorkerImageBlobs(assets, blobs) {
  if (!assets || !blobs?.length) return;
  const urls = new Map(blobs.map(([url, blob]) => [url, URL.createObjectURL(blob)]));
  assets.objectUrls = assets.objectUrls.map((url) => urls.get(url) ?? url);
  for (const images of assets.imagesByWorkbookSheetIndex) {
    for (const image of images) image.src = urls.get(image.src) ?? image.src;
  }
}

// src/colors.ts
function normalizeHexColor(value) {
  const hex = value.replace(/^#/, "");
  if (hex.length === 8) {
    return `#${hex.slice(2).toLowerCase()}`;
  }
  if (hex.length === 6) {
    return `#${hex.toLowerCase()}`;
  }
  return null;
}
function parseHexColor(color) {
  const normalized = normalizeHexColor(color);
  const match = normalized ? /^#([0-9a-f]{6})$/.exec(normalized) : null;
  if (!match) {
    return null;
  }
  const hex = match[1];
  return [
    Number.parseInt(hex.slice(0, 2), 16),
    Number.parseInt(hex.slice(2, 4), 16),
    Number.parseInt(hex.slice(4, 6), 16)
  ];
}
function rgbToHsl(red, green, blue) {
  const normalizedRed = red / 255;
  const normalizedGreen = green / 255;
  const normalizedBlue = blue / 255;
  const max = Math.max(normalizedRed, normalizedGreen, normalizedBlue);
  const min = Math.min(normalizedRed, normalizedGreen, normalizedBlue);
  const lightness = (max + min) / 2;
  if (max === min) {
    return [0, 0, lightness];
  }
  const delta = max - min;
  const saturation = lightness > 0.5 ? delta / (2 - max - min) : delta / (max + min);
  let hue = 0;
  switch (max) {
    case normalizedRed:
      hue = (normalizedGreen - normalizedBlue) / delta + (normalizedGreen < normalizedBlue ? 6 : 0);
      break;
    case normalizedGreen:
      hue = (normalizedBlue - normalizedRed) / delta + 2;
      break;
    default:
      hue = (normalizedRed - normalizedGreen) / delta + 4;
      break;
  }
  return [hue / 6, saturation, lightness];
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
function rgbToHex(red, green, blue) {
  return `#${[red, green, blue].map((channel) => Math.max(0, Math.min(255, channel)).toString(16).padStart(2, "0")).join("")}`;
}
function applyExcelTint(baseColor, tint) {
  const rgb = parseHexColor(baseColor);
  if (!rgb || !Number.isFinite(tint) || tint === 0) {
    return normalizeHexColor(baseColor);
  }
  const [hue, saturation, lightness] = rgbToHsl(rgb[0], rgb[1], rgb[2]);
  const nextLightness = tint < 0 ? lightness * (1 + tint) : lightness * (1 - tint) + tint;
  const [nextRed, nextGreen, nextBlue] = hslToRgb(hue, saturation, Math.max(0, Math.min(1, nextLightness)));
  return rgbToHex(nextRed, nextGreen, nextBlue);
}
function buildThemePaletteFromHex(hexColors) {
  const colorsByIndex = {};
  hexColors.forEach((hex, index) => {
    const color = normalizeHexColor(hex);
    if (color) {
      colorsByIndex[index] = color;
    }
  });
  return { colorsByIndex };
}
function resolveWorkbookColor(color, themePalette) {
  if (!color) {
    return null;
  }
  const directHex = ["hex", "rgb", "argb"].map((key) => color[key]).find((value) => typeof value === "string" && value.trim().length > 0);
  if (directHex) {
    return normalizeHexColor(directHex);
  }
  const themeValue = color.theme ?? color.themeIndex;
  const numericTheme = typeof themeValue === "number" ? themeValue : typeof themeValue === "string" && themeValue.trim().length > 0 ? Number(themeValue) : Number.NaN;
  const themeColor2 = Number.isFinite(numericTheme) ? themePalette?.colorsByIndex[numericTheme] ?? null : null;
  if (!themeColor2) {
    return null;
  }
  const tintValue = color.tint;
  const tint = typeof tintValue === "number" ? tintValue : typeof tintValue === "string" && tintValue.trim().length > 0 ? Number(tintValue) : Number.NaN;
  return Number.isFinite(tint) ? applyExcelTint(themeColor2, tint) : themeColor2;
}
function resolveWorkbookFillColor(fill, themePalette) {
  if (!fill) {
    return null;
  }
  if (fill.fillType === "solid") {
    return resolveWorkbookColor(
      fill.color ?? fill.foreground ?? fill.background,
      themePalette
    );
  }
  if (fill.fillType === "pattern") {
    return resolveWorkbookColor(
      fill.foreground ?? fill.color ?? fill.background,
      themePalette
    );
  }
  return null;
}
function resolveWorkbookFillStyle(fill, themePalette) {
  if (!fill) {
    return {
      backgroundColor: null,
      backgroundImage: null
    };
  }
  if (fill.fillType === "gradient") {
    const rawStops = Array.isArray(fill.stops) ? fill.stops : [];
    const stops = rawStops.map((stop) => ({
      color: resolveWorkbookColor(stop.color, themePalette),
      position: typeof stop.position === "number" ? stop.position : Number(stop.position)
    })).filter((stop) => Boolean(stop.color) && Number.isFinite(stop.position)).sort((left, right) => left.position - right.position);
    if (stops.length > 0) {
      const gradientType = typeof fill.gradientType === "string" ? fill.gradientType : "linear";
      if (gradientType === "path") {
        const backgroundColor = stops[stops.length - 1]?.color ?? null;
        return {
          backgroundColor,
          backgroundImage: `radial-gradient(circle at center, ${stops.map((stop) => `${stop.color} ${Math.max(0, Math.min(100, stop.position * 100))}%`).join(", ")})`
        };
      }
      const degree = typeof fill.degree === "number" ? fill.degree : Number(fill.degree ?? 0);
      const cssAngle = Number.isFinite(degree) ? 90 - degree : 90;
      return {
        backgroundColor: stops[stops.length - 1]?.color ?? null,
        backgroundImage: `linear-gradient(${cssAngle}deg, ${stops.map((stop) => `${stop.color} ${Math.max(0, Math.min(100, stop.position * 100))}%`).join(", ")})`
      };
    }
  }
  return {
    backgroundColor: resolveWorkbookFillColor(fill, themePalette),
    backgroundImage: null
  };
}

// src/images.ts
import { strFromU8, strToU8, zipSync } from "fflate";
var REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
var PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships";
var SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
var CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types";
var DRAWING_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing";
var IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image";
var DRAWING_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.drawing+xml";
var EMU_PER_PIXEL = 9525;
var MIN_COL_WIDTH_PX = 30;
var MIN_ROW_HEIGHT_PX = 16;
var DEFAULT_COL_WIDTH_EMU = 64 * EMU_PER_PIXEL;
var DEFAULT_ROW_HEIGHT_EMU = 20 * EMU_PER_PIXEL;
var DEFAULT_COLUMN_CHARACTER_WIDTH_PX = 7;
var pictureSources = /* @__PURE__ */ new WeakMap();
var columnCharacterWidthCache = /* @__PURE__ */ new Map();
function resolveDeviceGridlineThicknessPx() {
  if (typeof window === "undefined") {
    return 1;
  }
  const devicePixelRatio = window.devicePixelRatio;
  if (!Number.isFinite(devicePixelRatio) || devicePixelRatio <= 0) {
    return 1;
  }
  return 1 / devicePixelRatio;
}
function measureColumnCharacterWidthPx(fontFamily, fontSizePt) {
  const normalizedFamily = typeof fontFamily === "string" && fontFamily.trim().length > 0 ? fontFamily.trim() : "Calibri";
  const normalizedSizePt = typeof fontSizePt === "number" && Number.isFinite(fontSizePt) && fontSizePt > 0 ? fontSizePt : 11;
  const cacheKey = `${normalizedFamily}|${normalizedSizePt}`;
  const cached = columnCharacterWidthCache.get(cacheKey);
  if (cached !== void 0) {
    return cached;
  }
  const fontSizePx = normalizedSizePt * (96 / 72);
  const family = JSON.stringify(normalizedFamily);
  const fallback = normalizedFamily.toLowerCase() === "calibri" || normalizedFamily.toLowerCase() === "carlito" ? ', "Carlito"' : "";
  const font = `${fontSizePx}px ${family}${fallback}`;
  let width = DEFAULT_COLUMN_CHARACTER_WIDTH_PX;
  try {
    const context = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : typeof OffscreenCanvas !== "undefined" ? new OffscreenCanvas(32, 32).getContext("2d") : null;
    if (context) {
      context.font = font;
      width = Math.max(1, context.measureText("0").width);
    }
  } catch {
    width = DEFAULT_COLUMN_CHARACTER_WIDTH_PX;
  }
  columnCharacterWidthCache.set(cacheKey, width);
  return width;
}
function measureOfficeDigitWidthPt(fontFamily, fontSizePt) {
  const family = fontFamily?.trim() || "Calibri";
  const size = typeof fontSizePt === "number" && fontSizePt > 0 ? fontSizePt : 11;
  const key = `office|${family}|${size}`;
  const cached = columnCharacterWidthCache.get(key);
  if (cached !== void 0) return cached;
  const context = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : typeof OffscreenCanvas !== "undefined" ? new OffscreenCanvas(32, 32).getContext("2d") : null;
  if (!context) return 6;
  context.font = `${size}px ${JSON.stringify(family)}, "Carlito"`;
  const width = Math.max(1, Math.round(Math.max(...Array.from("0123456789", (digit) => context.measureText(digit).width))));
  columnCharacterWidthCache.set(key, width);
  return width;
}
function getColumnFontMeasurements() {
  return Array.from(columnCharacterWidthCache);
}
function restoreColumnFontMeasurements(entries) {
  for (const [key, value] of entries) columnCharacterWidthCache.set(key, value);
}
function getUnmeasuredWorkbookFont(archive) {
  const font = parseWorkbookStyles(archive).defaultFont;
  const family = font?.family?.trim() || "Calibri";
  const size = font?.sizePt && font.sizePt > 0 ? font.sizePt : 11;
  return columnCharacterWidthCache.has(`${family}|${size}`) && columnCharacterWidthCache.has(`office|${family}|${size}`) ? null : family;
}
function sheetColumnWidthToPixels(width, columnCharacterWidthPx = DEFAULT_COLUMN_CHARACTER_WIDTH_PX) {
  if (!Number.isFinite(width) || width <= 0) {
    return MIN_COL_WIDTH_PX;
  }
  const digitWidth = Math.max(1, columnCharacterWidthPx);
  const pixels = width < 1 ? Math.floor(width * (digitWidth + 5) + 0.5) : Math.floor((256 * width + Math.floor(128 / digitWidth)) / 256 * digitWidth);
  return Math.max(MIN_COL_WIDTH_PX, pixels);
}
function resolveWorksheetDefaultColumnWidthPixels(worksheet, columnCharacterWidthPx = DEFAULT_COLUMN_CHARACTER_WIDTH_PX, fallbackPx = sheetColumnWidthToPixels(8.43, columnCharacterWidthPx)) {
  const width = typeof worksheet.defaultColumnWidth === "number" ? worksheet.defaultColumnWidth : Number.NaN;
  return Number.isFinite(width) && width > 0 ? sheetColumnWidthToPixels(width, columnCharacterWidthPx) : fallbackPx;
}
function resolveWorksheetDefaultRowHeightPixels(worksheet, fallbackPx = Math.max(MIN_ROW_HEIGHT_PX, Math.round(15 * 1.33))) {
  const height = typeof worksheet.defaultRowHeight === "number" ? worksheet.defaultRowHeight : Number.NaN;
  return Number.isFinite(height) && height > 0 ? Math.max(MIN_ROW_HEIGHT_PX, Math.round(height * 1.33)) : fallbackPx;
}
function resolveWorksheetMergeMetadata(worksheet) {
  const mergeMetadata = {
    hasHorizontalMerges: false,
    hasVerticalMerges: false,
    maxHorizontalMergeEndCol: -1,
    maxVerticalMergeEndRow: -1,
    mergedRanges: []
  };
  const mergedRegions = Array.isArray(worksheet.mergedRegions) ? worksheet.mergedRegions : [];
  for (const rawRegion of mergedRegions) {
    let range = null;
    if (typeof rawRegion === "string") {
      range = parseA1RangeReference(rawRegion);
    } else if (rawRegion && typeof rawRegion === "object") {
      const region = rawRegion;
      const startRow = typeof region.startRow === "number" ? region.startRow : Number.NaN;
      const startCol = typeof region.startCol === "number" ? region.startCol : Number.NaN;
      const endRow = typeof region.endRow === "number" ? region.endRow : Number.NaN;
      const endCol = typeof region.endCol === "number" ? region.endCol : Number.NaN;
      if ([startRow, startCol, endRow, endCol].every((value) => Number.isFinite(value) && value >= 0)) {
        range = {
          end: {
            col: Math.max(startCol, endCol),
            row: Math.max(startRow, endRow)
          },
          start: {
            col: Math.min(startCol, endCol),
            row: Math.min(startRow, endRow)
          }
        };
      } else if (typeof region.range === "string") {
        range = parseA1RangeReference(region.range);
      }
    }
    if (!range) {
      continue;
    }
    mergeMetadata.mergedRanges.push(range);
    if (range.end.col > range.start.col) {
      mergeMetadata.hasHorizontalMerges = true;
      mergeMetadata.maxHorizontalMergeEndCol = Math.max(mergeMetadata.maxHorizontalMergeEndCol, range.end.col);
    }
    if (range.end.row > range.start.row) {
      mergeMetadata.hasVerticalMerges = true;
      mergeMetadata.maxVerticalMergeEndRow = Math.max(mergeMetadata.maxVerticalMergeEndRow, range.end.row);
    }
  }
  return mergeMetadata;
}
function buildThemePalette(theme) {
  const themeOrder = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink"];
  const colorsByIndex = {};
  themeOrder.forEach((key, index) => {
    const color = theme.colors.get(key);
    if (color) {
      colorsByIndex[index] = color;
    }
  });
  return {
    colorsByIndex,
    majorLatinFont: theme.majorLatinFont ?? void 0,
    minorLatinFont: theme.minorLatinFont ?? void 0
  };
}
function cloneBytes(bytes) {
  const nextBytes = new Uint8Array(bytes.byteLength);
  nextBytes.set(bytes);
  return nextBytes;
}
function normalizeArchivePath(path) {
  return path.replace(/\\/g, "/").replace(/^\/+/, "");
}
function joinArchivePath(...parts) {
  return normalizeArchivePath(parts.join("/"));
}
function dirname(path) {
  const normalized = normalizeArchivePath(path);
  const lastSlash = normalized.lastIndexOf("/");
  return lastSlash >= 0 ? normalized.slice(0, lastSlash) : "";
}
function resolveArchiveTarget(baseDocumentPath, target) {
  if (!target) {
    return normalizeArchivePath(baseDocumentPath);
  }
  if (target.startsWith("#")) {
    return target;
  }
  if (target.startsWith("/")) {
    return normalizeArchivePath(target);
  }
  const baseParts = dirname(baseDocumentPath).split("/").filter(Boolean);
  for (const segment of target.split("/")) {
    if (!segment || segment === ".") {
      continue;
    }
    if (segment === "..") {
      baseParts.pop();
      continue;
    }
    baseParts.push(segment);
  }
  return normalizeArchivePath(baseParts.join("/"));
}
function relativeArchivePath(fromDocumentPath, toPath) {
  const fromParts = dirname(fromDocumentPath).split("/").filter(Boolean);
  const toParts = normalizeArchivePath(toPath).split("/").filter(Boolean);
  let shared = 0;
  while (shared < fromParts.length && shared < toParts.length && fromParts[shared] === toParts[shared]) {
    shared += 1;
  }
  const upSegments = fromParts.slice(shared).map(() => "..");
  const downSegments = toParts.slice(shared);
  return [...upSegments, ...downSegments].join("/") || ".";
}
function relsPathForDocument(documentPath) {
  const baseName = documentPath.split("/").pop();
  const parentDir = dirname(documentPath);
  return joinArchivePath(parentDir, "_rels", `${baseName}.rels`);
}
function parseXml(xml) {
  try {
    return parseWorkbookXml(xml);
  } catch {
    return null;
  }
}
function serializeXml(document2) {
  return serializeWorkbookXml(document2);
}
function readArchiveText(archive, path) {
  const entry = archive[path];
  return entry ? strFromU8(entry) : null;
}
function parseColumnReference(reference) {
  let value = 0;
  for (const character of reference.toUpperCase()) {
    if (character < "A" || character > "Z") {
      return null;
    }
    value = value * 26 + (character.charCodeAt(0) - 64);
  }
  return value > 0 ? value - 1 : null;
}
function parseA1CellReference(reference) {
  const match = /^\$?([A-Za-z]+)\$?(\d+)$/.exec(reference.trim());
  if (!match) {
    return null;
  }
  const col = parseColumnReference(match[1] ?? "");
  const row = Number(match[2] ?? Number.NaN) - 1;
  if (col === null || !Number.isFinite(row) || row < 0) {
    return null;
  }
  return { col, row };
}
function parseA1RangeReference(reference) {
  const [startRef, endRef] = reference.split(":");
  const start = parseA1CellReference(startRef ?? "");
  const end = parseA1CellReference(endRef ?? startRef ?? "");
  return start && end ? { end, start } : null;
}
function stripSheetNameFromFormulaReference(reference) {
  const trimmed = reference.trim();
  const bangIndex = trimmed.lastIndexOf("!");
  return bangIndex >= 0 ? trimmed.slice(bangIndex + 1) : trimmed;
}
function parseFormulaCellReference(reference) {
  const normalized = stripSheetNameFromFormulaReference(reference).split(/\s+/)[0] ?? "";
  return parseA1CellReference(normalized);
}
function parseFormulaRangeReference(reference) {
  return parseA1RangeReference(stripSheetNameFromFormulaReference(reference));
}
function isElementNode(node) {
  return Boolean(node && node.nodeType === 1);
}
function getLocalElements(parent, localName) {
  return Array.from(parent.getElementsByTagName("*")).filter((node) => isElementNode(node) && node.localName === localName);
}
function getChildElements(parent, localName) {
  return Array.from(parent.childNodes).filter((node) => isElementNode(node) && node.localName === localName);
}
function getFirstChild(parent, localName) {
  return getChildElements(parent, localName)[0] ?? null;
}
function getFirstDescendant(parent, localName) {
  return getLocalElements(parent, localName)[0] ?? null;
}
function readFeaturePropertyBagCheckboxComplements(archive) {
  const xml = readArchiveText(archive, "xl/featurePropertyBag/featurePropertyBag.xml");
  if (!xml) {
    return /* @__PURE__ */ new Set();
  }
  const document2 = parseXml(xml);
  if (!document2?.documentElement) {
    return /* @__PURE__ */ new Set();
  }
  const bagNodes = getChildElements(document2.documentElement, "bag");
  const bagTypeById = bagNodes.map((node) => node.getAttribute("type") ?? "");
  const checkboxComplementIndices = /* @__PURE__ */ new Set();
  const xfComplementsBag = bagNodes.find((node) => node.getAttribute("type") === "XFComplements") ?? null;
  const mappedBagIds = xfComplementsBag ? getLocalElements(xfComplementsBag, "bagId").map((node) => Number(node.textContent ?? Number.NaN)).filter((value) => Number.isFinite(value)) : [];
  mappedBagIds.forEach((bagId, complementIndex) => {
    const xfComplementBag = bagNodes[bagId];
    if (!xfComplementBag || bagTypeById[bagId] !== "XFComplement") {
      return;
    }
    const xfControlsBagId = getLocalElements(xfComplementBag, "bagId").map((node) => Number(node.textContent ?? Number.NaN)).find((value) => Number.isFinite(value));
    if (xfControlsBagId === void 0) {
      return;
    }
    const xfControlsBag = bagNodes[xfControlsBagId];
    if (!xfControlsBag || bagTypeById[xfControlsBagId] !== "XFControls") {
      return;
    }
    const cellControlBagId = getLocalElements(xfControlsBag, "bagId").map((node) => Number(node.textContent ?? Number.NaN)).find((value) => Number.isFinite(value));
    if (cellControlBagId === void 0) {
      return;
    }
    if (bagTypeById[cellControlBagId] === "Checkbox") {
      checkboxComplementIndices.add(complementIndex);
    }
  });
  return checkboxComplementIndices;
}
function getRelationshipId(element) {
  return element.getAttributeNS(REL_NS, "id") ?? element.getAttribute("r:id") ?? element.getAttribute("id");
}
function getEmbeddedRelationshipId(element) {
  return element.getAttributeNS(REL_NS, "embed") ?? element.getAttribute("r:embed") ?? element.getAttribute("embed");
}
function setChildText(parent, localName, value) {
  const child = getFirstChild(parent, localName);
  if (child) {
    child.textContent = value;
  }
}
function updateMarkerElement(element, marker) {
  if (!element) {
    return;
  }
  setChildText(element, "col", String(Math.max(0, marker.col)));
  setChildText(element, "colOff", String(Math.max(0, Math.round(marker.colOffsetEmu))));
  setChildText(element, "row", String(Math.max(0, marker.row)));
  setChildText(element, "rowOff", String(Math.max(0, Math.round(marker.rowOffsetEmu))));
}
function parseContentTypes(archive) {
  const xml = readArchiveText(archive, "[Content_Types].xml");
  const defaultEntries = /* @__PURE__ */ new Map();
  const overrideEntries = /* @__PURE__ */ new Map();
  if (!xml) {
    return { defaultEntries, overrideEntries };
  }
  const document2 = parseXml(xml);
  if (!document2) {
    return { defaultEntries, overrideEntries };
  }
  for (const defaultNode of getLocalElements(document2, "Default")) {
    const extension = defaultNode.getAttribute("Extension");
    const contentType = defaultNode.getAttribute("ContentType");
    if (extension && contentType) {
      defaultEntries.set(extension.toLowerCase(), contentType);
    }
  }
  for (const overrideNode of getLocalElements(document2, "Override")) {
    const partName = overrideNode.getAttribute("PartName");
    const contentType = overrideNode.getAttribute("ContentType");
    if (partName && contentType) {
      overrideEntries.set(normalizeArchivePath(partName), contentType);
    }
  }
  return { defaultEntries, overrideEntries };
}
function resolveContentType(contentTypes, path) {
  const normalized = normalizeArchivePath(path);
  const override = contentTypes.overrideEntries.get(normalized);
  if (override) {
    return override;
  }
  const extension = normalized.split(".").pop()?.toLowerCase();
  if (!extension) {
    return "application/octet-stream";
  }
  return contentTypes.defaultEntries.get(extension) ?? "application/octet-stream";
}
function parseRelationships(archive, relsPath, baseDocumentPath) {
  const xml = readArchiveText(archive, relsPath);
  const relationships = /* @__PURE__ */ new Map();
  if (!xml) {
    return relationships;
  }
  const document2 = parseXml(xml);
  if (!document2) {
    return relationships;
  }
  for (const relationshipNode of getLocalElements(document2, "Relationship")) {
    const id = relationshipNode.getAttribute("Id");
    const target = relationshipNode.getAttribute("Target");
    const type = relationshipNode.getAttribute("Type");
    if (!id || !target || !type) {
      continue;
    }
    relationships.set(id, {
      id,
      target: resolveArchiveTarget(baseDocumentPath, target),
      targetMode: relationshipNode.getAttribute("TargetMode"),
      type
    });
  }
  return relationships;
}
function parseWorkbookSheets(archive) {
  const workbookXml = readArchiveText(archive, "xl/workbook.xml");
  if (!workbookXml) {
    return [];
  }
  const workbookDocument = parseXml(workbookXml);
  if (!workbookDocument) {
    return [];
  }
  const workbookRelationships = parseRelationships(archive, "xl/_rels/workbook.xml.rels", "xl/workbook.xml");
  const sheets = [];
  for (const sheetNode of getLocalElements(workbookDocument, "sheet")) {
    const relationshipId = getRelationshipId(sheetNode);
    if (!relationshipId) {
      continue;
    }
    const relationship = workbookRelationships.get(relationshipId);
    if (!relationship) {
      continue;
    }
    sheets.push({
      name: sheetNode.getAttribute("name") ?? `Sheet ${sheets.length + 1}`,
      path: relationship.target
    });
  }
  return sheets;
}
function parseWorkbookTheme(archive) {
  const defaultTheme = {
    colors: /* @__PURE__ */ new Map([
      ["accent1", "#5b9bd5"],
      ["accent2", "#ed7d31"],
      ["accent3", "#a5a5a5"],
      ["accent4", "#ffc000"],
      ["accent5", "#4472c4"],
      ["accent6", "#70ad47"],
      ["bg1", "#ffffff"],
      ["bg2", "#e7e6e6"],
      ["dk1", "#000000"],
      ["dk2", "#6e747a"],
      ["folHlink", "#993366"],
      ["hlink", "#085296"],
      ["lt1", "#ffffff"],
      ["lt2", "#e7e6e6"],
      ["tx1", "#000000"],
      ["tx2", "#6e747a"]
    ]),
    majorLatinFont: null,
    minorLatinFont: null
  };
  const themeXml = readArchiveText(archive, "xl/theme/theme1.xml");
  if (!themeXml) {
    return defaultTheme;
  }
  const themeDocument = parseXml(themeXml);
  if (!themeDocument) {
    return defaultTheme;
  }
  const colors = new Map(defaultTheme.colors);
  const colorSchemeNode = getLocalElements(themeDocument, "clrScheme")[0] ?? null;
  if (colorSchemeNode) {
    for (const colorNode of Array.from(colorSchemeNode.childNodes).filter(isElementNode)) {
      const key = colorNode.localName;
      const srgbNode = getFirstChild(colorNode, "srgbClr");
      const sysNode = getFirstChild(colorNode, "sysClr");
      const hex = srgbNode?.getAttribute("val") ?? sysNode?.getAttribute("lastClr");
      if (hex) {
        colors.set(key, normalizeHexColor2(hex));
      }
    }
  }
  const fontSchemeNode = getLocalElements(themeDocument, "fontScheme")[0] ?? null;
  const majorLatinFont = getFirstChild(getFirstChild(fontSchemeNode, "majorFont"), "latin")?.getAttribute("typeface") ?? null;
  const minorLatinFont = getFirstChild(getFirstChild(fontSchemeNode, "minorFont"), "latin")?.getAttribute("typeface") ?? null;
  colors.set("bg1", colors.get("lt1") ?? defaultTheme.colors.get("bg1") ?? "#ffffff");
  colors.set("tx1", colors.get("dk1") ?? defaultTheme.colors.get("tx1") ?? "#000000");
  colors.set("bg2", colors.get("lt2") ?? defaultTheme.colors.get("bg2") ?? "#e7e6e6");
  colors.set("tx2", colors.get("dk2") ?? defaultTheme.colors.get("tx2") ?? "#6e747a");
  return {
    colors,
    majorLatinFont,
    minorLatinFont
  };
}
function parseSpreadsheetColor(node) {
  if (!node) {
    return void 0;
  }
  const color = {};
  const rgb = node.getAttribute("rgb");
  const theme = node.getAttribute("theme");
  const tint = node.getAttribute("tint");
  const indexed = node.getAttribute("indexed");
  if (rgb) {
    color.rgb = normalizeHexColor2(rgb);
  }
  if (theme !== null) {
    color.theme = Number(theme);
  }
  if (tint !== null) {
    color.tint = Number(tint);
  }
  if (indexed !== null) {
    color.indexed = Number(indexed);
  }
  return Object.keys(color).length > 0 ? color : void 0;
}
function hasEnabledSpreadsheetFlag(node) {
  if (!node) {
    return false;
  }
  const value = node.getAttribute("val");
  return value === null || value !== "0" && value !== "false";
}
function parseSheetSparklines(document2, themePalette) {
  const sparklines = [];
  for (const groupNode of getLocalElements(document2, "sparklineGroup")) {
    const rawType = groupNode.getAttribute("type");
    const sparklineType = rawType === "column" ? "column" : rawType === "stacked" ? "winLoss" : "line";
    const markersNode = getFirstChild(groupNode, "markers");
    const negativeNode = getFirstChild(groupNode, "negative");
    const colorSeries = resolveWorkbookColor(parseSpreadsheetColor(getFirstChild(groupNode, "colorSeries")), themePalette);
    const colorNegative = resolveWorkbookColor(parseSpreadsheetColor(getFirstChild(groupNode, "colorNegative")), themePalette);
    const colorMarkers = resolveWorkbookColor(parseSpreadsheetColor(getFirstChild(groupNode, "colorMarkers")), themePalette);
    const colorFirst = resolveWorkbookColor(parseSpreadsheetColor(getFirstChild(groupNode, "colorFirst")), themePalette);
    const colorLast = resolveWorkbookColor(parseSpreadsheetColor(getFirstChild(groupNode, "colorLast")), themePalette);
    const colorHigh = resolveWorkbookColor(parseSpreadsheetColor(getFirstChild(groupNode, "colorHigh")), themePalette);
    const colorLow = resolveWorkbookColor(parseSpreadsheetColor(getFirstChild(groupNode, "colorLow")), themePalette);
    const sparklineCollectionNode = getFirstChild(groupNode, "sparklines");
    if (!sparklineCollectionNode) {
      continue;
    }
    for (const sparklineNode of getChildElements(sparklineCollectionNode, "sparkline")) {
      const formula = getFirstChild(sparklineNode, "f")?.textContent ?? "";
      const targetReference = getFirstChild(sparklineNode, "sqref")?.textContent ?? "";
      const range = parseFormulaRangeReference(formula);
      const target = parseFormulaCellReference(targetReference);
      if (!range || !target) {
        continue;
      }
      sparklines.push({
        color: colorSeries ?? void 0,
        firstColor: colorFirst ?? void 0,
        highColor: colorHigh ?? void 0,
        lastColor: colorLast ?? void 0,
        lowColor: colorLow ?? void 0,
        markerColor: colorMarkers ?? void 0,
        markers: hasEnabledSpreadsheetFlag(markersNode),
        negative: hasEnabledSpreadsheetFlag(negativeNode),
        negativeColor: colorNegative ?? void 0,
        range,
        target,
        type: sparklineType
      });
    }
  }
  return sparklines;
}
function parseSpreadsheetFont(node) {
  if (!node) {
    return void 0;
  }
  const font = {};
  for (const [tag, property] of [["b", "bold"], ["i", "italic"], ["strike", "strikethrough"]]) {
    const flag = getFirstChild(node, tag);
    if (flag) {
      font[property] = hasEnabledSpreadsheetFlag(flag);
    }
  }
  const size = getFirstChild(node, "sz")?.getAttribute("val");
  const name = getFirstChild(node, "name")?.getAttribute("val");
  const family = getFirstChild(node, "family")?.getAttribute("val");
  const scheme = getFirstChild(node, "scheme")?.getAttribute("val");
  const charset = getFirstChild(node, "charset")?.getAttribute("val");
  const verticalAlign = getFirstChild(node, "vertAlign")?.getAttribute("val");
  const color = parseSpreadsheetColor(getFirstChild(node, "color"));
  if (getFirstChild(node, "u")) {
    font.underline = getFirstChild(node, "u")?.getAttribute("val") ?? "single";
  }
  if (size !== null && size !== void 0) {
    font.size = Number(size);
  }
  if (name) {
    font.name = name;
  }
  if (family !== null && family !== void 0) {
    font.family = Number(family);
  }
  if (scheme) {
    font.scheme = scheme;
  }
  if (charset !== null && charset !== void 0) {
    font.charset = Number(charset);
  }
  if (verticalAlign) {
    font.verticalAlign = verticalAlign;
  }
  if (hasEnabledSpreadsheetFlag(getFirstChild(node, "shadow"))) {
    font.shadow = true;
  }
  if (hasEnabledSpreadsheetFlag(getFirstChild(node, "outline"))) {
    font.outline = true;
  }
  if (hasEnabledSpreadsheetFlag(getFirstChild(node, "condense"))) {
    font.condense = true;
  }
  if (hasEnabledSpreadsheetFlag(getFirstChild(node, "extend"))) {
    font.extend = true;
  }
  if (color) {
    font.color = color;
  }
  return Object.keys(font).length > 0 ? font : void 0;
}
function parseSpreadsheetFill(node) {
  if (!node) {
    return void 0;
  }
  const gradientFill = getFirstChild(node, "gradientFill");
  if (gradientFill) {
    const stops = Array.from(gradientFill.childNodes).filter(isElementNode).filter((child) => child.localName === "stop").map((stopNode) => ({
      color: parseSpreadsheetColor(Array.from(stopNode.childNodes).find(isElementNode) ?? null),
      position: Number(stopNode.getAttribute("position") ?? Number.NaN)
    })).filter((stop) => stop.color && Number.isFinite(stop.position));
    if (stops.length > 0) {
      return {
        degree: Number(gradientFill.getAttribute("degree") ?? 0),
        fillType: "gradient",
        gradientType: gradientFill.getAttribute("type") ?? "linear",
        stops
      };
    }
  }
  const patternFill = getFirstChild(node, "patternFill");
  if (!patternFill) {
    return void 0;
  }
  const patternType = patternFill.getAttribute("patternType") ?? "none";
  const foreground = parseSpreadsheetColor(getFirstChild(patternFill, "fgColor"));
  const background = parseSpreadsheetColor(getFirstChild(patternFill, "bgColor"));
  const solidColor = foreground ?? background;
  if (patternType === "solid" && solidColor) {
    return {
      color: solidColor,
      fillType: "solid"
    };
  }
  if ((patternType === "none" || patternType === "gray125") && (foreground || background)) {
    return {
      background,
      fillType: "pattern",
      foreground,
      patternType
    };
  }
  if (patternType !== "none" && patternType !== "gray125" && (foreground || background)) {
    return {
      background,
      fillType: "pattern",
      foreground,
      patternType
    };
  }
  return void 0;
}
function parseSpreadsheetBorderEdge(node) {
  if (!node) {
    return void 0;
  }
  const style = node.getAttribute("style");
  const color = parseSpreadsheetColor(getFirstChild(node, "color"));
  if (!style || style === "none") {
    return void 0;
  }
  return {
    color,
    style
  };
}
function parseSpreadsheetBorder(node) {
  if (!node) {
    return void 0;
  }
  const border = {};
  ["top", "right", "bottom", "left", "horizontal", "vertical"].forEach((edge) => {
    const parsedEdge = parseSpreadsheetBorderEdge(getFirstChild(node, edge));
    if (parsedEdge) {
      border[edge] = parsedEdge;
    }
  });
  return Object.keys(border).length > 0 ? border : void 0;
}
function parseSpreadsheetAlignment(node) {
  if (!node) {
    return void 0;
  }
  const alignment = {};
  const horizontal = node.getAttribute("horizontal");
  const vertical = node.getAttribute("vertical");
  const wrapText = node.getAttribute("wrapText");
  const indent = node.getAttribute("indent");
  const shrinkToFit = node.getAttribute("shrinkToFit");
  const textRotation = node.getAttribute("textRotation");
  if (horizontal) {
    alignment.horizontal = horizontal;
  }
  if (vertical) {
    alignment.vertical = vertical;
  }
  if (wrapText !== null) {
    alignment.wrapText = wrapText === "1";
  }
  if (shrinkToFit !== null) {
    alignment.shrinkToFit = shrinkToFit === "1";
  }
  if (indent !== null) {
    alignment.indent = Number(indent);
  }
  if (textRotation !== null) {
    const parsedRotation = Number(textRotation);
    if (Number.isFinite(parsedRotation)) {
      alignment.rotation = parsedRotation;
    }
  }
  return Object.keys(alignment).length > 0 ? alignment : void 0;
}
function parseDifferentialStyle(node) {
  if (!node) {
    return {};
  }
  const style = {};
  const font = parseSpreadsheetFont(getFirstChild(node, "font"));
  const fill = parseSpreadsheetFill(getFirstChild(node, "fill"));
  const border = parseSpreadsheetBorder(getFirstChild(node, "border"));
  const alignment = parseSpreadsheetAlignment(getFirstChild(node, "alignment"));
  if (font) {
    style.font = font;
  }
  if (fill) {
    style.fill = fill;
  }
  if (border) {
    style.border = border;
  }
  if (alignment) {
    style.alignment = alignment;
  }
  return style;
}
function parseResolvedXfStyle(xfNode, fonts, fills, borders, checkboxComplementIndices) {
  const style = {};
  const fontId = Number(xfNode.getAttribute("fontId") ?? Number.NaN);
  const fillId = Number(xfNode.getAttribute("fillId") ?? Number.NaN);
  const borderId = Number(xfNode.getAttribute("borderId") ?? Number.NaN);
  const alignment = parseSpreadsheetAlignment(getFirstChild(xfNode, "alignment"));
  if (Number.isFinite(fontId) && fonts[fontId]) {
    style.font = fonts[fontId];
  }
  if (Number.isFinite(fillId) && fills[fillId]) {
    style.fill = fills[fillId];
  }
  if (Number.isFinite(borderId) && borders[borderId]) {
    style.border = borders[borderId];
  }
  if (alignment) {
    style.alignment = alignment;
  }
  const xfComplementNode = getFirstDescendant(xfNode, "xfComplement");
  const xfComplementIndex = Number(xfComplementNode?.getAttribute("i") ?? Number.NaN);
  if (Number.isFinite(xfComplementIndex) && checkboxComplementIndices?.has(xfComplementIndex)) {
    style.cellControl = { kind: "checkbox" };
  }
  return style;
}
function parseWorkbookStyles(archive) {
  const xml = readArchiveText(archive, "xl/styles.xml");
  if (!xml) {
    return {
      differentialStyles: [],
      defaultFont: null,
      namedCellStyleByName: {},
      styleById: {},
      tableStyleByName: {}
    };
  }
  const document2 = parseXml(xml);
  if (!document2) {
    return {
      differentialStyles: [],
      defaultFont: null,
      namedCellStyleByName: {},
      styleById: {},
      tableStyleByName: {}
    };
  }
  const fontsNode = getFirstDescendant(document2, "fonts");
  const fillsNode = getFirstDescendant(document2, "fills");
  const bordersNode = getFirstDescendant(document2, "borders");
  const cellStyleXfsNode = getFirstDescendant(document2, "cellStyleXfs");
  const cellStylesNode = getFirstDescendant(document2, "cellStyles");
  const cellXfsNode = getFirstDescendant(document2, "cellXfs");
  const dxfsNode = getFirstDescendant(document2, "dxfs");
  const tableStylesNode = getFirstDescendant(document2, "tableStyles");
  if (!cellXfsNode) {
    return {
      differentialStyles: [],
      defaultFont: null,
      namedCellStyleByName: {},
      styleById: {},
      tableStyleByName: {}
    };
  }
  const checkboxComplementIndices = readFeaturePropertyBagCheckboxComplements(archive);
  const fonts = getChildElements(fontsNode ?? document2.documentElement, "font").map((node) => parseSpreadsheetFont(node));
  const fills = getChildElements(fillsNode ?? document2.documentElement, "fill").map((node) => parseSpreadsheetFill(node));
  const borders = getChildElements(bordersNode ?? document2.documentElement, "border").map((node) => parseSpreadsheetBorder(node));
  const differentialStyles = getChildElements(dxfsNode ?? document2.documentElement, "dxf").map((node) => parseDifferentialStyle(node));
  const cellStyleXfs = getChildElements(cellStyleXfsNode ?? document2.documentElement, "xf").map(
    (node) => parseResolvedXfStyle(node, fonts, fills, borders, checkboxComplementIndices)
  );
  const namedCellStyleByName = {};
  const styleById = {};
  const tableStyleByName = {};
  getChildElements(cellXfsNode, "xf").forEach((xfNode, index) => {
    const style = parseResolvedXfStyle(xfNode, fonts, fills, borders, checkboxComplementIndices);
    const overrides = {};
    for (const component of ["font", "fill", "border"]) {
      if (Number(xfNode.getAttribute(`${component}Id`) ?? 0) > 0 && xfNode.getAttribute(`apply${component[0].toUpperCase()}${component.slice(1)}`) !== "0") {
        Object.assign(overrides, { [component]: style[component] });
      }
    }
    styleById[index] = { ...style, tableStyleOverrides: overrides };
  });
  getChildElements(cellStylesNode ?? document2.documentElement, "cellStyle").forEach((cellStyleNode) => {
    const name = cellStyleNode.getAttribute("name");
    const xfId = Number(cellStyleNode.getAttribute("xfId") ?? Number.NaN);
    if (!name || !Number.isFinite(xfId)) {
      return;
    }
    const resolvedStyle = cellStyleXfs[xfId];
    if (resolvedStyle) {
      namedCellStyleByName[name] = resolvedStyle;
    }
  });
  getChildElements(tableStylesNode ?? document2.documentElement, "tableStyle").forEach((tableStyleNode) => {
    const name = tableStyleNode.getAttribute("name");
    if (!name) {
      return;
    }
    const elements = {};
    getChildElements(tableStyleNode, "tableStyleElement").forEach((elementNode) => {
      const type = elementNode.getAttribute("type");
      const dxfId = Number(elementNode.getAttribute("dxfId") ?? Number.NaN);
      if (!type || !Number.isFinite(dxfId)) {
        return;
      }
      const differentialStyle = differentialStyles[dxfId];
      if (differentialStyle) {
        elements[type] = differentialStyle;
      }
    });
    tableStyleByName[name] = elements;
  });
  const normalFont = namedCellStyleByName.Normal?.font ?? styleById[0]?.font ?? fonts[0];
  const defaultFont = normalFont ? {
    family: typeof normalFont.name === "string" ? normalFont.name : void 0,
    sizePt: typeof normalFont.size === "number" ? normalFont.size : void 0
  } : null;
  return {
    differentialStyles,
    defaultFont,
    namedCellStyleByName,
    styleById,
    tableStyleByName
  };
}
function parseSqrefRanges(sqref) {
  if (!sqref) {
    return [];
  }
  return sqref.trim().split(/\s+/).flatMap((reference) => {
    const range = parseA1RangeReference(reference);
    return range ? [range] : [];
  });
}
function parseConditionalFormatValueObject(node) {
  if (!node) {
    return null;
  }
  const type = node.getAttribute("type");
  if (!type) {
    return null;
  }
  const rawValue = node.getAttribute("val") ?? getFirstChild(node, "f")?.textContent ?? void 0;
  const numericValue = rawValue !== void 0 ? Number(rawValue) : Number.NaN;
  return {
    type,
    value: Number.isFinite(numericValue) ? numericValue : void 0
  };
}
function parseSpreadsheetBooleanAttribute(node, name) {
  if (!node) {
    return void 0;
  }
  const value = node.getAttribute(name);
  if (value === null) {
    return void 0;
  }
  return value !== "0" && value !== "false";
}
function parseStandardConditionalFormatRule(cfRuleNode, ranges, differentialStyles = []) {
  const type = cfRuleNode.getAttribute("type");
  const rawPriority = Number(cfRuleNode.getAttribute("priority") ?? Number.NaN);
  const priority = Number.isFinite(rawPriority) ? rawPriority : Number.MAX_SAFE_INTEGER;
  const formulas = getChildElements(cfRuleNode, "formula").map((formulaNode) => (formulaNode.textContent ?? "").trim()).filter((formula) => formula.length > 0);
  if (type === "colorScale") {
    const colorScaleNode = getFirstChild(cfRuleNode, "colorScale");
    if (!colorScaleNode) {
      return null;
    }
    const cfvos = getChildElements(colorScaleNode, "cfvo").map((node) => parseConditionalFormatValueObject(node)).filter((value) => Boolean(value));
    const colors = getChildElements(colorScaleNode, "color").map((node) => parseSpreadsheetColor(node)).filter((value) => Boolean(value));
    if (cfvos.length === 0 || colors.length === 0) {
      return null;
    }
    return {
      cfvos,
      colors,
      kind: "colorScale",
      priority,
      ranges
    };
  }
  if (type === "dataBar") {
    const dataBarNode = getFirstChild(cfRuleNode, "dataBar");
    if (!dataBarNode) {
      return null;
    }
    const cfvos = getChildElements(dataBarNode, "cfvo").map((node) => parseConditionalFormatValueObject(node)).filter((value) => Boolean(value));
    if (cfvos.length === 0) {
      return null;
    }
    const extId = getFirstDescendant(cfRuleNode, "id")?.textContent?.trim() || void 0;
    return {
      cfvos,
      color: parseSpreadsheetColor(getFirstChild(dataBarNode, "color")),
      kind: "dataBar",
      maxLength: Number(dataBarNode.getAttribute("maxLength") ?? 90),
      minLength: Number(dataBarNode.getAttribute("minLength") ?? 10),
      priority,
      ranges,
      id: extId
    };
  }
  if (type === "iconSet") {
    const iconSetNode = getFirstChild(cfRuleNode, "iconSet");
    if (!iconSetNode) {
      return null;
    }
    const iconSetName = iconSetNode.getAttribute("iconSet");
    const cfvos = getChildElements(iconSetNode, "cfvo").map((node) => parseConditionalFormatValueObject(node)).filter((value) => Boolean(value));
    if (!iconSetName || cfvos.length === 0) {
      return null;
    }
    return {
      cfvos,
      icons: cfvos.map((_, index) => ({
        iconId: index,
        iconSet: iconSetName
      })),
      kind: "iconSet",
      priority,
      ranges,
      reverse: parseSpreadsheetBooleanAttribute(iconSetNode, "reverse"),
      showValue: parseSpreadsheetBooleanAttribute(iconSetNode, "showValue")
    };
  }
  const rawDxfId = Number(cfRuleNode.getAttribute("dxfId") ?? Number.NaN);
  if (!type || !Number.isFinite(rawDxfId)) {
    return null;
  }
  const style = differentialStyles[rawDxfId];
  if (!style) {
    return null;
  }
  const rawRank = Number(cfRuleNode.getAttribute("rank") ?? Number.NaN);
  const rawStdDev = Number(cfRuleNode.getAttribute("stdDev") ?? Number.NaN);
  return {
    aboveAverage: parseSpreadsheetBooleanAttribute(cfRuleNode, "aboveAverage"),
    bottom: parseSpreadsheetBooleanAttribute(cfRuleNode, "bottom"),
    equalAverage: parseSpreadsheetBooleanAttribute(cfRuleNode, "equalAverage"),
    formulas,
    kind: "styled",
    operator: cfRuleNode.getAttribute("operator") ?? void 0,
    percent: parseSpreadsheetBooleanAttribute(cfRuleNode, "percent"),
    priority,
    rank: Number.isFinite(rawRank) ? rawRank : void 0,
    ranges,
    ruleType: type,
    stdDev: Number.isFinite(rawStdDev) ? rawStdDev : void 0,
    stopIfTrue: parseSpreadsheetBooleanAttribute(cfRuleNode, "stopIfTrue"),
    style,
    text: cfRuleNode.getAttribute("text") ?? void 0,
    timePeriod: cfRuleNode.getAttribute("timePeriod") ?? void 0
  };
}
function parseExtendedConditionalFormatRule(cfRuleNode, ranges) {
  const type = cfRuleNode.getAttribute("type");
  const ruleId = cfRuleNode.getAttribute("id") ?? void 0;
  const rawPriority = Number(cfRuleNode.getAttribute("priority") ?? Number.NaN);
  const priority = Number.isFinite(rawPriority) ? rawPriority : Number.MAX_SAFE_INTEGER;
  if (type === "dataBar") {
    const dataBarNode = getFirstChild(cfRuleNode, "dataBar");
    if (!dataBarNode) {
      return null;
    }
    const cfvos = getChildElements(dataBarNode, "cfvo").map((node) => parseConditionalFormatValueObject(node)).filter((value) => Boolean(value));
    if (cfvos.length === 0) {
      return null;
    }
    return {
      axisColor: parseSpreadsheetColor(getFirstChild(dataBarNode, "axisColor")),
      border: parseSpreadsheetBooleanAttribute(dataBarNode, "border"),
      borderColor: parseSpreadsheetColor(getFirstChild(dataBarNode, "borderColor")),
      cfvos,
      color: parseSpreadsheetColor(getFirstChild(dataBarNode, "fillColor")),
      gradient: parseSpreadsheetBooleanAttribute(dataBarNode, "gradient"),
      kind: "dataBar",
      maxLength: Number(dataBarNode.getAttribute("maxLength") ?? 90),
      minLength: Number(dataBarNode.getAttribute("minLength") ?? 10),
      negativeBarBorderColorSameAsPositive: parseSpreadsheetBooleanAttribute(dataBarNode, "negativeBarBorderColorSameAsPositive"),
      negativeBorderColor: parseSpreadsheetColor(getFirstChild(dataBarNode, "negativeBorderColor")),
      negativeFillColor: parseSpreadsheetColor(getFirstChild(dataBarNode, "negativeFillColor")),
      priority,
      ranges,
      showValue: parseSpreadsheetBooleanAttribute(dataBarNode, "showValue"),
      id: ruleId
    };
  }
  if (type === "iconSet") {
    const iconSetNode = getFirstChild(cfRuleNode, "iconSet");
    if (!iconSetNode) {
      return null;
    }
    const cfvos = getChildElements(iconSetNode, "cfvo").map((node) => parseConditionalFormatValueObject(node)).filter((value) => Boolean(value));
    const icons = getChildElements(iconSetNode, "cfIcon").map((iconNode) => {
      const iconSet = iconNode.getAttribute("iconSet");
      const rawIconId = Number(iconNode.getAttribute("iconId") ?? Number.NaN);
      if (!iconSet || !Number.isFinite(rawIconId)) {
        return null;
      }
      return {
        iconId: rawIconId,
        iconSet
      };
    }).filter((icon) => Boolean(icon));
    if (cfvos.length === 0 || icons.length === 0) {
      return null;
    }
    return {
      cfvos,
      icons,
      kind: "iconSet",
      priority,
      ranges,
      reverse: parseSpreadsheetBooleanAttribute(iconSetNode, "reverse"),
      showValue: parseSpreadsheetBooleanAttribute(iconSetNode, "showValue"),
      id: ruleId
    };
  }
  return null;
}
function mergeConditionalFormatRule(baseRule, extendedRule) {
  if (baseRule.kind !== extendedRule.kind) {
    return baseRule;
  }
  if (baseRule.kind === "colorScale" && extendedRule.kind === "colorScale") {
    return {
      ...baseRule,
      ...extendedRule,
      cfvos: extendedRule.cfvos.length > 0 ? extendedRule.cfvos : baseRule.cfvos,
      colors: extendedRule.colors.length > 0 ? extendedRule.colors : baseRule.colors,
      priority: Number.isFinite(extendedRule.priority) ? extendedRule.priority : baseRule.priority,
      ranges: extendedRule.ranges.length > 0 ? extendedRule.ranges : baseRule.ranges
    };
  }
  if (baseRule.kind === "dataBar" && extendedRule.kind === "dataBar") {
    const merged = {
      ...baseRule,
      ...extendedRule,
      axisColor: extendedRule.axisColor ?? baseRule.axisColor,
      border: extendedRule.border ?? baseRule.border,
      cfvos: extendedRule.cfvos.length > 0 ? extendedRule.cfvos : baseRule.cfvos,
      color: extendedRule.color ?? baseRule.color,
      negativeBarBorderColorSameAsPositive: extendedRule.negativeBarBorderColorSameAsPositive ?? baseRule.negativeBarBorderColorSameAsPositive,
      negativeBorderColor: extendedRule.negativeBorderColor ?? baseRule.negativeBorderColor,
      negativeFillColor: extendedRule.negativeFillColor ?? baseRule.negativeFillColor,
      priority: Number.isFinite(extendedRule.priority) ? extendedRule.priority : baseRule.priority,
      ranges: extendedRule.ranges.length > 0 ? extendedRule.ranges : baseRule.ranges
    };
    return merged;
  }
  if (baseRule.kind === "iconSet" && extendedRule.kind === "iconSet") {
    const merged = {
      ...baseRule,
      ...extendedRule,
      cfvos: extendedRule.cfvos.length > 0 ? extendedRule.cfvos : baseRule.cfvos,
      icons: extendedRule.icons.length > 0 ? extendedRule.icons : baseRule.icons,
      priority: Number.isFinite(extendedRule.priority) ? extendedRule.priority : baseRule.priority,
      ranges: extendedRule.ranges.length > 0 ? extendedRule.ranges : baseRule.ranges
    };
    return merged;
  }
  return baseRule;
}
function parseConditionalFormatRules(document2, differentialStyles = []) {
  const standardRules = [];
  const extendedRules = [];
  getLocalElements(document2, "conditionalFormatting").forEach((conditionalFormattingNode) => {
    const isExtended = conditionalFormattingNode.namespaceURI !== SPREADSHEET_NS;
    const ranges = isExtended ? parseSqrefRanges(getFirstChild(conditionalFormattingNode, "sqref")?.textContent ?? "") : parseSqrefRanges(conditionalFormattingNode.getAttribute("sqref"));
    getChildElements(conditionalFormattingNode, "cfRule").forEach((cfRuleNode) => {
      const parsedRule = isExtended ? parseExtendedConditionalFormatRule(cfRuleNode, ranges) : parseStandardConditionalFormatRule(cfRuleNode, ranges, differentialStyles);
      if (parsedRule) {
        if (isExtended) {
          extendedRules.push(parsedRule);
        } else {
          standardRules.push(parsedRule);
        }
      }
    });
  });
  const mergedRules = [];
  const usedExtendedRuleIds = /* @__PURE__ */ new Set();
  const extendedRulesById = new Map(
    extendedRules.filter((rule) => typeof rule.id === "string" && rule.id.length > 0).map((rule) => [rule.id, rule])
  );
  standardRules.forEach((rule) => {
    const matchingExtendedRule = rule.id ? extendedRulesById.get(rule.id) : void 0;
    if (matchingExtendedRule) {
      usedExtendedRuleIds.add(rule.id);
      mergedRules.push(mergeConditionalFormatRule(rule, matchingExtendedRule));
      return;
    }
    mergedRules.push(rule);
  });
  extendedRules.forEach((rule) => {
    if (rule.id && usedExtendedRuleIds.has(rule.id)) {
      return;
    }
    mergedRules.push(rule);
  });
  return mergedRules.map((rule) => {
    const nextRule = { ...rule };
    delete nextRule.id;
    return nextRule;
  }).filter((rule) => rule.ranges.length > 0).sort((left, right) => left.priority - right.priority);
}
function parseSheetState(archive, path, options) {
  const xml = readArchiveText(archive, path);
  if (!xml) {
    return null;
  }
  const document2 = parseXml(xml);
  if (!document2) {
    return null;
  }
  const includeCachedFormulaValues = options?.includeCachedFormulaValues ?? true;
  const autoFilterRanges = parseSqrefRanges(getLocalElements(document2, "autoFilter")[0]?.getAttribute("ref"));
  const cachedFormulaValues = {};
  const conditionalFormatRules = parseConditionalFormatRules(document2, options?.differentialStyles ?? []);
  const sparklines = parseSheetSparklines(document2, options?.themePalette);
  const sheetFormatNode = getLocalElements(document2, "sheetFormatPr")[0] ?? null;
  const sheetViewNode = getLocalElements(document2, "sheetView")[0] ?? null;
  const rowHeightOverridesPx = {};
  const colWidthOverridesPx = {};
  const rowStyleIds = {};
  const cellStyleIds = {};
  const colStyleIds = {};
  let minContentCol = Number.POSITIVE_INFINITY;
  let minContentRow = Number.POSITIVE_INFINITY;
  let maxContentCol = -1;
  let maxContentRow = -1;
  const columnWidthCharacterWidthPx = measureColumnCharacterWidthPx(
    options?.defaultFont?.family,
    options?.defaultFont?.sizePt
  );
  const defaultRowHeight = Number(sheetFormatNode?.getAttribute("defaultRowHeight") ?? 15);
  const digitWidthPt = measureOfficeDigitWidthPt(options?.defaultFont?.family, options?.defaultFont?.sizePt);
  const storedColumnPixels = (width) => resolveOfficeColumnWidthPixels(width, digitWidthPt);
  const explicitDefaultWidth = Number(sheetFormatNode?.getAttribute("defaultColWidth") ?? Number.NaN);
  const baseWidth = Number(sheetFormatNode?.getAttribute("baseColWidth") ?? 8);
  const officeLayout = {
    columnDigitWidthPt: digitWidthPt,
    defaultColumnPx: Number.isFinite(explicitDefaultWidth) && explicitDefaultWidth > 0 ? storedColumnPixels(explicitDefaultWidth) : ((Number.isFinite(baseWidth) && baseWidth > 0 ? baseWidth : 8) * digitWidthPt + 5) * (4 / 3),
    defaultRowPx: (Number.isFinite(defaultRowHeight) && defaultRowHeight > 0 ? defaultRowHeight : 15) * (4 / 3),
    columns: {},
    rows: {}
  };
  const defaultColWidth = Number(
    sheetFormatNode?.getAttribute("defaultColWidth") ?? sheetFormatNode?.getAttribute("baseColWidth") ?? 8.43
  );
  const rawZoomScale = Number(
    sheetViewNode?.getAttribute("zoomScale") ?? sheetViewNode?.getAttribute("zoomScaleNormal") ?? Number.NaN
  );
  const zoomScale = Number.isFinite(rawZoomScale) && rawZoomScale > 0 ? rawZoomScale : 100;
  const trackContentCell = (cellRef) => {
    if (!cellRef) {
      return;
    }
    const cell = parseA1CellReference(cellRef);
    if (!cell) {
      return;
    }
    minContentCol = Math.min(minContentCol, cell.col);
    minContentRow = Math.min(minContentRow, cell.row);
    maxContentCol = Math.max(maxContentCol, cell.col);
    maxContentRow = Math.max(maxContentRow, cell.row);
  };
  const isMeaningfulCellNode = (cellNode) => {
    if (getFirstChild(cellNode, "f") || getFirstChild(cellNode, "is")) {
      return true;
    }
    const valueNode = getFirstChild(cellNode, "v");
    return Boolean(valueNode && (valueNode.textContent ?? "").length > 0);
  };
  getLocalElements(document2, "row").forEach((rowNode) => {
    const rowIndex = Number(rowNode.getAttribute("r") ?? 0) - 1;
    const height = Number(rowNode.getAttribute("ht") ?? Number.NaN);
    const styleId = Number(rowNode.getAttribute("s") ?? Number.NaN);
    if (rowIndex >= 0 && Number.isFinite(height)) {
      rowHeightOverridesPx[rowIndex] = Math.max(MIN_ROW_HEIGHT_PX, Math.round(height * 1.33));
      officeLayout.rows[rowIndex] = { sourcePx: rowHeightOverridesPx[rowIndex], sizePx: Math.max(0, height * (4 / 3)) };
    }
    if (rowIndex >= 0 && Number.isFinite(styleId)) {
      rowStyleIds[rowIndex] = styleId;
    }
    getChildElements(rowNode, "c").forEach((cellNode) => {
      const cellRef = cellNode.getAttribute("r");
      const cellStyleId = Number(cellNode.getAttribute("s") ?? Number.NaN);
      if (cellRef && Number.isFinite(cellStyleId)) {
        cellStyleIds[cellRef] = cellStyleId;
      }
      if (isMeaningfulCellNode(cellNode)) {
        trackContentCell(cellRef);
      }
      if (includeCachedFormulaValues) {
        const formulaNode = getFirstChild(cellNode, "f");
        const valueNode = getFirstChild(cellNode, "v");
        if (formulaNode && valueNode && cellRef) {
          cachedFormulaValues[cellRef] = valueNode.textContent ?? "";
        }
      }
    });
  });
  const maxMetadataCol = Math.max(maxContentCol, 0) + 256;
  getLocalElements(document2, "col").forEach((colNode) => {
    const min = Number(colNode.getAttribute("min") ?? 0) - 1;
    const max = Number(colNode.getAttribute("max") ?? 0) - 1;
    const width = Number(colNode.getAttribute("width") ?? Number.NaN);
    const styleId = Number(colNode.getAttribute("style") ?? Number.NaN);
    if (!Number.isFinite(width)) {
      if (!Number.isFinite(styleId)) {
        return;
      }
    }
    for (let col = min; col <= Math.min(max, maxMetadataCol); col += 1) {
      if (col >= 0) {
        if (Number.isFinite(width)) {
          const widthPx = sheetColumnWidthToPixels(width, columnWidthCharacterWidthPx);
          colWidthOverridesPx[col] = widthPx;
          officeLayout.columns[col] = { sourcePx: widthPx, sizePx: storedColumnPixels(width) };
        }
        if (Number.isFinite(styleId)) {
          colStyleIds[col] = styleId;
        }
      }
    }
  });
  return {
    autoFilterRanges,
    cachedFormulaValues,
    cellStyleIds,
    columnWidthCharacterWidthPx,
    colWidthOverridesPx,
    colStyleIds,
    conditionalFormatRules,
    defaultColWidthPx: sheetColumnWidthToPixels(defaultColWidth, columnWidthCharacterWidthPx),
    officeLayout,
    defaultRowHeightPx: Math.max(MIN_ROW_HEIGHT_PX, Math.round(defaultRowHeight * 1.33)),
    hasHorizontalMerges: false,
    hasVerticalMerges: false,
    maxHorizontalMergeEndCol: -1,
    maxVerticalMergeEndRow: -1,
    maxContentCol,
    maxContentRow,
    minContentCol: Number.isFinite(minContentCol) ? minContentCol : -1,
    minContentRow: Number.isFinite(minContentRow) ? minContentRow : -1,
    hiddenCols: [],
    hiddenRows: [],
    rowHeightOverridesPx,
    rowStyleIds,
    showGridLines: (sheetViewNode?.getAttribute("showGridLines") ?? "1") !== "0",
    sparklines,
    zoomScale
  };
}
function clampChannel(value) {
  return Math.max(0, Math.min(255, Math.round(value)));
}
function normalizeHexColor2(value) {
  const hex = value.replace(/^#/, "");
  if (hex.length === 8) {
    return `#${hex.slice(2).toLowerCase()}`;
  }
  if (hex.length === 6) {
    return `#${hex.toLowerCase()}`;
  }
  return "#000000";
}
function hexToRgb(hex) {
  const normalized = normalizeHexColor2(hex);
  return {
    b: Number.parseInt(normalized.slice(5, 7), 16),
    g: Number.parseInt(normalized.slice(3, 5), 16),
    r: Number.parseInt(normalized.slice(1, 3), 16)
  };
}
function rgbToHex2(red, green, blue) {
  return `#${[red, green, blue].map((value) => clampChannel(value).toString(16).padStart(2, "0")).join("")}`;
}
function applyDrawingColorTransforms(baseColor, transformNodes) {
  let { r, g, b } = hexToRgb(baseColor);
  let opacity = 1;
  let lumMod = 1;
  let lumOff = 0;
  transformNodes.forEach((node) => {
    const rawValue = Number(node.getAttribute("val") ?? 0);
    const value = Number.isFinite(rawValue) ? rawValue / 1e5 : 0;
    switch (node.localName) {
      case "alpha":
        opacity *= value;
        break;
      case "lumMod":
        lumMod *= value;
        break;
      case "lumOff":
        lumOff += value;
        break;
      case "shade":
        r *= value;
        g *= value;
        b *= value;
        break;
      case "tint":
        r = r + (255 - r) * value;
        g = g + (255 - g) * value;
        b = b + (255 - b) * value;
        break;
      default:
        break;
    }
  });
  if (lumMod !== 1 || lumOff !== 0) {
    r = r * lumMod + 255 * lumOff;
    g = g * lumMod + 255 * lumOff;
    b = b * lumMod + 255 * lumOff;
  }
  return {
    color: rgbToHex2(r, g, b),
    opacity: Math.max(0, Math.min(1, opacity))
  };
}
function resolveThemeColorName(theme, name) {
  if (!name) {
    return null;
  }
  const aliases = {
    bg1: "bg1",
    bg2: "bg2",
    tx1: "tx1",
    tx2: "tx2"
  };
  const key = aliases[name] ?? name;
  return theme.colors.get(key) ?? null;
}
function resolveColorValue(colorNode, theme) {
  if (!colorNode) {
    return null;
  }
  let baseColor = null;
  if (colorNode.localName === "srgbClr") {
    baseColor = normalizeHexColor2(colorNode.getAttribute("val") ?? "");
  } else if (colorNode.localName === "schemeClr") {
    baseColor = resolveThemeColorName(theme, colorNode.getAttribute("val"));
  } else if (colorNode.localName === "scrgbClr") {
    const r = Number(colorNode.getAttribute("r") ?? 0) * 255 / 1e5;
    const g = Number(colorNode.getAttribute("g") ?? 0) * 255 / 1e5;
    const b = Number(colorNode.getAttribute("b") ?? 0) * 255 / 1e5;
    baseColor = rgbToHex2(r, g, b);
  } else if (colorNode.localName === "sysClr") {
    baseColor = normalizeHexColor2(colorNode.getAttribute("lastClr") ?? "");
  }
  if (!baseColor) {
    return null;
  }
  return applyDrawingColorTransforms(baseColor, Array.from(colorNode.childNodes).filter(isElementNode));
}
function resolveFillColor(fillParent, theme) {
  if (!fillParent) {
    return null;
  }
  const solidFillNode = getFirstChild(fillParent, "solidFill");
  if (!solidFillNode) {
    return null;
  }
  return resolveColorValue(Array.from(solidFillNode.childNodes).filter(isElementNode)[0] ?? null, theme);
}
function resolveTextTypeface(typeface, theme) {
  if (!typeface) {
    return void 0;
  }
  if (typeface === "+mn-lt" || typeface === "+mn-ea" || typeface === "+mn-cs") {
    return theme.minorLatinFont ?? void 0;
  }
  if (typeface === "+mj-lt" || typeface === "+mj-ea" || typeface === "+mj-cs") {
    return theme.majorLatinFont ?? void 0;
  }
  return typeface;
}
function isThemeTypeface(typeface) {
  return Boolean(typeface && typeface.startsWith("+"));
}
function resolvePreferredTextTypeface(node, theme) {
  if (!node) {
    return void 0;
  }
  const latin = getFirstChild(node, "latin")?.getAttribute("typeface") ?? null;
  const eastAsian = getFirstChild(node, "ea")?.getAttribute("typeface") ?? null;
  const complexScript = getFirstChild(node, "cs")?.getAttribute("typeface") ?? null;
  const candidates = [latin, eastAsian, complexScript];
  const explicit = candidates.find((candidate) => candidate && !isThemeTypeface(candidate));
  if (explicit) {
    return explicit;
  }
  return resolveTextTypeface(candidates.find(Boolean) ?? null, theme);
}
function parseShapeTextStyle(node, theme, fallbackColor) {
  if (!node) {
    return {
      color: fallbackColor?.color
    };
  }
  const fillColor = resolveFillColor(node, theme) ?? fallbackColor ?? null;
  const underlineValue = node.getAttribute("u");
  return {
    bold: node.getAttribute("b") === "1" || void 0,
    color: fillColor?.color,
    fontFamily: resolvePreferredTextTypeface(node, theme),
    fontSizePt: node.getAttribute("sz") ? Number(node.getAttribute("sz")) / 100 : void 0,
    italic: node.getAttribute("i") === "1" || void 0,
    underline: underlineValue && underlineValue !== "none" ? true : void 0
  };
}
function mergeShapeTextStyles(...styles) {
  return styles.reduce((acc, style) => {
    if (!style) {
      return acc;
    }
    return {
      bold: style.bold ?? acc.bold,
      color: style.color ?? acc.color,
      fontFamily: style.fontFamily ?? acc.fontFamily,
      fontSizePt: style.fontSizePt ?? acc.fontSizePt,
      italic: style.italic ?? acc.italic,
      underline: style.underline ?? acc.underline
    };
  }, {});
}
function parseMarker(node) {
  if (!node) {
    return null;
  }
  const col = Number(getFirstChild(node, "col")?.textContent ?? 0);
  const row = Number(getFirstChild(node, "row")?.textContent ?? 0);
  const colOffsetEmu = Number(getFirstChild(node, "colOff")?.textContent ?? 0);
  const rowOffsetEmu = Number(getFirstChild(node, "rowOff")?.textContent ?? 0);
  return {
    col,
    colOffsetEmu,
    row,
    rowOffsetEmu
  };
}
function dukeDrawingAnchorToXlsxAnchor(anchor) {
  if (anchor.type === "absolute") {
    return {
      kind: "absolute",
      positionEmu: { x: anchor.xEmu, y: anchor.yEmu },
      sizeEmu: { cx: anchor.widthEmu, cy: anchor.heightEmu }
    };
  }
  const from = {
    col: anchor.from.col,
    colOffsetEmu: anchor.from.colOffsetEmu ?? 0,
    row: anchor.from.row,
    rowOffsetEmu: anchor.from.rowOffsetEmu ?? 0
  };
  if (anchor.type === "oneCell") {
    return {
      from,
      kind: "one-cell",
      sizeEmu: { cx: anchor.widthEmu, cy: anchor.heightEmu }
    };
  }
  return {
    from,
    kind: "two-cell",
    to: {
      col: anchor.to.col,
      colOffsetEmu: anchor.to.colOffsetEmu ?? 0,
      row: anchor.to.row,
      rowOffsetEmu: anchor.to.rowOffsetEmu ?? 0
    }
  };
}
function xlsxAnchorToDukeDrawingAnchor(anchor, editAs) {
  if (anchor.kind === "absolute") {
    return {
      heightEmu: anchor.sizeEmu.cy,
      type: "absolute",
      widthEmu: anchor.sizeEmu.cx,
      xEmu: anchor.positionEmu.x,
      yEmu: anchor.positionEmu.y
    };
  }
  const from = {
    col: anchor.from.col,
    colOffsetEmu: anchor.from.colOffsetEmu,
    row: anchor.from.row,
    rowOffsetEmu: anchor.from.rowOffsetEmu
  };
  if (anchor.kind === "one-cell") {
    return {
      from,
      heightEmu: anchor.sizeEmu.cy,
      type: "oneCell",
      widthEmu: anchor.sizeEmu.cx
    };
  }
  return {
    editAs,
    from,
    to: {
      col: anchor.to.col,
      colOffsetEmu: anchor.to.colOffsetEmu,
      row: anchor.to.row,
      rowOffsetEmu: anchor.to.rowOffsetEmu
    },
    type: "twoCell"
  };
}
function mapDukeDrawingColor(color) {
  if (!color) {
    return void 0;
  }
  switch (color.colorType) {
    case "auto":
      return { colorType: "auto" };
    case "rgb":
      return { b: color.b, colorType: "rgb", g: color.g, r: color.r };
    case "argb":
      return { a: color.a, b: color.b, colorType: "argb", g: color.g, r: color.r };
    case "theme":
      return { colorType: "theme", themeIndex: color.index, tint: color.tint };
    case "indexed":
      return { colorType: "indexed", paletteIndex: color.index };
  }
}
function mapDukeDrawingFont(font) {
  if (!font) {
    return void 0;
  }
  return {
    bold: font.bold,
    charset: font.charset,
    color: mapDukeDrawingColor(font.color),
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
function mapDukeDrawingText(text) {
  return {
    horizontalAlignment: text.horizontalAlignment,
    runs: text.runs.map((run) => ({ font: mapDukeDrawingFont(run.font), text: run.text })),
    verticalAlignment: text.verticalAlignment
  };
}
function resolveDukeDrawingColor(color, themePalette) {
  if (!color) {
    return void 0;
  }
  switch (color.colorType) {
    case "rgb":
      return resolveWorkbookColor({ rgb: [color.r, color.g, color.b].map((value) => value.toString(16).padStart(2, "0")).join("") }) ?? void 0;
    case "argb":
      return resolveWorkbookColor({ argb: [color.a, color.r, color.g, color.b].map((value) => value.toString(16).padStart(2, "0")).join("") }) ?? void 0;
    case "theme":
      return resolveWorkbookColor({ theme: color.index, tint: color.tint }, themePalette) ?? void 0;
    default:
      return void 0;
  }
}
function resolveDukeDrawingText(text, themePalette) {
  const caption = mapDukeDrawingText(text);
  const label = normalizeControlLabel(text.runs.map((run) => run.text).join(""));
  const firstStyledRun = text.runs.find((run) => run.font)?.font;
  const horizontalAlignment = text.horizontalAlignment;
  return {
    caption,
    fontFamily: firstStyledRun?.name,
    fontSizePt: firstStyledRun?.size,
    label,
    textAlign: horizontalAlignment === "left" || horizontalAlignment === "center" || horizontalAlignment === "right" ? horizontalAlignment : void 0,
    textColor: resolveDukeDrawingColor(firstStyledRun?.color, themePalette)
  };
}
function mapDukeFormControlKind(kind, themePalette) {
  switch (kind.kind) {
    case "button":
      return { ...resolveDukeDrawingText(kind.caption, themePalette), kind: "button" };
    case "checkbox":
      return {
        ...resolveDukeDrawingText(kind.caption, themePalette),
        checked: kind.state === "checked",
        kind: "checkbox",
        linkedCell: kind.cellLink,
        no3D: kind.no3D,
        state: kind.state
      };
    case "optionButton":
      return {
        ...resolveDukeDrawingText(kind.caption, themePalette),
        checked: kind.state === "checked",
        firstInGroup: kind.firstInGroup,
        kind: "radio",
        linkedCell: kind.cellLink,
        no3D: kind.no3D,
        state: kind.state
      };
    case "label":
      return { ...resolveDukeDrawingText(kind.caption, themePalette), kind: "label" };
    case "groupBox":
      return {
        ...resolveDukeDrawingText(kind.caption, themePalette),
        kind: "group-box",
        no3D: kind.no3D
      };
    case "listBox":
      return {
        inputRange: kind.inputRange,
        kind: "listbox",
        linkedCell: kind.cellLink,
        no3D: kind.no3D,
        selected: [...kind.selected],
        selection: kind.selection
      };
    case "dropdown":
      return {
        inputRange: kind.inputRange,
        kind: "dropdown",
        lines: kind.lines,
        linkedCell: kind.cellLink,
        no3D: kind.no3D,
        selected: kind.selected
      };
    case "scrollbar":
      return {
        horizontal: kind.horizontal,
        increment: kind.increment,
        kind: "scrollbar",
        linkedCell: kind.cellLink,
        max: kind.max,
        min: kind.min,
        page: kind.page,
        value: kind.value
      };
    case "spinner":
      return {
        increment: kind.increment,
        kind: "spinner",
        linkedCell: kind.cellLink,
        max: kind.max,
        min: kind.min,
        value: kind.value
      };
    case "unknown":
      return {
        ...resolveDukeDrawingText(kind.caption, themePalette),
        kind: kind.objectType.toLowerCase() === "editbox" ? "editbox" : "unknown",
        legacyObjectType: kind.legacyObjectType,
        objectType: kind.objectType
      };
  }
}
function mapDukeFormControl(control, controlIndex, workbookSheetIndex, themePalette) {
  return {
    altText: control.altText,
    anchor: dukeDrawingAnchorToXlsxAnchor(control.anchor),
    controlIndex,
    editAs: control.anchor.type === "twoCell" ? control.anchor.editAs : void 0,
    hidden: control.hidden,
    id: `form-control-${workbookSheetIndex}-${controlIndex}`,
    locked: control.locked,
    macroName: control.formControl.macroName,
    name: control.name,
    printable: control.printable,
    rawClientData: control.formControl.rawClientData,
    rawObj: control.formControl.rawObj,
    rawProperties: control.formControl.rawProperties,
    sheetIndex: workbookSheetIndex,
    title: control.title,
    workbookSheetIndex,
    zIndex: (control.drawingPath[0] ?? controlIndex) + 1,
    ...mapDukeFormControlKind(control.formControl.kind, themePalette)
  };
}
function collectWorkbookFormControls(workbook, themePalette) {
  return Array.from({ length: workbook.sheetCount }, (_, workbookSheetIndex) => {
    try {
      const controls = workbook.getSheet(workbookSheetIndex).formControls;
      return Array.isArray(controls) ? controls.flatMap((control, controlIndex) => control.anchor ? [mapDukeFormControl(control, controlIndex, workbookSheetIndex, themePalette)] : []) : [];
    } catch {
      return [];
    }
  });
}
function normalizeControlLabel(label) {
  if (!label) {
    return void 0;
  }
  const normalized = label.replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();
  return normalized.length > 0 ? normalized : void 0;
}
function parseAnchor(anchorNode) {
  if (anchorNode.localName === "anchor") {
    const from = parseMarker(getFirstChild(anchorNode, "from"));
    const to = parseMarker(getFirstChild(anchorNode, "to"));
    return from && to ? { from, kind: "two-cell", to } : null;
  }
  if (anchorNode.localName === "twoCellAnchor") {
    const from = parseMarker(getFirstChild(anchorNode, "from"));
    const to = parseMarker(getFirstChild(anchorNode, "to"));
    return from && to ? { from, kind: "two-cell", to } : null;
  }
  if (anchorNode.localName === "oneCellAnchor") {
    const from = parseMarker(getFirstChild(anchorNode, "from"));
    const extNode2 = getFirstChild(anchorNode, "ext");
    return from && extNode2 ? {
      from,
      kind: "one-cell",
      sizeEmu: {
        cx: Number(extNode2.getAttribute("cx") ?? 0),
        cy: Number(extNode2.getAttribute("cy") ?? 0)
      }
    } : null;
  }
  const positionNode = getFirstChild(anchorNode, "pos");
  const extNode = getFirstChild(anchorNode, "ext");
  return positionNode && extNode ? {
    kind: "absolute",
    positionEmu: {
      x: Number(positionNode.getAttribute("x") ?? 0),
      y: Number(positionNode.getAttribute("y") ?? 0)
    },
    sizeEmu: {
      cx: Number(extNode.getAttribute("cx") ?? 0),
      cy: Number(extNode.getAttribute("cy") ?? 0)
    }
  } : null;
}
function anchorToRect(anchor) {
  if (anchor.kind === "absolute") {
    return {
      cx: anchor.sizeEmu.cx,
      cy: anchor.sizeEmu.cy,
      x: anchor.positionEmu.x,
      y: anchor.positionEmu.y
    };
  }
  if (anchor.kind === "one-cell") {
    return {
      cx: anchor.sizeEmu.cx,
      cy: anchor.sizeEmu.cy,
      x: anchor.from.colOffsetEmu,
      y: anchor.from.rowOffsetEmu
    };
  }
  return {
    cx: Math.max(0, (anchor.to.col - anchor.from.col) * DEFAULT_COL_WIDTH_EMU + anchor.to.colOffsetEmu - anchor.from.colOffsetEmu),
    cy: Math.max(0, (anchor.to.row - anchor.from.row) * DEFAULT_ROW_HEIGHT_EMU + anchor.to.rowOffsetEmu - anchor.from.rowOffsetEmu),
    x: anchor.from.colOffsetEmu,
    y: anchor.from.rowOffsetEmu
  };
}
function resolveSheetColumnWidthPx(sheetState, col) {
  if (col < 0) {
    return 0;
  }
  return sheetState?.colWidthOverridesPx[col] ?? sheetState?.defaultColWidthPx ?? emuToPixels(DEFAULT_COL_WIDTH_EMU);
}
function resolveSheetRowHeightPx(sheetState, row) {
  if (row < 0) {
    return 0;
  }
  return sheetState?.rowHeightOverridesPx[row] ?? sheetState?.defaultRowHeightPx ?? emuToPixels(DEFAULT_ROW_HEIGHT_EMU);
}
function sumSheetColumnWidthsEmu(sheetState, beforeCol) {
  let total = 0;
  for (let col = 0; col < beforeCol; col += 1) {
    total += pixelsToEmu(resolveSheetColumnWidthPx(sheetState, col));
  }
  return total;
}
function sumSheetRowHeightsEmu(sheetState, beforeRow) {
  let total = 0;
  for (let row = 0; row < beforeRow; row += 1) {
    total += pixelsToEmu(resolveSheetRowHeightPx(sheetState, row));
  }
  return total;
}
function anchorToAbsoluteRect(anchor, sheetState) {
  if (anchor.kind === "absolute") {
    return anchorToRect(anchor);
  }
  if (anchor.kind === "one-cell") {
    return {
      cx: anchor.sizeEmu.cx,
      cy: anchor.sizeEmu.cy,
      x: sumSheetColumnWidthsEmu(sheetState, anchor.from.col) + anchor.from.colOffsetEmu,
      y: sumSheetRowHeightsEmu(sheetState, anchor.from.row) + anchor.from.rowOffsetEmu
    };
  }
  const left = sumSheetColumnWidthsEmu(sheetState, anchor.from.col) + anchor.from.colOffsetEmu;
  const top = sumSheetRowHeightsEmu(sheetState, anchor.from.row) + anchor.from.rowOffsetEmu;
  const right = sumSheetColumnWidthsEmu(sheetState, anchor.to.col) + anchor.to.colOffsetEmu;
  const bottom = sumSheetRowHeightsEmu(sheetState, anchor.to.row) + anchor.to.rowOffsetEmu;
  return {
    cx: Math.max(0, right - left),
    cy: Math.max(0, bottom - top),
    x: left,
    y: top
  };
}
function rectToAbsoluteAnchor(rect) {
  return {
    kind: "absolute",
    positionEmu: {
      x: rect.x,
      y: rect.y
    },
    sizeEmu: {
      cx: rect.cx,
      cy: rect.cy
    }
  };
}
function parseTransformRect(xfrmNode) {
  if (!xfrmNode) {
    return null;
  }
  const offNode = getFirstChild(xfrmNode, "off");
  const extNode = getFirstChild(xfrmNode, "ext");
  if (!offNode || !extNode) {
    return null;
  }
  return {
    cx: Number(extNode.getAttribute("cx") ?? 0),
    cy: Number(extNode.getAttribute("cy") ?? 0),
    flipH: xfrmNode.getAttribute("flipH") === "1",
    flipV: xfrmNode.getAttribute("flipV") === "1",
    rot: Number(xfrmNode.getAttribute("rot") ?? 0) / 6e4,
    x: Number(offNode.getAttribute("x") ?? 0),
    y: Number(offNode.getAttribute("y") ?? 0)
  };
}
function applyGroupTransform(rect, group) {
  return {
    cx: rect.cx * group.scaleX,
    cy: rect.cy * group.scaleY,
    x: group.x + (rect.x - group.chX) * group.scaleX,
    y: group.y + (rect.y - group.chY) * group.scaleY
  };
}
function parseGroupTransform(groupNode, parentGroup, fallbackAnchor, sheetState) {
  const xfrmNode = getFirstDescendant(getFirstChild(groupNode, "grpSpPr") ?? groupNode, "xfrm");
  const anchorRect = anchorToAbsoluteRect(fallbackAnchor, sheetState);
  const rect = parseTransformRect(xfrmNode) ?? anchorRect;
  const rootRectMatchesAnchorOrigin = Math.abs(rect.x - anchorRect.x) <= EMU_PER_PIXEL && Math.abs(rect.y - anchorRect.y) <= EMU_PER_PIXEL;
  const chOffNode = getFirstChild(xfrmNode ?? groupNode, "chOff");
  const chExtNode = getFirstChild(xfrmNode ?? groupNode, "chExt");
  const rootScaleX = rect.cx !== 0 ? anchorRect.cx / rect.cx : 1;
  const rootScaleY = rect.cy !== 0 ? anchorRect.cy / rect.cy : 1;
  const useRectFrameForRoot = !parentGroup && (rootScaleX < 0.85 || rootScaleX > 1.15 || rootScaleY < 0.85 || rootScaleY > 1.15);
  const absoluteRect = parentGroup ? applyGroupTransform(rect, parentGroup) : rootRectMatchesAnchorOrigin ? rect : anchorRect;
  const childRectX = parentGroup ? Number(chOffNode?.getAttribute("x") ?? 0) : useRectFrameForRoot ? rect.x : Number(chOffNode?.getAttribute("x") ?? 0);
  const childRectY = parentGroup ? Number(chOffNode?.getAttribute("y") ?? 0) : useRectFrameForRoot ? rect.y : Number(chOffNode?.getAttribute("y") ?? 0);
  const childRectCx = parentGroup ? Number(chExtNode?.getAttribute("cx") ?? rect.cx) : useRectFrameForRoot ? rect.cx : Number(chExtNode?.getAttribute("cx") ?? rect.cx);
  const childRectCy = parentGroup ? Number(chExtNode?.getAttribute("cy") ?? rect.cy) : useRectFrameForRoot ? rect.cy : Number(chExtNode?.getAttribute("cy") ?? rect.cy);
  return {
    chCx: childRectCx,
    chCy: childRectCy,
    chX: childRectX,
    chY: childRectY,
    cx: absoluteRect.cx,
    cy: absoluteRect.cy,
    scaleX: childRectCx !== 0 ? absoluteRect.cx / childRectCx : parentGroup?.scaleX ?? 1,
    scaleY: childRectCy !== 0 ? absoluteRect.cy / childRectCy : parentGroup?.scaleY ?? 1,
    x: absoluteRect.x,
    y: absoluteRect.y
  };
}
function anchorFromNodeOrFallback(node, fallbackAnchor, parentGroup) {
  const xfrmNode = getFirstDescendant(node, "xfrm");
  const rect = parseTransformRect(xfrmNode);
  if (rect) {
    const scaleX = parentGroup?.scaleX ?? 1;
    const scaleY = parentGroup?.scaleY ?? 1;
    return {
      anchor: parentGroup ? rectToAbsoluteAnchor(applyGroupTransform(rect, parentGroup)) : fallbackAnchor,
      flipH: rect.flipH,
      flipV: rect.flipV,
      rotationDeg: rect.rot,
      scaleX,
      scaleY
    };
  }
  return {
    anchor: fallbackAnchor,
    flipH: false,
    flipV: false,
    rotationDeg: 0,
    scaleX: parentGroup?.scaleX ?? 1,
    scaleY: parentGroup?.scaleY ?? 1
  };
}
function mapParagraphAlign(value) {
  switch (value) {
    case "ctr":
      return "center";
    case "just":
      return "justify";
    case "r":
      return "right";
    case "l":
      return "left";
    default:
      return void 0;
  }
}
function mapVerticalAnchor(value) {
  switch (value) {
    case "b":
      return "bottom";
    case "ctr":
      return "middle";
    default:
      return "top";
  }
}
function createImageAnchorNodes(document2) {
  return document2.documentElement ? Array.from(document2.documentElement.childNodes).filter(
    (node) => isElementNode(node) && (node.localName === "twoCellAnchor" || node.localName === "oneCellAnchor" || node.localName === "absoluteAnchor")
  ) : [];
}
function createImageSource(bytes, mimeType, objectUrls) {
  if (typeof URL !== "undefined" && typeof Blob !== "undefined") {
    const objectUrl = createWorkbookObjectUrl(new Blob([cloneBytes(bytes)], { type: mimeType }));
    objectUrls.push(objectUrl);
    return objectUrl;
  }
  let binary = "";
  for (const value of bytes) {
    binary += String.fromCharCode(value);
  }
  const base64 = typeof btoa === "function" ? btoa(binary) : "";
  return `data:${mimeType};base64,${base64}`;
}
function isStrokeOnlyGeometry(geometry) {
  return geometry === "line" || geometry === "arc" || geometry === "leftBrace";
}
function parseShapeStroke(node, styleNode, theme) {
  const lineNode = getFirstDescendant(node, "ln");
  const lineRefNode = styleNode ? getFirstChild(styleNode, "lnRef") : null;
  if (!lineNode && !lineRefNode) {
    return void 0;
  }
  if (lineNode && getFirstChild(lineNode, "noFill")) {
    return { none: true };
  }
  const color = resolveFillColor(lineNode, theme) ?? resolveColorValue(Array.from(lineRefNode?.childNodes ?? []).filter(isElementNode)[0] ?? null, theme);
  const widthEmu = Number(lineNode?.getAttribute("w") ?? 0);
  return {
    color: color?.color,
    dash: getFirstChild(lineNode ?? node, "prstDash")?.getAttribute("val") ?? void 0,
    headEndType: getFirstChild(lineNode ?? node, "headEnd")?.getAttribute("type") ?? void 0,
    none: false,
    opacity: color?.opacity,
    tailEndType: getFirstChild(lineNode ?? node, "tailEnd")?.getAttribute("type") ?? void 0,
    widthPx: widthEmu > 0 ? emuToPixels(widthEmu) : void 0
  };
}
function parseShapeFill(node, styleNode, theme, geometry) {
  const shapePropsNode = getFirstChild(node, "spPr") ?? node;
  const noFillNode = getFirstChild(shapePropsNode, "noFill");
  if (noFillNode) {
    return { none: true };
  }
  if (isStrokeOnlyGeometry(geometry)) {
    return { none: true };
  }
  const fillRefNode = styleNode ? getFirstChild(styleNode, "fillRef") : null;
  const fillColor = resolveFillColor(shapePropsNode, theme) ?? resolveColorValue(Array.from(fillRefNode?.childNodes ?? []).filter(isElementNode)[0] ?? null, theme);
  if (!fillColor) {
    return void 0;
  }
  return {
    color: fillColor.color,
    none: false,
    opacity: fillColor.opacity
  };
}
function parsePointNode(pointNode) {
  if (!pointNode) {
    return null;
  }
  const x = Number(pointNode.getAttribute("x") ?? Number.NaN);
  const y = Number(pointNode.getAttribute("y") ?? Number.NaN);
  return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
}
function parseCustomGeometryPath(shapeNode) {
  const pathNode = getFirstDescendant(shapeNode, "path");
  if (!pathNode) {
    return void 0;
  }
  const width = Number(pathNode.getAttribute("w") ?? Number.NaN);
  const height = Number(pathNode.getAttribute("h") ?? Number.NaN);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return void 0;
  }
  const commands = [];
  let lastPoint = null;
  for (const child of Array.from(pathNode.childNodes).filter(isElementNode)) {
    if (child.localName === "moveTo") {
      const point = parsePointNode(getFirstChild(child, "pt"));
      if (point) {
        commands.push(`M ${point.x} ${point.y}`);
        lastPoint = point;
      }
      continue;
    }
    if (child.localName === "lnTo") {
      const point = parsePointNode(getFirstChild(child, "pt"));
      if (point && (!lastPoint || point.x !== lastPoint.x || point.y !== lastPoint.y)) {
        commands.push(`L ${point.x} ${point.y}`);
        lastPoint = point;
      }
      continue;
    }
    if (child.localName === "cubicBezTo") {
      const points = getChildElements(child, "pt").map(parsePointNode).filter((point) => point !== null);
      if (points.length === 3) {
        commands.push(`C ${points[0].x} ${points[0].y} ${points[1].x} ${points[1].y} ${points[2].x} ${points[2].y}`);
        lastPoint = points[2];
      }
      continue;
    }
    if (child.localName === "close") {
      commands.push("Z");
      lastPoint = null;
    }
  }
  if (commands.length === 0) {
    return void 0;
  }
  return {
    path: commands.join(" "),
    viewBox: {
      height,
      width
    }
  };
}
function parseShapeGeometryAdjustments(shapeNode) {
  const presetGeometry = getFirstDescendant(shapeNode, "prstGeom");
  if (!presetGeometry) {
    return void 0;
  }
  const adjustments = {};
  getChildElements(getFirstChild(presetGeometry, "avLst"), "gd").forEach((adjustmentNode) => {
    const name = adjustmentNode.getAttribute("name");
    const formula = adjustmentNode.getAttribute("fmla") ?? "";
    const match = formula.match(/^val\s+(-?\d+(?:\.\d+)?)$/);
    if (!name || !match) {
      return;
    }
    const value = Number.parseFloat(match[1] ?? "");
    if (Number.isFinite(value)) {
      adjustments[name] = value;
    }
  });
  return Object.keys(adjustments).length > 0 ? adjustments : void 0;
}
function parseShapeParagraphs(shapeNode, styleNode, theme) {
  const txBodyNode = getFirstChild(shapeNode, "txBody");
  if (!txBodyNode) {
    return [];
  }
  const defaultFontRef = styleNode ? getFirstChild(styleNode, "fontRef") : null;
  const defaultFontColor = resolveColorValue(Array.from(defaultFontRef?.childNodes ?? []).filter(isElementNode)[0] ?? null, theme);
  const listStyleNode = getFirstChild(txBodyNode, "lstStyle");
  const paragraphs = [];
  getChildElements(txBodyNode, "p").forEach((paragraphNode) => {
    const paragraphProps = getFirstChild(paragraphNode, "pPr");
    const paragraphLevel = Number(paragraphProps?.getAttribute("lvl") ?? 0);
    const listLevelProps = getFirstChild(listStyleNode ?? txBodyNode, `lvl${paragraphLevel + 1}pPr`);
    const inheritedStyle = mergeShapeTextStyles(
      parseShapeTextStyle(getFirstChild(listLevelProps ?? txBodyNode, "defRPr"), theme, defaultFontColor),
      parseShapeTextStyle(getFirstChild(paragraphProps ?? paragraphNode, "defRPr"), theme, defaultFontColor)
    );
    const runs = [];
    let sawRenderableChild = false;
    Array.from(paragraphNode.childNodes).filter(isElementNode).forEach((child) => {
      if (child.localName === "br") {
        sawRenderableChild = true;
        runs.push({ text: "\n" });
        return;
      }
      if (child.localName !== "r") {
        return;
      }
      sawRenderableChild = true;
      const text = getFirstChild(child, "t")?.textContent ?? "";
      const runProps = getFirstChild(child, "rPr");
      const runStyle = mergeShapeTextStyles(
        inheritedStyle,
        parseShapeTextStyle(runProps, theme, defaultFontColor)
      );
      runs.push({
        bold: runStyle.bold,
        color: runStyle.color,
        fontFamily: runStyle.fontFamily,
        fontSizePt: runStyle.fontSizePt,
        italic: runStyle.italic,
        text,
        underline: runStyle.underline
      });
    });
    if (runs.length === 0) {
      if (!sawRenderableChild && !getFirstChild(paragraphNode, "endParaRPr")) {
        return;
      }
      runs.push({
        bold: inheritedStyle.bold,
        color: inheritedStyle.color,
        fontFamily: inheritedStyle.fontFamily,
        fontSizePt: inheritedStyle.fontSizePt,
        italic: inheritedStyle.italic,
        text: " ",
        underline: inheritedStyle.underline
      });
    }
    paragraphs.push({
      align: mapParagraphAlign(paragraphProps?.getAttribute("algn")),
      runs
    });
  });
  return paragraphs;
}
function parseTextBox(shapeNode) {
  const txBodyNode = getFirstChild(shapeNode, "txBody");
  if (!txBodyNode) {
    return void 0;
  }
  const bodyProps = getFirstChild(txBodyNode, "bodyPr");
  const leftInset = emuToPixels(Number(bodyProps?.getAttribute("lIns") ?? 91440));
  const rightInset = emuToPixels(Number(bodyProps?.getAttribute("rIns") ?? 91440));
  const topInset = emuToPixels(Number(bodyProps?.getAttribute("tIns") ?? 45720));
  const bottomInset = emuToPixels(Number(bodyProps?.getAttribute("bIns") ?? 45720));
  return {
    horizontalAlign: bodyProps?.getAttribute("anchorCtr") === "1" ? "center" : "left",
    insetPx: {
      bottom: bottomInset,
      left: leftInset,
      right: rightInset,
      top: topInset
    },
    verticalAlign: mapVerticalAnchor(bodyProps?.getAttribute("anchor"))
  };
}
function getHyperlinkTarget(node, drawingRelationships) {
  const hyperlinkNode = node ? getFirstDescendant(node, "hlinkClick") : null;
  const hyperlinkTargetNode = hyperlinkNode ?? node;
  const hyperlinkId = hyperlinkTargetNode ? getRelationshipId(hyperlinkTargetNode) : null;
  return hyperlinkId ? drawingRelationships.get(hyperlinkId)?.target ?? void 0 : void 0;
}
function parsePictureNode(pictureNode, fallbackAnchor, drawingRelationships, archive, contentTypes, objectUrls, workbookSheetIndex, imageId, zIndex, parentGroup, sheetState) {
  const blipNode = getFirstDescendant(pictureNode, "blip");
  const svgBlipNode = blipNode ? getFirstDescendant(blipNode, "svgBlip") : null;
  const embedId = (svgBlipNode ? getEmbeddedRelationshipId(svgBlipNode) : null) ?? (blipNode ? getEmbeddedRelationshipId(blipNode) : null);
  if (!embedId) {
    return null;
  }
  const mediaRelationship = drawingRelationships.get(embedId);
  if (!mediaRelationship || mediaRelationship.type !== IMAGE_REL_TYPE) {
    return null;
  }
  const mediaBytes = archive[mediaRelationship.target];
  if (!mediaBytes) {
    return null;
  }
  const nonVisualProps = getFirstDescendant(pictureNode, "cNvPr");
  const transform = anchorFromNodeOrFallback(pictureNode, fallbackAnchor, parentGroup);
  const image = {
    anchor: transform.anchor,
    description: nonVisualProps?.getAttribute("descr") ?? void 0,
    hyperlink: getHyperlinkTarget(nonVisualProps ?? pictureNode, drawingRelationships),
    id: imageId,
    mediaPath: mediaRelationship.target,
    mimeType: resolveContentType(contentTypes, mediaRelationship.target),
    name: nonVisualProps?.getAttribute("name") ?? void 0,
    sheetIndex: workbookSheetIndex,
    src: createImageSource(mediaBytes, resolveContentType(contentTypes, mediaRelationship.target), objectUrls),
    workbookSheetIndex,
    zIndex
  };
  const rect = anchorToAbsoluteRect(transform.anchor, sheetState);
  const localRect = parseTransformRect(getFirstDescendant(pictureNode, "xfrm"));
  const layoutWidth = emuToPixels(parentGroup && localRect ? localRect.cx : rect.cx);
  const layoutHeight = emuToPixels(parentGroup && localRect ? localRect.cy : rect.cy);
  const rotation = (transform.rotationDeg % 180 + 180) % 180;
  const swapAxes = !parentGroup && rotation >= 45 && rotation < 135;
  pictureSources.set(image, {
    node: pictureNode,
    width: swapAxes ? layoutHeight : layoutWidth,
    height: swapAxes ? layoutWidth : layoutHeight,
    layoutWidth,
    layoutHeight
  });
  return {
    image,
    mediaPath: mediaRelationship.target
  };
}
function parseShapeNode(shapeNode, fallbackAnchor, drawingRelationships, theme, workbookSheetIndex, shapeId, zIndex, parentGroup) {
  const nonVisualProps = getFirstDescendant(shapeNode, "cNvPr");
  const styleNode = getFirstChild(shapeNode, "style");
  const transform = anchorFromNodeOrFallback(shapeNode, fallbackAnchor, parentGroup);
  const geometry = getFirstDescendant(shapeNode, "prstGeom")?.getAttribute("prst") ?? (getFirstDescendant(shapeNode, "custGeom") ? "custom" : "rect");
  const customPath = geometry === "custom" ? parseCustomGeometryPath(shapeNode) : void 0;
  const geometryAdjustments = parseShapeGeometryAdjustments(shapeNode);
  return {
    anchor: transform.anchor,
    description: nonVisualProps?.getAttribute("descr") ?? void 0,
    fill: parseShapeFill(shapeNode, styleNode, theme, geometry),
    flipH: transform.flipH,
    flipV: transform.flipV,
    geometry,
    geometryAdjustments,
    hidden: nonVisualProps?.getAttribute("hidden") === "1" || void 0,
    hyperlink: getHyperlinkTarget(nonVisualProps ?? shapeNode, drawingRelationships),
    id: shapeId,
    name: nonVisualProps?.getAttribute("name") ?? void 0,
    paragraphs: parseShapeParagraphs(shapeNode, styleNode, theme),
    rotationDeg: transform.rotationDeg,
    scaleX: transform.scaleX,
    scaleY: transform.scaleY,
    sheetIndex: workbookSheetIndex,
    svgPath: customPath?.path,
    svgViewBox: customPath?.viewBox,
    stroke: parseShapeStroke(shapeNode, styleNode, theme),
    textBox: parseTextBox(shapeNode),
    workbookSheetIndex,
    zIndex
  };
}
function parseAnchorContents(anchorNode, fallbackAnchor, drawingRelationships, archive, contentTypes, objectUrls, workbookSheetIndex, theme, ids, imageOriginsById, anchorIndex, sheetState, drawingPath, parentGroup = null, picturePath = []) {
  const images = [];
  const shapes = [];
  const mediaPaths = /* @__PURE__ */ new Set();
  Array.from(anchorNode.childNodes).filter(isElementNode).forEach((child, childIndex) => {
    if (child.localName === "pic") {
      const imageId = `sheet-${workbookSheetIndex}-${ids.image}`;
      const parsed = parsePictureNode(
        child,
        fallbackAnchor,
        drawingRelationships,
        archive,
        contentTypes,
        objectUrls,
        workbookSheetIndex,
        imageId,
        ids.z++,
        parentGroup,
        sheetState
      );
      ids.image += 1;
      if (parsed) {
        images.push(parsed.image);
        mediaPaths.add(parsed.mediaPath);
        imageOriginsById.set(imageId, {
          anchorIndex,
          drawingPath,
          picturePath: [...picturePath, childIndex],
          workbookSheetIndex
        });
      }
      return;
    }
    if (child.localName === "sp") {
      shapes.push(parseShapeNode(
        child,
        fallbackAnchor,
        drawingRelationships,
        theme,
        workbookSheetIndex,
        `shape-${workbookSheetIndex}-${ids.shape++}`,
        ids.z++,
        parentGroup
      ));
      return;
    }
    if (child.localName === "cxnSp") {
      shapes.push(parseShapeNode(
        child,
        fallbackAnchor,
        drawingRelationships,
        theme,
        workbookSheetIndex,
        `shape-${workbookSheetIndex}-${ids.shape++}`,
        ids.z++,
        parentGroup
      ));
      return;
    }
    if (child.localName !== "grpSp") {
      return;
    }
    const nextGroup = parseGroupTransform(
      child,
      parentGroup,
      fallbackAnchor,
      sheetState
    );
    const groupFallbackAnchor = rectToAbsoluteAnchor({
      cx: nextGroup.cx,
      cy: nextGroup.cy,
      x: nextGroup.x,
      y: nextGroup.y
    });
    const parsedGroup = parseAnchorContents(
      child,
      groupFallbackAnchor,
      drawingRelationships,
      archive,
      contentTypes,
      objectUrls,
      workbookSheetIndex,
      theme,
      ids,
      imageOriginsById,
      anchorIndex,
      sheetState,
      drawingPath,
      nextGroup,
      [...picturePath, childIndex]
    );
    parsedGroup.images.forEach((image) => images.push(image));
    parsedGroup.shapes.forEach((shape) => shapes.push(shape));
    parsedGroup.mediaPaths.forEach((path) => mediaPaths.add(path));
  });
  return {
    images,
    mediaPaths,
    shapes
  };
}
function parseDrawingObjects(archive, contentTypes, drawingPath, objectUrls, workbookSheetIndex, zIndexBase, theme, sheetState, imageOriginsById) {
  const drawingXml = readArchiveText(archive, drawingPath);
  if (!drawingXml) {
    return {
      images: [],
      mediaPaths: [],
      shapes: []
    };
  }
  const drawingDocument = parseXml(drawingXml);
  if (!drawingDocument) {
    return {
      images: [],
      mediaPaths: [],
      shapes: []
    };
  }
  const drawingRelationships = parseRelationships(archive, relsPathForDocument(drawingPath), drawingPath);
  const images = [];
  const shapes = [];
  const mediaPaths = /* @__PURE__ */ new Set();
  const anchorNodes = createImageAnchorNodes(drawingDocument);
  const ids = {
    image: zIndexBase,
    shape: zIndexBase,
    z: zIndexBase
  };
  anchorNodes.forEach((anchorNode, anchorIndex) => {
    const anchor = parseAnchor(anchorNode);
    if (!anchor) {
      return;
    }
    const parsed = parseAnchorContents(
      anchorNode,
      anchor,
      drawingRelationships,
      archive,
      contentTypes,
      objectUrls,
      workbookSheetIndex,
      theme,
      ids,
      imageOriginsById,
      anchorIndex,
      sheetState,
      drawingPath
    );
    const ordered = [...parsed.images, ...parsed.shapes].sort((a, b) => a.zIndex - b.zIndex);
    const layer = (item) => zIndexBase + anchorIndex + ordered.indexOf(item) / (ordered.length + 1);
    parsed.images.forEach((image) => images.push({ ...image, zIndex: layer(image) }));
    parsed.shapes.forEach((shape) => shapes.push({ ...shape, zIndex: layer(shape) }));
    parsed.mediaPaths.forEach((path) => mediaPaths.add(path));
  });
  return {
    images,
    mediaPaths: [...mediaPaths],
    shapes
  };
}
function refreshWorkbookFormControls(workbook, _currentControlsByWorkbookSheetIndex, themePalette) {
  return collectWorkbookFormControls(workbook, themePalette);
}
function revokeWorkbookImageAssets(assets) {
  if (!assets) {
    return;
  }
  for (const objectUrl of assets.objectUrls) {
    if (objectUrl.startsWith("blob:")) {
      revokeWorkbookObjectUrl(objectUrl);
    }
  }
}
function parseWorkbookStructureAssetsFromArchive(archive, options) {
  const contentTypes = parseContentTypes(archive);
  const workbookSheets = parseWorkbookSheets(archive);
  const theme = parseWorkbookTheme(archive);
  const themePalette = buildThemePalette(theme);
  const { defaultFont, differentialStyles, namedCellStyleByName, styleById, tableStyleByName } = parseWorkbookStyles(archive);
  return {
    contentTypes,
    namedCellStyleByName,
    sheetStatesByWorkbookSheetIndex: workbookSheets.map((sheet) => parseSheetState(archive, sheet.path, {
      ...options,
      differentialStyles,
      defaultFont,
      themePalette
    })),
    styleById,
    tableMetadataByWorkbookSheetIndex: workbookSheets.map(() => []),
    tableStyleByName,
    theme,
    themePalette,
    workbookSheets
  };
}
function serializePicture(node) {
  const drawingNamespace = "http://schemas.openxmlformats.org/drawingml/2006/main";
  const pictureNamespace = "http://schemas.openxmlformats.org/drawingml/2006/picture";
  const spreadsheetDrawingNamespace = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing";
  const extensionNamespace = "http://schemas.microsoft.com/office/drawing/2010/main";
  const document2 = node.ownerDocument.implementation.createDocument(pictureNamespace, "pic:pic", null);
  const copy = (source) => {
    const namespace = source.namespaceURI === spreadsheetDrawingNamespace ? pictureNamespace : source.namespaceURI;
    const prefix = namespace === drawingNamespace ? "a" : namespace === pictureNamespace ? "pic" : namespace === extensionNamespace ? "a14" : source.prefix;
    const target = document2.createElementNS(namespace, prefix ? `${prefix}:${source.localName}` : source.localName);
    for (const attribute of Array.from(source.attributes)) {
      if (attribute.namespaceURI === "http://www.w3.org/2000/xmlns/") continue;
      target.setAttributeNS(attribute.namespaceURI, attribute.name, attribute.value);
    }
    for (const child of Array.from(source.childNodes)) {
      target.appendChild(isElementNode(child) ? copy(child) : document2.importNode(child, true));
    }
    return target;
  };
  return serializeWorkbookXml(copy(node));
}
function hasPictureDecoration(node) {
  const transform = getFirstDescendant(node, "xfrm");
  if (Number(transform?.getAttribute("rot") ?? 0) !== 0 || ["flipH", "flipV"].some((name) => ["1", "true", "on"].includes(transform?.getAttribute(name) ?? ""))) return true;
  if ((getFirstDescendant(node, "prstGeom")?.getAttribute("prst") ?? "rect") !== "rect") return true;
  if (["srcRect", "fillRect"].some((name) => {
    const rectangle = getFirstDescendant(node, name);
    return rectangle && Array.from(rectangle.attributes).some((attribute) => Number.parseFloat(attribute.value) !== 0);
  })) return true;
  if (["ln", "custGeom", "tile", "effectDag", "scene3d", "sp3d"].some((name) => getFirstDescendant(node, name))) return true;
  return ["blip", "effectLst"].some((name) => Array.from(getFirstDescendant(node, name)?.children ?? []).some((child) => child.localName !== "extLst"));
}
async function renderWorkbookPictures(assets, theme) {
  const images = assets.imagesByWorkbookSheetIndex.flat();
  if (images.length === 0) return;
  const { loadOfficeArt } = await import("./loader-3T5AYYZT.js");
  const renderer = await loadOfficeArt();
  const sources = /* @__PURE__ */ new Map();
  const resolveColor = (xml) => {
    const document2 = parseXml(`<root xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">${xml}</root>`);
    const color = document2 && Array.from(document2.getElementsByTagName("*")).find((element) => ["srgbClr", "schemeClr", "scrgbClr", "sysClr"].includes(element.localName));
    return JSON.stringify(resolveColorValue(color || null, theme));
  };
  for (const image of images) {
    const picture = pictureSources.get(image);
    if (!picture || !image.mediaPath) continue;
    let source = sources.get(image.mediaPath);
    if (!source) {
      const bytes = assets.archive[image.mediaPath];
      if (!bytes) continue;
      const chunks = [];
      for (let offset = 0; offset < bytes.length; offset += 32768) chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + 32768)));
      source = `data:${image.mimeType};base64,${btoa(chunks.join(""))}`;
      if (image.mimeType === "image/tiff" || image.mimeType === "image/x-tiff") {
        const normalized = renderer.normalizeRaster(source);
        if (normalized) {
          source = normalized;
          image.src = normalized;
        }
      }
      sources.set(image.mediaPath, source);
    } else if (image.mimeType === "image/tiff" || image.mimeType === "image/x-tiff") {
      image.src = source;
    }
    const rendered = renderer.renderPicture(serializePicture(picture.node), source, picture.width, picture.height, resolveColor);
    if (rendered) {
      image.src = createImageSource(strToU8(rendered.svg), "image/svg+xml", assets.objectUrls);
      const bounds = rendered.paintBounds;
      image.paintBounds = bounds ? {
        ...bounds,
        xPx: bounds.xPx + (picture.layoutWidth - picture.width) / 2,
        yPx: bounds.yPx + (picture.layoutHeight - picture.height) / 2,
        layoutWidthPx: picture.layoutWidth,
        layoutHeightPx: picture.layoutHeight
      } : void 0;
      image.pictureRenderStatus = "rendered";
    } else {
      const unsupportedRaster = (image.mimeType === "image/tiff" || image.mimeType === "image/x-tiff") && !source.startsWith("data:image/png;");
      image.pictureRenderStatus = unsupportedRaster || hasPictureDecoration(picture.node) ? "unsupported" : "unchanged";
      if (image.pictureRenderStatus === "unsupported") console.warn("An unsupported picture decoration could not be rendered; the original image is displayed.");
    }
    pictureSources.delete(image);
  }
}
async function parseWorkbookImageAssets(bytes, workbook, parsedArchive) {
  const archive = parsedArchive ?? decodeWorkbookArchive(bytes);
  const {
    contentTypes,
    namedCellStyleByName,
    sheetStatesByWorkbookSheetIndex,
    styleById,
    tableMetadataByWorkbookSheetIndex,
    tableStyleByName,
    theme,
    themePalette,
    workbookSheets
  } = parseWorkbookStructureAssetsFromArchive(archive);
  const objectUrls = [];
  const formControlsByWorkbookSheetIndex = [];
  const imagesByWorkbookSheetIndex = [];
  const shapesByWorkbookSheetIndex = [];
  const sheetOrigins = [];
  const imageOriginsById = /* @__PURE__ */ new Map();
  const formControls = workbook ? collectWorkbookFormControls(workbook, themePalette) : [];
  workbookSheets.forEach((sheet, workbookSheetIndex) => {
    const sheetRelationships = parseRelationships(archive, relsPathForDocument(sheet.path), sheet.path);
    const attachments = [];
    const imageList = [];
    const shapeList = [];
    let zIndexBase = 1;
    for (const relationship of sheetRelationships.values()) {
      if (relationship.type !== DRAWING_REL_TYPE) {
        continue;
      }
      const drawingPath = relationship.target;
      const drawingRelsPath = relsPathForDocument(drawingPath);
      const drawingImages = parseDrawingObjects(
        archive,
        contentTypes,
        drawingPath,
        objectUrls,
        workbookSheetIndex,
        zIndexBase,
        theme,
        sheetStatesByWorkbookSheetIndex[workbookSheetIndex] ?? null,
        imageOriginsById
      );
      imageList.push(...drawingImages.images);
      shapeList.push(...drawingImages.shapes);
      zIndexBase += drawingImages.images.length + drawingImages.shapes.length + 10;
      attachments.push({
        drawingPath,
        drawingRelsPath: archive[drawingRelsPath] ? drawingRelsPath : null,
        mediaPaths: drawingImages.mediaPaths
      });
    }
    const visibleShapeList = shapeList.filter((shape) => !shape.hidden);
    formControlsByWorkbookSheetIndex[workbookSheetIndex] = formControls[workbookSheetIndex] ?? [];
    imagesByWorkbookSheetIndex[workbookSheetIndex] = imageList;
    shapesByWorkbookSheetIndex[workbookSheetIndex] = visibleShapeList;
    sheetOrigins[workbookSheetIndex] = attachments.length > 0 ? {
      attachments,
      workbookSheetIndex
    } : null;
  });
  const assets = {
    archive,
    dirtyArchivePaths: /* @__PURE__ */ new Set(),
    formControlsByWorkbookSheetIndex,
    imageOriginsById,
    imagesByWorkbookSheetIndex,
    namedCellStyleByName,
    objectUrls,
    shapesByWorkbookSheetIndex,
    sheetOrigins,
    sheetStatesByWorkbookSheetIndex,
    styleById,
    tableMetadataByWorkbookSheetIndex,
    tableStyleByName,
    themePalette
  };
  try {
    await renderWorkbookPictures(assets, theme);
    return assets;
  } catch (error) {
    revokeWorkbookImageAssets(assets);
    throw error;
  }
}
function updateAnchorNode(anchorNode, anchor) {
  if (anchor.kind === "two-cell") {
    updateMarkerElement(getFirstChild(anchorNode, "from"), anchor.from);
    updateMarkerElement(getFirstChild(anchorNode, "to"), anchor.to);
    return;
  }
  if (anchor.kind === "one-cell") {
    updateMarkerElement(getFirstChild(anchorNode, "from"), anchor.from);
    const extNode2 = getFirstChild(anchorNode, "ext");
    if (extNode2) {
      extNode2.setAttribute("cx", String(Math.max(0, Math.round(anchor.sizeEmu.cx))));
      extNode2.setAttribute("cy", String(Math.max(0, Math.round(anchor.sizeEmu.cy))));
    }
    return;
  }
  const positionNode = getFirstChild(anchorNode, "pos");
  if (positionNode) {
    positionNode.setAttribute("x", String(Math.max(0, Math.round(anchor.positionEmu.x))));
    positionNode.setAttribute("y", String(Math.max(0, Math.round(anchor.positionEmu.y))));
  }
  const extNode = getFirstChild(anchorNode, "ext");
  if (extNode) {
    extNode.setAttribute("cx", String(Math.max(0, Math.round(anchor.sizeEmu.cx))));
    extNode.setAttribute("cy", String(Math.max(0, Math.round(anchor.sizeEmu.cy))));
  }
}
function updateWorkbookImageAnchor(assets, imageId, anchor) {
  const origin = assets.imageOriginsById.get(imageId);
  if (!origin) {
    return false;
  }
  const attachments = assets.sheetOrigins[origin.workbookSheetIndex]?.attachments ?? [];
  for (const attachment of attachments) {
    if (attachment.drawingPath !== origin.drawingPath) {
      continue;
    }
    const drawingXml = readArchiveText(assets.archive, attachment.drawingPath);
    if (!drawingXml) {
      continue;
    }
    const drawingDocument = parseXml(drawingXml);
    if (!drawingDocument) {
      continue;
    }
    const anchorNodes = createImageAnchorNodes(drawingDocument);
    const anchorNode = anchorNodes[origin.anchorIndex];
    if (!anchorNode) {
      continue;
    }
    let pictureNode = anchorNode;
    let parentGroup = null;
    let groupAnchor = parseAnchor(anchorNode);
    for (const childIndex of origin.picturePath) {
      const child = Array.from(pictureNode.childNodes).filter(isElementNode)[childIndex];
      if (!child || !groupAnchor) {
        break;
      }
      pictureNode = child;
      if (child.localName === "grpSp") {
        parentGroup = parseGroupTransform(
          child,
          parentGroup,
          groupAnchor,
          assets.sheetStatesByWorkbookSheetIndex[origin.workbookSheetIndex] ?? null
        );
        groupAnchor = rectToAbsoluteAnchor(parentGroup);
      }
    }
    if (pictureNode.localName !== "pic") {
      continue;
    }
    if (parentGroup) {
      const transform = getFirstDescendant(pictureNode, "xfrm");
      const off = transform ? getFirstChild(transform, "off") : null;
      const ext = transform ? getFirstChild(transform, "ext") : null;
      if (anchor.kind !== "absolute" || !off || !ext || !parentGroup.scaleX || !parentGroup.scaleY) {
        continue;
      }
      off.setAttribute("x", String(Math.round(parentGroup.chX + (anchor.positionEmu.x - parentGroup.x) / parentGroup.scaleX)));
      off.setAttribute("y", String(Math.round(parentGroup.chY + (anchor.positionEmu.y - parentGroup.y) / parentGroup.scaleY)));
      ext.setAttribute("cx", String(Math.max(0, Math.round(anchor.sizeEmu.cx / parentGroup.scaleX))));
      ext.setAttribute("cy", String(Math.max(0, Math.round(anchor.sizeEmu.cy / parentGroup.scaleY))));
    } else {
      updateAnchorNode(anchorNode, anchor);
    }
    assets.archive[attachment.drawingPath] = strToU8(serializeXml(drawingDocument));
    assets.dirtyArchivePaths.add(normalizeArchivePath(attachment.drawingPath));
    const imageList = assets.imagesByWorkbookSheetIndex[origin.workbookSheetIndex] ?? [];
    const imageIndex = imageList.findIndex((image) => image.id === imageId);
    if (imageIndex >= 0) {
      imageList[imageIndex] = {
        ...imageList[imageIndex],
        anchor
      };
    }
    return true;
  }
  return false;
}
function ensureRelationshipsDocument(archive, relsPath) {
  const existing = readArchiveText(archive, relsPath);
  if (existing) {
    const parsed = parseXml(existing);
    if (parsed) {
      return parsed;
    }
  }
  return parseXml(
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="${PKG_REL_NS}"></Relationships>`
  );
}
function ensureContentTypesDocument(archive) {
  const existing = readArchiveText(archive, "[Content_Types].xml");
  if (existing) {
    const parsed = parseXml(existing);
    if (parsed) {
      return parsed;
    }
  }
  return parseXml(
    `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="${CONTENT_TYPES_NS}"></Types>`
  );
}
function mergeContentTypeForPath(targetDocument, originalDocument, partPath) {
  const normalizedPartName = `/${normalizeArchivePath(partPath)}`;
  const targetRoot = targetDocument.documentElement;
  if (!targetRoot) {
    return;
  }
  const existingOverride = getLocalElements(targetDocument, "Override").find(
    (node) => node.getAttribute("PartName") === normalizedPartName
  );
  if (originalDocument) {
    const sourceOverride = getLocalElements(originalDocument, "Override").find(
      (node) => node.getAttribute("PartName") === normalizedPartName
    );
    if (sourceOverride) {
      if (existingOverride) {
        existingOverride.setAttribute("ContentType", sourceOverride.getAttribute("ContentType"));
      } else {
        targetRoot.appendChild(sourceOverride.cloneNode(true));
      }
      return;
    }
  }
  const extension = normalizedPartName.split(".").pop()?.toLowerCase();
  if (!extension) {
    return;
  }
  const existingDefault = getLocalElements(targetDocument, "Default").find(
    (node) => (node.getAttribute("Extension") ?? "").toLowerCase() === extension
  );
  if (existingDefault) {
    return;
  }
  if (originalDocument) {
    const sourceDefault = getLocalElements(originalDocument, "Default").find(
      (node) => (node.getAttribute("Extension") ?? "").toLowerCase() === extension
    );
    if (sourceDefault) {
      targetRoot.appendChild(sourceDefault.cloneNode(true));
      return;
    }
  }
  if (extension === "xml") {
    const defaultNode = targetDocument.createElementNS(CONTENT_TYPES_NS, "Default");
    defaultNode.setAttribute("Extension", extension);
    defaultNode.setAttribute("ContentType", "application/xml");
    targetRoot.appendChild(defaultNode);
    return;
  }
  if (extension === "rels") {
    const defaultNode = targetDocument.createElementNS(CONTENT_TYPES_NS, "Default");
    defaultNode.setAttribute("Extension", extension);
    defaultNode.setAttribute("ContentType", "application/vnd.openxmlformats-package.relationships+xml");
    targetRoot.appendChild(defaultNode);
  }
}
function removeDrawingReferences(sheetDocument, relDocument) {
  getLocalElements(sheetDocument, "drawing").forEach((node) => node.remove());
  getLocalElements(relDocument, "Relationship").filter((node) => node.getAttribute("Type") === DRAWING_REL_TYPE).forEach((node) => node.remove());
}
function nextRelationshipId(relDocument) {
  const existingIds = new Set(
    getLocalElements(relDocument, "Relationship").map((node) => node.getAttribute("Id")).filter((value) => Boolean(value))
  );
  let index = 1;
  while (existingIds.has(`rIdReactXlsxImage${index}`)) {
    index += 1;
  }
  return `rIdReactXlsxImage${index}`;
}
function appendSheetDrawingReference(sheetDocument, relationshipId) {
  const worksheet = sheetDocument.documentElement;
  if (!worksheet) {
    return;
  }
  const drawingNode = sheetDocument.createElementNS(SPREADSHEET_NS, "drawing");
  drawingNode.setAttributeNS(REL_NS, "r:id", relationshipId);
  const successorNames = /* @__PURE__ */ new Set([
    "legacyDrawing",
    "legacyDrawingHF",
    "picture",
    "oleObjects",
    "controls",
    "webPublishItems",
    "tableParts",
    "extLst"
  ]);
  const successor = Array.from(worksheet.childNodes).find((node) => isElementNode(node) && node.namespaceURI === SPREADSHEET_NS && successorNames.has(node.localName));
  worksheet.insertBefore(drawingNode, successor ?? null);
}
var PIVOT_CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart";
function prepareNativePivotChartAssets(native, assets, origins, modified) {
  if (modified?.length === 0) return assets;
  const hasPivotChart = (archive) => Object.keys(archive).some((path) => path.startsWith("xl/charts/") && path.endsWith(".xml") && /<(?:\w+:)?pivotSource(?:\s|>)/.test(strFromU8(archive[path])));
  if (!hasPivotChart(native) && !hasPivotChart(assets.archive)) return assets;
  const nativeTypes = ensureContentTypesDocument(native);
  const sourceTypes = ensureContentTypesDocument(assets.archive);
  if (!nativeTypes || !sourceTypes) return assets;
  let prepared = null;
  let sequence = 0;
  const copied = /* @__PURE__ */ new Map();
  const writable = () => prepared ??= { ...assets, archive: { ...assets.archive }, dirtyArchivePaths: new Set(assets.dirtyArchivePaths) };
  const copyPart = (path) => {
    const existing = copied.get(path);
    if (existing) return existing;
    const bytes = native[path];
    if (!bytes) throw new Error("A PivotChart relationship target is missing.");
    let target;
    do {
      target = `${path.slice(0, path.lastIndexOf("/") + 1)}pivot-native-${++sequence}-${path.split("/").pop()}`;
    } while (native[target] || assets.archive[target]);
    copied.set(path, target);
    const out = writable();
    out.archive[target] = cloneBytes(bytes);
    const override = getLocalElements(nativeTypes, "Override").find((node) => node.getAttribute("PartName") === `/${path}`);
    if (override) {
      const copy = override.cloneNode(true);
      copy.setAttribute("PartName", `/${target}`);
      sourceTypes.documentElement.appendChild(copy);
    } else mergeContentTypeForPath(sourceTypes, nativeTypes, target);
    const relationships = readArchiveText(native, relsPathForDocument(path));
    if (relationships) {
      const document2 = parseXml(relationships);
      if (!document2) throw new Error("A PivotChart relationship document is invalid.");
      for (const relationship of getLocalElements(document2, "Relationship")) {
        const child = relationship.getAttribute("Target");
        if (child && relationship.getAttribute("TargetMode") !== "External") {
          const copiedChild = copyPart(resolveArchiveTarget(path, child));
          relationship.setAttribute("Target", relativeArchivePath(target, copiedChild));
        }
      }
      out.archive[relsPathForDocument(target)] = strToU8(serializeXml(document2));
    }
    return target;
  };
  const chartAnchors = (archive, path) => {
    const document2 = parseXml(readArchiveText(archive, path) ?? "");
    if (!document2) return [];
    const relationships = parseRelationships(archive, relsPathForDocument(path), path);
    return [...document2.documentElement.children].flatMap((anchor) => getLocalElements(anchor, "graphicFrame").flatMap((frame) => {
      const chart = getFirstDescendant(frame, "chart");
      const relationship = chart && relationships.get(getRelationshipId(chart) ?? "");
      if (!chart || !relationship) return [];
      const chartXml = readArchiveText(archive, relationship.target);
      const pivot = chartXml ? /<(?:\w+:)?pivotSource(?:\s|>)/.test(chartXml) : false;
      return [{ anchor, name: getFirstDescendant(frame, "cNvPr")?.getAttribute("name") ?? "", chartPath: relationship.target, pivot, nested: frame.parentNode !== anchor }];
    }));
  };
  parseWorkbookSheets(native).forEach((sheet, index) => {
    const changes = modified?.filter((chart) => chart.sheet.toLowerCase() === sheet.name.toLowerCase());
    if (changes?.length === 0) return;
    const origin = origins[index];
    if (!origin?.attachments.length) return;
    const original = origin.attachments.flatMap((attachment) => chartAnchors(assets.archive, attachment.drawingPath).map((chart) => ({ ...chart, drawingPath: attachment.drawingPath })));
    for (const previous of original.filter((chart) => chart.nested)) {
      const change = changes?.find((change2) => change2.name === previous.name);
      if (!change || change.sourceName === void 0) continue;
      const document2 = parseXml(readArchiveText(writable().archive, previous.chartPath) ?? "");
      if (!document2) throw new Error("A PivotChart source document is invalid.");
      const oldSource = getFirstChild(document2.documentElement, "pivotSource");
      if (change.sourceName !== null) {
        const source = document2.createElementNS(PIVOT_CHART_NS, "c:pivotSource");
        source.setAttribute("xmlns:c", PIVOT_CHART_NS);
        const name = document2.createElementNS(PIVOT_CHART_NS, "c:name");
        name.textContent = change.sourceName;
        source.appendChild(name);
        const format = document2.createElementNS(PIVOT_CHART_NS, "c:fmtId");
        format.setAttribute("val", String(change.formatId ?? 0));
        source.appendChild(format);
        document2.documentElement.insertBefore(source, oldSource ?? getFirstChild(document2.documentElement, "chart") ?? null);
      }
      oldSource?.parentNode?.removeChild(oldSource);
      writable().archive[previous.chartPath] = strToU8(serializeXml(document2));
      writable().dirtyArchivePaths.add(previous.chartPath);
    }
    const pivotNames = new Set(original.filter((chart) => chart.pivot).map((chart) => chart.name));
    const generated = [...parseRelationships(native, relsPathForDocument(sheet.path), sheet.path).values()].filter((relationship) => relationship.type === DRAWING_REL_TYPE).flatMap((relationship) => chartAnchors(native, relationship.target)).filter((chart) => (chart.pivot || pivotNames.has(chart.name)) && (!changes || changes.some((change) => !change.name || change.name === chart.name)));
    for (const chart of generated) {
      const previous = original.find((candidate) => candidate.name === chart.name) ?? (sheet.path.startsWith("xl/chartsheets/") ? original.find((candidate) => candidate.pivot) : void 0);
      if (previous && (chart.nested || !chart.pivot && previous.pivot)) {
        const document3 = parseXml(readArchiveText(writable().archive, previous.chartPath) ?? "");
        const generated2 = parseXml(readArchiveText(native, chart.chartPath) ?? "");
        if (!document3 || !generated2) throw new Error("A PivotChart source document is invalid.");
        const oldSource = getFirstChild(document3.documentElement, "pivotSource");
        const source = getFirstChild(generated2.documentElement, "pivotSource");
        if (source) document3.documentElement.insertBefore(source.cloneNode(true), oldSource ?? getFirstChild(document3.documentElement, "chart") ?? null);
        oldSource?.parentNode?.removeChild(oldSource);
        writable().archive[previous.chartPath] = strToU8(serializeXml(document3));
        writable().dirtyArchivePaths.add(previous.chartPath);
        continue;
      }
      const drawingPath = previous?.drawingPath ?? origin.attachments[0].drawingPath;
      const out = writable();
      const document2 = parseXml(readArchiveText(out.archive, drawingPath) ?? "");
      const relationships = ensureRelationshipsDocument(out.archive, relsPathForDocument(drawingPath));
      if (!document2 || !relationships) throw new Error("A PivotChart drawing document is invalid.");
      const anchor = chart.anchor.cloneNode(true);
      const chartNode = getFirstDescendant(anchor, "chart");
      if (!chartNode) continue;
      const copiedChart = copyPart(chart.chartPath);
      const id = nextRelationshipId(relationships);
      chartNode.setAttributeNS(REL_NS, "r:id", id);
      const relationship = relationships.createElementNS(PKG_REL_NS, "Relationship");
      relationship.setAttribute("Id", id);
      relationship.setAttribute("Type", `${REL_NS}/chart`);
      relationship.setAttribute("Target", relativeArchivePath(drawingPath, copiedChart));
      relationships.documentElement.appendChild(relationship);
      const oldAnchor = [...document2.documentElement.children].find((node) => getFirstDescendant(node, "cNvPr")?.getAttribute("name") === (previous?.name ?? chart.name));
      if (oldAnchor) {
        const oldChart = getFirstDescendant(oldAnchor, "chart");
        const oldId = oldChart && getRelationshipId(oldChart);
        const oldRelationship = getLocalElements(relationships, "Relationship").find((node) => node.getAttribute("Id") === oldId);
        oldRelationship?.parentNode?.removeChild(oldRelationship);
        oldAnchor.parentNode?.insertBefore(anchor, oldAnchor);
        oldAnchor.parentNode?.removeChild(oldAnchor);
      } else {
        const nextId = Math.max(0, ...getLocalElements(document2, "cNvPr").map((node) => Number(node.getAttribute("id")) || 0)) + 1;
        getFirstDescendant(anchor, "cNvPr")?.setAttribute("id", String(nextId));
        document2.documentElement.appendChild(anchor);
      }
      out.archive[drawingPath] = strToU8(serializeXml(document2));
      out.archive[relsPathForDocument(drawingPath)] = strToU8(serializeXml(relationships));
      out.dirtyArchivePaths.add(drawingPath);
      out.dirtyArchivePaths.add(relsPathForDocument(drawingPath));
    }
  });
  if (!prepared) return assets;
  const result = prepared;
  result.archive["[Content_Types].xml"] = strToU8(serializeXml(sourceTypes));
  return result;
}
function mergeWorkbookImageAssets(savedBytes, sourceAssets, sheetOrigins, parsedArchive, modifiedPivotCharts) {
  if (!sourceAssets) {
    return cloneBytes(savedBytes);
  }
  try {
    const archive = parsedArchive ?? decodeWorkbookArchive(savedBytes);
    const exportAssets = prepareNativePivotChartAssets(archive, sourceAssets, sheetOrigins, modifiedPivotCharts);
    const workbookSheets = parseWorkbookSheets(archive);
    const originalContentTypesDocument = parseXml(readArchiveText(exportAssets.archive, "[Content_Types].xml") ?? "");
    const targetContentTypesDocument = ensureContentTypesDocument(archive);
    if (!targetContentTypesDocument) {
      return cloneBytes(savedBytes);
    }
    const copiedParts = /* @__PURE__ */ new Set();
    const copyDrawingPart = (path) => {
      const normalizedPath = normalizeArchivePath(path);
      const bytes = exportAssets.archive[normalizedPath];
      if (!bytes || copiedParts.has(normalizedPath)) {
        return;
      }
      copiedParts.add(normalizedPath);
      archive[normalizedPath] = cloneBytes(bytes);
      mergeContentTypeForPath(targetContentTypesDocument, originalContentTypesDocument, normalizedPath);
      const relsPath = relsPathForDocument(normalizedPath);
      const relsBytes = exportAssets.archive[relsPath];
      if (!relsBytes) {
        return;
      }
      archive[relsPath] = cloneBytes(relsBytes);
      mergeContentTypeForPath(targetContentTypesDocument, originalContentTypesDocument, relsPath);
      for (const relationship of parseRelationships(exportAssets.archive, relsPath, normalizedPath).values()) {
        if (relationship.targetMode !== "External" && !relationship.type.endsWith("/hyperlink")) {
          copyDrawingPart(relationship.target);
        }
      }
    };
    sheetOrigins.forEach((origin, workbookSheetIndex) => {
      if (!origin?.attachments.length) {
        return;
      }
      const currentSheet = workbookSheets[workbookSheetIndex];
      if (!currentSheet) {
        return;
      }
      const sheetXml = readArchiveText(archive, currentSheet.path);
      if (!sheetXml) {
        return;
      }
      const sheetDocument = parseXml(sheetXml);
      const relsPath = relsPathForDocument(currentSheet.path);
      const relDocument = ensureRelationshipsDocument(archive, relsPath);
      if (!sheetDocument || !relDocument) {
        return;
      }
      removeDrawingReferences(sheetDocument, relDocument);
      origin.attachments.forEach((attachment) => {
        const drawingBytes = exportAssets.archive[attachment.drawingPath];
        if (!drawingBytes) {
          return;
        }
        copyDrawingPart(attachment.drawingPath);
        const relationshipId = nextRelationshipId(relDocument);
        const relationshipNode = relDocument.createElementNS(PKG_REL_NS, "Relationship");
        relationshipNode.setAttribute("Id", relationshipId);
        relationshipNode.setAttribute("Type", DRAWING_REL_TYPE);
        relationshipNode.setAttribute("Target", relativeArchivePath(currentSheet.path, attachment.drawingPath));
        relDocument.documentElement?.appendChild(relationshipNode);
        appendSheetDrawingReference(sheetDocument, relationshipId);
      });
      archive[currentSheet.path] = strToU8(serializeXml(sheetDocument));
      archive[relsPath] = strToU8(serializeXml(relDocument));
      mergeContentTypeForPath(targetContentTypesDocument, originalContentTypesDocument, relsPath);
    });
    for (const dirtyPath of exportAssets.dirtyArchivePaths) {
      const bytes = exportAssets.archive[dirtyPath];
      if (!bytes) {
        continue;
      }
      archive[dirtyPath] = cloneBytes(bytes);
      mergeContentTypeForPath(targetContentTypesDocument, originalContentTypesDocument, dirtyPath);
    }
    const hasDrawingOverride = getLocalElements(targetContentTypesDocument, "Override").some(
      (node) => node.getAttribute("ContentType") === DRAWING_CONTENT_TYPE
    );
    if (!hasDrawingOverride) {
      for (const path of Object.keys(archive)) {
        if (path.startsWith("xl/drawings/") && path.endsWith(".xml")) {
          mergeContentTypeForPath(targetContentTypesDocument, originalContentTypesDocument, path);
        }
      }
    }
    archive["[Content_Types].xml"] = strToU8(serializeXml(targetContentTypesDocument));
    return zipSync(archive, { level: 6 });
  } catch {
    return cloneBytes(savedBytes);
  }
}
function emuToPixels(value) {
  return value / EMU_PER_PIXEL;
}
function pixelsToEmu(value) {
  return value * EMU_PER_PIXEL;
}
function pxToSheetColumnWidth(widthPx, columnCharacterWidthPx = DEFAULT_COLUMN_CHARACTER_WIDTH_PX) {
  const digitWidth = Math.max(1, columnCharacterWidthPx);
  const pixels = Math.max(widthPx, MIN_COL_WIDTH_PX);
  return pixels < digitWidth ? pixels / (digitWidth + 5) : (pixels + 0.5) / digitWidth - Math.floor(128 / digitWidth) / 256;
}
function resolveOfficeColumnWidthPixels(width, digitWidthPt = 6) {
  return Math.max(0, Math.floor(
    (256 * width + Math.floor(128 / digitWidthPt)) / 256 * digitWidthPt
  ) * (4 / 3));
}
function pxToOfficeColumnWidth(widthPx, digitWidthPt = 6) {
  const points = Math.round(Math.max(widthPx, MIN_COL_WIDTH_PX) * (3 / 4));
  return (points + 0.5) / digitWidthPt - Math.floor(128 / digitWidthPt) / 256;
}
function resolveSheetColumnWidthPixels(width, columnWidthCharacterWidthPx) {
  return sheetColumnWidthToPixels(width, columnWidthCharacterWidthPx);
}
function resolveSheetRowHeightPixels(height) {
  return Math.max(Math.round(height * 1.33), MIN_ROW_HEIGHT_PX);
}
function resolveRenderedSheetAxisPixels(sizePx, showGridLines = true) {
  return Math.max(0, sizePx) + (showGridLines ? resolveDeviceGridlineThicknessPx() : 0);
}
function resolveContentSheetAxisPixels(sizePx, showGridLines = true) {
  return Math.max(0, sizePx - (showGridLines ? resolveDeviceGridlineThicknessPx() : 0));
}
function markerFromOffset(offsetPx, getSizePx) {
  let remaining = Math.max(0, offsetPx);
  let index = 0;
  while (remaining > 0) {
    const size = Math.max(0, getSizePx(index));
    if (remaining < size) {
      break;
    }
    remaining -= size;
    index += 1;
  }
  return {
    index,
    offsetPx: remaining
  };
}
function rectToImageAnchor(rect, currentAnchor, options) {
  const contentLeft = Math.max(0, rect.left - options.contentOffsetLeft);
  const contentTop = Math.max(0, rect.top - options.contentOffsetTop);
  const contentRight = Math.max(contentLeft + 1, rect.left + rect.width - options.contentOffsetLeft);
  const contentBottom = Math.max(contentTop + 1, rect.top + rect.height - options.contentOffsetTop);
  if (currentAnchor.kind === "absolute") {
    return {
      kind: "absolute",
      positionEmu: {
        x: pixelsToEmu(contentLeft),
        y: pixelsToEmu(contentTop)
      },
      sizeEmu: {
        cx: pixelsToEmu(rect.width),
        cy: pixelsToEmu(rect.height)
      }
    };
  }
  const fromCol = markerFromOffset(contentLeft, options.getColumnWidthPx);
  const fromRow = markerFromOffset(contentTop, options.getRowHeightPx);
  if (currentAnchor.kind === "one-cell") {
    return {
      from: {
        col: fromCol.index,
        colOffsetEmu: pixelsToEmu(fromCol.offsetPx),
        row: fromRow.index,
        rowOffsetEmu: pixelsToEmu(fromRow.offsetPx)
      },
      kind: "one-cell",
      sizeEmu: {
        cx: pixelsToEmu(rect.width),
        cy: pixelsToEmu(rect.height)
      }
    };
  }
  const toCol = markerFromOffset(contentRight, options.getColumnWidthPx);
  const toRow = markerFromOffset(contentBottom, options.getRowHeightPx);
  return {
    from: {
      col: fromCol.index,
      colOffsetEmu: pixelsToEmu(fromCol.offsetPx),
      row: fromRow.index,
      rowOffsetEmu: pixelsToEmu(fromRow.offsetPx)
    },
    kind: "two-cell",
    to: {
      col: toCol.index,
      colOffsetEmu: pixelsToEmu(toCol.offsetPx),
      row: toRow.index,
      rowOffsetEmu: pixelsToEmu(toRow.offsetPx)
    }
  };
}
function resizeImageRect(rect, handle, deltaX, deltaY, minimumSize = 16) {
  let left = rect.left;
  let top = rect.top;
  let width = rect.width;
  let height = rect.height;
  if (handle.includes("w")) {
    left += deltaX;
    width -= deltaX;
  }
  if (handle.includes("e")) {
    width += deltaX;
  }
  if (handle.includes("n")) {
    top += deltaY;
    height -= deltaY;
  }
  if (handle.includes("s")) {
    height += deltaY;
  }
  if (width < minimumSize) {
    if (handle.includes("w")) {
      left -= minimumSize - width;
    }
    width = minimumSize;
  }
  if (height < minimumSize) {
    if (handle.includes("n")) {
      top -= minimumSize - height;
    }
    height = minimumSize;
  }
  return { height, left, top, width };
}

// src/workbook-assets.ts
function inferImageMimeType(source) {
  if (source.startsWith("data:")) {
    const separatorIndex = source.indexOf(";");
    if (separatorIndex > 5) {
      return source.slice(5, separatorIndex);
    }
  }
  const normalized = source.split("?")[0]?.toLowerCase() ?? "";
  if (normalized.endsWith(".gif")) {
    return "image/gif";
  }
  if (normalized.endsWith(".jpg") || normalized.endsWith(".jpeg")) {
    return "image/jpeg";
  }
  if (normalized.endsWith(".svg")) {
    return "image/svg+xml";
  }
  if (normalized.endsWith(".webp")) {
    return "image/webp";
  }
  return "image/png";
}
function inferWorksheetDirectImageMimeType(info) {
  const format = info.format;
  if (format === "gif") {
    return "image/gif";
  }
  if (format === "jpeg") {
    return "image/jpeg";
  }
  if (format === "svg") {
    return "image/svg+xml";
  }
  if (format === "bmp") {
    return "image/bmp";
  }
  if (format === "tiff") {
    return "image/tiff";
  }
  if (format === "emf") {
    return "image/emf";
  }
  if (format === "wmf") {
    return "image/wmf";
  }
  if (format === "png") {
    return "image/png";
  }
  const mediaPath = typeof info.mediaPath === "string" ? info.mediaPath : "";
  if (mediaPath) {
    return inferImageMimeType(mediaPath);
  }
  return "image/png";
}
function createWorksheetDirectImageSource(data, mimeType, objectUrls) {
  const bytes = data instanceof Uint8Array ? data : Array.isArray(data) ? Uint8Array.from(data.filter((value) => typeof value === "number")) : null;
  if (!bytes || bytes.byteLength === 0) {
    return null;
  }
  const blobBuffer = new Uint8Array(bytes.byteLength);
  blobBuffer.set(bytes);
  const objectUrl = createWorkbookObjectUrl(new Blob([blobBuffer.buffer], { type: mimeType }));
  objectUrls.push(objectUrl);
  return objectUrl;
}
function buildWorksheetDirectApiImage(worksheet, workbookSheetIndex, drawing, objectUrls) {
  const hasSvgCompanion = Boolean(drawing.image.svgMediaPath);
  let mimeType = inferWorksheetDirectImageMimeType(drawing.image);
  let data;
  try {
    const svgData = drawing.image.format === "svg" || hasSvgCompanion ? worksheet.drawingSvgData(drawing.drawingPath) : void 0;
    if (svgData) {
      data = svgData;
      mimeType = "image/svg+xml";
    } else {
      data = worksheet.drawingImageData(drawing.drawingPath);
    }
  } catch {
    return null;
  }
  const src = createWorksheetDirectImageSource(data, mimeType, objectUrls);
  if (!src) {
    return null;
  }
  const zIndex = (drawing.drawingPath[0] ?? 0) + 1;
  return {
    anchor: dukeDrawingAnchorToXlsxAnchor(drawing.anchor),
    description: drawing.altText,
    editable: false,
    id: `worksheet-image-${workbookSheetIndex}-${drawing.drawingPath.join("-")}`,
    mediaPath: drawing.image.mediaPath || void 0,
    mimeType,
    name: drawing.name,
    sheetIndex: workbookSheetIndex,
    src,
    workbookSheetIndex,
    zIndex
  };
}
function collectWorksheetApiImages(workbook, objectUrls) {
  const directImagesByWorkbookSheetIndex = Array.from({ length: workbook.sheetCount }, () => []);
  for (let workbookSheetIndex = 0; workbookSheetIndex < workbook.sheetCount; workbookSheetIndex += 1) {
    const worksheet = workbook.getSheet(workbookSheetIndex);
    const rawImages = worksheet.images;
    if (rawImages.length === 0) {
      continue;
    }
    const nextImages = rawImages.filter((drawing) => !drawing.hidden && Boolean(drawing.anchor)).map((drawing) => buildWorksheetDirectApiImage(worksheet, workbookSheetIndex, drawing, objectUrls)).filter((image) => Boolean(image));
    if (nextImages.length > 0) {
      directImagesByWorkbookSheetIndex[workbookSheetIndex] = nextImages;
    }
  }
  return directImagesByWorkbookSheetIndex;
}
function imageAnchorKey(anchor) {
  if (anchor.kind === "absolute") {
    return [
      "absolute",
      Math.round(anchor.positionEmu.x),
      Math.round(anchor.positionEmu.y),
      Math.round(anchor.sizeEmu.cx),
      Math.round(anchor.sizeEmu.cy)
    ].join(":");
  }
  if (anchor.kind === "one-cell") {
    return [
      "one",
      anchor.from.col,
      anchor.from.row,
      Math.round(anchor.from.colOffsetEmu),
      Math.round(anchor.from.rowOffsetEmu),
      Math.round(anchor.sizeEmu.cx),
      Math.round(anchor.sizeEmu.cy)
    ].join(":");
  }
  return [
    "two",
    anchor.from.col,
    anchor.from.row,
    Math.round(anchor.from.colOffsetEmu),
    Math.round(anchor.from.rowOffsetEmu),
    anchor.to.col,
    anchor.to.row,
    Math.round(anchor.to.colOffsetEmu),
    Math.round(anchor.to.rowOffsetEmu)
  ].join(":");
}
function collectHiddenWorksheetImageAnchors(workbook) {
  return Array.from({ length: workbook.sheetCount }, (_, workbookSheetIndex) => new Set(
    workbook.getSheet(workbookSheetIndex).images.flatMap((drawing) => drawing.hidden && drawing.anchor ? [imageAnchorKey(dukeDrawingAnchorToXlsxAnchor(drawing.anchor))] : [])
  ));
}
function mergeParsedAndApiImages(parsedImages, apiImages, hiddenAnchorKeys) {
  const visibleParsedImages = parsedImages.filter((image) => !hiddenAnchorKeys.has(imageAnchorKey(image.anchor)));
  if (visibleParsedImages.length === 0) {
    return apiImages;
  }
  if (apiImages.length === 0) {
    return visibleParsedImages;
  }
  const normalizeTextKey = (value) => value?.trim().toLowerCase() ?? "";
  const imageKeys = (image) => {
    const keys = [
      `${normalizeTextKey(image.mediaPath)}|${normalizeTextKey(image.name)}|${imageAnchorKey(image.anchor)}`,
      `${normalizeTextKey(image.mediaPath)}|${imageAnchorKey(image.anchor)}`,
      `${normalizeTextKey(image.name)}|${imageAnchorKey(image.anchor)}`,
      `${imageAnchorKey(image.anchor)}`
    ];
    return keys.filter((key, index) => key && keys.indexOf(key) === index);
  };
  const apiBuckets = /* @__PURE__ */ new Map();
  for (const apiImage of apiImages) {
    for (const key of imageKeys(apiImage)) {
      const bucket = apiBuckets.get(key);
      if (bucket) {
        bucket.push(apiImage);
      } else {
        apiBuckets.set(key, [apiImage]);
      }
    }
  }
  const usedApiImages = /* @__PURE__ */ new Set();
  const takeApiMatch = (image) => {
    for (const key of imageKeys(image)) {
      const bucket = apiBuckets.get(key);
      if (!bucket) {
        continue;
      }
      const match = bucket.find((candidate) => !usedApiImages.has(candidate));
      if (match) {
        usedApiImages.add(match);
        return match;
      }
    }
    return null;
  };
  const merged = visibleParsedImages.map((image) => {
    const apiImage = takeApiMatch(image);
    if (!apiImage) {
      return image;
    }
    return {
      ...image,
      anchor: apiImage.anchor,
      mediaPath: apiImage.mediaPath ?? image.mediaPath,
      mimeType: apiImage.mimeType,
      name: apiImage.name ?? image.name,
      src: image.pictureRenderStatus ? image.src : apiImage.src,
      zIndex: apiImage.zIndex
    };
  });
  return merged;
}
function isZipWorkbook(bytes) {
  return bytes.byteLength >= 4 && bytes[0] === 80 && bytes[1] === 75;
}
function isLegacyXlsWorkbook(bytes) {
  return bytes.byteLength >= 8 && bytes[0] === 208 && bytes[1] === 207 && bytes[2] === 17 && bytes[3] === 224 && bytes[4] === 161 && bytes[5] === 177 && bytes[6] === 26 && bytes[7] === 225;
}
function shouldSkipXmlParsingForWorkbook(bytes, skipXmlParsing = false) {
  return skipXmlParsing || isLegacyXlsWorkbook(bytes);
}
function createBasicWorkbookAssets(workbook) {
  const objectUrls = [];
  return {
    archive: {},
    dirtyArchivePaths: /* @__PURE__ */ new Set(),
    formControlsByWorkbookSheetIndex: collectWorkbookFormControls(workbook),
    imageOriginsById: /* @__PURE__ */ new Map(),
    imagesByWorkbookSheetIndex: collectWorksheetApiImages(workbook, objectUrls),
    namedCellStyleByName: {},
    objectUrls,
    shapesByWorkbookSheetIndex: Array.from({ length: workbook.sheetCount }, () => []),
    sheetOrigins: Array.from({ length: workbook.sheetCount }, () => null),
    sheetStatesByWorkbookSheetIndex: Array.from({ length: workbook.sheetCount }, () => null),
    styleById: {},
    tableMetadataByWorkbookSheetIndex: Array.from({ length: workbook.sheetCount }, () => []),
    tableStyleByName: {},
    themePalette: { colorsByIndex: {} }
  };
}
async function loadWorkbookImageAssets(bytes, workbook, skipXmlParsing = false, archive) {
  if (shouldSkipXmlParsingForWorkbook(bytes, skipXmlParsing) || !isZipWorkbook(bytes)) {
    return createBasicWorkbookAssets(workbook);
  }
  const parsedAssets = await parseWorkbookImageAssets(bytes, workbook, archive);
  const apiImagesByWorkbookSheetIndex = collectWorksheetApiImages(workbook, parsedAssets.objectUrls);
  const hiddenImageAnchorsByWorkbookSheetIndex = collectHiddenWorksheetImageAnchors(workbook);
  const imagesByWorkbookSheetIndex = Array.from(
    { length: Math.max(workbook.sheetCount, parsedAssets.imagesByWorkbookSheetIndex.length, apiImagesByWorkbookSheetIndex.length) },
    (_, index) => {
      const parsedImages = parsedAssets.imagesByWorkbookSheetIndex[index] ?? [];
      const apiImages = apiImagesByWorkbookSheetIndex[index] ?? [];
      return mergeParsedAndApiImages(
        parsedImages,
        apiImages,
        hiddenImageAnchorsByWorkbookSheetIndex[index] ?? /* @__PURE__ */ new Set()
      );
    }
  );
  return {
    ...parsedAssets,
    imagesByWorkbookSheetIndex
  };
}

// src/number-locale.ts
var separators = /* @__PURE__ */ new Map();
function parseLocaleNumber(text, locale) {
  if (locale === "en-US") return void 0;
  const parts = new Intl.NumberFormat(locale).formatToParts(12345.6);
  const decimal = parts.find((part) => part.type === "decimal")?.value ?? ".";
  const group = parts.find((part) => part.type === "group")?.value ?? ",";
  let normalized = text.trim();
  const percent = normalized.endsWith("%");
  if (percent) normalized = normalized.slice(0, -1).trim();
  normalized = group.trim() === "" ? normalized.replace(/[ \u00a0\u202f]/g, "") : normalized.split(group).join("");
  normalized = normalized.replace(decimal, ".");
  if (!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(normalized)) return void 0;
  const value = Number(normalized) / (percent ? 100 : 1);
  return Number.isFinite(value) ? value : void 0;
}
function localizeCellNumber(worksheet, row, col, text, locale = "en-US") {
  if (locale === "en-US" || !text) return text;
  const value = worksheet.getCalculatedValueAt(row, col);
  try {
    if (!value.is_number) return text;
  } finally {
    value.free();
  }
  const style = worksheet.getCellStyleAt(row, col);
  return localizeFormattedNumber(text, style?.numberFormat, locale);
}
function localizeFormattedNumber(text, format, locale) {
  if (locale === "en-US" || !text || format?.isDateFormat) return text;
  let symbols = separators.get(locale);
  if (!symbols) {
    const parts = new Intl.NumberFormat(locale).formatToParts(12345.6);
    symbols = {
      decimal: parts.find((part) => part.type === "decimal")?.value ?? ".",
      group: parts.find((part) => part.type === "group")?.value ?? ","
    };
    if (separators.size >= 100) separators.clear();
    separators.set(locale, symbols);
  }
  if (symbols.decimal === "." && symbols.group === ",") return text;
  const protectedPositions = /* @__PURE__ */ new Set();
  const code = format?.formatString ?? "";
  const literalPattern = /"[^"]*"|\\.|\[[^\]]*\]/g;
  const firstPlaceholder = code.replace(literalPattern, (token) => " ".repeat(token.length)).search(/[0#?]/);
  const literals = [...code.matchAll(literalPattern)];
  let suffixEnd = text.length;
  let prefixStart = 0;
  const protect = (token, suffix) => {
    const literal = token.startsWith('"') ? token.slice(1, -1) : token.startsWith("\\") ? token.slice(1) : token.startsWith("[$") ? token.slice(2, -1).split("-")[0] : "";
    if (!literal) return;
    const offset = suffix ? text.lastIndexOf(literal, suffixEnd - literal.length) : text.indexOf(literal, prefixStart);
    if (offset >= 0) {
      for (let i = offset; i < offset + literal.length; i++) protectedPositions.add(i);
      if (suffix) suffixEnd = offset;
      else prefixStart = offset + literal.length;
    }
  };
  for (const token of literals.filter((token2) => token2.index < firstPlaceholder)) protect(token[0], false);
  for (const token of literals.filter((token2) => token2.index >= firstPlaceholder).reverse()) protect(token[0], true);
  return text.replace(
    /\d[\d,]*(?:\.\d*)?|\.\d+/g,
    (number, offset) => number.replace(/[.,]/g, (separator, index) => protectedPositions.has(offset + index) ? separator : separator === "." ? symbols.decimal : symbols.group)
  );
}
function localizeRows(rows, locale = "en-US") {
  if (locale === "en-US" || !Array.isArray(rows)) return;
  for (const row of rows) {
    for (const cell of row.cells ?? []) {
      if (cell.isMergedSecondary || typeof cell.value !== "string") continue;
      if (typeof cell.numericValue === "number") {
        cell.value = localizeFormattedNumber(cell.value, cell.style?.numberFormat, locale);
      } else {
        cell.numericValue = null;
      }
    }
  }
}

// src/spreadsheet-fonts.ts
async function loadSpreadsheetFonts(families, target) {
  await loadOfficeFonts(target, families).catch(() => void 0);
}

// src/builtin-chart-styles.ts
function decodeSrgb(channel) {
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}
function encodeSrgb(channel) {
  return channel <= 31308e-7 ? channel * 12.92 : 1.055 * channel ** (1 / 2.4) - 0.055;
}
function quantizeLinear(channel) {
  return Math.round(channel * 1e5) / 1e5;
}
function resolveBuiltinChartColor(color, colorsByIndex) {
  if (!color) return void 0;
  const hex = colorsByIndex[color.themeIndex]?.replace(/^#/, "");
  if (!hex || !/^[\da-f]{6}$/i.test(hex)) return void 0;
  if (color.transforms.length === 0) return `#${hex.toLowerCase()}`;
  const channels = [0, 2, 4].map((offset) => Math.fround(quantizeLinear(decodeSrgb(Number.parseInt(hex.slice(offset, offset + 2), 16) / 255))));
  for (const transform of color.transforms) {
    const amount = Math.fround(Math.max(0, Math.min(1, transform.value)));
    for (let index = 0; index < channels.length; index += 1) {
      const channel = channels[index];
      channels[index] = transform.type === "tint" ? Math.fround(Math.fround(1 - amount) + Math.fround(amount * channel)) : Math.fround(amount * channel);
    }
  }
  return `#${channels.map((channel) => Math.round(encodeSrgb(quantizeLinear(channel)) * 255).toString(16).padStart(2, "0")).join("")}`;
}
var GRAYSCALE_TINTS = [88, 55, 78, 92, 70, 30];
var DARK_GRAYSCALE_TINTS = [5, 55, 78, 15, 70, 30];
function normalizeClassicStyle(styleId) {
  if (styleId === void 0 || !Number.isInteger(styleId)) return void 0;
  if (styleId >= 1 && styleId <= 48) return styleId;
  if (styleId >= 101 && styleId <= 148) return styleId - 100;
  return void 0;
}
function themeColor(themeIndex, tint) {
  return {
    themeIndex,
    transforms: tint === void 0 ? [] : [{ type: "tint", value: tint / 100 }]
  };
}
function appendBrightness(color, percent) {
  if (percent > 0) color.transforms.push({ type: "tint", value: (100 - percent) / 100 });
  if (percent < 0) color.transforms.push({ type: "shade", value: (100 + percent) / 100 });
  return color;
}
function getBuiltinChartColor(styleId, index, count) {
  const style = normalizeClassicStyle(styleId);
  if (style === void 0 || !Number.isInteger(index) || index < 0 || !Number.isInteger(count) || count < 1) {
    return void 0;
  }
  const palette = style === 41 ? 9 : (style - 1) % 8 + 1;
  const monochrome = palette >= 3 && palette <= 8;
  const color = monochrome ? themeColor(palette + 1) : palette === 2 ? themeColor(4 + index % 6) : themeColor(1, (palette === 9 ? DARK_GRAYSCALE_TINTS : GRAYSCALE_TINTS)[index % 6]);
  const numerator = 140 * (monochrome ? index + 1 : Math.floor(index / 6) + 1);
  const denominator = monochrome ? count + 1 : Math.floor(count / 6) + 2;
  const brightness = (Math.trunc(Math.fround(Math.fround(numerator) / Math.fround(denominator))) - 70) % 100;
  return appendBrightness(color, brightness);
}
function getBuiltinChartSurfaceStyle(styleId) {
  const style = normalizeClassicStyle(styleId);
  if (style === void 0) return void 0;
  let fill = null;
  if (style === 33 || style === 34) fill = themeColor(1, 20);
  if (style >= 35 && style <= 40) fill = themeColor(style - 31, (styleId ?? 0) >= 100 ? 20 : void 0);
  if (style >= 41) fill = themeColor(1, 95);
  return {
    floor: { fill, line: style <= 40 ? themeColor(1, 75) : null },
    wall: { fill, line: null },
    majorGridline: themeColor(1, (styleId ?? 0) >= 100 ? 75 : void 0),
    minorGridline: themeColor(1, style >= 41 ? 90 : 50)
  };
}

// src/chartsheet-payload.ts
import { strFromU8 as strFromU82 } from "fflate";
var REL_NS2 = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
function readXml(archive, path) {
  const bytes = archive[path];
  if (!bytes) return null;
  const document2 = parseWorkbookXml(strFromU82(bytes));
  return document2.getElementsByTagName("parsererror").length > 0 ? null : document2;
}
function relationshipPath(partPath) {
  const separator = partPath.lastIndexOf("/");
  return `${partPath.slice(0, separator + 1)}_rels/${partPath.slice(separator + 1)}.rels`;
}
function resolveTarget(partPath, target) {
  if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith("//")) return null;
  const segments = target.startsWith("/") ? [] : partPath.split("/").slice(0, -1);
  for (const segment of target.replace(/\\/g, "/").split("/")) {
    if (!segment || segment === ".") continue;
    if (segment === "..") {
      if (segments.length === 0) return null;
      segments.pop();
    } else {
      segments.push(segment);
    }
  }
  return segments.join("/");
}
function readRelationships(archive, partPath) {
  const relationships = /* @__PURE__ */ new Map();
  const document2 = readXml(archive, relationshipPath(partPath));
  for (const element of Array.from(document2?.getElementsByTagNameNS("*", "Relationship") ?? [])) {
    if (element.getAttribute("TargetMode") === "External") continue;
    const id = element.getAttribute("Id");
    const rawTarget = element.getAttribute("Target");
    const type = element.getAttribute("Type");
    const target = rawTarget ? resolveTarget(partPath, rawTarget) : null;
    if (id && type && target && archive[target]) relationships.set(id, { target, type });
  }
  return relationships;
}
function collectChartsheetDrawingOrigins(archive, chartsheets) {
  const origins = /* @__PURE__ */ new Map();
  if (chartsheets.length === 0) return origins;
  const workbookPath = "xl/workbook.xml";
  const workbookDocument = readXml(archive, workbookPath);
  const workbookRelationships = readRelationships(archive, workbookPath);
  for (const sheet of Array.from(workbookDocument?.getElementsByTagNameNS("*", "sheet") ?? [])) {
    const relationshipId = sheet.getAttributeNS(REL_NS2, "id") ?? sheet.getAttribute("r:id");
    const relationship = relationshipId ? workbookRelationships.get(relationshipId) : null;
    if (!relationship?.type.endsWith("/chartsheet")) continue;
    const chartsheet = chartsheets.find((entry) => entry.name === sheet.getAttribute("name"));
    if (!chartsheet || chartsheet.workbookSheetIndex == null) continue;
    const sheetDocument = readXml(archive, relationship.target);
    const sheetRelationships = readRelationships(archive, relationship.target);
    const attachments = [];
    for (const drawing of Array.from(sheetDocument?.getElementsByTagNameNS("*", "drawing") ?? [])) {
      const drawingId = drawing.getAttributeNS(REL_NS2, "id") ?? drawing.getAttribute("r:id");
      const drawingRelationship = drawingId ? sheetRelationships.get(drawingId) : null;
      if (!drawingRelationship?.type.endsWith("/drawing")) continue;
      const drawingRelsPath = relationshipPath(drawingRelationship.target);
      attachments.push({
        drawingPath: drawingRelationship.target,
        drawingRelsPath: archive[drawingRelsPath] ? drawingRelsPath : null,
        mediaPaths: []
      });
    }
    origins.set(chartsheet.index, { attachments, workbookSheetIndex: chartsheet.workbookSheetIndex });
  }
  return origins;
}

// src/charts.ts
import { strFromU8 as strFromU83, strToU8 as strToU82 } from "fflate";
var CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart";
var DRAWINGML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main";
var CHART_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart";
var CHART_EX_REL_TYPE = "http://schemas.microsoft.com/office/2014/relationships/chartEx";
var CHART_STYLE_REL_TYPE = "http://schemas.microsoft.com/office/2011/relationships/chartStyle";
var CHART_COLOR_STYLE_REL_TYPE = "http://schemas.microsoft.com/office/2011/relationships/chartColorStyle";
var SERIES_COLORS = [
  "#4472c4",
  "#ed7d31",
  "#a5a5a5",
  "#ffc000",
  "#5b9bd5",
  "#70ad47",
  "#264478",
  "#9e480e",
  "#636363",
  "#997300"
];
function quoteSeriesFormulaString(value) {
  return `"${value.replace(/"/g, '""')}"`;
}
function unquoteSeriesFormulaString(value) {
  const trimmed = value.trim();
  if (trimmed.length < 2 || !trimmed.startsWith('"') || !trimmed.endsWith('"')) {
    return null;
  }
  return trimmed.slice(1, -1).replace(/""/g, '"');
}
function splitTopLevelSeriesArguments(value) {
  const args = [];
  let current = "";
  let doubleQuoted = false;
  let singleQuoted = false;
  let depth = 0;
  for (let index = 0; index < value.length; index += 1) {
    const char = value[index] ?? "";
    const next = value[index + 1] ?? "";
    if (doubleQuoted) {
      current += char;
      if (char === '"' && next === '"') {
        current += next;
        index += 1;
      } else if (char === '"') {
        doubleQuoted = false;
      }
      continue;
    }
    if (singleQuoted) {
      current += char;
      if (char === "'" && next === "'") {
        current += next;
        index += 1;
      } else if (char === "'") {
        singleQuoted = false;
      }
      continue;
    }
    if (char === '"') {
      doubleQuoted = true;
      current += char;
      continue;
    }
    if (char === "'") {
      singleQuoted = true;
      current += char;
      continue;
    }
    if (char === "(") {
      depth += 1;
      current += char;
      continue;
    }
    if (char === ")") {
      depth = Math.max(0, depth - 1);
      current += char;
      continue;
    }
    if (char === "," && depth === 0) {
      args.push(current.trim());
      current = "";
      continue;
    }
    current += char;
  }
  args.push(current.trim());
  return args;
}
function readSeriesNameFormula(series) {
  const raw = series.raw && typeof series.raw === "object" ? series.raw : null;
  return typeof raw?.name === "string" && raw.name.length > 0 ? raw.name : null;
}
function buildChartSeriesFormula(chart, seriesIndex) {
  const series = chart?.series[seriesIndex];
  if (!chart || !series) {
    return "";
  }
  const nameFormula = readSeriesNameFormula(series);
  const nameArgument = nameFormula ?? quoteSeriesFormulaString(series.name ?? `Series ${seriesIndex + 1}`);
  const categoryArgument = series.categoriesRef?.formula ?? "";
  const valueArgument = series.valuesRef?.formula ?? "";
  const orderArgument = String(seriesIndex + 1);
  const bubbleArgument = series.bubbleSizeRef?.formula;
  return [
    `=SERIES(${nameArgument}`,
    categoryArgument,
    valueArgument,
    orderArgument,
    ...chart.chartType === "Bubble" || bubbleArgument ? [bubbleArgument ?? ""] : []
  ].join(",") + ")";
}
function parseChartSeriesFormula(formula, chart) {
  const trimmed = formula.trim();
  const withoutEquals = trimmed.startsWith("=") ? trimmed.slice(1).trim() : trimmed;
  const match = /^SERIES\s*\(([\s\S]*)\)$/i.exec(withoutEquals);
  if (!match) {
    return null;
  }
  const args = splitTopLevelSeriesArguments(match[1]);
  const isBubble = chart?.chartType === "Bubble";
  if (args.length < 4 || args.length > 5 || isBubble && args.length !== 5) {
    return null;
  }
  const [nameArg = "", categoryFormula = "", valueFormula = "", orderArg = "", bubbleSizeFormula] = args;
  if (!categoryFormula || !valueFormula) {
    return null;
  }
  const parsedOrder = Number(orderArg);
  if (!Number.isFinite(parsedOrder)) {
    return null;
  }
  const nameLiteral = unquoteSeriesFormulaString(nameArg);
  return {
    bubbleSizeFormula: bubbleSizeFormula && bubbleSizeFormula.length > 0 ? bubbleSizeFormula : void 0,
    categoryFormula,
    nameFormula: nameLiteral == null && nameArg.length > 0 ? nameArg : void 0,
    nameLiteral: nameLiteral ?? void 0,
    order: parsedOrder,
    valueFormula
  };
}
function applyChartSeriesFormula(chart, seriesIndex, formula, workbook) {
  const parsed = parseChartSeriesFormula(formula, chart);
  const currentSeries = chart.series[seriesIndex];
  if (!parsed || !currentSeries) {
    return null;
  }
  const categoriesRef = {
    ...currentSeries.categoriesRef ?? {},
    formula: parsed.categoryFormula,
    values: parsed.categoryFormula === currentSeries.categoriesRef?.formula ? currentSeries.categoriesRef.values : void 0
  };
  const valuesRef = {
    ...currentSeries.valuesRef ?? {},
    formula: parsed.valueFormula,
    values: parsed.valueFormula === currentSeries.valuesRef?.formula ? currentSeries.valuesRef.values : void 0
  };
  const bubbleSizeRef = chart.chartType === "Bubble" || parsed.bubbleSizeFormula ? {
    ...currentSeries.bubbleSizeRef ?? {},
    formula: parsed.bubbleSizeFormula,
    values: parsed.bubbleSizeFormula === currentSeries.bubbleSizeRef?.formula ? currentSeries.bubbleSizeRef?.values : void 0
  } : currentSeries.bubbleSizeRef ?? null;
  const isUnresolved = (formula2) => Boolean(
    workbook && formula2 && !resolveReferenceSheet(workbook, chart.workbookSheetIndex, formula2).sheet
  );
  const resolveEditedReference = (reference, currentReference, currentValues, mode) => {
    if (!workbook) return currentValues;
    if (reference?.formula === currentReference?.formula && isUnresolved(reference?.formula)) return currentValues;
    return resolveReferenceValues(workbook, chart.workbookSheetIndex, reference, mode);
  };
  const raw = {
    ...currentSeries.raw ?? {},
    unresolvedCategoriesReference: isUnresolved(categoriesRef.formula),
    unresolvedValuesReference: isUnresolved(valuesRef.formula),
    unresolvedBubbleSizeReference: isUnresolved(bubbleSizeRef?.formula),
    unresolvedNameReference: isUnresolved(parsed.nameFormula)
  };
  if (parsed.nameFormula) {
    raw.name = parsed.nameFormula;
  } else {
    delete raw.name;
  }
  const categories = resolveEditedReference(categoriesRef, currentSeries.categoriesRef, currentSeries.categories, "category");
  raw.chartCategoryReferenceValues = categories;
  raw.chartCategoryNumericValues = workbook ? resolveReferenceValues(workbook, chart.workbookSheetIndex, categoriesRef, "value") : currentSeries.raw?.chartCategoryNumericValues;
  const nextSeries = {
    ...currentSeries,
    bubbleSizeRef,
    bubbleSizes: resolveEditedReference(bubbleSizeRef, currentSeries.bubbleSizeRef, currentSeries.bubbleSizes ?? [], "value").map((value) => typeof value === "number" && Number.isFinite(value) ? value : null),
    categories,
    categoriesRef,
    name: parsed.nameLiteral ?? (parsed.nameFormula === currentSeries.raw?.name && isUnresolved(parsed.nameFormula) ? currentSeries.name : parsed.nameFormula && workbook ? resolveSeriesName(workbook, chart.workbookSheetIndex, parsed.nameFormula) : parsed.nameFormula ?? currentSeries.name),
    raw,
    values: resolveEditedReference(valuesRef, currentSeries.valuesRef, currentSeries.values, "value").map((value) => typeof value === "number" && Number.isFinite(value) ? value : null),
    valuesRef
  };
  const hierarchy = currentSeries.raw?.chartHierarchyCategories;
  if (hierarchy) {
    const changedReference = categoriesRef.formula !== currentSeries.categoriesRef?.formula;
    const resolvedHierarchy = changedReference ? buildEditedChartHierarchy(nextSeries) : hydrateChartHierarchy(nextSeries, hierarchy);
    if (resolvedHierarchy) {
      raw.chartHierarchyCategories = resolvedHierarchy;
      nextSeries.categories = resolvedHierarchy.map((point) => point?.find((entry) => entry.level === 0)?.label ?? null);
    } else delete raw.chartHierarchyCategories;
  }
  const sourceSeries = chart.raw?.officeSourceSeries;
  return {
    ...chart,
    raw: sourceSeries ? { ...chart.raw, officeSourceSeries: sourceSeries.map((series) => series.id === currentSeries.id ? nextSeries : series) } : chart.raw,
    series: chart.series.map((series, index) => index === seriesIndex ? nextSeries : series),
    typeGroups: chart.typeGroups?.map((group) => ({
      ...group,
      series: group.series.map((series) => series.id === currentSeries.id ? nextSeries : series)
    }))
  };
}
function normalizeWorksheetVisibility(value) {
  return value === "hidden" || value === "veryHidden" ? value : "visible";
}
var EMU_PER_PIXEL2 = 9525;
var THEME_COLOR_INDEX_BY_NAME = {
  accent1: 4,
  accent2: 5,
  accent3: 6,
  accent4: 7,
  accent5: 8,
  accent6: 9,
  dk1: 1,
  dk2: 3,
  folHlink: 11,
  hlink: 10,
  lt1: 0,
  lt2: 2,
  tx1: 1,
  tx2: 3,
  bg1: 0,
  bg2: 2
};
var PRIMARY_CHART_TYPE_LOCAL_NAMES = [
  "barChart",
  "lineChart",
  "line3DChart",
  "stockChart",
  "radarChart",
  "scatterChart",
  "pieChart",
  "pie3DChart",
  "doughnutChart",
  "areaChart",
  "area3DChart",
  "bar3DChart",
  "ofPieChart",
  "bubbleChart",
  "surfaceChart",
  "surface3DChart"
];
function clampUnitInterval(value) {
  return Math.max(0, Math.min(1, value));
}
function isElementNode2(node) {
  return node != null && node.nodeType === 1;
}
function normalizeHexColor3(value) {
  const hex = value.replace(/^#/, "");
  if (hex.length === 8) {
    return `#${hex.slice(2).toLowerCase()}`;
  }
  if (hex.length === 6) {
    return `#${hex.toLowerCase()}`;
  }
  return null;
}
function resolveColorFromXmlFragment(fragment, themePalette) {
  if (!fragment) {
    return void 0;
  }
  const srgbMatch = fragment.match(/<a:srgbClr\b[^>]*\bval="([0-9a-fA-F]{6,8})"/i);
  if (srgbMatch?.[1]) {
    return normalizeHexColor3(srgbMatch[1]) ?? void 0;
  }
  const schemeMatch = fragment.match(/<a:schemeClr\b[^>]*\bval="([^"]+)"[^>]*>([\s\S]*?)<\/a:schemeClr>/i) ?? fragment.match(/<a:schemeClr\b[^>]*\bval="([^"]+)"[^>]*/i);
  if (!schemeMatch?.[1]) {
    return void 0;
  }
  const baseColor = resolveThemeColor(schemeMatch[1], themePalette);
  if (!baseColor) {
    return void 0;
  }
  const transforms = schemeMatch[2] ?? "";
  let lightnessModifier = 1;
  let lightnessOffset = 0;
  for (const match of transforms.matchAll(/<a:(lumMod|lumOff|tint|shade)\b[^>]*\bval="(-?\d+(?:\.\d+)?)"/gi)) {
    const transform = match[1]?.toLowerCase();
    const rawValue = Number(match[2] ?? Number.NaN);
    if (!transform || !Number.isFinite(rawValue)) {
      continue;
    }
    if (transform === "lummod") {
      lightnessModifier *= rawValue / 1e5;
    } else if (transform === "lumoff") {
      lightnessOffset += rawValue / 1e5;
    } else if (transform === "tint") {
      lightnessOffset += (1 - lightnessOffset) * (rawValue / 1e5);
    } else if (transform === "shade") {
      lightnessModifier *= rawValue / 1e5;
    }
  }
  return applyLightnessTransform(baseColor, lightnessModifier, lightnessOffset) ?? void 0;
}
function readHexColorFromXmlFragment(fragment, preferLine = false, themePalette) {
  const source = preferLine ? fragment.match(/<a:ln\b[\s\S]*?<\/a:ln>/i)?.[0] ?? "" : fragment.match(/<a:solidFill\b[\s\S]*?<\/a:solidFill>/i)?.[0] ?? "";
  return resolveColorFromXmlFragment(source, themePalette);
}
function parseFallbackSeriesStylesFromChartXml(chartXml, themePalette) {
  const seriesBlocks = chartXml.match(/<c:ser\b[\s\S]*?<\/c:ser>/gi) ?? [];
  if (seriesBlocks.length === 0) {
    return [];
  }
  return seriesBlocks.map((seriesBlock) => {
    const shapeBlock = seriesBlock.match(/<c:spPr\b[\s\S]*?<\/c:spPr>/i)?.[0] ?? "";
    return {
      color: readHexColorFromXmlFragment(shapeBlock, false, themePalette),
      lineColor: readHexColorFromXmlFragment(shapeBlock, true, themePalette)
    };
  });
}
function parseFallbackPointStylesFromChartXml(chartXml, themePalette) {
  const chartDocument = parseXml2(chartXml);
  if (chartDocument) {
    const parsedSeriesStyles = getLocalDescendants(chartDocument, "ser").map((seriesNode) => {
      const styles = [];
      for (const dataPointNode of getLocalChildren(seriesNode, "dPt")) {
        const indexValue = readChartNumericAttribute(dataPointNode, "idx");
        if (indexValue === void 0) {
          continue;
        }
        const shapeProperties = getFirstLocalChild(dataPointNode, "spPr");
        const lineStyle = resolveChartLineStyle(shapeProperties, themePalette);
        styles.push({
          color: resolveChartFillColor(shapeProperties, themePalette) ?? void 0,
          explosion: readChartNumericAttribute(dataPointNode, "explosion"),
          index: indexValue,
          lineColor: lineStyle.color ?? void 0
        });
      }
      return styles;
    });
    if (parsedSeriesStyles.some((styles) => styles.length > 0)) {
      return parsedSeriesStyles;
    }
  }
  const seriesBlocks = chartXml.match(/<c:ser\b[\s\S]*?<\/c:ser>/gi) ?? [];
  if (seriesBlocks.length === 0) {
    return [];
  }
  return seriesBlocks.map((seriesBlock) => {
    const pointBlocks = seriesBlock.match(/<c:dPt\b[\s\S]*?<\/c:dPt>/gi) ?? [];
    if (pointBlocks.length === 0) {
      return [];
    }
    const styles = [];
    for (const pointBlock of pointBlocks) {
      const indexMatch = pointBlock.match(/<c:idx\b[^>]*\bval="(-?\d+)"/i);
      const index = indexMatch?.[1] ? Number(indexMatch[1]) : Number.NaN;
      if (!Number.isFinite(index)) {
        continue;
      }
      const explosionMatch = pointBlock.match(/<c:explosion\b[^>]*\bval="(-?\d+(?:\.\d+)?)"/i);
      const explosionValue = explosionMatch?.[1] ? Number(explosionMatch[1]) : Number.NaN;
      styles.push({
        color: readHexColorFromXmlFragment(pointBlock, false, themePalette),
        explosion: Number.isFinite(explosionValue) ? explosionValue : void 0,
        index,
        lineColor: readHexColorFromXmlFragment(pointBlock, true, themePalette)
      });
    }
    return styles;
  });
}
function parseNumericPointCacheFromXmlFragment(fragment) {
  const pointMatches = Array.from(fragment.matchAll(/<c:pt\b[^>]*\bidx="(-?\d+)"[^>]*>[\s\S]*?<c:v>([^<]*)<\/c:v>[\s\S]*?<\/c:pt>/gi));
  if (pointMatches.length === 0) {
    return [];
  }
  const explicitPointCountMatch = fragment.match(/<c:ptCount\b[^>]*\bval="(\d+)"/i);
  const explicitPointCount = explicitPointCountMatch?.[1] ? Number(explicitPointCountMatch[1]) : Number.NaN;
  const maxIndex = pointMatches.reduce((max, match) => {
    const current = Number(match[1] ?? Number.NaN);
    return Number.isFinite(current) ? Math.max(max, current) : max;
  }, -1);
  const pointCount = Math.max(
    pointMatches.length,
    Number.isFinite(explicitPointCount) ? explicitPointCount : 0,
    maxIndex + 1
  );
  const values = Array.from({ length: pointCount }, () => null);
  for (const match of pointMatches) {
    const index = Number(match[1] ?? Number.NaN);
    const rawValue = (match[2] ?? "").trim();
    const numericValue = Number(rawValue);
    if (!Number.isFinite(index) || index < 0 || !Number.isFinite(numericValue)) {
      continue;
    }
    values[index] = numericValue;
  }
  return values;
}
function parseFallbackBubbleSizesFromChartXml(chartXml) {
  const seriesBlocks = chartXml.match(/<c:ser\b[\s\S]*?<\/c:ser>/gi) ?? [];
  if (seriesBlocks.length === 0) {
    return [];
  }
  return seriesBlocks.map((seriesBlock) => {
    const bubbleSizeBlock = seriesBlock.match(/<c:bubbleSize\b[\s\S]*?<\/c:bubbleSize>/i)?.[0] ?? "";
    if (!bubbleSizeBlock) {
      return [];
    }
    return parseNumericPointCacheFromXmlFragment(bubbleSizeBlock);
  });
}
function findPrimaryChartTypeNode(plotAreaNode) {
  if (!plotAreaNode) {
    return null;
  }
  for (const localName of PRIMARY_CHART_TYPE_LOCAL_NAMES) {
    const node = getLocalChildren(plotAreaNode, localName)[0];
    if (node) {
      return node;
    }
  }
  return null;
}
function resolveScatterChartType(scatterStyle) {
  switch (scatterStyle) {
    case "line":
    case "lineMarker":
      return "ScatterLines";
    case "smooth":
    case "smoothMarker":
      return "ScatterSmooth";
    default:
      return "Scatter";
  }
}
function parseHexColor2(color) {
  const normalized = normalizeHexColor3(color);
  if (!normalized) {
    return null;
  }
  const match = /^#([0-9a-f]{6})$/.exec(normalized);
  if (!match) {
    return null;
  }
  return [
    Number.parseInt(match[1].slice(0, 2), 16),
    Number.parseInt(match[1].slice(2, 4), 16),
    Number.parseInt(match[1].slice(4, 6), 16)
  ];
}
function rgbToHsl2(red, green, blue) {
  const normalizedRed = red / 255;
  const normalizedGreen = green / 255;
  const normalizedBlue = blue / 255;
  const max = Math.max(normalizedRed, normalizedGreen, normalizedBlue);
  const min = Math.min(normalizedRed, normalizedGreen, normalizedBlue);
  const lightness = (max + min) / 2;
  if (max === min) {
    return [0, 0, lightness];
  }
  const delta = max - min;
  const saturation = lightness > 0.5 ? delta / (2 - max - min) : delta / (max + min);
  let hue = 0;
  switch (max) {
    case normalizedRed:
      hue = (normalizedGreen - normalizedBlue) / delta + (normalizedGreen < normalizedBlue ? 6 : 0);
      break;
    case normalizedGreen:
      hue = (normalizedBlue - normalizedRed) / delta + 2;
      break;
    default:
      hue = (normalizedRed - normalizedGreen) / delta + 4;
      break;
  }
  return [hue / 6, saturation, lightness];
}
function hueToRgb2(p, q, t) {
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
function hslToRgb2(hue, saturation, lightness) {
  if (saturation === 0) {
    const gray = Math.round(lightness * 255);
    return [gray, gray, gray];
  }
  const q = lightness < 0.5 ? lightness * (1 + saturation) : lightness + saturation - lightness * saturation;
  const p = 2 * lightness - q;
  return [
    Math.round(hueToRgb2(p, q, hue + 1 / 3) * 255),
    Math.round(hueToRgb2(p, q, hue) * 255),
    Math.round(hueToRgb2(p, q, hue - 1 / 3) * 255)
  ];
}
function rgbToHex3(red, green, blue) {
  return `#${[red, green, blue].map((channel) => Math.max(0, Math.min(255, Math.round(channel))).toString(16).padStart(2, "0")).join("")}`;
}
function applyLightnessTransform(baseColor, modifier = 1, offset = 0) {
  const rgb = parseHexColor2(baseColor);
  if (!rgb) {
    return normalizeHexColor3(baseColor);
  }
  const [hue, saturation, lightness] = rgbToHsl2(rgb[0], rgb[1], rgb[2]);
  const nextLightness = clampUnitInterval(lightness * modifier + offset);
  const [nextRed, nextGreen, nextBlue] = hslToRgb2(hue, saturation, nextLightness);
  return rgbToHex3(nextRed, nextGreen, nextBlue);
}
function resolveThemeColor(name, themePalette) {
  if (!name) {
    return null;
  }
  const index = THEME_COLOR_INDEX_BY_NAME[name];
  return index === void 0 ? null : themePalette?.colorsByIndex[index] ?? null;
}
function resolveThemeTypeface(typeface, themePalette) {
  if (!typeface) {
    return null;
  }
  if (typeface === "+mn-lt" || typeface === "+mn-ea" || typeface === "+mn-cs") {
    return themePalette?.minorLatinFont ?? null;
  }
  if (typeface === "+mj-lt" || typeface === "+mj-ea" || typeface === "+mj-cs") {
    return themePalette?.majorLatinFont ?? null;
  }
  return typeface;
}
function readChartTextTypeface(textPropertiesNode, themePalette) {
  if (!textPropertiesNode) {
    return null;
  }
  const defaultRunProperties = getFirstLocalDescendant(textPropertiesNode, "defRPr") ?? getFirstLocalDescendant(textPropertiesNode, "rPr");
  if (!defaultRunProperties) {
    return null;
  }
  const typeface = getFirstLocalChild(defaultRunProperties, "latin")?.getAttribute("typeface") ?? getFirstLocalChild(defaultRunProperties, "ea")?.getAttribute("typeface") ?? getFirstLocalChild(defaultRunProperties, "cs")?.getAttribute("typeface") ?? null;
  const resolved = resolveThemeTypeface(typeface, themePalette)?.trim() ?? "";
  return resolved.length > 0 ? resolved : null;
}
function resolveChartColorNode(node, themePalette) {
  if (!node) {
    return null;
  }
  let baseColor = null;
  if (node.localName === "srgbClr") {
    baseColor = normalizeHexColor3(`#${node.getAttribute("val") ?? ""}`);
  } else if (node.localName === "schemeClr") {
    baseColor = resolveThemeColor(node.getAttribute("val"), themePalette);
  } else if (node.localName === "sysClr") {
    baseColor = normalizeHexColor3(`#${node.getAttribute("lastClr") ?? ""}`);
  }
  if (!baseColor) {
    return null;
  }
  let lightnessModifier = 1;
  let lightnessOffset = 0;
  for (const transformNode of Array.from(node.childNodes).filter(isElementNode2)) {
    const rawValue = Number(transformNode.getAttribute("val") ?? Number.NaN);
    if (!Number.isFinite(rawValue)) {
      continue;
    }
    if (transformNode.localName === "lumMod") {
      lightnessModifier *= rawValue / 1e5;
    } else if (transformNode.localName === "lumOff") {
      lightnessOffset += rawValue / 1e5;
    } else if (transformNode.localName === "tint") {
      lightnessOffset += (1 - lightnessOffset) * (rawValue / 1e5);
    } else if (transformNode.localName === "shade") {
      lightnessModifier *= rawValue / 1e5;
    }
  }
  return applyLightnessTransform(baseColor, lightnessModifier, lightnessOffset);
}
function isChartColorElement(node) {
  return Boolean(node && (node.localName === "schemeClr" || node.localName === "srgbClr" || node.localName === "sysClr"));
}
function findFirstChartColorElement(node) {
  if (!node) {
    return null;
  }
  if (isChartColorElement(node)) {
    return node;
  }
  for (const localName of ["srgbClr", "schemeClr", "sysClr"]) {
    for (const candidate of getLocalDescendants(node, localName)) {
      if (isChartColorElement(candidate)) {
        return candidate;
      }
    }
  }
  return null;
}
function resolveChartFillColor(shapeNode, themePalette) {
  if (!shapeNode || getFirstLocalChild(shapeNode, "noFill")) {
    return null;
  }
  const solidFill = getFirstLocalChild(shapeNode, "solidFill");
  if (solidFill) {
    const colorNode = findFirstChartColorElement(Array.from(solidFill.childNodes).find(isElementNode2) ?? null);
    return resolveChartColorNode(colorNode, themePalette);
  }
  const gradientFill = getFirstLocalChild(shapeNode, "gradFill");
  const gradientStops = gradientFill ? getLocalDescendants(gradientFill, "gs").map((stopNode) => ({
    colorNode: Array.from(stopNode.childNodes).find(isElementNode2) ?? null,
    position: Number(stopNode.getAttribute("pos") ?? Number.NaN)
  })).filter((stop) => Boolean(stop.colorNode)) : [];
  if (gradientStops.length === 0) {
    return null;
  }
  gradientStops.sort((left, right) => {
    const leftPos = Number.isFinite(left.position) ? left.position : 0;
    const rightPos = Number.isFinite(right.position) ? right.position : 0;
    return leftPos - rightPos;
  });
  const midpointStop = gradientStops.find((stop) => Number.isFinite(stop.position) && stop.position >= 5e4) ?? gradientStops[Math.floor(gradientStops.length / 2)] ?? gradientStops[0];
  return resolveChartColorNode(midpointStop.colorNode, themePalette);
}
function resolveChartLineStyle(shapeNode, themePalette) {
  const lineNode = shapeNode?.localName === "ln" ? shapeNode : shapeNode ? getFirstLocalChild(shapeNode, "ln") : null;
  if (!lineNode) {
    return { color: null, hidden: false, widthPx: void 0 };
  }
  if (getFirstLocalChild(lineNode, "noFill")) {
    return { color: null, hidden: true, widthPx: void 0 };
  }
  const solidFill = getFirstLocalChild(lineNode, "solidFill");
  const colorNode = solidFill ? findFirstChartColorElement(Array.from(solidFill.childNodes).find(isElementNode2) ?? null) : null;
  const widthValue = Number(lineNode.getAttribute("w") ?? Number.NaN);
  return {
    color: resolveChartColorNode(colorNode, themePalette),
    hidden: false,
    widthPx: Number.isFinite(widthValue) ? Math.max(1, widthValue / EMU_PER_PIXEL2) : void 0
  };
}
function normalizeLegend(raw) {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const legend = raw;
  return {
    overlay: typeof legend.overlay === "boolean" ? legend.overlay : void 0,
    position: typeof legend.position === "string" ? legend.position : void 0,
    raw: legend
  };
}
function normalizeLegendPosition(position) {
  if (!position) {
    return void 0;
  }
  switch (position) {
    case "bottom":
      return "b";
    case "left":
      return "l";
    case "right":
      return "r";
    case "top":
      return "t";
    default:
      return position;
  }
}
function readChartNumericAttribute(parent, localName) {
  const node = parent ? getFirstLocalChild(parent, localName) : null;
  const value = Number(node?.getAttribute("val") ?? Number.NaN);
  return Number.isFinite(value) ? value : void 0;
}
function readChartBooleanAttribute(parent, localName) {
  const node = parent ? getFirstLocalChild(parent, localName) : null;
  if (!node) {
    return void 0;
  }
  const rawValue = node.getAttribute("val");
  if (rawValue == null) {
    return true;
  }
  if (rawValue === "1" || rawValue === "true") {
    return true;
  }
  if (rawValue === "0" || rawValue === "false") {
    return false;
  }
  return void 0;
}
function readChartLabelFontSizePt(textPropertiesNode) {
  if (!textPropertiesNode) {
    return void 0;
  }
  const runPropertiesNode = getFirstLocalDescendant(textPropertiesNode, "defRPr") ?? getFirstLocalDescendant(textPropertiesNode, "rPr");
  const rawSize = Number(runPropertiesNode?.getAttribute("sz") ?? Number.NaN);
  if (!Number.isFinite(rawSize) || rawSize <= 0) {
    return void 0;
  }
  return rawSize / 100;
}
function parseChartPointDataLabelsFromXml(labelsNode) {
  const fallbackFontSizePt = readChartLabelFontSizePt(getFirstLocalChild(labelsNode, "txPr"));
  const labels = [];
  for (const pointLabelNode of getLocalChildren(labelsNode, "dLbl")) {
    const index = readChartNumericAttribute(pointLabelNode, "idx");
    if (typeof index !== "number" || !Number.isFinite(index)) {
      continue;
    }
    const layoutNode = getFirstLocalChild(pointLabelNode, "layout");
    const manualLayoutNode = layoutNode ? getFirstLocalChild(layoutNode, "manualLayout") : null;
    labels.push({
      deleted: readChartBooleanAttribute(pointLabelNode, "delete"),
      fontSizePt: readChartLabelFontSizePt(getFirstLocalChild(pointLabelNode, "txPr")) ?? fallbackFontSizePt,
      index,
      showBubbleSize: readChartBooleanAttribute(pointLabelNode, "showBubbleSize"),
      showCategoryName: readChartBooleanAttribute(pointLabelNode, "showCatName"),
      showPercent: readChartBooleanAttribute(pointLabelNode, "showPercent"),
      showSeriesName: readChartBooleanAttribute(pointLabelNode, "showSerName"),
      showValue: readChartBooleanAttribute(pointLabelNode, "showVal"),
      x: readChartNumericAttribute(manualLayoutNode, "x"),
      y: readChartNumericAttribute(manualLayoutNode, "y")
    });
  }
  return labels;
}
function parseChartDataLabelsFromXml(labelsNode) {
  if (!labelsNode) {
    return null;
  }
  const pointLabels = parseChartPointDataLabelsFromXml(labelsNode);
  const labels = {
    pointLabels: pointLabels.length > 0 ? pointLabels : void 0,
    raw: {},
    showBubbleSize: readChartBooleanAttribute(labelsNode, "showBubbleSize"),
    showCategoryName: readChartBooleanAttribute(labelsNode, "showCatName"),
    showLegendKey: readChartBooleanAttribute(labelsNode, "showLegendKey"),
    showPercent: readChartBooleanAttribute(labelsNode, "showPercent"),
    showSeriesName: readChartBooleanAttribute(labelsNode, "showSerName"),
    showValue: readChartBooleanAttribute(labelsNode, "showVal")
  };
  const hasValue = labels.showBubbleSize !== void 0 || labels.showCategoryName !== void 0 || labels.showLegendKey !== void 0 || labels.showPercent !== void 0 || (labels.pointLabels?.length ?? 0) > 0 || labels.showSeriesName !== void 0 || labels.showValue !== void 0;
  return hasValue ? labels : null;
}
function readChartRelationships(archive, chartPath) {
  const relsPath = normalizeArchivePath2(`${dirname2(chartPath)}/_rels/${chartPath.split("/").pop()}.rels`);
  const relsXml = readArchiveText2(archive, relsPath);
  if (!relsXml) {
    return /* @__PURE__ */ new Map();
  }
  const relsDocument = parseXml2(relsXml);
  if (!relsDocument) {
    return /* @__PURE__ */ new Map();
  }
  const relationships = /* @__PURE__ */ new Map();
  for (const relationshipNode of getLocalDescendants(relsDocument, "Relationship")) {
    const type = relationshipNode.getAttribute("Type");
    const target = relationshipNode.getAttribute("Target");
    if (!type || !target || relationshipNode.getAttribute("TargetMode") === "External") {
      continue;
    }
    relationships.set(type, resolveRelationshipPath(relsPath, target));
  }
  return relationships;
}
function readChartImages(archive, chartPath) {
  if (!chartPath || typeof btoa !== "function") return void 0;
  const relsPath = normalizeArchivePath2(`${dirname2(chartPath)}/_rels/${chartPath.split("/").pop()}.rels`);
  const document2 = parseXml2(readArchiveText2(archive, relsPath) ?? "");
  const images = /* @__PURE__ */ Object.create(null);
  for (const relationship of getLocalDescendants(document2, "Relationship")) {
    const id = relationship.getAttribute("Id");
    const target = relationship.getAttribute("Target");
    if (!id || !target || relationship.getAttribute("TargetMode") === "External" || !relationship.getAttribute("Type")?.endsWith("/image")) continue;
    const bytes = archive[resolveRelationshipPath(relsPath, target)];
    if (!bytes?.length || bytes.length > 72 * 1024 * 1024) continue;
    const signature = String.fromCharCode(...bytes.subarray(0, 12));
    const mime = bytes[0] === 137 && signature.slice(1, 4) === "PNG" ? "image/png" : bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255 ? "image/jpeg" : signature.startsWith("GIF87a") || signature.startsWith("GIF89a") ? "image/gif" : signature.startsWith("RIFF") && signature.slice(8, 12) === "WEBP" ? "image/webp" : signature.startsWith("BM") ? "image/bmp" : signature.startsWith("II*\0") || signature.startsWith("MM\0*") ? "image/tiff" : null;
    if (!mime) continue;
    const chunks = [];
    for (let index = 0; index < bytes.length; index += 32768) {
      chunks.push(String.fromCharCode(...bytes.subarray(index, index + 32768)));
    }
    images[id] = `data:${mime};base64,${btoa(chunks.join(""))}`;
  }
  return Object.keys(images).length > 0 ? images : void 0;
}
function readChartDrawings(archive, chartPath) {
  if (!chartPath) return void 0;
  const relsPath = normalizeArchivePath2(`${dirname2(chartPath)}/_rels/${chartPath.split("/").pop()}.rels`);
  const document2 = parseXml2(readArchiveText2(archive, relsPath) ?? "");
  const drawings = /* @__PURE__ */ Object.create(null);
  for (const relationship of getLocalDescendants(document2, "Relationship")) {
    const id = relationship.getAttribute("Id");
    const target = relationship.getAttribute("Target");
    if (!id || !target || relationship.getAttribute("TargetMode") === "External" || !relationship.getAttribute("Type")?.endsWith("/chartUserShapes")) continue;
    const path = resolveRelationshipPath(relsPath, target);
    if (!archive[path]?.length || archive[path].length > 8 * 1024 * 1024) continue;
    const xml = readArchiveText2(archive, path);
    if (xml) drawings[id] = { xml, images: readChartImages(archive, path) };
  }
  return Object.keys(drawings).length ? drawings : void 0;
}
function readChartColorPalette(archive, colorStylePath, themePalette) {
  const colorStyleXml = readArchiveText2(archive, colorStylePath);
  if (!colorStyleXml) {
    return [];
  }
  const colorStyleDocument = parseXml2(colorStyleXml);
  if (!colorStyleDocument?.documentElement) {
    return [];
  }
  return Array.from(colorStyleDocument.documentElement.childNodes).filter((child) => isElementNode2(child) && child.localName !== "variation").map((child) => resolveChartColorNode(child, themePalette) ?? resolveChartColorNode(findFirstChartColorElement(child), themePalette)).filter((color) => typeof color === "string");
}
function readChartStyleAppearance(archive, stylePath, themePalette) {
  const styleXml = readArchiveText2(archive, stylePath);
  if (!styleXml) {
    return {};
  }
  const styleDocument = parseXml2(styleXml);
  if (!styleDocument) {
    return {};
  }
  const dataPointNode = getFirstLocalDescendant(styleDocument, "dataPoint");
  const fillRefNode = dataPointNode ? getFirstLocalChild(dataPointNode, "fillRef") : null;
  const index = Number(fillRefNode?.getAttribute("idx") ?? Number.NaN);
  const chartAreaNode = getFirstLocalDescendant(styleDocument, "chartArea");
  const chartAreaShapeProperties = chartAreaNode ? getFirstLocalChild(chartAreaNode, "spPr") : null;
  const chartAreaFontRef = chartAreaNode ? getFirstLocalChild(chartAreaNode, "fontRef") : null;
  const chartAreaFontColor = chartAreaFontRef ? resolveChartColorNode(Array.from(chartAreaFontRef.childNodes).find(isElementNode2) ?? null, themePalette) : null;
  const titleNode = getFirstLocalDescendant(styleDocument, "title");
  const titleFontRef = titleNode ? getFirstLocalChild(titleNode, "fontRef") : null;
  const titleColor = titleFontRef ? resolveChartColorNode(Array.from(titleFontRef.childNodes).find(isElementNode2) ?? null, themePalette) : null;
  const axisStyleNode = getFirstLocalDescendant(styleDocument, "categoryAxis") ?? getFirstLocalDescendant(styleDocument, "valueAxis");
  const axisShapeProperties = axisStyleNode ? getFirstLocalChild(axisStyleNode, "spPr") : null;
  const axisFontRef = axisStyleNode ? getFirstLocalChild(axisStyleNode, "fontRef") : null;
  const chartAreaNoFill = chartAreaShapeProperties ? getFirstLocalChild(chartAreaShapeProperties, "noFill") != null : false;
  return {
    axisLabelColor: axisFontRef ? resolveChartColorNode(Array.from(axisFontRef.childNodes).find(isElementNode2) ?? null, themePalette) ?? void 0 : void 0,
    axisLineColor: resolveChartLineStyle(axisShapeProperties, themePalette).color ?? void 0,
    chartAreaBorderColor: resolveChartLineStyle(chartAreaShapeProperties, themePalette).color ?? void 0,
    chartAreaFillColor: resolveChartFillColor(chartAreaShapeProperties, themePalette) ?? void 0,
    chartAreaNoFill,
    paletteOffset: Number.isFinite(index) ? index : void 0,
    textColor: chartAreaFontColor ?? void 0,
    titleColor: titleColor ?? chartAreaFontColor ?? void 0
  };
}
function buildThemeSeriesPalette(themePalette) {
  const themeColors = [4, 5, 6, 7, 8, 9].map((index) => themePalette?.colorsByIndex[index] ?? null).filter((color) => Boolean(color));
  return themeColors.length > 0 ? themeColors : SERIES_COLORS;
}
function applyBuiltinSurfaceDefaults(chart, themePalette) {
  if (chart.chartType !== "Surface") {
    return;
  }
  const builtin = chart.raw?.hasCustomChartColorStyle !== true ? getBuiltinChartSurfaceStyle(chart.chartStyleId) : void 0;
  const colors = themePalette?.colorsByIndex ?? {};
  const wallFill = resolveBuiltinChartColor(builtin?.wall.fill, colors) ?? (chart.wireframe ? "#d0d0d0" : "#d9d9df");
  const floorFill = resolveBuiltinChartColor(builtin?.floor.fill, colors) ?? wallFill;
  const gridlineColor = resolveBuiltinChartColor(builtin?.majorGridline, colors);
  for (const axis of [chart.categoryAxis, chart.valueAxis, chart.seriesAxis]) {
    if (axis && !axis.majorGridlineColor) axis.majorGridlineColor = gridlineColor;
  }
  const wallLine = chart.wireframe ? "#a6a6a6" : "#a8adb7";
  const previousDefaults = chart.raw?.builtinSurfaceDefaults;
  const nextDefaults = {};
  for (const key of ["floor", "sideWall", "backWall"]) {
    const wall = chart[key] ?? {};
    const previous = previousDefaults?.[key];
    const fillIsDefault = wall.fillColor === void 0 || wall.fillColor === previous?.fillColor;
    const lineIsDefault = wall.lineColor === void 0 || wall.lineColor === previous?.lineColor;
    const fillColor = fillIsDefault ? key === "floor" ? floorFill : wallFill : wall.fillColor;
    const lineColor = lineIsDefault ? wallLine : wall.lineColor;
    chart[key] = { ...wall, fillColor, lineColor };
    nextDefaults[key] = {
      fillColor: fillIsDefault ? fillColor : void 0,
      lineColor: lineIsDefault ? lineColor : void 0
    };
  }
  chart.raw = { ...chart.raw, builtinSurfaceDefaults: nextDefaults };
  if (!chart.surfaceMaterial && chart.wireframe !== true) {
    chart.surfaceMaterial = "matte";
  }
}
function applyBuiltinChartDefaults(chart, themePalette) {
  const darkBuiltInStyle = typeof chart.chartStyleId === "number" && chart.chartStyleId >= 140 && chart.chartStyleId < 150;
  const textColor = themePalette?.colorsByIndex[1] ?? themePalette?.colorsByIndex[3] ?? null;
  const minorTypeface = themePalette?.minorLatinFont?.trim() || void 0;
  const derivedAxisColor = textColor ? applyLightnessTransform(textColor, 0.35, 0.55) : null;
  const derivedBorderColor = textColor ? applyLightnessTransform(textColor, chart.is3d ? 0.28 : 0.22, chart.is3d ? 0.6 : 0.7) : null;
  if (darkBuiltInStyle) {
    chart.chartAreaFillColor = chart.chartAreaFillColor ?? "#1f1f1f";
    chart.chartAreaBorderColor = chart.chartAreaBorderColor ?? "#1f1f1f";
    chart.textColor = chart.textColor ?? "#f5f5f5";
    chart.titleColor = chart.titleColor ?? "#f5f5f5";
    chart.axisLabelColor = chart.axisLabelColor ?? "#d9d9d9";
    chart.axisLineColor = chart.axisLineColor ?? "#8c8c8c";
  }
  chart.chartAreaBorderColor = chart.chartAreaBorderColor ?? derivedBorderColor ?? void 0;
  chart.textColor = chart.textColor ?? textColor ?? void 0;
  chart.titleColor = chart.titleColor ?? textColor ?? void 0;
  chart.axisLabelColor = chart.axisLabelColor ?? derivedAxisColor ?? textColor ?? void 0;
  chart.axisLineColor = chart.axisLineColor ?? derivedAxisColor ?? textColor ?? void 0;
  chart.fontFamily = chart.fontFamily ?? minorTypeface;
  chart.titleFontFamily = chart.titleFontFamily ?? chart.fontFamily ?? minorTypeface;
  const themeColors = themePalette?.colorsByIndex;
  const useBuiltin = chart.raw?.hasCustomChartColorStyle !== true && themeColors && getBuiltinChartColor(chart.chartStyleId, 0, 1) !== void 0;
  const colorCount = Math.max(1, chart.series.length, chart.typeGroups?.reduce((total, group) => total + group.series.length, 0) ?? 0);
  const seriesPalette = useBuiltin && chart.chartType !== "Surface" ? Array.from({ length: colorCount }, (_, index) => resolveBuiltinChartColor(getBuiltinChartColor(chart.chartStyleId, index, colorCount), themeColors) ?? SERIES_COLORS[index % SERIES_COLORS.length]) : chart.chartColorPalette?.length ? chart.chartColorPalette : buildThemeSeriesPalette(themePalette);
  chart.chartColorPalette = seriesPalette;
  chart.raw = { ...chart.raw, builtinThemeColors: useBuiltin ? themeColors : void 0 };
  const applySeriesDefaults = (series, index) => {
    const fallbackColor = seriesPalette[index % seriesPalette.length];
    const properties = series.shapeProperties ?? {};
    const previous = properties.builtinDefaultColors;
    const generated = {};
    const resolveColor = (key, explicit, fallback) => {
      const value = series[key];
      if (!explicit && (value == null || value === previous?.[key] || (key === "color" || key === "lineColor") && useBuiltin && chart.raw?.xmlChartType)) {
        generated[key] = fallback;
        return fallback;
      }
      return value ?? fallback;
    };
    const explicitFill = properties.xmlFillColor ?? properties.solidFillHex ?? properties.xmlFillHidden;
    const explicitLine = properties.xmlLineColor ?? properties.lineColorHex ?? properties.xmlLineHidden;
    const color = explicitFill ? series.color ?? series.lineColor ?? fallbackColor : explicitLine ? series.lineColor ?? series.color ?? fallbackColor : resolveColor("color", false, fallbackColor);
    const lineColor = explicitLine ? series.lineColor ?? color : explicitFill ? color : resolveColor("lineColor", false, color ?? fallbackColor);
    const markerColor = resolveColor("markerColor", properties.xmlMarkerFillColor ?? properties.xmlMarkerFillHidden, color ?? lineColor ?? fallbackColor);
    const markerLineColor = resolveColor("markerLineColor", properties.xmlMarkerLineColor ?? properties.xmlMarkerLineHidden, lineColor ?? color ?? fallbackColor);
    return {
      ...series,
      color,
      lineColor,
      markerColor,
      markerLineColor,
      shapeProperties: { ...properties, builtinDefaultColors: generated }
    };
  };
  chart.series = chart.series.map(applySeriesDefaults);
  const canonicalSeries = chart.id.startsWith("chart-ex-") ? null : new Map(chart.series.map((series) => [series.id, series]));
  let groupSeriesOffset = 0;
  chart.typeGroups = chart.typeGroups?.map((group) => {
    const series = group.series.map((entry, index) => canonicalSeries?.get(entry.id) ?? applySeriesDefaults(entry, groupSeriesOffset + index));
    groupSeriesOffset += group.series.length;
    return { ...group, series };
  });
  applyBuiltinSurfaceDefaults(chart, themePalette);
}
function parseChartPointStyles(seriesNode, themePalette) {
  const pointStyles = [];
  for (const dataPointNode of getLocalChildren(seriesNode, "dPt")) {
    const indexValue = readChartNumericAttribute(dataPointNode, "idx");
    if (indexValue === void 0) {
      continue;
    }
    const shapeProperties = getFirstLocalChild(dataPointNode, "spPr");
    const lineStyle = resolveChartLineStyle(shapeProperties, themePalette);
    pointStyles.push({
      color: resolveChartFillColor(shapeProperties, themePalette) ?? void 0,
      explosion: readChartNumericAttribute(dataPointNode, "explosion"),
      index: indexValue,
      lineColor: lineStyle.color ?? void 0
    });
  }
  return pointStyles;
}
function parseInvertNegativeStyle(seriesNode, themePalette) {
  const invertNode = getFirstLocalDescendant(seriesNode, "invertSolidFillFmt");
  const shapeProperties = invertNode ? getFirstLocalChild(invertNode, "spPr") : null;
  if (!shapeProperties) {
    return {
      color: void 0,
      lineColor: void 0
    };
  }
  const lineStyle = resolveChartLineStyle(shapeProperties, themePalette);
  return {
    color: resolveChartFillColor(shapeProperties, themePalette) ?? void 0,
    lineColor: lineStyle.color ?? void 0
  };
}
function parseChartCacheValues(parentNode, cacheName, mode) {
  if (!parentNode) {
    return null;
  }
  const referenceNode = getFirstLocalChild(parentNode, "numRef") ?? getFirstLocalChild(parentNode, "strRef") ?? parentNode;
  const cacheNode = getFirstLocalChild(referenceNode, cacheName) ?? getFirstLocalChild(parentNode, cacheName === "numCache" ? "numLit" : "strLit");
  if (!cacheNode) {
    return null;
  }
  const pointCount = readChartNumericAttribute(cacheNode, "ptCount");
  const pointNodes = getLocalChildren(cacheNode, "pt").map((pointNode) => {
    const rawIndex = Number(pointNode.getAttribute("idx") ?? Number.NaN);
    return {
      index: Number.isFinite(rawIndex) ? rawIndex : 0,
      value: getFirstLocalChild(pointNode, "v")?.textContent ?? ""
    };
  }).sort((left, right) => left.index - right.index);
  if (pointNodes.length === 0) {
    return null;
  }
  const maxIndex = pointNodes.reduce((max, point) => Math.max(max, point.index), 0);
  const targetLength = Math.max(
    pointNodes.length,
    Number.isFinite(pointCount ?? Number.NaN) ? Number(pointCount) : 0,
    maxIndex + 1
  );
  const values = Array.from({ length: targetLength }, () => null);
  for (const point of pointNodes) {
    if (mode === "value") {
      values[point.index] = cellValueToNumber(point.value);
    } else {
      values[point.index] = point.value.length > 0 ? point.value : null;
    }
  }
  return values;
}
function parseChartHierarchyCategories(parentNode) {
  const referenceNode = getFirstLocalChild(parentNode, "multiLvlStrRef");
  const cacheNode = getFirstLocalChild(referenceNode, "multiLvlStrCache");
  if (!cacheNode) return void 0;
  const pointCount = readChartNumericAttribute(cacheNode, "ptCount");
  const categories = new Array(
    Number.isSafeInteger(pointCount) && pointCount >= 0 && pointCount <= 1048576 ? pointCount : 0
  );
  getLocalChildren(cacheNode, "lvl").forEach((levelNode, level) => {
    for (const point of getLocalChildren(levelNode, "pt")) {
      const index = Number(point.getAttribute("idx") ?? Number.NaN);
      if (!Number.isSafeInteger(index) || index < 0 || index > 1048575) continue;
      (categories[index] ??= []).push({ level, label: getFirstLocalChild(point, "v")?.textContent ?? "" });
    }
  });
  return categories;
}
function hydrateChartHierarchy(series, hierarchy) {
  const formula = series.categoriesRef?.formula;
  if (!formula || series.raw?.unresolvedCategoriesReference) return hierarchy;
  const range = parseA1Range(splitSheetReference(formula)?.range ?? formula);
  if (!range) return hierarchy;
  const rows = range.end.row - range.start.row + 1;
  const columns = range.end.col - range.start.col + 1;
  const levels = hierarchy.reduce((count, point) => Math.max(count, ...point.map((entry) => entry.level + 1)), 0);
  const referenceValues = series.raw?.chartCategoryReferenceValues ?? series.categories;
  if (referenceValues.length !== rows * columns || levels !== columns && levels !== rows) return hierarchy;
  const pointsByRow = levels === columns && (rows === series.values.length || rows === hierarchy.length);
  const pointsByColumn = levels === rows && (columns === series.values.length || columns === hierarchy.length);
  if (!pointsByRow && !pointsByColumn) return hierarchy;
  const previous = /* @__PURE__ */ new Map();
  return Array.from({ length: pointsByRow ? rows : columns }, (_, index) => {
    const cached = hierarchy[index] ?? [];
    const entries = [];
    let changedParent = false;
    for (let level = levels - 1; level >= 0; level -= 1) {
      const offset = pointsByRow ? index * columns + columns - 1 - level : (rows - 1 - level) * columns + index;
      const value = referenceValues[offset];
      const explicit = cached.some((entry) => entry.level === level);
      if (level > 0 && (value == null || value === "") && !explicit) continue;
      const label = String(value ?? "");
      if (level === 0 || explicit || changedParent || previous.get(level) !== label) {
        entries.push({ level, label });
        changedParent = true;
      }
      previous.set(level, label);
    }
    return entries.sort((a, b) => a.level - b.level);
  });
}
function buildEditedChartHierarchy(series) {
  const formula = series.categoriesRef?.formula;
  if (!formula || series.raw?.unresolvedCategoriesReference) return void 0;
  const range = parseA1Range(splitSheetReference(formula)?.range ?? formula);
  if (!range) return void 0;
  const rows = range.end.row - range.start.row + 1;
  const columns = range.end.col - range.start.col + 1;
  const values = series.raw?.chartCategoryReferenceValues;
  if (!values || values.length !== rows * columns || rows < 2 || columns < 2) return void 0;
  const byRow = rows === series.values.length;
  if (!byRow && columns !== series.values.length) return void 0;
  const levelCount = byRow ? columns : rows;
  const previous = /* @__PURE__ */ new Map();
  return Array.from({ length: series.values.length }, (_, index) => {
    const entries = [];
    let changedParent = false;
    for (let level = levelCount - 1; level >= 0; level -= 1) {
      const offset = byRow ? index * columns + columns - 1 - level : (rows - 1 - level) * columns + index;
      const value = values[offset];
      if (level > 0 && value == null) continue;
      const label = String(value ?? "");
      if (level === 0 || index === 0 || changedParent || previous.get(level) !== label) {
        entries.push({ level, label });
        changedParent = true;
      }
      previous.set(level, label);
    }
    return entries.sort((a, b) => a.level - b.level);
  });
}
function parseChartMultiLevelCacheValues(parentNode, mode) {
  const hierarchy = parseChartHierarchyCategories(parentNode);
  if (!hierarchy?.length) return null;
  return Array.from({ length: hierarchy.length }, (_, index) => {
    const label = hierarchy[index]?.find((entry) => entry.level === 0)?.label;
    return mode === "value" ? cellValueToNumber(label) : label || null;
  });
}
function chartReferenceFromXml(parentNode, mode) {
  if (!parentNode) return null;
  const formula = getFirstLocalDescendant(parentNode, "f")?.textContent ?? void 0;
  const values = parseChartCacheValues(parentNode, "numCache", mode) ?? parseChartCacheValues(parentNode, "strCache", mode) ?? parseChartMultiLevelCacheValues(parentNode, mode) ?? [];
  return { formula, values, refType: formula ? "formula" : mode === "value" ? "numbers" : "strings" };
}
function createArchiveChartReferenceResolver(archive) {
  const documents = /* @__PURE__ */ new Map();
  const read = (path) => {
    if (!documents.has(path)) documents.set(path, parseXml2(readArchiveText2(archive, path) ?? ""));
    return documents.get(path) ?? null;
  };
  const cellsByPath = /* @__PURE__ */ new Map();
  let sharedStrings;
  const external = (reference, mode) => {
    const split = splitSheetReference(reference?.formula?.trim().replace(/^=/, "") ?? "");
    const link = /^\[(\d+)\](.+)$/.exec(split?.sheetName ?? "");
    const range = split ? parseA1Range(split.range) : null;
    if (!link || !range || Number(link[1]) < 1 || range.end.row >= 1048576 || range.end.col >= 16384 || (range.end.row - range.start.row + 1) * (range.end.col - range.start.col + 1) > 1048576) return null;
    const rootRelationships = getLocalDescendants(read("_rels/.rels"), "Relationship");
    const rootTarget = rootRelationships.find((node) => node.getAttribute("Type")?.endsWith("/officeDocument"))?.getAttribute("Target");
    const workbookPath = rootTarget ? resolveRelationshipPath("workbook.xml", rootTarget) : "xl/workbook.xml";
    const workbookDocument = read(workbookPath);
    const referenceNode = getLocalDescendants(workbookDocument, "externalReference")[Number(link[1]) - 1];
    const id = referenceNode?.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id") ?? referenceNode?.getAttribute("r:id");
    const relsPath = `${dirname2(workbookPath)}/_rels/${workbookPath.split("/").pop()}.rels`;
    const relationship = getLocalDescendants(read(relsPath), "Relationship").find((node) => node.getAttribute("Id") === id && node.getAttribute("Type")?.endsWith("/externalLink") && node.getAttribute("TargetMode") !== "External");
    const target = relationship?.getAttribute("Target");
    if (!target) return null;
    const path = resolveRelationshipPath(relsPath, target);
    const book = getFirstLocalChild(read(path)?.documentElement ?? null, "externalBook");
    const names = getLocalChildren(getFirstLocalChild(book, "sheetNames"), "sheetName");
    const sheetId = names.findIndex((node) => node.getAttribute("val")?.toLowerCase() === link[2].toLowerCase());
    if (sheetId < 0) return null;
    const sheet = getLocalChildren(getFirstLocalChild(book, "sheetDataSet"), "sheetData").find((node) => node.hasAttribute("sheetId") && Number(node.getAttribute("sheetId")) === sheetId);
    if (!sheet || ["1", "true"].includes(sheet.getAttribute("refreshError") ?? "")) return null;
    const key = `${path}#${sheetId}`;
    if (!cellsByPath.has(key)) cellsByPath.set(key, new Map(getLocalDescendants(sheet, "cell").map((cell) => [cell.getAttribute("r")?.replace(/\$/g, "").toUpperCase() ?? "", cell])));
    const cells = cellsByPath.get(key);
    const values = [];
    for (let row = range.start.row; row <= range.end.row; row += 1) {
      for (let col = range.start.col; col <= range.end.col; col += 1) {
        const cell = cells.get(`${formatA1Column(col)}${row + 1}`);
        const type = cell?.getAttribute("t") ?? "n";
        if (!["n", "str", "b", "e"].includes(type)) return null;
        const value = type === "e" ? null : getFirstLocalChild(cell, "v")?.textContent ?? null;
        values.push(mode === "value" ? cellValueToNumber(value) : value);
      }
    }
    return values;
  };
  const locate = (reference, sheetIndex) => {
    if (!reference?.formula) return null;
    const rootRelationships = getLocalDescendants(read("_rels/.rels"), "Relationship");
    const rootTarget = rootRelationships.find((node) => node.getAttribute("Type")?.endsWith("/officeDocument"))?.getAttribute("Target");
    const workbookPath = rootTarget ? resolveRelationshipPath("workbook.xml", rootTarget) : "xl/workbook.xml";
    const workbookDocument = read(workbookPath);
    const sheetNodes = getLocalDescendants(workbookDocument, "sheet");
    let formula = reference.formula.replace(/^=/, "");
    for (let depth = 0; depth < 8 && !formula.includes("!") && !parseA1Range(formula); depth += 1) {
      const names = getLocalDescendants(workbookDocument, "definedName").filter((node) => node.getAttribute("name") === formula);
      const named = names.find((node) => node.getAttribute("localSheetId") === String(sheetIndex)) ?? names.find((node) => !node.hasAttribute("localSheetId"));
      if (!named?.textContent || named.textContent === formula) return null;
      formula = named.textContent.replace(/^=/, "");
    }
    const split = splitSheetReference(formula);
    const range = parseA1Range(split?.range ?? formula);
    const sheet = split ? sheetNodes.find((node) => node.getAttribute("name") === split.sheetName) : sheetNodes[sheetIndex];
    if (!range || !sheet || range.end.row >= 1048576 || range.end.col >= 16384) return null;
    const id = sheet.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id") ?? sheet.getAttribute("r:id");
    const relsPath = `${dirname2(workbookPath)}/_rels/${workbookPath.split("/").pop()}.rels`;
    const relationships = getLocalDescendants(read(relsPath), "Relationship");
    const relationship = relationships.find((node) => node.getAttribute("Id") === id && node.getAttribute("TargetMode") !== "External");
    const target = relationship?.getAttribute("Target");
    if (!target) return null;
    const path = resolveRelationshipPath(relsPath, target);
    const document2 = read(path);
    if (!document2) return null;
    return { range, path, document: document2, relationships, relsPath, workbookPath };
  };
  const resolve = ((reference, sheetIndex, mode) => {
    if (!reference?.formula) return reference?.values ?? null;
    const cached = external(reference, mode);
    if (cached) return cached;
    const target = locate(reference, sheetIndex);
    if (!target) return null;
    const { range, path, document: document2, relationships, relsPath, workbookPath } = target;
    if (!cellsByPath.has(path)) cellsByPath.set(path, new Map(getLocalDescendants(document2, "c").map((cell) => [cell.getAttribute("r")?.toUpperCase() ?? "", cell])));
    const cells = cellsByPath.get(path);
    const values = [];
    for (let row = range.start.row; row <= range.end.row; row += 1) {
      for (let col = range.start.col; col <= range.end.col; col += 1) {
        const cell = cells.get(`${formatA1Column(col)}${row + 1}`);
        const type = cell?.getAttribute("t");
        let value = getFirstLocalChild(cell, "v")?.textContent ?? null;
        if (type === "s") {
          if (!sharedStrings) {
            const sharedTarget = relationships.find((node) => node.getAttribute("Type")?.endsWith("/sharedStrings"))?.getAttribute("Target");
            sharedStrings = getLocalDescendants(read(sharedTarget ? resolveRelationshipPath(relsPath, sharedTarget) : `${dirname2(workbookPath)}/sharedStrings.xml`), "si").map((item) => getLocalDescendants(item, "t").map((node) => node.textContent ?? "").join(""));
          }
          value = value == null ? null : sharedStrings[Number(value)] ?? null;
        } else if (type === "inlineStr") value = getLocalDescendants(cell, "t").map((node) => node.textContent ?? "").join("");
        else if (type === "e") value = null;
        values.push(mode === "value" ? cellValueToNumber(value) : value);
      }
    }
    return values;
  });
  resolve.external = external;
  resolve.layout = (reference, sheetIndex) => {
    const target = locate(reference, sheetIndex);
    if (!target) return null;
    const { range, path, document: document2 } = target;
    const hiddenRows = new Set(getLocalDescendants(document2, "row").filter((node) => node.getAttribute("hidden") === "1" || node.getAttribute("hidden") === "true").map((node) => Number(node.getAttribute("r")) - 1));
    const hiddenColumns = getLocalDescendants(document2, "col").filter((node) => node.getAttribute("hidden") === "1" || node.getAttribute("hidden") === "true").map((node) => [Number(node.getAttribute("min")) - 1, Number(node.getAttribute("max")) - 1]);
    const sheetRelsPath = `${dirname2(path)}/_rels/${path.split("/").pop()}.rels`;
    const totalRanges = getLocalDescendants(read(sheetRelsPath), "Relationship").filter((node) => node.getAttribute("Type")?.endsWith("/table") && node.getAttribute("TargetMode") !== "External").flatMap((node) => {
      const table = read(resolveRelationshipPath(sheetRelsPath, node.getAttribute("Target") ?? ""))?.documentElement;
      const tableRange = parseA1Range(table?.getAttribute("ref") ?? "");
      const totalCount = Number(table?.getAttribute("totalsRowCount") ?? 0);
      const headers = Number(table?.getAttribute("headerRowCount") ?? 1);
      if (!tableRange || totalCount <= 0 || range.start.col < tableRange.start.col || range.end.col > tableRange.end.col || range.start.row < tableRange.start.row + headers || range.end.row > tableRange.end.row) return [];
      const firstTotal = tableRange.end.row - totalCount + 1;
      return range.start.row < firstTotal && range.end.row >= firstTotal ? [firstTotal] : [];
    });
    const hiddenCells = [];
    const tableTotalCells = [];
    let index = 0;
    for (let row = range.start.row; row <= range.end.row; row += 1) {
      for (let col = range.start.col; col <= range.end.col; col += 1, index += 1) {
        if (hiddenRows.has(row) || hiddenColumns.some(([min, max]) => col >= min && col <= max)) hiddenCells.push(index);
        if (totalRanges.some((start) => row >= start)) tableTotalCells.push(index);
      }
    }
    return { range, hiddenCells, tableTotalCells };
  };
  return resolve;
}
function referenceHiddenCells(workbook, sheetIndex, reference) {
  const { sheet, range } = resolveReferenceSheet(workbook, sheetIndex, reference?.formula);
  if (!sheet || !range) return void 0;
  const hidden = [];
  let index = 0;
  for (let row = range.start.row; row <= range.end.row; row += 1) {
    for (let col = range.start.col; col <= range.end.col; col += 1, index += 1) {
      if (sheet.isRowHidden(row) || sheet.isColumnHidden(col)) hidden.push(index);
    }
  }
  return hidden;
}
function hydrateChartReferenceCaches(document2, sheetIndex, resolve, workbook) {
  for (const reference of [...getLocalDescendants(document2, "numRef"), ...getLocalDescendants(document2, "strRef")]) {
    const formula = getFirstLocalChild(reference, "f")?.textContent;
    if (!formula) continue;
    const numeric = reference.localName === "numRef";
    const source = { formula };
    const live = workbook ? resolveReferenceSheet(workbook, sheetIndex, formula) : null;
    const values = workbook && live?.sheet && live.range ? resolveReferenceValues(workbook, sheetIndex, source, numeric ? "value" : "category") : resolve(source, sheetIndex, numeric ? "value" : "category");
    if (!values) continue;
    const cache = ensureChild(reference, numeric ? "numCache" : "strCache");
    removeLocalChildren(cache, "pt");
    ensureChild(cache, "ptCount").setAttribute("val", String(values.length));
    values.forEach((value, index) => {
      if (value == null) return;
      const point = cache.ownerDocument.createElementNS(CHART_NS, "c:pt");
      point.setAttribute("idx", String(index));
      setLeafValue(point, "v", String(value));
      cache.appendChild(point);
    });
  }
  for (const reference of [...getLocalDescendants(document2, "multiLvlStrRef"), ...getLocalDescendants(document2, "numDim"), ...getLocalDescendants(document2, "strDim")]) {
    const formula = getFirstLocalChild(reference, "f")?.textContent;
    if (!formula) continue;
    const numeric = reference.localName === "numDim";
    const multi = reference.localName === "multiLvlStrRef";
    const source = { formula };
    const live = workbook ? resolveReferenceSheet(workbook, sheetIndex, formula) : null;
    const range = live?.range ?? resolve.layout(source, sheetIndex)?.range;
    const values = workbook && live?.sheet && live.range ? resolveReferenceValues(workbook, sheetIndex, source, numeric ? "value" : "category") : resolve(source, sheetIndex, numeric ? "value" : "category");
    const cache = multi ? getFirstLocalChild(reference, "multiLvlStrCache") : reference;
    if (!cache || !range || !values) continue;
    const levels = getLocalChildren(cache, "lvl");
    const rows = range.end.row - range.start.row + 1;
    const columns = range.end.col - range.start.col + 1;
    if (!levels.length || values.length !== rows * columns) continue;
    const byRow = levels.length === columns;
    if (levels.length > 1 && !byRow && levels.length !== rows) continue;
    const count = levels.length === 1 ? values.length : byRow ? rows : columns;
    if (multi) ensureChild(cache, "ptCount").setAttribute("val", String(count));
    levels.forEach((level, levelIndex) => {
      const explicit = new Set(getLocalChildren(level, "pt").map((point) => Number(point.getAttribute("idx"))));
      removeLocalChildren(level, "pt");
      if (!multi) level.setAttribute("ptCount", String(count));
      const dimension = multi ? levels.length - 1 - levelIndex : levelIndex;
      for (let index = 0; index < count; index++) {
        const offset = levels.length === 1 ? index : byRow ? index * columns + dimension : dimension * columns + index;
        const value = values[offset];
        if (value == null) continue;
        if (multi && levelIndex > 0 && index > 0 && !explicit.has(index)) {
          const unchanged = Array.from({ length: dimension + 1 }, (_, parent) => {
            const current = byRow ? index * columns + parent : parent * columns + index;
            const previous = byRow ? (index - 1) * columns + parent : parent * columns + index - 1;
            return values[current] === values[previous];
          }).every(Boolean);
          if (unchanged) continue;
        }
        const point = document2.createElementNS(reference.namespaceURI, `${reference.prefix ?? (multi ? "c" : "cx")}:pt`);
        point.setAttribute("idx", String(index));
        if (multi) setLeafValue(point, "v", String(value));
        else point.textContent = String(value);
        level.appendChild(point);
      }
    });
  }
  for (const text of getLocalDescendants(document2, "txData")) {
    const formula = getFirstLocalChild(text, "f")?.textContent;
    if (!formula) continue;
    const live = workbook ? resolveReferenceSheet(workbook, sheetIndex, formula) : null;
    const values = workbook && live?.sheet && live.range ? resolveReferenceValues(workbook, sheetIndex, { formula }, "category") : resolve({ formula }, sheetIndex, "category");
    if (!values?.length) continue;
    let value = getFirstLocalChild(text, "v");
    if (!value) {
      value = document2.createElementNS(text.namespaceURI, `${text.prefix ?? "cx"}:v`);
      text.appendChild(value);
    }
    value.textContent = String(values[0] ?? "");
  }
}
function chartPointExclusions(chart, series, resolve, workbook) {
  const count = Math.max(series.values.length, series.categories.length, series.bubbleSizes?.length ?? 0);
  const excluded = /* @__PURE__ */ new Set();
  const references = [series.categoriesRef, series.valuesRef, series.bubbleSizeRef];
  const hiddenByFormula = series.raw?.chartReferenceHiddenCells;
  for (const reference of references) {
    const layout = resolve.layout(reference ?? null, chart.workbookSheetIndex);
    if (!layout) continue;
    const rows = layout.range.end.row - layout.range.start.row + 1;
    const columns = layout.range.end.col - layout.range.start.col + 1;
    const hidden = workbook ? referenceHiddenCells(workbook, chart.workbookSheetIndex, reference) : reference?.formula ? hiddenByFormula?.[reference.formula] : void 0;
    const cells = [...layout.tableTotalCells, ...chart.plotVisibleOnly !== false ? hidden ?? layout.hiddenCells : []];
    for (const cell of cells) {
      const index = rows === count ? Math.floor(cell / columns) : columns === count ? cell % columns : rows * columns === count ? cell : -1;
      if (index >= 0 && index < count) excluded.add(index);
    }
  }
  return Array.from(excluded).sort((a, b) => a - b);
}
function reconcileChartSeries(chart, seriesNodes, resolveReference, workbook) {
  const sameCount = seriesNodes.length === chart.series.length;
  const unmatched = new Set(chart.series);
  chart.series = seriesNodes.map((node, index) => {
    const categoriesRef = chartReferenceFromXml(getFirstLocalChild(node, "cat") ?? getFirstLocalChild(node, "xVal"), "category");
    const valuesRef = chartReferenceFromXml(getFirstLocalChild(node, "val") ?? getFirstLocalChild(node, "yVal"), "value");
    const bubbleSizeRef = chartReferenceFromXml(getFirstLocalChild(node, "bubbleSize"), "value");
    const title = getFirstLocalChild(node, "tx");
    const nameFormula = getFirstLocalDescendant(title, "f")?.textContent ?? void 0;
    const name = getFirstLocalDescendant(title, "v")?.textContent ?? void 0;
    const existing = sameCount ? chart.series[index] : void 0;
    const matching = (existing ? [existing] : Array.from(unmatched)).find((series) => {
      const sameName = nameFormula ? series.raw?.name === nameFormula : series.name === name;
      const sameCategories = categoriesRef?.formula ? series.categoriesRef?.formula === categoriesRef.formula : !series.categoriesRef?.formula && JSON.stringify(series.categories) === JSON.stringify(categoriesRef?.values ?? []);
      const sameValues = valuesRef?.formula ? series.valuesRef?.formula === valuesRef.formula : !series.valuesRef?.formula && JSON.stringify(series.values) === JSON.stringify(valuesRef?.values ?? []);
      const sameBubbleSizes = bubbleSizeRef?.formula ? series.bubbleSizeRef?.formula === bubbleSizeRef.formula : !series.bubbleSizeRef?.formula && JSON.stringify(series.bubbleSizes ?? []) === JSON.stringify(bubbleSizeRef?.values ?? []);
      return sameName && sameCategories && sameValues && sameBubbleSizes;
    });
    if (matching) {
      unmatched.delete(matching);
      return matching;
    }
    if (workbook) {
      const asRaw = (reference, mode) => reference && {
        refType: reference.refType,
        formula: reference.formula,
        [mode === "value" ? "numbers" : "strings"]: reference.values
      };
      const normalized = normalizeChartSeries(workbook, chart.workbookSheetIndex, `${chart.id}-source`, {
        name: nameFormula ?? name,
        categories: asRaw(categoriesRef, "category"),
        values: asRaw(valuesRef, "value"),
        bubbleSize: asRaw(bubbleSizeRef, "value")
      }, index);
      return { ...existing, ...normalized, id: existing?.id ?? normalized.id, raw: { ...existing?.raw, ...normalized.raw } };
    }
    const categories = resolveReference(categoriesRef, chart.workbookSheetIndex, "category");
    const values = resolveReference(valuesRef, chart.workbookSheetIndex, "value");
    const bubbleSizes = resolveReference(bubbleSizeRef, chart.workbookSheetIndex, "value");
    const resolvedName = nameFormula ? resolveReference({ formula: nameFormula }, chart.workbookSheetIndex, "category") : null;
    return {
      ...existing,
      id: existing?.id ?? `${chart.id}-source-series-${index}`,
      name: resolvedName?.[0]?.toString() ?? name,
      categories: categories ?? categoriesRef?.values ?? [],
      categoriesRef,
      values: (values ?? valuesRef?.values ?? []).map(cellValueToNumber),
      valuesRef,
      bubbleSizes: (bubbleSizes ?? bubbleSizeRef?.values ?? []).map(cellValueToNumber),
      bubbleSizeRef,
      dataPoints: [],
      raw: {
        ...existing?.raw,
        name: nameFormula,
        chartCategoryReferenceValues: categories,
        unresolvedCategoriesReference: Boolean(categoriesRef?.formula && !categories),
        unresolvedValuesReference: Boolean(valuesRef?.formula && !values),
        unresolvedBubbleSizeReference: Boolean(bubbleSizeRef?.formula && !bubbleSizes)
      }
    };
  }).map((series) => {
    const categories = resolveReference.external(series.categoriesRef ?? null, "category");
    const values = resolveReference.external(series.valuesRef ?? null, "value");
    const bubbleSizes = resolveReference.external(series.bubbleSizeRef ?? null, "value");
    const name = typeof series.raw?.name === "string" ? resolveReference.external({ formula: series.raw.name }, "category") : null;
    if (!categories && !values && !bubbleSizes && !name) return series;
    return {
      ...series,
      name: name ? String(name[0] ?? "") : series.name,
      categories: categories ?? series.categories,
      values: values ? values.map(cellValueToNumber) : series.values,
      bubbleSizes: bubbleSizes ? bubbleSizes.map(cellValueToNumber) : series.bubbleSizes,
      raw: {
        ...series.raw,
        ...categories ? {
          chartCategoryReferenceValues: categories,
          chartCategoryNumericValues: resolveReference.external(series.categoriesRef ?? null, "value"),
          unresolvedCategoriesReference: false
        } : {},
        ...values ? { unresolvedValuesReference: false } : {},
        ...bubbleSizes ? { unresolvedBubbleSizeReference: false } : {},
        ...name ? { unresolvedNameReference: false } : {}
      }
    };
  });
}
function applyChartSeriesStyleFromXml(chart, chartTypeNode, themePalette) {
  const seriesNodes = getLocalChildren(chartTypeNode, "ser");
  chart.series = chart.series.map((series, index) => {
    const seriesNode = seriesNodes[index];
    if (!seriesNode) {
      return series;
    }
    const shapeProperties = getFirstLocalChild(seriesNode, "spPr");
    const markerNode = getFirstLocalChild(seriesNode, "marker");
    const markerShapeProperties = getFirstLocalChild(markerNode ?? chartTypeNode, "spPr");
    const lineStyle = resolveChartLineStyle(shapeProperties, themePalette);
    const markerLineStyle = resolveChartLineStyle(markerShapeProperties, themePalette);
    const fillColor = resolveChartFillColor(shapeProperties, themePalette);
    const markerSize = readChartNumericAttribute(markerNode, "size");
    const markerSymbolNode = markerNode ? getFirstLocalChild(markerNode, "symbol") : null;
    const markerSymbol = markerSymbolNode?.getAttribute("val") ?? (markerNode || chart.chartType === "Scatter" || ["marker", "lineMarker", "smoothMarker"].includes(chart.scatterStyle ?? "") || readChartBooleanAttribute(chartTypeNode, "marker") === true ? "auto" : series.markerSymbol);
    const pointStyles = parseChartPointStyles(seriesNode, themePalette);
    const seriesExplosion = readChartNumericAttribute(seriesNode, "explosion");
    const invertNegativeStyle = parseInvertNegativeStyle(seriesNode, themePalette);
    const invertIfNegative = readChartBooleanAttribute(seriesNode, "invertIfNegative");
    const isScatterChart = chartTypeNode.localName === "scatterChart" || chartTypeNode.localName === "bubbleChart";
    const cachedHierarchy = parseChartHierarchyCategories(getFirstLocalChild(seriesNode, "cat"));
    const hierarchy = cachedHierarchy ? hydrateChartHierarchy(series, cachedHierarchy) : void 0;
    const cachedCategories = isScatterChart ? parseChartCacheValues(getFirstLocalChild(seriesNode, "xVal"), "numCache", "value") ?? parseChartMultiLevelCacheValues(getFirstLocalChild(seriesNode, "xVal"), "category") : parseChartCacheValues(getFirstLocalChild(seriesNode, "cat"), "strCache", "category") ?? parseChartCacheValues(getFirstLocalChild(seriesNode, "cat"), "numCache", "category") ?? parseChartMultiLevelCacheValues(getFirstLocalChild(seriesNode, "cat"), "category");
    const cachedValues = isScatterChart ? parseChartCacheValues(getFirstLocalChild(seriesNode, "yVal"), "numCache", "value") : parseChartCacheValues(getFirstLocalChild(seriesNode, "val"), "numCache", "value");
    const cachedBubbleSizes = chart.chartType === "Bubble" ? parseChartCacheValues(getFirstLocalChild(seriesNode, "bubbleSize"), "numCache", "value") : null;
    const existingShapeProperties = series.shapeProperties && typeof series.shapeProperties === "object" ? series.shapeProperties : null;
    const rawFillColor = typeof existingShapeProperties?.solidFillHex === "string" ? normalizeHexColor3(existingShapeProperties.solidFillHex) : null;
    const rawLineColor = typeof existingShapeProperties?.lineColorHex === "string" ? normalizeHexColor3(existingShapeProperties.lineColorHex) : null;
    const resolvedLineColor = lineStyle.hidden ? void 0 : rawLineColor ?? lineStyle.color ?? rawFillColor ?? fillColor ?? series.lineColor ?? series.color;
    const hasCategoryReference = typeof series.categoriesRef?.formula === "string" && series.categoriesRef.formula.length > 0 && !series.raw?.unresolvedCategoriesReference;
    const hasValueReference = typeof series.valuesRef?.formula === "string" && series.valuesRef.formula.length > 0 && !series.raw?.unresolvedValuesReference;
    const hasBubbleSizeReference = typeof series.bubbleSizeRef?.formula === "string" && series.bubbleSizeRef.formula.length > 0 && !series.raw?.unresolvedBubbleSizeReference;
    return {
      ...series,
      raw: hierarchy ? { ...series.raw, chartHierarchyCategories: hierarchy } : series.raw,
      name: series.raw?.unresolvedNameReference ? parseChartCacheValues(getFirstLocalChild(seriesNode, "tx"), "strCache", "category")?.[0]?.toString() ?? series.name : series.name,
      bubbleSizes: !hasBubbleSizeReference && cachedBubbleSizes ? cachedBubbleSizes.map((value) => typeof value === "number" && Number.isFinite(value) ? value : null) : series.bubbleSizes,
      categories: hierarchy ? Array.from({ length: hierarchy.length }, (_, index2) => hierarchy[index2]?.find((entry) => entry.level === 0)?.label ?? null) : !hasCategoryReference && cachedCategories ? cachedCategories : series.categories,
      color: rawFillColor ?? rawLineColor ?? fillColor ?? lineStyle.color ?? series.color,
      dataPointStyles: pointStyles.length > 0 ? pointStyles : series.dataPointStyles,
      lineColor: resolvedLineColor,
      lineWidthPx: lineStyle.hidden ? void 0 : lineStyle.widthPx ?? series.lineWidthPx,
      markerColor: resolveChartFillColor(markerShapeProperties, themePalette) ?? rawFillColor ?? rawLineColor ?? fillColor ?? lineStyle.color ?? void 0,
      markerLineColor: markerLineStyle.color ?? rawLineColor ?? rawFillColor ?? lineStyle.color ?? fillColor ?? void 0,
      markerSize: markerSize ?? series.markerSize,
      markerSymbol,
      smooth: readChartBooleanAttribute(seriesNode, "smooth") ?? series.smooth,
      invertIfNegative: invertIfNegative ?? series.invertIfNegative,
      shapeProperties: {
        ...series.shapeProperties,
        xmlExplosion: seriesExplosion ?? void 0,
        xmlFillHidden: getFirstLocalChild(shapeProperties, "noFill") ? true : void 0,
        xmlFillColor: fillColor ?? void 0,
        xmlLineHidden: lineStyle.hidden ? true : void 0,
        xmlLineColor: lineStyle.color ?? void 0,
        xmlLineWidthPx: lineStyle.widthPx ?? void 0,
        xmlMarkerFillColor: resolveChartFillColor(markerShapeProperties, themePalette) ?? void 0,
        xmlMarkerFillHidden: getFirstLocalChild(markerShapeProperties, "noFill") ? true : void 0,
        xmlMarkerLineColor: markerLineStyle.color ?? void 0,
        xmlMarkerLineHidden: markerLineStyle.hidden ? true : void 0,
        xmlNegativeFillColor: invertNegativeStyle.color ?? void 0,
        xmlNegativeLineColor: invertNegativeStyle.lineColor ?? void 0
      },
      negativeColor: invertNegativeStyle.color ?? series.negativeColor,
      negativeLineColor: invertNegativeStyle.lineColor ?? series.negativeLineColor,
      values: !hasValueReference && cachedValues ? cachedValues.map((value) => typeof value === "number" && Number.isFinite(value) ? value : null) : series.values
    };
  });
}
function applyChartStyleFromXml(chart, chartPath, archive, themePalette, resolveReference, workbook) {
  if (chart.raw?.pivotSource && chart.raw?.pivotModified) return;
  const chartXml = readArchiveText2(archive, chartPath);
  if (!chartXml) {
    return;
  }
  const relationships = chartPath ? readChartRelationships(archive, chartPath) : /* @__PURE__ */ new Map();
  const workbookRelationships = readChartRelationships(archive, "xl/workbook.xml");
  const themePath = [...workbookRelationships].find(([type]) => type.endsWith("/theme"))?.[1];
  const themeXml = readArchiveText2(archive, themePath ?? "xl/theme/theme1.xml") ?? void 0;
  const images = readChartImages(archive, chartPath);
  const drawings = readChartDrawings(archive, chartPath);
  const fallbackPointStylesBySeries = parseFallbackPointStylesFromChartXml(chartXml, themePalette);
  const fallbackSeriesStyles = parseFallbackSeriesStylesFromChartXml(chartXml, themePalette);
  const fallbackBubbleSizesBySeries = parseFallbackBubbleSizesFromChartXml(chartXml);
  const applyFallbackSeriesStyles = () => {
    if (fallbackBubbleSizesBySeries.length > 0) {
      chart.series = chart.series.map((series, seriesIndex) => {
        const fallbackBubbleSizes = fallbackBubbleSizesBySeries[seriesIndex] ?? [];
        if (fallbackBubbleSizes.length === 0) {
          return series;
        }
        const currentNumericPointCount = (series.bubbleSizes ?? []).filter(
          (value) => typeof value === "number" && Number.isFinite(value)
        ).length;
        const fallbackNumericPointCount = fallbackBubbleSizes.filter(
          (value) => typeof value === "number" && Number.isFinite(value)
        ).length;
        if (currentNumericPointCount >= fallbackNumericPointCount) {
          return series;
        }
        return {
          ...series,
          bubbleSizes: fallbackBubbleSizes
        };
      });
    }
    if (fallbackPointStylesBySeries.length > 0) {
      chart.series = chart.series.map((series, seriesIndex) => {
        const fallbackPointStyles = fallbackPointStylesBySeries[seriesIndex] ?? [];
        if (fallbackPointStyles.length === 0) {
          return series;
        }
        const existingByIndex = new Map((series.dataPointStyles ?? []).map((entry) => [entry.index, entry]));
        for (const fallbackStyle of fallbackPointStyles) {
          const existing = existingByIndex.get(fallbackStyle.index);
          existingByIndex.set(fallbackStyle.index, {
            color: existing?.color ?? fallbackStyle.color,
            explosion: existing?.explosion ?? fallbackStyle.explosion,
            index: fallbackStyle.index,
            lineColor: existing?.lineColor ?? fallbackStyle.lineColor
          });
        }
        return {
          ...series,
          dataPointStyles: Array.from(existingByIndex.values()).sort((left, right) => left.index - right.index)
        };
      });
    }
    if (fallbackSeriesStyles.length > 0) {
      chart.series = chart.series.map((series, seriesIndex) => {
        const fallbackStyle = fallbackSeriesStyles[seriesIndex];
        if (!fallbackStyle) {
          return series;
        }
        const fallbackColor = fallbackStyle.color ?? fallbackStyle.lineColor;
        return {
          ...series,
          color: series.color ?? fallbackColor,
          lineColor: series.lineColor ?? fallbackStyle.lineColor ?? fallbackColor,
          markerColor: series.markerColor ?? fallbackColor ?? series.color,
          markerLineColor: series.markerLineColor ?? fallbackStyle.lineColor ?? fallbackColor ?? series.lineColor
        };
      });
    }
  };
  const applyRelationshipStyles = () => {
    chart.chartColorPalette = readChartColorPalette(archive, relationships.get(CHART_COLOR_STYLE_REL_TYPE), themePalette);
    chart.raw = { ...chart.raw, hasCustomChartColorStyle: Boolean(chart.chartColorPalette?.length) };
    const styleAppearance2 = readChartStyleAppearance(
      archive,
      relationships.get(CHART_STYLE_REL_TYPE),
      themePalette
    );
    chart.axisLabelColor = styleAppearance2.axisLabelColor ?? chart.axisLabelColor;
    chart.axisLineColor = styleAppearance2.axisLineColor ?? chart.axisLineColor;
    chart.chartAreaBorderColor = styleAppearance2.chartAreaBorderColor ?? chart.chartAreaBorderColor;
    chart.chartAreaFillColor = styleAppearance2.chartAreaFillColor ?? chart.chartAreaFillColor;
    chart.chartColorPaletteOffset = styleAppearance2.paletteOffset ?? chart.chartColorPaletteOffset;
    chart.textColor = styleAppearance2.textColor ?? chart.textColor;
    chart.titleColor = styleAppearance2.titleColor ?? chart.titleColor;
    return styleAppearance2;
  };
  const applyModernChartExStyles = () => {
    const modernPlotAreaNode = chartDocument?.documentElement ? getFirstLocalDescendant(chartDocument.documentElement, "plotArea") : null;
    if (!modernPlotAreaNode) {
      return;
    }
    const parseModernBinning = (seriesNode) => {
      const layoutPrNode = getFirstLocalChild(seriesNode, "layoutPr");
      const binningNode = layoutPrNode ? getFirstLocalChild(layoutPrNode, "binning") : null;
      if (!binningNode) {
        return null;
      }
      const binning = {};
      for (const attribute of Array.from(binningNode.attributes)) {
        const rawValue = attribute.value;
        const numeric = Number(rawValue);
        binning[attribute.localName || attribute.name] = Number.isFinite(numeric) && rawValue.trim() !== "" ? numeric : rawValue;
      }
      return Object.keys(binning).length > 0 ? binning : {};
    };
    const plotAreaShapeProperties2 = getFirstLocalChild(modernPlotAreaNode, "spPr");
    if (plotAreaShapeProperties2) {
      const plotAreaFillColor = resolveChartFillColor(plotAreaShapeProperties2, themePalette);
      const plotAreaLineStyle = resolveChartLineStyle(plotAreaShapeProperties2, themePalette);
      if (plotAreaFillColor) {
        chart.chartAreaFillColor = chart.chartAreaFillColor ?? plotAreaFillColor;
      }
      if (plotAreaLineStyle.color) {
        chart.chartAreaBorderColor = chart.chartAreaBorderColor ?? plotAreaLineStyle.color;
      }
    }
    const modernSeriesNodes = getLocalDescendants(modernPlotAreaNode, "series");
    if (modernSeriesNodes.length === 0) {
      return;
    }
    chart.series = chart.series.map((series, seriesIndex) => {
      const modernSeriesNode = modernSeriesNodes[seriesIndex] ?? null;
      if (!modernSeriesNode) {
        return series;
      }
      const valueColorsNode = getFirstLocalChild(modernSeriesNode, "valueColors");
      const valueColors = valueColorsNode ? Array.from(valueColorsNode.childNodes).filter((node) => node.nodeType === Node.ELEMENT_NODE).map((node) => resolveChartColorNode(findFirstChartColorElement(node) ?? node, themePalette)).filter((value) => typeof value === "string" && value.length > 0) : [];
      const nextRaw = valueColors.length > 0 ? {
        ...series.raw && typeof series.raw === "object" ? series.raw : {},
        valueColors
      } : series.raw;
      const seriesShapeProperties = getFirstLocalChild(modernSeriesNode, "spPr");
      if (!seriesShapeProperties) {
        return nextRaw === series.raw ? series : {
          ...series,
          raw: nextRaw
        };
      }
      const fillColor = resolveChartFillColor(seriesShapeProperties, themePalette);
      const lineStyle = resolveChartLineStyle(seriesShapeProperties, themePalette);
      const fallbackColor = fillColor ?? lineStyle.color ?? void 0;
      return {
        ...series,
        color: series.color ?? fallbackColor,
        lineColor: series.lineColor ?? lineStyle.color ?? fillColor ?? fallbackColor,
        lineWidthPx: series.lineWidthPx ?? (typeof lineStyle.widthPx === "number" ? lineStyle.widthPx : void 0),
        markerColor: series.markerColor ?? fallbackColor ?? series.color,
        markerLineColor: series.markerLineColor ?? lineStyle.color ?? fallbackColor ?? series.lineColor,
        raw: nextRaw
      };
    });
    const seriesLayouts = modernSeriesNodes.map((node) => node.getAttribute("layoutId") ?? node.getAttribute("layout"));
    const clusteredColumnIndex = seriesLayouts.findIndex((layout) => layout === "clusteredColumn");
    if (clusteredColumnIndex >= 0) {
      const clusteredNode = modernSeriesNodes[clusteredColumnIndex] ?? null;
      const parsedBinning = clusteredNode ? parseModernBinning(clusteredNode) : null;
      if (parsedBinning) {
        const syntheticRawSeries = {
          layoutId: "clusteredColumn",
          layoutPr: {
            binning: parsedBinning
          }
        };
        const hasParetoLine = seriesLayouts.includes("paretoLine");
        const replaceColumnSeries = (series) => series ? buildChartExHistogramSeries(series, syntheticRawSeries, hasParetoLine) : null;
        if (chart.typeGroups && chart.typeGroups.length > 0) {
          const nextTypeGroups = chart.typeGroups.map((group) => ({ ...group, series: [...group.series] }));
          const columnGroupIndex = nextTypeGroups.findIndex((group) => group.chartType === "ColumnClustered");
          if (columnGroupIndex >= 0) {
            const originalColumnSeries = nextTypeGroups[columnGroupIndex]?.series[0] ?? null;
            const binnedColumnSeries = replaceColumnSeries(originalColumnSeries);
            if (binnedColumnSeries) {
              nextTypeGroups[columnGroupIndex].series = [binnedColumnSeries];
              const lineGroupIndex = nextTypeGroups.findIndex((group) => group.chartType === "Line");
              if (lineGroupIndex >= 0 && nextTypeGroups[lineGroupIndex]?.series[0]) {
                const originalLineSeries = nextTypeGroups[lineGroupIndex].series[0];
                const recomputedLine = buildChartExParetoLineSeries(
                  binnedColumnSeries,
                  {
                    text: originalLineSeries.name,
                    ...originalLineSeries.raw && typeof originalLineSeries.raw === "object" ? originalLineSeries.raw : {}
                  },
                  0
                );
                nextTypeGroups[lineGroupIndex].series = [
                  {
                    ...originalLineSeries,
                    categories: recomputedLine.categories,
                    categoriesRef: recomputedLine.categoriesRef,
                    raw: recomputedLine.raw,
                    values: recomputedLine.values
                  }
                ];
                chart.series = [binnedColumnSeries, nextTypeGroups[lineGroupIndex].series[0]];
              } else {
                chart.series = [binnedColumnSeries];
              }
              chart.typeGroups = nextTypeGroups;
            }
          } else if (chart.series[0]) {
            const binnedSeries = replaceColumnSeries(chart.series[0]);
            if (binnedSeries) {
              chart.series = [binnedSeries];
            }
          }
        } else if (chart.series[0]) {
          const binnedSeries = replaceColumnSeries(chart.series[0]);
          if (binnedSeries) {
            chart.series = [binnedSeries];
          }
        }
      }
    }
  };
  const chartDocument = parseXml2(chartXml);
  const chartNode = chartDocument ? getFirstLocalDescendant(chartDocument, "chart") : null;
  const plotAreaNode = chartNode ? getFirstLocalChild(chartNode, "plotArea") : null;
  const styleIdNode = chartDocument?.documentElement ? getFirstLocalDescendant(chartDocument.documentElement, "style") : null;
  const chartTypeNode = findPrimaryChartTypeNode(plotAreaNode);
  if (!chartNode || !chartTypeNode) {
    applyRelationshipStyles();
    const fallbackStyleId = readChartNumericAttribute(styleIdNode, "style");
    if (typeof fallbackStyleId === "number" && Number.isFinite(fallbackStyleId)) {
      chart.chartStyleId = fallbackStyleId;
    }
    const sourceSeries = chart.raw?.officeSourceSeries;
    if (chartDocument?.documentElement.namespaceURI === "http://schemas.microsoft.com/office/drawing/2014/chartex") {
      hydrateChartReferenceCaches(chartDocument, chart.workbookSheetIndex, resolveReference, workbook);
      chart.renderSource = {
        kind: chart.chartExLayout ?? "",
        seriesTypes: getLocalDescendants(chartNode, "series").map((node) => node.getAttribute("layoutId") ?? ""),
        sourceSeries,
        experimental: true,
        xml: serializeXml2(chartDocument),
        images,
        drawings,
        themeXml,
        themeColors: themePalette ? Object.fromEntries(Object.entries(THEME_COLOR_INDEX_BY_NAME).flatMap(([key, index]) => {
          const color = themePalette.colorsByIndex[index];
          return color ? [[key, color]] : [];
        })) : void 0,
        themeOverrideXml: readArchiveText2(archive, relationships.get("http://schemas.openxmlformats.org/officeDocument/2006/relationships/themeOverride")) ?? void 0,
        styleXml: readArchiveText2(archive, relationships.get(CHART_STYLE_REL_TYPE)) ?? void 0,
        colorStyleXml: readArchiveText2(archive, relationships.get(CHART_COLOR_STYLE_REL_TYPE)) ?? void 0
      };
    }
    applyModernChartExStyles();
    applyFallbackSeriesStyles();
    applyBuiltinChartDefaults(chart, themePalette);
    return;
  }
  const plotArea = plotAreaNode;
  if (!plotArea) {
    applyRelationshipStyles();
    applyFallbackSeriesStyles();
    applyBuiltinChartDefaults(chart, themePalette);
    return;
  }
  switch (chartTypeNode.localName) {
    case "barChart":
    case "bar3DChart": {
      const grouping = getFirstLocalChild(chartTypeNode, "grouping")?.getAttribute("val");
      const barDir = getFirstLocalChild(chartTypeNode, "barDir")?.getAttribute("val");
      const isHorizontalBar = barDir === "bar";
      chart.is3d = chartTypeNode.localName === "bar3DChart" ? true : chart.is3d;
      if (grouping === "percentStacked") {
        chart.chartType = isHorizontalBar ? "BarPercentStacked" : "ColumnPercentStacked";
      } else if (grouping === "stacked") {
        chart.chartType = isHorizontalBar ? "BarStacked" : "ColumnStacked";
      } else {
        chart.chartType = isHorizontalBar ? "BarClustered" : "ColumnClustered";
      }
      break;
    }
    case "areaChart":
    case "area3DChart": {
      const grouping = getFirstLocalChild(chartTypeNode, "grouping")?.getAttribute("val");
      chart.is3d = chartTypeNode.localName === "area3DChart" ? true : chart.is3d;
      if (grouping === "stacked") {
        chart.chartType = "AreaStacked";
      } else if (grouping === "percentStacked") {
        chart.chartType = "AreaPercentStacked";
      } else {
        chart.chartType = "Area";
      }
      break;
    }
    case "lineChart":
    case "line3DChart": {
      const grouping = getFirstLocalChild(chartTypeNode, "grouping")?.getAttribute("val");
      chart.is3d = chartTypeNode.localName === "line3DChart" ? true : chart.is3d;
      if (grouping === "stacked") {
        chart.chartType = "LineStacked";
      } else if (grouping === "percentStacked") {
        chart.chartType = "LinePercentStacked";
      } else {
        chart.chartType = "Line";
      }
      break;
    }
    case "pieChart":
      chart.chartType = "Pie";
      break;
    case "pie3DChart":
      chart.chartType = "Pie3D";
      chart.is3d = true;
      break;
    case "doughnutChart":
      chart.chartType = "Doughnut";
      break;
    case "ofPieChart":
      chart.chartType = "BarOfPie";
      break;
    case "scatterChart":
      chart.chartType = resolveScatterChartType(getFirstLocalChild(chartTypeNode, "scatterStyle")?.getAttribute("val"));
      break;
    case "radarChart":
      chart.chartType = "Radar";
      break;
    case "surfaceChart":
      chart.chartType = "Surface";
      chart.is3d = false;
      break;
    case "surface3DChart":
      chart.chartType = "Surface";
      chart.is3d = true;
      break;
    case "stockChart":
      chart.chartType = "Stock";
      break;
    case "bubbleChart":
      chart.chartType = "Bubble";
      break;
    default:
      break;
  }
  const legendNode = getFirstLocalChild(chartNode, "legend");
  const legendPosition = legendNode ? getFirstLocalChild(legendNode, "legendPos")?.getAttribute("val") ?? void 0 : void 0;
  const legendOverlay = legendNode ? getFirstLocalChild(legendNode, "overlay")?.getAttribute("val") : void 0;
  chart.legend = legendNode ? {
    overlay: legendOverlay === "1",
    position: normalizeLegendPosition(legendPosition),
    raw: chart.legend?.raw
  } : chart.legend;
  const plotVisibleOnly = readChartBooleanAttribute(chartNode, "plotVisOnly");
  if (plotVisibleOnly !== void 0) {
    chart.plotVisibleOnly = plotVisibleOnly;
  }
  chart.displayBlanksAs = getFirstLocalChild(chartNode, "dispBlanksAs")?.getAttribute("val") ?? chart.displayBlanksAs;
  const styleId = Number(styleIdNode?.getAttribute("val") ?? Number.NaN);
  chart.chartStyleId = Number.isFinite(styleId) ? styleId : chart.chartStyleId;
  chart.firstSliceAngle = readChartNumericAttribute(chartTypeNode, "firstSliceAng") ?? chart.firstSliceAngle;
  chart.gapWidth = readChartNumericAttribute(chartTypeNode, "gapWidth") ?? chart.gapWidth;
  chart.overlap = readChartNumericAttribute(chartTypeNode, "overlap") ?? chart.overlap;
  chart.bubbleScale = readChartNumericAttribute(chartTypeNode, "bubbleScale") ?? chart.bubbleScale;
  chart.varyColors = readChartBooleanAttribute(chartTypeNode, "varyColors") ?? chart.varyColors;
  const bubble3dNode = getFirstLocalChild(chartTypeNode, "bubble3D");
  chart.bubble3d = bubble3dNode ? bubble3dNode.getAttribute("val") !== "0" : chart.bubble3d;
  chart.holeSize = readChartNumericAttribute(chartTypeNode, "holeSize") ?? chart.holeSize;
  chart.radarStyle = getFirstLocalChild(chartTypeNode, "radarStyle")?.getAttribute("val") ?? chart.radarStyle;
  chart.scatterStyle = getFirstLocalChild(chartTypeNode, "scatterStyle")?.getAttribute("val") ?? chart.scatterStyle;
  chart.shape3d = getFirstLocalChild(chartTypeNode, "shape")?.getAttribute("val") ?? chart.shape3d;
  const wireframeNode = getFirstLocalChild(chartTypeNode, "wireframe");
  chart.wireframe = wireframeNode ? wireframeNode.getAttribute("val") !== "0" : chart.wireframe;
  const chartTypeDataLabels = parseChartDataLabelsFromXml(getFirstLocalChild(chartTypeNode, "dLbls"));
  const firstSeriesNode = getLocalChildren(chartTypeNode, "ser")[0] ?? null;
  const seriesDataLabels = parseChartDataLabelsFromXml(getFirstLocalChild(firstSeriesNode, "dLbls"));
  chart.dataLabels = chartTypeDataLabels ?? seriesDataLabels ?? chart.dataLabels;
  const seriesSp3dNode = firstSeriesNode ? getFirstLocalDescendant(firstSeriesNode, "sp3d") : null;
  chart.surfaceMaterial = seriesSp3dNode?.getAttribute("prstMaterial") ?? chart.surfaceMaterial;
  const bandFormatsNode = getLocalChildren(chartTypeNode, "bandFmts")[0] ?? null;
  const bandFormatNodes = bandFormatsNode ? getLocalChildren(bandFormatsNode, "bandFmt") : [];
  const bandFormatColors = /* @__PURE__ */ Object.create(null);
  const bandFormatLineColors = /* @__PURE__ */ Object.create(null);
  const bandFormatLineWidths = /* @__PURE__ */ Object.create(null);
  for (const bandFormatNode of bandFormatNodes) {
    const index = readChartNumericAttribute(bandFormatNode, "idx");
    if (index == null || !Number.isInteger(index) || index < 0 || index > 4294967295) {
      continue;
    }
    const shapeProperties = getFirstLocalChild(bandFormatNode, "spPr");
    const fillColor = getFirstLocalChild(shapeProperties, "noFill") ? "transparent" : resolveChartFillColor(shapeProperties, themePalette);
    const lineStyle = resolveChartLineStyle(shapeProperties, themePalette);
    const lineColor = lineStyle.hidden ? "transparent" : lineStyle.color;
    const lineWidth = Number(getFirstLocalChild(shapeProperties, "ln")?.getAttribute("w") ?? Number.NaN);
    if (fillColor) bandFormatColors[index] = fillColor;
    if (lineColor) bandFormatLineColors[index] = lineColor;
    if (Number.isFinite(lineWidth) && lineWidth >= 0) bandFormatLineWidths[index] = lineWidth / EMU_PER_PIXEL2;
  }
  chart.raw = {
    ...chart.raw ?? {},
    bandFormatColors: Object.keys(bandFormatColors).length > 0 ? bandFormatColors : void 0,
    bandFormatLineColors: Object.keys(bandFormatLineColors).length > 0 ? bandFormatLineColors : void 0,
    bandFormatLineWidths: Object.keys(bandFormatLineWidths).length > 0 ? bandFormatLineWidths : void 0,
    date1904: readChartBooleanAttribute(chartDocument?.documentElement ?? null, "date1904"),
    titleOverlay: readChartBooleanAttribute(getFirstLocalChild(chartNode, "title"), "overlay"),
    bubble3d: chart.bubble3d,
    grouping: getFirstLocalChild(chartTypeNode, "grouping")?.getAttribute("val") ?? void 0,
    ofPieType: getFirstLocalChild(chartTypeNode, "ofPieType")?.getAttribute("val") ?? void 0,
    shape: getFirstLocalChild(chartTypeNode, "shape")?.getAttribute("val") ?? void 0,
    secondPieSize: readChartNumericAttribute(chartTypeNode, "secondPieSize"),
    scatterStyle: chart.scatterStyle,
    splitPos: readChartNumericAttribute(chartTypeNode, "splitPos"),
    splitType: getFirstLocalChild(chartTypeNode, "splitType")?.getAttribute("val") ?? void 0,
    xmlChartType: chartTypeNode.localName
  };
  const view3dNode = getFirstLocalDescendant(chartNode, "view3D");
  if (view3dNode) {
    chart.view3d = {
      depthPercent: readChartNumericAttribute(view3dNode, "depthPercent"),
      heightPercent: readChartNumericAttribute(view3dNode, "hPercent"),
      perspective: readChartNumericAttribute(view3dNode, "perspective"),
      rAngAx: getFirstLocalChild(view3dNode, "rAngAx")?.getAttribute("val") === "1",
      rotX: readChartNumericAttribute(view3dNode, "rotX"),
      rotY: readChartNumericAttribute(view3dNode, "rotY")
    };
  }
  for (const key of ["floor", "sideWall", "backWall"]) {
    const wall = readChartWallFromXml(getFirstLocalChild(chartNode, key), themePalette);
    if (wall) {
      chart[key] = wall;
      const defaults = chart.raw?.builtinSurfaceDefaults;
      if (defaults) chart.raw = { ...chart.raw, builtinSurfaceDefaults: { ...defaults, [key]: void 0 } };
    }
  }
  const styleAppearance = applyRelationshipStyles();
  const chartTextTypeface = readChartTextTypeface(getFirstLocalChild(chartNode, "txPr"), themePalette);
  const titleTypeface = readChartTextTypeface(getFirstLocalDescendant(chartNode, "title"), themePalette);
  chart.fontFamily = chartTextTypeface ?? chart.fontFamily;
  chart.titleFontFamily = titleTypeface ?? chart.titleFontFamily ?? chart.fontFamily;
  const chartAreaShapeProperties = chartDocument?.documentElement ? getFirstLocalChild(chartDocument.documentElement, "spPr") : null;
  const plotAreaShapeProperties = getFirstLocalChild(plotArea, "spPr");
  const chartAreaNoFill = chartAreaShapeProperties ? getFirstLocalChild(chartAreaShapeProperties, "noFill") != null : false;
  const plotAreaNoFill = plotAreaShapeProperties ? getFirstLocalChild(plotAreaShapeProperties, "noFill") != null : false;
  chart.raw = {
    ...chart.raw ?? {},
    chartAreaNoFill: styleAppearance.chartAreaNoFill === true || chartAreaNoFill,
    plotAreaNoFill,
    plotAreaFillColor: resolveChartFillColor(plotAreaShapeProperties, themePalette) ?? void 0,
    plotAreaLineColor: resolveChartLineStyle(plotAreaShapeProperties, themePalette).color ?? void 0
  };
  if (chartAreaShapeProperties) {
    const chartAreaFillColor = resolveChartFillColor(chartAreaShapeProperties, themePalette);
    if (chartAreaFillColor) {
      chart.chartAreaFillColor = chartAreaFillColor;
    } else if (getFirstLocalChild(chartAreaShapeProperties, "noFill")) {
      chart.chartAreaFillColor = "transparent";
    }
    const chartAreaLineStyle = resolveChartLineStyle(chartAreaShapeProperties, themePalette);
    if (chartAreaLineStyle.hidden) {
      chart.chartAreaBorderColor = "transparent";
    } else if (chartAreaLineStyle.color) {
      chart.chartAreaBorderColor = chartAreaLineStyle.color;
    }
  }
  if (!chart.chartAreaFillColor && (styleAppearance.chartAreaNoFill === true || plotAreaNoFill)) {
    chart.chartAreaFillColor = "transparent";
  }
  const categoryAxisNodes = [
    ...getLocalChildren(plotArea, "catAx"),
    ...getLocalChildren(plotArea, "dateAx")
  ];
  const valueAxisNodes = getLocalChildren(plotArea, "valAx");
  const seriesAxisNode = getLocalChildren(plotArea, "serAx")[0] ?? null;
  const isScatterLikeChart = chart.chartType === "Scatter" || chart.chartType === "ScatterLines" || chart.chartType === "ScatterSmooth" || chart.chartType === "Bubble";
  let categoryAxisNode = categoryAxisNodes[0] ?? null;
  let valueAxisNode = valueAxisNodes[0] ?? null;
  if (!categoryAxisNode && isScatterLikeChart && valueAxisNodes.length >= 2) {
    categoryAxisNode = valueAxisNodes.find((axisNode) => {
      const position = getFirstLocalChild(axisNode, "axPos")?.getAttribute("val");
      return position === "b" || position === "t";
    }) ?? valueAxisNodes[0];
    valueAxisNode = valueAxisNodes.find((axisNode) => {
      const position = getFirstLocalChild(axisNode, "axPos")?.getAttribute("val");
      return position === "l" || position === "r";
    }) ?? valueAxisNodes[1] ?? valueAxisNodes[0];
  }
  chart.categoryAxis = mergeChartAxis(chart.categoryAxis, readChartAxisFromXml(categoryAxisNode, themePalette));
  chart.valueAxis = mergeChartAxis(chart.valueAxis, readChartAxisFromXml(valueAxisNode, themePalette));
  chart.seriesAxis = mergeChartAxis(chart.seriesAxis, readChartAxisFromXml(seriesAxisNode, themePalette));
  chart.axes = chart.axes.length > 0 ? chart.axes.map((axis, index) => index === 0 && categoryAxisNode ? { ...axis, ...readChartAxisFromXml(categoryAxisNode, themePalette) } : index === 1 && valueAxisNode ? { ...axis, ...readChartAxisFromXml(valueAxisNode, themePalette) } : axis) : chart.axes;
  if (seriesAxisNode) {
    const seriesAxis = readChartAxisFromXml(seriesAxisNode, themePalette);
    if (seriesAxis && !chart.axes.some((axis) => axis.id != null && axis.id === seriesAxis.id)) {
      chart.axes = [...chart.axes, seriesAxis];
    }
  }
  const groups = Array.from(plotArea.children).filter((entry) => entry.localName.endsWith("Chart"));
  const seriesTypes = groups.flatMap((group) => getLocalChildren(group, "ser").map(() => group.localName.slice(0, -5)));
  const seriesNodes = groups.flatMap((group) => getLocalChildren(group, "ser"));
  const dateAxisIds = new Set(getLocalChildren(plotArea, "dateAx").map((node) => readChartNumericAttribute(node, "axId")));
  const dateCategorySeries = groups.flatMap((group) => {
    const axisIds = getLocalChildren(group, "axId").map((node) => Number(node.getAttribute("val")));
    const hasDates = axisIds.some((id) => dateAxisIds.has(id)) || axisIds.length === 0 && dateAxisIds.size > 0;
    return getLocalChildren(group, "ser").map(() => hasDates);
  });
  const indexedXSeries = seriesNodes.map((series) => {
    const x = getFirstLocalChild(series, "xVal");
    return Boolean(x && (getFirstLocalChild(x, "multiLvlStrRef") || getFirstLocalChild(x, "strRef") || getFirstLocalChild(x, "strLit")));
  });
  reconcileChartSeries(chart, seriesNodes, resolveReference, workbook);
  const kind = chartTypeNode.localName.slice(0, -5);
  const stable = groups.length === 1 && !chart.is3d && (kind === "line" && chart.chartType === "Line" || kind === "bar" && chart.chartType === "ColumnClustered") && !plotArea.querySelector("trendline, errBars, dropLines, hiLowLines, upDownBars, dateAx, multiLvlStrRef, pictureOptions");
  if (chartDocument) hydrateChartReferenceCaches(chartDocument, chart.workbookSheetIndex, resolveReference, workbook);
  chart.renderSource = {
    kind,
    seriesTypes,
    indexedXSeries,
    dateCategorySeries,
    experimental: !stable,
    xml: chartDocument ? serializeXml2(chartDocument) : chartXml,
    images,
    drawings,
    themeXml,
    themeColors: themePalette ? Object.fromEntries(Object.entries(THEME_COLOR_INDEX_BY_NAME).flatMap(([key, index]) => {
      const color = themePalette.colorsByIndex[index];
      return color ? [[key, color]] : [];
    })) : void 0,
    themeOverrideXml: readArchiveText2(archive, relationships.get("http://schemas.openxmlformats.org/officeDocument/2006/relationships/themeOverride")) ?? void 0,
    styleXml: readArchiveText2(archive, relationships.get(CHART_STYLE_REL_TYPE)) ?? void 0,
    colorStyleXml: readArchiveText2(archive, relationships.get(CHART_COLOR_STYLE_REL_TYPE)) ?? void 0
  };
  if (groups.length > 1) {
    let seriesOffset = 0;
    const hydratedSeries = [];
    chart.typeGroups = groups.map((node, index) => {
      const group = chart.typeGroups?.[index] ?? { chartType: node.localName.slice(0, -5), series: [] };
      const count = getLocalChildren(node, "ser").length;
      const groupChart = { ...chart, chartType: group.chartType, series: chart.series.slice(seriesOffset, seriesOffset + count) };
      applyChartSeriesStyleFromXml(groupChart, groups[index], themePalette);
      seriesOffset += count;
      hydratedSeries.push(...groupChart.series);
      return { ...group, series: groupChart.series };
    });
    chart.series = [...hydratedSeries, ...chart.series.slice(seriesOffset)];
  } else {
    applyChartSeriesStyleFromXml(chart, chartTypeNode, themePalette);
  }
  chart.series = chart.series.map((series, index) => {
    const raw = { ...series.raw, chartExcludedPointIndices: chartPointExclusions(chart, series, resolveReference, workbook) };
    if (!dateCategorySeries[index]) return { ...series, raw };
    const cachedNumbers = parseChartCacheValues(getFirstLocalChild(seriesNodes[index], "cat"), "numCache", "value");
    const currentNumbers = series.raw?.chartCategoryNumericValues;
    const numbers = !series.raw?.unresolvedCategoriesReference && currentNumbers ? currentNumbers : cachedNumbers ?? resolveReference(series.categoriesRef ?? null, chart.workbookSheetIndex, "value");
    return { ...series, raw: { ...raw, chartCategoryNumericValues: numbers } };
  });
  applyFallbackSeriesStyles();
  applyBuiltinChartDefaults(chart, themePalette);
}
function normalizeArchivePath2(path) {
  return path.replace(/^\/+/, "").replace(/\\/g, "/");
}
function dirname2(path) {
  const normalized = normalizeArchivePath2(path);
  const index = normalized.lastIndexOf("/");
  return index >= 0 ? normalized.slice(0, index) : "";
}
function resolveRelationshipPath(basePath, target) {
  if (!target) {
    return "";
  }
  const normalizedTarget = target.replace(/\\/g, "/");
  if (normalizedTarget.startsWith("/")) {
    return normalizeArchivePath2(normalizedTarget);
  }
  const normalizedBasePath = normalizeArchivePath2(basePath);
  let baseDirectory = dirname2(normalizedBasePath);
  if (normalizedBasePath.endsWith(".rels")) {
    const relsMarker = "/_rels/";
    const relsMarkerIndex = normalizedBasePath.lastIndexOf(relsMarker);
    if (relsMarkerIndex >= 0) {
      const ownerPrefix = normalizedBasePath.slice(0, relsMarkerIndex);
      const relFileName = normalizedBasePath.slice(relsMarkerIndex + relsMarker.length);
      const ownerFileName = relFileName.endsWith(".rels") ? relFileName.slice(0, -".rels".length) : relFileName;
      baseDirectory = dirname2(`${ownerPrefix}/${ownerFileName}`);
    }
  }
  const segments = [...baseDirectory.split("/").filter(Boolean), ...normalizedTarget.split("/").filter(Boolean)];
  const resolved = [];
  for (const segment of segments) {
    if (segment === ".") {
      continue;
    }
    if (segment === "..") {
      resolved.pop();
      continue;
    }
    resolved.push(segment);
  }
  return resolved.join("/");
}
function readArchiveText2(archive, path) {
  if (!path) {
    return null;
  }
  const entry = archive[normalizeArchivePath2(path)];
  return entry ? strFromU83(entry) : null;
}
function parseXml2(xml) {
  try {
    return parseWorkbookXml(xml);
  } catch {
    return null;
  }
}
function serializeXml2(document2) {
  return serializeWorkbookXml(document2);
}
function getLocalChildren(parent, localName) {
  return Array.from(parent?.childNodes ?? []).filter(
    (node) => node.nodeType === Node.ELEMENT_NODE && node.localName === localName
  );
}
function removeLocalChildren(parent, localName) {
  getLocalChildren(parent, localName).forEach((node) => node.parentNode?.removeChild(node));
}
function getLocalDescendants(parent, localName) {
  return Array.from(parent?.getElementsByTagName("*") ?? []).filter(
    (node) => node.localName === localName
  );
}
function getFirstLocalChild(parent, localName) {
  return getLocalChildren(parent, localName)[0] ?? null;
}
function getFirstLocalDescendant(parent, localName) {
  return getLocalDescendants(parent, localName)[0] ?? null;
}
function ensureChild(parent, localName, namespace = parent.namespaceURI ?? CHART_NS, prefix = "c") {
  const existing = getFirstLocalChild(parent, localName);
  if (existing) {
    return existing;
  }
  const document2 = parent.ownerDocument;
  const node = document2.createElementNS(namespace, `${prefix}:${localName}`);
  parent.appendChild(node);
  return node;
}
function setLeafValue(parent, localName, value, namespace = parent.namespaceURI ?? CHART_NS, prefix = "c") {
  const node = ensureChild(parent, localName, namespace, prefix);
  node.textContent = value;
  return node;
}
function setBooleanValue(parent, localName, value) {
  const node = ensureChild(parent, localName);
  node.setAttribute("val", value ? "1" : "0");
  return node;
}
function setNumericValue(parent, localName, value) {
  const node = ensureChild(parent, localName);
  node.setAttribute("val", String(Math.round(value)));
  return node;
}
function unquoteSheetName(value) {
  const trimmed = value.trim();
  if (trimmed.startsWith("'") && trimmed.endsWith("'")) {
    return trimmed.slice(1, -1).replace(/''/g, "'");
  }
  return trimmed;
}
function splitSheetReference(reference) {
  let bangIndex = -1;
  let quoted = false;
  for (let index = 0; index < reference.length; index += 1) {
    const char = reference[index];
    if (char === "'") {
      quoted = !quoted;
    } else if (char === "!" && !quoted) {
      bangIndex = index;
      break;
    }
  }
  if (bangIndex < 0) {
    return null;
  }
  return {
    range: reference.slice(bangIndex + 1),
    sheetName: unquoteSheetName(reference.slice(0, bangIndex))
  };
}
function parseA1Cell(reference) {
  const match = /^\$?([A-Z]+)\$?(\d+)$/i.exec(reference.trim());
  if (!match) {
    return null;
  }
  let col = 0;
  for (const char of match[1].toUpperCase()) {
    col = col * 26 + (char.charCodeAt(0) - 64);
  }
  return {
    col: col - 1,
    row: Number(match[2]) - 1
  };
}
function parseA1Range(reference) {
  const [startRef, endRef = startRef] = reference.split(":");
  const start = parseA1Cell(startRef ?? "");
  const end = parseA1Cell(endRef ?? "");
  if (!start || !end) {
    return null;
  }
  return {
    end: {
      col: Math.max(start.col, end.col),
      row: Math.max(start.row, end.row)
    },
    start: {
      col: Math.min(start.col, end.col),
      row: Math.min(start.row, end.row)
    }
  };
}
function formatA1Column(col) {
  let current = col + 1;
  let label = "";
  while (current > 0) {
    const remainder = (current - 1) % 26;
    label = String.fromCharCode(65 + remainder) + label;
    current = Math.floor((current - 1) / 26);
  }
  return label;
}
function buildA1RangeFormula(sheetName, start, end) {
  const escapedSheetName = sheetName.replace(/'/g, "''");
  return `'${escapedSheetName}'!$${formatA1Column(start.col)}$${start.row + 1}:$${formatA1Column(end.col)}$${end.row + 1}`;
}
function resolveReferenceSheet(workbook, fallbackSheetIndex, formula) {
  if (!formula) {
    return {
      range: null,
      sheet: fallbackSheetIndex < workbook.sheetCount ? workbook.getSheet(fallbackSheetIndex) : null,
      sheetName: fallbackSheetIndex < workbook.sheetCount ? workbook.getSheet(fallbackSheetIndex)?.name ?? "" : ""
    };
  }
  const trimmedFormula = formula.trim();
  if (trimmedFormula.length > 0 && !trimmedFormula.includes("!")) {
    try {
      const namedRange = workbook.getNamedRange(trimmedFormula);
      if (typeof namedRange === "string" && namedRange.length > 0 && namedRange !== trimmedFormula) {
        return resolveReferenceSheet(workbook, fallbackSheetIndex, namedRange);
      }
    } catch {
    }
  }
  const split = splitSheetReference(trimmedFormula);
  if (!split) {
    return {
      range: parseA1Range(trimmedFormula),
      sheet: fallbackSheetIndex < workbook.sheetCount ? workbook.getSheet(fallbackSheetIndex) : null,
      sheetName: fallbackSheetIndex < workbook.sheetCount ? workbook.getSheet(fallbackSheetIndex)?.name ?? "" : ""
    };
  }
  try {
    return {
      range: parseA1Range(split.range),
      sheet: workbook.getSheetByName(split.sheetName),
      sheetName: split.sheetName
    };
  } catch {
    return {
      range: parseA1Range(split.range),
      sheet: null,
      sheetName: split.sheetName
    };
  }
}
function resolveReferenceRowPaths(workbook, fallbackSheetIndex, reference) {
  if (!reference?.formula) {
    return [];
  }
  const resolved = resolveReferenceSheet(workbook, fallbackSheetIndex, reference.formula);
  if (!resolved.sheet || !resolved.range) {
    return [];
  }
  const rows = [];
  for (let row = resolved.range.start.row; row <= resolved.range.end.row; row += 1) {
    const parts = [];
    for (let col = resolved.range.start.col; col <= resolved.range.end.col; col += 1) {
      const calculated = typeof resolved.sheet.getCalculatedValueAt === "function" ? resolved.sheet.getCalculatedValueAt(row, col) : null;
      const formatted = typeof resolved.sheet.getFormattedValueAt === "function" ? resolved.sheet.getFormattedValueAt(row, col) : calculated;
      const display = cellValueToDisplay(formatted ?? calculated);
      const numeric = cellValueToNumber(calculated ?? formatted);
      const label = display.length > 0 ? display : numeric != null ? String(numeric) : "";
      if (label.length > 0) {
        parts.push(label);
      }
    }
    rows.push(parts);
  }
  return rows;
}
function normalizeChartExLegend(raw) {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const legend = raw;
  const position = typeof legend.position === "string" ? normalizeLegendPosition(String(legend.position)) : void 0;
  return {
    overlay: typeof legend.overlay === "boolean" ? legend.overlay : void 0,
    position,
    raw: legend
  };
}
function humanizeChartExLayoutLabel(layout) {
  if (!layout) {
    return void 0;
  }
  return layout.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/[-_]+/g, " ").trim().replace(/\b\w/g, (match) => match.toUpperCase());
}
function normalizeChartExAxis(raw) {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const axis = raw;
  const scaling = axis.scaling && typeof axis.scaling === "object" ? axis.scaling : null;
  const numberFormat = axis.numberFormat && typeof axis.numberFormat === "object" ? axis.numberFormat : null;
  return {
    delete: typeof axis.hidden === "boolean" ? axis.hidden : void 0,
    id: typeof axis.id === "number" && Number.isFinite(axis.id) ? axis.id : void 0,
    crossId: typeof axis.crossId === "number" && Number.isFinite(axis.crossId) ? axis.crossId : void 0,
    majorGridlines: axis.majorGridlines != null ? true : void 0,
    majorUnit: typeof scaling?.majorUnit === "number" ? scaling.majorUnit : void 0,
    max: typeof scaling?.max === "number" ? scaling.max : void 0,
    min: typeof scaling?.min === "number" ? scaling.min : void 0,
    minorGridlines: axis.minorGridlines != null ? true : void 0,
    minorUnit: typeof scaling?.minorUnit === "number" ? scaling.minorUnit : void 0,
    numberFormat: numberFormat ? {
      formatCode: typeof numberFormat.formatCode === "string" ? numberFormat.formatCode : void 0,
      sourceLinked: typeof numberFormat.sourceLinked === "boolean" ? numberFormat.sourceLinked : void 0
    } : void 0,
    raw: axis,
    position: typeof axis.position === "string" ? axis.position : void 0,
    tickLabelSkip: typeof axis.tickLabelSkip === "number" ? axis.tickLabelSkip : void 0,
    tickMarkSkip: typeof axis.tickMarkSkip === "number" ? axis.tickMarkSkip : void 0
  };
}
function resolveChartExLayoutChartType(layout) {
  switch (layout) {
    case "boxWhisker":
      return "BoxWhisker";
    case "clusteredColumn":
      return "ColumnClustered";
    case "funnel":
      return "Funnel";
    case "paretoLine":
      return "Line";
    case "regionMap":
      return "RegionMap";
    case "sunburst":
      return "Sunburst";
    case "treemap":
      return "Treemap";
    case "waterfall":
      return "Waterfall";
    default:
      return layout ? `Unsupported(cx:${layout})` : "ColumnClustered";
  }
}
function resolveChartExSeriesLayout(raw) {
  if (!raw || typeof raw !== "object") {
    return void 0;
  }
  const record = raw;
  return typeof record.layout === "string" ? record.layout : typeof record.layoutId === "string" ? record.layoutId : void 0;
}
function resolveChartExSeriesAxisIds(raw) {
  if (!raw || typeof raw !== "object") {
    return [];
  }
  const record = raw;
  if (Array.isArray(record.axisIds)) {
    return record.axisIds.filter((value) => typeof value === "number" && Number.isFinite(value));
  }
  if (Array.isArray(record.axisId)) {
    return record.axisId.flatMap((value) => {
      if (typeof value === "number" && Number.isFinite(value)) {
        return [value];
      }
      if (value && typeof value === "object" && typeof value.val === "number") {
        return [value.val];
      }
      return [];
    });
  }
  if (typeof record.axisId === "number" && Number.isFinite(record.axisId)) {
    return [record.axisId];
  }
  return [];
}
function niceHistogramStep(value) {
  if (!Number.isFinite(value) || value <= 0) {
    return 1;
  }
  const exponent = Math.floor(Math.log10(value));
  const scale = 10 ** exponent;
  const normalized = value / scale;
  if (normalized <= 1) {
    return scale;
  }
  if (normalized <= 2) {
    return scale * 2;
  }
  if (normalized <= 5) {
    return scale * 5;
  }
  return scale * 10;
}
function formatHistogramBinLabel(lower, upper, index, closedRight) {
  const leftBracket = closedRight ? index === 0 ? "[" : "(" : "[";
  const rightBracket = closedRight ? "]" : ")";
  return `${leftBracket}${Number(lower.toFixed(6))},${Number(upper.toFixed(6))}${rightBracket}`;
}
function buildChartExHistogramBins(values, rawSeries, sortByFrequency) {
  if (values.length === 0) {
    return [];
  }
  const rawRecord = rawSeries && typeof rawSeries === "object" ? rawSeries : null;
  const layoutProperties = rawRecord?.layoutProperties && typeof rawRecord.layoutProperties === "object" ? rawRecord.layoutProperties : null;
  const rawBinning = layoutProperties?.binning && typeof layoutProperties.binning === "object" ? layoutProperties.binning : null;
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const explicitWidth = typeof rawBinning?.binSize === "number" && Number.isFinite(rawBinning.binSize) && rawBinning.binSize > 0 ? rawBinning.binSize : void 0;
  const explicitCount = typeof rawBinning?.binCount === "number" && Number.isFinite(rawBinning.binCount) && rawBinning.binCount > 0 ? rawBinning.binCount : typeof rawBinning?.count === "number" && Number.isFinite(rawBinning.count) && rawBinning.count > 0 ? rawBinning.count : void 0;
  const closedRight = rawBinning?.intervalClosed === "r" || rawBinning?.intervalClosed === "right";
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(1, values.length);
  const standardDeviation = Math.sqrt(Math.max(0, variance));
  const allIntegers = values.every((value) => Math.abs(value - Math.round(value)) < 1e-9);
  const scottWidth = standardDeviation > 0 ? 3.49 * standardDeviation / Math.cbrt(values.length) : void 0;
  const fallbackWidth = explicitCount != null ? (maxValue - minValue) / Math.max(1, explicitCount) : scottWidth ?? (maxValue - minValue) / Math.max(1, Math.ceil(Math.log2(values.length) + 1));
  const roughWidth = explicitWidth ?? (allIntegers ? Math.max(1, Math.ceil(Math.max(fallbackWidth, 1e-6))) : niceHistogramStep(Math.max(fallbackWidth, 1e-6)));
  const binWidth = Math.max(roughWidth, 1e-6);
  const start = explicitWidth != null || explicitCount != null ? Math.floor(minValue / binWidth) * binWidth : minValue;
  const end = Math.max(start + binWidth, start + Math.ceil((maxValue - start) / binWidth) * binWidth);
  const binCount = Math.max(1, Math.ceil((end - start) / binWidth));
  const bins = Array.from({ length: binCount }, (_, index) => {
    const lower = start + binWidth * index;
    const upper = lower + binWidth;
    return {
      count: 0,
      label: formatHistogramBinLabel(lower, upper, index, closedRight),
      lower,
      upper
    };
  });
  values.forEach((value) => {
    if (!Number.isFinite(value)) {
      return;
    }
    const offset = (value - start) / binWidth;
    let binIndex = Math.floor(offset);
    if (closedRight && Math.abs(offset - Math.round(offset)) < 1e-9 && value > start) {
      binIndex -= 1;
    }
    if (value >= end) {
      binIndex = bins.length - 1;
    }
    if (value <= start) {
      binIndex = 0;
    }
    const target = bins[Math.max(0, Math.min(bins.length - 1, binIndex))];
    if (target) {
      target.count += 1;
    }
  });
  if (sortByFrequency) {
    bins.sort((left, right) => right.count - left.count || left.lower - right.lower);
  }
  return bins;
}
function buildChartExHistogramSeries(series, rawSeries, sortByFrequency) {
  const layout = resolveChartExSeriesLayout(rawSeries);
  const rawRecord = rawSeries && typeof rawSeries === "object" ? rawSeries : null;
  const hasBinning = Boolean(
    layout === "clusteredColumn" && rawRecord?.layoutProperties && typeof rawRecord.layoutProperties === "object" && rawRecord.layoutProperties.binning != null
  );
  if (!hasBinning) {
    return series;
  }
  const numericValues = series.values.filter((value) => typeof value === "number" && Number.isFinite(value));
  if (numericValues.length === 0) {
    return series;
  }
  const bins = buildChartExHistogramBins(numericValues, rawSeries, sortByFrequency);
  if (bins.length === 0) {
    return series;
  }
  return {
    ...series,
    categories: bins.map((bin) => bin.label),
    categoriesRef: null,
    raw: {
      ...series.raw,
      chartExHistogramBins: bins,
      chartExSourceValues: numericValues
    },
    values: bins.map((bin) => bin.count)
  };
}
function buildChartExParetoLineSeries(series, sourceRaw, index) {
  const counts = series.values.map((value) => typeof value === "number" && Number.isFinite(value) ? value : 0);
  const total = counts.reduce((sum, value) => sum + value, 0);
  let running = 0;
  const cumulative = counts.map((value) => {
    running += value;
    return total > 0 ? running / total * 100 : 0;
  });
  return {
    ...series,
    id: series.id.replace(/-series-\d+$/, `-series-${index}`),
    color: void 0,
    lineColor: void 0,
    markerColor: void 0,
    markerLineColor: void 0,
    markerSize: 7,
    markerSymbol: "circle",
    name: typeof sourceRaw?.text === "string" ? sourceRaw.text : "Pareto",
    raw: {
      ...series.raw ?? {},
      chartExLayout: "paretoLine",
      source: sourceRaw && typeof sourceRaw === "object" ? sourceRaw : void 0
    },
    values: cumulative
  };
}
function resolveChartExTextFormula(raw) {
  if (typeof raw === "string" && raw.length > 0) {
    return raw;
  }
  if (!raw || typeof raw !== "object") {
    return void 0;
  }
  const record = raw;
  if (typeof record.formula === "string" && record.formula.length > 0) {
    return record.formula;
  }
  if (typeof record.text === "string" && record.text.length > 0) {
    return record.text;
  }
  if (typeof record.value === "string" && record.value.length > 0) {
    return record.value;
  }
  return void 0;
}
function resolveChartExTitleText(raw) {
  if (typeof raw === "string" && raw.length > 0) {
    return raw;
  }
  if (!raw || typeof raw !== "object") {
    return void 0;
  }
  const record = raw;
  if (typeof record.text === "string" && record.text.length > 0) {
    return record.text;
  }
  const nestedText = record.text && typeof record.text === "object" ? resolveChartExTextFormula(record.text) : void 0;
  if (nestedText) {
    return nestedText;
  }
  return typeof record.value === "string" && record.value.length > 0 ? record.value : void 0;
}
function resolveChartExFallbackCategoryReference(workbook, fallbackSheetIndex, valueFormula) {
  if (!valueFormula) {
    return null;
  }
  const resolved = resolveReferenceSheet(workbook, fallbackSheetIndex, valueFormula);
  if (!resolved.sheet || !resolved.range || resolved.range.start.col <= 0) {
    return null;
  }
  return normalizeChartReference({
    formula: buildA1RangeFormula(
      resolved.sheetName,
      {
        col: resolved.range.start.col - 1,
        row: resolved.range.start.row
      },
      {
        col: resolved.range.start.col - 1,
        row: resolved.range.end.row
      }
    )
  });
}
function normalizeChartExSeries(workbook, workbookSheetIndex, chartId, raw, dataById, index, chartType) {
  const series = raw && typeof raw === "object" ? raw : {};
  const dataId = typeof series.dataId === "number" ? series.dataId : null;
  const dataEntry = dataId != null ? dataById.get(dataId) ?? null : null;
  const dimensions = Array.isArray(dataEntry?.dimensions) ? dataEntry.dimensions.filter((value) => Boolean(value && typeof value === "object")) : [];
  const categoryDimension = dimensions.find((dimension) => dimension.dimType === "cat") ?? dimensions.find((dimension) => dimension.dimType === "name") ?? null;
  const valueDimension = dimensions.find((dimension) => dimension.dimType === "val" || dimension.dimType === "y" || dimension.dimType === "colorVal" || dimension.dimType === "size") ?? dimensions.find((dimension) => dimension !== categoryDimension) ?? categoryDimension;
  const categoryDimensionFormula = typeof categoryDimension?.formula === "string" ? categoryDimension.formula : void 0;
  const valueDimensionFormula = typeof valueDimension?.formula === "string" ? valueDimension.formula : void 0;
  const fallbackCategoryRef = (chartType === "Sunburst" || chartType === "Treemap") && !categoryDimension && typeof valueDimensionFormula === "string" ? resolveChartExFallbackCategoryReference(workbook, workbookSheetIndex, valueDimensionFormula) : null;
  const categoriesRef = categoryDimension ? normalizeChartReference({
    formula: categoryDimensionFormula
  }) : fallbackCategoryRef;
  const valuesRef = valueDimension ? normalizeChartReference({
    formula: valueDimensionFormula
  }) : null;
  const isCategoricalMap = chartType === "RegionMap" && valueDimension?.dimType === "colorStr";
  const resolvedValueCells = resolveReferenceValues(workbook, workbookSheetIndex, valuesRef, isCategoricalMap ? "category" : "value");
  const values = resolvedValueCells.map((value) => typeof value === "number" && Number.isFinite(value) ? value : null);
  const colorStrings = isCategoricalMap ? resolvedValueCells.map((value) => {
    if (typeof value === "string") {
      const trimmed = value.trim();
      return trimmed.length > 0 ? trimmed : null;
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      return String(value);
    }
    return null;
  }) : [];
  const categoryRows = chartType === "RegionMap" ? resolveReferenceRowPaths(workbook, workbookSheetIndex, categoriesRef) : [];
  const categories = categoryRows.length === resolvedValueCells.length && categoryRows.length > 0 ? categoryRows.map((parts) => parts[0] ?? "") : resolveReferenceValues(workbook, workbookSheetIndex, categoriesRef, "category");
  const hierarchyCategories = chartType === "Sunburst" || chartType === "Treemap" ? resolveReferenceRowPaths(workbook, workbookSheetIndex, categoriesRef) : [];
  const seriesTextFormula = resolveChartExTextFormula(series.text);
  const shapeProperties = series.shapeProperties && typeof series.shapeProperties === "object" ? series.shapeProperties : void 0;
  const rawFillColor = typeof shapeProperties?.solidFillHex === "string" ? normalizeHexColor3(shapeProperties.solidFillHex) : null;
  const rawLineColor = typeof shapeProperties?.lineColorHex === "string" ? normalizeHexColor3(shapeProperties.lineColorHex) : null;
  return {
    bubbleSizeRef: null,
    bubbleSizes: [],
    categories,
    categoriesRef,
    color: rawFillColor ?? void 0,
    dataPoints: Array.isArray(series.dataPoints) ? series.dataPoints : [],
    dataPointStyles: void 0,
    formatIdx: typeof series.formatIdx === "number" ? series.formatIdx : void 0,
    hidden: typeof series.hidden === "boolean" ? series.hidden : void 0,
    id: `${chartId}-series-${index}`,
    invertIfNegative: void 0,
    lineColor: rawLineColor ?? rawFillColor ?? void 0,
    lineWidthPx: typeof shapeProperties?.lineWidth === "number" ? Math.max(1, Number(shapeProperties.lineWidth) / EMU_PER_PIXEL2) : void 0,
    marker: void 0,
    markerColor: rawFillColor ?? void 0,
    markerLineColor: rawLineColor ?? rawFillColor ?? void 0,
    markerSize: void 0,
    markerSymbol: void 0,
    name: typeof series.text === "string" ? series.text : seriesTextFormula ? resolveSeriesName(workbook, workbookSheetIndex, seriesTextFormula) : void 0,
    negativeColor: void 0,
    negativeLineColor: void 0,
    raw: {
      ...series,
      chartExColorStrings: colorStrings,
      chartExHierarchyCategories: hierarchyCategories,
      data: dataEntry,
      dimType: typeof valueDimension?.dimType === "string" ? valueDimension.dimType : void 0
    },
    shapeProperties,
    smooth: void 0,
    values,
    valuesRef
  };
}
function collapseChartExPointSeries(chartType, series) {
  if (chartType !== "Funnel" && chartType !== "Waterfall") {
    if ((chartType === "Sunburst" || chartType === "Treemap") && series.length > 1 && series.every((entry) => {
      const raw = entry.raw && typeof entry.raw === "object" ? entry.raw : null;
      return raw?.dimType === "size";
    })) {
      const primarySeries2 = series.find((entry) => entry.hidden !== true) ?? series[0] ?? null;
      if (!primarySeries2) {
        return series;
      }
      return [
        {
          ...primarySeries2,
          dataPoints: [],
          hidden: false
        }
      ];
    }
    return series;
  }
  const primarySeries = series.find((entry) => entry.hidden !== true) ?? series[0] ?? null;
  if (!primarySeries) {
    return series;
  }
  return [
    {
      ...primarySeries,
      categories: [],
      categoriesRef: null,
      dataPoints: [],
      hidden: false
    }
  ];
}
function normalizeChartExChart(workbook, workbookSheetIndex, visibleSheetIndex, raw, index, themePalette) {
  const drawing = raw && typeof raw === "object" ? raw : {};
  const chart = drawing.chartEx && typeof drawing.chartEx === "object" ? drawing.chartEx : {};
  const plotArea = chart.plotArea && typeof chart.plotArea === "object" ? chart.plotArea : {};
  const rawSeries = Array.isArray(plotArea.series) ? plotArea.series : [];
  const seriesLayouts = rawSeries.map(resolveChartExSeriesLayout);
  const dataEntries = Array.isArray(chart.data) ? chart.data : [];
  const dataById = /* @__PURE__ */ new Map();
  dataEntries.forEach((entry) => {
    if (!entry || typeof entry !== "object") {
      return;
    }
    const record = entry;
    if (typeof record.id === "number") {
      dataById.set(record.id, record);
    }
  });
  const axes = Array.isArray(plotArea.axes) ? plotArea.axes.map(normalizeChartExAxis).filter((value) => Boolean(value)) : [];
  const primaryLayout = typeof chart.layout === "string" ? chart.layout : seriesLayouts.find((value) => typeof value === "string" && value.length > 0);
  const fallbackTitle = humanizeChartExLayoutLabel(primaryLayout);
  const chartTitle = resolveChartExTitleText(chart.title) ?? (chart.title != null ? "Chart Title" : fallbackTitle);
  const chartType = resolveChartExLayoutChartType(primaryLayout);
  const normalizedSeries = rawSeries.map((entry, seriesIndex) => normalizeChartExSeries(workbook, workbookSheetIndex, `chart-ex-${workbookSheetIndex}-${index}`, entry, dataById, seriesIndex, chartType));
  const clusteredColumnSeriesIndex = seriesLayouts.findIndex((layout) => layout === "clusteredColumn");
  const hasParetoLine = seriesLayouts.includes("paretoLine");
  const clusteredColumnAxisIds = clusteredColumnSeriesIndex >= 0 ? resolveChartExSeriesAxisIds(rawSeries[clusteredColumnSeriesIndex]) : [];
  const paretoLineSeriesIndex = seriesLayouts.findIndex((layout) => layout === "paretoLine");
  const paretoLineAxisIds = paretoLineSeriesIndex >= 0 ? resolveChartExSeriesAxisIds(rawSeries[paretoLineSeriesIndex]) : [];
  const primaryHistogramSeries = clusteredColumnSeriesIndex >= 0 ? buildChartExHistogramSeries(normalizedSeries[clusteredColumnSeriesIndex] ?? normalizedSeries[0], rawSeries[clusteredColumnSeriesIndex], hasParetoLine) : null;
  const synthesizedParetoSeries = hasParetoLine && primaryHistogramSeries && primaryHistogramSeries.values.length > 0 ? buildChartExParetoLineSeries(primaryHistogramSeries, rawSeries[paretoLineSeriesIndex], paretoLineSeriesIndex) : null;
  const resolvedSeries = synthesizedParetoSeries ? [primaryHistogramSeries, synthesizedParetoSeries] : primaryHistogramSeries ? [
    primaryHistogramSeries,
    ...normalizedSeries.filter((_, seriesIndex) => seriesIndex !== clusteredColumnSeriesIndex)
  ] : collapseChartExPointSeries(chartType, normalizedSeries);
  const resolvedChartType = primaryHistogramSeries ? "ColumnClustered" : chartType;
  const resolvedGapWidth = primaryHistogramSeries ? 0 : void 0;
  const typeGroups = synthesizedParetoSeries ? [
    {
      axisIds: clusteredColumnAxisIds,
      chartType: "ColumnClustered",
      gapWidth: 0,
      raw: {
        gapWidth: 0,
        layout: "clusteredColumn"
      },
      series: [primaryHistogramSeries]
    },
    {
      axisIds: paretoLineAxisIds,
      chartType: "Line",
      raw: {
        layout: "paretoLine"
      },
      series: [synthesizedParetoSeries]
    }
  ] : [];
  const normalizedChart = {
    anchor: normalizeChartAnchor(drawing.anchor),
    autoTitleDeleted: void 0,
    axes,
    axisLabelColor: void 0,
    axisLineColor: void 0,
    categoryAxis: axes[0] ?? null,
    chartAreaBorderColor: void 0,
    chartAreaFillColor: void 0,
    chartColorPalette: void 0,
    chartColorPaletteOffset: void 0,
    chartExLayout: primaryLayout,
    chartPath: void 0,
    chartStyleId: void 0,
    chartType: resolvedChartType,
    dataLabels: rawSeries.length > 0 && rawSeries[0] && typeof rawSeries[0] === "object" ? normalizeChartDataLabels(rawSeries[0].dataLabels) : null,
    displayBlanksAs: void 0,
    editable: true,
    firstSliceAngle: void 0,
    fontFamily: void 0,
    gapWidth: resolvedGapWidth,
    holeSize: void 0,
    id: `chart-ex-${workbookSheetIndex}-${index}`,
    is3d: void 0,
    legend: normalizeChartExLegend(chart.legend),
    name: typeof drawing.name === "string" ? drawing.name : chartTitle,
    overlap: void 0,
    plotVisibleOnly: void 0,
    raw: { ...chart, officeSourceSeries: normalizedSeries },
    radarStyle: void 0,
    scatterStyle: void 0,
    roundedCorners: void 0,
    shape3d: void 0,
    seriesAxis: null,
    series: resolvedSeries,
    sheetIndex: visibleSheetIndex,
    showDlblsOverMax: void 0,
    sideWall: null,
    backWall: null,
    bubbleScale: void 0,
    bubble3d: void 0,
    floor: null,
    surfaceMaterial: void 0,
    textColor: void 0,
    title: chartTitle,
    titleColor: void 0,
    titleFontFamily: void 0,
    typeGroups,
    valueAxis: axes.find((axis) => axis.numberFormat || axis.majorGridlines) ?? axes[1] ?? null,
    varyColors: typeof chart.valueColors === "boolean" ? chart.valueColors : void 0,
    view3d: void 0,
    wireframe: void 0,
    workbookSheetIndex,
    zIndex: Array.isArray(drawing.drawingPath) && typeof drawing.drawingPath[0] === "number" ? drawing.drawingPath[0] + 1 : index + 1
  };
  applyBuiltinChartDefaults(normalizedChart, themePalette);
  return normalizedChart;
}
function cellValueToNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (value && typeof value === "object") {
    if (value.is_empty) {
      return null;
    }
    if (typeof value.toJs === "function") {
      const primitive = value.toJs();
      if (primitive == null || typeof primitive !== "object") return cellValueToNumber(primitive);
    }
    const candidates = [];
    if (typeof value.asText === "function") {
      candidates.push(value.asText());
    }
    if (typeof value.asNumber === "function") {
      candidates.push(value.asNumber());
    }
    if (typeof value.toString === "function") {
      candidates.push(value.toString());
    }
    for (const candidate of candidates) {
      if (typeof candidate === "number" && Number.isFinite(candidate)) {
        return candidate;
      }
      if (typeof candidate === "string") {
        return cellValueToNumber(candidate);
      }
    }
  }
  if (typeof value === "string") {
    const stripped = value.replace(/,/g, "").trim();
    if (!stripped) return null;
    const parsed = Number(stripped);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}
function cellValueToDisplay(value) {
  if (value === null || value === void 0) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value && typeof value === "object") {
    if (value.is_empty) {
      return "";
    }
    const candidates = [];
    if (typeof value.asText === "function") {
      candidates.push(value.asText());
    }
    if (typeof value.toJs === "function") {
      candidates.push(value.toJs());
    }
    if (typeof value.toString === "function") {
      candidates.push(value.toString());
    }
    for (const candidate of candidates) {
      if (candidate === null || candidate === void 0) {
        continue;
      }
      if (typeof candidate === "string") {
        return candidate;
      }
      return String(candidate);
    }
  }
  return String(value);
}
function resolveReferenceValues(workbook, fallbackSheetIndex, reference, mode) {
  if (!reference?.formula) {
    return reference?.values ?? [];
  }
  const resolved = resolveReferenceSheet(workbook, fallbackSheetIndex, reference.formula);
  if (!resolved.sheet || !resolved.range) {
    return reference.values ?? [];
  }
  const values = [];
  for (let row = resolved.range.start.row; row <= resolved.range.end.row; row += 1) {
    for (let col = resolved.range.start.col; col <= resolved.range.end.col; col += 1) {
      const calculated = typeof resolved.sheet.getCalculatedValueAt === "function" ? resolved.sheet.getCalculatedValueAt(row, col) : null;
      const formatted = typeof resolved.sheet.getFormattedValueAt === "function" ? resolved.sheet.getFormattedValueAt(row, col) : calculated;
      if (mode === "value") {
        values.push(cellValueToNumber(calculated ?? formatted));
      } else {
        const display = cellValueToDisplay(formatted ?? calculated);
        const numeric = cellValueToNumber(calculated ?? formatted);
        values.push(display.length > 0 ? display : numeric !== null ? numeric : null);
      }
    }
  }
  return values;
}
function resolveSeriesName(workbook, fallbackSheetIndex, rawName) {
  if (typeof rawName !== "string" || !rawName) {
    return void 0;
  }
  const resolved = resolveReferenceSheet(workbook, fallbackSheetIndex, rawName);
  if (!resolved.sheet || !resolved.range) {
    return rawName;
  }
  const value = typeof resolved.sheet.getFormattedValueAt === "function" ? resolved.sheet.getFormattedValueAt(resolved.range.start.row, resolved.range.start.col) : null;
  const display = cellValueToDisplay(value);
  return display || rawName;
}
function normalizeChartReference(raw) {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const record = raw;
  const values = Array.isArray(record.numbers) ? record.numbers : Array.isArray(record.strings) ? record.strings : void 0;
  return {
    formula: typeof record.formula === "string" ? record.formula : void 0,
    refType: typeof record.refType === "string" ? record.refType : void 0,
    values
  };
}
function normalizeChartAxis(raw) {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const rawAxis = raw;
  const axis = rawAxis.axis && typeof rawAxis.axis === "object" ? rawAxis.axis : rawAxis;
  const numberFormat = axis.numberFormat && typeof axis.numberFormat === "object" ? axis.numberFormat : null;
  return {
    crossId: typeof rawAxis.crossId === "number" && Number.isFinite(rawAxis.crossId) ? rawAxis.crossId : void 0,
    crosses: typeof axis.crosses === "string" ? axis.crosses : void 0,
    crossBetween: typeof axis.crossBetween === "string" ? axis.crossBetween : void 0,
    delete: typeof axis.delete === "boolean" ? axis.delete : void 0,
    id: typeof rawAxis.id === "number" && Number.isFinite(rawAxis.id) ? rawAxis.id : void 0,
    labelPosition: typeof axis.labelPosition === "string" ? axis.labelPosition : void 0,
    logBase: typeof axis.logBase === "number" ? axis.logBase : void 0,
    orientation: typeof axis.orientation === "string" ? axis.orientation : void 0,
    majorUnit: typeof axis.majorUnit === "number" ? axis.majorUnit : void 0,
    max: typeof axis.maximum === "number" ? axis.maximum : void 0,
    min: typeof axis.minimum === "number" ? axis.minimum : void 0,
    majorGridlines: typeof axis.majorGridlines === "boolean" ? axis.majorGridlines : void 0,
    majorTickMark: typeof axis.majorTickMark === "string" ? axis.majorTickMark : void 0,
    minorUnit: typeof axis.minorUnit === "number" ? axis.minorUnit : void 0,
    minorGridlines: typeof axis.minorGridlines === "boolean" ? axis.minorGridlines : void 0,
    minorTickMark: typeof axis.minorTickMark === "string" ? axis.minorTickMark : void 0,
    numberFormat: numberFormat ? {
      formatCode: typeof numberFormat.formatCode === "string" ? numberFormat.formatCode : void 0,
      sourceLinked: typeof numberFormat.sourceLinked === "boolean" ? numberFormat.sourceLinked : void 0
    } : void 0,
    position: typeof axis.position === "string" ? axis.position : void 0,
    raw: axis,
    shapeProperties: axis.shapeProperties && typeof axis.shapeProperties === "object" ? axis.shapeProperties : void 0,
    tickLabelSkip: typeof axis.tickLabelSkip === "number" && Number.isFinite(axis.tickLabelSkip) ? axis.tickLabelSkip : void 0,
    tickMarkSkip: typeof axis.tickMarkSkip === "number" && Number.isFinite(axis.tickMarkSkip) ? axis.tickMarkSkip : void 0
  };
}
function mergeChartAxis(target, patch) {
  if (!patch) {
    return target ?? null;
  }
  return {
    ...target ?? {},
    ...patch
  };
}
function readChartAxisFromXml(axisNode, themePalette) {
  if (!axisNode) {
    return null;
  }
  const numFmt = getFirstLocalChild(axisNode, "numFmt");
  const scalingNode = getFirstLocalChild(axisNode, "scaling");
  return {
    crossId: readChartNumericAttribute(axisNode, "crossAx"),
    crosses: getFirstLocalChild(axisNode, "crosses")?.getAttribute("val") ?? void 0,
    crossBetween: getFirstLocalChild(axisNode, "crossBetween")?.getAttribute("val") ?? void 0,
    delete: getFirstLocalChild(axisNode, "delete")?.getAttribute("val") === "1" ? true : getFirstLocalChild(axisNode, "delete")?.getAttribute("val") === "0" ? false : void 0,
    id: readChartNumericAttribute(axisNode, "axId"),
    labelPosition: getFirstLocalChild(axisNode, "tickLblPos")?.getAttribute("val") ?? void 0,
    logBase: readChartNumericAttribute(getFirstLocalChild(axisNode, "scaling"), "logBase"),
    orientation: getFirstLocalChild(scalingNode ?? axisNode, "orientation")?.getAttribute("val") ?? void 0,
    majorGridlines: Boolean(getFirstLocalChild(axisNode, "majorGridlines")),
    majorGridlineColor: (() => {
      const style = resolveChartLineStyle(getFirstLocalChild(getFirstLocalChild(axisNode, "majorGridlines"), "spPr"), themePalette);
      return style.hidden ? "transparent" : style.color ?? void 0;
    })(),
    majorTickMark: getFirstLocalChild(axisNode, "majorTickMark")?.getAttribute("val") ?? void 0,
    majorUnit: readChartNumericAttribute(axisNode, "majorUnit"),
    max: readChartNumericAttribute(scalingNode, "max"),
    min: readChartNumericAttribute(scalingNode, "min"),
    minorGridlines: Boolean(getFirstLocalChild(axisNode, "minorGridlines")),
    minorTickMark: getFirstLocalChild(axisNode, "minorTickMark")?.getAttribute("val") ?? void 0,
    minorUnit: readChartNumericAttribute(axisNode, "minorUnit"),
    numberFormat: numFmt ? {
      formatCode: numFmt.getAttribute("formatCode") ?? void 0,
      sourceLinked: numFmt.getAttribute("sourceLinked") === "1" ? true : numFmt.getAttribute("sourceLinked") === "0" ? false : void 0
    } : void 0,
    position: getFirstLocalChild(axisNode, "axPos")?.getAttribute("val") ?? void 0,
    tickLabelSkip: readChartNumericAttribute(axisNode, "tickLblSkip"),
    tickMarkSkip: readChartNumericAttribute(axisNode, "tickMarkSkip")
  };
}
function readChartWallFromXml(wallNode, themePalette) {
  if (!wallNode) {
    return null;
  }
  const shapeProperties = getFirstLocalChild(wallNode, "spPr");
  const lineStyle = resolveChartLineStyle(shapeProperties, themePalette);
  return {
    fillColor: resolveChartFillColor(shapeProperties, themePalette) ?? void 0,
    hidden: shapeProperties ? getFirstLocalChild(shapeProperties, "noFill") != null : void 0,
    lineColor: lineStyle.color ?? void 0,
    thickness: readChartNumericAttribute(wallNode, "thickness")
  };
}
function normalizeChartDataLabels(raw) {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const labels = raw;
  const pointLabels = Array.isArray(labels.pointLabels) ? (() => {
    const normalized = [];
    for (const entry of labels.pointLabels) {
      if (!entry || typeof entry !== "object") {
        continue;
      }
      const point = entry;
      const index = typeof point.index === "number" && Number.isFinite(point.index) ? point.index : null;
      if (index == null) {
        continue;
      }
      const nextPoint = { index };
      if (typeof point.deleted === "boolean") {
        nextPoint.deleted = point.deleted;
      }
      if (typeof point.fontSizePt === "number" && Number.isFinite(point.fontSizePt)) {
        nextPoint.fontSizePt = point.fontSizePt;
      }
      if (typeof point.showBubbleSize === "boolean") {
        nextPoint.showBubbleSize = point.showBubbleSize;
      }
      if (typeof point.showCategoryName === "boolean") {
        nextPoint.showCategoryName = point.showCategoryName;
      }
      if (typeof point.showPercent === "boolean") {
        nextPoint.showPercent = point.showPercent;
      }
      if (typeof point.showSeriesName === "boolean") {
        nextPoint.showSeriesName = point.showSeriesName;
      }
      if (typeof point.showValue === "boolean") {
        nextPoint.showValue = point.showValue;
      }
      if (typeof point.x === "number" && Number.isFinite(point.x)) {
        nextPoint.x = point.x;
      }
      if (typeof point.y === "number" && Number.isFinite(point.y)) {
        nextPoint.y = point.y;
      }
      normalized.push(nextPoint);
    }
    return normalized;
  })() : void 0;
  return {
    pointLabels: pointLabels && pointLabels.length > 0 ? pointLabels : void 0,
    raw: labels,
    showBubbleSize: typeof labels.showBubbleSize === "boolean" ? labels.showBubbleSize : void 0,
    showCategoryName: typeof (labels.showCategoryName ?? labels.visibilityCategoryName) === "boolean" ? Boolean(labels.showCategoryName ?? labels.visibilityCategoryName) : void 0,
    showLegendKey: typeof labels.showLegendKey === "boolean" ? labels.showLegendKey : void 0,
    showPercent: typeof labels.showPercent === "boolean" ? labels.showPercent : void 0,
    showSeriesName: typeof (labels.showSeriesName ?? labels.visibilitySeriesName) === "boolean" ? Boolean(labels.showSeriesName ?? labels.visibilitySeriesName) : void 0,
    showValue: typeof (labels.showValue ?? labels.visibilityValue) === "boolean" ? Boolean(labels.showValue ?? labels.visibilityValue) : void 0
  };
}
function normalizeChartAnchor(raw) {
  if (!raw || typeof raw !== "object") {
    return {
      kind: "two-cell",
      from: { col: 0, colOffsetEmu: 0, row: 0, rowOffsetEmu: 0 },
      to: { col: 8, colOffsetEmu: 0, row: 15, rowOffsetEmu: 0 }
    };
  }
  const anchor = raw;
  const from = anchor.from && typeof anchor.from === "object" ? anchor.from : null;
  if (anchor.type === "oneCell") {
    return {
      from: {
        col: typeof from?.col === "number" ? from.col : 0,
        colOffsetEmu: typeof from?.colOffsetEmu === "number" ? from.colOffsetEmu : 0,
        row: typeof from?.row === "number" ? from.row : 0,
        rowOffsetEmu: typeof from?.rowOffsetEmu === "number" ? from.rowOffsetEmu : 0
      },
      kind: "one-cell",
      sizeEmu: {
        cx: typeof anchor.widthEmu === "number" ? anchor.widthEmu : 0,
        cy: typeof anchor.heightEmu === "number" ? anchor.heightEmu : 0
      }
    };
  }
  if (anchor.type === "absolute") {
    return {
      kind: "absolute",
      positionEmu: {
        x: typeof anchor.xEmu === "number" ? anchor.xEmu : 0,
        y: typeof anchor.yEmu === "number" ? anchor.yEmu : 0
      },
      sizeEmu: {
        cx: typeof anchor.widthEmu === "number" ? anchor.widthEmu : 0,
        cy: typeof anchor.heightEmu === "number" ? anchor.heightEmu : 0
      }
    };
  }
  const to = anchor.to && typeof anchor.to === "object" ? anchor.to : null;
  const fromColValue = from?.col;
  const fromColOffsetValue = from?.colOffsetEmu;
  const fromRowValue = from?.row;
  const fromRowOffsetValue = from?.rowOffsetEmu;
  const toColValue = to?.col;
  const toColOffsetValue = to?.colOffsetEmu;
  const toRowValue = to?.row;
  const toRowOffsetValue = to?.rowOffsetEmu;
  const fromCol = typeof fromColValue === "number" ? fromColValue : 0;
  const fromColOffsetEmu = typeof fromColOffsetValue === "number" ? fromColOffsetValue : 0;
  const fromRow = typeof fromRowValue === "number" ? fromRowValue : 0;
  const fromRowOffsetEmu = typeof fromRowOffsetValue === "number" ? fromRowOffsetValue : 0;
  const rawToCol = typeof toColValue === "number" ? toColValue : 0;
  const rawToColOffsetEmu = typeof toColOffsetValue === "number" ? toColOffsetValue : 0;
  const rawToRow = typeof toRowValue === "number" ? toRowValue : 0;
  const rawToRowOffsetEmu = typeof toRowOffsetValue === "number" ? toRowOffsetValue : 0;
  return {
    kind: "two-cell",
    from: {
      col: fromCol,
      colOffsetEmu: fromColOffsetEmu,
      row: fromRow,
      rowOffsetEmu: fromRowOffsetEmu
    },
    to: {
      col: rawToCol,
      colOffsetEmu: rawToColOffsetEmu,
      row: rawToRow,
      rowOffsetEmu: rawToRowOffsetEmu
    }
  };
}
function parseMarkerNode(node) {
  if (!node) {
    return null;
  }
  const col = Number(getFirstLocalChild(node, "col")?.textContent ?? Number.NaN);
  const row = Number(getFirstLocalChild(node, "row")?.textContent ?? Number.NaN);
  const colOffsetEmu = Number(getFirstLocalChild(node, "colOff")?.textContent ?? 0);
  const rowOffsetEmu = Number(getFirstLocalChild(node, "rowOff")?.textContent ?? 0);
  if (!Number.isFinite(col) || !Number.isFinite(row)) {
    return null;
  }
  return {
    col: Math.max(0, Math.round(col)),
    colOffsetEmu: Number.isFinite(colOffsetEmu) ? Math.max(0, Math.round(colOffsetEmu)) : 0,
    row: Math.max(0, Math.round(row)),
    rowOffsetEmu: Number.isFinite(rowOffsetEmu) ? Math.max(0, Math.round(rowOffsetEmu)) : 0
  };
}
function parseChartAnchorNode(anchorNode) {
  if (anchorNode.localName === "twoCellAnchor") {
    const from = parseMarkerNode(getFirstLocalChild(anchorNode, "from"));
    const to = parseMarkerNode(getFirstLocalChild(anchorNode, "to"));
    return from && to ? { from, kind: "two-cell", to } : null;
  }
  if (anchorNode.localName === "oneCellAnchor") {
    const from = parseMarkerNode(getFirstLocalChild(anchorNode, "from"));
    const ext2 = getFirstLocalChild(anchorNode, "ext");
    const cx2 = Number(ext2?.getAttribute("cx") ?? Number.NaN);
    const cy2 = Number(ext2?.getAttribute("cy") ?? Number.NaN);
    return from && Number.isFinite(cx2) && Number.isFinite(cy2) ? {
      from,
      kind: "one-cell",
      sizeEmu: {
        cx: Math.max(0, Math.round(cx2)),
        cy: Math.max(0, Math.round(cy2))
      }
    } : null;
  }
  const pos = getFirstLocalChild(anchorNode, "pos");
  const ext = getFirstLocalChild(anchorNode, "ext");
  const x = Number(pos?.getAttribute("x") ?? Number.NaN);
  const y = Number(pos?.getAttribute("y") ?? Number.NaN);
  const cx = Number(ext?.getAttribute("cx") ?? Number.NaN);
  const cy = Number(ext?.getAttribute("cy") ?? Number.NaN);
  return Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(cx) && Number.isFinite(cy) ? {
    kind: "absolute",
    positionEmu: {
      x: Math.round(x),
      y: Math.round(y)
    },
    sizeEmu: {
      cx: Math.max(0, Math.round(cx)),
      cy: Math.max(0, Math.round(cy))
    }
  } : null;
}
function normalizeChartSeries(workbook, workbookSheetIndex, chartId, raw, index) {
  const series = raw && typeof raw === "object" ? raw : {};
  const categoriesRef = normalizeChartReference(series.categories);
  const valuesRef = normalizeChartReference(series.values);
  const shapeProperties = series.shapeProperties && typeof series.shapeProperties === "object" ? series.shapeProperties : void 0;
  const rawFillColor = typeof shapeProperties?.solidFillHex === "string" ? normalizeHexColor3(shapeProperties.solidFillHex) : null;
  const rawLineColor = typeof shapeProperties?.lineColorHex === "string" ? normalizeHexColor3(shapeProperties.lineColorHex) : null;
  const bubbleSizeRef = normalizeChartReference(series.bubbleSize ?? series.bubbleSizes ?? series.bubbles);
  const categories = resolveReferenceValues(workbook, workbookSheetIndex, categoriesRef, "category");
  return {
    bubbleSizeRef,
    bubbleSizes: resolveReferenceValues(workbook, workbookSheetIndex, bubbleSizeRef, "value").map((value) => typeof value === "number" && Number.isFinite(value) ? value : null),
    categories,
    categoriesRef,
    color: rawFillColor ?? void 0,
    dataPoints: Array.isArray(series.dataPoints) ? series.dataPoints : [],
    dataPointStyles: void 0,
    id: `${chartId}-series-${index}`,
    invertIfNegative: typeof series.invertIfNegative === "boolean" ? series.invertIfNegative : void 0,
    lineColor: rawLineColor ?? rawFillColor ?? void 0,
    lineWidthPx: typeof shapeProperties?.lineWidth === "number" ? Math.max(1, Number(shapeProperties.lineWidth) / EMU_PER_PIXEL2) : void 0,
    marker: series.marker && typeof series.marker === "object" ? series.marker : void 0,
    markerColor: void 0,
    markerLineColor: void 0,
    markerSize: series.marker && typeof series.marker === "object" && typeof series.marker.size === "number" ? Number(series.marker.size) : void 0,
    markerSymbol: series.marker && typeof series.marker === "object" && typeof series.marker.symbol === "string" ? String(series.marker.symbol) : void 0,
    name: resolveSeriesName(workbook, workbookSheetIndex, series.name),
    negativeColor: void 0,
    negativeLineColor: void 0,
    raw: {
      ...series,
      chartCategoryReferenceValues: categories,
      chartCategoryNumericValues: resolveReferenceValues(workbook, workbookSheetIndex, categoriesRef, "value"),
      chartReferenceHiddenCells: Object.fromEntries([categoriesRef, valuesRef, bubbleSizeRef].filter((reference) => reference?.formula).map((reference) => [reference.formula, referenceHiddenCells(workbook, workbookSheetIndex, reference) ?? []])),
      unresolvedCategoriesReference: Boolean(categoriesRef?.formula && !resolveReferenceSheet(workbook, workbookSheetIndex, categoriesRef.formula).sheet),
      unresolvedValuesReference: Boolean(valuesRef?.formula && !resolveReferenceSheet(workbook, workbookSheetIndex, valuesRef.formula).sheet),
      unresolvedBubbleSizeReference: Boolean(bubbleSizeRef?.formula && !resolveReferenceSheet(workbook, workbookSheetIndex, bubbleSizeRef.formula).sheet),
      unresolvedNameReference: typeof series.name === "string" && series.name.includes("!") && !resolveReferenceSheet(workbook, workbookSheetIndex, series.name).sheet
    },
    shapeProperties,
    smooth: typeof series.smooth === "boolean" ? series.smooth : void 0,
    values: resolveReferenceValues(workbook, workbookSheetIndex, valuesRef, "value").map((value) => typeof value === "number" && Number.isFinite(value) ? value : null),
    valuesRef
  };
}
function normalizeChartTypeGroup(workbook, workbookSheetIndex, chartId, raw, index) {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const group = raw;
  const rawSeries = Array.isArray(group.series) ? group.series : [];
  return {
    axisIds: Array.isArray(group.axisIds) ? group.axisIds.filter((value) => typeof value === "number" && Number.isFinite(value)) : void 0,
    chartType: typeof group.chartType === "string" ? group.chartType : "ColumnClustered",
    dataLabels: normalizeChartDataLabels(group.dataLabels),
    gapWidth: typeof group.gapWidth === "number" && Number.isFinite(group.gapWidth) ? group.gapWidth : void 0,
    is3d: typeof group.is3D === "boolean" ? group.is3D : void 0,
    overlap: typeof group.overlap === "number" && Number.isFinite(group.overlap) ? group.overlap : void 0,
    raw: group,
    series: rawSeries.map((entry, seriesIndex) => normalizeChartSeries(workbook, workbookSheetIndex, `${chartId}-group-${index}`, entry, seriesIndex)),
    varyColors: typeof group.varyColors === "boolean" ? group.varyColors : void 0
  };
}
function normalizeChartsheet(raw, index) {
  const chartsheet = raw && typeof raw === "object" ? raw : {};
  return {
    chartIds: Array.isArray(chartsheet.chartIds) ? chartsheet.chartIds.filter((value) => typeof value === "string") : [],
    chartPath: typeof chartsheet.chartPath === "string" ? chartsheet.chartPath : void 0,
    id: `chartsheet-${index}`,
    index,
    name: typeof chartsheet.name === "string" ? chartsheet.name : `Chart ${index + 1}`,
    raw: chartsheet,
    workbookSheetIndex: typeof chartsheet.workbookSheetIndex === "number" ? chartsheet.workbookSheetIndex : void 0
  };
}
function buildTabs(workbook, chartsheets, visibleSheetIndexByWorkbookSheetIndex, showHiddenSheets = false) {
  const rawOrder = Array.isArray(workbook.sheetOrder) ? workbook.sheetOrder : [];
  if (rawOrder.length === 0) {
    return workbook.sheetNames.flatMap((name, index) => {
      const worksheet = workbook.getSheet(index);
      const visibility = normalizeWorksheetVisibility(worksheet.visibility);
      if (!showHiddenSheets && visibility !== "visible") {
        return [];
      }
      return [{
        id: `sheet-${index}`,
        index,
        kind: "sheet",
        name,
        sheetIndex: visibleSheetIndexByWorkbookSheetIndex.get(index) ?? index,
        visibility,
        workbookSheetIndex: index
      }];
    });
  }
  return rawOrder.flatMap((entry, index) => {
    const slotType = typeof entry.slotType === "string" ? entry.slotType : "worksheet";
    const slotIndex = typeof entry.index === "number" ? entry.index : index;
    if (slotType === "chartsheet") {
      const chartsheet = chartsheets[slotIndex];
      const visibility2 = normalizeWorksheetVisibility(chartsheet?.raw?.visibility);
      if (!showHiddenSheets && visibility2 !== "visible") return [];
      return chartsheet ? [{
        chartsheetIndex: slotIndex,
        id: `chartsheet-${slotIndex}`,
        index,
        kind: "chartsheet",
        name: chartsheet.name,
        visibility: visibility2
      }] : [];
    }
    const worksheet = workbook.getSheet(slotIndex);
    const visibility = normalizeWorksheetVisibility(worksheet.visibility);
    if (!showHiddenSheets && visibility !== "visible") {
      return [];
    }
    return [{
      id: `sheet-${slotIndex}`,
      index,
      kind: "sheet",
      name: worksheet.name,
      sheetIndex: visibleSheetIndexByWorkbookSheetIndex.get(slotIndex) ?? slotIndex,
      visibility,
      workbookSheetIndex: slotIndex
    }];
  });
}
function collectChartOriginsForSheet(archive, origin) {
  if (!origin) {
    return [];
  }
  const chartOrigins = [];
  for (const attachment of origin.attachments) {
    const drawingXml = readArchiveText2(archive, attachment.drawingPath);
    const relsXml = readArchiveText2(archive, attachment.drawingRelsPath);
    if (!drawingXml || !relsXml) {
      continue;
    }
    const drawingDocument = parseXml2(drawingXml);
    const relsDocument = parseXml2(relsXml);
    if (!drawingDocument || !relsDocument) {
      continue;
    }
    const relationships = /* @__PURE__ */ new Map();
    for (const node of getLocalDescendants(relsDocument, "Relationship")) {
      const id = node.getAttribute("Id");
      const target = node.getAttribute("Target");
      const type = node.getAttribute("Type");
      if (id && target) {
        relationships.set(id, {
          target: resolveRelationshipPath(attachment.drawingRelsPath ?? attachment.drawingPath, target),
          type
        });
      }
    }
    const anchorNodes = Array.from(drawingDocument.documentElement.childNodes).filter(
      (node) => node.nodeType === Node.ELEMENT_NODE && (node.localName === "twoCellAnchor" || node.localName === "oneCellAnchor" || node.localName === "absoluteAnchor")
    );
    let chartAnchorIndex = 0;
    for (const anchorNode of anchorNodes) {
      const graphicFrame = getFirstLocalDescendant(anchorNode, "graphicFrame");
      const chartNode = graphicFrame ? getFirstLocalDescendant(graphicFrame, "chart") : null;
      const relationshipId = chartNode?.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id") ?? chartNode?.getAttribute("r:id") ?? chartNode?.getAttribute("id");
      if (!relationshipId) {
        continue;
      }
      const relationship = relationships.get(relationshipId);
      if (!relationship || relationship.type !== CHART_REL_TYPE && relationship.type !== CHART_EX_REL_TYPE) {
        continue;
      }
      chartOrigins.push({
        anchorIndex: chartAnchorIndex,
        anchor: parseChartAnchorNode(anchorNode),
        chartKind: relationship.type === CHART_EX_REL_TYPE ? "modern" : "classic",
        chartPath: relationship.target,
        drawingPath: attachment.drawingPath,
        workbookSheetIndex: origin.workbookSheetIndex
      });
      chartAnchorIndex += 1;
    }
  }
  return chartOrigins;
}
function applyChartOrigins(chartsByWorkbookSheetIndex, chartOriginsById, archive, sheetOrigins) {
  for (let workbookSheetIndex = 0; workbookSheetIndex < chartsByWorkbookSheetIndex.length; workbookSheetIndex += 1) {
    const charts = chartsByWorkbookSheetIndex[workbookSheetIndex] ?? [];
    const origins = collectChartOriginsForSheet(archive, sheetOrigins[workbookSheetIndex] ?? null);
    const originsByKind = {
      classic: origins.filter((origin) => origin.chartKind === "classic"),
      modern: origins.filter((origin) => origin.chartKind === "modern")
    };
    const chartIndexByKind = {
      classic: 0,
      modern: 0
    };
    charts.forEach((chart) => {
      const chartKind = chart.id.startsWith("chart-ex-") ? "modern" : "classic";
      const origin = originsByKind[chartKind][chartIndexByKind[chartKind]];
      chartIndexByKind[chartKind] += 1;
      if (!origin) {
        return;
      }
      if (origin.anchor && !chart.raw?.pivotModified) {
        chart.anchor = origin.anchor;
      }
      chart.chartPath = origin.chartPath ?? void 0;
      chartOriginsById.set(chart.id, origin);
    });
  }
}
function refreshChartRenderSource(chart, imageAssets, workbook) {
  const next = { ...chart, series: chart.series.map((series) => ({ ...series })) };
  applyChartStyleFromXml(
    next,
    next.chartPath,
    imageAssets.archive,
    imageAssets.themePalette,
    createArchiveChartReferenceResolver(imageAssets.archive),
    workbook ?? void 0
  );
  return next;
}
function hydrateWorkbookChartStyles(chartsByWorkbookSheetIndex, imageAssets, chartsheets = [], workbook) {
  const resolveReference = createArchiveChartReferenceResolver(imageAssets.archive);
  const chartOriginsById = /* @__PURE__ */ new Map();
  applyChartOrigins(chartsByWorkbookSheetIndex, chartOriginsById, imageAssets.archive, imageAssets.sheetOrigins);
  const chartsheetOrigins = collectChartsheetDrawingOrigins(imageAssets.archive, chartsheets);
  for (const chartsheet of chartsheets) {
    if (chartsheet.workbookSheetIndex == null) continue;
    const charts = chartsByWorkbookSheetIndex[chartsheet.workbookSheetIndex] ?? [];
    const origins = collectChartOriginsForSheet(imageAssets.archive, chartsheetOrigins.get(chartsheet.index) ?? null);
    for (const chart of charts) {
      const kind = chart.id.startsWith("chart-ex-") ? "modern" : "classic";
      const origin = origins.find((entry) => entry.chartKind === kind);
      if (!origin) continue;
      if (origin.anchor) chart.anchor = origin.anchor;
      chart.chartPath = origin.chartPath ?? void 0;
      chartsheet.chartPath = chart.chartPath;
      chartOriginsById.set(chart.id, origin);
    }
  }
  for (const charts of chartsByWorkbookSheetIndex) {
    for (const chart of charts) {
      applyChartStyleFromXml(chart, chart.chartPath, imageAssets.archive, imageAssets.themePalette, resolveReference, workbook);
      applyBuiltinChartDefaults(chart, imageAssets.themePalette);
    }
  }
  return chartOriginsById;
}
function normalizeClassicChartDrawing(workbook, workbookSheetIndex, visibleSheetIndex, rawChart, chartIndex, chartId = `chart-${workbookSheetIndex}-${chartIndex}`) {
  const drawing = rawChart && typeof rawChart === "object" ? rawChart : {};
  const chart = drawing.chart && typeof drawing.chart === "object" ? drawing.chart : {};
  const rawView3d = chart.view3D && typeof chart.view3D === "object" ? chart.view3D : null;
  const rawSeries = Array.isArray(chart.series) ? chart.series : [];
  const typeGroups = Array.isArray(chart.typeGroups) ? chart.typeGroups.map((entry, groupIndex) => normalizeChartTypeGroup(workbook, workbookSheetIndex, chartId, entry, groupIndex)).filter((value) => value != null) : [];
  let seriesOrdinal = 0;
  const series = typeGroups.some((group) => group.series.length > 0) ? typeGroups.flatMap((group) => {
    group.series = group.series.map((entry) => ({ ...entry, id: `${chartId}-series-${seriesOrdinal++}` }));
    return group.series;
  }) : rawSeries.map((entry, seriesIndex) => normalizeChartSeries(workbook, workbookSheetIndex, chartId, entry, seriesIndex));
  const chartLevelDataLabels = normalizeChartDataLabels(chart.dataLabels);
  const firstSeriesDataLabels = rawSeries.length > 0 && rawSeries[0] && typeof rawSeries[0] === "object" ? normalizeChartDataLabels(rawSeries[0].dataLabels) : null;
  return {
    anchor: normalizeChartAnchor(drawing.anchor),
    autoTitleDeleted: typeof chart.autoTitleDeleted === "boolean" ? chart.autoTitleDeleted : void 0,
    axes: Array.isArray(chart.axes) ? chart.axes.map(normalizeChartAxis).filter((value) => Boolean(value)) : [],
    axisLabelColor: void 0,
    axisLineColor: void 0,
    categoryAxis: normalizeChartAxis(chart.categoryAxis),
    chartAreaBorderColor: void 0,
    chartAreaFillColor: void 0,
    chartColorPalette: void 0,
    chartColorPaletteOffset: void 0,
    chartPath: void 0,
    chartStyleId: void 0,
    chartType: typeof chart.chartType === "string" ? chart.chartType : "ColumnClustered",
    dataLabels: chartLevelDataLabels ?? firstSeriesDataLabels,
    displayBlanksAs: typeof chart.displayBlanksAs === "string" ? chart.displayBlanksAs : void 0,
    editable: true,
    firstSliceAngle: typeof chart.firstSliceAngle === "number" ? chart.firstSliceAngle : void 0,
    fontFamily: void 0,
    gapWidth: typeof chart.gapWidth === "number" ? chart.gapWidth : void 0,
    holeSize: typeof chart.holeSize === "number" ? chart.holeSize : void 0,
    id: chartId,
    is3d: typeof chart.is3D === "boolean" ? chart.is3D : typeof chart.is3d === "boolean" ? chart.is3d : void 0,
    legend: normalizeLegend(chart.legend) ? {
      ...normalizeLegend(chart.legend),
      position: normalizeLegendPosition(normalizeLegend(chart.legend)?.position)
    } : null,
    name: typeof drawing.name === "string" ? drawing.name : void 0,
    overlap: typeof chart.overlap === "number" ? chart.overlap : void 0,
    plotVisibleOnly: typeof chart.plotVisibleOnly === "boolean" ? chart.plotVisibleOnly : void 0,
    raw: chart,
    radarStyle: typeof chart.radarStyle === "string" ? chart.radarStyle : void 0,
    scatterStyle: typeof chart.scatterStyle === "string" ? chart.scatterStyle : void 0,
    roundedCorners: typeof chart.roundedCorners === "boolean" ? chart.roundedCorners : void 0,
    shape3d: typeof chart.shape === "string" ? chart.shape : typeof chart.shape3d === "string" ? chart.shape3d : void 0,
    seriesAxis: null,
    series,
    sheetIndex: visibleSheetIndex,
    showDlblsOverMax: typeof chart.showDlblsOverMax === "boolean" ? chart.showDlblsOverMax : void 0,
    sideWall: null,
    backWall: null,
    bubbleScale: typeof chart.bubbleScale === "number" ? chart.bubbleScale : void 0,
    bubble3d: typeof chart.bubble3d === "boolean" ? chart.bubble3d : void 0,
    floor: null,
    surfaceMaterial: void 0,
    textColor: void 0,
    title: typeof chart.title === "string" ? chart.title : void 0,
    titleColor: void 0,
    titleFontFamily: void 0,
    typeGroups,
    valueAxis: normalizeChartAxis(chart.valueAxis),
    varyColors: typeof chart.varyColors === "boolean" ? chart.varyColors : void 0,
    view3d: rawView3d ? {
      depthPercent: typeof rawView3d.depthPercent === "number" ? rawView3d.depthPercent : void 0,
      heightPercent: typeof rawView3d.heightPercent === "number" ? rawView3d.heightPercent : void 0,
      perspective: typeof rawView3d.perspective === "number" ? rawView3d.perspective : void 0,
      rAngAx: typeof rawView3d.rAngAx === "boolean" ? rawView3d.rAngAx : typeof rawView3d.rightAngleAxes === "boolean" ? rawView3d.rightAngleAxes : void 0,
      rotX: typeof rawView3d.rotX === "number" ? rawView3d.rotX : typeof rawView3d.rotateX === "number" ? rawView3d.rotateX : void 0,
      rotY: typeof rawView3d.rotY === "number" ? rawView3d.rotY : typeof rawView3d.rotateY === "number" ? rawView3d.rotateY : void 0
    } : void 0,
    wireframe: typeof chart.wireframe === "boolean" ? chart.wireframe : void 0,
    workbookSheetIndex,
    zIndex: Array.isArray(drawing.drawingPath) && typeof drawing.drawingPath[0] === "number" ? drawing.drawingPath[0] + 1 : chartIndex + 1
  };
}
function loadWorkbookChartAssets(workbook, imageAssets, visibleSheetIndexByWorkbookSheetIndex, showHiddenSheets = false) {
  const excludedChartIds = /* @__PURE__ */ new Set();
  const chartsByWorkbookSheetIndex = Array.from({ length: workbook.sheetCount }, (_, workbookSheetIndex) => {
    const worksheet = workbook.getSheet(workbookSheetIndex);
    const rawCharts = worksheet.charts;
    const rawChartsEx = worksheet.chartsEx;
    const visibleSheetIndex = visibleSheetIndexByWorkbookSheetIndex.get(workbookSheetIndex) ?? workbookSheetIndex;
    const classicCharts = rawCharts.map((rawChart, chartIndex) => {
      const chartId = `chart-${workbookSheetIndex}-${chartIndex}`;
      if (rawChart.hidden || !rawChart.anchor) {
        excludedChartIds.add(chartId);
      }
      return normalizeClassicChartDrawing(workbook, workbookSheetIndex, visibleSheetIndex, rawChart, chartIndex, chartId);
    });
    const modernCharts = rawChartsEx.map((rawChartEx, chartExIndex) => {
      const chartId = `chart-ex-${workbookSheetIndex}-${chartExIndex}`;
      if (rawChartEx.hidden || !rawChartEx.anchor) {
        excludedChartIds.add(chartId);
      }
      return normalizeChartExChart(
        workbook,
        workbookSheetIndex,
        visibleSheetIndex,
        rawChartEx,
        chartExIndex,
        imageAssets?.themePalette ?? null
      );
    });
    return [...classicCharts, ...modernCharts];
  });
  const chartsheets = Array.isArray(workbook.chartsheets) ? workbook.chartsheets.map((entry, index) => normalizeChartsheet(entry, index)) : [];
  for (const chartsheet of chartsheets) {
    const workbookSheetIndex = workbook.sheetCount + chartsheet.index;
    const raw = chartsheet.raw;
    const charts = [];
    if (raw?.chart && typeof raw.chart === "object") {
      charts.push(normalizeClassicChartDrawing(
        workbook,
        workbookSheetIndex,
        workbookSheetIndex,
        raw,
        0,
        `${chartsheet.id}-chart-0`
      ));
    }
    if (raw?.chartEx && typeof raw.chartEx === "object") {
      charts.push(normalizeChartExChart(
        workbook,
        workbookSheetIndex,
        workbookSheetIndex,
        raw,
        0,
        imageAssets?.themePalette ?? null
      ));
    }
    chartsByWorkbookSheetIndex[workbookSheetIndex] = charts;
    chartsheet.chartIds = charts.map((chart) => chart.id);
    chartsheet.workbookSheetIndex = workbookSheetIndex;
  }
  const tabs = buildTabs(workbook, chartsheets, visibleSheetIndexByWorkbookSheetIndex, showHiddenSheets);
  const chartOriginsById = imageAssets ? hydrateWorkbookChartStyles(chartsByWorkbookSheetIndex, imageAssets, chartsheets, workbook) : /* @__PURE__ */ new Map();
  if (imageAssets) {
    for (let index = 0; index < chartsByWorkbookSheetIndex.length; index += 1) {
      chartsByWorkbookSheetIndex[index] = (chartsByWorkbookSheetIndex[index] ?? []).filter((chart) => !excludedChartIds.has(chart.id));
    }
    for (const id of excludedChartIds) {
      chartOriginsById.delete(id);
    }
  } else {
    for (let index = 0; index < chartsByWorkbookSheetIndex.length; index += 1) {
      chartsByWorkbookSheetIndex[index] = (chartsByWorkbookSheetIndex[index] ?? []).filter((chart) => !excludedChartIds.has(chart.id));
    }
    for (const charts of chartsByWorkbookSheetIndex) {
      for (const chart of charts) {
        applyBuiltinChartDefaults(chart, null);
      }
    }
  }
  return {
    chartOriginsById,
    chartsByWorkbookSheetIndex,
    chartsheets,
    tabs
  };
}
function getChartAnchorNodes(drawingDocument) {
  return Array.from(drawingDocument.documentElement.childNodes).filter(
    (node) => node.nodeType === Node.ELEMENT_NODE && (node.localName === "twoCellAnchor" || node.localName === "oneCellAnchor" || node.localName === "absoluteAnchor")
  ).filter((anchorNode) => {
    const graphicFrame = getFirstLocalChild(anchorNode, "graphicFrame");
    return Boolean(graphicFrame && getFirstLocalDescendant(graphicFrame, "chart"));
  });
}
function updateMarkerNode(markerNode, marker) {
  if (!markerNode) {
    return;
  }
  setLeafValue(markerNode, "col", String(Math.max(0, Math.round(marker.col))));
  setLeafValue(markerNode, "colOff", String(Math.max(0, Math.round(marker.colOffsetEmu))));
  setLeafValue(markerNode, "row", String(Math.max(0, Math.round(marker.row))));
  setLeafValue(markerNode, "rowOff", String(Math.max(0, Math.round(marker.rowOffsetEmu))));
}
function updateAnchorNode2(anchorNode, anchor) {
  if (anchor.kind === "two-cell") {
    updateMarkerNode(getFirstLocalChild(anchorNode, "from"), anchor.from);
    updateMarkerNode(getFirstLocalChild(anchorNode, "to"), anchor.to);
    return;
  }
  if (anchor.kind === "one-cell") {
    updateMarkerNode(getFirstLocalChild(anchorNode, "from"), anchor.from);
    const ext2 = getFirstLocalChild(anchorNode, "ext");
    if (ext2) {
      ext2.setAttribute("cx", String(Math.max(0, Math.round(anchor.sizeEmu.cx))));
      ext2.setAttribute("cy", String(Math.max(0, Math.round(anchor.sizeEmu.cy))));
    }
    return;
  }
  const pos = getFirstLocalChild(anchorNode, "pos");
  if (pos) {
    pos.setAttribute("x", String(Math.max(0, Math.round(anchor.positionEmu.x))));
    pos.setAttribute("y", String(Math.max(0, Math.round(anchor.positionEmu.y))));
  }
  const ext = getFirstLocalChild(anchorNode, "ext");
  if (ext) {
    ext.setAttribute("cx", String(Math.max(0, Math.round(anchor.sizeEmu.cx))));
    ext.setAttribute("cy", String(Math.max(0, Math.round(anchor.sizeEmu.cy))));
  }
}
function setChartTitle(chartNode, value) {
  const existing = getFirstLocalChild(chartNode, "title");
  if (!value) {
    existing?.remove();
    return;
  }
  const titleNode = existing ?? chartNode.insertBefore(
    chartNode.ownerDocument.createElementNS(CHART_NS, "c:title"),
    chartNode.firstChild
  );
  while (titleNode.firstChild) {
    titleNode.removeChild(titleNode.firstChild);
  }
  const tx = titleNode.ownerDocument.createElementNS(CHART_NS, "c:tx");
  const rich = titleNode.ownerDocument.createElementNS(CHART_NS, "c:rich");
  const bodyPr = titleNode.ownerDocument.createElementNS(DRAWINGML_NS, "a:bodyPr");
  const lstStyle = titleNode.ownerDocument.createElementNS(DRAWINGML_NS, "a:lstStyle");
  const p = titleNode.ownerDocument.createElementNS(DRAWINGML_NS, "a:p");
  const r = titleNode.ownerDocument.createElementNS(DRAWINGML_NS, "a:r");
  const t = titleNode.ownerDocument.createElementNS(DRAWINGML_NS, "a:t");
  t.textContent = value;
  r.appendChild(t);
  p.appendChild(r);
  rich.append(bodyPr, lstStyle, p);
  tx.appendChild(rich);
  titleNode.appendChild(tx);
}
function setRefFormula(parent, refNodeName, formula) {
  for (const name of ["multiLvlStrRef", "strRef", "numRef", "strLit", "numLit"]) {
    if (name !== refNodeName) removeLocalChildren(parent, name);
  }
  if (!formula) {
    removeLocalChildren(parent, refNodeName);
    return;
  }
  const refNode = ensureChild(parent, refNodeName);
  setLeafValue(refNode, "f", formula);
}
function setSeriesText(seriesNode, series) {
  const raw = series.raw && typeof series.raw === "object" ? series.raw : null;
  const nameFormula = typeof raw?.name === "string" && raw.name.length > 0 ? raw.name : void 0;
  if (!nameFormula && series.name === void 0) {
    return;
  }
  const tx = ensureChild(seriesNode, "tx");
  removeLocalChildren(tx, "strRef");
  removeLocalChildren(tx, "v");
  if (nameFormula) {
    const strRef = ensureChild(tx, "strRef");
    setLeafValue(strRef, "f", nameFormula);
    return;
  }
  setLeafValue(tx, "v", series.name ?? "");
}
function updateSeriesNodes(plotAreaNode, chart) {
  if (!chart.series) {
    return;
  }
  const seriesNodes = getLocalDescendants(plotAreaNode, "ser");
  chart.series.forEach((series, index) => {
    const seriesNode = seriesNodes[index];
    if (!seriesNode) {
      return;
    }
    setSeriesText(seriesNode, series);
    if (series.categoriesRef?.formula) {
      const target = getFirstLocalChild(seriesNode, "xVal") ?? getFirstLocalChild(seriesNode, "cat") ?? (chart.chartType === "Scatter" || chart.chartType === "ScatterLines" || chart.chartType === "ScatterSmooth" || chart.chartType === "Bubble" ? ensureChild(seriesNode, "xVal") : ensureChild(seriesNode, "cat"));
      const hierarchy = series.raw?.chartHierarchyCategories;
      const categoryRefName = target.localName === "xVal" || getFirstLocalChild(target, "numRef") ? "numRef" : hierarchy ? "multiLvlStrRef" : "strRef";
      setRefFormula(target, categoryRefName, series.categoriesRef.formula);
      if (categoryRefName === "multiLvlStrRef" && hierarchy) {
        const reference = ensureChild(target, categoryRefName);
        removeLocalChildren(reference, "multiLvlStrCache");
        const cache = ensureChild(reference, "multiLvlStrCache");
        ensureChild(cache, "ptCount").setAttribute("val", String(hierarchy.length));
        const levelCount = hierarchy.reduce((count, point) => Math.max(count, ...point.map((entry) => entry.level + 1)), 0);
        for (let level = 0; level < levelCount; level += 1) {
          const levelNode = cache.ownerDocument.createElementNS(CHART_NS, "c:lvl");
          hierarchy.forEach((point, index2) => {
            const entry = point.find((item) => item.level === level);
            if (!entry) return;
            const pointNode = cache.ownerDocument.createElementNS(CHART_NS, "c:pt");
            pointNode.setAttribute("idx", String(index2));
            setLeafValue(pointNode, "v", entry.label);
            levelNode.appendChild(pointNode);
          });
          cache.appendChild(levelNode);
        }
      }
    }
    if (series.valuesRef?.formula) {
      const target = getFirstLocalChild(seriesNode, "yVal") ?? getFirstLocalChild(seriesNode, "val") ?? (chart.chartType === "Scatter" || chart.chartType === "ScatterLines" || chart.chartType === "ScatterSmooth" || chart.chartType === "Bubble" ? ensureChild(seriesNode, "yVal") : ensureChild(seriesNode, "val"));
      setRefFormula(target, "numRef", series.valuesRef.formula);
    }
    if (series.bubbleSizeRef) {
      const target = getFirstLocalChild(seriesNode, "bubbleSize") ?? ensureChild(seriesNode, "bubbleSize");
      setRefFormula(target, "numRef", series.bubbleSizeRef.formula);
    }
    if (series.invertIfNegative !== void 0) {
      setBooleanValue(seriesNode, "invertIfNegative", series.invertIfNegative);
    }
    if (series.smooth !== void 0) {
      setBooleanValue(seriesNode, "smooth", series.smooth);
    }
  });
}
function updateAxisNode(axisNode, axis) {
  if (!axisNode || !axis) {
    return;
  }
  if (axis.position) {
    setLeafValue(ensureChild(axisNode, "axPos"), "val", axis.position);
    getFirstLocalChild(axisNode, "axPos")?.setAttribute("val", axis.position);
  }
  if (axis.majorGridlines !== void 0) {
    const gridlines = getFirstLocalChild(axisNode, "majorGridlines");
    if (axis.majorGridlines && !gridlines) {
      axisNode.appendChild(axisNode.ownerDocument.createElementNS(CHART_NS, "c:majorGridlines"));
    } else if (!axis.majorGridlines) {
      gridlines?.remove();
    }
  }
  if (axis.minorGridlines !== void 0) {
    const gridlines = getFirstLocalChild(axisNode, "minorGridlines");
    if (axis.minorGridlines && !gridlines) {
      axisNode.appendChild(axisNode.ownerDocument.createElementNS(CHART_NS, "c:minorGridlines"));
    } else if (!axis.minorGridlines) {
      gridlines?.remove();
    }
  }
  if (axis.majorTickMark) {
    getFirstLocalChild(axisNode, "majorTickMark")?.setAttribute("val", axis.majorTickMark) ?? setBooleanValue(axisNode, "majorTickMark", false).setAttribute("val", axis.majorTickMark);
  }
  if (axis.minorTickMark) {
    getFirstLocalChild(axisNode, "minorTickMark")?.setAttribute("val", axis.minorTickMark) ?? setBooleanValue(axisNode, "minorTickMark", false).setAttribute("val", axis.minorTickMark);
  }
  if (axis.labelPosition) {
    getFirstLocalChild(axisNode, "tickLblPos")?.setAttribute("val", axis.labelPosition) ?? setBooleanValue(axisNode, "tickLblPos", false).setAttribute("val", axis.labelPosition);
  }
  if (axis.crosses) {
    getFirstLocalChild(axisNode, "crosses")?.setAttribute("val", axis.crosses) ?? setBooleanValue(axisNode, "crosses", false).setAttribute("val", axis.crosses);
  }
  if (axis.crossBetween) {
    getFirstLocalChild(axisNode, "crossBetween")?.setAttribute("val", axis.crossBetween) ?? setBooleanValue(axisNode, "crossBetween", false).setAttribute("val", axis.crossBetween);
  }
  if (axis.delete !== void 0) {
    setBooleanValue(axisNode, "delete", axis.delete);
  }
  if (axis.numberFormat?.formatCode) {
    const numFmt = ensureChild(axisNode, "numFmt");
    numFmt.setAttribute("formatCode", axis.numberFormat.formatCode);
    if (axis.numberFormat.sourceLinked !== void 0) {
      numFmt.setAttribute("sourceLinked", axis.numberFormat.sourceLinked ? "1" : "0");
    }
  }
}
function updateDataLabels(chartTypeNode, labels) {
  if (!labels) {
    return;
  }
  const labelsNode = ensureChild(chartTypeNode, "dLbls");
  if (labels.showLegendKey !== void 0) {
    setBooleanValue(labelsNode, "showLegendKey", labels.showLegendKey);
  }
  if (labels.showValue !== void 0) {
    setBooleanValue(labelsNode, "showVal", labels.showValue);
  }
  if (labels.showCategoryName !== void 0) {
    setBooleanValue(labelsNode, "showCatName", labels.showCategoryName);
  }
  if (labels.showSeriesName !== void 0) {
    setBooleanValue(labelsNode, "showSerName", labels.showSeriesName);
  }
  if (labels.showPercent !== void 0) {
    setBooleanValue(labelsNode, "showPercent", labels.showPercent);
  }
  if (labels.showBubbleSize !== void 0) {
    setBooleanValue(labelsNode, "showBubbleSize", labels.showBubbleSize);
  }
}
function updateWorkbookChartAnchor(imageAssets, chartAssets, chartId, anchor) {
  const origin = chartAssets.chartOriginsById.get(chartId);
  if (!origin) {
    return false;
  }
  const drawingXml = readArchiveText2(imageAssets.archive, origin.drawingPath);
  if (!drawingXml) {
    return false;
  }
  const drawingDocument = parseXml2(drawingXml);
  if (!drawingDocument) {
    return false;
  }
  const anchorNode = getChartAnchorNodes(drawingDocument)[origin.anchorIndex];
  if (!anchorNode) {
    return false;
  }
  updateAnchorNode2(anchorNode, anchor);
  imageAssets.archive[normalizeArchivePath2(origin.drawingPath)] = strToU82(serializeXml2(drawingDocument));
  imageAssets.dirtyArchivePaths.add(normalizeArchivePath2(origin.drawingPath));
  return true;
}
function updateWorkbookChartDefinition(imageAssets, chartAssets, chartId, patch) {
  const origin = chartAssets.chartOriginsById.get(chartId);
  if (!origin?.chartPath) {
    return false;
  }
  const chartXml = readArchiveText2(imageAssets.archive, origin.chartPath);
  if (!chartXml) {
    return false;
  }
  const chartDocument = parseXml2(chartXml);
  if (!chartDocument) {
    return false;
  }
  const chartNode = getFirstLocalDescendant(chartDocument, "chart");
  const plotAreaNode = chartNode ? getFirstLocalChild(chartNode, "plotArea") : null;
  const chartTypeNode = findPrimaryChartTypeNode(plotAreaNode);
  if (!chartNode || !plotAreaNode || !chartTypeNode) {
    return false;
  }
  if (patch.title !== void 0) {
    setChartTitle(chartNode, patch.title);
  }
  if (patch.displayBlanksAs) {
    const node = ensureChild(chartNode, "dispBlanksAs");
    node.setAttribute("val", patch.displayBlanksAs);
  }
  if (patch.roundedCorners !== void 0) {
    setBooleanValue(chartNode, "roundedCorners", patch.roundedCorners);
  }
  if (patch.showDlblsOverMax !== void 0) {
    setBooleanValue(chartNode, "showDLblsOverMax", patch.showDlblsOverMax);
  }
  if (patch.varyColors !== void 0) {
    setBooleanValue(chartTypeNode, "varyColors", patch.varyColors);
  }
  if (patch.gapWidth !== void 0) {
    setNumericValue(chartTypeNode, "gapWidth", patch.gapWidth);
  }
  if (patch.overlap !== void 0) {
    const overlapNode = ensureChild(chartTypeNode, "overlap");
    overlapNode.setAttribute("val", String(Math.round(patch.overlap)));
  }
  if (patch.dataLabels) {
    updateDataLabels(chartTypeNode, patch.dataLabels);
  }
  updateSeriesNodes(plotAreaNode, patch);
  updateAxisNode(
    getLocalChildren(plotAreaNode, "catAx")[0] ?? getLocalChildren(plotAreaNode, "dateAx")[0] ?? getLocalChildren(plotAreaNode, "serAx")[0] ?? null,
    patch.categoryAxis
  );
  updateAxisNode(getLocalChildren(plotAreaNode, "valAx")[0] ?? null, patch.valueAxis);
  imageAssets.archive[normalizeArchivePath2(origin.chartPath)] = strToU82(serializeXml2(chartDocument));
  imageAssets.dirtyArchivePaths.add(normalizeArchivePath2(origin.chartPath));
  return true;
}

// src/safe-calculate.ts
var SHEET_REF_REGEX = /'((?:[^']|'')+)'!|([A-Za-z_\u0080-\uFFFF][\w.\u0080-\uFFFF]*)!/g;
function collectReferencedSheetNames(workbook) {
  const referenced = /* @__PURE__ */ new Set();
  for (let sheetIdx = 0; sheetIdx < workbook.sheetCount; sheetIdx += 1) {
    let sheet;
    try {
      sheet = workbook.getSheet(sheetIdx);
    } catch {
      continue;
    }
    const cells = sheet.formulaCells;
    if (!Array.isArray(cells)) {
      continue;
    }
    for (const cell of cells) {
      const formula = cell?.formula;
      if (!formula) {
        continue;
      }
      SHEET_REF_REGEX.lastIndex = 0;
      let match;
      while ((match = SHEET_REF_REGEX.exec(formula)) !== null) {
        const raw = match[1] ?? match[2];
        if (!raw) {
          continue;
        }
        referenced.add(raw.replace(/''/g, "'"));
      }
    }
  }
  return referenced;
}
function hasUnresolvedSheetReferences(workbook) {
  let names;
  try {
    names = workbook.sheetNames;
  } catch {
    return false;
  }
  const known = new Set(names.map((name) => name.toLowerCase()));
  const referenced = collectReferencedSheetNames(workbook);
  for (const name of referenced) {
    if (!known.has(name.toLowerCase())) {
      return true;
    }
  }
  return false;
}
function collectFormulaCellsWithSavedValues(workbook) {
  const positions = [];
  for (let sheetIdx = 0; sheetIdx < workbook.sheetCount; sheetIdx += 1) {
    let sheet;
    try {
      sheet = workbook.getSheet(sheetIdx);
    } catch {
      continue;
    }
    const cells = sheet.formulaCells;
    if (!Array.isArray(cells)) {
      continue;
    }
    for (const cell of cells) {
      if (typeof cell?.row !== "number" || typeof cell?.col !== "number") {
        continue;
      }
      let saved;
      try {
        saved = sheet.getCalculatedValueAt(cell.row, cell.col);
      } catch {
        continue;
      }
      if (!saved.is_empty && !saved.is_error) {
        positions.push({ sheetIdx, row: cell.row, col: cell.col });
      }
    }
  }
  return positions;
}
function anyBecameError(workbook, positions) {
  return positions.some(({ sheetIdx, row, col }) => {
    try {
      return workbook.getSheet(sheetIdx).getCalculatedValueAt(row, col).is_error;
    } catch {
      return false;
    }
  });
}
function safeCalculate(workbook, options = {}) {
  if (hasUnresolvedSheetReferences(workbook)) {
    return { workbook, calculated: false, skipReason: "unresolved-sheet-refs" };
  }
  const withSavedValues = options.reparse && options.preserveSavedValues !== false ? collectFormulaCellsWithSavedValues(workbook) : [];
  try {
    workbook.calculate();
  } catch (err) {
    console.warn("[react-xlsx] workbook.calculate() trapped; falling back to cached formula values", err);
    if (options.reparse) {
      try {
        return { workbook: options.reparse(), calculated: false, skipReason: "calculate-trapped" };
      } catch (reparseErr) {
        console.warn("[react-xlsx] workbook reparse after calculate trap failed", reparseErr);
      }
    }
    return { workbook, calculated: false, skipReason: "calculate-trapped" };
  }
  if (options.reparse && anyBecameError(workbook, withSavedValues)) {
    try {
      return { workbook: options.reparse(), calculated: false, skipReason: "calculate-regressed" };
    } catch (reparseErr) {
      console.warn("[react-xlsx] workbook reparse after calculate regression failed", reparseErr);
    }
  }
  return { workbook, calculated: true, skipReason: null };
}
function tryRecalculate(workbook) {
  try {
    workbook.calculate();
    return { calculated: true, error: null };
  } catch (err) {
    console.warn("[react-xlsx] workbook.calculate() trapped during recalculation", err);
    return { calculated: false, error: err };
  }
}

// src/worksheet-autofit.ts
function readWorksheetAutofitCells(worksheet, axis, index, locale) {
  return localizeSizingCells(worksheet.getAutofitCells(axis, index), locale);
}
function localizeSizingCells(rows, locale) {
  if (locale === "en-US") return rows;
  for (const row of rows) {
    for (const cell of row.cells) {
      if (cell.numericValue !== void 0) {
        cell.value = localizeFormattedNumber(cell.value, cell.style?.numberFormat, locale);
      }
    }
  }
  return rows;
}

export {
  XLSX_MAX_ROWS,
  XLSX_MAX_COLUMNS,
  parseXlsxRange,
  pivotWorkbook,
  readPivotTables,
  findIntersectingPivot,
  takeWorkerImageBlobs,
  restoreWorkerImageBlobs,
  buildThemePaletteFromHex,
  resolveWorkbookColor,
  resolveWorkbookFillStyle,
  getColumnFontMeasurements,
  restoreColumnFontMeasurements,
  getUnmeasuredWorkbookFont,
  resolveWorksheetDefaultColumnWidthPixels,
  resolveWorksheetDefaultRowHeightPixels,
  resolveWorksheetMergeMetadata,
  xlsxAnchorToDukeDrawingAnchor,
  collectWorkbookFormControls,
  refreshWorkbookFormControls,
  revokeWorkbookImageAssets,
  updateWorkbookImageAnchor,
  mergeWorkbookImageAssets,
  emuToPixels,
  pxToSheetColumnWidth,
  pxToOfficeColumnWidth,
  resolveSheetColumnWidthPixels,
  resolveSheetRowHeightPixels,
  resolveRenderedSheetAxisPixels,
  resolveContentSheetAxisPixels,
  rectToImageAnchor,
  resizeImageRect,
  loadWorkbookImageAssets,
  parseLocaleNumber,
  localizeCellNumber,
  localizeRows,
  loadSpreadsheetFonts,
  buildChartSeriesFormula,
  applyChartSeriesFormula,
  refreshChartRenderSource,
  hydrateWorkbookChartStyles,
  loadWorkbookChartAssets,
  updateWorkbookChartAnchor,
  updateWorkbookChartDefinition,
  safeCalculate,
  tryRecalculate,
  readWorksheetAutofitCells
};
//# sourceMappingURL=chunk-2TLD35UF.js.map