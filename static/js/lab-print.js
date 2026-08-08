/**
 * Lab report print (A4 popup) + layout/pagination helpers.
 * Uses named @page size "A4" so Windows/WebView2 defaults to A4, not Letter.
 */
const A4_WIDTH_MM = 210;
const A4_HEIGHT_MM = 297;
const A4_PAGE_SIZE = `${A4_WIDTH_MM}mm ${A4_HEIGHT_MM}mm`;
const MM_TO_PX = 96 / 25.4;

function resolvePageSizeRule(settings) {
    const raw = String(settings?.page_size || 'A4').trim().toUpperCase();
    if (raw === 'A4') return 'A4 portrait';
    if (raw === 'LETTER') return 'letter portrait';
    return `${A4_WIDTH_MM}mm ${A4_HEIGHT_MM}mm`;
}

function mmToPx(mm) {
    return mm * MM_TO_PX;
}

/** Footer height (px) derived from print_settings — no separate footer_height column. */
function getFooterHeightPx(s) {
    if (s?.footer_height != null && s.footer_height > 0) {
        return Number(s.footer_height);
    }
    const marginTop = s?.footer_margin_top ?? 40;
    const paddingTop = s?.footer_padding_top ?? 20;
    const fontSize = s?.footer_font_size ?? 11;
    const lineHeight = 1.35;
    let lines = 2;
    if (s?.display_pathologist_signature) lines += 1;
    if (s?.display_verified_by) lines += 1;
    const borderPx = 1;
    return marginTop + paddingTop + borderPx + Math.ceil(lines * fontSize * lineHeight) + 6;
}

/**
 * Printable vertical budget (px) inside page margins, below fixed header and above fixed footer.
 */
function getPageLayout(settings) {
    const s = settings || {};
    const marginTopMm = s.page_top_margin ?? 25;
    const marginBottomMm = s.page_bottom_margin ?? 25;
    const headerPx = s.header_height ?? 140;
    const footerPx = getFooterHeightPx(s);
    const innerHeightPx = mmToPx(A4_HEIGHT_MM - marginTopMm - marginBottomMm);
    const bodyBudgetPx = Math.max(80, innerHeightPx - headerPx - footerPx);
    return {
        marginTopMm,
        marginRightMm: s.page_right_margin ?? 15,
        marginBottomMm,
        marginLeftMm: s.page_left_margin ?? 15,
        headerPx,
        footerPx,
        bodyBudgetPx
    };
}

function linePx(fontSize, lineHeight = 1.25) {
    return fontSize * lineHeight;
}

function estimateCategoryChromePx(s) {
    const catFont = s?.category_font_size ?? 18;
    const catPadTop = s?.category_padding_top ?? 6;
    const catPadBottom = s?.category_padding_bottom ?? 4;
    const catBorder = s?.category_border_width ?? 2;
    const headFont = s?.test_name_font_size ?? 14;
    const headPadV = s?.table_header_padding_vertical ?? 8;
    const titleBlock = catBorder + catPadTop + linePx(catFont, 1.2) + catPadBottom + 4;
    const theadBlock = headPadV * 2 + linePx(headFont, 1.2) + 2;
    return titleBlock + theadBlock;
}

/**
 * Cost of a category title separator row when rendered INSIDE an existing table.
 * Only the title row — no thead since one shared thead is already at the top.
 */
function estimateCategorySeparatorRowPx(s) {
    const catFont = s?.category_font_size ?? 18;
    const catPadTop = s?.category_padding_top ?? 6;
    const catPadBottom = s?.category_padding_bottom ?? 4;
    const catBorder = s?.category_border_width ?? 2;
    return catBorder + catPadTop + Math.ceil(linePx(catFont, 1.2)) + catPadBottom;
}

function estimateTestTitleRowPx(s) {
    const font = s?.group_font_size ?? 15;
    const padTop = s?.group_padding_top ?? 8;
    const padBottom = s?.group_padding_bottom ?? 2;
    return padTop + linePx(font, 1.2) + padBottom;
}

function estimateParamRowPx(s) {
    const font = s?.result_font_size ?? 14;
    const padV = s?.table_cell_padding_vertical ?? 4;
    return padV * 2 + linePx(font, 1.25);
}

function estimateRemarksRowPx(s) {
    const font = Math.max(10, (s?.result_font_size ?? 14) - 2);
    return 6 + linePx(font, 1.35) + 4;
}

