// Render a tiered report source (see ../FORMAT.md) into a .docx for one tier.
// Usage: node build.js <source.md> <S|M|L> <out.docx>   (normally called by render.sh)
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Footer, PageNumber,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle, ImageRun, TableOfContents,
  LevelFormat, PageBreak, TabStopType,
} = require("docx");

const [srcPath, tier, outPath] = process.argv.slice(2);
const TIER_NAMES = { S: "Short edition", M: "Medium edition", L: "Long edition" };
const srcDir = path.dirname(srcPath);
const raw = fs.readFileSync(srcPath, "utf8").replace(/\r\n/g, "\n");

// ---------- front matter ----------
let meta = {}, body = raw;
const fm = raw.match(/^---\n([\s\S]*?)\n---\n/);
if (fm) {
  fm[1].split("\n").forEach((l) => { const m = l.match(/^(\w+):\s*(.*)$/); if (m) meta[m[1]] = m[2].trim(); });
  body = raw.slice(fm[0].length);
}

// ---------- tier filtering ----------
const keep = { S: ["S-only", "SM-only"], M: ["M", "SM-only"], L: ["M", "L"] }[tier];
const lines = body.split("\n");
const out = [];
let block = null, inCode = false;
for (const l of lines) {
  if (/^```/.test(l)) inCode = !inCode;
  const open = !inCode && l.match(/^:::\s*(S-only|SM-only|M|L)\s*$/);
  if (open) { if (block) throw new Error("nested tier block: " + l); block = open[1]; continue; }
  if (!inCode && /^:::\s*$/.test(l)) { if (!block) throw new Error("stray ::: close"); block = null; continue; }
  if (block === null || keep.includes(block)) out.push(l);
}
if (block) throw new Error("unclosed tier block " + block);

// ---------- inline markup ----------
const BODY_PT = 11, FONT = "Calibri", MONO = "Consolas";
function inline(text, base = {}) {
  const runs = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let i = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > i) runs.push(new TextRun({ text: text.slice(i, m.index), ...base }));
    const t = m[0];
    if (t.startsWith("**")) runs.push(new TextRun({ text: t.slice(2, -2), bold: true, ...base }));
    else if (t.startsWith("`")) runs.push(new TextRun({ text: t.slice(1, -1), font: MONO, size: (base.size || BODY_PT * 2) - 2, color: "8A2B2B", ...base, ...(base.color ? { color: base.color } : {}) }));
    else runs.push(new TextRun({ text: t.slice(1, -1), italics: true, ...base }));
    i = m.index + t.length;
  }
  if (i < text.length) runs.push(new TextRun({ text: text.slice(i), ...base }));
  return runs;
}

// ---------- diagrams ----------
const figDir = path.join(srcDir, "diagrams", "_png");
fs.mkdirSync(figDir, { recursive: true });
function renderDot(rel) {
  const dotPath = path.join(srcDir, rel);
  const png = path.join(figDir, path.basename(rel).replace(/\.dot$/, ".png"));
  if (!fs.existsSync(png) || fs.statSync(png).mtimeMs < fs.statSync(dotPath).mtimeMs)
    execFileSync("dot", ["-Tpng", "-Gdpi=220", dotPath, "-o", png]);
  const buf = fs.readFileSync(png);
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
  return { buf, w, h };
}

// ---------- body ----------
const CONTENT_W = 9360; // 6.5in in DXA
const children = [];
const counters = [0, 0, 0];
let figN = 0, tableN = 0;
const border = { style: BorderStyle.SINGLE, size: 4, color: "B8C2CF" };
const cellBorders = { top: border, bottom: border, left: border, right: border };

function flushPara(buf) {
  if (!buf.length) return;
  children.push(new Paragraph({ children: inline(buf.join(" ")), spacing: { after: 120, line: 276 } }));
  buf.length = 0;
}

function tableFrom(rows) {
  const parse = (r) => r.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
  const header = parse(rows[0]);
  const data = rows.slice(2).map(parse);
  const n = header.length;
  // width by content length, clamped
  const lens = header.map((h, i) => Math.max(h.length, ...data.map((r) => (r[i] || "").length)));
  const weights = lens.map((x) => Math.min(Math.max(x, 13), 60));
  const tot = weights.reduce((a, b) => a + b, 0);
  let widths = weights.map((w) => Math.floor((CONTENT_W * w) / tot));
  widths[n - 1] += CONTENT_W - widths.reduce((a, b) => a + b, 0);
  const mkRow = (cells, head) => new TableRow({
    tableHeader: head,
    cantSplit: true,
    children: cells.map((c, i) => new TableCell({
      width: { size: widths[i], type: WidthType.DXA },
      borders: cellBorders,
      shading: head ? { fill: "1F3A5F", type: ShadingType.CLEAR, color: "auto" } : undefined,
      margins: { top: 60, bottom: 60, left: 100, right: 100 },
      children: [new Paragraph({ children: inline(c || "", head ? { bold: true, color: "FFFFFF", size: 19 } : { size: 19 }) })],
    })),
  });
  tableN++;
  children.push(new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    rows: [mkRow(header, true), ...data.map((r) => mkRow(header.map((_, i) => r[i] || ""), false))],
  }));
  children.push(new Paragraph({ children: [], spacing: { after: 120 } }));
}

