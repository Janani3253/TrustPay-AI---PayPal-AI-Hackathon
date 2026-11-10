import { useEffect } from 'react'
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { AppProvider } from './context/AppContext'
import { AppLayout } from './components/layout/AppLayout'
import { ToastViewport } from './components/common/ToastViewport'
import { useApp } from './context/AppContext'
import { BudgetPlannerPage } from './pages/BudgetPlannerPage'
import {
  ApprovalPage, AuditLogPage, CartPage, DashboardPage, LandingPage, LoginPage, PlatformSelectionPage,
  PaymentPage, ProductResultsPage, ProductsPage, RegisterPage, RequestPage,
  TransactionReceiptPage, TransactionsPage, VerificationPage,
} from './pages/Pages'

function ProtectedLayout() {
  const { user, authLoading } = useApp()
  const location = useLocation()
  if (authLoading) return <div className="panel api-state"><span className="spinner" /><p>Restoring your secure session…</p></div>
  return user ? <AppLayout /> : <Navigate to="/login" replace state={{ from: location }} />
}

function RequirePlatform() {
  const { selectedPlatformId, setSelectedPlatformId } = useApp()
  useEffect(() => {
    if (selectedPlatformId !== 'dummyjson') {
      setSelectedPlatformId('dummyjson')
    }
  }, [selectedPlatformId, setSelectedPlatformId])
  return <Outlet />
}

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <ToastViewport />
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route element={<ProtectedLayout />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/platforms" element={<PlatformSelectionPage />} />
            <Route element={<RequirePlatform />}>
              <Route path="/products" element={<ProductsPage />} />
              <Route path="/shopping-request" element={<RequestPage />} />
              <Route path="/product-results" element={<ProductResultsPage />} />
              <Route path="/cart" element={<CartPage />} />
              <Route path="/verification" element={<VerificationPage />} />
              <Route path="/approval" element={<ApprovalPage />} />
              <Route path="/payment" element={<PaymentPage />} />
            </Route>
            <Route path="/transactions" element={<TransactionsPage />} />
            <Route path="/transactions/:transactionId" element={<TransactionReceiptPage />} />
            <Route path="/budget-planner" element={<BudgetPlannerPage />} />
            <Route path="/audit-log" element={<AuditLogPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AppProvider>
  )
}
