import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { AlertTriangle, Bell, CalendarDays, Check, CircleDollarSign, Clock3, Pencil, Plus, Trash2, WalletCards, X } from 'lucide-react'
import { useApp } from '../context/AppContext'
import { formatMoney } from '../mock/data'
import type { Currency, Transaction } from '../types'

type BudgetPeriod = 'daily' | 'weekly' | 'monthly' | 'yearly' | 'total'

interface BudgetPlan {
  period: BudgetPeriod
  amount: number
}

interface ManualExpense {
  id: string
  label: string
  amount: number
  date: string
}

interface PlannerData {
  currency: Currency
  plans: BudgetPlan[]
  expenses: ManualExpense[]
}

interface SpendingEntry {
  id: string
  label: string
  amount: number
  currency: Currency
  date: string
  source: 'Purchase' | 'Manual'
}

const periods: { id: BudgetPeriod; label: string; caption: string }[] = [
  { id: 'daily', label: 'Daily budget', caption: 'Today' },
  { id: 'weekly', label: 'Weekly budget', caption: 'This week' },
  { id: 'monthly', label: 'Monthly budget', caption: 'This month' },
  { id: 'yearly', label: 'Yearly budget', caption: 'This year' },
  { id: 'total', label: 'Total budget', caption: 'All time' },
]

const emptyPlanner: PlannerData = { currency: 'USD', plans: [], expenses: [] }

function localDateKey(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function readPlannerData(key: string): PlannerData {
  const saved = localStorage.getItem(key)
  if (!saved) return emptyPlanner
  try {
    const parsed: unknown = JSON.parse(saved)
    if (!parsed || typeof parsed !== 'object') return emptyPlanner
    const data = parsed as Partial<PlannerData>
    return {
      currency: data.currency === 'INR' ? 'INR' : 'USD',
      plans: Array.isArray(data.plans)
        ? data.plans.filter((plan): plan is BudgetPlan =>
          !!plan && periods.some(({ id }) => id === plan.period)
          && typeof plan.amount === 'number' && Number.isFinite(plan.amount) && plan.amount > 0)
        : [],
      expenses: Array.isArray(data.expenses)
        ? data.expenses.filter((expense): expense is ManualExpense =>
          !!expense && typeof expense.id === 'string'
          && typeof expense.label === 'string'
          && typeof expense.amount === 'number' && Number.isFinite(expense.amount) && expense.amount > 0
          && typeof expense.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(expense.date))
        : [],
    }
  } catch (error) {
    console.error('Could not read saved Budget Planner data.', error)
    return emptyPlanner
  }
}

function periodStart(period: BudgetPeriod, today: Date): string {
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  if (period === 'weekly') {
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7))
  } else if (period === 'monthly') {
    start.setDate(1)
  } else if (period === 'yearly') {
    start.setMonth(0, 1)
  }
  return localDateKey(start)
}

function getSpending(
  period: BudgetPeriod,
  entries: SpendingEntry[],
  today: Date,
): number {
  if (period === 'total') {
    return entries.reduce((sum, entry) => sum + entry.amount, 0)
  }
  const firstDay = periodStart(period, today)
  const lastDay = localDateKey(today)
  return entries.reduce(
    (sum, entry) => sum + (entry.date >= firstDay && entry.date <= lastDay ? entry.amount : 0),
    0,
  )
}

function displayDate(value: string): string {
  const [year, month, day] = value.slice(0, 10).split('-').map(Number)
  if (!year || !month || !day) return value
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
    .format(new Date(year, month - 1, day))
}

