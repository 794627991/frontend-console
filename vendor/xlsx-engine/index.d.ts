import * as React from 'react';
export { XlsxFileSizeLimitExceededError, XlsxWasmSource, initWasm, parseXlsxRange, setWasmSource } from '@extend-ai/react-xlsx/vanilla';
import * as react_jsx_runtime from 'react/jsx-runtime';

type ChartWorkerResult = {
    svg: string | null;
    pointMaps?: number[][];
} | null;
type RenderChartAsync = (chart: XlsxChart, source: XlsxChartRenderSource, width: number, height: number) => Promise<ChartWorkerResult>;

interface ChartPoint {
    index: number;
    categories?: ReadonlyArray<{
        level: number;
        label: string;
    }>;
    value?: string | null;
    x?: string | null;
    y?: string | null;
    bubbleSize?: string | null;
}
interface ChartData {
    title?: string | null;
    series: ReadonlyArray<{
        chartType: string;
        name?: string | null;
        points: ReadonlyArray<ChartPoint>;
    }>;
}
interface RenderOptions {
    width?: number;
    height?: number;
    themeColors?: Readonly<Record<string, string>>;
    images?: Readonly<Record<string, string>>;
    drawings?: Readonly<Record<string, {
        xml: string;
        images?: Readonly<Record<string, string>>;
    }>>;
    fontFamily?: string;
    themeXml?: string;
    themeOverrideXml?: string;
    styleXml?: string;
    colorStyleXml?: string;
    legacyDefaults?: boolean;
    spreadsheetDefaults?: boolean;
    interactive?: boolean;
    data?: ChartData;
}
interface OfficeCharts {
    renderChart(xml: string, options?: RenderOptions): string | null;
}

declare const englishMessages: {
    sortAscending: string;
    sortDescending: string;
    openMenuForColumn: string;
    cut: string;
    copy: string;
    paste: string;
    editCell: string;
    clearContents: string;
    undo: string;
    redo: string;
    mergeAndCenter: string;
    mergeAcross: string;
    mergeCells: string;
    unmergeCells: string;
    rowHeight: string;
    columnWidth: string;
    pixels: string;
    cancel: string;
    ok: string;
    hide: string;
    unhide: string;
    selectRow: string;
    selectColumn: string;
    selectAll: string;
    showPivotFieldList: string;
    hidePivotFieldList: string;
    pivotTableFields: string;
    refreshPivotTable: string;
    showPivotDetails: string;
    expandPivotGroup: string;
    collapsePivotGroup: string;
    contextMenu: string;
    clipboardCopyUnavailable: string;
    clipboardPasteUnavailable: string;
    nothingToPaste: string;
    actionFailed: string;
    workbookSheets: string;
    downloadWorkbook: string;
    zoomIn: string;
    zoomOut: string;
    resetZoom: string;
    hiddenSheet: string;
    veryHiddenSheet: string;
    loadingWorkbook: string;
    emptyWorkbook: string;
    loadWorkbookFailed: string;
    fileTooLarge: string;
    largeWorkbook: string;
    deferredLoadDescription: string;
    loadAnyway: string;
    worksheetGrid: string;
    workbookGrid: string;
    dropdownControl: string;
    listBoxControl: string;
    scrollbarControl: string;
    spinnerControl: string;
    chart: string;
    loadingChart: string;
    loadChartFailed: string;
    mapUnavailable: string;
    chartUnavailable: string;
    chartsheetUnavailable: string;
};
type XlsxViewerMessages = {
    [Key in keyof typeof englishMessages]: string;
};

/* tslint:disable */
/* eslint-disable */

declare global {
    interface SymbolConstructor {
        readonly dispose: unique symbol;
    }
}

interface JsRowCell {
    col: number;
    value: string;
    numericValue?: number;
    generalAlignment?: "left" | "center" | "right";
    richText?: Array<{ text: string; font?: FontStyleInput | null }>;
    style?: any;
    mergeSpan?: JsMergeSpan;
    isMergedSecondary?: boolean;
    hyperlink?: any;
    comment?: any;
    formula?: string;
    image?: any;
}

interface JsRow {
    index: number;
    cells: Array<JsRowCell>;
}

interface JsMergeSpan {
    rowSpan: number;
    colSpan: number;
}

interface JsRowsOptions {
    useFormattedValues?: boolean;
    useCalculatedValues?: boolean;
    includeStyles?: boolean;
    includeMergeInfo?: boolean;
    includeHyperlinks?: boolean;
    includeComments?: boolean;
    includeFormulas?: boolean;
    includeImages?: boolean;
    skipEmptyValues?: boolean;
    skipBlankValues?: boolean;
}

interface ColorInput {
    colorType?: "auto" | "rgb" | "argb" | "theme" | "indexed";
    hex?: string;
    r?: number;
    g?: number;
    b?: number;
    a?: number;
    themeIndex?: number;
    tint?: number;
    paletteIndex?: number;
}

interface FontStyleInput {
    name?: string;
    size?: number;
    bold?: boolean;
    italic?: boolean;
    underline?: "none" | "single" | "double" | "singleAccounting" | "doubleAccounting";
    strikethrough?: boolean;
    color?: ColorInput;
    verticalAlign?: "baseline" | "superscript" | "subscript";
    family?: number;
    charset?: number;
    scheme?: string;
}

interface GradientStopInput {
    position: number;
    color: ColorInput;
}

interface FillStyleInput {
    fillType?: "none" | "solid" | "pattern" | "gradient";
    color?: ColorInput;
    pattern?: string;
    foreground?: ColorInput;
    background?: ColorInput;
    gradientType?: "linear" | "path";
    angle?: number;
    stops?: GradientStopInput[];
}

interface BorderEdgeInput {
    style?: "none" | "thin" | "medium" | "thick" | "dashed" | "dotted" | "double" | "hair" | "mediumDashed" | "dashDot" | "mediumDashDot" | "dashDotDot" | "mediumDashDotDot" | "slantDashDot";
    color?: ColorInput;
}

interface BorderStyleInput {
    left?: BorderEdgeInput;
    right?: BorderEdgeInput;
    top?: BorderEdgeInput;
    bottom?: BorderEdgeInput;
    diagonal?: BorderEdgeInput;
    diagonalDirection?: "none" | "down" | "up" | "both";
}

interface AlignmentInput {
    horizontal?: "general" | "left" | "center" | "right" | "fill" | "justify" | "centerContinuous" | "distributed";
    vertical?: "top" | "center" | "bottom" | "justify" | "distributed";
    wrapText?: boolean;
    shrinkToFit?: boolean;
    indent?: number;
    rotation?: number;
    readingOrder?: "contextDependent" | "leftToRight" | "rightToLeft";
}

interface NumberFormatInput {
    formatType?: "general" | "builtin" | "custom";
    id?: number;
    formatString?: string;
}

interface CellProtectionInput {
    locked?: boolean;
    hidden?: boolean;
}

interface StyleInput {
    font?: FontStyleInput;
    fill?: FillStyleInput;
    border?: BorderStyleInput;
    alignment?: AlignmentInput;
    numberFormat?: NumberFormatInput;
    protection?: CellProtectionInput;
}

declare class RowIterator implements IterableIterator<JsRow> {
    constructor(ws: Worksheet, opts?: JsRowsOptions, maxRow?: number);
    [Symbol.iterator](): RowIterator;
    next(): IteratorResult<JsRow>;
}

interface DrawingMeta {
    name?: string;
    hidden: boolean;
    locked: boolean;
    printable: boolean;
    altText?: string;
    title?: string;
}

interface DrawingMetaInput {
    name?: string;
    hidden?: boolean;
    locked?: boolean;
    printable?: boolean;
    altText?: string;
    title?: string;
}

interface DrawingCellMarker {
    col: number;
    row: number;
    colOffsetEmu?: number;
    rowOffsetEmu?: number;
}

type DrawingAnchor =
| { type: "twoCell"; from: DrawingCellMarker; to: DrawingCellMarker; editAs?: "twoCell" | "oneCell" | "absolute" }
| { type: "oneCell"; from: DrawingCellMarker; widthEmu: number; heightEmu: number }
| { type: "absolute"; xEmu: number; yEmu: number; widthEmu: number; heightEmu: number };

interface DrawingChildTransform {
    xEmu?: number;
    yEmu?: number;
    cxEmu?: number;
    cyEmu?: number;
    rotation?: number;
    flipH?: boolean;
    flipV?: boolean;
}

interface DrawingGroupTransform extends DrawingChildTransform {
    childXEmu?: number;
    childYEmu?: number;
    childCxEmu?: number;
    childCyEmu?: number;
}

type DrawingPlacement =
| { anchor: DrawingAnchor; transform?: never }
| { anchor?: never; transform: DrawingChildTransform };

type DrawingColor =
| { colorType: "auto" }
| { colorType: "rgb"; r: number; g: number; b: number }
| { colorType: "argb"; a: number; r: number; g: number; b: number }
| { colorType: "theme"; index: number; tint: number }
| { colorType: "indexed"; index: number };

interface DrawingRunFont {
    bold?: boolean;
    italic?: boolean;
    size?: number;
    color?: DrawingColor;
    name?: string;
    underline?: "none" | "single" | "double" | "singleAccounting" | "doubleAccounting";
    strikethrough?: boolean;
    verticalAlign?: "baseline" | "superscript" | "subscript";
    family?: number;
    charset?: number;
    scheme?: string;
}

interface DrawingText {
    runs: Array<{ text: string; font?: DrawingRunFont }>;
    horizontalAlignment?: "general" | "left" | "center" | "right" | "fill" | "justify" | "centerContinuous" | "distributed";
    verticalAlignment?: "top" | "center" | "bottom" | "justify" | "distributed";
}

type FormControlKind =
| { kind: "button"; caption: DrawingText }
| { kind: "checkbox"; caption: DrawingText; state: "unchecked" | "checked" | "mixed"; cellLink?: string; no3D: boolean }
/**
 * `firstInGroup` reports whether this radio heads its group; writers
 * recompute it from group-box containment, so it is read-side
 * information. `"mixed"` never validates on write but can surface
 * when reading hostile files.
 */
| { kind: "optionButton"; caption: DrawingText; state: "unchecked" | "checked" | "mixed"; cellLink?: string; firstInGroup: boolean; no3D: boolean }
| { kind: "label"; caption: DrawingText }
| { kind: "groupBox"; caption: DrawingText; no3D: boolean }
| { kind: "listBox"; inputRange?: string; cellLink?: string; selection: "single" | "multi" | "extend"; selected: number[]; no3D: boolean }
| { kind: "dropdown"; inputRange?: string; cellLink?: string; selected?: number; lines: number; no3D: boolean }
| { kind: "scrollbar"; value: number; min: number; max: number; increment: number; page: number; horizontal: boolean; cellLink?: string }
| { kind: "spinner"; value: number; min: number; max: number; increment: number; cellLink?: string }
/** Unsupported legacy control, preserved for passthrough. */
| { kind: "unknown"; objectType: string; legacyObjectType?: number; caption: DrawingText };

type FormControlKindInput =
| { kind: "button"; caption: DrawingText }
| { kind: "checkbox"; caption: DrawingText; state: "unchecked" | "checked" | "mixed"; cellLink?: string; no3D?: boolean }
/** `firstInGroup` is ignored on input; writers recompute it from group-box containment. */
| { kind: "optionButton"; caption: DrawingText; state: "unchecked" | "checked"; cellLink?: string; firstInGroup?: boolean; no3D?: boolean }
| { kind: "label"; caption: DrawingText }
| { kind: "groupBox"; caption: DrawingText; no3D?: boolean }
| { kind: "listBox"; inputRange?: string; cellLink?: string; selection: "single" | "multi" | "extend"; selected?: number[]; no3D?: boolean }
| { kind: "dropdown"; inputRange?: string; cellLink?: string; selected?: number; lines: number; no3D?: boolean }
| { kind: "scrollbar"; value: number; min: number; max: number; increment: number; page: number; horizontal?: boolean; cellLink?: string }
| { kind: "spinner"; value: number; min: number; max: number; increment: number; cellLink?: string }
| { kind: "unknown"; objectType: string; legacyObjectType?: number; caption?: DrawingText };

interface FormControlPayload {
    kind: FormControlKind;
    macroName?: string;
    /**
     * Unmodeled VML ClientData child fragments preserved on any control
     * kind; opaque internal passthrough echoed back unchanged on write.
     */
    rawClientData: number[][];
    /**
     * Unmodeled XLSX formControlPr attributes preserved on any control
     * kind; opaque internal passthrough echoed back unchanged on write.
     */
    rawProperties: Array<[string, string]>;
    /** Original BIFF OBJ body for XLS passthrough of unknown controls. */
    rawObj?: number[];
}

interface FormControlInputPayload {
    kind: FormControlKindInput;
    macroName?: string;
    /** Echo back the raw* fields unchanged when rewriting a control read from a file. */
    rawClientData?: Array<Uint8Array | number[]>;
    rawProperties?: Array<[string, string]>;
    rawObj?: Uint8Array | number[];
}

interface DrawingImage {
    format: "png" | "jpeg" | "gif" | "bmp" | "emf" | "wmf" | "tiff" | "svg";
    mediaPath: string;
    svgMediaPath?: string;
    widthEmu: number;
    heightEmu: number;
    rotation?: number;
    flipH: boolean;
    flipV: boolean;
}

interface DrawingImageInput extends Partial<Omit<DrawingImage, "format" | "widthEmu" | "heightEmu">> {
    format: DrawingImage["format"];
    widthEmu: number;
    heightEmu: number;
    data: Uint8Array | number[];
    svgData?: Uint8Array | number[];
}

type DrawingShapeFill =
| { kind: "none" }
| { kind: "solid"; color: DrawingColor };

interface DrawingShape {
    geometry: string;
    fill: DrawingShapeFill;
    line: { color?: DrawingColor; widthEmu?: number; dashStyle?: string; noFill: boolean };
    text?: DrawingText;
    rotation: number;
    flipH: boolean;
    flipV: boolean;
}

interface DrawingShapeInput extends Partial<DrawingShape> {
    geometry?: string;
}

interface DrawingComment {
    row: number;
    col: number;
    author: string;
    /** Plain text (runs concatenated). */
    text: string;
    /**
     * Rich runs; present on output when any run is formatted, and wins
     * over `text` on input when supplied.
     */
    richText?: DrawingText;
}

type ChartDataReference =
| { refType: "formula"; formula: string }
| { refType: "numbers"; numbers: number[] }
| { refType: "strings"; strings: string[] };

interface ChartShapeProperties {
    solidFillHex?: string;
    noFill: boolean;
    lineWidth?: number;
    lineColorHex?: string;
    lineNoFill: boolean;
    lineDashStyle?: string;
}

interface ChartNumberFormat {
    formatCode: string;
    sourceLinked?: boolean;
}

interface ChartDataLabels {
    showLegendKey?: boolean;
    showValue?: boolean;
    showCategoryName?: boolean;
    showSeriesName?: boolean;
    showPercent?: boolean;
    showBubbleSize?: boolean;
    separator?: string;
    position?: string;
    numberFormat?: ChartNumberFormat;
    showLeaderLines?: boolean;
}

interface ChartDataSeries {
    name?: string;
    values: ChartDataReference;
    categories?: ChartDataReference;
    dataLabels?: ChartDataLabels;
    trendline?: { trendlineType: string; name?: string; order?: number; period?: number; forward?: number; backward?: number; intercept?: number; displayRSquared?: boolean; displayEquation?: boolean };
    errorBars?: { direction: string; barType: string; valueType: string; value?: number; noEndCap?: boolean };
    marker?: { symbol?: string; size?: number };
    dataPoints: Array<{ index: number; marker?: { symbol?: string; size?: number }; explosion?: number; shapeProperties?: ChartShapeProperties }>;
    smooth?: boolean;
    explosion?: number;
    invertIfNegative?: boolean;
    shapeProperties?: ChartShapeProperties;
}

