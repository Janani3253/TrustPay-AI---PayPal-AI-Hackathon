import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react'
import { useApp } from '../../context/AppContext'

const icons = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
}

export function ToastViewport() {
  const { toasts, dismissToast } = useApp()

  return (
    <div className="toast-viewport" aria-live="polite" aria-label="Action notifications">
      {toasts.map((toast) => {
        const Icon = icons[toast.tone]
        return (
          <div className={`action-toast toast-${toast.tone}`} key={toast.id} role={toast.tone === 'error' ? 'alert' : 'status'}>
            <Icon size={18} aria-hidden="true" />
            <span>{toast.message}</span>
            <button type="button" className="toast-dismiss" aria-label="Dismiss notification" onClick={() => dismissToast(toast.id)}>
              <X size={16} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