function estimateTestBlockPx(block, s) {
    const hideSingle = Boolean(s?.hide_single_param_title ?? 1);
    const isSingleParam = (block.params || []).length === 1;
    let h = 0;
    if (!hideSingle || !isSingleParam) {
        h += estimateTestTitleRowPx(s);
    }
    h += (block.params?.length || 0) * estimateParamRowPx(s);
    if (block.remarks) h += estimateRemarksRowPx(s);
    return h;
}

/**
 * Split one test across pages; remarks stay on the final chunk with the last params.
 */
function splitTestBlock(block, budgetPx, s) {
    const full = { ...block, continued: false };
    if (estimateTestBlockPx(full, s) <= budgetPx) {
        return [full];
    }

    const parts = [];
    let remaining = (block.params || []).slice();
    let partIndex = 0;

    if (!remaining.length && block.remarks) {
        return [{
            category: block.category,
            name: block.name,
            params: [],
            remarks: block.remarks,
            continued: false
        }];
    }

    while (remaining.length > 0) {
        partIndex += 1;
        const titlePx = estimateTestTitleRowPx(s);
        const remarksPx = block.remarks ? estimateRemarksRowPx(s) : 0;
        const chunk = [];
        let used = titlePx;

        while (remaining.length > 0) {
            const paramPx = estimateParamRowPx(s);
            const isLastParam = remaining.length === 1;
            const tailPx = isLastParam && block.remarks ? remarksPx : 0;

            if (chunk.length > 0 && used + paramPx + tailPx > budgetPx) {
                break;
            }
            if (chunk.length === 0 && used + paramPx + tailPx > budgetPx) {
                chunk.push(remaining.shift());
                used += paramPx;
                break;
            }

            chunk.push(remaining.shift());
            used += paramPx;
        }

        const isLast = remaining.length === 0;
        parts.push({
            category: block.category,
            name: block.name,
            params: chunk,
            remarks: isLast ? (block.remarks || '') : '',
            continued: partIndex > 1
        });
    }

    return parts.length ? parts : [full];
}

/**
 * Paginate tests within a single category (FIFO). Never mixes categories.
 */
function paginateCategoryBlocks(blocks, settings) {
    const layout = getPageLayout(settings);
    const chromePx = estimateCategoryChromePx(settings);
    const pageContentBudget = () => layout.bodyBudgetPx - chromePx;

    const pages = [];
    let current = [];
    let usedPx = 0;

    const flush = () => {
        if (current.length) {
            pages.push(current.slice());
            current = [];
            usedPx = 0;
        }
    };

    const budgetRemaining = () => pageContentBudget() - usedPx;

    for (const block of blocks) {
        let blockPx = estimateTestBlockPx(block, settings);

        if (blockPx <= budgetRemaining()) {
            current.push({ ...block, continued: block.continued || false });
            usedPx += blockPx;
            continue;
        }

        if (current.length) {
            flush();
            blockPx = estimateTestBlockPx(block, settings);
        }

        if (blockPx <= pageContentBudget()) {
            current.push({ ...block, continued: block.continued || false });
            usedPx = blockPx;
            continue;
        }

        const parts = splitTestBlock(block, pageContentBudget(), settings);
        parts.forEach((part, idx) => {
            if (idx > 0) flush();
            const partPx = estimateTestBlockPx(part, settings);
            current.push(part);
            usedPx = partPx;
            if (idx < parts.length - 1) flush();
        });
    }

    flush();
    return pages;
}

/**
 * Each category starts on a new page; overflow categories span multiple pages.
 */
function paginateByCategory(categories, settings) {
    const result = [];
    const catNames = Object.keys(categories).sort((a, b) => a.localeCompare(b));

    for (const cat of catNames) {
        const testMap = categories[cat];
        const blocks = Object.keys(testMap)
            .sort((a, b) => a.localeCompare(b))
            .map((name) => {
                const entry = testMap[name];
                const params = Array.isArray(entry) ? entry : (entry?.params || []);
                const remarks = Array.isArray(entry) ? '' : (entry?.remarks || '').trim();
                return { category: cat, name, params: params.slice(), remarks };
            });

        if (!blocks.length) continue;

        const catPages = paginateCategoryBlocks(blocks, settings);
        catPages.forEach((pageBlocks, idx) => {
            result.push({
                category: cat,
                blocks: pageBlocks,
                continued: idx > 0
            });
        });
    }

    return result;
}

/**
 * Pack ALL categories onto as few pages as possible.
 * FIRST category on a page costs full chrome (title row + thead).
 * SUBSEQUENT categories on the same page cost only a separator title row (no thead).
 * This produces ONE shared thead per page with category names as inline separators.
 */
