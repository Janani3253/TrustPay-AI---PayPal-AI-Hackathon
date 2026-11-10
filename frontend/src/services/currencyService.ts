import type { Currency } from '../types'

export const USD_TO_INR_RATE = 83.0
export const INR_TO_USD_RATE = 1.0 / USD_TO_INR_RATE

export function getCurrencySymbol(currency: Currency): string {
  return currency === 'INR' ? '₹' : '$'
}

export function convertCurrency(amount: number, from: Currency, to: Currency): number {
  if (from === to) return amount
  if (from === 'USD' && to === 'INR') {
    return Math.round(amount * USD_TO_INR_RATE * 100) / 100
  }
  if (from === 'INR' && to === 'USD') {
    return Math.round(amount * INR_TO_USD_RATE * 100) / 100
  }
  return amount
}

export function formatMoney(amount: number, currency: Currency = 'USD'): string {
  const safeAmount = Number.isFinite(amount) ? amount : 0
  const symbol = getCurrencySymbol(currency)
  return `${symbol}${safeAmount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function formatMoneyWithCode(amount: number, currency: Currency = 'USD'): string {
  return `${formatMoney(amount, currency)} ${currency}`
}

export function getPlatformCurrencyNotice(currency: Currency, budget?: number): string {
  if (currency === 'INR') {
    const usdConverted = budget ? convertCurrency(budget, 'INR', 'USD') : null
    return usdConverted !== null
      ? `Selected catalogue (DummyJSON Demo Store) prices in USD. ₹${budget?.toLocaleString()} INR converts to approx. $${usdConverted.toFixed(2)} USD (rate: 1 USD = 83 INR).`
      : 'Selected catalogue prices in USD. INR budgets will be converted at authoritative rate 1 USD = 83 INR.'
  }
  return 'USD is the native API price currency of the selected DummyJSON Demo Store catalogue.'
}

