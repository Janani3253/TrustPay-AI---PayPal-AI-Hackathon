import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowRight, BadgeCheck, Check,
  CheckCircle2, CircleAlert, Clock3,
  Download, Eye, EyeOff, FileCheck2, Fingerprint, Heart, LockKeyhole,
  PackageCheck, Plus, Search, Shield, ShieldAlert, ShieldCheck,
  ShoppingBag, ShoppingCart, Sparkles, Trash2, X,
} from 'lucide-react'
import { Brand } from '../components/common/Brand'
import { MarketplaceCatalogPage } from '../components/marketplace/MarketplaceCatalogPage'
import { useApp } from '../context/AppContext'
import { formatMoney } from '../mock/data'
import { login, register } from '../services/authService'
import { extractIntent } from '../services/intentService'
import { getProduct, getProductCategories, getProducts, mapProduct, productDataSource } from '../services/productService'
import { calculateCartTotals } from '../services/cartService'
import { getOrderFingerprint } from '../utils/order'
import {
  addCartProduct, approveBackendOrder, clearBackendCart, createBackendOrder,
  createPayPalOrder, capturePayPalOrder, getAuditEvents, getBackendError,
  getDashboardSummary, getPlatforms, removeCartProduct, searchRecommendations,
  updateCartProduct, verifyBackendAudit, verifyBackendOrder,
  type ShoppingPlatform,
} from '../services/backendService'
import type { AuditEvent, BackendVerificationCheck, Currency, Product, ProductCategory, ProductRecommendation, Transaction } from '../types'

function PageTitle({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: ReactNode }) {
  return <div className="page-title-row"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1>{description && <p>{description}</p>}</div>{action}</div>
}

function ButtonLink({ to, children, variant = 'primary', icon }: { to: string; children: ReactNode; variant?: string; icon?: ReactNode }) {
  return <Link className={`btn ${variant}`} to={to}>{children}{icon}</Link>
}

function ProductTile({ product, matched = false, matchPercent = '96%' }: { product: Product; matched?: boolean; matchPercent?: string }) {
  const { addToCart } = useApp()
  const [details, setDetails] = useState(false)
  const [detailProduct, setDetailProduct] = useState<Product | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [added, setAdded] = useState(false)
  const [addError, setAddError] = useState('')
  const [saved, setSaved] = useState(false)
  const loadDetails = async () => {
    setDetails(true)
    setDetailLoading(true)
    setDetailError('')
    try {
      setDetailProduct(await getProduct(product.id))
    } catch (error) {
      console.error('Could not load product details from Demo Product API.', error)
      setDetailError('Product details could not be loaded from Demo Product API.')
    } finally {
      setDetailLoading(false)
    }
  }
  const selectedProduct = detailProduct ?? product
  return (
    <article className="product-card">
      <div className="product-image-wrap"><img src={product.image} alt={product.name} onError={(event) => { event.currentTarget.src = 'https://placehold.co/800x500/eef2ff/334155?text=Product' }} />{matched && <span className="match-tag"><Sparkles size={12} /> {matchPercent} match</span>}<button className={`favorite-btn ${saved ? 'saved' : ''}`} aria-label={saved ? `Remove ${product.name} from saved products` : `Save ${product.name}`} aria-pressed={saved} onClick={() => setSaved(!saved)}><Heart size={17} fill={saved ? 'currentColor' : 'none'} /></button></div>
      <div className="product-info"><div className="product-meta"><span>{product.category}</span><span className="rating">★ {product.rating}</span></div><h3>{product.name}</h3><p>{product.description}</p><div className="seller-line"><CircleAlert size={14} />Seller: Not provided by Demo Product API</div><div className="product-price-row"><strong>{formatMoney(product.price, product.currency)}</strong><span>DummyJSON catalogue · API price</span></div><div className="product-actions"><button className="btn btn-outline btn-sm" onClick={() => void loadDetails()}>View details</button><button className="btn btn-primary btn-sm" onClick={async () => { setAddError(''); try { await addCartProduct(product.id); addToCart(product); setAdded(true); window.setTimeout(() => setAdded(false), 1800) } catch (error) { setAddError(getBackendError(error, 'Could not add this product to the backend cart.')) } }}>{added ? <><Check size={15} /> Added</> : <><Plus size={15} /> Add to cart</>}</button></div>{addError && <p className="form-error">{addError}</p>}</div>
      {details && <div className="modal-backdrop" role="presentation" onClick={() => setDetails(false)}><div className="modal-card" role="dialog" aria-modal="true" aria-label={`${product.name} details`} onClick={(event) => event.stopPropagation()}><button className="modal-close icon-btn" onClick={() => setDetails(false)} aria-label="Close"><X size={18} /></button>{detailLoading ? <div className="empty-message">Loading product details from backend…</div> : detailError ? <div className="form-error">{detailError}<button className="btn btn-outline btn-sm" onClick={() => void loadDetails()}>Retry</button></div> : <><img className="modal-product-image" src={selectedProduct.image} alt={selectedProduct.name} /><span className="eyebrow">BACKEND PRODUCT DETAILS</span><h2>{selectedProduct.name}</h2><p>{selectedProduct.description}</p><div className="spec-chips">{(selectedProduct.specifications.length ? selectedProduct.specifications : ['Specifications: Not available for verification']).map((spec) => <span key={spec}>{spec}</span>)}</div><div className="seller-line"><CircleAlert size={15} />Seller: Not provided by DummyJSON</div><strong className="modal-price">{formatMoney(selectedProduct.price, selectedProduct.currency)}</strong><button className="btn btn-primary btn-full" onClick={async () => { try { await addCartProduct(selectedProduct.id); addToCart(selectedProduct); setDetails(false) } catch (error) { setDetailError(getBackendError(error, 'Could not add this product to the backend cart.')) } }}>Add to cart</button></>}</div></div>}
    </article>
  )
}

export function LandingPage() {
  return <div className="landing-page">
    <nav className="landing-nav"><Link to="/" className="brand-link"><Brand /></Link><div className="landing-links"><a href="#how">How it works</a><a href="#security">Security</a><Link to="/login">Sign in</Link><ButtonLink to="/register" variant="btn-primary btn-sm">Get started <ArrowRight size={15} /></ButtonLink></div></nav>
    <section className="landing-hero">
      <div className="hero-copy"><div className="hero-badge"><ShieldCheck size={14} /> AI shopping, with customer intent at the center</div><h1>Shop smarter.<br /><span>Pay safer.</span></h1><p>TrustPay AI demonstrates how a purchase can be checked against your request before simulated payment.</p><div className="hero-actions"><ButtonLink to="/register" icon={<ArrowRight size={17} />}>Get started</ButtonLink><ButtonLink to="/shopping-request" variant="btn-ghost">Explore IntentLock <Shield size={16} /></ButtonLink></div><div className="hero-trust"><span><CheckCircle2 size={15} /> Your intent, protected</span><span><LockKeyhole size={15} /> Demo workflow</span></div></div>
      <div className="hero-visual"><div className="visual-glow" /><div className="visual-top"><div><span className="tiny-label">ILLUSTRATIVE DEMO · NOT LIVE API DATA</span><strong><span className="green-dot" /> Example order preview</strong></div><ShieldCheck size={32} /></div><div className="visual-order"><div className="visual-product"><div className="visual-laptop"><div /></div><div><b>Example product</b><span>Specifications unavailable</span></div><b>Sample price</b></div><div className="intent-line"><CheckCircle2 size={15} /><span>Simulated intent analysis</span><b>DEMO</b></div><div className="visual-line"><span>Seller data unavailable</span><CircleAlert size={15} /></div><div className="visual-line"><span>Currency and budget require review</span><CircleAlert size={15} /></div></div><div className="visual-footer"><ShieldCheck size={17} /><span>IntentLock frontend demonstration</span><small>NOT A SECURITY CERTIFICATION</small></div><div className="floating-lock"><Fingerprint size={18} /><span>Customer intent snapshot</span></div></div>
    </section>
    <section id="how" className="landing-section"><div className="section-heading"><span className="eyebrow">A SAFER WAY TO SHOP</span><h2>Every purchase. <span>Double-checked.</span></h2><p>Simple for you. Smarter protection behind the scenes.</p></div><div className="steps-grid">{[['01','Tell us what you need','Describe what you are looking for in your own words.'],['02','Review API product data','Compare catalogue details and unavailable fields.'],['03','Approve the exact order','Review demo checks before a simulated payment.']].map(([n,title,copy]) => <div className="step-card" key={n}><span className="step-num">{n}</span><div className="step-icon"><ShoppingBag size={21} /></div><h3>{title}</h3><p>{copy}</p></div>)}</div></section>
    <section className="landing-section marketplace-landing"><div className="section-heading"><span className="eyebrow">CATALOGUE PROVIDERS</span><h2>Marketplace access, <span>clearly labelled.</span></h2><p>Provider readiness is not the same as a live connection. Current health is shown in the signed-in catalogue using backend status.</p></div><div className="marketplace-readiness-grid"><div><b>DummyJSON Demo Store</b><span className="readiness-demo">Demo catalogue available</span></div><div><b>Amazon India</b><span>Requires official Creators API access</span></div><div><b>Flipkart India</b><span>Requires approved Affiliate API access</span></div><div><b>Myntra India</b><span>Official partner catalogue access not verified</span></div></div></section>
    <section id="security" className="security-banner"><div className="banner-icon"><ShieldCheck size={26} /></div><div><span className="eyebrow">INTRODUCING INTENTLOCK</span><h2>Your original request is the source of truth.</h2><p>Review simulated checks for unauthorized changes, estimated fees, untrusted instructions, and last-minute cart changes.</p></div><ButtonLink to="/shopping-request" variant="btn-light" icon={<ArrowRight size={16} />}>Try IntentLock</ButtonLink></section>
    <footer className="landing-footer"><Brand /><span>© 2026 TrustPay AI. Frontend demo.</span><div><Link to="/login">Sign in</Link><Link to="/register">Create account</Link></div></footer>
  </div>
}

