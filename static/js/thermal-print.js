/**
 * Print thermal receipt via a hidden iframe (same approach as lab-print.js)
 * so the browser does not add default headers/footers and no pop-up is needed.
 */
function printThermalReceiptInIframe(html, pageWidth) {
    let iframe = document.getElementById('thermal-print-iframe');
    if (iframe) iframe.remove();
    iframe = document.createElement('iframe');
    iframe.id = 'thermal-print-iframe';
    iframe.setAttribute('aria-hidden', 'true');
    iframe.style.cssText = `position:fixed;left:-9999px;top:0;width:${pageWidth};height:auto;border:none;`;
    document.body.appendChild(iframe);

    const doc = iframe.contentDocument || iframe.contentWindow.document;
    doc.open();
    doc.write(html);
    doc.close();
    const win = iframe.contentWindow;
    win.focus();
    setTimeout(() => win.print(), 300);
}

function printThermalReceipt(rootEl) {
    const paper = rootEl && (rootEl.querySelector('.invoice-paper') || rootEl);
    if (!paper) {
        window.print();
        return;
    }

    let inner = paper.innerHTML;
    inner = inner.replace(/<button[^>]*btn-print-invoice[^>]*>[\s\S]*?<\/button>/gi, '');
    inner = inner.replace(/href\s*=\s*["']about:[^"']*["']/gi, 'href="#"');

    const width =
        (getComputedStyle(document.documentElement).getPropertyValue('--invoice-width') || '3in').trim() ||
        '3in';
    const pageWidth = /^(?:\d+(?:\.\d+)?)(?:in|mm|cm)$/.test(width) ? width : '3in';

    const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Receipt</title>
<style>
@page {
    margin: 0mm;
    size: ${pageWidth} auto;
}
html, body {
    margin: 0;
    padding: 0;
    width: ${pageWidth};
    background: #fff;
    color: #000;
    font-family: Inter, Arial, sans-serif;
    line-height: 1.4;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}
.invoice-paper {
    width: ${pageWidth};
    box-sizing: border-box;
    padding: 10px;
    margin: 0;
}
.invoice-header { text-align: center; margin-bottom: 5px; padding-top: 8px; }
.invoice-logo { width: 100px; height: auto; margin-bottom: 8px; }
.hospital-name-text {
    font-weight: 700; font-size: 13px; text-transform: uppercase;
    margin-bottom: 10px; border: 1px solid #ccc; padding: 4px 6px;
}
.title-banner, .desc-title {
    background: #000; color: #fff; text-align: center; font-weight: 700;
    -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.title-banner { padding: 6px 0; font-size: 14px; margin-bottom: 12px; text-transform: uppercase; }
.desc-title { padding: 5px; font-size: 12px; text-transform: uppercase; }
.invoice-info { margin-bottom: 12px; display: flex; flex-direction: column; gap: 6px; }
.info-row-centered { display: flex; font-size: 10px; }
.info-label-text { font-weight: 700; width: 95px; flex-shrink: 0; }
.info-value-text { flex: 1; word-break: break-word; }
.online-report-box {
    border-top: 1px dashed #999; border-bottom: 1px dashed #999;
    padding: 8px 0; margin-bottom: 12px; font-size: 9px;
}
.qr-row { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.qr-row img { width: 72px; height: 72px; border: 1px solid #ddd; }
.qr-scan-text { font-weight: 700; font-size: 10px; text-transform: uppercase; }
.desc-box { border: 2px solid #000; margin-bottom: 16px; }
.item-row {
    padding: 8px; border-bottom: 1px dashed #000;
    font-size: 11px; font-weight: 600; text-align: center;
}
.item-row:last-child { border-bottom: none; }
.invoice-footer { text-align: center; margin-top: 10px; border-top: 1px solid #000; padding-top: 8px; }
.wish-text { font-weight: 700; font-size: 12px; text-decoration: underline; }
.dev-credit { font-size: 9px; color: #666; }
.dev-credit a { color: #666; text-decoration: none; }
</style>
</head>
<body>
<div class="invoice-paper">${inner}</div>
</body>
</html>`;

    printThermalReceiptInIframe(html, pageWidth);
}
