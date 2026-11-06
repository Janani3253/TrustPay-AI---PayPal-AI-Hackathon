import { api } from './api'
import type { Product, ProductApiListResponse, ProductApiProduct, ProductCategory } from '../types'

export const DUMMYJSON_PLATFORM_ID = 'dummyjson'

export function mapProduct(item: ProductApiProduct): Product {
  return {
    id: String(item.id),
    name: item.title,
    description: item.description,
    category: item.category,
    price: item.price,
    currency: 'USD',
    seller: null,
    sellerVerified: false,
    rating: item.rating,
    image: item.thumbnail || item.images[0] || '',
    specifications: [
      item.brand ? `Brand: ${item.brand}` : null,
      item.sku ? `SKU: ${item.sku}` : null,
      typeof item.weight === 'number' ? `Weight: ${item.weight} (unit not specified by API)` : null,
      item.dimensions ? `Dimensions: ${item.dimensions.width} × ${item.dimensions.height} × ${item.dimensions.depth}` : null,
      item.availabilityStatus ? `Availability: ${item.availabilityStatus}` : null,
    ].filter((value): value is string => value !== null),
    source: 'DummyJSON',
  }
}

export interface ProductListOptions {
  query?: string
  category?: string
  limit?: number
  skip?: number
  platform?: string
}

export async function getProductList(options: ProductListOptions = {}): Promise<ProductApiListResponse> {
  const { query, category, limit = 24, skip = 0, platform = DUMMYJSON_PLATFORM_ID } = options
  const cleanQuery = query?.trim()
  const path = cleanQuery && !category ? '/products/search' : '/products'
  const response = await api.get<ProductApiListResponse>(path, {
    params: {
      ...(cleanQuery ? { q: cleanQuery } : {}),
      ...(category ? { category } : {}),
      limit,
      skip,
      platform,
    },
  })
  return response.data
}

export async function getProducts(options: ProductListOptions = {}): Promise<Product[]> {
  const response = await getProductList(options)
  return response.products.map(mapProduct)
}

export async function getProduct(id: string, platform = DUMMYJSON_PLATFORM_ID): Promise<Product> {
  const response = await api.get<ProductApiProduct>(`/products/${encodeURIComponent(id)}`, { params: { platform } })
  return mapProduct(response.data)
}

export async function getProductCategories(platform = DUMMYJSON_PLATFORM_ID): Promise<ProductCategory[]> {
  const response = await api.get<ProductCategory[]>('/products/categories', { params: { platform } })
  return response.data
}

export const productDataSource = 'TrustPay API · DummyJSON catalogue'