/**
 * Combined category pagination decision hierarchy:
 * 1. If ALL tests fit on 1 single page -> Return 1 page combined.
 * 2. If tests exceed 1 page, try standard per-category pagination. If <= 2 pages -> Return standard 2-page category report.
 * 3. If standard per-category produces 3+ pages, try packing single-parameter tests into free space on Page 1 & 2 to fit within 2 pages.
 * 4. Otherwise, fallback to standard multi-page (3+ pages) category report.
 */
function paginateCombinedCategories(categories, settings) {
    const layout = getPageLayout(settings);
    const fullBudget = layout.bodyBudgetPx;
    const firstCatCost = estimateCategoryChromePx(settings);

    // Collect all test blocks across all categories
    const catNames = Object.keys(categories).sort((a, b) => a.localeCompare(b));
    const allBlocks = [];
    for (const cat of catNames) {
        const testMap = categories[cat];
        const blocks = Object.keys(testMap)
            .sort((a, b) => a.localeCompare(b))
            .map((name) => {
                const entry = testMap[name];
                const params = Array.isArray(entry) ? entry : (entry?.params || []);
                const remarks = Array.isArray(entry) ? '' : (entry?.remarks || '').trim();
                return { category: cat, name, params: params.slice(), remarks };
            });
        allBlocks.push(...blocks);
    }

    if (!allBlocks.length) return [];

    // Calculate total height if all blocks were combined on 1 page
    let totalSinglePagePx = firstCatCost;
    for (const b of allBlocks) {
        totalSinglePagePx += estimateTestBlockPx(b, settings);
    }

    // Tier 1: If ALL tests fit on 1 single page -> Return 1 page combined!
    if (totalSinglePagePx <= fullBudget) {
        const multi = allBlocks.filter(b => (b.params || []).length > 1);
        const single = allBlocks.filter(b => (b.params || []).length === 1);
        multi.sort((a, b) => (b.params?.length || 0) - (a.params?.length || 0));
        single.sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name));

        const sortedSinglePageBlocks = [...multi, ...single];
        const pageCatMap = [];
        for (const b of sortedSinglePageBlocks) {
            let sec = pageCatMap.find(s => s.category === b.category);
            if (!sec) { sec = { category: b.category, blocks: [] }; pageCatMap.push(sec); }
            sec.blocks.push(b);
        }
        return [{
            sections: pageCatMap,
            blocks: sortedSinglePageBlocks,
            continued: false
        }];
    }

    // Tier 2: Try standard per-category pagination (each category gets its own page)
    const categoryPages = paginateByCategory(categories, settings);
    if (categoryPages.length <= 2) {
        return categoryPages;
    }

    // Tier 3: If standard category-wise produced 3+ pages, try packing single-parameter tests into free space on Page 1 & 2 to fit within 2 pages
    const twoPagePacked = tryTwoPagePacking(categories, settings);
    if (twoPagePacked && twoPagePacked.length <= 2) {
        return twoPagePacked;
    }

    // Tier 4: Fallback to standard multi-page (3+ pages) category-wise report
    return categoryPages;
}

/**
 * Try packing multi-parameter blocks intact + single-parameter blocks into free space across max 2 pages.
 */
