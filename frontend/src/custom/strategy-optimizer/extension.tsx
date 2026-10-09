import { BarChart3 } from 'lucide-react'
import type { FrontendExtension } from '../../extensions/types'
import { StrategyOptimizerPage } from './StrategyOptimizerPage'

const extension: FrontendExtension = {
  id: 'strategy.optimizer', apiVersion: 1,
  routes: [{ id: 'strategy-optimizer.page', path: '/strategy-optimizer', component: StrategyOptimizerPage }],
  navigation: [{ id: 'strategy-optimizer.nav', routeId: 'strategy-optimizer.page', label: '策略优化', icon: BarChart3, order: 65 }],
}
export default extension
