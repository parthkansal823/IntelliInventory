/** Billing helpers: live bill preview (same maths as the server), WhatsApp texts, UPI links and printable invoices. */
import QRCode from 'qrcode'
import type { BusinessProfile, CustomerDue, InvoiceDetail } from './types'
import { money } from './utils'

export interface DraftLine { product_id: number; sku: string; name: string; quantity: number; unit_price: number; discount_pct: number; gst_rate: number; stock: number }

export interface BillPreview {
  subtotal: number
  discount: number
  taxable: number
  cgst: number
  sgst: number
  igst: number
  tax: number
  roundOff: number
  total: number
  lines: { taxable: number; tax: number; total: number }[]
}

const r2 = (n: number) => Math.round(n * 100) / 100

/** Mirrors app.services.billing.create_invoice so the total on screen is exactly what gets saved. */
export function previewBill(lines: DraftLine[], opts: { inclusive: boolean; interstate: boolean; exportSale: boolean; gstOn: boolean }): BillPreview {
  let subtotal = 0
  let discount = 0
  let taxable = 0
  let tax = 0
  const out = lines.map((l) => {
    const rate = opts.gstOn ? l.gst_rate : 0
    const gross = l.unit_price * l.quantity
    const net = gross * (1 - l.discount_pct / 100)
    const t = r2(opts.inclusive ? net / (1 + rate / 100) : net)
    const x = opts.exportSale ? 0 : r2((t * rate) / 100)
    subtotal += gross
    discount += gross - net
    taxable += t
    tax += x
    return { taxable: t, tax: x, total: r2(t + x) }
  })
  const exact = taxable + tax
  const total = Math.round(exact)
  const taxR = r2(tax)
  const cgst = opts.interstate ? 0 : r2(taxR / 2)
  return {
    subtotal: r2(subtotal),
    discount: r2(discount),
    taxable: r2(taxable),
    cgst,
    sgst: opts.interstate ? 0 : r2(taxR - cgst),
    igst: opts.interstate ? taxR : 0,
    tax: taxR,
    roundOff: r2(total - exact),
    total,
    lines: out,
  }
}

/** Standard UPI deep link - every UPI app can pay it. Free, no payment gateway. */
export function upiLink(upiId: string, payee: string, amount: number, note: string): string {
  const q = new URLSearchParams({ pa: upiId, pn: payee.slice(0, 50), am: amount.toFixed(2), cu: 'INR', tn: note.slice(0, 80) })
  return `upi://pay?${q.toString().replace(/\+/g, '%20')}`
}

export const qrDataUrl = (text: string, width = 220) => QRCode.toDataURL(text, { width, margin: 1 })

export function invoiceWhatsApp(inv: InvoiceDetail): string {
  const items = inv.lines.map((l) => `• ${l.name} × ${l.quantity} = ${money(l.total)}`).join('\n')
  const due = inv.balance > 0 ? `\nBalance due: *${money(inv.balance)}*${inv.seller.upi_id ? `\nPay by UPI: ${inv.seller.upi_id}` : ''}` : '\nPaid in full ✅'
  return `*${inv.seller.name}*\n${inv.title} ${inv.number}\n${new Date(inv.created_at).toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata' })}\n\n${items}\n\nTotal: *${money(inv.total)}*${due}\n\nDhanyavaad! 🙏`
}

export function duesReminder(due: CustomerDue, shop: BusinessProfile): string {
  const bills = due.invoices.map((i) => `• ${i.number}: ${money(i.balance)}`).join('\n')
  return `Namaste ${due.name} ji 🙏\n\n${shop.name} mein aapka *${money(due.balance)}* baaki hai:\n${bills}\n${shop.upi_id ? `\nUPI se bhej sakte hain: ${shop.upi_id}` : ''}\n\nDhanyavaad!`
}

const esc = (s: string | null | undefined) => (s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!)