function AuthLayout({ children, title, subtitle }: { children: ReactNode; title: string; subtitle: string }) {
  return <div className="auth-page"><div className="auth-aside"><Link to="/" className="brand-link"><Brand light /></Link><div className="auth-promo"><div className="auth-shield"><ShieldCheck size={35} /></div><span>SHOP WITH PEACE OF MIND</span><h2>Your intent.<br />Your rules.</h2><p>One extra layer of protection between your AI shopping assistant and checkout.</p><div className="auth-footnote"><CheckCircle2 size={16} /> Every order verified before payment</div></div><div className="auth-aside-bottom">© 2026 TrustPay AI</div></div><div className="auth-content"><div className="auth-form-wrap"><Link className="auth-back" to="/">← Back to home</Link><span className="eyebrow">WELCOME TO TRUSTPAY AI</span><h1>{title}</h1><p className="auth-subtitle">{subtitle}</p>{children}<div className="auth-privacy"><LockKeyhole size={14} /> Your information is protected and never sold.</div></div></div></div>
}

export function LoginPage() {
  const { setUser, notify } = useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!/^\S+@\S+\.\S+$/.test(email) || password.length < 6) { setError('Enter a valid email and a password of at least 6 characters.'); return }
    setError('')
    try {
      setUser(await login(email, password))
      notify('Signed in successfully.')
      navigate((location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? '/dashboard')
    } catch (cause) {
      const message = getBackendError(cause, 'Could not sign in to the backend.')
      setError(message)
      notify(message, 'error')
    }
  }
  return <AuthLayout title="Welcome back" subtitle="Sign in to your account to continue securely."><form className="auth-form" onSubmit={submit}><label>Email address<input type="email" placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} required /></label><label>Password<div className="password-wrap"><input type={show ? 'text' : 'password'} placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} required /><button type="button" className="password-toggle" onClick={() => setShow(!show)} aria-label={show ? 'Hide password' : 'Show password'}>{show ? <EyeOff size={17} /> : <Eye size={17} />}</button></div></label><div className="form-between"><label className="check-label"><input type="checkbox" /> Remember me</label><a href="mailto:support@trustpay.ai?subject=Password%20reset">Forgot password?</a></div>{error && <div className="form-error">{error}</div>}<button className="btn btn-primary btn-full" type="submit">Sign in securely <ArrowRight size={16} /></button><p className="auth-switch">New to TrustPay AI? <Link to="/register">Create an account</Link></p></form></AuthLayout>
}

export function RegisterPage() {
  const { setUser, notify } = useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const [error, setError] = useState('')
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const password = String(form.get('password'))
    const mobile = String(form.get('mobile'))
    if (password.length < 8) { setError('Choose a password with at least 8 characters.'); return }
    if (password !== form.get('confirmPassword')) { setError('Your passwords do not match.'); return }
    if (!/^[+0-9 ()-]{8,}$/.test(mobile)) { setError('Enter a valid mobile number.'); return }
    if (!form.get('terms')) { setError('Please accept the terms to create an account.'); return }
    try {
      setUser(await register(String(form.get('name')), String(form.get('email')), password))
      notify('Account created successfully.')
      navigate((location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? '/dashboard')
    } catch (cause) {
      const message = getBackendError(cause, 'Could not create an account on the backend.')
      setError(message)
      notify(message, 'error')
    }
  }
  return <AuthLayout title="Create your account" subtitle="A safer way to shop starts here."><form className="auth-form" onSubmit={submit}><label>Full name<input name="name" placeholder="Alex Morgan" required /></label><label>Email address<input name="email" type="email" placeholder="you@example.com" required /></label><label>Mobile number<input name="mobile" type="tel" placeholder="+91 98765 43210" required /></label><label>Password<input name="password" type="password" placeholder="At least 8 characters" required minLength={8} /></label><label>Confirm password<input name="confirmPassword" type="password" placeholder="Re-enter your password" required /></label><label className="check-label terms-label"><input type="checkbox" name="terms" /> I agree to the <a href="#terms">Terms of Service</a> and Privacy Policy.</label>{error && <div className="form-error">{error}</div>}<button className="btn btn-primary btn-full" type="submit">Create account <ArrowRight size={16} /></button><p className="auth-switch">Already have an account? <Link to="/login">Sign in</Link></p></form></AuthLayout>
}