interface ChartAxis {
    title?: string;
    minimum?: number;
    maximum?: number;
    majorUnit?: number;
    minorUnit?: number;
    position: "bottom" | "top" | "left" | "right";
    numberFormat?: ChartNumberFormat;
    majorGridlines: boolean;
    minorGridlines: boolean;
    majorGridlinesShapeProperties?: ChartShapeProperties;
    minorGridlinesShapeProperties?: ChartShapeProperties;
    majorTickMark?: string;
    minorTickMark?: string;
    labelPosition?: string;
    delete?: boolean;
    crosses?: string;
    crossBetween?: string;
    shapeProperties?: ChartShapeProperties;
}

interface Chart {
    pivotSource?: { name: string; formatId: number } | null;
    pivotModified?: boolean;
    chartType: string;
    title?: string;
    series: ChartDataSeries[];
    categoryAxis?: ChartAxis;
    valueAxis?: ChartAxis;
    legend?: { position: string; overlay: boolean };
    dataLabels?: ChartDataLabels;
    view3D?: { rotateX?: number; rotateY?: number; depthPercent?: number; heightPercent?: number; perspective?: number; rightAngleAxes?: boolean };
    dataTable?: { showHorizontalBorder?: boolean; showVerticalBorder?: boolean; showOutline?: boolean; showKeys?: boolean };
    displayBlanksAs?: "gap" | "span" | "zero";
    plotVisibleOnly?: boolean;
    layout?: { manualLayout?: { x?: number; y?: number; width?: number; height?: number } };
    shapeProperties?: ChartShapeProperties;
    is3D: boolean;
    varyColors?: boolean;
    gapWidth?: number;
    overlap?: number;
    firstSliceAngle?: number;
    holeSize?: number;
    bubbleScale?: number;
    showNegativeBubbles?: boolean;
    autoTitleDeleted?: boolean;
    roundedCorners?: boolean;
    showDlblsOverMax?: boolean;
    wireframe?: boolean;
    radarStyle?: string;
    typeGroups: Array<{ chartType: string; is3D: boolean; series: ChartDataSeries[]; dataLabels?: ChartDataLabels; varyColors?: boolean; gapWidth?: number; overlap?: number; firstSliceAngle?: number; holeSize?: number; bubbleScale?: number; showNegativeBubbles?: boolean; radarStyle?: string; wireframe?: boolean; axisIds: number[] }>;
    axes: Array<{ id: number; crossId: number; axis: ChartAxis }>;
}

interface ChartSeriesInput {
    name?: string;
    values: ChartDataReference;
    categories?: ChartDataReference;
}

/** Exactly the chart fields accepted when authoring; all other Chart fields are read-only. */
interface ChartInput {
    chartType: string;
    title?: string;
    series?: ChartSeriesInput[];
    is3D?: boolean;
    varyColors?: boolean;
    gapWidth?: number;
    overlap?: number;
}

interface ChartExTitle {
    text?: string;
    position?: string;
    align?: string;
    overlay?: boolean;
    offset?: { top?: number; left?: number };
    shapeProperties?: ChartShapeProperties;
}

interface ChartStyleReference {
    idx: number
    /** The colour override, as the XML it was read as. */
    color?: string
}

interface ChartStyleEntry {
    lineReference: ChartStyleReference
    lineWidthScale?: number
    fillReference: ChartStyleReference
    effectReference: ChartStyleReference
    /** `major`, `minor` or `none`. */
    fontCollection: string
    fontColor?: string
    /** DrawingML kept as the XML it was read as. */
    shapeProperties?: string
    defaultRunProperties?: string
    bodyProperties?: string
    mods?: string
}

/**
 * A chart style part. `entries` is keyed by the element name the entry
 * belongs to (`chartArea`, `dataPoint`, ...); `raw` is set instead when
 * the part could not be modelled and is replayed as read.
 */
interface ChartStyle {
    id?: number
    entries: Record<string, ChartStyleEntry>
    markerSymbol?: string
    markerSize?: number
    raw?: string
}

/** A chart colour style part. `raw` is set when it could not be modelled. */
interface ChartColorStyle {
    method?: string
    id?: number
    colors: string[]
    variations: string[]
    raw?: string
}

interface ChartExGridlines {
    shapeProperties?: ChartShapeProperties;
}

interface ChartExDataLabelOverride {
    idx: number;
    position?: string;
    visibilitySeriesName?: boolean;
    visibilityCategoryName?: boolean;
    visibilityValue?: boolean;
    numberFormat?: ChartNumberFormat;
    separator?: string;
    shapeProperties?: ChartShapeProperties;
}

interface ChartExColorPosition {
    positionType: 'extremeValue' | 'number' | 'percent';
    value?: number;
}

interface ChartExSeriesLayoutProperties {
    parentLabelLayout?: string;
    regionLabelLayout?: string;
    visibility?: { connectorLines?: boolean; meanLine?: boolean; meanMarker?: boolean; nonoutliers?: boolean; outliers?: boolean };
    aggregation: boolean;
    binning?: { intervalClosed?: string; underflow?: string; overflow?: string; binSize?: number; binCount?: number };
    geography?: { projectionType?: string; viewedRegionType?: string; cultureLanguage?: string; cultureRegion?: string; attribution?: string };
    statistics?: { quartileMethod?: string };
    /** Absent when the cx:subtotals element is absent; [] when it is present but empty. */
    subtotals?: number[];
}

interface ChartExSeries {
    layout: string;
    dataId: number;
    uniqueId?: string;
    hidden?: boolean;
    ownerIdx?: number;
    formatIdx?: number;
    text?: { formula?: string; value?: string };
    dataLabels?: { position?: string; visibilitySeriesName?: boolean; visibilityCategoryName?: boolean; visibilityValue?: boolean; numberFormat?: ChartNumberFormat; separator?: string; shapeProperties?: ChartShapeProperties; overrides: ChartExDataLabelOverride[]; hiddenLabels: number[] };
    dataPoints: Array<{ idx: number; shapeProperties?: ChartShapeProperties }>;
    layoutProperties?: ChartExSeriesLayoutProperties;
    axisIds: number[];
    valueColors: boolean;
    valueColorPositions?: { count?: number; min?: ChartExColorPosition; mid?: ChartExColorPosition; max?: ChartExColorPosition };
    shapeProperties?: ChartShapeProperties;
}

interface ChartExAxis {
    id: number;
    hidden?: boolean;
    scaling: { scalingType: string; gapWidth?: number; min?: number; max?: number; majorUnit?: number; minorUnit?: number };
    title?: { text?: string; shapeProperties?: ChartShapeProperties };
    units?: { unit?: string };
    majorGridlines?: ChartExGridlines;
    minorGridlines?: ChartExGridlines;
    majorTickMarks?: string;
    minorTickMarks?: string;
    tickLabels: boolean;
    numberFormat?: ChartNumberFormat;
    shapeProperties?: ChartShapeProperties;
}

interface ChartEx {
    layout: string;
    version?: string;
    featureList?: string;
    fallbackImg?: string;
    title?: ChartExTitle;
    data: Array<{ id: number; dimensions: Array<{ dimType: string; formula?: string; nfFormula?: string }> }>;
    plotArea: { plotSurface?: ChartShapeProperties; series: ChartExSeries[]; axes: ChartExAxis[]; shapeProperties?: ChartShapeProperties };
    legend?: { position?: string; align?: string; overlay?: boolean; offset?: { top?: number; left?: number }; shapeProperties?: ChartShapeProperties };
    shapeProperties?: ChartShapeProperties;
    formatOverrides: Array<{ idx: number; shapeProperties?: ChartShapeProperties }>;
    externalDataRelId?: string;
    externalDataAutoUpdate?: boolean;
    style?: ChartStyle;
    colorStyle?: ChartColorStyle;
}

interface ChartExTitleInput {
    text?: string;
    position?: string;
    align?: string;
    overlay?: boolean;
}

/** Exactly the ChartEx fields accepted when authoring; all other ChartEx fields are read-only. */
interface ChartExInput {
    layout: string;
    version?: string;
    featureList?: string;
    fallbackImg?: string;
    title?: ChartExTitleInput;
}

interface RawDrawingMetadata {
    byteLength: number;
    relationships: Array<{ id: string; relType: string; target: string; external: boolean; hasPart: boolean }>;
}

/**
 * Resolved on-sheet placement in EMU: the anchor rectangle for
 * top-level drawings, the group-mapped (rotation/flip aware)
 * rectangle for group children.
 */
type RectEmu = { xEmu: number; yEmu: number; widthEmu: number; heightEmu: number };

type DrawingNode = DrawingMeta & DrawingPlacement & { drawingPath: number[]; absoluteRectEmu: RectEmu };

type ImageDrawing = DrawingNode & { kind: "image"; image: DrawingImage };
type ChartDrawing = DrawingNode & { kind: "chart"; chart: Chart };
type ChartExDrawing = DrawingNode & { kind: "chartEx"; chartEx: ChartEx };
type FormControlDrawing = DrawingNode & { kind: "formControl"; formControl: FormControlPayload };
type CommentDrawing = DrawingNode & { kind: "comment"; comment: DrawingComment };
type ShapeDrawing = DrawingNode & { kind: "shape"; shape: DrawingShape };
type GroupDrawing = DrawingNode & { kind: "group"; group: { groupTransform: DrawingGroupTransform; children: Drawing[] } };
type RawDrawing = DrawingNode & { kind: "raw"; raw: RawDrawingMetadata };

type Drawing = ImageDrawing | ChartDrawing | ChartExDrawing | FormControlDrawing | CommentDrawing | ShapeDrawing | GroupDrawing | RawDrawing;

type DrawingInputPlacement =
| { anchor: DrawingAnchor; transform?: never }
| { anchor?: never; transform: DrawingChildTransform };

type DrawingInput = DrawingMetaInput & DrawingInputPlacement & (
| { kind: "image"; image: DrawingImageInput }
| { kind: "chart"; chart: ChartInput }
| { kind: "chartEx"; chartEx: ChartExInput }
| { kind: "formControl"; formControl: FormControlInputPayload }
| { kind: "comment"; comment: DrawingComment }
| { kind: "shape"; shape: DrawingShapeInput }
| { kind: "group"; group: { groupTransform?: DrawingGroupTransform; children?: DrawingInput[] } }
);

interface FormControlInteractionResult {
    controlsChanged: number;
    linkedCellsChanged: number;
}



declare class CellValue {
    private constructor();
    free(): void;
    [Symbol.dispose](): void;
    asBoolean(): boolean | undefined;
    asError(): string | undefined;
    asNumber(): number | undefined;
    asText(): string | undefined;
    toJs(): any;
    toString(): string;
    readonly is_boolean: boolean;
    readonly is_empty: boolean;
    readonly is_error: boolean;
    readonly is_number: boolean;
    readonly is_text: boolean;
}

interface Workbook {
    /**
     * Resolve a drawing color to display RGB ("RRGGBB" hex) against
     * this workbook's theme palette; `auto` resolves to undefined.
     */
    resolveColor(color: DrawingColor): string | undefined;
}

declare class Workbook {
    free(): void;
    [Symbol.dispose](): void;
    addSheet(name: string): number;
    calculate(options?: any | null): any;
    createPivotChart(id: string, options: any): any;
    defineName(name: string, refers_to: string): void;
    exportSnapshot(): Uint8Array;
    fontFamilies(): string[];
    /**
     * Load a workbook from bytes, auto-detecting the format (XLSX or XLS).
     */
    static fromBytes(data: Uint8Array): Workbook;
    static fromBytesForViewer(data: Uint8Array): Workbook;
    /**
     * Load a password-protected workbook from bytes, auto-detecting
     * the format (XLSX or XLS). `skipIntegrityCheck` skips the HMAC
     * integrity check on Agile-encrypted files (matches Office
     * behaviour); defaults to false.
     */
    static fromBytesWithPassword(data: Uint8Array, password: string, skip_integrity_check?: boolean | null): Workbook;
    static fromCsvString(csv: string): Workbook;
    static fromSnapshot(data: Uint8Array): Workbook;
    getNamedRange(name: string): string | undefined;
    getPivotSourceFields(source: any): any;
    getSheet(index: number): Worksheet;
    getSheetByName(name: string): Worksheet;
    static loadCsvString(csv: string): Workbook;
    modifiedPivotCharts(): any;
    constructor();
    pivotDrillDown(id: string, row: number, col: number): any;
    refreshPivotTable(id: string): any;
    removePivotTable(id: string): boolean;
    removeSheet(index: number): void;
    /**
     * Save the first sheet as a CSV string, with form-control state
     * synchronized into linked cells in the output.
     */
    saveCsvString(): string;
    /**
     * Save the workbook as encrypted XLS bytes after synchronizing
     * form-control state into linked cells. `profile` selects
     * the FilePass variant; `null` defaults to RC4 CryptoAPI 128.
     * Valid values: `"rc4-cryptoapi"`, `"rc4-legacy"`, `"xor"`.
     * `keyBits` controls RC4 CryptoAPI key size (40 or 128). XOR is
     * not certified to interoperate with modern Excel.
     */
    saveXlsBytesEncrypted(password: string, profile?: string | null, key_bits?: number | null): Uint8Array;
    /**
     * Save XLSB bytes with form-control state synchronized into linked cells,
     * replacing existing values and formulas in the output.
     */
    saveXlsbBytes(): Uint8Array;
    /**
     * Save XLSX bytes with form-control state synchronized into linked cells,
     * replacing existing values and formulas in the output.
     */
    saveXlsxBytes(): Uint8Array;
    /**
     * Save the workbook as encrypted XLSX bytes after synchronizing
     * form-control state into linked cells. `profile` selects
     * the encryption variant; passing `null`/`undefined` uses the
     * Agile-256 default. Valid values: `"agile"`, `"standard"`.
     * `keyBits` and `spinCount` override the defaults where the
     * profile supports them.
     */
    saveXlsxBytesEncrypted(password: string, profile?: string | null, key_bits?: number | null, spin_count?: number | null): Uint8Array;
    setWorkbookProtection(protection: any): void;
    sheetIndex(name: string): number | undefined;
    /**
     * Project all form-control state into linked cells.
     */
    syncFormControls(): number;
    /**
     * Drive controls from formula-backed linked cells.
     */
    syncFormControlsFromLinkedCells(): number;
    takeViewerArchive(): any;
    updatePivotChart(sheet: string, name: string, patch: any): void;
    upsertPivotTable(input: any): any;
    readonly activeSheet: number;
    readonly chartsheetCount: number;
    readonly chartsheets: any;
    readonly isEmpty: boolean;
    readonly namedRanges: any;
    readonly pivotTables: any;
    readonly settings: any;
    readonly sheetCount: number;
    readonly sheetNames: string[];
    readonly sheetOrder: any;
    /**
     * The workbook theme's 12 clrScheme colors as `RRGGBB` hex, in
     * theme-index order (background 1, text 1, background 2, text 2,
     * accent 1-6, hyperlink, followed hyperlink). The Office default
     * palette when the file carries no theme.
     */
    readonly themePalette: string[];
    readonly totalSheetCount: number;
    readonly workbookProtection: any;
}

interface Worksheet {
    getAutofitCells(axis: "column" | "row", index: number): JsRow[];
    getAutoHeightCells(rowCount: number, colCount: number): JsRow[];
    iterateRows(opts?: JsRowsOptions): RowIterator;
    setCellStyle(address: string, style: StyleInput): void;
    setCellStyleAt(row: number, col: number, style: StyleInput): void;
    setRangeStyle(range: string, style: StyleInput): void;
    readonly drawings: Drawing[];
    readonly formControls: FormControlDrawing[];
    readonly formControlCount: number;
    readonly images: ImageDrawing[];
    readonly imageCount: number;
    readonly charts: ChartDrawing[];
    readonly chartCount: number;
    readonly chartsEx: ChartExDrawing[];
    readonly chartExCount: number;
    addDrawing(drawing: DrawingInput & { anchor: DrawingAnchor }): number;
    /** Drawing paths are positional; mutating the list invalidates previously returned paths. */
    insertDrawing(index: number, drawing: DrawingInput & { anchor: DrawingAnchor }): void;
    /** Drawing paths are positional; mutating the list invalidates previously returned paths. */
    setDrawing(path: number[], drawing: DrawingInput): void;
    /** Drawing paths are positional; mutating the list invalidates previously returned paths. */
    removeDrawing(path: number[]): void;
    /** Drawing paths are positional; mutating the list invalidates previously returned paths. */
    moveDrawing(from: number, to: number): void;
    /** Paths are positional; mutating the drawing list invalidates previously returned paths. */
    drawingImageData(path: number[]): Uint8Array;
    /** Paths are positional; mutating the drawing list invalidates previously returned paths. */
    drawingSvgData(path: number[]): Uint8Array | undefined;
    setFormControlCheckState(path: number[], state: "unchecked" | "checked" | "mixed"): FormControlInteractionResult;
}