function PeriodProgress({ amount, spent, currency }: { amount: number; spent: number; currency: Currency }) {
  const percentage = amount > 0 ? spent / amount * 100 : 0
  const clampedPercentage = Math.min(percentage, 100)
  const progressTone = percentage >= 100 ? 'over' : percentage >= 80 ? 'warning' : 'safe'
  return (
    <>
      <div className="budget-progress-label">
        <span>{Math.round(percentage)}% used</span>
        <span>{formatMoney(Math.max(0, amount - spent), currency)} remaining</span>
      </div>
      <div
        className={`budget-progress-track ${progressTone}`}
        role="progressbar"
        aria-label="Budget spending progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.min(Math.round(percentage), 100)}
      >
        <span style={{ width: `${clampedPercentage}%` }} />
      </div>
      {spent > amount && (
        <p className="budget-overage">{formatMoney(spent - amount, currency)} over budget</p>
      )}
    </>
  )
}

export function BudgetPlannerPage() {
  const { user, transactions, notify } = useApp()
  const storageKey = `trustpay-budget-planner-v1:${user?.id ?? 'guest'}`
  const [data, setData] = useState<PlannerData>(() => readPlannerData(storageKey))
  const [planDialog, setPlanDialog] = useState(false)
  const [editingPeriod, setEditingPeriod] = useState<BudgetPeriod | null>(null)
  const [planPeriod, setPlanPeriod] = useState<BudgetPeriod>('monthly')
  const [planAmount, setPlanAmount] = useState('')
  const [expenseDialog, setExpenseDialog] = useState(false)
  const [expenseLabel, setExpenseLabel] = useState('')
  const [expenseAmount, setExpenseAmount] = useState('')
  const [expenseDate, setExpenseDate] = useState(() => localDateKey(new Date()))
  const [formError, setFormError] = useState('')
  const [today, setToday] = useState(() => new Date())

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(data))
    } catch (error) {
      console.error('Could not save Budget Planner data.', error)
      notify('Budget Planner changes could not be saved in this browser.', 'error')
    }
  }, [data, notify, storageKey])

  useEffect(() => {
    const now = new Date()
    const nextMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)
    const timer = window.setTimeout(() => setToday(new Date()), nextMidnight.getTime() - now.getTime() + 10)
    return () => window.clearTimeout(timer)
  }, [today])

  const entries = useMemo<SpendingEntry[]>(() => [
    ...data.expenses.map((expense) => ({
      ...expense,
      currency: data.currency,
      source: 'Manual' as const,
    })),
    ...transactions
      .filter((transaction) => transaction.status === 'Completed' && transaction.currency === data.currency)
      .map((transaction: Transaction) => ({
        id: `transaction-${transaction.id}`,
        label: transaction.product || 'Completed purchase',
        amount: transaction.amount,
        currency: transaction.currency,
        date: transaction.date.slice(0, 10),
        source: 'Purchase' as const,
      })),
  ], [data.currency, data.expenses, transactions])

  const recentSpending = useMemo(
    () => [...entries].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 6),
    [entries],
  )
  const activePlans = useMemo(
    () => periods.flatMap((period) => {
      const plan = data.plans.find((item) => item.period === period.id)
      return plan ? [{ ...period, amount: plan.amount, spent: getSpending(period.id, entries, today) }] : []
    }),
    [data.plans, entries, today],
  )
  const alerts = useMemo(() => {
    const result: {
      key: string
      message: string
      tone: 'notice' | 'warning' | 'critical'
      plan: (typeof activePlans)[number]
    }[] = []
    const thresholds = [
      { threshold: 100, message: 'Your budget has been fully used.', tone: 'critical' },
      { threshold: 80, message: 'You have used at least 80% of your budget.', tone: 'warning' },
      { threshold: 50, message: 'You have used at least 50% of your budget.', tone: 'notice' },
    ] as const

    activePlans.forEach((plan) => {
      const percentage = plan.amount > 0 ? plan.spent / plan.amount * 100 : 0
      thresholds.forEach((alert) => {
        if (percentage >= alert.threshold) {
          result.push({
            key: `${plan.id}-${alert.threshold}`,
            message: alert.message,
            tone: alert.tone,
            plan,
          })
        }
      })
      if (percentage > 100) {
        result.unshift({
          key: `${plan.id}-exceeded`,
          message: `You are ${formatMoney(plan.spent - plan.amount, data.currency)} over budget.`,
          tone: 'critical',
          plan,
        })
      }
    })
    return result
  }, [activePlans, data.currency])

  const openNewPlan = () => {
    const firstAvailable = periods.find(({ id }) => !data.plans.some((plan) => plan.period === id))
    if (!firstAvailable) {
      notify('All budget periods already have plans. Edit an existing plan instead.', 'info')
      return
    }
    setEditingPeriod(null)
    setPlanPeriod(firstAvailable.id)
    setPlanAmount('')
    setFormError('')
    setPlanDialog(true)
  }

  const openEditPlan = (period: BudgetPeriod, amount: number) => {
    setEditingPeriod(period)
    setPlanPeriod(period)
    setPlanAmount(String(amount))
    setFormError('')
    setPlanDialog(true)
  }

  const savePlan = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const amount = Number(planAmount)
    if (!Number.isFinite(amount) || amount <= 0) {
      setFormError('Enter a budget amount greater than zero.')
      return
    }
    if (!editingPeriod && data.plans.some((plan) => plan.period === planPeriod)) {
      setFormError('A plan already exists for this period. Edit that plan instead.')
      return
    }
    setData((current) => ({
      ...current,
      plans: editingPeriod
        ? current.plans.map((plan) => plan.period === editingPeriod ? { ...plan, amount } : plan)
        : [...current.plans, { period: planPeriod, amount }],
    }))
    setPlanDialog(false)
    notify(editingPeriod ? 'Budget plan updated.' : 'Budget plan created.')
  }

  const deletePlan = (period: BudgetPeriod) => {
    setData((current) => ({
      ...current,
      plans: current.plans.filter((plan) => plan.period !== period),
    }))
    notify('Budget plan removed.', 'info')
  }

  const addExpense = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const amount = Number(expenseAmount)
    if (!expenseLabel.trim() || !Number.isFinite(amount) || amount <= 0) {
      setFormError('Enter a description and an amount greater than zero.')
      return
    }
    setData((current) => ({
      ...current,
      expenses: [{
        id: crypto.randomUUID(),
        label: expenseLabel.trim(),
        amount,
        date: expenseDate,
      }, ...current.expenses],
    }))
    setExpenseDialog(false)
    setExpenseLabel('')
    setExpenseAmount('')
    setExpenseDate(localDateKey(new Date()))
    setFormError('')
    notify('Spending entry added.')
  }

  const todaySpent = getSpending('daily', entries, today)
  const weekSpent = getSpending('weekly', entries, today)
  const monthSpent = getSpending('monthly', entries, today)
  const yearSpent = getSpending('yearly', entries, today)
  const allSpent = getSpending('total', entries, today)

  return (
    <div className="budget-planner-page">
      <div className="page-title-row">
        <div>
          <div className="eyebrow">PERSONAL FINANCE</div>
          <h1>Budget Planner</h1>
          <p>Set spending limits and keep an eye on your progress.</p>
        </div>
        <div className="budget-page-actions">
          <button className="btn btn-outline" onClick={() => { setFormError(''); setExpenseDialog(true) }}><Plus size={16} /> Add spending</button>
          <button className="btn btn-primary" onClick={openNewPlan} disabled={data.plans.length === periods.length}><Plus size={16} /> Create budget</button>
        </div>
      </div>

      <div className="budget-summary-grid">
        <article className="budget-summary-card">
          <span className="budget-summary-icon blue"><CalendarDays size={18} /></span>
          <div><small>Spent today</small><strong>{formatMoney(todaySpent, data.currency)}</strong></div>
        </article>
        <article className="budget-summary-card">
          <span className="budget-summary-icon blue"><CalendarDays size={18} /></span>
          <div><small>Spent this week</small><strong>{formatMoney(weekSpent, data.currency)}</strong></div>
        </article>
        <article className="budget-summary-card">
          <span className="budget-summary-icon green"><WalletCards size={18} /></span>
          <div><small>Spent this month</small><strong>{formatMoney(monthSpent, data.currency)}</strong></div>
        </article>
        <article className="budget-summary-card">
          <span className="budget-summary-icon green"><WalletCards size={18} /></span>
          <div><small>Spent this year</small><strong>{formatMoney(yearSpent, data.currency)}</strong></div>
        </article>
        <article className="budget-summary-card">
          <span className="budget-summary-icon amber"><CircleDollarSign size={18} /></span>
          <div><small>Total recorded spending</small><strong>{formatMoney(allSpent, data.currency)}</strong></div>
        </article>
      </div>

      <section className="budget-section">
        <div className="panel-heading budget-section-heading">
          <div><h2>Your budgets</h2><p>Progress is based on completed purchases and spending you add here.</p></div>
          {data.plans.length > 0 && data.plans.length < periods.length && <button className="text-link" onClick={openNewPlan}><Plus size={15} /> Add plan</button>}
        </div>
        {activePlans.length === 0 ? (
          <div className="panel budget-empty-state">
            <span className="budget-empty-icon"><WalletCards size={22} /></span>
            <h3>Start with a budget plan</h3>
            <p>Create a daily, weekly, monthly, yearly, or total budget. Your planner is independent of checkout.</p>
            <button className="btn btn-primary" onClick={openNewPlan}><Plus size={16} /> Create your first budget</button>
          </div>
        ) : (
          <div className="budget-plan-grid">
            {activePlans.map((plan) => {
              const remaining = plan.amount - plan.spent
              return (
                <article className="panel budget-plan-card" key={plan.id}>
                  <div className="budget-plan-heading">
                    <span className="budget-period-icon"><CalendarDays size={17} /></span>
                    <div><h3>{plan.label}</h3><small>{plan.caption}</small></div>
                    <button className="icon-btn" onClick={() => openEditPlan(plan.id, plan.amount)} aria-label={`Edit ${plan.label}`} title="Edit budget"><Pencil size={15} /></button>
                    <button className="icon-btn budget-delete-btn" onClick={() => deletePlan(plan.id)} aria-label={`Delete ${plan.label}`} title="Delete budget"><Trash2 size={15} /></button>
                  </div>
                  <div className="budget-plan-totals">
                    <div><small>Spent</small><strong>{formatMoney(plan.spent, data.currency)}</strong></div>
                    <div><small>Budget</small><strong>{formatMoney(plan.amount, data.currency)}</strong></div>
                  </div>
                  <PeriodProgress amount={plan.amount} spent={plan.spent} currency={data.currency} />
                  <div className={`budget-remaining ${remaining < 0 ? 'is-over' : ''}`}>
                    {remaining < 0 ? 'Over budget' : 'Remaining'}
                    <strong>{formatMoney(Math.abs(remaining), data.currency)}</strong>
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </section>

      <div className="budget-detail-grid">
        <section className="panel budget-activity-panel">
          <div className="panel-heading budget-section-heading">
            <div><h2>Recent spending</h2><p>Latest recorded purchases and manual entries</p></div>
            <Clock3 size={17} />
          </div>
          {recentSpending.length === 0 ? (
            <div className="budget-activity-empty">No spending recorded yet. Add an entry to start tracking your budget.</div>
          ) : (
            <div className="budget-spending-list">
              {recentSpending.map((entry) => (
                <div className="budget-spending-row" key={entry.id}>
                  <span className={`budget-entry-icon ${entry.source === 'Purchase' ? 'purchase' : 'manual'}`}>
                    {entry.source === 'Purchase' ? <Check size={16} /> : <CircleDollarSign size={16} />}
                  </span>
                  <div className="budget-spending-copy">
                    <strong>{entry.label}</strong>
                    <small>{entry.source} · {displayDate(entry.date)}</small>
                  </div>
                  <strong className="budget-spending-amount">−{formatMoney(entry.amount, entry.currency)}</strong>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel budget-alerts-panel">
          <div className="panel-heading budget-section-heading">
            <div><h2>Budget alerts</h2><p>Alerts appear at 50%, 80%, 100%, and over budget.</p></div>
            <Bell size={17} />
          </div>
          {alerts.length === 0 ? (
            <div className="budget-alert-empty"><span><Check size={16} /></span><div><strong>All on track</strong><small>No budget thresholds reached.</small></div></div>
          ) : (
            <div className="budget-alert-list">
              {alerts.map((alert) => (
                <div className={`budget-alert-item ${alert.tone}`} key={alert.key}>
                  <AlertTriangle size={16} />
                  <div><strong>{alert.plan.label}</strong><small>{alert.message}</small></div>
                </div>
              ))}
            </div>
          )}
          <p className="budget-disclaimer">Planner totals are informational and never block checkout.</p>
        </section>
      </div>

      {planDialog && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPlanDialog(false) }}>
          <form className="modal-card budget-form" role="dialog" aria-modal="true" onSubmit={savePlan} aria-labelledby="budget-plan-form-title">
            <button type="button" className="modal-close icon-btn" onClick={() => setPlanDialog(false)} aria-label="Close budget form"><X size={18} /></button>
            <span className="budget-modal-icon"><WalletCards size={19} /></span>
            <h2 id="budget-plan-form-title">{editingPeriod ? 'Edit budget plan' : 'Create budget plan'}</h2>
            <p>Choose a time period and spending limit. This planner does not affect checkout.</p>
            <label className="field-label">Budget period
              <select value={planPeriod} disabled={!!editingPeriod} onChange={(event) => setPlanPeriod(event.target.value as BudgetPeriod)}>
                {periods.map((period) => <option key={period.id} value={period.id} disabled={!editingPeriod && data.plans.some((plan) => plan.period === period.id)}>{period.label}</option>)}
              </select>
            </label>
            <label className="field-label">Budget amount ({data.currency})
              <input className="budget-text-input" type="number" min="0.01" step="0.01" required value={planAmount} onChange={(event) => setPlanAmount(event.target.value)} placeholder="e.g. 500" />
            </label>
            {formError && <p className="form-error" role="alert">{formError}</p>}
            <div className="budget-form-actions">
              <button type="button" className="btn btn-outline" onClick={() => setPlanDialog(false)}>Cancel</button>
              <button type="submit" className="btn btn-primary">{editingPeriod ? 'Save changes' : 'Create budget'}</button>
            </div>
          </form>
        </div>
      )}

      {expenseDialog && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setExpenseDialog(false) }}>
          <form className="modal-card budget-form" role="dialog" aria-modal="true" onSubmit={addExpense} aria-labelledby="budget-expense-form-title">
            <button type="button" className="modal-close icon-btn" onClick={() => setExpenseDialog(false)} aria-label="Close spending form"><X size={18} /></button>
            <span className="budget-modal-icon"><CircleDollarSign size={19} /></span>
            <h2 id="budget-expense-form-title">Add spending</h2>
            <p>Record an expense in {data.currency}. Completed TrustPay purchases are included automatically.</p>
            <label className="field-label">Description
              <input className="budget-text-input" type="text" maxLength={100} required value={expenseLabel} onChange={(event) => setExpenseLabel(event.target.value)} placeholder="e.g. Groceries" />
            </label>
            <label className="field-label">Amount ({data.currency})
              <input className="budget-text-input" type="number" min="0.01" step="0.01" required value={expenseAmount} onChange={(event) => setExpenseAmount(event.target.value)} placeholder="e.g. 42.50" />
            </label>
            <label className="field-label">Date
              <input className="budget-text-input" type="date" max={localDateKey(new Date())} required value={expenseDate} onChange={(event) => setExpenseDate(event.target.value)} />
            </label>
            {formError && <p className="form-error" role="alert">{formError}</p>}
            <div className="budget-form-actions">
              <button type="button" className="btn btn-outline" onClick={() => setExpenseDialog(false)}>Cancel</button>
              <button type="submit" className="btn btn-primary">Add spending</button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
