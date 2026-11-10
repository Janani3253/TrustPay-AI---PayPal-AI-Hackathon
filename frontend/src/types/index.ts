export type Currency = 'USD' | 'INR'

export interface ProductApiProduct {
  id: number
  title: string
  description: string
  category: string
  price: number
  currency?: Currency
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
  currency: Currency
  seller: null
  sellerVerified: false
  rating: number
  image: string
  specifications: string[]
  source: 'DummyJSON'
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
  status: 'Matched' | 'Mentioned in catalogue (unverified)' | 'Not available for verification' | 'Not matched'
  explanation: string
}

export interface RecommendationConstraint {
  name: string
  status: 'Matched' | 'Not available for verification'
  explanation: string
}

export interface ProductMatchAnalysis {
  percentage: number
  matchType?: 'Exact Match' | 'Partial Match' | 'No Match'
  rankingTier?: number
  nameRelevance?: number
  nameMatched?: boolean
  requestedBrand?: string | null
  brandMatched?: boolean | null
  brandMatchStatus?: string
  verificationStatus?: string
  categoryMatched: boolean
  specificationsMatched?: boolean | null
  budgetMatched: boolean | null
  matches: RequirementMatch[]
  cataloguePrice?: number | null
  catalogueCurrency?: Currency
  convertedPrice?: number | null
  convertedShipping?: number | null
  convertedTax?: number | null
  comparableTotal?: number | null
  comparisonCurrency?: Currency
  budgetCurrency?: Currency | null
  budgetAmount?: number | null
  exchangeRate?: number | null
  exchangeRateBase?: Currency
  exchangeRateQuote?: Currency
  exchangeRateDate?: string | null
  constraints?: RecommendationConstraint[]
  status?: 'Matches Requirements' | 'Exact Match' | 'Partial Match' | 'No Match' | 'Budget Exceeded' | 'Specifications Unverified' | 'Constraint Verification Pending' | 'Exchange Rate Unavailable' | 'Category Mismatch'
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
  budgetComparison?: {
    amount: number | null
    currency: Currency
    exchangeRate: number | null
    exchangeRateBase: Currency
    exchangeRateQuote: Currency
    exchangeRateDate: string | null
  }
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

export interface TransactionDetails {
  transaction: {
    id: string
    order_id: string
    reference: string
    provider: string
    status: string
    capture_status: string
    paypal_capture_id: string | null
    paypal_order_id: string | null
    amount: number
    currency: Currency
    date: string
    captured_at: string
    payer: { name?: string; email?: string } | null
  }
  order: {
    id: string
    version: number
    status: string
    intent: Record<string, unknown>
    products: Array<{
      product: ProductApiProduct & { source?: string; provider?: string; url?: string }
      quantity: number
      unit_price: number
      subtotal: number
      provider: string
      marketplace: string | null
      product_url: string | null
    }>
    totals: { subtotal: number; shipping: number; tax: number; total: number; currency: Currency }
    verification: {
      status?: string
      checks?: Array<{
        name: string
        status: string
        reason: string
        critical: boolean
        expected?: unknown
        actual?: unknown
      }>
      [key: string]: unknown
    } | null
    budget: {
      maximum: number
      currency: Currency
      actual_total: number | null
      remaining: number | null
      status: string
      exchange_rate: number | null
      exchange_rate_base: Currency | null
      exchange_rate_quote: Currency | null
      exchange_rate_date: string | null
    } | null
  }
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