export function DashboardPage() {
  const { transactions, user, selectedPlatformId } = useApp()
  const [summary, setSummary] = useState<Awaited<ReturnType<typeof getDashboardSummary>> | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let active = true
    getDashboardSummary()
      .then((result) => { if (active) setSummary(result) })
      .catch((cause: unknown) => { if (active) setError(getBackendError(cause, 'Dashboard data could not be loaded.')) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])
  const firstName = user?.name.trim().split(/\s+/)[0] || 'Customer'
  const metrics = [
    ['Shopping requests', summary?.total_requests ?? 0, Search],
    ['Verified orders', summary?.verified_orders ?? 0, CheckCircle2],
    ['Blocked orders', summary?.blocked_transactions ?? 0, ShieldAlert],
    ['Recorded transactions', transactions.length, ShoppingBag],
  ] as const
  const recent = summary?.recent_transactions ?? transactions
  const activities = summary?.security_activity ?? []
  return <><PageTitle eyebrow="ACCOUNT OVERVIEW" title={`Welcome, ${firstName}`} description="Your account activity is retrieved from the TrustPay backend." action={<ButtonLink to="/platforms" icon={<ArrowRight size={16} />}>{selectedPlatformId ? 'Choose shopping platform' : 'Start shopping'}</ButtonLink>} />
    {error && <div className="form-error">{error}<button className="btn btn-outline btn-sm" onClick={() => { setError(''); setLoading(true); getDashboardSummary().then(setSummary).catch((cause: unknown) => setError(getBackendError(cause, 'Dashboard data could not be loaded.'))).finally(() => setLoading(false)) }}>Retry</button></div>}
    <div className="metrics-grid">{metrics.map(([label, value, Icon], index) => <div className="metric-card" key={label}><div className={`metric-icon metric-${index}`}><Icon size={18} /></div><div className="metric-label">{label}</div><div className="metric-number">{loading ? '—' : value}</div><div className="metric-delta">{loading ? 'Loading backend data…' : 'Backend account data'}</div></div>)}</div>
    <div className="panel dashboard-platform"><div className="panel-heading"><div><h2>Choose where to shop</h2><p>Select a supported store before browsing products.</p></div><span className="status-chip status-warning"><i />Only the Demo Store is integrated</span></div><ButtonLink to="/platforms" icon={<ArrowRight size={16} />}>Select shopping platform</ButtonLink></div>
    <div className="dashboard-grid lower-grid"><section className="panel table-panel"><div className="panel-heading"><div><h2>Recent transactions</h2><p>Latest backend-recorded activity</p></div><Link className="text-link" to="/transactions">View all <ArrowRight size={14} /></Link></div>{recent.length ? <TransactionsTable rows={recent.slice(0, 4)} /> : <div className="empty-message">No transactions recorded yet.</div>}</section><section className="panel alerts-panel"><div className="panel-heading"><div><h2>Security activity</h2><p>Recent backend audit events</p></div></div>{activities.length ? activities.slice(0, 3).map((activity) => <div className="alert-item" key={`${activity.timestamp}-${activity.type}`}><span className="alert-icon alert-warning"><ShieldCheck size={17} /></span><div><b>{activity.type}</b><p>{activity.description}</p><small>{new Date(activity.timestamp).toLocaleString()}</small></div></div>) : <div className="empty-message">{loading ? 'Loading backend activity…' : 'No security activity recorded yet.'}</div>}<ButtonLink to="/audit-log" variant="btn-outline btn-full">View audit log <ArrowRight size={15} /></ButtonLink></section></div>
  </>
}