function tryTwoPagePacking(categories, settings) {
    const layout = getPageLayout(settings);
    const fullBudget = layout.bodyBudgetPx;
    const firstCatCost = estimateCategoryChromePx(settings);

    const catNames = Object.keys(categories).sort((a, b) => a.localeCompare(b));
    const multiBlocks = [];
    const singleBlocks = [];

    for (const cat of catNames) {
        const testMap = categories[cat];
        const blocks = Object.keys(testMap)
            .sort((a, b) => a.localeCompare(b))
            .map((name) => {
                const entry = testMap[name];
                const params = Array.isArray(entry) ? entry : (entry?.params || []);
                const remarks = Array.isArray(entry) ? '' : (entry?.remarks || '').trim();
                return { category: cat, name, params: params.slice(), remarks };
            });
        for (const b of blocks) {
            if ((b.params || []).length > 1) {
                multiBlocks.push(b);
            } else {
                singleBlocks.push(b);
            }
        }
    }

    multiBlocks.sort((a, b) => (b.params?.length || 0) - (a.params?.length || 0));
    singleBlocks.sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name));

    const pages = [];
    let remMulti = multiBlocks.slice();
    let remSingle = singleBlocks.slice();

    for (let pageNum = 1; pageNum <= 2; pageNum++) {
        if (!remMulti.length && !remSingle.length) break;
        let pageBlocks = [];
        let usedPx = firstCatCost;

        // Add multi-parameter blocks that fit intact
        while (remMulti.length > 0) {
            const b = remMulti[0];
            const px = estimateTestBlockPx(b, settings);
            if (usedPx + px <= fullBudget) {
                pageBlocks.push(remMulti.shift());
                usedPx += px;
            } else {
                break;
            }
        }

        // Fill remaining space with single-parameter blocks
        while (remSingle.length > 0) {
            const b = remSingle[0];
            const px = estimateTestBlockPx(b, settings);
            if (usedPx + px <= fullBudget) {
                pageBlocks.push(remSingle.shift());
                usedPx += px;
            } else {
                break;
            }
        }

        if (pageBlocks.length > 0) {
            const pageCatMap = [];
            for (const b of pageBlocks) {
                let sec = pageCatMap.find(s => s.category === b.category);
                if (!sec) { sec = { category: b.category, blocks: [] }; pageCatMap.push(sec); }
                sec.blocks.push(b);
            }
            pages.push({
                sections: pageCatMap,
                blocks: pageBlocks,
                continued: false
            });
        }
    }

    if (remMulti.length === 0 && remSingle.length === 0) {
        return pages;
    }
    return null;
}

function buildLabPrintStyles(s) {
    const layout = getPageLayout(s);
    const pageSizeRule = resolvePageSizeRule(s);
    const top = layout.marginTopMm;
    const right = layout.marginRightMm;
    const bottom = layout.marginBottomMm;
    const left = layout.marginLeftMm;
    const cellV = s?.table_cell_padding_vertical ?? 4;
    const cellH = s?.table_cell_padding_horizontal ?? 12;
    const headV = s?.table_header_padding_vertical ?? 8;
    const groupTop = s?.group_padding_top ?? 8;

    return `
@page {
    size: ${pageSizeRule};
    margin: 0;
}
html {
    width: ${A4_WIDTH_MM}mm;
}
html, body {
    margin: 0; padding: 0; background: #fff;
    width: ${A4_WIDTH_MM}mm;
    color: ${s?.primary_color || '#111'};
    font-family: Arial, Helvetica, sans-serif;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.lab-print-body { margin: 0; padding: 0; width: ${A4_WIDTH_MM}mm; }
.report-page {
    box-sizing: border-box;
    width: ${A4_WIDTH_MM}mm;
    height: ${A4_HEIGHT_MM}mm;
    min-height: ${A4_HEIGHT_MM}mm;
    max-height: ${A4_HEIGHT_MM}mm;
    padding: ${top}mm ${right}mm ${bottom}mm ${left}mm;
    page-break-after: always;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
.report-page.last-page { page-break-after: auto; }
.page-header {
    flex: 0 0 auto;
    max-height: ${layout.headerPx}px;
    overflow: hidden;
}
.page-body {
    flex: 1 1 auto;
    min-height: 0;
    max-height: ${layout.bodyBudgetPx}px;
    overflow: hidden;
}
.page-footer {
    flex: 0 0 ${layout.footerPx}px;
    height: ${layout.footerPx}px;
    min-height: ${layout.footerPx}px;
    max-height: ${layout.footerPx}px;
    overflow: hidden;
    margin-top: auto;
    border-top: 1px solid #000;
    padding-top: ${s?.footer_padding_top ?? 20}px;
    box-sizing: border-box;
}
.patient-header-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    margin-bottom: ${s?.patient_info_bottom_margin ?? 6}px;
}
.info-box {
    border: 1.5px solid #222;
    border-radius: 14px;
    padding: 10px 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    background-color: #fff;
}
.category {
    margin-top: 0;
    padding-top: ${s?.category_padding_top ?? 6}px;
    border-top: ${s?.category_border_width ?? 2}px solid #111;
}
/* Category title as a <div> in per-category mode */
.category-title {
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
    font-size: ${s?.category_font_size ?? 18}px;
    margin: 0px 0 ${s?.category_padding_bottom ?? 4}px;
    padding: 0;
    color: #111;
    border: none;
}
/* Category title as a <td> separator row inside combined table */
.cat-sep-row td {
    font-weight: 800;
    letter-spacing: .08em;
    text-transform: uppercase;
    font-size: ${s?.category_font_size ?? 18}px;
    padding-top: ${s?.category_padding_top ?? 6}px;
    padding-bottom: ${s?.category_padding_bottom ?? 4}px;
    padding-left: 0;
    border-top: ${s?.category_border_width ?? 2}px solid #111;
    color: #111;
}
table { width: 100%; border-collapse: collapse; font-size: ${s?.test_name_font_size ?? 13.5}px; }
thead th {
    text-align: left; font-weight: bold;
    padding: ${headV}px 4px;
    border-top: 1.5px solid #000;
    border-bottom: 1.5px solid #000;
    border-left: none; border-right: none;
    background: #fff; color: #000;
    font-size: ${s?.test_name_font_size ?? 13}px;
}
thead th:first-child { padding-left: 4px; }
tbody td {
    padding: ${cellV}px 4px;
    vertical-align: top;
    border: none;
    line-height: 1.25;
    font-size: ${s?.result_font_size ?? 14}px;
}
tbody td:first-child { padding-left: 4px; }
.test-group {
    font-weight: 800;
    text-transform: uppercase;
    font-size: ${s?.group_font_size ?? 15}px;
    padding-top: ${groupTop}px;
    padding-bottom: ${s?.group_padding_bottom ?? 2}px;
    padding-left: 4px;
}
.result-col { width: 150px; white-space: nowrap; text-align: left; }
thead th.result-col { text-align: left; padding-left: 0px; }
tbody td.result-col { padding-left: 8px; }
.range-col { width: 200px; }
.test-block { page-break-inside: avoid; break-inside: avoid; }
tbody.test-block + tbody.test-block { border-top: 1px solid #e2e8f0; }
.test-remarks {
    padding: 4px ${cellH}px 6px;
    color: #b91c1c;
    font-weight: 600;
    font-size: ${Math.max(10, (s?.result_font_size ?? 14) - 2)}px;
    line-height: 1.35;
    border-top: 1px dashed #d1d5db;
}
.test-block { page-break-inside: avoid; break-inside: avoid; }
.footer {
    font-size: ${s?.footer_font_size ?? 11}px;
    font-weight: 700;
    text-align: center;
}
.footer-left {
    margin-top: 6px;
    font-size: ${s?.footer_font_size ?? 11}px;
    font-weight: 700;
}
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
@media print {
    @page { size: ${pageSizeRule} !important; margin: 0 !important; }
    html, body { width: ${A4_WIDTH_MM}mm !important; margin: 0 !important; padding: 0 !important; }
    .report-page {
        width: ${A4_WIDTH_MM}mm !important;
        height: ${A4_HEIGHT_MM}mm !important;
        min-height: ${A4_HEIGHT_MM}mm !important;
        max-height: ${A4_HEIGHT_MM}mm !important;
    }
}
`;
}

