import { api } from './api'
import type { Product, ProductApiListResponse, ProductApiProduct, ProductCategory } from '../types'

export function mapProduct(item: ProductApiProduct): Product {
  return {
    id: String(item.id),
    name: item.title,
    description: item.description,
    category: item.category,
    price: item.price,
    currency: item.currency ?? 'USD',
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

export async function getProducts(options: { query?: string; category?: string; limit?: number } = {}): Promise<Product[]> {
  const { query, category, limit = 200 } = options
  const response = await api.get<ProductApiListResponse>('/products', {
    params: { ...(query?.trim() ? { q: query.trim() } : {}), ...(category ? { category } : {}), limit },
  })
  return response.data.products.map(mapProduct)
}

export async function getProduct(id: string): Promise<Product> {
  const response = await api.get<ProductApiProduct>(`/products/${encodeURIComponent(id)}`)
  return mapProduct(response.data)
}

export async function getProductCategories(): Promise<ProductCategory[]> {
  const response = await api.get<ProductCategory[]>('/products/categories')
  return response.data
}

export const productDataSource = 'TrustPay API · DummyJSON catalogue'
