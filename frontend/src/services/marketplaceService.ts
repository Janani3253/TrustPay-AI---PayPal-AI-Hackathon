import { api } from './api'
import type {
  MarketplaceProduct,
  MarketplaceProvider,
  MarketplaceProviderName,
  MarketplaceProviderStatus,
  Product,
} from '../types'

const providerNames: MarketplaceProviderName[] = ['AMAZON', 'FLIPKART', 'MYNTRA', 'DEMO']
const providerStatuses: MarketplaceProviderStatus[] = [
  'CONNECTED',
  'NOT_CONFIGURED',
  'TEMPORARILY_UNAVAILABLE',
  'AUTHENTICATION_FAILED',
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function httpUrl(value: unknown): string | null | undefined {
  if (value === null) return null
  if (typeof value !== 'string') return undefined
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : undefined
  } catch {
    return undefined
  }
}

function toMarketplaceProduct(value: unknown): MarketplaceProduct {
  if (!isRecord(value) || typeof value.id !== 'string' || typeof value.title !== 'string'
      || typeof value.provider !== 'string' || !providerNames.includes(value.provider as MarketplaceProviderName)
      || typeof value.external_product_id !== 'string') {
    throw new Error('The product API returned data that does not match the marketplace product contract.')
  }
  const id = value.id
  const externalProductId = value.external_product_id
  const title = value.title
  const provider = value.provider as MarketplaceProviderName

  const optionalString = (field: unknown): string | null | undefined => {
    if (field === null) return null
    return typeof field === 'string' ? field : undefined
  }
  const optionalNumber = (field: unknown): number | null | undefined => {
    if (field === null) return null
    return typeof field === 'number' && Number.isFinite(field) ? field : undefined
  }

  return {
    id,
    external_product_id: externalProductId,
    provider,
    title,
    description: optionalString(value.description),
    image_url: httpUrl(value.image_url),
    price: optionalNumber(value.price),
    currency: optionalString(value.currency) ?? null,
    category: optionalString(value.category),
    rating: optionalNumber(value.rating),
    product_url: httpUrl(value.product_url),
    seller_name: optionalString(value.seller_name),
    seller_verified: value.seller_verified === null
      ? null
      : typeof value.seller_verified === 'boolean' ? value.seller_verified : undefined,
    specifications: isRecord(value.specifications) ? value.specifications : null,
    source_updated_at: optionalString(value.source_updated_at),
  }
}

function toDemoMarketplaceProduct(product: Product): MarketplaceProduct {
  return {
    id: product.id,
    external_product_id: product.id,
    provider: 'DEMO',
    title: product.name,
    description: product.description,
    image_url: product.image,
    price: product.price,
    currency: product.currency,
    category: product.category,
    rating: product.rating,
    product_url: null,
    seller_name: null,
    seller_verified: null,
    specifications: Object.fromEntries(product.specifications.map((specification, index) => [`specification_${index + 1}`, specification])),
    source_updated_at: null,
  }
}

function extractProducts(response: unknown): MarketplaceProduct[] {
  const values = Array.isArray(response)
    ? response
    : isRecord(response) && Array.isArray(response.products)
      ? response.products
      : null
  if (!values) throw new Error('The marketplace search response must contain a products array.')
  return values.map(toMarketplaceProduct)
}

export async function getMarketplaceProviders(): Promise<MarketplaceProvider[]> {
  const response = await api.get<{ providers: unknown }>('/products/providers')
  if (!Array.isArray(response.data.providers)) {
    throw new Error('The marketplace provider response is missing its providers array.')
  }
  return response.data.providers.map((value: unknown) => {
    if (!isRecord(value) || typeof value.name !== 'string'
        || !providerNames.includes(value.name as MarketplaceProviderName)
        || typeof value.connected !== 'boolean'
        || typeof value.status !== 'string'
        || !providerStatuses.includes(value.status as MarketplaceProviderStatus)) {
      throw new Error('The marketplace provider response does not match the documented provider contract.')
    }
    return {
      name: value.name as MarketplaceProviderName,
      connected: value.connected,
      status: value.status as MarketplaceProviderStatus,
      message: typeof value.message === 'string' ? value.message : undefined,
    }
  })
}

export async function searchMarketplaceProducts(
  query: string,
  provider?: MarketplaceProviderName,
  category?: string,
): Promise<MarketplaceProduct[]> {
  const response = await api.get<unknown>('/products/search', {
    params: { q: query.trim(), ...(provider ? { provider } : {}), ...(category ? { category } : {}) },
  })
  return extractProducts(response.data)
}

export function mapDemoProducts(products: Product[]): MarketplaceProduct[] {
  return products.map(toDemoMarketplaceProduct)
}
