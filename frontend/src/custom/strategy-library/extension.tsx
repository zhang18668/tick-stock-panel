import { LibraryBig } from 'lucide-react'
import type { FrontendExtension } from '../../extensions/types'
import { StrategyLibraryPage } from './StrategyLibraryPage'

const extension: FrontendExtension = {
  id: 'strategy.library',
  apiVersion: 1,
  routes: [{ id: 'strategy-library.page', path: '/strategy-library', component: StrategyLibraryPage }],
  navigation: [{ id: 'strategy-library.nav', routeId: 'strategy-library.page', label: '策略库', icon: LibraryBig, order: 64 }],
}
export default extension
