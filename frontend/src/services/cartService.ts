import type { CartItem, Product } from '../types'

export interface CartTotals {
  subtotal: number
  shipping: number
  tax: number
  total: number
  currency: Product['currency'] | null
  hasMixedCurrencies: boolean
}

export function updateCart(cart: CartItem[], product: Product): CartItem[] {
  const existing = cart.find((item) => item.product.id === product.id)
  return existing
    ? cart.map((item) => item.product.id === product.id ? { ...item, quantity: item.quantity + 1 } : item)
    : [...cart, { product, quantity: 1 }]
}

export function calculateCartTotals(cart: CartItem[]): CartTotals {
  const currencies = new Set(cart.map(({ product }) => product.currency))
  const currency = currencies.size === 1 ? cart[0]?.product.currency ?? null : null
  const subtotal = cart.reduce((total, item) => total + item.product.price * item.quantity, 0)
  const shipping = subtotal > 0 ? 9.99 : 0
  const tax = Math.round(subtotal * 0.05 * 100) / 100
  return { subtotal, shipping, tax, total: subtotal + shipping + tax, currency, hasMixedCurrencies: currencies.size > 1 }
}