let para = [];
for (let i = 0; i < out.length; i++) {
  const l = out[i];
  if (/^```/.test(l)) {
    flushPara(para);
    const code = [];
    i++;
    while (i < out.length && !/^```/.test(out[i])) code.push(out[i++]);
    code.forEach((c, k) => children.push(new Paragraph({
      children: [new TextRun({ text: c.length ? c : " ", font: MONO, size: 17 })],
      shading: { fill: "F3F5F8", type: ShadingType.CLEAR, color: "auto" },
      spacing: { before: k === 0 ? 60 : 0, after: k === code.length - 1 ? 160 : 0, line: 240 },
      indent: { left: 144, right: 144 },
      keepLines: true, keepNext: k < code.length - 1,
    })));
    continue;
  }
  const h = l.match(/^(#{1,3})\s+(.*)$/);
  if (h) {
    flushPara(para);
    const lvl = h[1].length;
    counters[lvl - 1]++;
    for (let k = lvl; k < 3; k++) counters[k] = 0;
    const num = counters.slice(0, lvl).join(".");
    const heading = [HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3][lvl - 1];
    // no forced page break before H1 (keeps page counts honest)
    children.push(new Paragraph({ heading, children: [new TextRun({ text: `${num}  ${h[2]}` })], keepNext: true }));
    continue;
  }
  const fig = l.match(/^!\[(.*)\]\((.*)\)\s*$/);
  if (fig) {
    flushPara(para);
    const { buf, w, h: ht } = renderDot(fig[2]);
    let width = Math.min(624, (w / 220) * 96 * 0.9); // px at 96dpi, max 6.5in
    let height = (ht * width) / w;
    if (height > 500) { height = 500; width = (w * height) / ht; } // ~7.9in max height
    figN++;
    children.push(new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 120, after: 60 },
      children: [new ImageRun({ type: "png", data: buf, transformation: { width: Math.round(width), height: Math.round(height) },
        altText: { title: `Figure ${figN}`, description: fig[1], name: `fig${figN}` } })] }));
    children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
      children: [new TextRun({ text: `Figure ${figN}. `, bold: true, size: 18, color: "555555" }), ...inline(fig[1], { size: 18, color: "555555", italics: true })] }));
    continue;
  }
  if (/^\|/.test(l) && i + 1 < out.length && /^\|\s*:?-{2,}/.test(out[i + 1])) {
    flushPara(para);
    const rows = [];
    while (i < out.length && /^\|/.test(out[i])) rows.push(out[i++]);
    i--;
    tableFrom(rows);
    continue;
  }
  const bl = l.match(/^(\s*)[-*]\s+(.*)$/);
  if (bl) {
    flushPara(para);
    let text = bl[2];
    while (i + 1 < out.length && /^\s{2,}\S/.test(out[i + 1]) && !/^\s*[-*]\s+/.test(out[i + 1]) && !/^\s*\d+\.\s+/.test(out[i + 1])) text += " " + out[++i].trim();
    children.push(new Paragraph({ numbering: { reference: "bullets", level: bl[1].length >= 2 ? 1 : 0 }, children: inline(text), spacing: { after: 60, line: 264 } }));
    continue;
  }
  const nl = l.match(/^(\s*)\d+\.\s+(.*)$/);
  if (nl) {
    flushPara(para);
    let text = nl[2];
    while (i + 1 < out.length && /^\s{2,}\S/.test(out[i + 1]) && !/^\s*[-*]\s+/.test(out[i + 1]) && !/^\s*\d+\.\s+/.test(out[i + 1])) text += " " + out[++i].trim();
    children.push(new Paragraph({ numbering: { reference: "numbers", level: nl[1].length >= 2 ? 1 : 0, instance: listInstance(i) }, children: inline(text), spacing: { after: 60, line: 264 } }));
    continue;
  }
  if (/^>\s?/.test(l)) {
    flushPara(para);
    const q = [l.replace(/^>\s?/, "")];
    while (i + 1 < out.length && /^>\s?/.test(out[i + 1])) q.push(out[++i].replace(/^>\s?/, ""));
    children.push(new Paragraph({ children: inline(q.join(" ")), shading: { fill: "EAF1FB", type: ShadingType.CLEAR, color: "auto" },
      border: { left: { style: BorderStyle.SINGLE, size: 18, color: "2E6DB4", space: 8 } }, indent: { left: 200, right: 200 }, spacing: { before: 80, after: 160 } }));
    continue;
  }
  if (!l.trim()) { flushPara(para); continue; }
  para.push(l.trim());
}
flushPara(para);

