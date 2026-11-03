import { ShieldCheck } from 'lucide-react'

export function Brand({ light = false }: { light?: boolean }) {
  return <span className={`brand ${light ? 'brand-light' : ''}`}><span className="brand-mark"><ShieldCheck size={19} strokeWidth={2.2} /></span><span>trustpay<span className="brand-ai">.ai</span></span></span>
}