function buildLabPrintDocument(contentHtml, settings) {
    const styles = buildLabPrintStyles(settings);
    return `<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<title>Lab Report</title>
<style>${styles}</style>
</head>
<body><div class="lab-print-body">${contentHtml}</div></body></html>`;
}

function printLabReportInIframe(html) {
    let iframe = document.getElementById('lab-print-iframe');
    if (iframe) iframe.remove();
    iframe = document.createElement('iframe');
    iframe.id = 'lab-print-iframe';
    iframe.setAttribute('aria-hidden', 'true');
    iframe.style.cssText = `position:fixed;left:-9999px;top:0;width:${A4_WIDTH_MM}mm;height:${A4_HEIGHT_MM}mm;border:none;`;
    document.body.appendChild(iframe);

    const doc = iframe.contentDocument || iframe.contentWindow.document;
    doc.open();
    doc.write(html);
    doc.close();
    const win = iframe.contentWindow;
    win.focus();
    setTimeout(() => win.print(), 400);
}

function printLabReport(options) {
    const opts = options || {};
    const previewEl = opts.contentEl || document.getElementById('preview');
    const settings = opts.settings || null;
    if (!previewEl || !previewEl.innerHTML.trim()) return;

    const html = buildLabPrintDocument(previewEl.innerHTML, settings);
    printLabReportInIframe(html);
}

/**
 * Build a stable fingerprint string from a list of test names.
 * Used as the key for saved print layouts.
 */
function buildFingerprint(testNames) {
    if (!testNames || !testNames.length) return '';
    const sorted = [...testNames].map(n => (n || '').trim().toLowerCase()).sort();
    return sorted.join('|');
}

