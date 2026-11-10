import { api } from './api'
import { mapProduct } from './productService'
import type {
  AuditEvent,
  BackendOrder,
  BackendVerification,
  CartItem,
  ProductApiListResponse,
  ProductRecommendation,
  PurchaseIntent,
  TransactionDetails,
  Transaction,
} from '../types'

interface BackendCart {
  items: Array<{ product: ProductApiListResponse['products'][number]; quantity: number }>
}

export interface ShoppingPlatform {
  id: string
  name: string
  supported: boolean
  demo_only: boolean
  description: string
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

export async function getCart(): Promise<CartItem[]> {
  const response = await api.get<BackendCart>('/cart')
  return response.data.items.map(({ product, quantity }) => ({ product: mapProduct(product), quantity }))
}

export async function addCartProduct(productId: string): Promise<void> {
  await api.post('/cart/items', { product_id: Number(productId), quantity: 1 })
}

export async function updateCartProduct(productId: string, quantity: number): Promise<void> {
  await api.put(`/cart/items/${encodeURIComponent(productId)}`, { quantity })
}

export async function removeCartProduct(productId: string): Promise<void> {
  await api.delete(`/cart/items/${encodeURIComponent(productId)}`)
}

export async function getPlatforms(): Promise<ShoppingPlatform[]> {
  const response = await api.get<ShoppingPlatform[]>('/platforms')
  return response.data
}

export async function searchRecommendations(intent: PurchaseIntent): Promise<ProductRecommendation[]> {
  const response = await api.post<{
    recommendations: Array<{
      product: ProductApiListResponse['products'][number]
      analysis: ProductRecommendation['analysis']
    }>
  }>('/recommendations/search', { intent })
  return response.data.recommendations.map(({ product, analysis }) => ({
    product: mapProduct(product),
    analysis,
  }))
}

export async function createBackendOrder(intent: PurchaseIntent): Promise<BackendOrder> {
  const response = await api.post<BackendOrder>('/orders', { intent })
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

export async function createPayPalOrder(orderId: string): Promise<{
  order_id: string
  paypal_order_id: string
  approval_url: string
  status: string
}> {
  const response = await api.post<{
    order_id: string
    paypal_order_id: string
    approval_url: string
    status: string
  }>('/payments/create-order', { order_id: orderId }, { timeout: 120000 })
  return response.data
}

export interface BackendPaymentResult {
  id: string | null
  order_id: string
  paypal_reference: string | null
  amount: number
  currency: 'USD' | 'INR'
  date: string
  status: string
  method: string
  product?: string
  cart_cleared?: boolean
}

export async function capturePayPalOrder(paypalOrderId: string): Promise<BackendPaymentResult> {
  const response = await api.post<BackendPaymentResult>(
    '/payments/capture-order',
    { paypal_order_id: paypalOrderId },
    { timeout: 120000 },
  )
  return response.data
}

export async function cancelPayPalOrder(orderId: string): Promise<BackendPaymentResult> {
  const response = await api.post<BackendPaymentResult>(
    '/payments/cancel-order',
    { order_id: orderId },
    { timeout: 120000 },
  )
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

export async function getTransactionDetails(transactionId: string): Promise<TransactionDetails> {
  const response = await api.get<TransactionDetails>(
    `/transactions/${encodeURIComponent(transactionId)}`,
  )
  return response.data
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
    const response = (error as { response?: { data?: { detail?: unknown } } }).response
    if (typeof response?.data?.detail === 'string') return response.data.detail
  }
  if (error instanceof Error && error.message) return error.message
  return fallback
}
