import { api } from './api'
import { DUMMYJSON_PLATFORM_ID } from './productService'
import type { Currency, PurchaseIntent } from '../types'

export async function extractIntent(
  request: string,
  budget: number,
  category?: string,
  trustedSellersOnly = true,
  currency: Currency = 'INR',
  platformId = DUMMYJSON_PLATFORM_ID,
): Promise<PurchaseIntent> {
  if (platformId !== DUMMYJSON_PLATFORM_ID) {
    throw new Error('Only the DummyJSON Demo Store is available for shopping requests.')
  }
  try {
    const response = await api.post<PurchaseIntent>('/intent/parse', {
      request,
      maximumBudget: budget,
      currency,
      category: category ?? '',
      trustedSellersOnly,
      platformId,
    })
    return { ...response.data, platformId: DUMMYJSON_PLATFORM_ID }
  } catch (error: unknown) {
    // If backend returns 503 because Gemini AI is unconfigured, create the policy directly from customer inputs
    const status = (error as { response?: { status?: number } })?.response?.status
    if (status === 503) {
      return {
        request,
        category: category ?? '',
        requirements: [],
        maximumBudget: budget,
        currency,
        trustedSellersOnly,
        platformId: DUMMYJSON_PLATFORM_ID,
      }
    }
    throw error
  }
}
