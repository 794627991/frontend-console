import * as React from 'react';
import { Properties } from 'csstype';

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

declare function decodeArchive(data: Uint8Array): any;

declare function init(): void;

declare function inspectArchive(data: Uint8Array): any;

declare function parseXmlTree(xml: string): string;

type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly __wbg_cellvalue_free: (a: number, b: number) => void;
    readonly __wbg_workbook_free: (a: number, b: number) => void;
    readonly __wbg_worksheet_free: (a: number, b: number) => void;
    readonly cellvalue_asBoolean: (a: number) => number;
    readonly cellvalue_asError: (a: number) => [number, number];
    readonly cellvalue_asNumber: (a: number) => [number, number];
    readonly cellvalue_asText: (a: number) => [number, number];
    readonly cellvalue_is_boolean: (a: number) => number;
    readonly cellvalue_is_empty: (a: number) => number;
    readonly cellvalue_is_error: (a: number) => number;
    readonly cellvalue_is_number: (a: number) => number;
    readonly cellvalue_is_text: (a: number) => number;
    readonly cellvalue_toJs: (a: number) => any;
    readonly cellvalue_toString: (a: number) => [number, number];
    readonly init: () => void;
    readonly workbook_addSheet: (a: number, b: number, c: number) => [number, number, number];
    readonly workbook_calculate: (a: number, b: number) => [number, number, number];
    readonly workbook_defineName: (a: number, b: number, c: number, d: number, e: number) => [number, number];
    readonly workbook_exportSnapshot: (a: number) => [number, number, number, number];
    readonly workbook_fromBytes: (a: number, b: number) => [number, number, number];
    readonly workbook_fromBytesWithPassword: (a: number, b: number, c: number, d: number, e: number) => [number, number, number];
    readonly workbook_fromCsvString: (a: number, b: number) => [number, number, number];
    readonly workbook_fromSnapshot: (a: number, b: number) => [number, number, number];
    readonly workbook_getNamedRange: (a: number, b: number, c: number) => [number, number, number, number];
    readonly workbook_getSheet: (a: number, b: number) => [number, number, number];
    readonly workbook_getSheetByName: (a: number, b: number, c: number) => [number, number, number];
    readonly workbook_new: () => number;
    readonly workbook_removeSheet: (a: number, b: number) => [number, number];
    readonly workbook_saveCsvString: (a: number) => [number, number, number, number];
    readonly workbook_saveXlsBytesEncrypted: (a: number, b: number, c: number, d: number, e: number, f: number) => [number, number, number, number];
    readonly workbook_saveXlsbBytes: (a: number) => [number, number, number, number];
    readonly workbook_saveXlsxBytes: (a: number) => [number, number, number, number];
    readonly workbook_saveXlsxBytesEncrypted: (a: number, b: number, c: number, d: number, e: number, f: number, g: number) => [number, number, number, number];
    readonly workbook_setWorkbookProtection: (a: number, b: any) => [number, number];
    readonly workbook_sheetCount: (a: number) => [number, number, number];
    readonly workbook_sheetNames: (a: number) => [number, number, number, number];
    readonly worksheet_getCalculatedValue: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getCalculatedValueAt: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getCell: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getCellAt: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getColumnWidth: (a: number, b: number) => [number, number, number, number];
    readonly worksheet_getImageAt: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getRowHeight: (a: number, b: number) => [number, number, number, number];
    readonly worksheet_hiddenColumns: (a: number) => [number, number, number, number];
    readonly worksheet_hiddenRows: (a: number) => [number, number, number, number];
    readonly worksheet_mergeCells: (a: number, b: number, c: number) => [number, number];
    readonly worksheet_name: (a: number) => [number, number, number, number];
    readonly worksheet_setCell: (a: number, b: number, c: number, d: any) => [number, number];
    readonly worksheet_setCellStyle: (a: number, b: number, c: number, d: any) => [number, number];
    readonly worksheet_setCellStyleAt: (a: number, b: number, c: number, d: any) => [number, number];
    readonly worksheet_setColumnWidth: (a: number, b: number, c: number) => [number, number];
    readonly worksheet_setColumnsHidden: (a: number, b: number, c: number, d: number) => [number, number];
    readonly worksheet_setFormula: (a: number, b: number, c: number, d: number, e: number) => [number, number];
    readonly worksheet_setFreezePanes: (a: number, b: number, c: number) => [number, number];
    readonly worksheet_setProtectedRanges: (a: number, b: any) => [number, number];
    readonly worksheet_setProtection: (a: number, b: any) => [number, number];
    readonly worksheet_setRangeStyle: (a: number, b: number, c: number, d: any) => [number, number];
    readonly worksheet_setRowHeight: (a: number, b: number, c: number) => [number, number];
    readonly worksheet_setRowsHidden: (a: number, b: number, c: number, d: number) => [number, number];
    readonly worksheet_unmergeCells: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_usedRange: (a: number) => [number, number, number];
    readonly workbook_loadCsvString: (a: number, b: number) => [number, number, number];
    readonly decodeArchive: (a: number, b: number) => [number, number, number];
    readonly inspectArchive: (a: number, b: number) => [number, number, number];
    readonly parseXmlTree: (a: number, b: number) => [number, number, number, number];
    readonly workbook_fontFamilies: (a: number) => [number, number];
    readonly workbook_fromBytesForViewer: (a: number, b: number) => [number, number, number];
    readonly workbook_takeViewerArchive: (a: number) => [number, number, number];
    readonly worksheet_autoFilter: (a: number) => [number, number, number];
    readonly worksheet_cellCount: (a: number) => [number, number, number];
    readonly worksheet_colBreaks: (a: number) => [number, number, number];
    readonly worksheet_commentAuthors: (a: number) => [number, number, number, number];
    readonly worksheet_commentCount: (a: number) => [number, number, number];
    readonly worksheet_comments: (a: number) => [number, number, number];
    readonly worksheet_conditionalFormatCount: (a: number) => [number, number, number];
    readonly worksheet_conditionalFormats: (a: number) => [number, number, number];
    readonly worksheet_dataValidationCount: (a: number) => [number, number, number];
    readonly worksheet_dataValidations: (a: number) => [number, number, number];
    readonly worksheet_date1904: (a: number) => [number, number, number];
    readonly worksheet_defaultColumnWidth: (a: number) => [number, number, number];
    readonly worksheet_defaultRowHeight: (a: number) => [number, number, number];
    readonly worksheet_formulaCells: (a: number) => [number, number, number];
    readonly worksheet_formulaCount: (a: number) => [number, number, number];
    readonly worksheet_freezePanes: (a: number) => [number, number, number];
    readonly worksheet_getAutoHeightCells: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getAutofitCells: (a: number, b: number, c: number, d: number) => [number, number, number];
    readonly worksheet_getCellStyle: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getCellStyleAt: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getColumnOutlineLevel: (a: number, b: number) => [number, number, number];
    readonly worksheet_getComment: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getCommentAt: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getFormattedValue: (a: number, b: number, c: number) => [number, number, number, number];
    readonly worksheet_getFormattedValueAt: (a: number, b: number, c: number) => [number, number, number, number];
    readonly worksheet_getFormulaAt: (a: number, b: number, c: number) => [number, number, number, number];
    readonly worksheet_getHyperlink: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getHyperlinkAt: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getMergeSpan: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getRichTextAt: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getRowOutlineLevel: (a: number, b: number) => [number, number, number];
    readonly worksheet_getRowsBatch: (a: number, b: number, c: number, d: any) => [number, number, number];
    readonly worksheet_getSpillSource: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getTableByName: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_getValueSnapshotAt: (a: number, b: number, c: number) => [number, number, number, number];
    readonly worksheet_hasComment: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_hasCommentAt: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_hyperlinkCount: (a: number) => [number, number, number];
    readonly worksheet_hyperlinks: (a: number) => [number, number, number];
    readonly worksheet_isColumnCollapsed: (a: number, b: number) => [number, number, number];
    readonly worksheet_isColumnHidden: (a: number, b: number) => [number, number, number];
    readonly worksheet_isEmpty: (a: number) => [number, number, number];
    readonly worksheet_isMergedSecondary: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_isRowCollapsed: (a: number, b: number) => [number, number, number];
    readonly worksheet_isRowHidden: (a: number, b: number) => [number, number, number];
    readonly worksheet_isSelected: (a: number) => [number, number, number];
    readonly worksheet_isSpillSource: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_isSpillTarget: (a: number, b: number, c: number) => [number, number, number];
    readonly worksheet_mergedRegions: (a: number) => [number, number, number];
    readonly worksheet_pageSetup: (a: number) => [number, number, number];
    readonly worksheet_printArea: (a: number) => [number, number, number, number];
    readonly worksheet_protectedRanges: (a: number) => [number, number, number];
    readonly worksheet_protection: (a: number) => [number, number, number];
    readonly worksheet_repeatCols: (a: number) => [number, number, number, number];
    readonly worksheet_repeatRows: (a: number) => [number, number, number, number];
    readonly worksheet_restoreValueSnapshotAt: (a: number, b: number, c: number, d: number, e: number) => [number, number];
    readonly worksheet_rowBreaks: (a: number) => [number, number, number];
    readonly worksheet_selections: (a: number) => [number, number, number];
    readonly worksheet_splitPanes: (a: number) => [number, number, number];
    readonly worksheet_tabColor: (a: number) => [number, number, number];
    readonly worksheet_tableCount: (a: number) => [number, number, number];
    readonly worksheet_tables: (a: number) => [number, number, number];
    readonly worksheet_visibility: (a: number) => [number, number, number, number];
    readonly worksheet_zoomScale: (a: number) => [number, number, number];
    readonly workbook_activeSheet: (a: number) => [number, number, number];
    readonly workbook_chartsheetCount: (a: number) => [number, number, number];
    readonly workbook_chartsheets: (a: number) => [number, number, number];
    readonly workbook_createPivotChart: (a: number, b: number, c: number, d: any) => [number, number, number];
    readonly workbook_isEmpty: (a: number) => [number, number, number];
    readonly workbook_modifiedPivotCharts: (a: number) => [number, number, number];
    readonly workbook_namedRanges: (a: number) => [number, number, number];
    readonly workbook_resolveColor: (a: number, b: any) => [number, number, number, number];
    readonly workbook_settings: (a: number) => [number, number, number];
    readonly workbook_sheetIndex: (a: number, b: number, c: number) => [number, number, number];
    readonly workbook_sheetOrder: (a: number) => [number, number, number];
    readonly workbook_syncFormControls: (a: number) => number;
    readonly workbook_syncFormControlsFromLinkedCells: (a: number) => number;
    readonly workbook_themePalette: (a: number) => [number, number];
    readonly workbook_totalSheetCount: (a: number) => [number, number, number];
    readonly workbook_updatePivotChart: (a: number, b: number, c: number, d: number, e: number, f: any) => [number, number];
    readonly workbook_workbookProtection: (a: number) => [number, number, number];
    readonly worksheet_addDrawing: (a: number, b: any) => [number, number, number];
    readonly worksheet_chartCount: (a: number) => [number, number, number];
    readonly worksheet_chartExCount: (a: number) => [number, number, number];
    readonly worksheet_charts: (a: number) => [number, number, number];
    readonly worksheet_chartsEx: (a: number) => [number, number, number];
    readonly worksheet_drawingImageData: (a: number, b: any) => [number, number, number, number];
    readonly worksheet_drawingSvgData: (a: number, b: any) => [number, number, number, number];
    readonly worksheet_drawings: (a: number) => [number, number, number];
    readonly worksheet_formControlCount: (a: number) => [number, number, number];
    readonly worksheet_formControls: (a: number) => [number, number, number];
    readonly worksheet_imageCount: (a: number) => [number, number, number];
    readonly worksheet_images: (a: number) => [number, number, number];
    readonly worksheet_insertDrawing: (a: number, b: number, c: any) => [number, number];
    readonly worksheet_moveDrawing: (a: number, b: number, c: number) => [number, number];
    readonly worksheet_removeDrawing: (a: number, b: any) => [number, number];
    readonly worksheet_setDrawing: (a: number, b: any, c: any) => [number, number];
    readonly worksheet_setFormControlCheckState: (a: number, b: any, c: number, d: number) => [number, number, number];
    readonly workbook_getPivotSourceFields: (a: number, b: any) => [number, number, number];
    readonly workbook_pivotDrillDown: (a: number, b: number, c: number, d: number, e: number) => [number, number, number];
    readonly workbook_pivotTables: (a: number) => [number, number, number];
    readonly workbook_refreshPivotTable: (a: number, b: number, c: number) => [number, number, number];
    readonly workbook_removePivotTable: (a: number, b: number, c: number) => [number, number, number];
    readonly workbook_upsertPivotTable: (a: number, b: any) => [number, number, number];
    readonly __wbindgen_malloc: (a: number, b: number) => number;
    readonly __wbindgen_realloc: (a: number, b: number, c: number, d: number) => number;
    readonly __wbindgen_exn_store: (a: number) => void;
    readonly __externref_table_alloc: () => number;
    readonly __wbindgen_externrefs: WebAssembly.Table;
    readonly __wbindgen_free: (a: number, b: number, c: number) => void;
    readonly __externref_table_dealloc: (a: number) => void;
    readonly __externref_drop_slice: (a: number, b: number) => void;
    readonly __wbindgen_start: () => void;
}