declare class Worksheet {
    private constructor();
    free(): void;
    [Symbol.dispose](): void;
    getCalculatedValue(address: string): CellValue;
    getCalculatedValueAt(row: number, col: number): CellValue;
    getCell(address: string): CellValue;
    getCellAt(row: number, col: number): CellValue;
    getCellStyle(address: string): any;
    getCellStyleAt(row: number, col: number): any;
    getColumnOutlineLevel(col: number): number;
    getColumnWidth(col: number): number | undefined;
    getComment(address: string): any;
    getCommentAt(row: number, col: number): any;
    getFormattedValue(address: string): string;
    getFormattedValueAt(row: number, col: number): string;
    getFormulaAt(row: number, col: number): string | undefined;
    getHyperlink(address: string): any;
    getHyperlinkAt(row: number, col: number): any;
    getImageAt(row: number, col: number): any;
    getMergeSpan(row: number, col: number): any;
    getRichTextAt(row: number, col: number): any;
    getRowHeight(row: number): number | undefined;
    getRowOutlineLevel(row: number): number;
    getSpillSource(row: number, col: number): any;
    getTableByName(name: string): any;
    getValueSnapshotAt(row: number, col: number): Uint8Array;
    hasComment(address: string): boolean;
    hasCommentAt(row: number, col: number): boolean;
    isColumnCollapsed(col: number): boolean;
    isColumnHidden(col: number): boolean;
    isMergedSecondary(row: number, col: number): boolean;
    isRowCollapsed(row: number): boolean;
    isRowHidden(row: number): boolean;
    isSpillSource(row: number, col: number): boolean;
    isSpillTarget(row: number, col: number): boolean;
    mergeCells(range_str: string): void;
    restoreValueSnapshotAt(row: number, col: number, bytes: Uint8Array): void;
    setCell(address: string, value: any): void;
    setCellStyle(address: string, style: any): void;
    setCellStyleAt(row: number, col: number, style: any): void;
    setColumnWidth(col: number, width: number): void;
    setColumnsHidden(start: number, end: number, hidden: boolean): void;
    setFormula(address: string, formula: string): void;
    setFreezePanes(row: number, col: number): void;
    setProtectedRanges(ranges: any): void;
    setProtection(protection: any): void;
    setRangeStyle(range_str: string, style: any): void;
    setRowHeight(row: number, height: number): void;
    setRowsHidden(start: number, end: number, hidden: boolean): void;
    unmergeCells(range_str: string): boolean;
    usedRange(): any;
    readonly autoFilter: any;
    readonly cellCount: number;
    readonly colBreaks: any;
    readonly commentAuthors: string[];
    readonly commentCount: number;
    readonly comments: any;
    readonly conditionalFormatCount: number;
    readonly conditionalFormats: any;
    readonly dataValidationCount: number;
    readonly dataValidations: any;
    readonly date1904: boolean;
    readonly defaultColumnWidth: number;
    readonly defaultRowHeight: number;
    readonly formulaCells: any;
    /**
     * Get the number of formula cells in this worksheet.
     */
    readonly formulaCount: number;
    readonly freezePanes: any;
    readonly hiddenColumns: Uint32Array;
    readonly hiddenRows: Uint32Array;
    readonly hyperlinkCount: number;
    readonly hyperlinks: any;
    readonly isEmpty: boolean;
    readonly isSelected: boolean;
    readonly mergedRegions: any;
    readonly name: string;
    readonly pageSetup: any;
    readonly printArea: string | undefined;
    readonly protectedRanges: any;
    readonly protection: any;
    readonly repeatCols: Uint32Array | undefined;
    readonly repeatRows: Uint32Array | undefined;
    readonly rowBreaks: any;
    readonly selections: any;
    readonly splitPanes: any;
    readonly tabColor: any;
    readonly tableCount: number;
    readonly tables: any;
    readonly visibility: string;
    readonly zoomScale: number | undefined;
}

type XlsxPivotAggregation = "sum" | "count" | "countNums" | "average" | "min" | "max" | "product" | "var" | "varp" | "stdDev" | "stdDevp";
type XlsxPivotShowAs = "normal" | "percentOfGrandTotal" | "percentOfRowTotal" | "percentOfColumnTotal" | "percentOfParentRowTotal" | "percentOfParentColumnTotal" | "difference" | "percentDifference" | "percent" | "runningTotal" | "percentRunningTotal" | "rankAscending" | "rankDescending" | "index";
/** Worksheet source range, table, or supported static defined name. */
interface XlsxPivotSource {
    sheet: string;
    range: string;
    table?: string | null;
}
/** Existing destination worksheet and its A1-style anchor address. */
interface XlsxPivotTarget {
    sheet: string;
    cell: string;
}
/** Use the typed key for filtering and base items; the caption is display text. */
interface XlsxPivotMember {
    key: string;
    caption: string;
}
/** Indexes identify zero-based source columns. */
interface XlsxPivotSourceField {
    index: number;
    name: string;
    dataType: string;
    items: XlsxPivotMember[];
}
interface XlsxPivotGrouping {
    kind: "number" | "date" | "manual";
    unit: "years" | "quarters" | "months" | "days" | "hours" | "minutes" | "seconds";
    interval: number;
    start?: number | null;
    end?: number | null;
    groups: {
        name: string;
        members: string[];
    }[];
}
interface XlsxPivotAxisField {
    /** Zero-based source field index; date hierarchy levels may share a field. */
    field: number;
    name?: string | null;
    sort: "ascending" | "descending" | "manual" | "valueAscending" | "valueDescending";
    /** Zero-based index in the report's values array for value-based sorting. */
    sortMeasure?: number | null;
    items?: XlsxPivotMember[];
    subtotalFunctions?: XlsxPivotAggregation[];
    showItemsWithNoData?: boolean;
    subtotals: boolean;
    collapsed: string[];
    grouping?: XlsxPivotGrouping | null;
}
interface XlsxPivotFilter {
    field: number;
    /** Identifies the effective grouped level when a source field has multiple levels. */
    groupingUnit?: string | null;
    kind: "members" | "label" | "value" | "top10";
    /** Typed member keys for a member filter. */
    values: string[];
    operator: "equal" | "notEqual" | "contains" | "notContains" | "beginsWith" | "notBeginsWith" | "endsWith" | "notEndsWith" | "greaterThan" | "greaterThanOrEqual" | "lessThan" | "lessThanOrEqual" | "between" | "notBetween";
    value: string;
    value2: string;
    /** Zero-based index in the report's values array. */
    measure: number;
    top: boolean;
    count: number;
    percent: boolean;
}
interface XlsxPivotValueField {
    field: number;
    /** Stable calculated-field name, independent of its displayed caption. */
    sourceName?: string | null;
    name: string;
    aggregation: XlsxPivotAggregation;
    showAs: XlsxPivotShowAs;
    baseField?: number | null;
    baseGroupingUnit?: string | null;
    /** Typed member key, or "previous"/"next", used by relative Show Values As calculations. */
    baseItem?: string | null;
    numberFormat?: string | null;
    formula?: string | null;
}
interface XlsxPivotCalculatedItem {
    field: number;
    name: string;
    formula: string;
}
type XlsxPivotChartType = "ColumnClustered" | "ColumnStacked" | "ColumnPercentStacked" | "BarClustered" | "BarStacked" | "BarPercentStacked" | "Line" | "LineStacked" | "Area" | "AreaStacked" | "AreaPercentStacked" | "Pie" | "Doughnut";
interface XlsxPivotChartInput {
    sheet?: string;
    cell?: string;
    chartType?: XlsxPivotChartType;
    title?: string;
    width?: number;
    height?: number;
    measure?: number | null;
}
interface XlsxPivotChart extends XlsxPivotChartInput {
    sheet: string;
    drawingName: string;
    chartType: XlsxPivotChartType;
    title: string;
    workbookName: string;
    formatId: number;
    measure?: number | null;
}
/** Expansion control with zero-based worksheet coordinates. */
interface XlsxPivotToggle {
    row: number;
    col: number;
    axis: "rows" | "columns";
    field: number;
    depth?: number;
    key: string;
    collapsed: boolean;
    caption: string;
}
interface XlsxPivotHeaderField {
    field: number;
    depth: number;
    name: string;
    groupingUnit?: string | null;
}
/** Sort/filter header with zero-based worksheet coordinates. */
interface XlsxPivotHeader {
    row: number;
    col: number;
    axis: "rows" | "columns" | "reportFilters";
    caption: string;
    fields: XlsxPivotHeaderField[];
}
interface XlsxPivotTable {
    id: string;
    name: string;
    source: XlsxPivotSource;
    target: XlsxPivotTarget;
    rows: XlsxPivotAxisField[];
    columns: XlsxPivotAxisField[];
    filters: XlsxPivotFilter[];
    reportFilters: number[];
    values: XlsxPivotValueField[];
    layout: "compact" | "outline" | "tabular";
    valuesOnRows?: boolean;
    repeatLabels: boolean;
    /** Preserve existing report formatting when rebuilding results. Defaults to true. */
    preserveFormatting?: boolean;
    rowGrandTotals: boolean;
    columnGrandTotals: boolean;
    subtotalsPosition: "top" | "bottom" | "none";
    styleName: string;
    fields: XlsxPivotSourceField[];
    outputRange?: string | null;
    /** Reasons the report can be viewed but cannot be edited or refreshed. */
    unsupportedFeatures: string[];
    /** Refresh from worksheet source data when the workbook opens. */
    refreshOnLoad: boolean;
    /** Automatic refresh failure; saved results remain available. */
    refreshError?: string;
    calculatedItems: XlsxPivotCalculatedItem[];
    charts?: XlsxPivotChart[];
    toggles?: XlsxPivotToggle[];
    headers?: XlsxPivotHeader[];
}
/** Supply an existing id to update a report; omit it to create one. */
type XlsxPivotTableInput = Pick<XlsxPivotTable, "source" | "target"> & Partial<Omit<XlsxPivotTable, "source" | "target">>;
interface XlsxPivotDrillDown {
    fields: string[];
    rows: (string | number | boolean | null)[][];
}
interface XlsxViewerPivots {
    /** Workbook-wide report metadata, including reports on inactive worksheets. */
    pivotTables: XlsxPivotTable[];
    /** Shared visibility for default/custom field lists and active-report guides. */
    pivotFieldListVisible: boolean;
    /** Explicitly show or hide the field list; hiding suppresses automatic reopening. */
    setPivotFieldListVisible: (visible: boolean) => void;
    /** Inspect source columns and typed member keys without creating a report. */
    getPivotSourceFields: (source: XlsxPivotSource) => XlsxPivotSourceField[];
    /** Find a report at zero-based worksheet coordinates; defaults to the active sheet. */
    getPivotTableAtCell: (cell: XlsxCellAddress, sheetName?: string) => XlsxPivotTable | null;
    /** Create or update a report atomically. Invalid or disallowed mutations throw. */
    upsertPivotTable: (input: XlsxPivotTableInput) => XlsxPivotTable;
    /** Rebuild the saved cache and report from source data as an undoable mutation. */
    refreshPivotTable: (id: string) => XlsxPivotTable;
    /** Refresh reports in one transaction; dependency chains are not reordered. */
    refreshAllPivotTables: () => XlsxPivotTable[];
    /** Remove a report and detach linked PivotCharts; returns whether it was found. */
    removePivotTable: (id: string) => boolean;
    /** Read source records behind a result at zero-based worksheet coordinates. */
    pivotDrillDown: (id: string, row: number, col: number) => XlsxPivotDrillDown;
    /** Create an undoable details worksheet and return its name. Coordinates are zero-based. */
    showPivotDetails: (id: string, row: number, col: number) => string;
    /** Create a linked chart whose data stays synchronized with the report. */
    createPivotChart: (id: string, options?: XlsxPivotChartInput) => XlsxPivotChart;
    /** Expand or collapse a group using a toggle from the report's metadata. */
    togglePivotGroup: (id: string, toggle: XlsxPivotToggle) => XlsxPivotTable;
}

type XlsxPivotFieldArea = "rows" | "columns" | "values" | "reportFilters";
interface XlsxPivotTableEditorOptions {
    /** Follow the active pivot when no draft changes are pending. Defaults to true. */
    autoSelect?: boolean;
    /** Set field-list visibility on workbook changes; omit to retain automatic opening. */
    initialOpen?: boolean;
    /** Enable automatic draft synchronization and draft edits. Defaults to true. */
    enabled?: boolean;
}
/** Shared headless field-list state. Draft edits take effect when apply() succeeds. */
interface XlsxPivotTableEditor {
    viewer: XlsxViewerController;
    readOnly: boolean;
    open: boolean;
    setOpen: (open: boolean) => void;
    draft: XlsxPivotTable | null;
    dirty: boolean;
    /** The saved report changed while this editor had unapplied changes. */
    stale: boolean;
    /** The draft source changed and must be inspected with readFields() before applying. */
    sourceNeedsLoad: boolean;
    error: string | null;
    status: string | null;
    edit: (change: (pivot: XlsxPivotTable) => XlsxPivotTable) => void;
    select: (id: string) => void;
    create: () => void;
    apply: () => void;
    reset: () => void;
    remove: () => void;
    refresh: (all?: boolean) => void;
    readFields: () => void;
    /** Add a zero-based source field index to a report area. */
    addField: (area: XlsxPivotFieldArea, field: number) => void;
    /** Remove an entry by its zero-based position within the area. */
    removeField: (area: XlsxPivotFieldArea, index: number) => void;
    moveField: (fromArea: XlsxPivotFieldArea, fromIndex: number, toArea: XlsxPivotFieldArea, toIndex?: number) => void;
    details: XlsxPivotDrillDown | null;
    detailContext: {
        id: string;
        row: number;
        col: number;
    } | null;
    showDetails: () => void;
    clearDetails: () => void;
    /** Run a synchronous action and capture any thrown error in editor.error. */
    run: (action: () => void) => void;
}
interface XlsxPivotTableControlsRenderProps {
    editor: XlsxPivotTableEditor;
    controller: XlsxViewerController;
    defaultNode: React.ReactNode;
    isDark: boolean;
}

interface XlsxPivotTableHeaderMenuRenderProps {
    pivot: XlsxPivotTable;
    header: XlsxPivotHeader;
    field: XlsxPivotHeaderField;
    /** Choose an effective field by its header depth, including grouped levels. */
    setField: (depth: number) => void;
    members: XlsxPivotMember[];
    filters: XlsxPivotFilter[];
    sort: XlsxPivotAxisField["sort"] | null;
    readOnly: boolean;
    isOpen: boolean;
    setOpen: (open: boolean) => void;
    close: () => void;
    error: string | null;
    /** Forward the ref, events, and positioning style to the actual trigger button. */
    triggerProps: React.ComponentPropsWithRef<"button">;
    /** Forward the ref and events to the popup; contain nested popup portals within it. */
    popupProps: React.ComponentPropsWithRef<"div">;
    defaultNode: React.ReactNode;
    /** Sort labels or values; measure is a zero-based index in the report's values array. */
    sortBy: (direction: XlsxPivotAxisField["sort"], measure?: number) => void;
    /** Select typed member keys, or pass null to remove the member filter. */
    setMembers: (keys: string[] | null) => void;
    setFilter: (filter: XlsxPivotFilter) => void;
    clearFilters: () => void;
}

