// Part F: session-cookie auth for everyone, every client-facing operation a whitelisted
// function (never raw /api/resource/*). This client is the one place that talks to the
// backend — every page calls through here, never fetch() directly.

const METHOD_BASE = '/api/method'

let csrfToken: string | null = null

export class ApiError extends Error {}

function extractErrorMessage(data: any, status: number): string {
  if (data?._server_messages) {
    try {
      const messages = JSON.parse(data._server_messages)
      const first = JSON.parse(messages[0])
      if (first.message) return first.message
    } catch {
      // fall through to generic messages below
    }
  }
  if (data?.exception) return String(data.exception).split(':').pop()?.trim() || data.exception
  return `Request failed (${status})`
}

async function request<T = any>(
  method: string,
  args: Record<string, unknown> = {},
  httpMethod: 'GET' | 'POST' = 'POST',
): Promise<T> {
  let url = `${METHOD_BASE}/${method}`
  const options: RequestInit = { method: httpMethod, credentials: 'include' }

  if (httpMethod === 'GET') {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(args)) {
      if (value !== undefined && value !== null) params.set(key, String(value))
    }
    const qs = params.toString()
    if (qs) url += `?${qs}`
  } else {
    options.headers = {
      'Content-Type': 'application/json',
      ...(csrfToken ? { 'X-Frappe-CSRF-Token': csrfToken } : {}),
    }
    options.body = JSON.stringify(args)
  }

  const res = await fetch(url, options)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new ApiError(extractErrorMessage(data, res.status))
  }
  return data.message as T
}

export async function fetchCsrfToken(): Promise<void> {
  csrfToken = await request<string>('agency_tracking.auth_api.get_csrf_token', {}, 'GET')
}

export async function login(usr: string, pwd: string): Promise<void> {
  const res = await fetch(`${METHOD_BASE}/login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ usr, pwd }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new ApiError(extractErrorMessage(data, res.status))
  }
  await fetchCsrfToken()
}

export async function logout(): Promise<void> {
  await request('logout', {}, 'POST')
  csrfToken = null
}

export interface CurrentUser {
  user: string
  full_name: string
  roles: string[]
}

// null means "no session" (Guest) — a normal, expected outcome (allow_guest=True on the
// backend specifically so this is a clean 200 response, not a caught exception).
export async function getCurrentUser(): Promise<CurrentUser | null> {
  return request<CurrentUser | null>('agency_tracking.auth_api.get_current_user', {}, 'GET')
}

// Applicant / CV (Part I Steps 1-2)
export const createApplicant = (data: Record<string, unknown>) =>
  request('agency_tracking.applicant_api.create_applicant', data, 'POST')

export const registerApplicant = (applicant_name: string) =>
  request('agency_tracking.applicant_api.register_applicant', { applicant_name }, 'POST')

export const getApplicant = (applicant_name: string) =>
  request('agency_tracking.applicant_api.get_applicant', { applicant_name }, 'GET')

export const generateCV = (applicant_name: string) =>
  request('agency_tracking.cv_api.generate_cv', { applicant_name }, 'POST')

// Portal (Part I Step 3)
export interface PortalCandidate {
  name: string
  full_name: string
  gender: string
  nationality: string
  date_of_birth: string
  target_job: string
  education: string
  photograph: string
}

export const listPortalCandidates = () =>
  request<PortalCandidate[]>('agency_tracking.portal_api.list_portal_candidates', {}, 'GET')

export const selectCandidate = (applicant_name: string, free_replacement_for_complaint?: string) =>
  request('agency_tracking.portal_api.select_candidate', { applicant_name, free_replacement_for_complaint }, 'POST')
