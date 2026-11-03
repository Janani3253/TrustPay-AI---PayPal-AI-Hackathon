import { api } from './api'
import type { Currency, PurchaseIntent } from '../types'

export async function extractIntent(
  request: string,
  budget: number,
  category?: string,
  trustedSellersOnly = true,
  currency: Currency = 'INR',
  platformId = 'dummyjson',
): Promise<PurchaseIntent> {
  const response = await api.post<PurchaseIntent>('/intent/parse', {
    request,
    maximumBudget: budget,
    currency,
    category: category ?? '',
    trustedSellersOnly,
    platformId,
  })
  return response.data
}
