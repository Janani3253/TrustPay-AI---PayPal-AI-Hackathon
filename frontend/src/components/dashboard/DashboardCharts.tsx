import { useState } from 'react'
import {
  Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'

const activityData = [
  { name: 'May', value: 18 }, { name: 'Jun', value: 23 }, { name: 'Jul', value: 20 },
  { name: 'Aug', value: 32 }, { name: 'Sep', value: 28 }, { name: 'Oct', value: 42 },
]
const paymentData = [
  { name: 'Verified', value: 82, color: '#14b887' },
  { name: 'Warnings', value: 13, color: '#f5aa42' },
  { name: 'Blocked', value: 5, color: '#e35b64' },
]

export default function DashboardCharts() {
  const [period, setPeriod] = useState('Last 6 months')
  const visibleActivity = period === 'Last 3 months' ? activityData.slice(-3) : activityData
  return <div className="dashboard-grid"><section className="panel chart-panel"><div className="panel-heading"><div><h2>Shopping activity</h2><p>Your verified transactions over time</p></div><select className="select-button" aria-label="Shopping activity period" value={period} onChange={(event) => setPeriod(event.target.value)}><option>Last 3 months</option><option>Last 6 months</option><option>This year</option></select></div><div className="chart-area"><ResponsiveContainer width="100%" height="100%"><AreaChart data={visibleActivity} margin={{ left: -20, right: 5, top: 14 }}><defs><linearGradient id="activityFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#315ef6" stopOpacity={0.17} /><stop offset="100%" stopColor="#315ef6" stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="#edf0f5" vertical={false} /><XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fill: '#8a94a9', fontSize: 12 }} /><YAxis tickLine={false} axisLine={false} tick={{ fill: '#8a94a9', fontSize: 12 }} /><Tooltip /><Area type="monotone" dataKey="value" stroke="#315ef6" strokeWidth={2.5} fill="url(#activityFill)" /></AreaChart></ResponsiveContainer></div></section><section className="panel payment-panel"><div className="panel-heading"><div><h2>Payment health</h2><p>IntentLock order outcomes</p></div></div><div className="donut-wrap"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={paymentData} dataKey="value" innerRadius={62} outerRadius={82} paddingAngle={4} stroke="none">{paymentData.map((item) => <Cell key={item.name} fill={item.color} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer><div className="donut-center"><strong>248</strong><span>orders</span></div></div><div className="legend-list">{paymentData.map((item) => <div key={item.name}><span><i style={{ background: item.color }} />{item.name}</span><b>{item.value}%</b></div>)}</div></section></div>
}
