import {
  buildThemePaletteFromHex,
  collectWorkbookFormControls,
  getColumnFontMeasurements,
  getUnmeasuredWorkbookFont,
  hydrateWorkbookChartStyles,
  loadSpreadsheetFonts,
  loadWorkbookChartAssets,
  loadWorkbookImageAssets,
  localizeCellNumber,
  localizeRows,
  mergeWorkbookImageAssets,
  pivotWorkbook,
  readPivotTables,
  readWorksheetAutofitCells,
  resolveSheetColumnWidthPixels,
  resolveWorksheetDefaultColumnWidthPixels,
  resolveWorksheetDefaultRowHeightPixels,
  resolveWorksheetMergeMetadata,
  restoreColumnFontMeasurements,
  revokeWorkbookImageAssets,
  safeCalculate,
  takeWorkerImageBlobs
} from "./chunk-2TLD35UF.js";
import "./chunk-QXXS4J36.js";
import {
  configureWorkbookArchiveDecoder,
  configureWorkbookXmlDecoder,
  installWorkerXmlAdapters,
  takeWorkbookXmlRecords
} from "./chunk-67TEHWH5.js";

// src/workbook-runtime.ts
import { strFromU8, strToU8 } from "fflate";
import { getSheetsWasmModule } from "@extend-ai/react-xlsx/internal";
var DEFAULT_ROW_HEIGHT = 24;
var DEFAULT_COL_WIDTH = 80;
var DEFAULT_ZOOM_SCALE = 100;
var FORMULA_COUNT_THRESHOLD = 1e3;
function isLegacyXlsWorkbook(bytes) {
  return bytes.byteLength >= 8 && bytes[0] === 208 && bytes[1] === 207 && bytes[2] === 17 && bytes[3] === 224 && bytes[4] === 161 && bytes[5] === 177 && bytes[6] === 26 && bytes[7] === 225;
}
function shouldSkipXmlParsingForWorkbook(bytes, skipXmlParsing = false) {
  return skipXmlParsing || isLegacyXlsWorkbook(bytes);
}
function normalizeWorksheetVisibility(value) {
  return value === "hidden" || value === "veryHidden" ? value : "visible";
}
function normalizeRange(range) {
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
  return normalizeRange({ end, start });
}
function resolveWorkbookReference(targetWorkbook, defaultWorkbookSheetIndex, rawReference, resolvingNamedRange = false) {
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
    const resolvedSheetIndex = targetWorkbook.sheetIndex(sheetName);
    if (resolvedSheetIndex === void 0) {
      return null;
    }
    workbookSheetIndex = resolvedSheetIndex;
  } else if (!resolvingNamedRange) {
    const namedRange = targetWorkbook.getNamedRange(reference);
    if (namedRange) {
      return resolveWorkbookReference(targetWorkbook, defaultWorkbookSheetIndex, namedRange, true);
    }
  }
  const range = parseA1RangeReference(rangeReference.replace(/\$/g, ""));
  if (!range || workbookSheetIndex < 0 || workbookSheetIndex >= targetWorkbook.sheetCount) {
    return null;
  }
  try {
    return {
      range,
      worksheet: targetWorkbook.getSheet(workbookSheetIndex)
    };
  } catch {
    return null;
  }
}
function resolveFormControlItems(targetWorkbook, workbookSheetIndex, control) {
  if (control.kind !== "dropdown" && control.kind !== "listbox" || !control.inputRange) {
    return [];
  }
  const source = resolveWorkbookReference(targetWorkbook, workbookSheetIndex, control.inputRange);
  if (!source) {
    return [];
  }
  const items = [];
  for (let row = source.range.start.row; row <= source.range.end.row; row += 1) {
    for (let col = source.range.start.col; col <= source.range.end.col; col += 1) {
      items.push(source.worksheet.getFormattedValueAt(row, col));
    }
  }
  return items;
}
function parseWorksheetFreezePanes(worksheet) {
  const rawFreezePanes = worksheet.freezePanes;
  const row = typeof rawFreezePanes?.row === "number" && rawFreezePanes.row >= 0 ? rawFreezePanes.row : null;
  const col = typeof rawFreezePanes?.col === "number" && rawFreezePanes.col >= 0 ? rawFreezePanes.col : null;
  if (row === null && col === null) {
    return null;
  }
  return {
    col: col ?? 0,
    row: row ?? 0
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
function resolveWorksheetZoomScale(worksheet, sheetState) {
  const candidates = [
    sheetState?.zoomScale,
    typeof worksheet.zoomScale === "number" ? worksheet.zoomScale : void 0
  ];
  const value = candidates.find((entry) => typeof entry === "number" && Number.isFinite(entry) && entry > 0);
  return value ?? DEFAULT_ZOOM_SCALE;
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
function buildSheetList(nextWorkbook, themePalette, structureAssets, sheetLayoutStates, showHiddenSheets = false) {
  const sheetsByWorkbookSheetIndex = [];
  for (let index = 0; index < nextWorkbook.sheetCount; index += 1) {
    const worksheet = nextWorkbook.getSheet(index);
    const sheetState = structureAssets?.sheetStatesByWorkbookSheetIndex[index] ?? sheetLayoutStates?.[index] ?? null;
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
    const resolveRowHeightPx = (row) => {
      const height = worksheet.getRowHeight(row);
      if (height !== void 0 && height !== null) {
        return Math.max(Math.round(height * 1.33), 16);
      }
      return sheetState?.rowHeightOverridesPx?.[row] ?? defaultRowHeightPx;
    };
    const hiddenRows = Array.from(worksheet.hiddenRows);
    const hiddenCols = Array.from(worksheet.hiddenColumns);
    const rowHeightOverridesPx = sheetState?.rowHeightOverridesPx ?? {};
    const colWidthOverridesPx = sheetState?.colWidthOverridesPx ?? {};
    if (!sheetState) {
      for (const row of hiddenRows) {
        const height = resolveRowHeightPx(row);
        if (height !== defaultRowHeightPx) rowHeightOverridesPx[row] = height;
      }
      for (const col of hiddenCols) {
        const width = resolveColumnWidthPx(col);
        if (width !== defaultColWidthPx) colWidthOverridesPx[col] = width;
      }
    }
    const usedRange = worksheet.usedRange();
    if (!usedRange) {
      sheetsByWorkbookSheetIndex.push({
        autoFilterRanges: sheetState?.autoFilterRanges ?? [],
        cachedFormulaValues: sheetState?.cachedFormulaValues ?? {},
        columnWidthCharacterWidthPx: sheetState?.columnWidthCharacterWidthPx,
        colCount: 0,
        colStyleIds: sheetState?.colStyleIds ?? {},
        colWidthOverridesPx,
        colWidths: [],
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
        hiddenCols,
        hiddenRows,
        minUsedCol: -1,
        minUsedRow: -1,
        maxUsedCol: -1,
        maxUsedRow: -1,
        name: worksheet.name,
        visibility,
        namedCellStyleByName: structureAssets?.namedCellStyleByName ?? {},
        rowCount: 0,
        rowHeightOverridesPx,
        rowHeights: [],
        rowStyleIds: sheetState?.rowStyleIds ?? {},
        cellStyleIds: sheetState?.cellStyleIds ?? {},
        showGridLines: sheetState?.showGridLines ?? true,
        sparklines: sheetState?.sparklines ?? [],
        styleById: structureAssets?.styleById ?? {},
        tableStyleByName: structureAssets?.tableStyleByName ?? {},
        themePalette,
        visibleCols: [],
        visibleRows: [],
        workbookSheetIndex: index,
        zoomScale: resolveWorksheetZoomScale(worksheet, sheetState)
      });
      continue;
    }
    const [minRow, minCol, maxRow, maxCol] = resolveSheetDisplayUsedRange(usedRange, effectiveSheetState);
    const visibleRows = [];
    for (let row = 0; row <= maxRow; row += 1) {
      if (!worksheet.isRowHidden(row)) {
        visibleRows.push(row);
      }
    }
    const visibleCols = [];
    for (let col = 0; col <= maxCol; col += 1) {
      if (!worksheet.isColumnHidden(col)) {
        visibleCols.push(col);
      }
    }
    sheetsByWorkbookSheetIndex.push({
      autoFilterRanges: sheetState?.autoFilterRanges ?? [],
      cachedFormulaValues: sheetState?.cachedFormulaValues ?? {},
      columnWidthCharacterWidthPx: sheetState?.columnWidthCharacterWidthPx,
      colCount: visibleCols.length,
      colStyleIds: sheetState?.colStyleIds ?? {},
      colWidthOverridesPx,
      colWidths: visibleCols.map(resolveColumnWidthPx),
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
      hiddenCols,
      hiddenRows,
      minUsedCol: minCol,
      minUsedRow: minRow,
      maxUsedCol: maxCol,
      maxUsedRow: maxRow,
      name: worksheet.name,
      visibility,
      namedCellStyleByName: structureAssets?.namedCellStyleByName ?? {},
      rowCount: visibleRows.length,
      rowHeightOverridesPx,
      rowHeights: visibleRows.map(resolveRowHeightPx),
      rowStyleIds: sheetState?.rowStyleIds ?? {},
      cellStyleIds: sheetState?.cellStyleIds ?? {},
      showGridLines: sheetState?.showGridLines ?? true,
      sparklines: sheetState?.sparklines ?? [],
      styleById: structureAssets?.styleById ?? {},
      tableStyleByName: structureAssets?.tableStyleByName ?? {},
      themePalette,
      visibleCols,
      visibleRows,
      workbookSheetIndex: index,
      zoomScale: resolveWorksheetZoomScale(worksheet, sheetState)
    });
  }
  return sheetsByWorkbookSheetIndex;
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
    const reference = `${cellAddressToA1(range.start)}:${cellAddressToA1(range.end)}`;
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
function decodeHtmlEntities(value) {
  return value.replace(/&quot;/g, '"').replace(/&#34;/g, '"').replace(/&apos;/g, "'").replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}
function getCellDisplayValue(worksheet, row, col, activeSheet) {
  const formula = worksheet.getFormulaAt(row, col);
  const cachedFormulaValue = formula ? activeSheet?.cachedFormulaValues?.[cellAddressToA1({ row, col })] : void 0;
  const formatted = worksheet.getFormattedValueAt(row, col);
  if (formatted && !(formula && cachedFormulaValue !== void 0 && formatted.startsWith("#"))) {
    return decodeHtmlEntities(formatted);
  }
  const cellValue = worksheet.getCalculatedValueAt(row, col);
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
function cellAddressToA1(cell) {
  let col = cell.col + 1;
  let label = "";
  while (col > 0) {
    const remainder = (col - 1) % 26;
    label = String.fromCharCode(65 + remainder) + label;
    col = Math.floor((col - 1) / 26);
  }
  return `${label}${cell.row + 1}`;
}
function createWorkbookRuntime() {
  let disposed = false;
  let loadedImageAssets = null;
  let workbook = null;
  let workbookFontFamilies = [];
  let chartsByWorkbookSheetIndex = [];
  let chartsheets = [];
  let formControlsByWorkbookSheetIndex = [];
  let sheets = [];
  let tablesByWorkbookSheetIndex = [];
  let tabs = [];
  async function loadWorkbook(buffer, skipXmlParsing = false, showHiddenSheets = false, includeSnapshot = false) {
    const wasmModule = await getSheetsWasmModule();
    if (disposed) throw new DOMException("Aborted", "AbortError");
    configureWorkbookXmlDecoder(wasmModule.parseXmlTree);
    configureWorkbookArchiveDecoder(wasmModule.decodeArchive);
    if (typeof document === "undefined") installWorkerXmlAdapters();
    const bytes = new Uint8Array(buffer);
    const preflight = wasmModule.inspectArchive(bytes);
    if (preflight.tooLarge) throw new Error("XLSX is too large to preview interactively.");
    const effectiveSkipXmlParsing = shouldSkipXmlParsingForWorkbook(bytes, skipXmlParsing);
    let activeWorkbook = wasmModule.Workbook.fromBytesForViewer(bytes);
    try {
      const fontFamilies = activeWorkbook.fontFamilies();
      const archive = activeWorkbook.takeViewerArchive();
      let totalFormulas = 0;
      for (let index = 0; index < activeWorkbook.sheetCount; index += 1) totalFormulas += activeWorkbook.getSheet(index).formulaCount;
      const refreshOnLoadPivots = readPivotTables(activeWorkbook).filter((pivot) => pivot.refreshOnLoad && !pivot.unsupportedFeatures.length);
      let sourceCalculated = totalFormulas === 0;
      let shouldAutoCalculate = totalFormulas === 0;
      if (totalFormulas > 0 && (totalFormulas <= FORMULA_COUNT_THRESHOLD || refreshOnLoadPivots.length > 0)) {
        const snapshot = activeWorkbook.exportSnapshot();
        const result = safeCalculate(activeWorkbook, { reparse: () => wasmModule.Workbook.fromSnapshot(snapshot) });
        activeWorkbook = result.workbook;
        sourceCalculated = result.calculated;
        shouldAutoCalculate = result.calculated && totalFormulas <= FORMULA_COUNT_THRESHOLD;
      }
      const pivotRefreshErrors = /* @__PURE__ */ new Map();
      let recalculatedPivotFormulas = false;
      for (const pivot of refreshOnLoadPivots) {
        if (!sourceCalculated) {
          pivotRefreshErrors.set(pivot.id, "The workbook formulas could not be recalculated safely. The saved pivot table has been kept.");
          continue;
        }
        try {
          pivotWorkbook(activeWorkbook).refreshPivotTable(pivot.id);
        } catch (error) {
          pivotRefreshErrors.set(pivot.id, error instanceof Error ? error.message : String(error));
          continue;
        }
        const snapshot = activeWorkbook.exportSnapshot();
        const result = safeCalculate(activeWorkbook, { reparse: () => wasmModule.Workbook.fromSnapshot(snapshot), preserveSavedValues: false });
        activeWorkbook = result.workbook;
        sourceCalculated = result.calculated;
        recalculatedPivotFormulas ||= result.calculated;
        if (!result.calculated) {
          shouldAutoCalculate = false;
          pivotRefreshErrors.set(pivot.id, "The pivot table refreshed, but dependent formulas could not be recalculated.");
        }
      }
      const nextWorkbook = activeWorkbook;
      const unmeasuredFont = effectiveSkipXmlParsing ? null : getUnmeasuredWorkbookFont(archive);
      if (unmeasuredFont) await loadSpreadsheetFonts([unmeasuredFont], typeof document === "undefined" ? globalThis : document);
      workbookFontFamilies = fontFamilies;
      const imageAssets = await loadWorkbookImageAssets(bytes, nextWorkbook, effectiveSkipXmlParsing, archive);
      if (disposed) {
        revokeWorkbookImageAssets(imageAssets);
        throw new DOMException("Aborted", "AbortError");
      }
      revokeWorkbookImageAssets(loadedImageAssets);
      loadedImageAssets = imageAssets;
      if (recalculatedPivotFormulas) {
        for (const sheet of imageAssets?.sheetStatesByWorkbookSheetIndex ?? []) if (sheet) sheet.cachedFormulaValues = {};
      }
      const structureAssets = imageAssets;
      const themePalette = structureAssets?.themePalette ?? buildThemePaletteFromHex(nextWorkbook.themePalette);
      formControlsByWorkbookSheetIndex = collectWorkbookFormControls(nextWorkbook, themePalette).map(
        (controls, sheetIndex) => controls.map((control) => ({ ...control, items: resolveFormControlItems(nextWorkbook, sheetIndex, control) }))
      );
      workbook?.free();
      workbook = nextWorkbook;
      sheets = buildSheetList(nextWorkbook, themePalette, structureAssets, void 0, showHiddenSheets);
      tablesByWorkbookSheetIndex = Array.from(
        { length: nextWorkbook.sheetCount },
        (_, index) => mapWorksheetTables(nextWorkbook.getSheet(index), structureAssets?.sheetStatesByWorkbookSheetIndex[index]?.autoFilterRanges ?? [])
      );
      const visibleSheetIndexByWorkbookSheetIndex = new Map(sheets.map((sheet, index) => [sheet.workbookSheetIndex, index]));
      const chartAssets = loadWorkbookChartAssets(nextWorkbook, null, visibleSheetIndexByWorkbookSheetIndex, showHiddenSheets);
      if (imageAssets) chartAssets.chartOriginsById = hydrateWorkbookChartStyles(chartAssets.chartsByWorkbookSheetIndex, imageAssets, chartAssets.chartsheets, nextWorkbook);
      chartsByWorkbookSheetIndex = chartAssets.chartsByWorkbookSheetIndex;
      chartsheets = chartAssets.chartsheets;
      tabs = chartAssets.tabs;
      return {
        chartsByWorkbookSheetIndex,
        chartsheets,
        formControlsByWorkbookSheetIndex,
        sheets,
        tablesByWorkbookSheetIndex,
        tabs,
        pivotTables: readPivotTables(nextWorkbook).map((pivot) => ({ ...pivot, ...pivotRefreshErrors.has(pivot.id) ? { refreshError: pivotRefreshErrors.get(pivot.id) } : {} })),
        chartOriginsById: chartAssets.chartOriginsById,
        columnFontMeasurements: getColumnFontMeasurements(),
        fontFamilies,
        imageAssets,
        xmlRecords: takeWorkbookXmlRecords(includeSnapshot ? void 0 : new Set(chartsByWorkbookSheetIndex.flat().flatMap((chart) => chart.renderSource ? [chart.renderSource.xml] : []))),
        shouldAutoCalculate,
        workbookSnapshot: includeSnapshot ? nextWorkbook.exportSnapshot() : void 0,
        imageBlobs: takeWorkerImageBlobs(imageAssets?.objectUrls ?? [])
      };
    } catch (error) {
      if (workbook !== activeWorkbook) activeWorkbook.free();
      throw error;
    }
  }
  async function handleMessage(message) {
    switch (message.type) {
      case "renderChart": {
        const [chart, source, width, height] = message.payload;
        const [{ loadOfficeCharts }, { renderChartInWorker }] = await Promise.all([
          source.experimental ? import("./full-646FFXB3.js") : import("./browser-NA4MQWEC.js"),
          import("./chart-worker-render-DGWTPUBG.js")
        ]);
        await loadSpreadsheetFonts(workbookFontFamilies, typeof document === "undefined" ? globalThis : document);
        const renderer = await loadOfficeCharts(source.experimental && typeof DecompressionStream !== "function" ? new URL("./office_charts_full_bg.wasm", import.meta.url) : void 0);
        try {
          return renderChartInWorker(renderer, chart, source, width, height);
        } finally {
          takeWorkbookXmlRecords();
        }
      }
      case "export": {
        const wasmModule = await getSheetsWasmModule();
        configureWorkbookXmlDecoder(wasmModule.parseXmlTree);
        configureWorkbookArchiveDecoder(wasmModule.decodeArchive);
        if (typeof document === "undefined") installWorkerXmlAdapters();
        const restored = wasmModule.Workbook.fromSnapshot(message.payload.snapshot);
        try {
          const bytes = restored.saveXlsxBytes();
          const archive = wasmModule.decodeArchive(bytes);
          const styles = archive["xl/styles.xml"];
          if (styles) archive["xl/styles.xml"] = strToU8(strFromU8(styles).replace(/&amp;quot;/g, "&quot;").replace(/&amp;apos;/g, "&apos;"));
          const result = mergeWorkbookImageAssets(bytes, message.payload.assets, message.payload.origins, archive, pivotWorkbook(restored).modifiedPivotCharts());
          return result;
        } finally {
          restored.free();
          takeWorkbookXmlRecords();
        }
      }
      case "load": {
        restoreColumnFontMeasurements(message.payload.columnFontMeasurements ?? []);
        return loadWorkbook(message.payload.buffer, message.payload.skipXmlParsing, message.payload.showHiddenSheets, message.payload.includeSnapshot);
      }
      case "getCellSnapshot": {
        if (!workbook) {
          return {
            displayValue: "",
            formula: ""
          };
        }
        const targetSheet = sheets.find((sheet) => sheet.workbookSheetIndex === message.payload.workbookSheetIndex) ?? null;
        const worksheet = workbook.getSheet(message.payload.workbookSheetIndex);
        return {
          displayValue: localizeCellNumber(worksheet, message.payload.row, message.payload.col, getCellDisplayValue(worksheet, message.payload.row, message.payload.col, targetSheet), message.payload.locale),
          formula: worksheet.getFormulaAt(message.payload.row, message.payload.col) ?? ""
        };
      }
      case "getAutofitCells": {
        if (!workbook) return [];
        const { workbookSheetIndex, axis, index, locale } = message.payload;
        const worksheet = workbook.getSheet(workbookSheetIndex);
        try {
          return readWorksheetAutofitCells(worksheet, axis, index, locale);
        } finally {
          worksheet.free();
        }
      }
      case "getRowsBatch": {
        if (!workbook) {
          return null;
        }
        const worksheet = workbook.getSheet(message.payload.workbookSheetIndex);
        if (typeof worksheet.getRowsBatch !== "function") {
          return null;
        }
        const rows = worksheet.getRowsBatch(message.payload.startRow, message.payload.rowCount, {
          includeFormulas: true,
          includeHyperlinks: true,
          includeMergeInfo: true,
          includeStyles: true,
          useFormattedValues: true
        });
        localizeRows(rows, message.payload.locale);
        return rows;
      }
      default:
        return null;
    }
  }
  return {
    handleMessage,
    dispose() {
      disposed = true;
      workbook?.free();
      workbook = null;
      revokeWorkbookImageAssets(loadedImageAssets);
      loadedImageAssets = null;
    }
  };
}
export {
  createWorkbookRuntime
};
//# sourceMappingURL=workbook-runtime-BAAYDYYK.js.map