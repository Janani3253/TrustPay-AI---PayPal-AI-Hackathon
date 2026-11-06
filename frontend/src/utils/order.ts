import type { CartItem, PurchaseIntent } from '../types'

export function getOrderFingerprint(cart: CartItem[], intent: PurchaseIntent | null): string {
  return JSON.stringify({
    intent: intent ? {
      request: intent.request,
      category: intent.category,
      requirements: intent.requirements,
      maximumBudget: intent.maximumBudget,
      currency: intent.currency,
      trustedSellersOnly: intent.trustedSellersOnly,
      platformId: intent.platformId,
    } : null,
    cart: [...cart]
      .sort((left, right) => left.product.id.localeCompare(right.product.id))
      .map(({ product, quantity }) => ({
        id: product.id,
        quantity,
        price: product.price,
        currency: product.currency,
        category: product.category,
        name: product.name,
        source: product.source,
      })),
  })
}
