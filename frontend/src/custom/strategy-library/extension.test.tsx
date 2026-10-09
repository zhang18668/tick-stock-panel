import { expect, it } from 'vitest'
import extension from './extension'

it('registers strategy library route and navigation item', () => {
  expect(extension.routes?.[0].path).toBe('/strategy-library')
  expect(extension.navigation?.[0].routeId).toBe(extension.routes?.[0].id)
})
