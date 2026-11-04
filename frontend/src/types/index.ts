export type Currency = 'USD' | 'INR'

export interface ProductApiProduct {
  id: number
  title: string
  description: string
  category: string
  price: number
  rating: number
  brand?: string
  sku?: string
  weight?: number
  dimensions?: { width: number; height: number; depth: number }
  tags?: string[]
  availabilityStatus?: string
  thumbnail: string
  images: string[]
}

export interface ProductApiListResponse {
  products: ProductApiProduct[]
  total: number
  skip: number
  limit: number
}

export interface ProductCategory {
  slug: string
  name: string
  url: string
}

export interface Product {
  id: string
  name: string
  description: string
  category: string
  price: number
  currency: 'USD'
  seller: null
  sellerVerified: false
  rating: number
  image: string
  specifications: string[]
  source: 'DummyJSON'
}

export type MarketplaceProviderName = 'AMAZON' | 'FLIPKART' | 'MYNTRA' | 'DEMO'

export type MarketplaceProviderStatus =
  | 'CONNECTED'
  | 'NOT_CONFIGURED'
  | 'TEMPORARILY_UNAVAILABLE'
  | 'AUTHENTICATION_FAILED'

export interface MarketplaceProvider {
  name: MarketplaceProviderName
  connected: boolean
  status: MarketplaceProviderStatus
  message?: string
}

export interface MarketplaceProduct {
  id: string
  external_product_id: string
  provider: MarketplaceProviderName
  title: string
  description?: string | null
  image_url?: string | null
  price?: number | null
  currency: string | null
  category?: string | null
  rating?: number | null
  product_url?: string | null
  seller_name?: string | null
  seller_verified?: boolean | null
  specifications?: Record<string, unknown> | null
  source_updated_at?: string | null
}

export interface CartItem {
  product: Product
  quantity: number
}

export interface PurchaseRequirement {
  name: string
  value: string
}

export interface PurchaseIntent {
  request: string
  category: string
  requirements: PurchaseRequirement[]
  maximumBudget: number
  currency: Currency
  trustedSellersOnly: boolean
  platformId?: string
  excludeAccessories?: boolean
}

export interface RequirementMatch {
  name: string
  requested: string
  status: 'Matched' | 'Not available for verification' | 'Not matched'
  explanation: string
}

export interface ProductMatchAnalysis {
  percentage: number
  categoryMatched: boolean
  budgetMatched: boolean | null
  matches: RequirementMatch[]
  status?: string
}

export interface ProductRecommendation {
  product: Product
  analysis: ProductMatchAnalysis
}

export interface BackendOrder {
  id: string
  version: number
  status: string
  intent: PurchaseIntent
  items: Array<{ product: ProductApiProduct; quantity: number }>
  totals: { subtotal: number; shipping: number; tax: number; total: number; currency: Currency }
}

export interface BackendVerificationCheck {
  name: string
  status: 'Passed' | 'Failed' | 'Needs Review'
  reason: string
  critical: boolean
}

export interface BackendVerification {
  order_id: string
  order_version: number
  status: 'Passed' | 'Failed'
  checks: BackendVerificationCheck[]
  totals: { subtotal: number; shipping: number; tax: number; total: number; currency: Currency }
}

export interface Transaction {
  id: string
  orderId: string
  product: string
  amount: number
  currency: Currency
  date: string
  method: string
  status: 'Completed' | 'Failed'
  verification: string
}

export interface AuditEvent {
  id: string
  type: string
  timestamp: string
  description: string
  previousHash: string
  hash: string
  integrity: 'Verified' | 'Pending'
}

export interface AuditRecord {
  id: string
  type: string
  timestamp: string
  description: string
}
