import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { updateCart, type CartTotals } from '../services/cartService'
import type { AuditRecord, BackendOrder, BackendVerification, CartItem, Product, PurchaseIntent, Transaction } from '../types'
import { clearAuthToken, getCurrentUser, type DemoUser } from '../services/authService'
import { getBackendError, getCart, getTransactions } from '../services/backendService'
import { DUMMYJSON_PLATFORM_ID } from '../services/productService'
import { getOrderFingerprint } from '../utils/order'

interface AppContextValue {
  user: DemoUser | null
  authLoading: boolean
  selectedPlatformId: string | null
  cart: CartItem[]
  cartTotals: CartTotals | null
  cartSyncError: string | null
  intent: PurchaseIntent | null
  backendOrder: BackendOrder | null
  backendVerification: BackendVerification | null
  transactions: Transaction[]
  transactionsSyncError: string | null
  approved: boolean
  verified: boolean
  verifiedFingerprint: string | null
  auditRecords: AuditRecord[]
  toasts: ToastNotice[]
  setUser: (user: DemoUser | null) => void
  setSelectedPlatformId: (platformId: string) => void
  replaceCart: (cart: CartItem[], totals?: CartTotals | null) => void
  setBackendOrder: (order: BackendOrder | null) => void
  setBackendVerification: (verification: BackendVerification | null) => void
  addToCart: (product: Product) => void
  setQuantity: (productId: string, quantity: number) => void
  removeFromCart: (productId: string) => void
  setIntent: (intent: PurchaseIntent) => void
  setApproved: (approved: boolean) => void
  setVerified: (verified: boolean) => void
  recordAudit: (type: string, description: string) => void
  notify: (message: string, tone?: ToastTone) => void
  dismissToast: (id: string) => void
  addTransaction: (transaction: Transaction) => void
  clearCart: () => void
}

export type ToastTone = 'success' | 'error' | 'info'

export interface ToastNotice {
  id: string
  message: string
  tone: ToastTone
}

const AppContext = createContext<AppContextValue | null>(null)

function getStored<T>(key: string, fallback: T): T {
  const stored = localStorage.getItem(key)
  if (!stored) return fallback
  try {
    return JSON.parse(stored) as T
  } catch (error) {
    console.error(`Could not read saved ${key} data.`, error)
    return fallback
  }
}