export function PlatformSelectionPage() {
  const { selectedPlatformId, setSelectedPlatformId, notify } = useApp()
  const navigate = useNavigate()
  const [platforms, setPlatforms] = useState<ShoppingPlatform[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    getPlatforms()
      .then((result) => { if (active) setPlatforms(result) })
      .catch((cause: unknown) => { if (active) setError(getBackendError(cause, 'Shopping platforms could not be loaded.')) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])
  const choose = (platform: ShoppingPlatform) => {
    if (!platform.supported) {
      notify(`${platform.name} is not configured for shopping yet.`, 'info')
      return
    }
    setSelectedPlatformId(platform.id)
    navigate('/products')
  }
  return <><PageTitle eyebrow="STEP 1 · SHOPPING SOURCE" title="Choose a shopping platform" description="Choose a supported store first. The catalogue shown next will come from that selected platform." />{error && <div className="form-error">{error}<button className="btn btn-outline btn-sm" onClick={() => { setError(''); setLoading(true); getPlatforms().then(setPlatforms).catch((cause: unknown) => setError(getBackendError(cause, 'Shopping platforms could not be loaded.'))).finally(() => setLoading(false)) }}>Retry</button></div>}{loading ? <div className="panel api-state"><span className="spinner" /><p>Loading available platforms from backend…</p></div> : <div className="platform-grid">{platforms.map((platform) => <button key={platform.id} className={`panel platform-card ${platform.supported ? 'platform-enabled' : 'platform-disabled'} ${selectedPlatformId === platform.id ? 'platform-selected' : ''}`} onClick={() => choose(platform)} disabled={!platform.supported}><span className="platform-icon"><ShoppingBag size={24} /></span><span className="platform-title">{platform.name}</span><span className={`status-chip ${platform.supported ? 'status-success' : 'status-warning'}`}><i />{platform.supported ? 'Available' : 'Not integrated'}</span><span className="platform-description">{platform.description}</span><span className="platform-footnote">{platform.demo_only ? 'Demo catalogue · DummyJSON API' : 'No product access will be attempted'}</span>{selectedPlatformId === platform.id && <span className="platform-current">Currently selected</span>}</button>)}</div>}{!loading && !platforms.some((platform) => platform.supported) && !error && <div className="empty-state"><CircleAlert size={25} /><h3>No supported platforms</h3><p>The backend currently has no product platform enabled.</p></div>}<div className="info-banner"><CircleAlert size={18} /><span>Amazon, Flipkart, and Myntra are listed as unsupported; this prototype does not connect to their catalogues. Only a platform marked Available can be selected.</span></div></>
}

function TransactionsTable({ rows }: { rows: ReturnType<typeof useApp>['transactions'] }) {
  return <div className="table-scroll"><table><thead><tr><th>TRANSACTION</th><th>PRODUCT</th><th>DATE</th><th>AMOUNT</th><th>STATUS</th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td><b>{row.id}</b><small>{row.orderId}</small></td><td>{row.product}</td><td>{new Date(`${row.date}T12:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}</td><td><b>{formatMoney(row.amount, row.currency ?? 'INR')}</b></td><td><span className={`status-chip ${row.status === 'Completed' ? 'status-success' : 'status-danger'}`}><i />{row.status}</span></td></tr>)}</tbody></table></div>
}

export function LegacyProductsPage() {
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [sort, setSort] = useState('Recommended')
  const [maxPrice, setMaxPrice] = useState('')
  const [items, setItems] = useState<Product[]>([])
  const [visibleCount, setVisibleCount] = useState(24)
  const [categories, setCategories] = useState<ProductCategory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [categoryError, setCategoryError] = useState('')
  const [retry, setRetry] = useState(0)
  const { recordAudit, selectedPlatformId } = useApp()
  const auditLoaded = useRef(false)

  useEffect(() => {
    let active = true
    getProductCategories().then((result) => {
      if (active) setCategories(result)
    }).catch((cause: unknown) => {
      console.error('Could not load product categories from Demo Product API.', cause)
      if (active) setCategoryError('Product categories could not be loaded.')
    })
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    const timer = window.setTimeout(() => {
      setLoading(true)
      setError('')
      getProducts({ query: search, category: category || undefined })
        .then((result) => {
          if (!active) return
          setItems(result)
          setLoading(false)
          if (!auditLoaded.current) {
            recordAudit('Product API data retrieved', `Retrieved ${result.length} products from Demo Product API.`)
            auditLoaded.current = true
          }
        })
        .catch((cause: unknown) => {
          console.error('Could not load products from Demo Product API.', cause)
          if (active) {
            setError('Products could not be loaded from Demo Product API. Check your connection and retry.')
            setItems([])
            setLoading(false)
          }
        })
    }, search ? 300 : 0)
    return () => { active = false; window.clearTimeout(timer) }
  }, [search, category, retry, recordAudit])

  const filtered = useMemo(() => items
    .filter((product) => !maxPrice || product.price <= Number(maxPrice))
    .sort((left, right) => sort === 'Price: low to high' ? left.price - right.price : sort === 'Price: high to low' ? right.price - left.price : right.rating - left.rating), [items, maxPrice, sort])
  return <><PageTitle eyebrow="PRODUCT CATALOGUE" title="Find your next favorite" description="Products below are fetched from the platform selected in your dashboard." action={<ButtonLink to="/cart" variant="btn-outline" icon={<ShoppingCart size={16} />}>View cart</ButtonLink>} /><div className="api-source-strip"><span className="api-live-dot" />Selected platform: {selectedPlatformId === 'dummyjson' ? 'DummyJSON Demo Store' : selectedPlatformId}<span>{productDataSource} · USD prices, as provided by the catalogue.</span></div><div className="catalog-toolbar"><label className="search-field"><Search size={17} /><input placeholder="Search products via API..." value={search} onChange={(e) => { setSearch(e.target.value); setVisibleCount(24) }} /></label><select aria-label="Filter by product category" value={category} onChange={(e) => { setCategory(e.target.value); setVisibleCount(24) }}><option value="">All categories</option>{categories.map((item) => <option value={item.slug} key={item.slug}>{item.name}</option>)}</select><label className="price-filter">Under $<input aria-label="Maximum price in USD" type="number" min="0" placeholder="Any" value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} /></label><select aria-label="Sort products by price" value={sort} onChange={(e) => setSort(e.target.value)}><option>Recommended</option><option>Price: low to high</option><option>Price: high to low</option></select></div>{categoryError && <div className="info-banner warning-banner"><CircleAlert size={18} /><span>{categoryError} Category filter may be unavailable.</span><button className="btn btn-outline btn-sm" onClick={() => { setCategoryError(''); getProductCategories().then(setCategories).catch((cause: unknown) => { console.error(cause); setCategoryError('Product categories could not be loaded.') }) }}>Retry categories</button></div>}{loading ? <div className="panel api-state"><span className="spinner" /><p>Loading selected platform catalogue…</p></div> : error ? <div className="panel api-error"><CircleAlert size={25} /><h2>Backend catalogue unavailable</h2><p>{error}</p><button className="btn btn-primary" onClick={() => { setVisibleCount(24); setRetry((value) => value + 1) }}>Retry product request</button></div> : <><div className="api-results-label">{filtered.length} product{filtered.length === 1 ? '' : 's'} from selected platform</div><div className="product-grid">{filtered.slice(0, visibleCount).map((product) => <ProductTile key={product.id} product={product} />)}</div>{filtered.length === 0 && <div className="empty-state"><Search size={28} /><h3>No products found</h3><p>Try a different search, category, or price limit.</p></div>}{visibleCount < filtered.length && <div className="load-more-wrap"><button className="btn btn-outline" onClick={() => setVisibleCount((count) => count + 24)}>Load more products</button></div>}</>}</>
}

export function ProductsPage() {
  return <MarketplaceCatalogPage />
}

export function RequestPage() {
  const { intent, setIntent, selectedPlatformId, notify } = useApp()
  const [request, setRequest] = useState(intent?.request ?? '')
  const [budget, setBudget] = useState(intent?.maximumBudget ?? 800)
  const [currency, setCurrency] = useState<Currency>(intent?.currency ?? 'USD')
  const [category, setCategory] = useState(intent?.category ?? '')
  const [categories, setCategories] = useState<ProductCategory[]>([])
  const [platforms, setPlatforms] = useState<ShoppingPlatform[]>([])
  const platformId = selectedPlatformId ?? intent?.platformId ?? ''
  const [categoryError, setCategoryError] = useState('')
  const [trustedSellersOnly, setTrustedSellersOnly] = useState(intent?.trustedSellersOnly ?? true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    getProductCategories().then((result) => { if (active) setCategories(result) })
      .catch((cause: unknown) => { console.error('Could not load request categories.', cause); if (active) setCategoryError('API categories are unavailable. You can still submit a request without a category.') })
    getPlatforms().then((result) => { if (active) setPlatforms(result) })
      .catch((cause: unknown) => { console.error('Could not load supported platforms.', cause); if (active) setCategoryError('Shopping platforms could not be loaded from the backend.') })
    return () => { active = false }
  }, [])
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!request.trim() || budget < 1) { setError('Describe your purchase and enter a valid budget.'); return }
    setError('')
    setWorking(true)
    try {
      setIntent(await extractIntent(request, budget, category, trustedSellersOnly, currency, platformId))
    } catch (cause) {
      console.error('Could not extract purchase intent.', cause)
      const message = getBackendError(cause, 'The backend could not process this request.')
      setError(message)
      notify(message, 'error')
    } finally { setWorking(false) }
  }
  return <><PageTitle eyebrow="PERSONALIZED SHOPPING" title="What are you looking for?" description="Your selected platform catalogue is used for policy extraction and product results." /><div className="request-layout"><form className="panel request-form" onSubmit={submit}><div className="info-banner"><ShoppingBag size={16} /><span>Selected platform: {platforms.find((platform) => platform.id === platformId)?.name ?? 'Loading selected platform…'} · <Link to="/platforms">Change</Link></span></div><label className="field-label">Your shopping request<textarea rows={6} placeholder="I need a laptop with at least 16GB RAM, 512GB SSD, Intel i7 processor, below $800. Only trusted sellers." value={request} onChange={(e) => setRequest(e.target.value)} required /></label><div className="request-field-row"><label className="field-label">Maximum budget<div className="currency-input"><span>{currency === 'USD' ? '$' : '₹'}</span><input type="number" min="1" value={budget} onChange={(e) => setBudget(Number(e.target.value))} required /></div></label><label className="field-label">Budget currency<select value={currency} onChange={(e) => setCurrency(e.target.value as Currency)}><option value="USD">USD (API price currency)</option><option value="INR">INR</option></select></label></div><label className="field-label">Preferred API category<select value={category} onChange={(e) => setCategory(e.target.value)}><option value="">Not specified</option>{categories.map((item) => <option value={item.slug} key={item.slug}>{item.name}</option>)}</select></label>{categoryError && <div className="form-error">{categoryError}</div>}<label className="seller-option"><span className="seller-option-icon"><BadgeCheck size={18} /></span><span className="seller-option-copy"><b>Prefer trusted sellers</b><p>Seller verification is unavailable from the selected catalogue.</p></span><span className="toggle-switch"><input type="checkbox" checked={trustedSellersOnly} onChange={(event) => setTrustedSellersOnly(event.target.checked)} aria-label="Require trusted sellers" /><i /></span></label>{error && <div className="form-error">{error}</div>}<button className="btn btn-primary" type="submit" disabled={working || !platformId}>{working ? <><span className="spinner" /> Sending request…</> : <>Review purchase policy <Sparkles size={16} /></>}</button><p className="form-note"><ShieldCheck size={14} /> The backend verifies order checks; unsupported product facts remain unavailable.</p></form><aside className="intent-aside"><div className="aside-icon"><Sparkles size={20} /></div><span className="eyebrow">BACKEND POLICY EXTRACTION</span><h2>Your words become your shopping policy.</h2><p>The API returns the extracted policy. Public catalogue content remains untrusted text and cannot override it.</p><div className="mini-step"><span>1</span><div><b>We capture your intent</b><small>Your requested category, requirements and budget.</small></div></div><div className="mini-step"><span>2</span><div><b>We compare API fields</b><small>Unsupported specifications stay explicitly unavailable.</small></div></div><div className="mini-step"><span>3</span><div><b>You stay in control</b><small>Nothing is purchased without your approval.</small></div></div></aside></div>{intent && <section className="panel extracted-card"><div className="extracted-title"><div><span className="eyebrow">BACKEND POLICY</span><h2>Purchase policy extracted</h2></div><span className="mock-tag">API</span></div><div className="extracted-grid"><div><small>Selected platform</small><b>{platforms.find((platform) => platform.id === intent.platformId)?.name ?? intent.platformId}</b></div><div><small>API category</small><b>{intent.category || 'Not specified'}</b></div><div><small>Requirements</small><b>{intent.requirements.length ? intent.requirements.map((requirement) => `${requirement.name}: ${requirement.value}`).join(', ') : 'None detected'}</b></div><div><small>Maximum budget</small><b>{formatMoney(intent.maximumBudget, intent.currency)} {intent.currency}</b></div><div><small>Preferred seller</small><b>{intent.trustedSellersOnly ? 'Trusted seller required (not currently verifiable)' : 'No preference'}</b></div></div><div className="request-summary"><small>ORIGINAL REQUEST</small><p>“{intent.request}”</p></div><ButtonLink to="/product-results" icon={<ArrowRight size={16} />}>Search selected platform</ButtonLink></section>}</>
}

export function ProductResultsPage() {
  const { intent, recordAudit } = useApp()
  const navigate = useNavigate()
  const [items, setItems] = useState<ProductRecommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!intent) return
    let active = true
    const timer = window.setTimeout(() => {
      setLoading(true)
      setError('')
      searchRecommendations(intent)
        .then((result) => {
          if (active) {
            setItems(result)
            setLoading(false)
            recordAudit('Product API data retrieved', `Backend searched the supported product catalogue and returned ${result.length} recommendation(s).`)
          }
        })
        .catch((cause: unknown) => {
          console.error('Could not fetch intent-matched products.', cause)
          if (active) {
            setError('Matching products could not be loaded from Demo Product API.')
            setItems([])
            setLoading(false)
          }
        })
    }, 0)
    return () => { active = false; window.clearTimeout(timer) }
  }, [intent, retry, recordAudit])
  const analyzed = [...items].sort((left, right) => right.analysis.percentage - left.analysis.percentage)
  return <><PageTitle eyebrow="PERSONALIZED MATCHES" title="Products for your intent" description="Backend recommendation status and API product fields are shown without frontend security decisions." action={<ButtonLink to="/shopping-request" variant="btn-outline">Edit request</ButtonLink>} />{intent ? <div className="intent-summary-strip"><Sparkles size={17} /><span><b>Original request:</b> “{intent.request}”</span><span className="summary-budget">Budget {formatMoney(intent.maximumBudget, intent.currency)}</span></div> : <div className="info-banner"><CircleAlert size={18} /><span>Start with a shopping request for personalized matches.</span><Link to="/shopping-request">Create request</Link></div>}<div className="api-source-strip"><span className="api-live-dot" />{productDataSource}<span>Recommendation statuses come from the backend.</span></div>{loading && <div className="panel api-state"><span className="spinner" /><p>Searching supported product catalogue…</p></div>}{error && <div className="panel api-error"><CircleAlert size={25} /><h2>Backend recommendation service unavailable</h2><p>{error}</p><button className="btn btn-primary" onClick={() => setRetry((value) => value + 1)}>Retry product search</button></div>}{!loading && !error && <><div className="results-caption"><span>{analyzed.length} backend recommendation{analyzed.length === 1 ? '' : 's'}</span></div><div className="product-grid">{analyzed.length ? analyzed.map(({ product, analysis }) => <div key={product.id} className="result-product"><div className="match-summary"><span className="match-score">{analysis.percentage}%</span><div><b>{analysis.categoryMatched ? 'Category match' : 'Category mismatch'}</b><small>Backend recommendation result</small></div><span className="status-chip status-warning"><i />{analysis.status ?? 'Needs Review'}</span></div><ProductTile product={product} matched matchPercent={`${analysis.percentage}%`} /><div className="match-analysis"><b>Backend-reported requirements</b>{analysis.matches.length ? analysis.matches.map((requirement) => <div key={requirement.name}><span>{requirement.name}: {requirement.requested}</span><em>{requirement.status}</em></div>) : <p>No technical requirements were extracted.</p>}<div><span>Seller</span><em>Not available for verification</em></div><div><span>Budget comparison</span><em>{analysis.budgetMatched === null ? `Unavailable (${intent?.currency} budget, USD API price)` : analysis.budgetMatched ? 'Within budget including estimated fees' : 'Above budget including estimated fees'}</em></div><details><summary>API description (untrusted text)</summary><p>{product.description}</p></details></div></div>) : <div className="empty-state"><PackageCheck size={30} /><h3>No API products found</h3><p>Try editing the request or browsing all product categories.</p><button className="btn btn-outline" onClick={() => navigate('/products')}>Browse products</button></div>}</div></>}</>
}

export function CartPage() {
  const { cart, intent, setQuantity, removeFromCart, notify } = useApp()
  const [cartError, setCartError] = useState('')
  const totals = calculateCartTotals(cart)
  const budgetCurrencyMatches = Boolean(intent && totals.currency === intent.currency)
  const overBudget = Boolean(budgetCurrencyMatches && intent && totals.total > intent.maximumBudget)
  const budgetUnavailable = Boolean(intent && totals.currency && !budgetCurrencyMatches)
  const blocked = overBudget || budgetUnavailable || totals.hasMixedCurrencies
  const display = (amount: number) => formatMoney(amount, totals.currency ?? 'USD')
  const runCartUpdate = async (operation: () => Promise<void>, update: () => void) => {
    setCartError('')
    try { await operation(); update() }
    catch (error) {
      const message = getBackendError(error, 'The backend could not update your cart.')
      setCartError(message)
      notify(message, 'error')
    }
  }
  return <><PageTitle eyebrow="YOUR ORDER" title="Shopping cart" description="Your cart and product details are synchronized with the backend." action={<ButtonLink to="/products" variant="btn-outline" icon={<ShoppingBag size={16} />}>Continue shopping</ButtonLink>} />{cartError && <div className="form-error">{cartError}</div>}{cart.length === 0 ? <div className="panel empty-cart"><div className="empty-icon"><ShoppingCart size={27} /></div><h2>Your cart is waiting</h2><p>Add products from the supported catalogue to build and verify an order.</p><ButtonLink to="/products" icon={<ArrowRight size={16} />}>Explore products</ButtonLink></div> : <div className="cart-layout"><section className="panel cart-items"><div className="cart-items-heading"><div><h2>Items <span>({cart.reduce((sum, item) => sum + item.quantity, 0)})</span></h2><p>Current backend product prices (USD)</p></div><span className="status-chip status-warning"><i /> Seller not verified by catalogue</span></div>{cart.map(({ product, quantity }) => <div className="cart-item" key={product.id}><img src={product.image} alt={product.name} /><div className="cart-item-main"><Link to="/products">{product.name}</Link><span className="seller-line"><CircleAlert size={13} />Seller: Not provided by catalogue</span><div className="quantity-control"><button aria-label="Decrease quantity" onClick={() => void runCartUpdate(quantity === 1 ? () => removeCartProduct(product.id) : () => updateCartProduct(product.id, quantity - 1), () => quantity === 1 ? removeFromCart(product.id) : setQuantity(product.id, quantity - 1))}>−</button><span>{quantity}</span><button aria-label="Increase quantity" onClick={() => void runCartUpdate(() => updateCartProduct(product.id, quantity + 1), () => setQuantity(product.id, quantity + 1))}>+</button></div></div><div className="cart-item-price"><b>{formatMoney(product.price * quantity, product.currency)}</b><button className="remove-btn" onClick={() => void runCartUpdate(() => removeCartProduct(product.id), () => removeFromCart(product.id))} aria-label={`Remove ${product.name}`}><Trash2 size={15} /></button></div></div>)}<div className="cart-note"><ShieldCheck size={17} /><span>Any backend cart change invalidates previous verification and approval.</span></div></section><aside className="panel order-summary"><h2>Order summary</h2><p className="summary-muted">Shipping and tax are itemized demo estimates</p><div className="summary-row"><span>Subtotal</span><b>{display(totals.subtotal)}</b></div><div className="summary-row"><span>Estimated shipping</span><b>{display(totals.shipping)}</b></div><div className="summary-row"><span>Estimated tax (5%)</span><b>{display(totals.tax)}</b></div><div className="summary-row total-row"><b>Total ({totals.currency ?? 'mixed currencies'})</b><strong>{display(totals.total)}</strong></div>{intent && <div className={`budget-status ${blocked ? 'budget-over' : ''}`}><span>{budgetUnavailable ? <CircleAlert size={16} /> : overBudget ? <CircleAlert size={16} /> : <CheckCircle2 size={16} />}{budgetUnavailable ? 'Currency mismatch — comparison unavailable' : overBudget ? 'Over your stated budget' : 'Within your stated budget'}</span><b>{formatMoney(intent.maximumBudget, intent.currency)}</b></div>}{blocked && <div className="form-error">{budgetUnavailable ? `Catalogue prices are ${totals.currency}; your policy budget is ${intent?.currency}. No currency conversion is assumed.` : 'Resolve the mixed currency or budget issue before continuing.'}</div>}<Link aria-disabled={blocked} onClick={(event) => { if (blocked) event.preventDefault() }} to="/verification" className={`btn btn-primary btn-full ${blocked ? 'disabled-link' : ''}`}>Verify my order <ShieldCheck size={16} /></Link><p className="checkout-safe"><LockKeyhole size={13} /> Backend verification required before approval</p></aside></div>}</>
}

export function VerificationPage() {
  const { cart, intent, backendOrder, backendVerification, setVerified, setBackendOrder, setBackendVerification, replaceCart, notify } = useApp()
  const navigate = useNavigate()
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const checks = backendVerification
    ? backendVerification.checks.map((check: BackendVerificationCheck) => ({
      title: check.name,
      status: check.status === 'Passed' ? 'Verified' as const : check.status === 'Needs Review' ? 'Warning' as const : 'Failed' as const,
      detail: check.reason,
      critical: check.critical,
    }))
    : []
  const failed = checks.filter((check) => check.status === 'Failed').length
  const warnings = checks.filter((check) => check.status === 'Warning').length
  const passed = checks.filter((check) => check.status === 'Verified').length
  const score = Math.max(0, Math.round((passed / checks.length) * 100 - warnings * 3 - failed * 20))
  const criticalFailures = backendVerification?.status !== 'Passed'
  const statusIcon = (status: string) => status === 'Verified' ? <CheckCircle2 size={19} /> : status === 'Warning' ? <CircleAlert size={19} /> : status === 'Pending' ? <Clock3 size={19} /> : <ShieldAlert size={19} />
  const runVerification = async () => {
    if (!cart.length || !intent || working) return
    setWorking(true)
    setError('')
    try {
      const order = await createBackendOrder(intent)
      replaceCart(order.items.map(({ product, quantity }) => ({
        product: mapProduct(product),
        quantity,
      })))
      setBackendOrder(order)
      const result = await verifyBackendOrder(order.id)
      setBackendVerification(result)
      setVerified(result.status === 'Passed')
      if (result.status === 'Passed') navigate('/approval')
      else notify('IntentLock found a critical issue. Review the failed checks before continuing.', 'error')
    } catch (cause) {
      const message = getBackendError(cause, 'The backend could not verify this order.')
      setError(message)
      notify(message, 'error')
    } finally {
      setWorking(false)
    }
  }
  return <><PageTitle eyebrow="PRE-PAYMENT SECURITY" title="IntentLock verification" description="The backend checks this exact cart snapshot against the saved customer policy." />{error && <div className="form-error">{error}</div>}<div className="verification-overview"><div className="score-gauge"><div className="score-number">{checks.length ? score : '—'}<small>{checks.length ? '/100' : ''}</small></div><span>BACKEND CHECK SUMMARY</span><div className="score-track"><i style={{ width: `${checks.length ? score : 0}%` }} /></div></div><div className="overview-copy"><div className={`security-status ${criticalFailures ? 'security-failed' : 'security-verified'}`}><ShieldCheck size={22} />{!backendVerification ? 'Verification required' : criticalFailures ? 'Action required' : 'Backend checks passed'}</div><h2>{!backendVerification ? 'Run the server-side order checks.' : criticalFailures ? 'Resolve critical policy mismatches.' : 'Review the verified order snapshot.'}</h2><p>Unsupported API data remains unavailable and is not treated as verified.</p><div className="check-counts"><span className="count-green"><Check size={14} />{passed} passed</span><span className="count-amber"><CircleAlert size={14} />{warnings} needs review</span><span className="count-red"><X size={14} />{failed} failed</span></div></div><div className="check-summary-box"><span>Server checks</span><b>{checks.length || 8}</b><small>Backend decision</small></div></div><div className="panel checks-panel"><div className="panel-heading"><div><h2>IntentLock checks</h2><p>{backendOrder ? `Order ${backendOrder.id} · version ${backendOrder.version}` : 'Checks are generated by the backend'}</p></div><span className="mock-tag">SERVER VERIFIED</span></div>{checks.length ? checks.map((check) => <div className="verification-check" key={check.title}><span className={`check-status-icon check-${check.status.toLowerCase()}`}>{statusIcon(check.status)}</span><div className="check-copy"><b>{check.title}</b><p>{check.detail}</p></div><span className={`status-chip status-${check.status.toLowerCase()}`}><i />{check.status === 'Warning' ? 'Needs Review' : check.status}</span></div>) : <div className="empty-message">No verification has been run for this cart yet.</div>}</div><div className="untrusted-callout"><span className="untrusted-icon"><ShieldAlert size={19} /></span><div><b>Untrusted product content</b><p>External catalog descriptions cannot override your policy.</p><small>Product descriptions are displayed as text; backend verification does not execute them as instructions.</small></div></div><div className="verify-actions"><Link className="btn btn-outline" to="/cart">Back to cart</Link><button className="btn btn-primary" disabled={cart.length === 0 || !intent || working} onClick={() => void runVerification()}>{working ? <><span className="spinner" /> Verifying on backend…</> : backendVerification ? 'Re-run backend verification' : 'Verify this order'} <ArrowRight size={16} /></button></div>{cart.length === 0 && <div className="info-banner"><CircleAlert size={18} /> Your cart is empty. Add a product before verification.</div>}</>
}

export function ApprovalPage() {
  const { cart, intent, backendOrder, backendVerification, approved, verified, verifiedFingerprint, setApproved, notify } = useApp()
  const navigate = useNavigate()
  const [confirmed, setConfirmed] = useState(approved)
  const [approvalError, setApprovalError] = useState('')
  const [approving, setApproving] = useState(false)
  const totals = calculateCartTotals(cart)
  const checks = backendVerification?.checks ?? []
  const currentChecksPass = backendVerification?.status === 'Passed' && verifiedFingerprint === getOrderFingerprint(cart, intent)
  const blocked = cart.length === 0 || !backendOrder || !currentChecksPass || backendOrder.status === 'verification_failed'
  const display = (amount: number) => formatMoney(amount, backendVerification?.totals.currency ?? totals.currency ?? 'USD')
  const approve = async () => {
    if (!confirmed || blocked || !backendOrder || approving) return
    setApprovalError('')
    setApproving(true)
    try {
      await approveBackendOrder(backendOrder.id, backendOrder.version)
      setApproved(true)
      navigate('/payment')
    } catch (cause) {
      const message = getBackendError(cause, 'The backend could not record this approval. Reverify the order.')
      setApprovalError(message)
      notify(message, 'error')
    } finally { setApproving(false) }
  }
  return <><PageTitle eyebrow="EXPLICIT CUSTOMER AUTHORIZATION" title="Review and approve" description="Approval is recorded by the backend against the exact verified order version." />{(!verified || !backendOrder) && <div className="info-banner warning-banner"><CircleAlert size={18} /><span>The order has not passed backend verification or has changed. Re-run checks before approval.</span><Link to="/verification">Run verification</Link></div>}{approvalError && <div className="form-error">{approvalError}</div>}<div className="approval-security"><ShieldCheck size={19} /><div><b>{currentChecksPass ? 'Current order version verified' : 'Backend verification required'}</b><span>{backendOrder ? `Order version ${backendOrder.version}; changes require new verification and approval.` : 'No backend order snapshot exists.'}</span></div><Link to="/verification">Review checks</Link></div>{blocked ? <div className="panel empty-state"><ShieldAlert size={28} /><h3>Order cannot be approved yet</h3><p>Pass server-side verification before approving.</p><ButtonLink to={cart.length ? '/verification' : '/cart'}>{cart.length ? 'Verify this order' : 'Review cart'}</ButtonLink></div> : <div className="approval-layout"><section className="panel approval-order"><div className="panel-heading"><div><h2>Exact order details</h2><p>Backend order {backendOrder?.id}</p></div><span className="status-chip status-success"><i /> Version {backendOrder?.version} verified</span></div>{cart.map(({ product, quantity }) => <div className="approval-product" key={product.id}><img src={product.image} alt={product.name} /><div><b>{product.name}</b><span>{product.specifications.length ? product.specifications.join(' · ') : 'Specifications: Not available for verification'}</span><small>{quantity} × {formatMoney(product.price, product.currency)} · Seller: Not provided by catalogue</small></div><strong>{formatMoney(product.price * quantity, product.currency)}</strong></div>)}<div className="request-summary"><small>CUSTOMER PURCHASE POLICY</small><p>“{intent?.request ?? 'No purchase policy found.'}”</p></div><div className="summary-row"><span>Estimated shipping and tax</span><b>{display((backendVerification?.totals.shipping ?? totals.shipping) + (backendVerification?.totals.tax ?? totals.tax))}</b></div><div className="summary-row total-row"><b>Final amount</b><strong>{display(backendVerification?.totals.total ?? totals.total)}</strong></div>{intent && <div className="budget-status"><span><CheckCircle2 size={16} /> Customer budget ({intent.currency})</span><b>{formatMoney(intent.maximumBudget, intent.currency)}</b></div>}<div className="approval-check-results"><b>Backend verification results</b>{checks.map((check) => <span key={check.name}>{check.name}: <strong>{check.status}</strong></span>)}</div><label className="approve-checkbox"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>I explicitly approve this exact product, quantity, estimated fees, and total amount.</span></label><div className="approval-actions"><button className="btn btn-outline" onClick={() => { setApproved(false); navigate('/cart') }}>Reject order</button><button className="btn btn-primary" disabled={!confirmed || blocked || approving} onClick={() => void approve()}>{approving ? 'Recording approval…' : 'Approve exact order'} <ArrowRight size={16} /></button></div></section><aside className="approval-aside"><div className="aside-icon"><Fingerprint size={21} /></div><h3>Approval is order-specific</h3><p>The backend rejects payment if this order changes or the approval becomes stale.</p><div className="approval-includes"><b>You're approving</b><span><Check size={14} /> {cart.length} product{cart.length > 1 ? 's' : ''}</span><span><Check size={14} /> {cart.reduce((sum, item) => sum + item.quantity, 0)} unit{cart.reduce((sum, item) => sum + item.quantity, 0) > 1 ? 's' : ''}</span><span><Check size={14} /> {display(backendVerification?.totals.total ?? totals.total)} total</span></div></aside></div>}</>
}

export function PaymentPage() {
  const { cart, intent, backendOrder, backendVerification, approved, verified, verifiedFingerprint, addTransaction, clearCart, notify } = useApp()
  const [searchParams] = useSearchParams()
  const [processing, setProcessing] = useState(() => Boolean(searchParams.get('token')))
  const [payment, setPayment] = useState<{ id: string; status: string } | null>(null)
  const [paymentError, setPaymentError] = useState('')
  const returnHandled = useRef(false)
  const totals = calculateCartTotals(cart)
  const currency = backendVerification?.totals.currency ?? totals.currency ?? 'USD'
  const display = (amount: number) => formatMoney(amount, currency)
  const snapshotMatches = Boolean(verifiedFingerprint && getOrderFingerprint(cart, intent) === verifiedFingerprint)
  const paymentAllowed = Boolean(
    cart.length && backendOrder && backendVerification?.status === 'Passed'
    && approved && verified && snapshotMatches,
  )

  useEffect(() => {
    if (returnHandled.current) return
    const paypalOrderId = searchParams.get('token')
    if (searchParams.get('cancelled') === '1') {
      returnHandled.current = true
      return
    }
    if (!paypalOrderId) return
    returnHandled.current = true
    let active = true
    capturePayPalOrder(paypalOrderId)
      .then(async (result) => {
        if (!active) return
        setPayment({ id: result.paypal_reference, status: result.status })
        if (result.status === 'COMPLETED') {
          const transaction: Transaction = {
            id: result.id ?? result.paypal_reference,
            orderId: result.order_id,
            product: cart.map((item) => item.product.name).join(', '),
            amount: result.amount,
            currency: result.currency,
            date: result.date,
            method: result.method,
            status: 'Completed',
            verification: 'Backend verified',
          }
          addTransaction(transaction)
          await clearBackendCart()
          clearCart()
          notify('Sandbox payment completed and transaction recorded.')
        } else if (result.status === 'CANCELLED') {
          notify('PayPal Sandbox checkout was cancelled; no payment was captured.', 'info')
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          const message = getBackendError(cause, 'PayPal Sandbox could not confirm the payment result.')
          setPaymentError(message)
          notify(message, 'error')
        }
      })
      .finally(() => { if (active) setProcessing(false) })
    return () => { active = false }
  }, [searchParams, addTransaction, cart, clearCart, notify])
  const paymentResult = payment ?? (searchParams.get('cancelled') === '1'
    ? { id: searchParams.get('order_id') ?? '', status: 'CANCELLED' }
    : null)

  const pay = async () => {
    if (!paymentAllowed || processing || !backendOrder) return
    setProcessing(true)
    setPaymentError('')
    try {
      const checkout = await createPayPalOrder(backendOrder.id)
      window.location.assign(checkout.approval_url)
    } catch (cause) {
      const message = getBackendError(cause, 'PayPal Sandbox checkout could not be started.')
      setPaymentError(message)
      notify(message, 'error')
      setProcessing(false)
    } finally { setProcessing(false) }
  }
  if (processing && !paymentResult && !paymentError) return <div className="panel api-state"><span className="spinner" /><p>Waiting for PayPal Sandbox confirmation…</p></div>
  if (paymentResult) {
    const completed = paymentResult.status === 'COMPLETED'
    const cancelled = paymentResult.status === 'CANCELLED'
    return <div className="panel payment-result"><div className={`result-icon ${completed ? 'success' : 'failure'}`}>{completed ? <CheckCircle2 size={34} /> : <CircleAlert size={34} />}</div><span className="eyebrow">PAYPAL SANDBOX · LIVE PROVIDER RESPONSE</span><h1>{completed ? 'Sandbox payment completed' : cancelled ? 'Payment cancelled' : `Payment ${paymentResult.status.toLowerCase()}`}</h1><p>{completed ? 'PayPal confirmed the capture. The backend recorded the transaction.' : cancelled ? 'The PayPal checkout was cancelled; no payment was captured.' : 'PayPal did not confirm a completed capture. No successful payment is recorded.'}</p>{paymentResult.id && <div className="transaction-id"><small>PAYPAL REFERENCE</small><b>{paymentResult.id}</b></div>}<ButtonLink to="/transactions" icon={<ArrowRight size={16} />}>View transaction history</ButtonLink></div>
  }
  return <><PageTitle eyebrow="SECURE CHECKOUT" title="PayPal Sandbox Checkout" description="Checkout is created and captured by the backend using server-only sandbox credentials." />{paymentError && <div className="form-error">{paymentError}</div>}<div className="payment-layout"><section className="panel payment-main"><div className="paypal-brand"><span className="paypal-mark">P</span><b>PayPal</b><span className="sandbox-badge">SANDBOX TEST PAYMENT</span></div>{!paymentAllowed && <div className="info-banner warning-banner"><CircleAlert size={18} /><span>Payment is blocked until backend verification and explicit approval are current.</span><Link to={cart.length ? '/approval' : '/cart'}>{cart.length ? 'Review approval' : 'Build an order'}</Link></div>}<div className="payment-protection"><ShieldCheck size={19} /><div><b>Backend order state</b><small>Verification: {verified && snapshotMatches ? 'Current snapshot verified' : 'Not verified'} · Approval: {approved && snapshotMatches ? 'Approved' : 'Not approved'}</small></div>{paymentAllowed ? <CheckCircle2 size={18} /> : <CircleAlert size={18} />}</div><div className="payment-order-title"><h2>Verified order amount</h2><span>{cart.length} item{cart.length === 1 ? '' : 's'}</span></div>{cart.length ? cart.map(({ product, quantity }) => <div className="payment-item" key={product.id}><img src={product.image} alt={product.name} /><div><b>{product.name}</b><small>Qty {quantity} · Seller not verified by catalogue</small></div><strong>{formatMoney(product.price * quantity, product.currency)}</strong></div>) : <div className="empty-message">No order is ready for payment.</div>}<div className="summary-row total-row"><b>Total due</b><strong>{display(backendVerification?.totals.total ?? totals.total)}</strong></div><button className="paypal-button" onClick={() => void pay()} disabled={!paymentAllowed || processing}>{processing ? <><span className="spinner" /> Connecting to PayPal Sandbox…</> : <><span>Continue to</span> <b>PayPal</b> <ArrowRight size={16} /></>}</button><p className="sandbox-disclaimer">Sandbox only · Provider approval and capture are handled by the backend · No card data stored here</p></section><aside className="payment-aside"><div className="aside-icon"><LockKeyhole size={20} /></div><h3>Pre-payment recheck</h3><p>The backend rejects checkout if the approved order snapshot or cart has changed.</p><div className="payment-assurances"><span><CheckCircle2 size={15} /> Exact order approved: {approved && snapshotMatches ? 'Yes' : 'No'}</span><span><CheckCircle2 size={15} /> Server verification passed: {backendVerification?.status === 'Passed' ? 'Yes' : 'No'}</span><span><CheckCircle2 size={15} /> Sandbox transaction only</span></div></aside></div></>
}

export function TransactionsPage() {
  const { transactions } = useApp()
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('All statuses')
  const [dateRange, setDateRange] = useState('All time')
  const [dateCutoff, setDateCutoff] = useState<number | null>(null)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<string | null>(null)
  const cutoff = dateCutoff === null ? null : new Date(dateCutoff)
  const filtered = transactions.filter((item) => (status === 'All statuses' || item.status === status) && (!cutoff || new Date(`${item.date}T00:00:00`) >= cutoff) && `${item.id} ${item.product} ${item.orderId}`.toLowerCase().includes(query.toLowerCase()))
  const pages = Math.max(1, Math.ceil(filtered.length / 5))
  const rows = filtered.slice((page - 1) * 5, page * 5)
  return <><PageTitle eyebrow="PAYMENT ACTIVITY" title="Transaction history" description="A clear record of every order processed through TrustPay AI." action={<button className="btn btn-outline" onClick={() => window.print()}><Download size={15} /> Export history</button>} /><div className="panel transactions-panel"><div className="transaction-filters"><label className="search-field"><Search size={16} /><input placeholder="Search transactions..." value={query} onChange={(e) => { setQuery(e.target.value); setPage(1) }} /></label><select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}><option>All statuses</option><option>Completed</option><option>Failed</option></select><select className="select-button" aria-label="Date filter" value={dateRange} onChange={(e) => { const range = e.target.value; setDateRange(range); setDateCutoff(range === 'All time' ? null : Date.now() - (range === 'Last 30 days' ? 30 : 90) * 24 * 60 * 60 * 1000); setPage(1) }}><option>All time</option><option>Last 30 days</option><option>Last 90 days</option></select></div><div className="table-scroll"><table><thead><tr><th>TRANSACTION / ORDER</th><th>PRODUCT</th><th>DATE</th><th>METHOD</th><th>AMOUNT</th><th>STATUS</th><th></th></tr></thead><tbody>{rows.map((row) => <tr key={row.id}><td><b>{row.id}</b><small>{row.orderId}</small></td><td>{row.product}</td><td>{new Date(`${row.date}T12:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}</td><td>{row.method}</td><td><b>{formatMoney(row.amount, row.currency)}</b></td><td><span className={`status-chip ${row.status === 'Completed' ? 'status-success' : 'status-danger'}`}><i />{row.status}</span></td><td><button className="icon-btn" onClick={() => setSelected(selected === row.id ? null : row.id)} aria-label={`View ${row.id}`}><Eye size={16} /></button></td></tr>)}</tbody></table></div>{filtered.length === 0 && <div className="empty-message">No matching transactions.</div>}<div className="pagination"><span>Showing {filtered.length ? (page - 1) * 5 + 1 : 0}–{Math.min(page * 5, filtered.length)} of {filtered.length}</span><div><button className="btn btn-outline btn-sm" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</button><button className="btn btn-outline btn-sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button></div></div></div>{selected && <div className="info-banner blue-banner"><FileCheck2 size={18} /><span>{selected}: status is {transactions.find((item) => item.id === selected)?.status}; IntentLock verification recorded.</span><button className="icon-btn" onClick={() => setSelected(null)} aria-label="Dismiss"><X size={16} /></button></div>}</>
}

