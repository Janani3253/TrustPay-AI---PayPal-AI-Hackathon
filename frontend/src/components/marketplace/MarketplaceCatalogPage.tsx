import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Search, ShoppingCart } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useApp } from '../../context/AppContext'
import { addCartProduct, getBackendError } from '../../services/backendService'
import { getProduct, getProductCategories, getProducts, productDataSource } from '../../services/productService'
import { getMarketplaceProviders, mapDemoProducts, searchMarketplaceProducts } from '../../services/marketplaceService'
import type { MarketplaceProduct, MarketplaceProvider, MarketplaceProviderName, ProductCategory } from '../../types'
import { MarketplaceProductCard } from './MarketplaceProductCard'
import { MarketplaceProviderStatus } from './MarketplaceProviderStatus'
import { ProductComparison } from './ProductComparison'

const providerLabels: Record<MarketplaceProviderName, string> = {
  AMAZON: 'Amazon India',
  FLIPKART: 'Flipkart India',
  MYNTRA: 'Myntra India',
  DEMO: 'DummyJSON Demo Store',
}

export function MarketplaceCatalogPage() {
  const { addToCart } = useApp()
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [maximumPrice, setMaximumPrice] = useState('')
  const [minimumRating, setMinimumRating] = useState('')
  const [sort, setSort] = useState('Recommended')
  const [selectedProvider, setSelectedProvider] = useState<'ALL' | MarketplaceProviderName>('ALL')
  const [products, setProducts] = useState<MarketplaceProduct[]>([])
  const [providers, setProviders] = useState<MarketplaceProvider[]>([])
  const [categories, setCategories] = useState<ProductCategory[]>([])
  const [providerLoading, setProviderLoading] = useState(true)
  const [providerError, setProviderError] = useState('')
  const [providerRetry, setProviderRetry] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [visibleCount, setVisibleCount] = useState(24)
  const [comparison, setComparison] = useState<MarketplaceProduct[]>([])
  const requestSequence = useRef(0)

  useEffect(() => {
    let active = true
    getMarketplaceProviders()
      .then((result) => { if (active) setProviders(result) })
      .catch((cause: unknown) => {
        console.warn('Marketplace provider status is not available from this backend.', cause)
        if (active) setProviderError('Provider status could not be loaded from the backend; marketplace connectivity is unknown.')
      })
      .finally(() => { if (active) setProviderLoading(false) })
    getProductCategories()
      .then((result) => { if (active) setCategories(result) })
      .catch((cause: unknown) => console.warn('Catalogue categories are unavailable.', cause))
    return () => { active = false }
  }, [providerRetry])

  useEffect(() => {
    let active = true
    if (selectedProvider === 'ALL' && providerLoading) {
      return () => { active = false }
    }
    const requestId = ++requestSequence.current
    const timer = window.setTimeout(async () => {
      setLoading(true)
      setError('')
      try {
        let results: MarketplaceProduct[]
        if (selectedProvider === 'DEMO') {
          results = await searchMarketplaceProducts(query, 'DEMO', category || undefined)
        } else if (selectedProvider !== 'ALL') {
          const provider = providers.find((item) => item.name === selectedProvider)
          if (!provider) throw new Error(`${providerLabels[selectedProvider]} status has not been reported by the backend.`)
          if (provider.status !== 'CONNECTED' || !provider.connected) {
            throw new Error(provider.message ?? `${providerLabels[selectedProvider]} is ${provider.status.toLowerCase().replaceAll('_', ' ')}.`)
          }
          results = await searchMarketplaceProducts(query, selectedProvider, category || undefined)
        } else if (providerError) {
          results = mapDemoProducts(await getProducts({ query, category }))
        } else {
          results = await searchMarketplaceProducts(query, undefined, category || undefined)
        }
        if (active && requestSequence.current === requestId) setProducts(results)
      } catch (cause) {
        if (active && requestSequence.current === requestId) {
          setProducts([])
          setError(getBackendError(cause, 'The backend could not load catalogue products.'))
        }
      } finally {
        if (active && requestSequence.current === requestId) setLoading(false)
      }
    }, query ? 300 : 0)
    return () => { active = false; window.clearTimeout(timer) }
  }, [query, category, selectedProvider, providers, providerLoading, providerError, retry])

  const visibleProducts = useMemo(() => products
    .filter((product) => !maximumPrice || product.price != null && product.price <= Number(maximumPrice))
    .filter((product) => !minimumRating || product.rating != null && product.rating >= Number(minimumRating))
    .sort((left, right) => {
      if (sort === 'Price: low to high') return (left.price ?? Number.POSITIVE_INFINITY) - (right.price ?? Number.POSITIVE_INFINITY)
      if (sort === 'Price: high to low') return (right.price ?? Number.NEGATIVE_INFINITY) - (left.price ?? Number.NEGATIVE_INFINITY)
      if (sort === 'Rating: high to low') return (right.rating ?? Number.NEGATIVE_INFINITY) - (left.rating ?? Number.NEGATIVE_INFINITY)
      return 0
    }), [products, maximumPrice, minimumRating, sort])

  const toggleComparison = (product: MarketplaceProduct) => setComparison((current) => {
    const found = current.some((item) => item.id === product.id && item.provider === product.provider)
    if (found) return current.filter((item) => item.id !== product.id || item.provider !== product.provider)
    return current.length < 3 ? [...current, product] : current
  })

  const addDemoProduct = async (marketplaceProduct: MarketplaceProduct) => {
    const product = await getProduct(marketplaceProduct.external_product_id)
    await addCartProduct(product.id)
    addToCart(product)
  }

  return (
    <>
      <div className="page-title-row">
        <div><div className="eyebrow">MARKETPLACE CATALOGUE</div><h1>Find your next favorite</h1><p>Marketplace availability and products are provided by the backend; unavailable providers never show sample items.</p></div>
        <Link className="btn btn-outline" to="/cart"><ShoppingCart size={16} /> View cart</Link>
      </div>
      <MarketplaceProviderStatus
        providers={providers}
        loading={providerLoading}
        error={providerError}
        selected={selectedProvider}
        onSelect={(provider) => { setSelectedProvider(provider); setCategory(''); setProducts([]); setVisibleCount(24); setError('') }}
        onRetry={() => { setProviderError(''); setProviderLoading(true); setProviderRetry((value) => value + 1) }}
      />
      <div className="api-source-strip"><span className="api-live-dot" />{selectedProvider === 'ALL' ? providerError ? 'Legacy DummyJSON results only · provider API unavailable' : 'All backend catalogue results' : providerLabels[selectedProvider]}<span>{selectedProvider === 'DEMO' || selectedProvider === 'ALL' ? productDataSource : 'Marketplace API results · provided by backend'}</span></div>
      <div className="catalog-toolbar marketplace-catalog-toolbar">
        <label className="search-field"><Search size={17} /><input placeholder="Search products via backend API…" value={query} onChange={(event) => { setQuery(event.target.value); setVisibleCount(24) }} /></label>
        <select aria-label="Filter by product category" value={category} onChange={(event) => setCategory(event.target.value)}><option value="">All categories</option>{categories.map((item) => <option value={item.slug} key={item.slug}>{item.name}</option>)}</select>
        <label className="price-filter">Max price<input aria-label="Maximum product price" type="number" min="0" placeholder="Any" value={maximumPrice} onChange={(event) => setMaximumPrice(event.target.value)} /></label>
        <select aria-label="Minimum product rating" value={minimumRating} onChange={(event) => setMinimumRating(event.target.value)}><option value="">Any rating</option><option value="3">3+ rating</option><option value="4">4+ rating</option></select>
        <select aria-label="Sort products" value={sort} onChange={(event) => setSort(event.target.value)}><option>Recommended</option><option>Price: low to high</option><option>Price: high to low</option><option>Rating: high to low</option></select>
      </div>
      {loading ? <div className="panel api-state"><span className="spinner" /><p>Loading results from the selected backend provider…</p></div>
        : error ? <div className="panel api-error"><AlertCircle size={25} /><h2>Marketplace results unavailable</h2><p>{error}</p><button className="btn btn-primary" onClick={() => setRetry((value) => value + 1)}>Retry product request</button></div>
          : visibleProducts.length ? <>
            <div className="api-results-label">{visibleProducts.length} product{visibleProducts.length === 1 ? '' : 's'} returned by backend</div>
            <div className="product-grid marketplace-product-grid">{visibleProducts.slice(0, visibleCount).map((product) => (
            <MarketplaceProductCard
              key={`${product.provider}:${product.id}`}
              product={product}
              comparing={comparison.some((item) => item.id === product.id && item.provider === product.provider)}
              onCompare={toggleComparison}
              onAddToCart={product.provider === 'DEMO' ? () => addDemoProduct(product) : undefined}
            />
            ))}</div>
            {visibleCount < visibleProducts.length && <div className="load-more-wrap"><button className="btn btn-outline" onClick={() => setVisibleCount((count) => count + 24)}>Load more products</button></div>}
          </>
            : <div className="empty-state"><Search size={28} /><h3>No products available</h3><p>{selectedProvider === 'ALL' ? 'The backend returned no catalogue results.' : 'The selected provider has no connected product results. No demo items are substituted.'}</p></div>}
      {comparison.length > 0 && <ProductComparison
        products={comparison}
        onRemove={(removed) => setComparison((current) => current.filter((product) => product.id !== removed.id || product.provider !== removed.provider))}
        onClear={() => setComparison([])}
      />}
    </>
  )
}