/**
 * Re-paginate using a saved page_map: { testName -> pageIndex (0-based) }.
 * Tests not in the map follow automatic placement at the end.
 * Returns pages in the same shape as paginateCombinedCategories.
 */
function applyManualPageOverrides(categories, settings, pageMap, testOrder) {
    if (!pageMap || !Object.keys(pageMap).length) {
        return paginateCombinedCategories(categories, settings);
    }

    // Collect all blocks
    const catNames = Object.keys(categories).sort((a, b) => a.localeCompare(b));
    const allBlocks = [];
    for (const cat of catNames) {
        const testMap = categories[cat];
        for (const name of Object.keys(testMap).sort((a, b) => a.localeCompare(b))) {
            const entry = testMap[name];
            const params = Array.isArray(entry) ? entry : (entry?.params || []);
            const remarks = Array.isArray(entry) ? '' : (entry?.remarks || '').trim();
            allBlocks.push({ category: cat, name, params: params.slice(), remarks });
        }
    }

    if (!allBlocks.length) return [];

    // Sort allBlocks according to testOrder if provided
    if (testOrder && Array.isArray(testOrder) && testOrder.length > 0) {
        const orderMap = {};
        testOrder.forEach((tName, idx) => {
            orderMap[(tName || '').trim().toLowerCase()] = idx;
        });
        allBlocks.sort((a, b) => {
            const ka = (a.name || '').trim().toLowerCase();
            const kb = (b.name || '').trim().toLowerCase();
            const idxA = ka in orderMap ? orderMap[ka] : 9999;
            const idxB = kb in orderMap ? orderMap[kb] : 9999;
            if (idxA !== idxB) return idxA - idxB;
            return ka.localeCompare(kb);
        });
    }

    // Normalise page_map keys to lowercase trimmed
    const normMap = {};
    for (const [k, v] of Object.entries(pageMap)) {
        normMap[(k || '').trim().toLowerCase()] = Number(v);
    }

    // Separate mapped vs unmapped blocks
    const buckets = {}; // pageIndex -> blocks[]
    const unmapped = [];
    for (const b of allBlocks) {
        const key = (b.name || '').trim().toLowerCase();
        if (key in normMap) {
            const pg = normMap[key];
            if (!buckets[pg]) buckets[pg] = [];
            buckets[pg].push(b);
        } else {
            unmapped.push(b);
        }
    }

    // Build pages from buckets, sorted by page index
    const pageIndices = Object.keys(buckets).map(Number).sort((a, b) => a - b);
    const pages = [];
    for (const pgIdx of pageIndices) {
        const pageBlocks = buckets[pgIdx];
        if (!pageBlocks || !pageBlocks.length) continue;
        const pageCatMap = [];
        for (const b of pageBlocks) {
            let sec = pageCatMap.find(s => s.category === b.category);
            if (!sec) { sec = { category: b.category, blocks: [] }; pageCatMap.push(sec); }
            sec.blocks.push(b);
        }
        pages.push({ sections: pageCatMap, blocks: pageBlocks, continued: false });
    }

    // Append unmapped blocks on a final extra page (or merge into last page if space)
    if (unmapped.length) {
        const layout = getPageLayout(settings);
        const firstCatCost = estimateCategoryChromePx(settings);
        const lastPage = pages.length ? pages[pages.length - 1] : null;
        let usedPx = lastPage ? firstCatCost + lastPage.blocks.reduce((s, b) => s + estimateTestBlockPx(b, settings), 0) : firstCatCost;
        const overflowBlocks = [];
        for (const b of unmapped) {
            const px = estimateTestBlockPx(b, settings);
            if (lastPage && usedPx + px <= layout.bodyBudgetPx) {
                lastPage.blocks.push(b);
                usedPx += px;
            } else {
                overflowBlocks.push(b);
            }
        }
        if (overflowBlocks.length) {
            const pageCatMap = [];
            for (const b of overflowBlocks) {
                let sec = pageCatMap.find(s => s.category === b.category);
                if (!sec) { sec = { category: b.category, blocks: [] }; pageCatMap.push(sec); }
                sec.blocks.push(b);
            }
            pages.push({ sections: pageCatMap, blocks: overflowBlocks, continued: false });
        }
    }

    return pages.length ? pages : paginateCombinedCategories(categories, settings);
}

window.LabPrintLayout = {
    getPageLayout,
    getFooterHeightPx,
    paginateByCategory,
    paginateCategoryBlocks,
    paginateCombinedCategories,
    applyManualPageOverrides,
    buildFingerprint,
};