export function AuditLogPage() {
  const { notify } = useApp()
  const [loading, setLoading] = useState(true)
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const loadAudit = useCallback(async () => {
    setBusy(true)
    try {
      setEvents(await getAuditEvents())
      setError('')
    } catch (cause) {
      setError(getBackendError(cause, 'Backend audit records could not be loaded.'))
    } finally { setBusy(false); setLoading(false) }
  }, [])
  useEffect(() => {
    let active = true
    getAuditEvents()
      .then((result) => { if (active) setEvents(result) })
      .catch((cause: unknown) => { if (active) setError(getBackendError(cause, 'Backend audit records could not be loaded.')) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])
  const verify = async () => {
    setBusy(true)
    setMessage('')
    try {
      const result = await verifyBackendAudit()
      setMessage(result.valid
        ? `Backend audit integrity verified across ${result.records_checked} record(s).`
        : `Backend audit integrity failed; checked ${result.records_checked} record(s).`)
      setEvents((current) => current.map((event) => ({ ...event, integrity: result.valid ? 'Verified' : 'Pending' })))
      notify(result.valid
        ? `Audit integrity verified across ${result.records_checked} record(s).`
        : 'Audit integrity verification failed.', result.valid ? 'success' : 'error')
    }
    catch (cause) {
      const message = getBackendError(cause, 'Backend audit integrity could not be verified.')
      setError(message)
      notify(message, 'error')
    }
    finally { setBusy(false) }
  }
  return <><PageTitle eyebrow="TRANSPARENCY & ACCOUNTABILITY" title="Audit log" description="Backend records for policy, catalogue, order verification, approval, and payment activity." action={<button className="btn btn-outline" onClick={() => void loadAudit()} disabled={busy}><Download size={16} /> Refresh records</button>} /><div className="audit-disclaimer"><CircleAlert size={17} /><span><b>Backend audit chain.</b> Records are hashed and verified by the API; this prototype does not use a tamper-proof external ledger.</span></div>{error && <div className="form-error">{error}</div>}<div className="audit-toolbar"><span>{events.length} backend audit record(s)</span><button className="btn btn-outline btn-sm" onClick={() => void verify()} disabled={busy || events.length === 0}><ShieldCheck size={15} /> Verify backend integrity</button></div>{message && <div className={`info-banner ${message.includes('failed') ? 'warning-banner' : 'blue-banner'}`}>{message.includes('verified') ? <CheckCircle2 size={17} /> : <CircleAlert size={17} />}{message}</div>}<div className="panel audit-panel">{loading ? <div className="empty-message">Loading backend audit records…</div> : events.length === 0 ? <div className="empty-state"><FileCheck2 size={28} /><h3>No workflow events yet</h3><p>Complete a backend shopping workflow to create audit records.</p></div> : <div className="audit-timeline">{events.map((event) => <div className="audit-event" key={event.id}><div className="timeline-dot"><Check size={13} /></div><div className="audit-event-content"><div className="audit-event-heading"><div><span className="audit-event-type">{event.type}</span><small>{new Date(event.timestamp).toLocaleString('en-IN')}</small></div><span className={`status-chip ${event.integrity === 'Verified' ? 'status-success' : 'status-warning'}`}><i />{event.integrity}</span></div><p>{event.description}</p><div className="hash-grid"><div><small>EVENT ID</small><code>{event.id}</code></div><div><small>PREVIOUS HASH</small><code>{event.previousHash}</code></div><div><small>SHA-256 HASH</small><code>{event.hash}</code></div></div></div></div>)}</div>}</div><div className="audit-footnote"><Shield size={15} /> Backend hashes are illustrative and are not a production immutable ledger.</div></>
}
