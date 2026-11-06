import type { Transaction } from '../types'
import { formatMoney } from '../services/currencyService'

export { formatMoney }

export const initialTransactions: Transaction[] = [
  { id: 'TRX-29814', orderId: 'ORD-84721', product: 'Wireless headphones', amount: 12990, currency: 'INR', date: '2026-10-28', method: 'PayPal Sandbox Demo', status: 'Completed', verification: 'Demo verified' },
  { id: 'TRX-29802', orderId: 'ORD-84690', product: 'Smart home hub', amount: 8990, currency: 'INR', date: '2026-10-25', method: 'PayPal Sandbox Demo', status: 'Completed', verification: 'Demo verified' },
  { id: 'TRX-29776', orderId: 'ORD-84517', product: 'Laptop accessories', amount: 6490, currency: 'INR', date: '2026-10-22', method: 'PayPal Sandbox Demo', status: 'Failed', verification: 'Warning' },
]

export const formatINR = (amount: number) => formatMoney(amount, 'INR')