function getStoredIntent(userId: number): PurchaseIntent | null {
  const stored = getStored<unknown>(`trustpay-intent-${userId}`, null)
  if (!stored || typeof stored !== 'object') return null
  const intent = stored as PurchaseIntent
  if (intent.platformId && !['dummyjson', 'demo', 'dummy'].includes(intent.platformId)) return null
  return { ...intent, platformId: DUMMYJSON_PLATFORM_ID }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<DemoUser | null>(null)
  const [authLoading, setAuthLoading] = useState(() => Boolean(localStorage.getItem('trustpay-access-token')))
  const [selectedPlatformId, setSelectedPlatformId] = useState<string | null>(() => (
    getStored('trustpay-platform-id', DUMMYJSON_PLATFORM_ID) || DUMMYJSON_PLATFORM_ID
  ))
  const [cart, setCart] = useState<CartItem[]>([])
  const [cartTotals, setCartTotals] = useState<CartTotals | null>(null)
  const [cartSyncError, setCartSyncError] = useState<string | null>(null)
  const [intent, setIntent] = useState<PurchaseIntent | null>(null)
  const [backendOrder, setBackendOrder] = useState<BackendOrder | null>(null)
  const [backendVerification, setBackendVerification] = useState<BackendVerification | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [transactionsSyncError, setTransactionsSyncError] = useState<string | null>(null)
  const [toasts, setToasts] = useState<ToastNotice[]>([])
  const [verificationFingerprint, setVerificationFingerprint] = useState<string | null>(null)
  const [approvalFingerprint, setApprovalFingerprint] = useState<string | null>(null)
  const [auditRecords, setAuditRecords] = useState<AuditRecord[]>(() => getStored('trustpay-audit-records', []))
  const fingerprint = getOrderFingerprint(cart, intent)
  const verified = cart.length > 0 && verificationFingerprint === fingerprint
  const approved = verified && approvalFingerprint === fingerprint
  const recordAudit = useCallback((type: string, description: string) => setAuditRecords((current) => [...current, {
    id: crypto.randomUUID(),
    type,
    timestamp: new Date().toISOString(),
    description,
  }]), [])
  const notify = useCallback((message: string, tone: ToastTone = 'success') => {
    const id = crypto.randomUUID()
    setToasts((current) => [...current.slice(-3), { id, message, tone }])
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 4500)
  }, [])
  const dismissToast = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  useEffect(() => {
    localStorage.removeItem('trustpay-cart')
    localStorage.removeItem('trustpay-transactions')
    localStorage.removeItem('trustpay-verification-fingerprint')
    localStorage.removeItem('trustpay-approval-fingerprint')
    localStorage.removeItem('trustpay-user')
    localStorage.removeItem('trustpay-intent')
  }, [])

  useEffect(() => {
    let active = true
    const token = localStorage.getItem('trustpay-access-token')
    if (!token) return () => { active = false }
    getCurrentUser()
      .then((currentUser) => {
        if (active) {
          setUser(currentUser)
          setIntent(getStoredIntent(currentUser.id))
        }
      })
      .catch((error: unknown) => {
        console.error('Could not restore the backend session.', error)
        if (active) {
          notify(getBackendError(error, 'Could not restore the backend session. Please sign in again.'), 'error')
          clearAuthToken()
          setUser(null)
          setCart([])
          setCartTotals(null)
          setTransactions([])
          setIntent(null)
          setBackendOrder(null)
          setBackendVerification(null)
          setApprovalFingerprint(null)
          setVerificationFingerprint(null)
          setSelectedPlatformId(DUMMYJSON_PLATFORM_ID)
        }
      })
      .finally(() => { if (active) setAuthLoading(false) })
    return () => { active = false }
  }, [notify])

  useEffect(() => {
    if (!user) return
    let active = true
    getCart()
      .then((remoteCart) => {
        if (active) {
          setCart(remoteCart.items)
          setCartTotals(remoteCart.totals)
          setCartSyncError(null)
        }
      })
      .catch((error: unknown) => {
        console.error('Could not synchronize cart data with the backend.', error)
        if (active) {
          const message = getBackendError(error, 'The backend cart could not be loaded.')
          setCartSyncError(message)
          notify(message, 'error')
        }
      })
    getTransactions()
      .then((remoteTransactions) => {
        if (active) {
          setTransactions(remoteTransactions)
          setTransactionsSyncError(null)
        }
      })
      .catch((error: unknown) => {
        console.error('Could not synchronize transactions with the backend.', error)
        if (active) {
          const message = getBackendError(error, 'Transactions could not be loaded from the backend.')
          setTransactionsSyncError(message)
          notify(message, 'error')
        }
      })
    return () => { active = false }
  }, [user, notify])

  useEffect(() => localStorage.setItem('trustpay-platform-id', JSON.stringify(selectedPlatformId)), [selectedPlatformId])
  useEffect(() => localStorage.setItem('trustpay-audit-records', JSON.stringify(auditRecords)), [auditRecords])

  const value = useMemo<AppContextValue>(() => ({
    user,
    authLoading,
    selectedPlatformId,
    cart,
    cartTotals,
    cartSyncError,
    intent,
    backendOrder,
    backendVerification,
    transactions,
    transactionsSyncError,
    approved,
    verified,
    verifiedFingerprint: verified ? fingerprint : null,
    auditRecords,
    toasts,
    setUser: (nextUser) => {
      if (!nextUser || (user && user.id !== nextUser.id)) {
        if (!nextUser) clearAuthToken()
        if (user) localStorage.removeItem(`trustpay-intent-${user.id}`)
        setCart([])
        setCartTotals(null)
        setCartSyncError(null)
        setTransactions([])
        setTransactionsSyncError(null)
        setIntent(null)
        setBackendOrder(null)
        setBackendVerification(null)
        setApprovalFingerprint(null)
        setVerificationFingerprint(null)
        setSelectedPlatformId(DUMMYJSON_PLATFORM_ID)
      }
      if (nextUser) setIntent(getStoredIntent(nextUser.id))
      setUser(nextUser)
    },
    setSelectedPlatformId: (platformId) => {
      if (platformId !== DUMMYJSON_PLATFORM_ID) return
      if (selectedPlatformId === platformId) return
      setSelectedPlatformId(platformId)
      setIntent(null)
      setBackendOrder(null)
      setBackendVerification(null)
      setApprovalFingerprint(null)
      setVerificationFingerprint(null)
      setCart([])
      setCartTotals(null)
      notify('Shopping platform selected. Your previous order state was cleared.')
    },
    replaceCart: (nextCart, totals) => {
      setCart(nextCart)
      if (totals !== undefined) setCartTotals(totals)
      setCartSyncError(null)
    },
    addToCart: (product) => {
      setCart((current) => updateCart(current, product))
      setCartTotals(null)
      setCartSyncError(null)
      getCart()
        .then((remoteCart) => {
          setCart(remoteCart.items)
          setCartTotals(remoteCart.totals)
          setCartSyncError(null)
        })
        .catch((error: unknown) => {
          console.error('Could not refresh authoritative cart totals.', error)
          const message = getBackendError(error, 'The backend cart could not be refreshed.')
          setCartSyncError(message)
          notify(message, 'error')
        })
      setApprovalFingerprint(null)
      setVerificationFingerprint(null)
      setBackendOrder(null)
      setBackendVerification(null)
      setAuditRecords((current) => [
        ...current,
        { id: crypto.randomUUID(), type: 'Product selected', timestamp: new Date().toISOString(), description: `Selected API product ${product.name} (${product.id}).` },
        ...(cart.length === 0 ? [{ id: crypto.randomUUID(), type: 'Cart created', timestamp: new Date().toISOString(), description: 'Created a cart using current Demo Product API data.' }] : []),
      ])
      notify(`${product.name} added to your cart.`)
    },
    setQuantity: (productId, quantity) => {
      setCart((current) => current.map((item) => item.product.id === productId ? { ...item, quantity: Math.max(1, quantity) } : item))
      setCartTotals(null)
      setApprovalFingerprint(null)
      setVerificationFingerprint(null)
      setBackendOrder(null)
      setBackendVerification(null)
      notify('Cart quantity updated. Verification and approval were cleared.')
    },
    removeFromCart: (productId) => {
      setCart((current) => current.filter((item) => item.product.id !== productId))
      setCartTotals(null)
      setApprovalFingerprint(null)
      setVerificationFingerprint(null)
      setBackendOrder(null)
      setBackendVerification(null)
      notify('Product removed from cart. Verification and approval were cleared.', 'info')
    },
    setIntent: (nextIntent) => {
      if (nextIntent.platformId !== DUMMYJSON_PLATFORM_ID) return
      setIntent(nextIntent)
      if (user) localStorage.setItem(`trustpay-intent-${user.id}`, JSON.stringify(nextIntent))
      setApprovalFingerprint(null)
      setVerificationFingerprint(null)
      setBackendOrder(null)
      setBackendVerification(null)
      setAuditRecords((current) => [...current, {
        id: crypto.randomUUID(),
        type: 'Purchase policy created',
        timestamp: new Date().toISOString(),
        description: `Created purchase policy for ${nextIntent.category || 'the requested category'} with a ${nextIntent.currency} ${nextIntent.maximumBudget} limit.`,
      }])
      notify('Purchase policy saved.')
    },
    setApproved: (value) => {
      if (!value) {
        setApprovalFingerprint(null)
        notify('Order approval was withdrawn.', 'info')
        return
      }
      if (verified) {
        setApprovalFingerprint(fingerprint)
        setAuditRecords((current) => [...current, {
          id: crypto.randomUUID(),
          type: 'Customer approval recorded',
          timestamp: new Date().toISOString(),
          description: 'Customer approved the exact order snapshot after verification.',
        }])
        notify('Exact order approval recorded.')
      }
    },
    setVerified: (value) => {
      setVerificationFingerprint(value && cart.length > 0 ? fingerprint : null)
      if (value && cart.length > 0) setAuditRecords((current) => [...current, {
        id: crypto.randomUUID(),
        type: 'IntentLock verification completed',
        timestamp: new Date().toISOString(),
        description: 'Completed the frontend demonstration checks against the current order snapshot.',
      }])
      if (value && cart.length > 0) notify('IntentLock verification completed.')
    },
    recordAudit,
    notify,
    dismissToast,
    addTransaction: (transaction) => setTransactions((current) => [transaction, ...current]),
    clearCart: () => {
      setCart([])
      setCartTotals(null)
      setApprovalFingerprint(null)
      setVerificationFingerprint(null)
      setBackendOrder(null)
      setBackendVerification(null)
    },
    setBackendOrder: (order) => {
      setBackendOrder(order)
      setBackendVerification(null)
      setApprovalFingerprint(null)
      setVerificationFingerprint(null)
    },
    setBackendVerification: (verification) => setBackendVerification(verification),
  }), [user, authLoading, selectedPlatformId, cart, cartTotals, cartSyncError, intent, backendOrder, backendVerification, transactions, transactionsSyncError, approved, verified, fingerprint, auditRecords, toasts, recordAudit, notify, dismissToast])

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

// The provider and hook are colocated to keep the shared state implementation together.
// eslint-disable-next-line react-refresh/only-export-components
export function useApp() {
  const context = useContext(AppContext)
  if (!context) throw new Error('useApp must be used within AppProvider')
  return context
}