type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
declare function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
declare function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;

type __duke_sheets_generated_duke_sheets_wasm_js_AlignmentInput = AlignmentInput;
type __duke_sheets_generated_duke_sheets_wasm_js_BorderEdgeInput = BorderEdgeInput;
type __duke_sheets_generated_duke_sheets_wasm_js_BorderStyleInput = BorderStyleInput;
type __duke_sheets_generated_duke_sheets_wasm_js_CellProtectionInput = CellProtectionInput;
type __duke_sheets_generated_duke_sheets_wasm_js_CellValue = CellValue;
declare const __duke_sheets_generated_duke_sheets_wasm_js_CellValue: typeof CellValue;
type __duke_sheets_generated_duke_sheets_wasm_js_Chart = Chart;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartAxis = ChartAxis;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartColorStyle = ChartColorStyle;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartDataLabels = ChartDataLabels;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartDataReference = ChartDataReference;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartDataSeries = ChartDataSeries;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartDrawing = ChartDrawing;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartEx = ChartEx;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartExAxis = ChartExAxis;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartExColorPosition = ChartExColorPosition;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartExDataLabelOverride = ChartExDataLabelOverride;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartExDrawing = ChartExDrawing;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartExGridlines = ChartExGridlines;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartExInput = ChartExInput;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartExSeries = ChartExSeries;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartExSeriesLayoutProperties = ChartExSeriesLayoutProperties;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartExTitle = ChartExTitle;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartExTitleInput = ChartExTitleInput;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartInput = ChartInput;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartNumberFormat = ChartNumberFormat;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartSeriesInput = ChartSeriesInput;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartShapeProperties = ChartShapeProperties;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartStyle = ChartStyle;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartStyleEntry = ChartStyleEntry;
type __duke_sheets_generated_duke_sheets_wasm_js_ChartStyleReference = ChartStyleReference;
type __duke_sheets_generated_duke_sheets_wasm_js_ColorInput = ColorInput;
type __duke_sheets_generated_duke_sheets_wasm_js_CommentDrawing = CommentDrawing;
type __duke_sheets_generated_duke_sheets_wasm_js_Drawing = Drawing;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingAnchor = DrawingAnchor;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingCellMarker = DrawingCellMarker;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingChildTransform = DrawingChildTransform;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingColor = DrawingColor;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingComment = DrawingComment;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingGroupTransform = DrawingGroupTransform;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingImage = DrawingImage;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingImageInput = DrawingImageInput;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingInput = DrawingInput;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingMeta = DrawingMeta;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingMetaInput = DrawingMetaInput;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingPlacement = DrawingPlacement;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingRunFont = DrawingRunFont;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingShape = DrawingShape;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingShapeFill = DrawingShapeFill;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingShapeInput = DrawingShapeInput;
type __duke_sheets_generated_duke_sheets_wasm_js_DrawingText = DrawingText;
type __duke_sheets_generated_duke_sheets_wasm_js_FillStyleInput = FillStyleInput;
type __duke_sheets_generated_duke_sheets_wasm_js_FontStyleInput = FontStyleInput;
type __duke_sheets_generated_duke_sheets_wasm_js_FormControlDrawing = FormControlDrawing;
type __duke_sheets_generated_duke_sheets_wasm_js_FormControlInputPayload = FormControlInputPayload;
type __duke_sheets_generated_duke_sheets_wasm_js_FormControlInteractionResult = FormControlInteractionResult;
type __duke_sheets_generated_duke_sheets_wasm_js_FormControlKind = FormControlKind;
type __duke_sheets_generated_duke_sheets_wasm_js_FormControlKindInput = FormControlKindInput;
type __duke_sheets_generated_duke_sheets_wasm_js_FormControlPayload = FormControlPayload;
type __duke_sheets_generated_duke_sheets_wasm_js_GradientStopInput = GradientStopInput;
type __duke_sheets_generated_duke_sheets_wasm_js_GroupDrawing = GroupDrawing;
type __duke_sheets_generated_duke_sheets_wasm_js_ImageDrawing = ImageDrawing;
type __duke_sheets_generated_duke_sheets_wasm_js_InitInput = InitInput;
type __duke_sheets_generated_duke_sheets_wasm_js_InitOutput = InitOutput;
type __duke_sheets_generated_duke_sheets_wasm_js_JsMergeSpan = JsMergeSpan;
type __duke_sheets_generated_duke_sheets_wasm_js_JsRow = JsRow;
type __duke_sheets_generated_duke_sheets_wasm_js_JsRowCell = JsRowCell;
type __duke_sheets_generated_duke_sheets_wasm_js_JsRowsOptions = JsRowsOptions;
type __duke_sheets_generated_duke_sheets_wasm_js_NumberFormatInput = NumberFormatInput;
type __duke_sheets_generated_duke_sheets_wasm_js_RawDrawing = RawDrawing;
type __duke_sheets_generated_duke_sheets_wasm_js_RawDrawingMetadata = RawDrawingMetadata;
type __duke_sheets_generated_duke_sheets_wasm_js_RectEmu = RectEmu;
type __duke_sheets_generated_duke_sheets_wasm_js_RowIterator = RowIterator;
declare const __duke_sheets_generated_duke_sheets_wasm_js_RowIterator: typeof RowIterator;
type __duke_sheets_generated_duke_sheets_wasm_js_ShapeDrawing = ShapeDrawing;
type __duke_sheets_generated_duke_sheets_wasm_js_StyleInput = StyleInput;
type __duke_sheets_generated_duke_sheets_wasm_js_SyncInitInput = SyncInitInput;
type __duke_sheets_generated_duke_sheets_wasm_js_Workbook = Workbook;
declare const __duke_sheets_generated_duke_sheets_wasm_js_Workbook: typeof Workbook;
type __duke_sheets_generated_duke_sheets_wasm_js_Worksheet = Worksheet;
declare const __duke_sheets_generated_duke_sheets_wasm_js_Worksheet: typeof Worksheet;
declare const __duke_sheets_generated_duke_sheets_wasm_js_decodeArchive: typeof decodeArchive;
declare const __duke_sheets_generated_duke_sheets_wasm_js_init: typeof init;
declare const __duke_sheets_generated_duke_sheets_wasm_js_initSync: typeof initSync;
declare const __duke_sheets_generated_duke_sheets_wasm_js_inspectArchive: typeof inspectArchive;
declare const __duke_sheets_generated_duke_sheets_wasm_js_parseXmlTree: typeof parseXmlTree;
declare namespace __duke_sheets_generated_duke_sheets_wasm_js {
  export { type __duke_sheets_generated_duke_sheets_wasm_js_AlignmentInput as AlignmentInput, type __duke_sheets_generated_duke_sheets_wasm_js_BorderEdgeInput as BorderEdgeInput, type __duke_sheets_generated_duke_sheets_wasm_js_BorderStyleInput as BorderStyleInput, type __duke_sheets_generated_duke_sheets_wasm_js_CellProtectionInput as CellProtectionInput, __duke_sheets_generated_duke_sheets_wasm_js_CellValue as CellValue, type __duke_sheets_generated_duke_sheets_wasm_js_Chart as Chart, type __duke_sheets_generated_duke_sheets_wasm_js_ChartAxis as ChartAxis, type __duke_sheets_generated_duke_sheets_wasm_js_ChartColorStyle as ChartColorStyle, type __duke_sheets_generated_duke_sheets_wasm_js_ChartDataLabels as ChartDataLabels, type __duke_sheets_generated_duke_sheets_wasm_js_ChartDataReference as ChartDataReference, type __duke_sheets_generated_duke_sheets_wasm_js_ChartDataSeries as ChartDataSeries, type __duke_sheets_generated_duke_sheets_wasm_js_ChartDrawing as ChartDrawing, type __duke_sheets_generated_duke_sheets_wasm_js_ChartEx as ChartEx, type __duke_sheets_generated_duke_sheets_wasm_js_ChartExAxis as ChartExAxis, type __duke_sheets_generated_duke_sheets_wasm_js_ChartExColorPosition as ChartExColorPosition, type __duke_sheets_generated_duke_sheets_wasm_js_ChartExDataLabelOverride as ChartExDataLabelOverride, type __duke_sheets_generated_duke_sheets_wasm_js_ChartExDrawing as ChartExDrawing, type __duke_sheets_generated_duke_sheets_wasm_js_ChartExGridlines as ChartExGridlines, type __duke_sheets_generated_duke_sheets_wasm_js_ChartExInput as ChartExInput, type __duke_sheets_generated_duke_sheets_wasm_js_ChartExSeries as ChartExSeries, type __duke_sheets_generated_duke_sheets_wasm_js_ChartExSeriesLayoutProperties as ChartExSeriesLayoutProperties, type __duke_sheets_generated_duke_sheets_wasm_js_ChartExTitle as ChartExTitle, type __duke_sheets_generated_duke_sheets_wasm_js_ChartExTitleInput as ChartExTitleInput, type __duke_sheets_generated_duke_sheets_wasm_js_ChartInput as ChartInput, type __duke_sheets_generated_duke_sheets_wasm_js_ChartNumberFormat as ChartNumberFormat, type __duke_sheets_generated_duke_sheets_wasm_js_ChartSeriesInput as ChartSeriesInput, type __duke_sheets_generated_duke_sheets_wasm_js_ChartShapeProperties as ChartShapeProperties, type __duke_sheets_generated_duke_sheets_wasm_js_ChartStyle as ChartStyle, type __duke_sheets_generated_duke_sheets_wasm_js_ChartStyleEntry as ChartStyleEntry, type __duke_sheets_generated_duke_sheets_wasm_js_ChartStyleReference as ChartStyleReference, type __duke_sheets_generated_duke_sheets_wasm_js_ColorInput as ColorInput, type __duke_sheets_generated_duke_sheets_wasm_js_CommentDrawing as CommentDrawing, type __duke_sheets_generated_duke_sheets_wasm_js_Drawing as Drawing, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingAnchor as DrawingAnchor, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingCellMarker as DrawingCellMarker, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingChildTransform as DrawingChildTransform, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingColor as DrawingColor, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingComment as DrawingComment, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingGroupTransform as DrawingGroupTransform, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingImage as DrawingImage, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingImageInput as DrawingImageInput, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingInput as DrawingInput, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingMeta as DrawingMeta, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingMetaInput as DrawingMetaInput, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingPlacement as DrawingPlacement, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingRunFont as DrawingRunFont, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingShape as DrawingShape, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingShapeFill as DrawingShapeFill, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingShapeInput as DrawingShapeInput, type __duke_sheets_generated_duke_sheets_wasm_js_DrawingText as DrawingText, type __duke_sheets_generated_duke_sheets_wasm_js_FillStyleInput as FillStyleInput, type __duke_sheets_generated_duke_sheets_wasm_js_FontStyleInput as FontStyleInput, type __duke_sheets_generated_duke_sheets_wasm_js_FormControlDrawing as FormControlDrawing, type __duke_sheets_generated_duke_sheets_wasm_js_FormControlInputPayload as FormControlInputPayload, type __duke_sheets_generated_duke_sheets_wasm_js_FormControlInteractionResult as FormControlInteractionResult, type __duke_sheets_generated_duke_sheets_wasm_js_FormControlKind as FormControlKind, type __duke_sheets_generated_duke_sheets_wasm_js_FormControlKindInput as FormControlKindInput, type __duke_sheets_generated_duke_sheets_wasm_js_FormControlPayload as FormControlPayload, type __duke_sheets_generated_duke_sheets_wasm_js_GradientStopInput as GradientStopInput, type __duke_sheets_generated_duke_sheets_wasm_js_GroupDrawing as GroupDrawing, type __duke_sheets_generated_duke_sheets_wasm_js_ImageDrawing as ImageDrawing, type __duke_sheets_generated_duke_sheets_wasm_js_InitInput as InitInput, type __duke_sheets_generated_duke_sheets_wasm_js_InitOutput as InitOutput, type __duke_sheets_generated_duke_sheets_wasm_js_JsMergeSpan as JsMergeSpan, type __duke_sheets_generated_duke_sheets_wasm_js_JsRow as JsRow, type __duke_sheets_generated_duke_sheets_wasm_js_JsRowCell as JsRowCell, type __duke_sheets_generated_duke_sheets_wasm_js_JsRowsOptions as JsRowsOptions, type __duke_sheets_generated_duke_sheets_wasm_js_NumberFormatInput as NumberFormatInput, type __duke_sheets_generated_duke_sheets_wasm_js_RawDrawing as RawDrawing, type __duke_sheets_generated_duke_sheets_wasm_js_RawDrawingMetadata as RawDrawingMetadata, type __duke_sheets_generated_duke_sheets_wasm_js_RectEmu as RectEmu, __duke_sheets_generated_duke_sheets_wasm_js_RowIterator as RowIterator, type __duke_sheets_generated_duke_sheets_wasm_js_ShapeDrawing as ShapeDrawing, type __duke_sheets_generated_duke_sheets_wasm_js_StyleInput as StyleInput, type __duke_sheets_generated_duke_sheets_wasm_js_SyncInitInput as SyncInitInput, __duke_sheets_generated_duke_sheets_wasm_js_Workbook as Workbook, __duke_sheets_generated_duke_sheets_wasm_js_Worksheet as Worksheet, __duke_sheets_generated_duke_sheets_wasm_js_decodeArchive as decodeArchive, __wbg_init as default, __duke_sheets_generated_duke_sheets_wasm_js_init as init, __duke_sheets_generated_duke_sheets_wasm_js_initSync as initSync, __duke_sheets_generated_duke_sheets_wasm_js_inspectArchive as inspectArchive, __duke_sheets_generated_duke_sheets_wasm_js_parseXmlTree as parseXmlTree };
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

type XlsxVanillaContent = Node | string | number | null;
type XlsxVanillaStyle = Properties<string | number>;
interface XlsxVanillaChartLoadingRenderProps {
    chart: XlsxChart;
    rect: XlsxImageRect;
    stage?: "metadata" | "renderer" | "map";
}
interface XlsxVanillaContextMenuRenderProps {
    context: XlsxContextMenuContext;
    actions: XlsxContextMenuAction[];
    runAction: (actionId: XlsxContextMenuActionId) => Promise<boolean>;
    closeMenu: () => void;
    signal: AbortSignal;
    commit: (apply: (context: XlsxContextMenuContext) => void) => boolean;
    position: {
        x: number;
        y: number;
    };
    isDark: boolean;
    busy: boolean;
    error: string | null;
}
interface XlsxVanillaFileTooLargeRenderProps {
    displayFileName: string;
    fileSizeBytes: number;
    maxFileSizeBytes: number;
}
interface XlsxVanillaImageRenderProps {
    image: XlsxImage;
    rect: XlsxImageRect;
    style: XlsxVanillaStyle;
}
interface XlsxVanillaFormControlRenderProps {
    activate: () => void;
    checked: boolean;
    control: XlsxFormControl;
    disabled: boolean;
    items: string[];
    label: string;
    mixed: boolean;
    readOnly: boolean;
    rect: XlsxImageRect;
    setSelected: (selected: number | number[] | undefined) => boolean;
    setState: (state: XlsxFormControlState) => boolean;
    setValue: (value: number) => boolean;
    stopPropagation: (event: Event) => void;
    style: XlsxVanillaStyle;
    zoomFactor: number;
}
interface XlsxVanillaCellStyleContext {
    cell: XlsxCellAddress;
    hasChartHighlight: boolean;
    hasConditionalFormat: boolean;
    hasHyperlink: boolean;
    hasValidation: boolean;
    isMerged: boolean;
    isTableHeader: boolean;
    resolvedStyle: XlsxVanillaStyle;
    sheetName: string;
    value: string;
    workbookSheetIndex: number;
}
interface XlsxVanillaViewerOptions extends UseXlsxViewerControllerOptions {
    highlightedRanges?: string | readonly string[] | null;
    autoScrollToHighlightedRanges?: boolean;
    highlightClassName?: string;
    className?: string;
    emptyState?: XlsxVanillaContent;
    enableCanvasSelectionAnimation?: boolean;
    enableGestureZoom?: boolean;
    experimentalCanvas?: boolean;
    experimentalOfficeCharts?: OfficeCharts;
    errorState?: XlsxVanillaContent | ((error: Error) => XlsxVanillaContent);
    fileTooLargeState?: XlsxVanillaContent | ((props: XlsxVanillaFileTooLargeRenderProps) => XlsxVanillaContent);
    getCellStyle?: (context: XlsxVanillaCellStyleContext) => XlsxVanillaStyle | null | undefined;
    headerBackgroundColor?: string;
    headerTextColor?: string;
    height?: XlsxVanillaStyle["height"];
    isDark?: boolean;
    loadingState?: XlsxVanillaContent;
    onFormControlAction?: (event: XlsxFormControlActionEvent) => void;
    onFormControlChange?: (event: XlsxFormControlChangeEvent) => void;
    renderChartLoading?: (props: XlsxVanillaChartLoadingRenderProps) => XlsxVanillaContent;
    renderContextMenu?: (props: XlsxVanillaContextMenuRenderProps) => XlsxVanillaContent;
    enableContextMenu?: boolean;
    contextMenuClassName?: string;
    contextMenuStyle?: XlsxVanillaStyle & {
        [property: `--${string}`]: string | number | undefined;
    };
    renderFormControl?: (props: XlsxVanillaFormControlRenderProps) => XlsxVanillaContent;
    renderImage?: (props: XlsxVanillaImageRenderProps) => XlsxVanillaContent;
    rounded?: boolean;
    selectionColor?: string;
    selectionFillColor?: string;
    selectionHeaderColor?: string;
    renderActiveCellOverlay?: (props: XlsxActiveCellOverlayRenderProps) => XlsxVanillaContent;
    cellEditorStyle?: XlsxVanillaStyle;
    renderCellEditorOverlay?: (props: XlsxCellEditorOverlayRenderProps) => XlsxVanillaContent;
    renderSelectionPopover?: (props: XlsxSelectionPopoverRenderProps) => XlsxVanillaContent;
    /** Enable the built-in pivot pane. Defaults to false. */
    showPivotTableControls?: boolean;
    /** Replace pane content when the built-in pane is enabled and the field list is open. */
    renderPivotTableControls?: (props: Omit<XlsxPivotTableControlsRenderProps, "defaultNode">) => XlsxVanillaContent;
    /** Replace pivot header triggers/popups; forward triggerProps and popupProps to their elements. */
    renderPivotTableHeaderMenu?: (props: Omit<XlsxPivotTableHeaderMenuRenderProps, "defaultNode">) => XlsxVanillaContent;
    /** Color of the active pivot's field guides while its field list is visible. */
    pivotTableHighlightColor?: string;
    showImages?: boolean;
    showDefaultToolbar?: boolean;
    toolbar?: XlsxVanillaContent | ((controller: XlsxViewerController) => XlsxVanillaContent);
}
interface XlsxVanillaViewer {
    readonly element: HTMLElement;
    getController(): XlsxViewerController | null;
    reload(): void;
    setOptions(options: Partial<XlsxVanillaViewerOptions>): void;
    subscribe(listener: (controller: XlsxViewerController) => void): () => void;
    destroy(): void;
}

declare function formatBinaryBytes(bytes: number): string;
declare class XlsxFileSizeLimitExceededError extends Error {
    fileSizeBytes: number;
    maxFileSizeBytes: number;
    constructor(fileSizeBytes: number, maxFileSizeBytes: number);
}

type XlsxWasmSource = string | URL | Request | Response | BufferSource | WebAssembly.Module;
type WorkerWasmSource = string | ArrayBuffer | WebAssembly.Module;
declare function setWasmSource(source: XlsxWasmSource): void;
declare function initWasm(source?: XlsxWasmSource): Promise<typeof __duke_sheets_generated_duke_sheets_wasm_js>;
declare function canUseConfiguredWasmSourceInWorker(): boolean;
declare function getConfiguredWorkerWasmSource(): Promise<WorkerWasmSource | undefined>;
declare function getSheetsWasmModule(): Promise<typeof __duke_sheets_generated_duke_sheets_wasm_js>;

declare class XlsxViewer implements XlsxVanillaViewer {
    readonly element: HTMLElement;
    private readonly viewer;
    constructor(container: Element | DocumentFragment, options?: XlsxVanillaViewerOptions);
    getController(): XlsxViewerController | null;
    setOptions(options: Partial<XlsxVanillaViewerOptions>): void;
    reload(): void;
    subscribe(listener: (controller: XlsxViewerController) => void): () => void;
    destroy(): void;
}
declare function createXlsxViewer(container: Element | DocumentFragment, options?: XlsxVanillaViewerOptions): XlsxViewer;
declare function __createControlledViewer(container: Element | DocumentFragment): {
    update(props: unknown): void;
    destroy(): void;
};
declare function __createContentNode(node: Node): unknown;
declare function __createContentRoot(container: Element): {
    update(content: unknown): void;
    destroy(): void;
};

export { type XlsxFormControlKindInput as $, type XlsxChartTypeGroup as A, type XlsxChartWall as B, type XlsxChartsheet as C, type XlsxClipboardData as D, type XlsxConditionalColorScaleRule as E, type XlsxConditionalDataBarRule as F, type XlsxConditionalFormatIcon as G, type XlsxConditionalFormatRule as H, type XlsxConditionalFormatValueObject as I, type XlsxConditionalIconSetRule as J, type XlsxConditionalStyledRule as K, type XlsxContextMenuAction as L, type XlsxContextMenuActionId as M, type XlsxContextMenuContext as N, type XlsxDataValidation as O, type XlsxDrawingLayout as P, XlsxFileSizeLimitExceededError as Q, type XlsxFormControl as R, type XlsxFormControlActionEvent as S, type XlsxFormControlCaption as T, type UseXlsxViewerControllerOptions as U, type XlsxFormControlCaptionInput as V, type XlsxFormControlCaptionRun as W, type XlsxParsedRange as X, type XlsxFormControlChangeEvent as Y, type XlsxFormControlInput as Z, type XlsxFormControlKind as _, type UseXlsxViewerThumbnailsOptions as a, type XlsxVanillaFileTooLargeRenderProps as a$, type XlsxFormControlPatch as a0, type XlsxFormControlSelectionMode as a1, type XlsxFormControlState as a2, type XlsxFormulaTarget as a3, type XlsxFreezePanes as a4, type XlsxHighlightRangeOptions as a5, type XlsxImage as a6, type XlsxImageAnchor as a7, type XlsxImageMarker as a8, type XlsxImageRect as a9, type XlsxPivotValueField as aA, type XlsxRangeHighlight as aB, type XlsxResolvedCellStyle as aC, type XlsxSelectionPopoverContext as aD, type XlsxSelectionPopoverRenderProps as aE, type XlsxShape as aF, type XlsxShapeFill as aG, type XlsxShapeParagraph as aH, type XlsxShapeStroke as aI, type XlsxShapeTextBox as aJ, type XlsxShapeTextRun as aK, type XlsxSheetData as aL, type XlsxSheetThumbnail as aM, type XlsxSheetThumbnailResolution as aN, type XlsxSheetVisibility as aO, type XlsxSparkline as aP, type XlsxTable as aQ, type XlsxTableColumn as aR, type XlsxTableSortDirection as aS, type XlsxTableSortState as aT, type XlsxTableStyleDefinition as aU, type XlsxTableStyleInfo as aV, type XlsxThemePalette as aW, type XlsxVanillaCellStyleContext as aX, type XlsxVanillaChartLoadingRenderProps as aY, type XlsxVanillaContent as aZ, type XlsxVanillaContextMenuRenderProps as a_, type XlsxImageResizeHandlePosition as aa, type XlsxMergeMode as ab, type XlsxPivotAggregation as ac, type XlsxPivotAxisField as ad, type XlsxPivotCalculatedItem as ae, type XlsxPivotChart as af, type XlsxPivotChartInput as ag, type XlsxPivotChartType as ah, type XlsxPivotDrillDown as ai, type XlsxPivotFieldArea as aj, type XlsxPivotFilter as ak, type XlsxPivotGrouping as al, type XlsxPivotHeader as am, type XlsxPivotHeaderField as an, type XlsxPivotMember as ao, type XlsxPivotShowAs as ap, type XlsxPivotSource as aq, type XlsxPivotSourceField as ar, type XlsxPivotTable as as, type XlsxPivotTableControlsRenderProps as at, type XlsxPivotTableEditor as au, type XlsxPivotTableEditorOptions as av, type XlsxPivotTableHeaderMenuRenderProps as aw, type XlsxPivotTableInput as ax, type XlsxPivotTarget as ay, type XlsxPivotToggle as az, type XlsxActiveCellOverlayRenderProps as b, type XlsxVanillaFormControlRenderProps as b0, type XlsxVanillaImageRenderProps as b1, type XlsxVanillaStyle as b2, type XlsxVanillaViewer as b3, type XlsxVanillaViewerOptions as b4, XlsxViewer as b5, type XlsxViewerCharts as b6, type XlsxViewerController as b7, type XlsxViewerEditing as b8, type XlsxViewerImages as b9, type XlsxViewerLayout as ba, type XlsxViewerMessages as bb, type XlsxViewerPivots as bc, type XlsxViewerSelection as bd, type XlsxViewerTables as be, type XlsxViewerThumbnails as bf, type XlsxViewerZoom as bg, type XlsxWasmSource as bh, type XlsxWorkbookTab as bi, createXlsxViewer as bj, initWasm as bk, setWasmSource as bl, type WorkerWasmSource as bm, __createContentNode as bn, __createContentRoot as bo, __createControlledViewer as bp, canUseConfiguredWasmSourceInWorker as bq, formatBinaryBytes as br, getConfiguredWorkerWasmSource as bs, getSheetsWasmModule as bt, type XlsxCellAddress as c, type XlsxCellAlignmentInput as d, type XlsxCellBorderEdgeInput as e, type XlsxCellBorderStyleInput as f, type XlsxCellEditorContext as g, type XlsxCellEditorOverlayRenderProps as h, type XlsxCellEditorSession as i, type XlsxCellFillStyleInput as j, type XlsxCellFontStyleInput as k, type XlsxCellGradientStopInput as l, type XlsxCellNumberFormatInput as m, type XlsxCellProtectionInput as n, type XlsxCellRange as o, type XlsxCellStyleColorInput as p, type XlsxCellStyleInput as q, type XlsxChart as r, type XlsxChartAxis as s, type XlsxChartDataLabels as t, type XlsxChartElementSelection as u, type XlsxChartLegend as v, type XlsxChartPointDataLabel as w, type XlsxChartPointStyle as x, type XlsxChartReference as y, type XlsxChartSeries as z };
