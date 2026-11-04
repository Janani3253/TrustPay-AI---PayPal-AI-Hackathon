import { X } from 'lucide-react'
import type { MarketplaceProduct } from '../../types'

function display(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (value === null || value === undefined) return 'Not available'
  if (Array.isArray(value)) return value.length ? value.map(display).join(', ') : 'Not available'
  if (typeof value === 'object') {
    const entries = Object.entries(value)
      .filter(([, entry]) => ['string', 'number', 'boolean'].includes(typeof entry))
      .map(([key, entry]) => `${key}: ${String(entry)}`)
    return entries.length ? entries.join(' · ') : 'Not available'
  }
  return 'Not available'
}

export function ProductComparison({ products, onRemove, onClear }: {
  products: MarketplaceProduct[]
  onRemove: (product: MarketplaceProduct) => void
  onClear: () => void
}) {
  if (!products.length) return null
  const rows: Array<[string, (product: MarketplaceProduct) => string]> = [
    ['Marketplace', (product) => product.provider],
    ['Title', (product) => product.title],
    ['Price', (product) => product.price == null || !product.currency ? 'Not available' : `${product.currency} ${product.price.toFixed(2)}`],
    ['Brand', (product) => display(product.specifications?.brand)],
    ['Category', (product) => display(product.category)],
    ['Rating', (product) => display(product.rating)],
    ['Seller', (product) => display(product.seller_name)],
    ['Seller verification', (product) => product.seller_verified == null ? 'Not available' : product.seller_verified ? 'Verified by provider' : 'Not verified'],
    ['Specifications', (product) => display(product.specifications)],
    ['Product URL', (product) => display(product.product_url)],
    ['Provider product ID', (product) => product.external_product_id],
  ]
  return (
    <section className="panel product-comparison">
      <div className="panel-heading">
        <div><h2>Compare selected products</h2><p>Items are shown as separate provider listings; similar titles do not imply identical products.</p></div>
        <button type="button" className="btn btn-outline btn-sm" onClick={onClear}>Clear comparison</button>
      </div>
      <div className="comparison-scroll">
        <table>
          <thead><tr><th>Attribute</th>{products.map((product) => <th key={`${product.provider}-${product.id}`}><span>{product.provider}</span><button type="button" className="icon-btn" onClick={() => onRemove(product)} aria-label={`Remove ${product.title} from comparison`}><X size={15} /></button></th>)}</tr></thead>
          <tbody>{rows.map(([label, getValue]) => <tr key={label}><th>{label}</th>{products.map((product) => <td key={`${product.provider}-${product.id}-${label}`}>{getValue(product)}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </section>
  )
}
