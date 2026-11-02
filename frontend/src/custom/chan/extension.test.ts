import { expect, it, vi } from 'vitest'
import extension from './extension'

it('以独立路由和左侧快捷入口接入，冲突时入口一并隔离', async () => {
  vi.resetModules()
  const registry = await import('@/extensions/registry')
  await registry.loadFrontendExtensions({ chan: async () => ({ default: extension }) })
  registry.finalizeFrontendExtensions(new Set(['/watchlist']))
  expect(registry.getFrontendExtensionRoutes()).toMatchObject([{ path: '/chan-analysis', extensionId: 'chan.analysis' }, { path: '/chan-review', extensionId: 'chan.analysis' }])
  expect(registry.getFrontendSlotRegistrations('layout.header.quick')).toMatchObject([{ id: 'chan-shortcut' }])
  expect(registry.getFrontendExtensionNavigation()).toMatchObject([{ routeId: 'chan-review', label: '缠论复盘' }])
  vi.resetModules()
  const conflicting = await import('@/extensions/registry')
  await conflicting.loadFrontendExtensions({ chan: async () => ({ default: extension }) })
  conflicting.finalizeFrontendExtensions(new Set(['/chan-analysis']))
  expect(conflicting.getFrontendExtensionRoutes()).toEqual([])
  expect(conflicting.getFrontendSlotRegistrations('layout.header.quick')).toEqual([])
  expect(conflicting.getFrontendExtensionLoadErrors()).toHaveLength(1)
})