interface XlsxThemePalette {
    colorsByIndex: Record<number, string>;
    majorLatinFont?: string;
    minorLatinFont?: string;
}
interface XlsxResolvedCellStyle {
    [key: string]: unknown;
    alignment?: Record<string, unknown>;
    border?: Record<string, Record<string, unknown>>;
    cellControl?: {
        kind: "checkbox";
    };
    fill?: Record<string, unknown>;
    font?: Record<string, unknown>;
    tableStyleOverrides?: XlsxResolvedCellStyle;
}
interface XlsxTableStyleDefinition {
    [elementType: string]: XlsxResolvedCellStyle;
}
interface XlsxConditionalFormatValueObject {
    type: string;
    value?: number;
}
interface XlsxConditionalDataBarRule {
    axisColor?: Record<string, unknown>;
    border?: boolean;
    color?: Record<string, unknown>;
    borderColor?: Record<string, unknown>;
    cfvos: XlsxConditionalFormatValueObject[];
    gradient?: boolean;
    kind: "dataBar";
    maxLength?: number;
    minLength?: number;
    negativeBarBorderColorSameAsPositive?: boolean;
    negativeBorderColor?: Record<string, unknown>;
    negativeFillColor?: Record<string, unknown>;
    priority: number;
    ranges: XlsxCellRange[];
    showValue?: boolean;
}
interface XlsxConditionalColorScaleRule {
    cfvos: XlsxConditionalFormatValueObject[];
    colors: Record<string, unknown>[];
    kind: "colorScale";
    priority: number;
    ranges: XlsxCellRange[];
}
interface XlsxConditionalFormatIcon {
    iconId: number;
    iconSet: string;
}
interface XlsxConditionalIconSetRule {
    cfvos: XlsxConditionalFormatValueObject[];
    icons: XlsxConditionalFormatIcon[];
    kind: "iconSet";
    priority: number;
    ranges: XlsxCellRange[];
    reverse?: boolean;
    showValue?: boolean;
}
interface XlsxConditionalStyledRule {
    aboveAverage?: boolean;
    bottom?: boolean;
    equalAverage?: boolean;
    formulas: string[];
    kind: "styled";
    operator?: string;
    percent?: boolean;
    priority: number;
    rank?: number;
    ranges: XlsxCellRange[];
    ruleType: string;
    stdDev?: number;
    stopIfTrue?: boolean;
    style: XlsxResolvedCellStyle;
    text?: string;
    timePeriod?: string;
}
type XlsxConditionalFormatRule = XlsxConditionalColorScaleRule | XlsxConditionalStyledRule | XlsxConditionalDataBarRule | XlsxConditionalIconSetRule;
interface XlsxDataValidation {
    allowBlank?: boolean;
    errorMessage?: string;
    errorStyle?: string;
    inputMessage?: string;
    listSource?: string;
    ranges: XlsxCellRange[];
    showDropdown?: boolean;
    showErrorAlert?: boolean;
    showInputMessage?: boolean;
    validationType: string;
}
interface XlsxFreezePanes {
    col: number;
    row: number;
}
type XlsxSheetVisibility = "hidden" | "veryHidden" | "visible";
interface XlsxOfficeLayout {
    columnDigitWidthPt?: number;
    defaultColumnPx: number;
    defaultRowPx: number;
    columns: Record<number, {
        sourcePx: number;
        sizePx: number;
    }>;
    rows: Record<number, {
        sourcePx: number;
        sizePx: number;
    }>;
}
interface XlsxSheetData {
    officeLayout?: XlsxOfficeLayout;
    cellStyleIds?: Record<string, number>;
    autoFilterRanges: XlsxCellRange[];
    cachedFormulaValues: Record<string, string>;
    colWidthOverridesPx: Record<number, number>;
    colStyleIds: Record<number, number>;
    hiddenCols?: number[];
    hiddenRows?: number[];
    conditionalFormatRules: XlsxConditionalFormatRule[];
    dataValidations: XlsxDataValidation[];
    name: string;
    visibility: XlsxSheetVisibility;
    columnWidthCharacterWidthPx?: number;
    defaultColWidthPx: number;
    defaultRowHeightPx: number;
    freezePanes: XlsxFreezePanes | null;
    hasHorizontalMerges: boolean;
    hasVerticalMerges: boolean;
    maxHorizontalMergeEndCol: number;
    maxVerticalMergeEndRow: number;
    mergedRanges?: XlsxCellRange[];
    minUsedCol: number;
    minUsedRow: number;
    maxUsedCol: number;
    maxUsedRow: number;
    rowCount: number;
    colCount: number;
    rowHeightOverridesPx: Record<number, number>;
    rowStyleIds: Record<number, number>;
    namedCellStyleByName: Record<string, XlsxResolvedCellStyle>;
    styleById: Record<number, XlsxResolvedCellStyle>;
    tableStyleByName: Record<string, XlsxTableStyleDefinition>;
    visibleRows: number[];
    visibleCols: number[];
    colWidths: number[];
    rowHeights: number[];
    showGridLines: boolean;
    sparklines: XlsxSparkline[];
    themePalette: XlsxThemePalette;
    workbookSheetIndex: number;
    zoomScale?: number;
}
interface XlsxCellAddress {
    col: number;
    row: number;
}
interface XlsxCellRange {
    end: XlsxCellAddress;
    start: XlsxCellAddress;
}
type XlsxMergeMode = "cells" | "center" | "across";
interface XlsxParsedRange {
    kind: "cells" | "rows" | "columns";
    range: XlsxCellRange;
    sheetName: string | null;
}
interface XlsxHighlightRangeOptions {
    /** Navigates to the worksheet and reveals the first range. Defaults to true. */
    autoScroll?: boolean;
    /** Visible worksheet index for an unqualified reference. Defaults to the active worksheet. */
    sheetIndex?: number;
}
interface XlsxRangeHighlight extends XlsxParsedRange {
    /** Whether this entry is the navigation target for the current highlight update. */
    autoScroll: boolean;
    sheetName: string;
    workbookSheetIndex: number;
}
/**
 * Color value accepted by persisted workbook style mutation APIs.
 *
 * Use `rgb` with a six-character `hex` value such as `"2563EB"` for the
 * simplest browser-to-Excel mapping. `argb`, `theme`, and `indexed` are
 * available for callers that need to preserve Excel-native color references.
 */
interface XlsxCellStyleColorInput {
    /** Excel color representation to write. Defaults are handled by the workbook engine. */
    colorType?: "auto" | "rgb" | "argb" | "theme" | "indexed";
    /** Hex color string, for example `"2563EB"` for RGB or `"FF2563EB"` for ARGB. */
    hex?: string;
    /** Red channel, 0-255. */
    r?: number;
    /** Green channel, 0-255. */
    g?: number;
    /** Blue channel, 0-255. */
    b?: number;
    /** Alpha channel, 0-255, used by ARGB colors. */
    a?: number;
    /** Theme color index for Excel theme colors. */
    themeIndex?: number;
    /** Theme tint/shade adjustment. */
    tint?: number;
    /** Indexed color palette entry. */
    paletteIndex?: number;
}
/** Font styling to persist on a cell or range. */
interface XlsxCellFontStyleInput {
    /** Font face name, such as `"Aptos"` or `"Calibri"`. */
    name?: string;
    /** Font size in points. */
    size?: number;
    /** Whether the font is bold. */
    bold?: boolean;
    /** Whether the font is italic. */
    italic?: boolean;
    /** Underline style. */
    underline?: "none" | "single" | "double" | "singleAccounting" | "doubleAccounting";
    /** Whether the font is struck through. */
    strikethrough?: boolean;
    /** Font color. */
    color?: XlsxCellStyleColorInput;
    /** Baseline, superscript, or subscript positioning. */
    verticalAlign?: "baseline" | "superscript" | "subscript";
    /** Excel font family classification. */
    family?: number;
    /** Font charset identifier. */
    charset?: number;
    /** Excel font scheme value. */
    scheme?: string;
}
/** A color stop used by gradient fills. */
interface XlsxCellGradientStopInput {
    /** Stop position from 0 to 1. */
    position: number;
    /** Stop color. */
    color: XlsxCellStyleColorInput;
}
/** Fill styling to persist on a cell or range. */
interface XlsxCellFillStyleInput {
    /** Fill type. Use `"solid"` with `color` for typical Excel fill color. */
    fillType?: "none" | "solid" | "pattern" | "gradient";
    /** Primary fill color. */
    color?: XlsxCellStyleColorInput;
    /** Excel pattern name for pattern fills. */
    pattern?: string;
    /** Foreground color for pattern fills. */
    foreground?: XlsxCellStyleColorInput;
    /** Background color for pattern fills. */
    background?: XlsxCellStyleColorInput;
    /** Gradient type for gradient fills. */
    gradientType?: "linear" | "path";
    /** Gradient angle in degrees. */
    angle?: number;
    /** Gradient color stops. */
    stops?: XlsxCellGradientStopInput[];
}
/** A single border edge style. */
interface XlsxCellBorderEdgeInput {
    /** Excel border line style. */
    style?: "none" | "thin" | "medium" | "thick" | "dashed" | "dotted" | "double" | "hair" | "mediumDashed" | "dashDot" | "mediumDashDot" | "dashDotDot" | "mediumDashDotDot" | "slantDashDot";
    /** Border line color. */
    color?: XlsxCellStyleColorInput;
}
/** Border styling to persist on a cell or range. */
interface XlsxCellBorderStyleInput {
    /** Left border edge. */
    left?: XlsxCellBorderEdgeInput;
    /** Right border edge. */
    right?: XlsxCellBorderEdgeInput;
    /** Top border edge. */
    top?: XlsxCellBorderEdgeInput;
    /** Bottom border edge. */
    bottom?: XlsxCellBorderEdgeInput;
    /** Diagonal border edge. */
    diagonal?: XlsxCellBorderEdgeInput;
    /** Diagonal border direction. */
    diagonalDirection?: "none" | "down" | "up" | "both";
}
/** Alignment styling to persist on a cell or range. */
interface XlsxCellAlignmentInput {
    /** Horizontal alignment. */
    horizontal?: "general" | "left" | "center" | "right" | "fill" | "justify" | "centerContinuous" | "distributed";
    /** Vertical alignment. */
    vertical?: "top" | "center" | "bottom" | "justify" | "distributed";
    /** Whether text wraps inside the cell. */
    wrapText?: boolean;
    /** Whether text shrinks to fit the cell. */
    shrinkToFit?: boolean;
    /** Indentation level. */
    indent?: number;
    /** Text rotation in degrees. */
    rotation?: number;
    /** Text reading order. */
    readingOrder?: "contextDependent" | "leftToRight" | "rightToLeft";
}
/** Number format styling to persist on a cell or range. */
interface XlsxCellNumberFormatInput {
    /** Number format source. Use `"custom"` with `formatString` for custom Excel formats. */
    formatType?: "general" | "builtin" | "custom";
    /** Built-in Excel number format id. */
    id?: number;
    /** Excel number format string, for example `"$#,##0.00"` or `"m/d/yyyy"`. */
    formatString?: string;
}
/** Protection flags to persist on a cell or range. */
interface XlsxCellProtectionInput {
    /** Whether the cell is locked when sheet protection is enabled. */
    locked?: boolean;
    /** Whether the cell formula is hidden when sheet protection is enabled. */
    hidden?: boolean;
}
/**
 * Persisted Excel cell style patch.
 *
 * Passing a partial style updates the supplied style groups on the target cell
 * or range. Unlike the `getCellStyle` render override prop, this mutates the
 * workbook and is included in exported XLSX bytes.
 */
