import { LibraryBig, FlaskConical } from 'lucide-react'
import type { FrontendExtension } from '../../extensions/types'
import { StrategyLibraryPage } from './StrategyLibraryPage'
import { CustomStrategyBacktestPage } from './CustomStrategyBacktestPage'

const extension: FrontendExtension = {
  id: 'strategy.library',
  apiVersion: 1,
  routes: [
    { id: 'strategy-library.page', path: '/strategy-library', component: StrategyLibraryPage },
    { id: 'custom-strategies.page', path: '/custom-strategies', component: CustomStrategyBacktestPage },
  ],
  navigation: [
    { id: 'strategy-library.nav', routeId: 'strategy-library.page', label: '策略库', icon: LibraryBig, order: 64 },
    { id: 'custom-strategies.nav', routeId: 'custom-strategies.page', label: '自定义策略', icon: FlaskConical, order: 65 },
  ],
}
export default extension
