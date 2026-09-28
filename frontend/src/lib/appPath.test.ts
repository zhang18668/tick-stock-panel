import { describe, expect, it } from 'vitest'

import { appPath, appRelativeLocation, normalizeBasePath } from './appPath'

describe('application base path', () => {
  it('normalizes a configured subpath for router and API use', () => {
    expect(normalizeBasePath('/quant/')).toBe('/quant')
    expect(appPath('/api/settings', '/quant/')).toBe('/quant/api/settings')
    expect(appPath('login?redirect=%2F', '/quant/')).toBe('/quant/login?redirect=%2F')
  })

  it('keeps root deployments unchanged', () => {
    expect(normalizeBasePath('/')).toBe('/')
    expect(appPath('/api/settings', '/')).toBe('/api/settings')
  })

  it('removes the configured base from login redirect locations', () => {
    expect(appRelativeLocation('/quant/watchlist?tab=mine', '/quant/')).toBe('/watchlist?tab=mine')
    expect(appRelativeLocation('/quant/', '/quant/')).toBe('/')
    expect(appRelativeLocation('/watchlist', '/quant/')).toBe('/watchlist')
  })
})