interface XlsxCellStyleInput {
    /** Font formatting such as bold, italic, size, family, and font color. */
    font?: XlsxCellFontStyleInput;
    /** Cell fill formatting such as background color or gradient fill. */
    fill?: XlsxCellFillStyleInput;
    /** Border formatting for cell edges. */
    border?: XlsxCellBorderStyleInput;
    /** Alignment, wrapping, indentation, rotation, and reading order. */
    alignment?: XlsxCellAlignmentInput;
    /** Excel number/date/currency/percent format metadata. */
    numberFormat?: XlsxCellNumberFormatInput;
    /** Cell protection flags. */
    protection?: XlsxCellProtectionInput;
}
interface XlsxSparkline {
    color?: string;
    firstColor?: string;
    highColor?: string;
    lastColor?: string;
    lowColor?: string;
    markerColor?: string;
    markers?: boolean;
    negative?: boolean;
    negativeColor?: string;
    range: XlsxCellRange;
    sheetName?: string;
    target: XlsxCellAddress;
    type: "column" | "line" | "winLoss";
}
interface XlsxClipboardData {
    html: string;
    structured: string;
    text: string;
}
interface XlsxTableColumn {
    id: number;
    index: number;
    name: string;
}
interface XlsxTableStyleInfo {
    name?: string;
    showColumnStripes?: boolean;
    showFirstColumn?: boolean;
    showLastColumn?: boolean;
    showRowStripes?: boolean;
}
interface XlsxTable {
    columns: XlsxTableColumn[];
    displayName: string;
    end: XlsxCellAddress;
    headerRowCount: number;
    headerRowCellStyle?: string;
    name: string;
    reference: string;
    start: XlsxCellAddress;
    styleInfo?: XlsxTableStyleInfo;
    totalsRowCount: number;
    totalsRowShown: boolean;
}
type XlsxTableSortDirection = "ascending" | "descending";
interface XlsxTableSortState {
    columnIndex: number;
    direction: XlsxTableSortDirection;
    tableName: string;
}
interface XlsxImageMarker {
    col: number;
    colOffsetEmu: number;
    row: number;
    rowOffsetEmu: number;
}
type XlsxImageAnchor = {
    from: XlsxImageMarker;
    kind: "one-cell";
    sizeEmu: {
        cx: number;
        cy: number;
    };
} | {
    kind: "absolute";
    positionEmu: {
        x: number;
        y: number;
    };
    sizeEmu: {
        cx: number;
        cy: number;
    };
} | {
    from: XlsxImageMarker;
    kind: "two-cell";
    to: XlsxImageMarker;
};
interface XlsxImage {
    anchor: XlsxImageAnchor;
    description?: string;
    editable?: boolean;
    hyperlink?: string;
    id: string;
    mediaPath?: string;
    mimeType: string;
    name?: string;
    pictureRenderStatus?: "rendered" | "unchanged" | "unsupported";
    paintBounds?: {
        xPx: number;
        yPx: number;
        widthPx: number;
        heightPx: number;
        layoutWidthPx: number;
        layoutHeightPx: number;
    };
    sheetIndex: number;
    src: string;
    workbookSheetIndex: number;
    zIndex: number;
}
interface XlsxShapeFill {
    color?: string;
    none?: boolean;
    opacity?: number;
}
interface XlsxShapeStroke {
    color?: string;
    dash?: string;
    headEndType?: string;
    none?: boolean;
    opacity?: number;
    tailEndType?: string;
    widthPx?: number;
}
interface XlsxShapeTextRun {
    bold?: boolean;
    color?: string;
    fontFamily?: string;
    fontSizePt?: number;
    italic?: boolean;
    text: string;
    underline?: boolean;
}
interface XlsxShapeParagraph {
    align?: "center" | "justify" | "left" | "right";
    runs: XlsxShapeTextRun[];
}
interface XlsxShapeTextBox {
    horizontalAlign?: "center" | "left";
    insetPx?: {
        bottom: number;
        left: number;
        right: number;
        top: number;
    };
    verticalAlign?: "bottom" | "middle" | "top";
}
interface XlsxShape {
    anchor: XlsxImageAnchor;
    description?: string;
    fill?: XlsxShapeFill;
    flipH?: boolean;
    flipV?: boolean;
    geometry: string;
    geometryAdjustments?: Record<string, number>;
    hidden?: boolean;
    hyperlink?: string;
    id: string;
    name?: string;
    paragraphs: XlsxShapeParagraph[];
    rotationDeg?: number;
    scaleX?: number;
    scaleY?: number;
    sheetIndex: number;
    svgPath?: string;
    svgViewBox?: {
        height: number;
        width: number;
    };
    stroke?: XlsxShapeStroke;
    textBox?: XlsxShapeTextBox;
    workbookSheetIndex: number;
    zIndex: number;
}
type XlsxFormControlKind = "button" | "checkbox" | "dropdown" | "editbox" | "group-box" | "label" | "listbox" | "radio" | "scrollbar" | "spinner" | "unknown";
type XlsxFormControlState = "unchecked" | "checked" | "mixed";
type XlsxFormControlSelectionMode = "single" | "multi" | "extend";
interface XlsxFormControlCaptionRun {
    font?: XlsxCellFontStyleInput;
    text: string;
}
interface XlsxFormControlCaption {
    horizontalAlignment?: "general" | "left" | "center" | "right" | "fill" | "justify" | "centerContinuous" | "distributed";
    runs: XlsxFormControlCaptionRun[];
    verticalAlignment?: "top" | "center" | "bottom" | "justify" | "distributed";
}
type XlsxFormControlCaptionInput = string | XlsxFormControlCaption;
type XlsxFormControlKindInput = {
    kind: "button";
    caption: XlsxFormControlCaptionInput;
} | {
    kind: "checkbox";
    caption: XlsxFormControlCaptionInput;
    state: XlsxFormControlState;
    cellLink?: string;
    no3D?: boolean;
} | {
    kind: "optionButton";
    caption: XlsxFormControlCaptionInput;
    state: Exclude<XlsxFormControlState, "mixed">;
    cellLink?: string;
    no3D?: boolean;
} | {
    kind: "label";
    caption: XlsxFormControlCaptionInput;
} | {
    kind: "groupBox";
    caption: XlsxFormControlCaptionInput;
    no3D?: boolean;
} | {
    kind: "listBox";
    inputRange?: string;
    cellLink?: string;
    selection: XlsxFormControlSelectionMode;
    selected?: number[];
    no3D?: boolean;
} | {
    kind: "dropdown";
    inputRange?: string;
    cellLink?: string;
    selected?: number;
    lines: number;
    no3D?: boolean;
} | {
    kind: "editbox";
    caption: XlsxFormControlCaptionInput;
    legacyObjectType?: number;
    rawObj?: Uint8Array | number[];
    rawProperties?: Array<[string, string]>;
} | {
    kind: "scrollbar";
    value: number;
    min: number;
    max: number;
    increment: number;
    page: number;
    horizontal?: boolean;
    cellLink?: string;
} | {
    kind: "spinner";
    value: number;
    min: number;
    max: number;
    increment: number;
    cellLink?: string;
} | {
    kind: "unknown";
    objectType: string;
    legacyObjectType?: number;
    caption?: XlsxFormControlCaptionInput;
    rawObj?: Uint8Array | number[];
    rawProperties?: Array<[string, string]>;
};
interface XlsxFormControlMetadataInput {
    altText?: string;
    hidden?: boolean;
    kind: XlsxFormControlKindInput;
    locked?: boolean;
    macroName?: string;
    name?: string;
    printable?: boolean;
    rawClientData?: Array<Uint8Array | number[]>;
    title?: string;
}
type XlsxFormControlInput = XlsxFormControlMetadataInput & ({
    anchor: Extract<XlsxImageAnchor, {
        kind: "two-cell";
    }>;
    editAs?: "twoCell" | "oneCell" | "absolute";
} | {
    anchor: Exclude<XlsxImageAnchor, {
        kind: "two-cell";
    }>;
    editAs?: never;
});
type XlsxFormControlPatch = Partial<Omit<XlsxFormControlMetadataInput, "kind">> & {
    anchor?: XlsxImageAnchor;
    editAs?: "twoCell" | "oneCell" | "absolute";
    kind?: XlsxFormControlKindInput;
};
interface XlsxFormControl {
    anchor: XlsxImageAnchor;
    altText?: string;
    /** Original rich caption reported by Duke Sheets. */
    caption?: XlsxFormControlCaption;
    checked?: boolean;
    /** Duke Sheets' stable zero-based index for this worksheet load. */
    controlIndex?: number;
    /** Original two-cell anchor behavior. */
    editAs?: "twoCell" | "oneCell" | "absolute";
    firstInGroup?: boolean;
    fontFamily?: string;
    fontSizePt?: number;
    hidden?: boolean;
    horizontal?: boolean;
    id: string;
    increment?: number;
    inputRange?: string;
    /** Current formatted labels resolved from a dropdown or list box input range. */
    items?: string[];
    kind: XlsxFormControlKind;
    label?: string;
    lines?: number;
    linkedCell?: string;
    locked?: boolean;
    macroName?: string;
    max?: number;
    min?: number;
    name?: string;
    no3D?: boolean;
    page?: number;
    printable?: boolean;
    objectType?: string;
    legacyObjectType?: number;
    rawClientData?: number[][];
    rawObj?: number[];
    rawProperties?: Array<[string, string]>;
    /** Zero-based selected item index or indexes, matching Duke Sheets. */
    selected?: number | number[];
    selection?: XlsxFormControlSelectionMode;
    sheetIndex: number;
    state?: XlsxFormControlState;
    textAlign?: "center" | "left" | "right";
    textColor?: string;
    title?: string;
    value?: number;
    workbookSheetIndex: number;
    zIndex: number;
}
interface XlsxFormControlActionEvent {
    control: XlsxFormControl;
    type: "activate";
}
interface XlsxFormControlChangeEvent {
    control: XlsxFormControl;
    previousControl: XlsxFormControl;
    type: "change";
}
interface XlsxFormControlRenderProps {
    /** Activates a button control. No-ops in read-only mode. */
    activate: () => void;
    /** Current checked state for checkbox and radio controls. */
    checked: boolean;
    /** Full parsed control metadata. Switch on `control.kind` to render a kind-specific component. */
    control: XlsxFormControl;
    /** True when this control cannot be changed through the viewer. */
    disabled: boolean;
    /** Current formatted dropdown or list box items resolved from the control input range. */
    items: string[];
    /** Display label after placeholder Excel names have been removed. */
    label: string;
    /** True when a checkbox is in Excel's indeterminate state. */
    mixed: boolean;
    /** True when the viewer is rendering without workbook mutation support. */
    readOnly: boolean;
    /** Calculated worksheet-relative control rectangle in CSS pixels. */
    rect: XlsxImageRect;
    /** Persists a dropdown or list box selection. No-ops for other control kinds or in read-only mode. */
    setSelected: (selected: number | number[] | undefined) => boolean;
    /** Persists a checkbox or radio state. No-ops for other control kinds or in read-only mode. */
    setState: (state: XlsxFormControlState) => boolean;
    /** Persists a scrollbar or spinner value. No-ops for other control kinds or in read-only mode. */
    setValue: (value: number) => boolean;
    /** Stops an event from leaking into worksheet selection. */
    stopPropagation: (event: React.SyntheticEvent) => void;
    /** Apply this style to the custom control root to preserve worksheet positioning and sizing. */
    style: React.CSSProperties;
    /** Current worksheet zoom multiplier, where `1` is 100%. */
    zoomFactor: number;
}
interface XlsxChartReference {
    formula?: string;
    refType?: string;
    values?: Array<number | string | null>;
}
interface XlsxChartDataLabels {
    pointLabels?: XlsxChartPointDataLabel[];
    raw?: Record<string, unknown>;
    showBubbleSize?: boolean;
    showCategoryName?: boolean;
    showLegendKey?: boolean;
    showPercent?: boolean;
    showSeriesName?: boolean;
    showValue?: boolean;
}
interface XlsxChartPointDataLabel {
    deleted?: boolean;
    fontSizePt?: number;
    index: number;
    showBubbleSize?: boolean;
    showCategoryName?: boolean;
    showPercent?: boolean;
    showSeriesName?: boolean;
    showValue?: boolean;
    x?: number;
    y?: number;
}
interface XlsxChartLegend {
    overlay?: boolean;
    position?: string;
    raw?: Record<string, unknown>;
}
interface XlsxChartAxis {
    crossId?: number;
    crosses?: string;
    crossBetween?: string;
    delete?: boolean;
    id?: number;
    labelPosition?: string;
    logBase?: number;
    orientation?: string;
    majorUnit?: number;
    max?: number;
    min?: number;
    majorGridlines?: boolean;
    majorGridlineColor?: string;
    majorTickMark?: string;
    minorUnit?: number;
    minorGridlines?: boolean;
    minorTickMark?: string;
    numberFormat?: {
        formatCode?: string;
        sourceLinked?: boolean;
    };
    position?: string;
    raw?: Record<string, unknown>;
    shapeProperties?: Record<string, unknown>;
    tickLabelSkip?: number;
    tickMarkSkip?: number;
}
interface XlsxChartPointStyle {
    color?: string;
    explosion?: number;
    index: number;
    lineColor?: string;
}
interface XlsxChartSeries {
    bubbleSizeRef?: XlsxChartReference | null;
    bubbleSizes?: Array<number | null>;
    categories: Array<number | string | null>;
    categoriesRef?: XlsxChartReference | null;
    color?: string;
    dataPoints: unknown[];
    dataPointStyles?: XlsxChartPointStyle[];
    formatIdx?: number;
    hidden?: boolean;
    id: string;
    invertIfNegative?: boolean;
    lineColor?: string;
    lineWidthPx?: number;
    marker?: Record<string, unknown>;
    markerColor?: string;
    markerLineColor?: string;
    markerSize?: number;
    markerSymbol?: string;
    name?: string;
    negativeColor?: string;
    negativeLineColor?: string;
    raw?: Record<string, unknown>;
    shapeProperties?: Record<string, unknown>;
    smooth?: boolean;
    values: Array<number | null>;
    valuesRef?: XlsxChartReference | null;
}
type XlsxChartElementSelection = {
    kind: "chart";
    chartId: string;
} | {
    kind: "legend";
    chartId: string;
} | {
    kind: "series";
    chartId: string;
    seriesId: string;
    seriesIndex: number;
} | {
    kind: "point";
    chartId: string;
    seriesId: string;
    seriesIndex: number;
    pointIndex: number;
} | {
    kind: "legendEntry";
    chartId: string;
    seriesId: string;
    seriesIndex: number;
    legendIndex?: number;
};
type XlsxFormulaTarget = {
    kind: "cell";
    cell: XlsxCellAddress | null;
} | {
    kind: "chartSeries";
    chartId: string;
    seriesId: string;
    seriesIndex: number;
} | null;
interface XlsxChartTypeGroup {
    axisIds?: number[];
    chartType: string;
    dataLabels?: XlsxChartDataLabels | null;
    gapWidth?: number;
    is3d?: boolean;
    overlap?: number;
    raw?: Record<string, unknown>;
    series: XlsxChartSeries[];
    varyColors?: boolean;
}
interface XlsxChartWall {
    fillColor?: string;
    hidden?: boolean;
    lineColor?: string;
    thickness?: number;
}
interface XlsxChartRenderSource {
    kind: string;
    images?: Record<string, string>;
    drawings?: Record<string, {
        xml: string;
        images?: Record<string, string>;
    }>;
    seriesTypes?: string[];
    indexedXSeries?: boolean[];
    dateCategorySeries?: boolean[];
    sourceSeries?: XlsxChartSeries[];
    experimental?: boolean;
    xml: string;
    themeColors?: Record<string, string>;
    themeXml?: string;
    themeOverrideXml?: string;
    styleXml?: string;
    colorStyleXml?: string;
}
interface XlsxChart {
    /** Original chart appearance used with the current workbook values during rendering. */
    renderSource?: XlsxChartRenderSource;
    anchor: XlsxImageAnchor;
    autoTitleDeleted?: boolean;
    axes: XlsxChartAxis[];
    axisLabelColor?: string;
    axisLineColor?: string;
    categoryAxis?: XlsxChartAxis | null;
    chartExLayout?: string;
    chartAreaBorderColor?: string;
    chartAreaFillColor?: string;
    chartColorPalette?: string[];
    chartColorPaletteOffset?: number;
    chartPath?: string;
    chartStyleId?: number;
    chartType: string;
    dataLabels?: XlsxChartDataLabels | null;
    displayBlanksAs?: string;
    editable?: boolean;
    firstSliceAngle?: number;
    fontFamily?: string;
    gapWidth?: number;
    holeSize?: number;
    id: string;
    is3d?: boolean;
    legend?: XlsxChartLegend | null;
    name?: string;
    overlap?: number;
    plotVisibleOnly?: boolean;
    raw?: Record<string, unknown>;
    radarStyle?: string;
    scatterStyle?: string;
    roundedCorners?: boolean;
    shape3d?: string;
    seriesAxis?: XlsxChartAxis | null;
    series: XlsxChartSeries[];
    sheetIndex: number;
    showDlblsOverMax?: boolean;
    sideWall?: XlsxChartWall | null;
    backWall?: XlsxChartWall | null;
    bubbleScale?: number;
    bubble3d?: boolean;
    floor?: XlsxChartWall | null;
    surfaceMaterial?: string;
    textColor?: string;
    title?: string;
    titleColor?: string;
    titleFontFamily?: string;
    typeGroups?: XlsxChartTypeGroup[];
    valueAxis?: XlsxChartAxis | null;
    varyColors?: boolean;
    view3d?: {
        depthPercent?: number;
        heightPercent?: number;
        perspective?: number;
        rAngAx?: boolean;
        rotX?: number;
        rotY?: number;
    };
    wireframe?: boolean;
    workbookSheetIndex: number;
    zIndex: number;
}
interface XlsxChartsheet {
    chartIds: string[];
    chartPath?: string;
    id: string;
    index: number;
    name: string;
    raw?: Record<string, unknown>;
    workbookSheetIndex?: number;
}
interface XlsxWorkbookTab {
    chartsheetIndex?: number;
    id: string;
    index: number;
    kind: "chartsheet" | "sheet";
    name: string;
    sheetIndex?: number;
    visibility?: XlsxSheetVisibility;
    workbookSheetIndex?: number;
}
interface XlsxImageRect {
    height: number;
    left: number;
    top: number;
    width: number;
}
/** Rendered column widths and row heights in logical pixels, indexed by worksheet coordinates. */
interface XlsxDrawingLayout {
    columnWidths: readonly number[];
    rowHeights: readonly number[];
}
type XlsxImageResizeHandlePosition = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";
interface XlsxImageRenderProps {
    /** The built-in image element that react-xlsx would render without customization. */
    defaultNode: React.ReactNode;
    /** Workbook image metadata, including source, anchor, name, alt text, and editability. */
    image: XlsxImage;
    /** The image rectangle in viewer pixels, including the current zoom level. */
    rect: XlsxImageRect;
    /** Absolute positioning styles to apply when rendering a replacement image node. */
    style: React.CSSProperties;
}
interface XlsxImageSelectionRenderProps {
    /** The built-in selected-image outline and resize handles. */
    defaultNode: React.ReactNode;
    /** Returns pointer handlers and styles for a custom resize handle. */
    getHandleProps: (position: XlsxImageResizeHandlePosition) => {
        onPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
        style: React.CSSProperties;
    };
    /** The currently selected image. */
    image: XlsxImage;
    /** The selected image rectangle in viewer pixels, including the current zoom level. */
    rect: XlsxImageRect;
}
interface XlsxChartLoadingRenderProps {
    /** The chart that is waiting for its renderer or data. */
    chart: XlsxChart;
    /** The built-in chart loading placeholder. */
    defaultNode: React.ReactNode;
    /** The chart rectangle in viewer pixels, including the current zoom level. */
    rect: XlsxImageRect;
    /** Identifies whether chart metadata, rendering code, or map geometry is loading. */
    stage?: "metadata" | "renderer" | "map";
}
interface XlsxFileTooLargeRenderProps {
    /** The built-in file-too-large message. */
    defaultNode: React.ReactNode;
    /** File name displayed in the viewer UI. */
    displayFileName: string;
    /** Actual file size in bytes. */
    fileSizeBytes: number;
    /** Configured maximum file size in bytes. */
    maxFileSizeBytes: number;
}
interface XlsxScrollerRenderProps {
    /** Workbook grid content that should be rendered inside the scrollable viewport. */
    children: React.ReactNode;
    /** Props that must be applied to the actual scrollable viewport element. */
    viewportProps: React.HTMLAttributes<HTMLDivElement> & {
        ref: React.Ref<HTMLDivElement>;
        style: React.CSSProperties;
        tabIndex: number;
    };
}
interface UseXlsxViewerControllerOptions {
    /** BCP 47 locale for number formatting and built-in UI text. Defaults to en-US. */
    locale?: string;
    /** Partial overrides for localized UI text, including accessibility labels. */
    messages?: Partial<XlsxViewerMessages>;
    /**
     * Allows row and column resizing even while editing is disabled by `readOnly`.
     *
     * @default false
     */
    allowResizeInReadOnly?: boolean;
    /** Allow session-only freeze and unfreeze in read-only mode. Defaults to false. */
    allowFreezeInReadOnly?: boolean;
    /** Allow session-only hiding and unhiding of rows and columns in read-only mode. Defaults to false. */
    allowHideInReadOnly?: boolean;
    /**
     * Defers loading until `continueDeferredLoad()` is called when the file is larger than this byte threshold.
     * Set to `0` to parse immediately.
     *
     * @default 0
     * @example
     * ```tsx
     * useXlsxViewerController({ file, deferLoadingAboveBytes: 10 * 1024 * 1024 })
     * ```
     */
    deferLoadingAboveBytes?: number;
    /**
     * Local workbook bytes to load. Use either `file` or `src`.
     *
     * @example
     * ```tsx
     * <XlsxViewer file={await uploadedFile.arrayBuffer()} fileName={uploadedFile.name} />
     * ```
     */
    file?: ArrayBuffer;
    /**
     * Optional display and download name for the workbook.
     *
     * @example
     * ```tsx
     * <XlsxViewer file={buffer} fileName="forecast.xlsx" />
     * ```
     */
    fileName?: string;
    /**
     * Rejects files larger than this byte limit and renders `fileTooLargeState`.
     *
     * @default 25 * 1024 * 1024
     */
    maxFileSizeBytes?: number;
    /**
     * Disables workbook edits, paste, fill, undo/redo, and other mutation actions.
     *
     * @default false
     */
    readOnly?: boolean;
    /**
     * Automatically enables read-only mode for files larger than this byte threshold.
     * Set to `0` to disable the automatic switch.
     *
     * @default 0
     */
    readOnlyAboveBytes?: number;
    /**
     * Includes hidden and very hidden workbook sheets in the sheet tabs and controller state.
     *
     * @default false
     */
    showHiddenSheets?: boolean;
    /**
     * Skips supplemental viewer metadata and uses the bundled native workbook metadata.
     * This is automatically used for legacy `.xls` files.
     *
     * @default false
     */
    skipXmlParsing?: boolean;
    /**
     * Remote workbook URL to fetch and load. Use either `src` or `file`.
     *
     * @example
     * ```tsx
     * <XlsxViewer src="/workbooks/report.xlsx" />
     * ```
     */
    src?: string;
    /**
     * Uses a worker for parsing, chart rendering, export, and read-only queries when available.
     * Falls back to the main thread if the worker cannot run. Set false to disable workers entirely.
     *
     * @default true
     */
    useWorker?: boolean;
}
interface XlsxViewerLayout {
    /** Frozen row and column counts on the active worksheet, or null when unfrozen. */
    frozenPanes: XlsxFreezePanes | null;
    /** Whether freeze and unfreeze are available on the active worksheet. */
    canChangeFreezePanes?: boolean;
    /** Whether rows and columns can be hidden or revealed on the active worksheet. */
    canChangeVisibility?: boolean;
    /** Whether the current selection can be used as a freeze boundary. */
    canFreezePanes: boolean;
    /** Hide selected rows, or an inclusive, zero-based row interval. */
    hideRows: (start?: number, end?: number) => void;
    /** Reveal hidden rows in the selection or an inclusive, zero-based row interval. */
    unhideRows: (start?: number, end?: number) => void;
    /** Hide selected columns, or an inclusive, zero-based column interval. */
    hideColumns: (start?: number, end?: number) => void;
    /** Reveal hidden columns in the selection or an inclusive, zero-based column interval. */
    unhideColumns: (start?: number, end?: number) => void;
    /** Freeze rows above and columns left of the given cell, defaulting to the selected header or active cell. */
    freezePanes: (cell?: XlsxCellAddress) => void;
    /** Remove the freeze boundary on the active worksheet. */
    unfreezePanes: () => void;
}
interface XlsxViewerController extends XlsxViewerPivots, XlsxViewerLayout {
    activeCell: XlsxCellAddress | null;
    activeCellAddress: string | null;
    activeSheet: XlsxSheetData | null;
    activeSheetIndex: number;
    activeTab: XlsxWorkbookTab | null;
    activeTabIndex: number;
    canDownload: boolean;
    canExport: boolean;
    canLoadDeferred: boolean;
    canRedo: boolean;
    canUndo: boolean;
    canZoomIn: boolean;
    canZoomOut: boolean;
    /** Adds a Duke-supported form control to a visible worksheet and returns its worksheet-local index. */
    addFormControl: (input: XlsxFormControlInput, sheetIndex?: number) => number | null;
    clearSelectedCells: () => void;
    clearSelection: () => void;
    /** Removes all render-only range highlights. */
    clearHighlightedRanges: () => void;
    /** Replaces the highlights with validated A1 ranges. Returns false without changing state if any reference cannot be resolved. */
    highlightRanges: (references: string | readonly string[], options?: XlsxHighlightRangeOptions) => boolean;
    highlightedRanges: XlsxRangeHighlight[];
    continueDeferredLoad: () => void;
    copySelectionToClipboard: () => Promise<boolean>;
    defaultZoomScale: number;
    deferredLoadFileSize: number | null;
    defineNamedRange: (name: string, range?: XlsxCellRange | null) => void;
    displayFileName: string;
    locale: string;
    /** Resolved UI text after applying locale defaults and message overrides. */
    messages: XlsxViewerMessages;
    download: () => Promise<void>;
    charts: XlsxChart[];
    chartsheets: XlsxChartsheet[];
    exportCsv: () => void;
    exportXlsx: () => Promise<void>;
    /** Resolves to the current workbook as XLSX bytes, or null before an editable model loads. */
    renderChartAsync?: RenderChartAsync;
    getXlsxBytes: () => Promise<Uint8Array | null>;
    error: Error | null;
    file?: ArrayBuffer;
    fillSelection: (targetRange: XlsxCellRange) => void;
    clearSelectedChart: () => void;
    clearSelectedChartElement: () => void;
    clearSelectedImage: () => void;
    getChartById: (id: string) => XlsxChart | null;
    getChartSeriesFormula: (chartId: string, seriesIndex: number) => string;
    getChartsheetById: (id: string) => XlsxChartsheet | null;
    formControls: XlsxFormControl[];
    getSheetCharts: (sheetIndex?: number) => XlsxChart[];
    getSheetFormControls: (sheetIndex?: number) => XlsxFormControl[];
    /** Resolves a list/dropdown input range to its current formatted item labels. */
    getFormControlItems: (controlIndex: number, sheetIndex?: number) => string[];
    getImageById: (id: string) => XlsxImage | null;
    getSheetImages: (sheetIndex?: number) => XlsxImage[];
    getSheetShapes: (sheetIndex?: number) => XlsxShape[];
    getClipboardData: () => XlsxClipboardData | null;
    getCellDisplayValue: (cell?: XlsxCellAddress | null) => string;
    getCellFormula: (cell?: XlsxCellAddress | null) => string;
    getCellSnapshotAsync?: (workbookSheetIndex: number, row: number, col: number) => Promise<{
        displayValue: string;
        formula: string;
    }>;
    isLoadDeferred: boolean;
    isLoading: boolean;
    isChartsLoading: boolean;
    isWorkerBacked?: boolean;
    images: XlsxImage[];
    moveChartBy: (id: string, deltaX: number, deltaY: number) => void;
    shapes: XlsxShape[];
    /** Merges the selection; defaults to preserving its existing alignment. */
    mergeSelection: (mode?: XlsxMergeMode) => void;
    maxZoomScale: number;
    minZoomScale: number;
    moveImageBy: (id: string, deltaX: number, deltaY: number) => void;
    removeActiveSheet: () => void;
    /** Removes a Duke-supported control by its worksheet-local index. */
    removeFormControl: (controlIndex: number, sheetIndex?: number) => boolean;
    readOnly: boolean;
    recalculate: () => void;
    revision: number;
    resetZoom: () => void;
    resizeChartBy: (id: string, handle: XlsxImageResizeHandlePosition, deltaX: number, deltaY: number) => void;
    resizeImageBy: (id: string, handle: XlsxImageResizeHandlePosition, deltaX: number, deltaY: number) => void;
    resizeColumn: (col: number | readonly number[], widthPx: number) => void;
    resizeRow: (row: number | readonly number[], heightPx: number) => void;
    redo: () => void;
    /** Reads browser clipboard representations. Pass paste-event data to retain image and text fallbacks. */
    pasteFromClipboard: (clipboardData?: DataTransfer) => Promise<boolean>;
    pasteStructuredClipboardData: (payload: string) => boolean;
    pasteText: (text: string) => boolean;
    selectedRangeAddress: string | null;
    selectedValue: string;
    selectedFormula: string;
    /**
     * Sets the formula for a cell in the active worksheet.
     *
     * Pass an A1-style formula body or formula string, for example `"SUM(A1:A3)"`
     * or `"=SUM(A1:A3)"`. The mutation is recorded in undo history and is included
     * in exported workbook bytes.
     *
     * @param cell Zero-based row and column address in the active worksheet.
     * @param formula Formula text to write. Pass an empty string to clear the formula.
     */
    setCellFormula: (cell: XlsxCellAddress, formula: string) => void;
    /**
     * Applies persisted Excel style properties to a cell in the active worksheet.
     *
     * This mutates workbook data, records undo history, refreshes the viewer, and
     * is included in exported XLSX bytes. Use the `getCellStyle` viewer prop only
     * for render-time CSS overrides that should not modify the workbook.
     *
     * @param cell Zero-based row and column address in the active worksheet.
     * @param style Partial Excel style patch to apply to the target cell.
     */
    setCellStyle: (cell: XlsxCellAddress, style: XlsxCellStyleInput) => void;
    /** Applies individual cell styles as one undoable workbook edit. */
    setCellStyles: (updates: ReadonlyArray<{
        cell: XlsxCellAddress;
        style: XlsxCellStyleInput;
    }>) => void;
    /**
     * Sets the value for a cell in the active worksheet.
     *
     * User-entered strings are coerced to booleans or numbers when they match
     * Excel-like input. Prefix text with an apostrophe to force literal text.
     *
     * @param cell Zero-based row and column address in the active worksheet.
     * @param value Text entered by the user.
     */
    setCellValue: (cell: XlsxCellAddress, value: string) => void;
    /**
     * Applies persisted Excel style properties to every cell in a range.
     *
     * This mutates workbook data, records undo history, refreshes the viewer, and
     * is included in exported XLSX bytes.
     *
     * @param range Zero-based cell range in the active worksheet.
     * @param style Partial Excel style patch to apply to the target range.
     */
    setRangeStyle: (range: XlsxCellRange | readonly XlsxCellRange[], style: XlsxCellStyleInput) => void;
    setZoomScale: (zoomScale: number) => void;
    selectCell: (cell: XlsxCellAddress, options?: {
        extend?: boolean;
    }) => void;
    selectChart: (id: string | null) => void;
    selectChartElement: (selection: XlsxChartElementSelection | null) => void;
    selectRange: (range: XlsxCellRange) => void;
    selectRanges: (ranges: readonly XlsxCellRange[], activeCorner?: "start" | "end") => void;
    /** Selected areas in selection order. The last area is the active selection. */
    selectionRanges: readonly XlsxCellRange[];
    selection: XlsxCellRange | null;
    setActiveSheetIndex: (index: number) => void;
    setActiveTabIndex: (index: number) => void;
    selectedChart: XlsxChart | null;
    selectedChartElement: XlsxChartElementSelection | null;
    selectedChartFormula: string | null;
    selectedChartId: string | null;
    selectedCellFormula: string;
    selectedFormulaTarget: XlsxFormulaTarget;
    selectedImage: XlsxImage | null;
    selectedImageId: string | null;
    setSelectedFormula: (formula: string) => boolean;
    setSelectedCellFormula: (formula: string) => void;
    /**
     * Applies persisted Excel style properties to the active cell.
     *
     * No-ops when there is no active cell, when editing is disabled, or when no
     * workbook is loaded. The mutation is recorded in undo history and is included
     * in exported XLSX bytes.
     *
     * @param style Partial Excel style patch to apply to the active cell.
     */
    setSelectedCellStyle: (style: XlsxCellStyleInput) => void;
    setSelectedCellValue: (value: string) => void;
    sheets: XlsxSheetData[];
    src?: string;
    sortState: XlsxTableSortState | null;
    sortTable: (tableName: string, columnIndex: number, direction: XlsxTableSortDirection) => void;
    setChartSeriesFormula: (chartId: string, seriesIndex: number, formula: string) => boolean;
    selectImage: (id: string | null) => void;
    setChartRect: (id: string, rect: XlsxImageRect, layout?: XlsxDrawingLayout) => void;
    setImageRect: (id: string, rect: XlsxImageRect, layout?: XlsxDrawingLayout) => void;
    arrangeDrawing: (kind: "image" | "chart", id: string, order: XlsxDrawingOrder) => Promise<boolean>;
    /** Pastes a browser-readable Office drawing or image at the active cell. */
    pasteDrawingFromClipboard: (data?: string | Blob) => Promise<boolean>;
    changeChartType: (id: string, type: string) => Promise<boolean>;
    getRowsBatchAsync?: (workbookSheetIndex: number, startRow: number, rowCount: number) => Promise<unknown[] | null>;
    /** Reads the populated cells for a single worksheet axis. Used by worker-backed viewers. */
    getAutofitCellsAsync?: (workbookSheetIndex: number, axis: "column" | "row", index: number) => Promise<unknown[]>;
    /** Whether the controller permits grid resizing after applying read-only size limits. */
    canResize?: boolean;
    tables: XlsxTable[];
    tabs: XlsxWorkbookTab[];
    undo: () => void;
    unmergeSelection: () => void;
    updateChart: (id: string, patch: Partial<XlsxChart>) => void;
    /** Updates a Duke-supported control and participates in undo/redo and export. */
    updateFormControl: (controlIndex: number, patch: XlsxFormControlPatch, sheetIndex?: number) => boolean;
    workbook: Workbook | null;
    zoomIn: () => void;
    zoomOut: () => void;
    zoomScale: number;
    getActiveWorksheet: () => Worksheet | null;
    addSheet: (name?: string) => void;
}
interface XlsxViewerSelection {
    activeCell: XlsxCellAddress | null;
    activeCellAddress: string | null;
    clearSelection: () => void;
    selectedRangeAddress: string | null;
    selectCell: (cell: XlsxCellAddress, options?: {
        extend?: boolean;
    }) => void;
    selectRange: (range: XlsxCellRange) => void;
    selectRanges: (ranges: readonly XlsxCellRange[], activeCorner?: "start" | "end") => void;
    /** Selected areas in selection order. The last area is the active selection. */
    selectionRanges: readonly XlsxCellRange[];
    selection: XlsxCellRange | null;
}
interface XlsxViewerZoom {
    canZoomIn: boolean;
    canZoomOut: boolean;
    defaultZoomScale: number;
    maxZoomScale: number;
    minZoomScale: number;
    resetZoom: () => void;
    setZoomScale: (zoomScale: number) => void;
    zoomIn: () => void;
    zoomOut: () => void;
    zoomScale: number;
}
type XlsxContextMenuActionId = "bringToFront" | "bringForward" | "sendBackward" | "sendToBack" | "arrange" | "changeChartType" | `chartType:${string}` | `chartFamily:${string}` | "cut" | "copy" | "paste" | "clearContents" | "editCell" | "undo" | "redo" | "mergeCells" | "mergeAndCenter" | "mergeAcross" | "unmergeCells" | "sortAscending" | "sortDescending" | "refreshPivotTable" | "showPivotDetails" | "togglePivotFieldList" | "rowHeight" | "columnWidth" | "hideRows" | "unhideRows" | "hideColumns" | "unhideColumns" | "selectRow" | "selectColumn" | "selectAll";
interface XlsxContextMenuAction {
    id: XlsxContextMenuActionId;
    label: string;
    shortcut?: string;
    disabled?: boolean;
    destructive?: boolean;
    separatorBefore?: boolean;
    checked?: boolean;
    children?: XlsxContextMenuAction[];
}
type XlsxDrawingOrder = "bringToFront" | "bringForward" | "sendBackward" | "sendToBack";
interface XlsxContextMenuContext {
    kind: "cell" | "row" | "column" | "sheet" | "image" | "chart";
    image?: XlsxImage;
    chart?: XlsxChart;
    cell: XlsxCellAddress;
    selection: XlsxCellRange;
    selectionRanges?: readonly XlsxCellRange[];
    sheetIndex: number;
    sheetName: string;
    readOnly: boolean;
}
interface XlsxContextMenuRenderProps {
    context: XlsxContextMenuContext;
    actions: XlsxContextMenuAction[];
    /** Returns whether the command completed; failures remain visible in the menu. */
    runAction: (actionId: XlsxContextMenuActionId) => Promise<boolean>;
    closeMenu: () => void;
    /** Aborted when the menu closes or its selection expires. */
    signal: AbortSignal;
    /** Applies a synchronous custom mutation, then closes the menu. Rejects stale or read-only menus. */
    commit: (apply: (context: XlsxContextMenuContext) => void) => boolean;
    /** Viewport coordinates. The menu container handles positioning and edge clamping. */
    position: {
        x: number;
        y: number;
    };
    isDark: boolean;
    busy: boolean;
    error: string | null;
    defaultNode: React.ReactNode;
}
interface XlsxViewerEditing {
    addSheet: (name?: string) => void;
    addFormControl: (input: XlsxFormControlInput, sheetIndex?: number) => number | null;
    canRedo: boolean;
    canUndo: boolean;
    clearSelectedCells: () => void;
    copySelectionToClipboard: () => Promise<boolean>;
    defineNamedRange: (name: string, range?: XlsxCellRange | null) => void;
    fillSelection: (targetRange: XlsxCellRange) => void;
    formControls: XlsxFormControl[];
    getClipboardData: () => XlsxClipboardData | null;
    getCellDisplayValue: (cell?: XlsxCellAddress | null) => string;
    getCellFormula: (cell?: XlsxCellAddress | null) => string;
    getFormControlItems: (controlIndex: number, sheetIndex?: number) => string[];
    getSheetFormControls: (sheetIndex?: number) => XlsxFormControl[];
    mergeSelection: (mode?: XlsxMergeMode) => void;
    pasteFromClipboard: XlsxViewerController["pasteFromClipboard"];
    pasteStructuredClipboardData: (payload: string) => boolean;
    pasteText: (text: string) => boolean;
    removeActiveSheet: () => void;
    removeFormControl: (controlIndex: number, sheetIndex?: number) => boolean;
    readOnly: boolean;
    redo: () => void;
    selectedCellFormula: string;
    selectedChartFormula: string | null;
    selectedFormula: string;
    selectedFormulaTarget: XlsxFormulaTarget;
    selectedValue: string;
    /**
     * Sets the formula for a cell in the active worksheet.
     *
     * @param cell Zero-based row and column address in the active worksheet.
     * @param formula Formula text to write. Pass an empty string to clear the formula.
     */
    setCellFormula: (cell: XlsxCellAddress, formula: string) => void;
    /**
     * Applies persisted Excel style properties to a cell in the active worksheet.
     *
     * The mutation is recorded in undo history and is included in exported XLSX
     * bytes. This is different from the `getCellStyle` render override prop.
     *
     * @param cell Zero-based row and column address in the active worksheet.
     * @param style Partial Excel style patch to apply to the target cell.
     */
    setCellStyle: (cell: XlsxCellAddress, style: XlsxCellStyleInput) => void;
    /** Applies individual cell styles as one undoable workbook edit. */
    setCellStyles: (updates: ReadonlyArray<{
        cell: XlsxCellAddress;
        style: XlsxCellStyleInput;
    }>) => void;
    /**
     * Sets the value for a cell in the active worksheet.
     *
     * @param cell Zero-based row and column address in the active worksheet.
     * @param value Text entered by the user.
     */
    setCellValue: (cell: XlsxCellAddress, value: string) => void;
    /**
     * Applies persisted Excel style properties to every cell in a range.
     *
     * @param range Zero-based cell range in the active worksheet.
     * @param style Partial Excel style patch to apply to the target range.
     */
    setRangeStyle: (range: XlsxCellRange | readonly XlsxCellRange[], style: XlsxCellStyleInput) => void;
    setSelectedFormula: (formula: string) => boolean;
    setSelectedCellFormula: (formula: string) => void;
    /**
     * Applies persisted Excel style properties to the active cell.
     *
     * @param style Partial Excel style patch to apply to the active cell.
     */
    setSelectedCellStyle: (style: XlsxCellStyleInput) => void;
    setSelectedCellValue: (value: string) => void;
    undo: () => void;
    unmergeSelection: () => void;
    updateFormControl: (controlIndex: number, patch: XlsxFormControlPatch, sheetIndex?: number) => boolean;
}
interface XlsxViewerTables {
    sortState: XlsxTableSortState | null;
    sortTable: (tableName: string, columnIndex: number, direction: XlsxTableSortDirection) => void;
    tables: XlsxTable[];
}
interface XlsxViewerImages {
    arrangeDrawing: XlsxViewerController["arrangeDrawing"];
    changeChartType: XlsxViewerController["changeChartType"];
    pasteDrawingFromClipboard: XlsxViewerController["pasteDrawingFromClipboard"];
    charts: XlsxChart[];
    clearSelectedChart: () => void;
    clearSelectedChartElement: () => void;
    clearSelectedImage: () => void;
    getChartById: (id: string) => XlsxChart | null;
    getChartSeriesFormula: (chartId: string, seriesIndex: number) => string;
    getSheetCharts: (sheetIndex?: number) => XlsxChart[];
    getImageById: (id: string) => XlsxImage | null;
    getSheetImages: (sheetIndex?: number) => XlsxImage[];
    images: XlsxImage[];
    moveChartBy: (id: string, deltaX: number, deltaY: number) => void;
    moveImageBy: (id: string, deltaX: number, deltaY: number) => void;
    isChartsLoading: boolean;
    readOnly: boolean;
    resizeChartBy: (id: string, handle: XlsxImageResizeHandlePosition, deltaX: number, deltaY: number) => void;
    resizeImageBy: (id: string, handle: XlsxImageResizeHandlePosition, deltaX: number, deltaY: number) => void;
    selectedChart: XlsxChart | null;
    selectedChartElement: XlsxChartElementSelection | null;
    selectedChartFormula: string | null;
    selectedChartId: string | null;
    selectedImage: XlsxImage | null;
    selectedImageId: string | null;
    selectChart: (id: string | null) => void;
    selectChartElement: (selection: XlsxChartElementSelection | null) => void;
    selectImage: (id: string | null) => void;
    setChartSeriesFormula: (chartId: string, seriesIndex: number, formula: string) => boolean;
    setChartRect: (id: string, rect: XlsxImageRect, layout?: XlsxDrawingLayout) => void;
    setImageRect: (id: string, rect: XlsxImageRect, layout?: XlsxDrawingLayout) => void;
    updateChart: (id: string, patch: Partial<XlsxChart>) => void;
}
interface XlsxViewerCharts {
    activeTab: XlsxWorkbookTab | null;
    activeTabIndex: number;
    arrangeDrawing: XlsxViewerController["arrangeDrawing"];
    changeChartType: XlsxViewerController["changeChartType"];
    pasteDrawingFromClipboard: XlsxViewerController["pasteDrawingFromClipboard"];
    charts: XlsxChart[];
    chartsheets: XlsxChartsheet[];
    clearSelectedChart: () => void;
    clearSelectedChartElement: () => void;
    getChartById: (id: string) => XlsxChart | null;
    getChartSeriesFormula: (chartId: string, seriesIndex: number) => string;
    getChartsheetById: (id: string) => XlsxChartsheet | null;
    getSheetCharts: (sheetIndex?: number) => XlsxChart[];
    isChartsLoading: boolean;
    moveChartBy: (id: string, deltaX: number, deltaY: number) => void;
    readOnly: boolean;
    resizeChartBy: (id: string, handle: XlsxImageResizeHandlePosition, deltaX: number, deltaY: number) => void;
    selectChart: (id: string | null) => void;
    selectedChart: XlsxChart | null;
    selectedChartElement: XlsxChartElementSelection | null;
    selectedChartFormula: string | null;
    selectedChartId: string | null;
    selectChartElement: (selection: XlsxChartElementSelection | null) => void;
    setChartSeriesFormula: (chartId: string, seriesIndex: number, formula: string) => boolean;
    setActiveTabIndex: (index: number) => void;
    setChartRect: (id: string, rect: XlsxImageRect, layout?: XlsxDrawingLayout) => void;
    tabs: XlsxWorkbookTab[];
    updateChart: (id: string, patch: Partial<XlsxChart>) => void;
}
type XlsxSheetThumbnailResolution = number | {
    maxHeight?: number;
    maxWidth?: number;
};
interface UseXlsxViewerThumbnailsOptions {
    includeHeaders?: boolean;
    resolution?: XlsxSheetThumbnailResolution;
}
interface XlsxSheetThumbnail {
    aspectRatio: number;
    contentHeight: number;
    contentWidth: number;
    height: number;
    paint: (canvas: HTMLCanvasElement | null) => boolean;
    sheet: XlsxSheetData;
    sheetIndex: number;
    sourceRange: XlsxCellRange;
    width: number;
    workbookSheetIndex: number;
}
interface XlsxViewerThumbnails {
    paintThumbnail: (sheetIndex: number, canvas: HTMLCanvasElement | null) => boolean;
    thumbnails: XlsxSheetThumbnail[];
}
interface XlsxTableHeaderMenuRenderProps {
    kind?: "table" | "pivot";
    pivot?: XlsxPivotTableHeaderMenuRenderProps;
    defaultNode?: React.ReactNode;
    /** Address of the table header cell that owns this menu. */
    cell: XlsxCellAddress;
    /** Table column metadata for the active header. */
    column: XlsxTableColumn;
    /** Current sort direction for this column, or `null` when unsorted. */
    direction: XlsxTableSortDirection | null;
    /** Sorts the table by this column in ascending order. */
    sortAscending: () => void;
    /** Sorts the table by this column in descending order. */
    sortDescending: () => void;
    /** Table metadata for the active header. */
    table: XlsxTable;
    /** Built-in trigger text/icon. Useful when composing your own trigger button. */
    triggerIcon: string;
    /** Props that must be applied to your menu trigger button so grid selection does not receive the click. */
    triggerProps: React.ButtonHTMLAttributes<HTMLButtonElement>;
}
interface XlsxActiveCellOverlayRenderProps {
    /** Address of the active cell. For merged cells this is the merge anchor. */
    cell: XlsxCellAddress;
    /**
     * Pixel rect of the active cell (spanning the full merge) within the grid's scroll content,
     * at the current zoom. The rendered node is already positioned to fill this rect.
     */
    rect: XlsxImageRect;
}
interface XlsxCellEditorContext {
    cell: XlsxCellAddress;
    sheetIndex: number;
    sheetName: string;
    /** The saved cell input before editing started, including a leading equals sign for formulas. */
    originalValue: string;
    /** The interaction that opened this editing session. */
    trigger: "double-click" | "typing" | "keyboard" | "context-menu";
}
interface XlsxCellEditorSession {
    context: XlsxCellEditorContext;
    value: string;
    isPreview: boolean;
    /** Aborted when editing ends or the target changes. Pass to asynchronous requests. */
    signal: AbortSignal;
    /** Reads the latest draft, or null after this session ends. */
    getValue: () => string | null;
    /** Replaces the draft without writing to the workbook. Returns false after this session ends. */
    setValue: (value: string) => boolean;
    /** Replaces the draft for review. Leaving the editor cancels an unconfirmed preview. */
    preview: (value: string) => boolean;
    /** Restores the draft from before the preview and keeps editing. */
    discardPreview: () => boolean;
    /** Saves the supplied input, or the current draft, using the existing undo history. */
    commit: (value?: string) => boolean;
    /** Ends editing without saving. */
    cancel: () => boolean;
    /** Returns focus to the built-in input. */
    focus: () => boolean;
}
interface XlsxCellEditorOverlayRenderProps extends XlsxCellEditorSession {
    /** The live editor element, for anchoring and scoped visual effects. */
    editorElement: HTMLDivElement;
    /** The expanded editor rectangle in viewport pixels. The overlay container already fills it. */
    rect: XlsxImageRect;
}
interface XlsxSelectionPopoverContext {
    cell: XlsxCellAddress;
    selection: XlsxCellRange;
    sheetIndex: number;
    sheetName: string;
    readOnly: boolean;
}
interface XlsxSelectionPopoverRenderProps {
    context: XlsxSelectionPopoverContext;
    /** The visible selection rectangle in viewport pixels. The container already fills it. */
    rect: XlsxImageRect;
    /** Aborted when the selection changes, editing starts, or the popover closes. */
    signal: AbortSignal;
    /** Saves a formula in the active cell and closes. Returns false for stale or read-only selections. */
    applyFormula: (formula: string) => boolean;
    /** Runs a synchronous custom mutation for the current selection and closes. */
    commit: (apply: (context: XlsxSelectionPopoverContext) => void) => boolean;
    close: () => void;
}
interface XlsxCellStyleContext {
    /** Address of the cell being styled. */
    cell: XlsxCellAddress;
    /** True when the cell is part of a selected chart's highlighted source range. */
    hasChartHighlight: boolean;
    /** True when a conditional format (color scale, data bar, or icon set) applies to the cell. */
    hasConditionalFormat: boolean;
    /** True when the cell has a hyperlink. */
    hasHyperlink: boolean;
    /** True when the cell has a data validation rule. */
    hasValidation: boolean;
    /** True when the cell is the anchor of a merged range. */
    isMerged: boolean;
    /** True when the cell is a table header cell. */
    isTableHeader: boolean;
    /**
     * The fully resolved style the viewer computed for this cell, combining the workbook's
     * own formatting with the viewer's built-in styling. Treat this as read-only; returning
     * a partial style from `getCellStyle` merges on top of it.
     */
    resolvedStyle: React.CSSProperties;
    /** Display name of the sheet the cell belongs to. */
    sheetName: string;
    /** The cell's resolved display value. */
    value: string;
    /** Workbook sheet index of the cell's sheet. */
    workbookSheetIndex: number;
}
interface XlsxViewerProviderProps extends UseXlsxViewerControllerOptions {
    /** Viewer UI and hooks that should share this provider's workbook controller. */
    children: React.ReactNode;
    /**
     * Existing controller to provide instead of creating one from `file`, `src`, or other controller options.
     *
     * @example
     * ```tsx
     * const controller = useXlsxViewerController({ src: "/report.xlsx" });
     * return <XlsxViewerProvider controller={controller}><XlsxViewer /></XlsxViewerProvider>;
     * ```
     */
    controller?: XlsxViewerController;
    /**
     * Uses the built-in dark worksheet/viewer palette.
     *
     * @default false
     */
    isDark?: boolean;
}
interface XlsxViewerProps extends UseXlsxViewerControllerOptions {
    /** Render-only A1 ranges to highlight. Null or an empty array clears them; undefined leaves controller state alone. */
    highlightedRanges?: string | readonly string[] | null;
    /** Reveals the first newly highlighted range, including switching worksheets. Defaults to true. */
    autoScrollToHighlightedRanges?: boolean;
    /** Additional CSS class applied to the range highlight in both renderers. */
    highlightClassName?: string;
    /**
     * Allows row and column resizing even while editing is disabled by `readOnly`.
     *
     * @default false
     */
    allowResizeInReadOnly?: boolean;
    /** Class name applied to the root viewer shell. */
    className?: string;
    /**
     * Existing controller to render. Takes precedence over provider context and source props on this viewer.
     *
     * @example
     * ```tsx
     * const controller = useXlsxViewerController({ file, fileName: "model.xlsx" });
     * return <XlsxViewer controller={controller} />;
     * ```
     */
    controller?: XlsxViewerController;
    /** Content shown when no workbook has been loaded. */
    emptyState?: React.ReactNode;
    /**
     * Animates the selection rectangle in canvas mode.
     *
     * @default true
     */
    enableCanvasSelectionAnimation?: boolean;
    /**
     * Enables pinch zoom and modifier-key wheel zoom inside the viewer.
     *
     * @default true
     */
    enableGestureZoom?: boolean;
    /**
     * Renders worksheets with the canvas renderer. Set to `false` to use the DOM table renderer.
     *
     * @default true
     * @example
     * ```tsx
     * <XlsxViewer experimentalCanvas={false} />
     * ```
     */
    experimentalCanvas?: boolean;
    /** Content shown for non-size load errors, or a function that receives the thrown error. */
    errorState?: React.ReactNode | ((error: Error) => React.ReactNode);
    /** Content shown when `maxFileSizeBytes` rejects a file. */
    fileTooLargeState?: React.ReactNode | ((props: XlsxFileTooLargeRenderProps) => React.ReactNode);
    /**
     * Returns extra CSS style overrides for an individual cell. Called for every rendered cell
     * with the cell's address, sheet, resolved style, and contextual flags. Return `undefined`
     * (or `null`) to leave a cell untouched, or a partial style object that merges on top of the
     * viewer's resolved style. Use this as an escape hatch for custom per-cell styling such as
     * highlights, outlines, or status tints, without forking the workbook data.
     *
     * The DOM renderer applies every returned CSS property. The canvas renderer
     * (`experimentalCanvas`, the default) honors the subset it can paint: `backgroundColor`,
     * `backgroundImage` gradients, `color`, the four `border*` sides, `padding`, `textAlign`,
     * `textDecoration`, `textOverflow`, and font properties. CSS-only effects such as `boxShadow`,
     * `outline`, or `animation` apply in the DOM renderer (`experimentalCanvas={false}`).
     *
     * Keep this callback stable (e.g. wrap it in `useCallback`) so cell styling is not recomputed
     * on every render. When the callback identity changes, the viewer re-resolves and repaints
     * cell styles.
     *
     * @example
     * ```tsx
     * const getCellStyle = React.useCallback<NonNullable<XlsxViewerProps["getCellStyle"]>>(
     *   ({ cell }) => (cell.row === 3 && cell.col === 1 ? { backgroundColor: "#dbeafe" } : undefined),
     *   []
     * );
     * return <XlsxViewer file={buffer} getCellStyle={getCellStyle} />;
     * ```
     */
    getCellStyle?: (context: XlsxCellStyleContext) => React.CSSProperties | null | undefined;
    /** Background color used for row-number, column-letter, and corner headers. */
    headerBackgroundColor?: string;
    /** Text color used for row-number and column-letter headers. */
    headerTextColor?: string;
    /**
     * CSS height for the viewer container.
     *
     * @example
     * ```tsx
     * <XlsxViewer height="70vh" />
     * ```
     */
    height?: React.CSSProperties["height"];
    /**
     * Uses the built-in dark worksheet/viewer palette.
     *
     * @default false
     */
    isDark?: boolean;
    /** Legacy loading element rendered while the workbook is being parsed. Prefer `loadingState` for new code. */
    loadingComponent?: React.ReactElement;
    /** Content shown while the workbook is being parsed. */
    loadingState?: React.ReactNode;
    /** Called when an editable button form control is activated. Duke preserves buttons but does not execute macros. */
    onFormControlAction?: (event: XlsxFormControlActionEvent) => void;
    /** Called after the built-in editor persists a checkbox, radio, list, dropdown, scrollbar, or spinner change. */
    onFormControlChange?: (event: XlsxFormControlChangeEvent) => void;
    /** Override the bundled Office chart renderer. */
    experimentalOfficeCharts?: OfficeCharts;
    /** Replaces the loading placeholder for chart metadata, chart rendering code, and map geometry. */
    renderChartLoading?: (props: XlsxChartLoadingRenderProps) => React.ReactNode;
    /** Replaces menu contents. Use runAction for built-in commands and closeMenu after custom commands. */
    renderContextMenu?: (props: XlsxContextMenuRenderProps) => React.ReactNode;
    /** Enables cell and drawing right-click and keyboard context menus. Defaults to true. */
    enableContextMenu?: boolean;
    /** Class applied to the portaled menu container. */
    contextMenuClassName?: string;
    /** Styles applied to the portaled menu container. */
    contextMenuStyle?: React.CSSProperties & {
        [property: `--${string}`]: string | number | undefined;
    };
    /**
     * Replaces built-in worksheet form-control rendering.
     * Apply `style` to the custom root and use `stopPropagation` on pointer/click handlers.
     * The supplied setters preserve Duke mutation, linked-cell, undo/redo, and change-event behavior.
     */
    renderFormControl?: (props: XlsxFormControlRenderProps) => React.ReactNode;
    /**
     * Replaces worksheet images while preserving their calculated rect and style.
     *
     * @example
     * ```tsx
     * <XlsxViewer renderImage={({ image, style }) => <img src={image.src} style={style} alt={image.description ?? ""} />} />
     * ```
     */
    renderImage?: (props: XlsxImageRenderProps) => React.ReactNode;
    /** Replaces the selected-image outline and resize handles. */
    renderImageSelection?: (props: XlsxImageSelectionRenderProps) => React.ReactNode;
    /**
     * Replaces the scroll viewport shell. Spread `viewportProps` onto the actual scrollable viewport element.
     *
     * @example
     * ```tsx
     * <XlsxViewer
     *   renderScroller={({ children, viewportProps }) => (
     *     <ScrollAreaPrimitive.Root className="h-full min-h-0 w-full min-w-0 flex-1">
     *       <ScrollAreaPrimitive.Viewport {...viewportProps}>{children}</ScrollAreaPrimitive.Viewport>
     *       <ScrollBar />
     *       <ScrollAreaPrimitive.Corner />
     *     </ScrollAreaPrimitive.Root>
     *   )}
     * />
     * ```
     */
    renderScroller?: (props: XlsxScrollerRenderProps) => React.ReactNode;
    /**
     * Toggles the default rounded outer shell.
     *
     * @default true
     */
    rounded?: boolean;
    /**
     * Disables workbook edits, paste, fill, undo/redo, and other mutation actions.
     *
     * @default false
     */
    readOnly?: boolean;
    /**
     * Border and accent color for the current selection.
     *
     * @example
     * ```tsx
     * <XlsxViewer selectionColor="#2563eb" />
     * ```
     */
    selectionColor?: string;
    /** Fill color used for the translucent selection overlay. */
    selectionFillColor?: string;
    /** Accent color used for selected row and column headers. */
    selectionHeaderColor?: string;
    /**
     * Replaces ordinary table and pivot header sort/filter trigger menus.
     * Pivot headers provide `kind: "pivot"` and a `pivot` context.
     * Apply `triggerProps` to your actual trigger button so clicks do not leak into grid selection.
     */
    renderTableHeaderMenu?: (props: XlsxTableHeaderMenuRenderProps) => React.ReactNode;
    /** Overrides only pivot header menus, taking precedence over renderTableHeaderMenu. */
    renderPivotTableHeaderMenu?: (props: XlsxPivotTableHeaderMenuRenderProps) => React.ReactNode;
    /** Color of the active pivot's field guides, shown while its field list is visible. */
    pivotTableHighlightColor?: string;
    /** Enables the built-in pivot pane. Hidden by default. */
    showPivotTableControls?: boolean;
    /** Share an editor from useXlsxPivotTableEditor with external field panes or toolbars. */
    pivotTableEditor?: XlsxPivotTableEditor;
    /** Replace pane content when showPivotTableControls is enabled and the field list is open. */
    renderPivotTableControls?: (props: XlsxPivotTableControlsRenderProps) => React.ReactNode;
    /**
     * Renders custom content positioned over the active cell. The returned node is placed in a
     * container that exactly covers the cell, so it can carry classes, data attributes, or refs
     * for measuring the cell with `getBoundingClientRect()`.
     *
     * The container ignores pointer events so grid interaction is unaffected; set
     * `pointerEvents: "auto"` on your own elements to make them interactive.
     *
     * @example
     * ```tsx
     * <XlsxViewer
     *   renderActiveCellOverlay={({ cell }) => (
     *     <div data-active-cell={`${cell.row}:${cell.col}`} style={{ height: "100%", width: "100%" }} />
     *   )}
     * />
     * ```
     */
    renderActiveCellOverlay?: (props: XlsxActiveCellOverlayRenderProps) => React.ReactNode;
    /** Styling for the built-in editor. Layout and text measurement remain managed by the viewer. */
    cellEditorStyle?: React.CSSProperties;
    /** Opt-in decoration and actions around the editing input. Nothing is rendered on cell selection. */
    renderCellEditorOverlay?: (props: XlsxCellEditorOverlayRenderProps) => React.ReactNode;
    /** Opt-in custom content around a selected cell or range. Hidden while editing. No default UI. */
    renderSelectionPopover?: (props: XlsxSelectionPopoverRenderProps) => React.ReactNode;
    /**
     * Shows worksheet images, charts, shapes, and form controls.
     *
     * @default true
     */
    showImages?: boolean;
    /**
     * Shows the built-in toolbar above the workbook grid.
     *
     * @default true
     */
    showDefaultToolbar?: boolean;
    /**
     * Replaces the toolbar area with a node or render function.
     *
     * @example
     * ```tsx
     * <XlsxViewer toolbar={(controller) => <button onClick={controller.download}>Download</button>} />
     * ```
     */
    toolbar?: React.ReactNode | ((controller: XlsxViewerController) => React.ReactNode);
}