// numbered-list instances: each contiguous run of numbered items restarts at 1
function listInstance(idx) {
  let j = idx;
  while (j > 0) {
    const p = out[j - 1];
    if (/^\d+\.\s+/.test(p) || /^\s{2,}\S/.test(p)) { j--; continue; }
    break;
  }
  return j + 1;
}

// ---------- title page ----------
const title = meta.title || "Report";
const short = meta.short_title || title;
const titlePage = [
  new Paragraph({ spacing: { before: 2400 }, children: [] }),
  new Paragraph({ children: [new TextRun({ text: short, size: 52, bold: true, color: "1F3A5F", font: FONT })], spacing: { after: 120 } }),
  new Paragraph({ children: [new TextRun({ text: title.replace(short, "").replace(/^\s*[—–-]\s*/, "") || "Architecture and Workflow Report", size: 32, color: "2E6DB4" })], spacing: { after: 360 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: "2E6DB4", space: 8 } } }),
  ...(meta.subtitle ? [new Paragraph({ children: inline(meta.subtitle, { size: 24, color: "333333" }), spacing: { after: 480 } })] : []),
  new Paragraph({ children: [new TextRun({ text: TIER_NAMES[tier], bold: true, size: 24, color: "8A2B2B" })], spacing: { after: 120 } }),
  ...(meta.repo ? [new Paragraph({ children: [new TextRun({ text: "Repository: ", bold: true, size: 20 }), new TextRun({ text: meta.repo, size: 20 })], spacing: { after: 60 } })] : []),
  ...(meta.commit ? [new Paragraph({ children: [new TextRun({ text: "Reviewed at commit: ", bold: true, size: 20 }), new TextRun({ text: meta.commit, size: 20, font: MONO })], spacing: { after: 60 } })] : []),
  new Paragraph({ children: [new TextRun({ text: "Report date: ", bold: true, size: 20 }), new TextRun({ text: meta.date || new Date().toISOString().slice(0, 10), size: 20 })], spacing: { after: 60 } }),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ children: [new TextRun({ text: "Contents", bold: true, size: 32, color: "1F3A5F" })], spacing: { after: 200 } }),
  new TableOfContents("Contents", { hyperlink: true, headingStyleRange: tier === "S" ? "1-1" : "1-2" }),
  new Paragraph({ children: [new PageBreak()] }),
];

const doc = new Document({
  creator: "Claude", title, description: `${short} — ${TIER_NAMES[tier]}`,
  features: { updateFields: false },
  styles: {
    default: { document: { run: { font: FONT, size: BODY_PT * 2 } } },
    paragraphStyles: [
      { id: "FooterMuted", name: "Footer Muted", basedOn: "Normal", run: { size: 18, color: "8C8C8C", font: FONT } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, color: "1F3A5F", font: FONT }, paragraph: { spacing: { before: 240, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, color: "2E6DB4", font: FONT }, paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 23, bold: true, color: "333333", font: FONT }, paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 2 } },
    ],
  },
  numbering: { config: [
    { reference: "bullets", levels: [
      { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } },
      { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1000, hanging: 270 } } } } ] },
    { reference: "numbers", levels: [
      { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 320 } } } },
      { level: 1, format: LevelFormat.LOWER_LETTER, text: "%2)", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1000, hanging: 320 } } } } ] },
  ] },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, bottom: 1300, left: 1440, right: 1440, footer: 600 } }, titlePage: true },
    footers: {
      first: new Footer({ children: [new Paragraph({ children: [] })] }),
      default: new Footer({ children: [new Paragraph({ style: "FooterMuted", alignment: AlignmentType.CENTER, children: [
        new TextRun({ text: `${short}  |  Page `, size: 18, color: "8C8C8C" }),
        new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "8C8C8C" }),
        new TextRun({ text: " of ", size: 18, color: "8C8C8C" }),
        new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 18, color: "8C8C8C" }),
      ] })] }),
    },
    children: [...titlePage, ...children],
  }],
});

Packer.toBuffer(doc).then((b) => { fs.writeFileSync(outPath, b); console.log(`wrote ${outPath} (figures ${figN}, tables ${tableN})`); });
