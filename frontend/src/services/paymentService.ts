import type { Currency, Transaction } from '../types'

export async function simulatePayment(amount: number, product: string, currency: Currency): Promise<Transaction> {
  await new Promise((resolve) => window.setTimeout(resolve, 900))
  return {
    id: `TRX-${Math.floor(10000 + Math.random() * 89999)}`,
    orderId: `ORD-${Math.floor(10000 + Math.random() * 89999)}`,
    product,
    amount,
    currency,
    date: new Date().toISOString().slice(0, 10),
    method: 'PayPal Sandbox Demo',
    status: Math.random() < 0.9 ? 'Completed' : 'Failed',
    verification: 'Verified',
  }
}
