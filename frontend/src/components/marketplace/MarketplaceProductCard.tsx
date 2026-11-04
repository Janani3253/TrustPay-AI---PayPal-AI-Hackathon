import { useState } from 'react'
import { AlertCircle, ExternalLink, Plus } from 'lucide-react'
import type { MarketplaceProduct } from '../../types'

function specificationText(specifications: Record<string, unknown> | null | undefined): string {
  if (!specifications) return 'Not available'
  const entries = Object.entries(specifications)
    .filter(([, value]) => ['string', 'number', 'boolean'].includes(typeof value))
    .map(([key, value]) => `${key}: ${String(value)}`)
  return entries.length ? entries.join(' · ') : 'Not available'
}

export function MarketplaceProductCard({ product, onCompare, comparing, onAddToCart }: {
  product: MarketplaceProduct
  onCompare: (product: MarketplaceProduct) => void
  comparing: boolean
  onAddToCart?: () => Promise<void>
}) {
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState('')

  const add = async () => {
    if (!onAddToCart || adding) return
    setAdding(true)
    setError('')
    try {
      await onAddToCart()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The backend could not add this product to the cart.')
    } finally {
      setAdding(false)
    }
  }

  return (
    <article className="product-card marketplace-product-card">
      <div className="product-image-wrap">
        {product.image_url
          ? <img src={product.image_url} alt={product.title} loading="lazy" />
          : <div className="marketplace-image-missing"><AlertCircle size={20} />Image not available</div>}
        <span className="marketplace-source-badge">{product.provider}</span>
      </div>
      <div className="product-info">
        <div className="product-meta"><span>{product.category ?? 'Category not available'}</span><span className="rating">{product.rating == null ? 'Rating unavailable' : `★ ${product.rating}`}</span></div>
        <h3>{product.title}</h3>
        <p>{product.description || 'Description not available from this provider.'}</p>
        <div className="seller-line"><AlertCircle size={14} />Seller: {product.seller_name ?? 'Not provided by provider'}</div>
        <div className="seller-line"><AlertCircle size={14} />Seller verification: {product.seller_verified == null ? 'Not available' : product.seller_verified ? 'Provider-reported verified' : 'Not verified'}</div>
        <div className="marketplace-specs"><b>Specifications</b><span>{specificationText(product.specifications)}</span></div>
        <div className="product-price-row">
          <strong>{product.price == null || !product.currency ? 'Price not available' : `${product.currency} ${product.price.toFixed(2)}`}</strong>
          <span>{product.provider} · backend catalogue</span>
        </div>
        <div className="product-actions">
          <button type="button" className={`btn btn-outline btn-sm ${comparing ? 'compare-selected' : ''}`} onClick={() => onCompare(product)} aria-pressed={comparing}>
            {comparing ? 'Remove comparison' : 'Compare'}
          </button>
          {product.product_url && <a className="btn btn-outline btn-sm" href={product.product_url} target="_blank" rel="noreferrer">View provider <ExternalLink size={13} /></a>}
          {onAddToCart
            ? <button type="button" className="btn btn-primary btn-sm" onClick={() => void add()} disabled={adding}>{adding ? 'Adding…' : <><Plus size={14} />Add to cart</>}</button>
            : <span className="marketplace-cart-unavailable">Cart API does not support this provider yet</span>}
        </div>
        {error && <p className="form-error">{error}</p>}
      </div>
    </article>
  )
}