/** Opens a print-ready invoice (A4 or 80 mm thermal roll) in a new window. */
export async function printInvoice(inv: InvoiceDetail, size: 'a4' | 'thermal' = 'a4') {
  const w = window.open('', '_blank', 'width=900,height=1000')
  if (!w) return
  const s = inv.seller
  const qr = inv.upi_link ? await qrDataUrl(inv.upi_link, size === 'thermal' ? 160 : 140) : null
  const date = new Date(inv.created_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' })
  const gst = inv.kind !== 'bill_of_supply'
  const rows = inv.lines
    .map((l, i) =>
      size === 'thermal'
        ? `<tr><td>${esc(l.name)}<div class="m">${l.quantity} × ${money(l.unit_price)}${l.discount_pct ? ` − ${l.discount_pct}%` : ''}${gst && l.gst_rate ? ` · GST ${l.gst_rate}%` : ''}</div></td><td class="r">${money(l.total)}</td></tr>`
        : `<tr><td>${i + 1}</td><td>${esc(l.name)}${gst && l.hsn_code ? `<div class="m">HSN ${esc(l.hsn_code)}</div>` : ''}</td><td class="r">${l.quantity}</td><td class="r">${money(l.unit_price)}</td><td class="r">${l.discount_pct ? `${l.discount_pct}%` : '—'}</td>${gst ? `<td class="r">${l.gst_rate}%</td>` : ''}<td class="r">${money(l.total)}</td></tr>`,
    )
    .join('')
  const head =
    size === 'thermal'
      ? '<tr><th>Item</th><th class="r">Amount</th></tr>'
      : `<tr><th>#</th><th>Item</th><th class="r">Qty</th><th class="r">Rate</th><th class="r">Disc</th>${gst ? '<th class="r">GST</th>' : ''}<th class="r">Amount</th></tr>`
  const taxRows = gst
    ? inv.interstate
      ? `<tr><td>IGST</td><td class="r">${money(inv.igst)}</td></tr>`
      : `<tr><td>CGST</td><td class="r">${money(inv.cgst)}</td></tr><tr><td>SGST</td><td class="r">${money(inv.sgst)}</td></tr>`
    : ''
  const hsn =
    size === 'a4' && gst && inv.tax > 0
      ? `<table class="t hsn"><thead><tr><th>HSN</th><th class="r">Rate</th><th class="r">Taxable</th>${inv.interstate ? '<th class="r">IGST</th>' : '<th class="r">CGST</th><th class="r">SGST</th>'}</tr></thead><tbody>${inv.hsn_summary
          .map((h) => `<tr><td>${esc(h.hsn_code) || '—'}</td><td class="r">${h.gst_rate}%</td><td class="r">${money(h.taxable)}</td>${inv.interstate ? `<td class="r">${money(h.igst)}</td>` : `<td class="r">${money(h.cgst)}</td><td class="r">${money(h.sgst)}</td>`}</tr>`)
          .join('')}</tbody></table>`
      : ''
  const css =
    size === 'thermal'
      ? `@page{size:80mm auto;margin:3mm}body{width:74mm;font:12px/1.35 ui-monospace,monospace}h1{font-size:15px;text-align:center}.c{text-align:center}.t td,.t th{padding:3px 0;border-bottom:1px dashed #999;vertical-align:top}.t td.r{padding-left:6px;white-space:nowrap}`
      : `@page{size:A4;margin:14mm}body{font:13px/1.45 system-ui,sans-serif}h1{font-size:20px}.t td,.t th{padding:6px 8px;border-bottom:1px solid #ddd}.t th{background:#f4f4f5}.head{display:flex;justify-content:space-between;gap:24px}.box{border:1px solid #ddd;border-radius:8px;padding:10px 12px}`
  w.document.write(`<!doctype html><html><head><title>${esc(inv.number)}</title><style>
    *{box-sizing:border-box}body{margin:0;color:#111}h1{margin:0 0 2px}.m{color:#666;font-size:11px}.r,.t th.r,.t td.r{text-align:right}.t{width:100%;border-collapse:collapse;margin:10px 0}.t th{text-align:left}
    .tot td{padding:2px 0}.grand td{font-weight:700;font-size:1.15em;border-top:1px solid #111;padding-top:4px}.words{margin:6px 0;font-style:italic}.foot{margin-top:18px;display:flex;justify-content:space-between;align-items:flex-end;gap:16px}
    .badge{display:inline-block;border:1px solid #111;border-radius:4px;padding:1px 6px;font-size:11px;letter-spacing:.04em;text-transform:uppercase}.hsn{font-size:11px}${css}
  </style></head><body>
  <div class="${size === 'thermal' ? 'c' : 'head'}">
    <div><h1>${esc(s.name)}</h1><div class="m">${esc(s.address)}</div><div class="m">${[s.phone, s.email].filter(Boolean).map(esc).join(' · ')}</div>${s.gstin ? `<div class="m">GSTIN: <b>${esc(s.gstin)}</b> · ${esc(s.state)}</div>` : ''}</div>
    <div${size === 'a4' ? ' class="r"' : ''}><div class="badge">${esc(inv.title)}</div><div><b>${esc(inv.number)}</b></div><div class="m">${date}</div>${inv.status === 'cancelled' ? '<div class="badge">Cancelled</div>' : ''}</div>
  </div>
  <div class="${size === 'a4' ? 'box' : ''}" style="margin-top:10px"><div class="m">Bill to</div><b>${esc(inv.customer_name)}</b>${inv.customer_phone ? ` · ${esc(inv.customer_phone)}` : ''}${inv.customer_address ? `<div class="m">${esc(inv.customer_address)}</div>` : ''}${inv.customer_gstin ? `<div class="m">GSTIN: ${esc(inv.customer_gstin)}</div>` : ''}${gst && inv.place_of_supply ? `<div class="m">Place of supply: ${esc(inv.place_of_supply)}</div>` : ''}</div>
  <table class="t"><thead>${head}</thead><tbody>${rows}</tbody></table>
  <table class="tot" style="margin-left:auto;min-width:${size === 'a4' ? '260px' : '100%'}">
    ${inv.discount ? `<tr><td>Discount</td><td class="r">−${money(inv.discount)}</td></tr>` : ''}
    <tr><td>Taxable value</td><td class="r">${money(inv.taxable)}</td></tr>${taxRows}
    ${inv.round_off ? `<tr><td>Round off</td><td class="r">${inv.round_off > 0 ? '+' : ''}${inv.round_off.toFixed(2)}</td></tr>` : ''}
    <tr class="grand"><td>Total</td><td class="r">${money(inv.total)}</td></tr>
    ${inv.amount_paid && inv.balance ? `<tr><td>Paid</td><td class="r">${money(inv.amount_paid)}</td></tr><tr><td><b>Balance due</b></td><td class="r"><b>${money(inv.balance)}</b></td></tr>` : ''}
  </table>
  <div class="words">${esc(inv.amount_in_words)}</div>
  ${hsn}
  ${inv.notes.map((n) => `<div class="m">${esc(n)}</div>`).join('')}
  <div class="foot"><div>${qr ? `<img src="${qr}" alt="UPI QR"/><div class="m">Scan with any UPI app to pay ${money(inv.balance)}</div>` : ''}<div class="m" style="margin-top:6px">${esc(s.terms)}</div></div>${size === 'a4' ? `<div class="r"><div style="height:40px"></div><div class="m">For ${esc(s.name)}</div><div>Authorised signatory</div></div>` : ''}</div>
  ${size === 'thermal' ? '<p class="c">Dhanyavaad! Phir padhariye 🙏</p>' : ''}
  <script>window.onload=()=>{window.print()}</script></body></html>`)
  w.document.close()
}
