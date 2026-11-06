import { api } from './api'
import { DUMMYJSON_PLATFORM_ID } from './productService'
import type { Currency, PurchaseIntent } from '../types'

export async function extractIntent(
  request: string,
  budget?: number,
  category?: string,
  trustedSellersOnly = true,
  currency: Currency = 'USD',
  platformId = DUMMYJSON_PLATFORM_ID,
): Promise<PurchaseIntent> {
  if (platformId !== DUMMYJSON_PLATFORM_ID) {
    throw new Error('Only the DummyJSON Demo Store is available for shopping requests.')
  }
  const effectiveBudget = typeof budget === 'number' && budget > 0 ? budget : undefined
  try {
    const response = await api.post<PurchaseIntent & { original_request?: string }>('/ai/analyze-intent', {
      request,
      maximumBudget: effectiveBudget,
      currency,
      category: category ?? '',
      trustedSellersOnly,
      platformId,
    })
    const data = response.data
    const intentObj = data.intent
    const maxBudget = intentObj?.max_budget ?? data.maximumBudget ?? (effectiveBudget || 1000)
    const categoryVal = intentObj?.category || data.category || (category || '')
    const currencyVal = (intentObj?.currency || data.currency || currency || 'USD') as Currency
    const brandList = intentObj?.brand || data.brand || []
    const quantityVal = intentObj?.quantity ?? data.quantity ?? 1
    const featureList = intentObj?.features || data.features || []

    return {
      ...data,
      request: data.request || request,
      original_request: data.original_request || request,
      category: categoryVal,
      maximumBudget: maxBudget,
      currency: currencyVal,
      trustedSellersOnly,
      platformId: DUMMYJSON_PLATFORM_ID,
      brand: brandList,
      quantity: quantityVal,
      features: featureList,
      requirements: data.requirements?.length ? data.requirements : [
        ...brandList.map((b) => ({ name: 'Brand', value: b })),
        ...featureList.map((f) => ({ name: 'Feature', value: f })),
      ],
      intent: {
        category: categoryVal,
        brand: brandList,
        max_budget: maxBudget,
        currency: currencyVal,
        features: featureList,
        quantity: quantityVal,
      },
    }
  } catch {
    try {
      const fallback = await api.post<PurchaseIntent>('/intent/parse', {
        request,
        maximumBudget: effectiveBudget || 1000,
        currency,
        category: category ?? '',
        trustedSellersOnly,
        platformId,
      })
      const data = fallback.data
      return {
        ...data,
        request: data.request || request,
        original_request: request,
        platformId: DUMMYJSON_PLATFORM_ID,
      }
    } catch {
      return {
        request,
        original_request: request,
        category: category ?? '',
        requirements: [],
        maximumBudget: effectiveBudget || 1000,
        currency,
        trustedSellersOnly,
        platformId: DUMMYJSON_PLATFORM_ID,
        intent: {
          category: category ?? '',
          brand: [],
          max_budget: effectiveBudget || 1000,
          currency,
          features: [],
          quantity: 1,
        },
      }
    }
  }
}
