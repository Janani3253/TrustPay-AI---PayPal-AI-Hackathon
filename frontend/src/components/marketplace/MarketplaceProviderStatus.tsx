import { AlertCircle, CheckCircle2, Clock3, ShieldAlert } from 'lucide-react'
import type { MarketplaceProvider, MarketplaceProviderName } from '../../types'

const labels: Record<MarketplaceProviderName, string> = {
  AMAZON: 'Amazon India',
  FLIPKART: 'Flipkart India',
  MYNTRA: 'Myntra India',
  DEMO: 'DummyJSON Demo Store',
}

const statusDetails = {
  CONNECTED: { label: 'Connected', Icon: CheckCircle2, className: 'provider-connected' },
  NOT_CONFIGURED: { label: 'Not configured', Icon: AlertCircle, className: 'provider-not-configured' },
  TEMPORARILY_UNAVAILABLE: { label: 'Temporarily unavailable', Icon: Clock3, className: 'provider-unavailable' },
  AUTHENTICATION_FAILED: { label: 'Authentication failed', Icon: ShieldAlert, className: 'provider-auth-failed' },
}

interface Props {
  providers: MarketplaceProvider[]
  loading: boolean
  error: string
  selected: 'ALL' | MarketplaceProviderName
  onSelect: (provider: 'ALL' | MarketplaceProviderName) => void
  onRetry: () => void
}

export function MarketplaceProviderStatus({ providers, loading, error, selected, onSelect, onRetry }: Props) {
  const knownProviders: MarketplaceProviderName[] = ['AMAZON', 'FLIPKART', 'MYNTRA', 'DEMO']
  return (
    <section className="marketplace-provider-panel" aria-label="Marketplace providers">
      <div className="marketplace-filter-heading">
        <div><b>Marketplace</b><small>Provider status is reported by the backend.</small></div>
        <span className="eyebrow">{loading ? 'CHECKING PROVIDERS' : error ? 'STATUS UNAVAILABLE' : 'BACKEND STATUS'}</span>
      </div>
      <div className="marketplace-filter-list">
        <button type="button" className={`marketplace-filter-chip ${selected === 'ALL' ? 'selected' : ''}`} onClick={() => onSelect('ALL')}>All catalogues</button>
        {knownProviders.map((name) => {
          const provider = providers.find((item) => item.name === name)
          const status = provider ? statusDetails[provider.status] : null
          const StatusIcon = status?.Icon
          return (
            <button type="button" key={name} className={`marketplace-filter-chip ${selected === name ? 'selected' : ''}`} onClick={() => onSelect(name)}>
              <span>{labels[name]}</span>
              <small className={status?.className ?? 'provider-unknown'}>
                {StatusIcon ? <StatusIcon size={13} /> : <AlertCircle size={13} />}
                {status?.label ?? (loading ? 'Checking…' : error ? 'Status unavailable' : 'Status not reported')}
              </small>
            </button>
          )
        })}
      </div>
      {error && <div className="provider-status-note"><AlertCircle size={14} /><span>{error}</span><button type="button" className="btn btn-outline btn-sm" onClick={onRetry}>Retry status</button></div>}
    </section>
  )
}
