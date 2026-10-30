import { lazy, Suspense } from 'react'
import { NavLink } from 'react-router-dom'
import { ChartNoAxesCombined } from 'lucide-react'
import type { FrontendExtension } from '@/extensions/types'

const Page = lazy(() => import('./ChanAnalysisPage').then(m => ({ default: m.ChanAnalysisPage })))

function ChanEntry() {
  return <NavLink to="/chan-analysis" aria-label="打开缠论分析" title="缠论分析"
    className={({ isActive }) => `group flex h-7 min-w-0 flex-1 items-center justify-center gap-1 rounded-md border transition-colors duration-150 ${isActive
      ? 'border-accent/40 bg-accent/10 text-accent'
      : 'border-border/60 bg-elevated/25 text-secondary hover:border-border hover:bg-elevated hover:text-foreground'}`}>
    <ChartNoAxesCombined className="h-3 w-3 shrink-0" />
    <span className="whitespace-nowrap text-[11px] leading-none">缠论</span>
  </NavLink>
}

function ChanRoute() {
  return <Suspense fallback={<div className="p-6 text-sm text-muted">加载缠论分析…</div>}><Page /></Suspense>
}

const extension: FrontendExtension = {
  id: 'chan.analysis', apiVersion: 1,
  routes: [{ id: 'chan-analysis', path: '/chan-analysis', component: ChanRoute }],
  slots: [{ name: 'layout.header.quick', id: 'chan-shortcut', order: 20, component: ChanEntry }],
}
export default extension
