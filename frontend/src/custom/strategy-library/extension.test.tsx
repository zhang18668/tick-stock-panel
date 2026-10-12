import { expect, it } from 'vitest'
import extension from './extension'

it('registers strategy library route and navigation item', () => {
  expect(extension.routes?.[0].path).toBe('/strategy-library')
  expect(extension.navigation?.[0].routeId).toBe(extension.routes?.[0].id)
})

it('registers custom strategy backtesting in the same extension', () => {
  expect(extension.routes?.map(route => route.path)).toEqual(['/strategy-library', '/custom-strategies'])
  expect(extension.navigation?.map(item => item.label)).toEqual(['策略库', '自定义策略'])
  expect(extension.navigation?.[1]?.routeId).toBe(extension.routes?.[1]?.id)
})
