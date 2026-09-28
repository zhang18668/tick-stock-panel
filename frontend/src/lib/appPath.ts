export function normalizeBasePath(baseUrl = import.meta.env.BASE_URL): string {
  const normalized = `/${baseUrl}`.replace(/\/+/g, '/').replace(/\/$/, '')
  return normalized || '/'
}

export function appPath(path: string, baseUrl = import.meta.env.BASE_URL): string {
  const base = normalizeBasePath(baseUrl)
  const suffix = path.startsWith('/') ? path : `/${path}`
  return base === '/' ? suffix : `${base}${suffix}`
}

export function appRelativeLocation(location: string, baseUrl = import.meta.env.BASE_URL): string {
  const base = normalizeBasePath(baseUrl)
  if (base === '/' || (location !== base && !location.startsWith(`${base}/`))) return location
  return location.slice(base.length) || '/'
}