declare function useXlsxViewerController(options: UseXlsxViewerControllerOptions): XlsxViewerController;

declare function XlsxViewer(props: XlsxViewerProps): react_jsx_runtime.JSX.Element;

declare function XlsxViewerProvider({ children, controller, isDark, ...options }: XlsxViewerProviderProps): react_jsx_runtime.JSX.Element;
declare function useXlsxViewer(): XlsxViewerController;
declare function useXlsxViewerSelection(): XlsxViewerSelection;
declare function useXlsxViewerLayout(): XlsxViewerLayout;
declare function useXlsxViewerZoom(): XlsxViewerZoom;
declare function useXlsxViewerEditing(): XlsxViewerEditing;
declare function useXlsxViewerTables(): XlsxViewerTables;
declare function useXlsxViewerPivots(): {
    pivotTables: XlsxPivotTable[];
    pivotFieldListVisible: boolean;
    setPivotFieldListVisible: (visible: boolean) => void;
    getPivotSourceFields: (source: XlsxPivotSource) => XlsxPivotSourceField[];
    getPivotTableAtCell: (cell: XlsxCellAddress, sheetName?: string) => XlsxPivotTable | null;
    upsertPivotTable: (input: XlsxPivotTableInput) => XlsxPivotTable;
    refreshPivotTable: (id: string) => XlsxPivotTable;
    refreshAllPivotTables: () => XlsxPivotTable[];
    removePivotTable: (id: string) => boolean;
    pivotDrillDown: (id: string, row: number, col: number) => XlsxPivotDrillDown;
    showPivotDetails: (id: string, row: number, col: number) => string;
    createPivotChart: (id: string, options?: XlsxPivotChartInput) => XlsxPivotChart;
    togglePivotGroup: (id: string, toggle: XlsxPivotToggle) => XlsxPivotTable;
};
declare function useXlsxPivotTableEditor(options?: XlsxPivotTableEditorOptions): XlsxPivotTableEditor;
declare function useXlsxViewerImages(): XlsxViewerImages;
declare function useXlsxViewerCharts(): XlsxViewerCharts;
declare function useXlsxViewerThumbnails(options?: UseXlsxViewerThumbnailsOptions): XlsxViewerThumbnails;
declare function DefaultXlsxToolbar({ pivotTableEditor }?: {
    pivotTableEditor?: XlsxPivotTableEditor;
}): react_jsx_runtime.JSX.Element;

