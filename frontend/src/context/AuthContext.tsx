import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { type CurrentUser, fetchCsrfToken, getCurrentUser, login as apiLogin, logout as apiLogout } from '../api/client'

interface AuthContextValue {
  user: CurrentUser | null
  loading: boolean
  login: (usr: string, pwd: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // A page refresh still has a valid session cookie — re-derive who's logged in rather than
    // forcing a fresh login every time. get_current_user is allow_guest=True and returns null
    // for an anonymous session (a normal 200, not a thrown error) specifically so this check
    // never produces a console-visible network failure on an ordinary cold page load — the
    // CSRF token is fetched only once we know there's an actual session to fetch it for.
    ;(async () => {
      try {
        const info = await getCurrentUser()
        if (info) {
          await fetchCsrfToken()
          setUser(info)
        }
      } catch {
        setUser(null)
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  async function login(usr: string, pwd: string) {
    await apiLogin(usr, pwd)
    setUser(await getCurrentUser())
  }

  async function logout() {
    await apiLogout()
    setUser(null)
  }

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
