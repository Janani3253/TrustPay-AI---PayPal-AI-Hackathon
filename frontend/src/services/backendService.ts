import { api } from './api'
import { DUMMYJSON_PLATFORM_ID, mapProduct } from './productService'
import type { CartTotals } from './cartService'
import type {
  AuditEvent,
  BackendOrder,
  BackendVerification,
  CartItem,
  ProductApiListResponse,
  ProductRecommendation,
  PurchaseIntent,
  Transaction,
} from '../types'

interface BackendCart {
  items: Array<{ product: ProductApiListResponse['products'][number]; quantity: number }>
  totals: { subtotal: number; shipping: number; tax: number; total: number; currency: 'USD' }
}

function mapBackendCart(cart: BackendCart): { items: CartItem[]; totals: CartTotals } {
  return {
    items: cart.items.map(({ product, quantity }) => ({ product: mapProduct(product), quantity })),
    totals: { ...cart.totals, hasMixedCurrencies: false },
  }
}

export interface ShoppingPlatform {
  id: string
  name: string
  supported: boolean
  demo_only: boolean
  description: string
  connected?: boolean | null
  status?: string | null
}

export interface DashboardSummary {
  total_requests: number
  verified_orders: number
  blocked_transactions: number
  recent_transactions: Transaction[]
  security_activity: Array<{ type: string; timestamp: string; description: string }>
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const response = await api.get<Omit<DashboardSummary, 'recent_transactions'> & {
    recent_transactions: Array<Omit<Transaction, 'orderId'> & { order_id: string }>
  }>('/dashboard')
  return {
    ...response.data,
    recent_transactions: response.data.recent_transactions.map((transaction) => ({
      ...transaction,
      orderId: transaction.order_id,
    })),
  }
}

export async function getCart(): Promise<{ items: CartItem[]; totals: CartTotals }> {
  const response = await api.get<BackendCart>('/cart')
  return mapBackendCart(response.data)
}

export async function addCartProduct(productId: string): Promise<void> {
  const numericId = Number(productId)
  if (!Number.isSafeInteger(numericId) || numericId < 1) {
    throw new Error('Only numeric DummyJSON products can be added to the cart.')
  }
  await api.post('/cart/items', { product_id: numericId, quantity: 1 })
}

export async function updateCartProduct(productId: string, quantity: number): Promise<void> {
  await api.put(`/cart/items/${encodeURIComponent(productId)}`, { quantity })
}

export async function removeCartProduct(productId: string): Promise<void> {
  await api.delete(`/cart/items/${encodeURIComponent(productId)}`)
}

export async function clearBackendCart(): Promise<void> {
  await api.delete('/cart/items')
}

export async function getPlatforms(): Promise<ShoppingPlatform[]> {
  const response = await api.get<ShoppingPlatform[]>('/platforms')
  return response.data.map((platform) => ({
    ...platform,
    supported: platform.id === DUMMYJSON_PLATFORM_ID && platform.supported,
    connected: platform.id === DUMMYJSON_PLATFORM_ID ? platform.connected : false,
    status: platform.id === DUMMYJSON_PLATFORM_ID ? platform.status : 'NOT_CONFIGURED',
  }))
}

export async function searchRecommendations(intent: PurchaseIntent): Promise<{
  recommendations: ProductRecommendation[]
  total: number
}> {
  if (intent.platformId !== DUMMYJSON_PLATFORM_ID) {
    throw new Error('Recommendations are available only for the DummyJSON Demo Store.')
  }
  const response = await api.post<{
    total: number
    recommendations: Array<{
      product: ProductApiListResponse['products'][number]
      analysis: ProductRecommendation['analysis']
    }>
  }>('/recommendations/search', { intent })
  return {
    total: response.data.total,
    recommendations: response.data.recommendations.map(({ product, analysis }) => ({
      product: mapProduct(product),
      analysis,
    })),
  }
}

export async function createBackendOrder(intent: PurchaseIntent): Promise<BackendOrder> {
  if (intent.platformId !== DUMMYJSON_PLATFORM_ID) {
    throw new Error('Orders can be created only from the DummyJSON Demo Store.')
  }
  const response = await api.post<BackendOrder>('/orders', { intent })
  return {
    ...response.data,
    items: response.data.items.map(({ product, quantity }) => ({
      product: { ...product, id: Number(product.id) },
      quantity,
    })),
  }
}

export async function getBackendOrder(orderId: string): Promise<BackendOrder> {
  const response = await api.get<BackendOrder>(`/orders/${encodeURIComponent(orderId)}`)
  return {
    ...response.data,
    items: response.data.items.map(({ product, quantity }) => ({
      product: { ...product, id: Number(product.id) },
      quantity,
    })),
  }
}

export async function verifyBackendOrder(orderId: string): Promise<BackendVerification> {
  const response = await api.post<BackendVerification>('/verification/order', { order_id: orderId })
  return response.data
}

export async function approveBackendOrder(orderId: string, orderVersion: number): Promise<void> {
  await api.post(`/approvals/${encodeURIComponent(orderId)}/approve`, { order_version: orderVersion })
}

export async function createPayPalOrder(orderId: string): Promise<{ approval_url: string }> {
  const response = await api.post<{ approval_url: string }>('/payments/create-order', { order_id: orderId })
  return response.data
}

export async function capturePayPalOrder(paypalOrderId: string): Promise<{
  id: string | null
  order_id: string
  paypal_reference: string
  amount: number
  currency: 'USD' | 'INR'
  date: string
  status: string
  method: string
}> {
  const response = await api.post('/payments/capture-order', { paypal_order_id: paypalOrderId })
  return response.data
}

export async function getTransactions(): Promise<Transaction[]> {
  const response = await api.get<Array<{
    id: string
    order_id: string
    product: string
    amount: number
    currency: 'USD' | 'INR'
    date: string
    method: string
    status: 'Completed' | 'Failed'
    verification: string
  }>>('/transactions')
  return response.data.map((transaction) => ({
    ...transaction,
    orderId: transaction.order_id,
  }))
}

export async function getAuditEvents(): Promise<AuditEvent[]> {
  const response = await api.get<AuditEvent[]>('/audit')
  return response.data
}

export async function verifyBackendAudit(): Promise<{ valid: boolean; records_checked: number }> {
  const response = await api.post('/audit/verify-integrity')
  return response.data
}

export function getBackendError(error: unknown, fallback: string): string {
  if (typeof error === 'object' && error !== null && 'response' in error) {
    const response = (error as { response?: { status?: number; data?: { detail?: unknown } } }).response
    const detail = response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail.map((item) => {
        if (typeof item === 'string') return item
        if (typeof item === 'object' && item !== null && 'msg' in item && typeof item.msg === 'string') {
          return item.msg
        }
        return null
      }).filter((message): message is string => message !== null)
      if (messages.length) return messages.join(' ')
    }
    if (response?.status === 401) return 'Your session has expired. Sign in again to continue.'
    if (response?.status === 409) return 'The order changed since it was reviewed. Refresh the cart and verify it again.'
    if (response?.status === 503) return 'This backend service is temporarily unavailable or not configured.'
  }
  if (error instanceof Error && error.message && !error.message.startsWith('Request failed with status code')) {
    return error.message
  }
  return fallback
}