interface DefaultXlsxPivotTableFieldListProps {
    editor: XlsxPivotTableEditor;
    isDark?: boolean;
    className?: string;
    style?: React.CSSProperties;
}
declare function DefaultXlsxPivotTableFieldList({ editor, isDark, className, style }: DefaultXlsxPivotTableFieldListProps): react_jsx_runtime.JSX.Element;

export { DefaultXlsxPivotTableFieldList, type DefaultXlsxPivotTableFieldListProps, DefaultXlsxToolbar, type UseXlsxViewerControllerOptions, type UseXlsxViewerThumbnailsOptions, type XlsxActiveCellOverlayRenderProps, type XlsxCellAddress, type XlsxCellAlignmentInput, type XlsxCellBorderEdgeInput, type XlsxCellBorderStyleInput, type XlsxCellEditorContext, type XlsxCellEditorOverlayRenderProps, type XlsxCellEditorSession, type XlsxCellFillStyleInput, type XlsxCellFontStyleInput, type XlsxCellGradientStopInput, type XlsxCellNumberFormatInput, type XlsxCellProtectionInput, type XlsxCellRange, type XlsxCellStyleColorInput, type XlsxCellStyleContext, type XlsxCellStyleInput, type XlsxChart, type XlsxChartAxis, type XlsxChartDataLabels, type XlsxChartElementSelection, type XlsxChartLoadingRenderProps, type XlsxChartReference, type XlsxChartSeries, type XlsxChartsheet, type XlsxContextMenuAction, type XlsxContextMenuActionId, type XlsxContextMenuContext, type XlsxContextMenuRenderProps, type XlsxDrawingLayout, type XlsxDrawingOrder, type XlsxFileTooLargeRenderProps, type XlsxFormControl, type XlsxFormControlActionEvent, type XlsxFormControlCaption, type XlsxFormControlCaptionInput, type XlsxFormControlCaptionRun, type XlsxFormControlChangeEvent, type XlsxFormControlInput, type XlsxFormControlKind, type XlsxFormControlKindInput, type XlsxFormControlPatch, type XlsxFormControlRenderProps, type XlsxFormControlSelectionMode, type XlsxFormControlState, type XlsxFormulaTarget, type XlsxFreezePanes, type XlsxHighlightRangeOptions, type XlsxImage, type XlsxImageAnchor, type XlsxImageRect, type XlsxImageRenderProps, type XlsxImageResizeHandlePosition, type XlsxImageSelectionRenderProps, type XlsxMergeMode, type XlsxParsedRange, type XlsxPivotAggregation, type XlsxPivotAxisField, type XlsxPivotCalculatedItem, type XlsxPivotChart, type XlsxPivotChartInput, type XlsxPivotChartType, type XlsxPivotDrillDown, type XlsxPivotFieldArea, type XlsxPivotFilter, type XlsxPivotGrouping, type XlsxPivotHeader, type XlsxPivotHeaderField, type XlsxPivotMember, type XlsxPivotShowAs, type XlsxPivotSource, type XlsxPivotSourceField, type XlsxPivotTable, type XlsxPivotTableControlsRenderProps, type XlsxPivotTableEditor, type XlsxPivotTableEditorOptions, type XlsxPivotTableHeaderMenuRenderProps, type XlsxPivotTableInput, type XlsxPivotTarget, type XlsxPivotToggle, type XlsxPivotValueField, type XlsxRangeHighlight, type XlsxScrollerRenderProps, type XlsxSelectionPopoverContext, type XlsxSelectionPopoverRenderProps, type XlsxShape, type XlsxShapeFill, type XlsxShapeParagraph, type XlsxShapeStroke, type XlsxShapeTextBox, type XlsxShapeTextRun, type XlsxSheetData, type XlsxSheetThumbnail, type XlsxSheetThumbnailResolution, type XlsxSheetVisibility, type XlsxTable, type XlsxTableColumn, type XlsxTableHeaderMenuRenderProps, type XlsxTableSortDirection, type XlsxTableSortState, type XlsxThemePalette, XlsxViewer, type XlsxViewerCharts, type XlsxViewerController, type XlsxViewerEditing, type XlsxViewerImages, type XlsxViewerLayout, type XlsxViewerMessages, type XlsxViewerPivots, type XlsxViewerProps, XlsxViewerProvider, type XlsxViewerProviderProps, type XlsxViewerSelection, type XlsxViewerTables, type XlsxViewerThumbnails, type XlsxViewerZoom, type XlsxWorkbookTab, useXlsxPivotTableEditor, useXlsxViewer, useXlsxViewerCharts, useXlsxViewerController, useXlsxViewerEditing, useXlsxViewerImages, useXlsxViewerLayout, useXlsxViewerPivots, useXlsxViewerSelection, useXlsxViewerTables, useXlsxViewerThumbnails, useXlsxViewerZoom };
