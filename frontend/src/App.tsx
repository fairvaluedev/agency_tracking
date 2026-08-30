import { useAuth } from './context/AuthContext'
import Login from './pages/Login'
import Intake from './pages/Intake'
import Portal from './pages/Portal'

// Part I Step 14: "one screen per API module, starting with intake and portal (highest daily
// volume), finance and dashboard last." This is the real, working slice of that plan — routing
// picks the right screen from the roles auth_api.get_current_user actually returned, not a
// hardcoded guess. See BUILD_LOG.md for what's built here vs. the remaining screens per API
// module that follow this same established pattern.
export default function App() {
  const { user, loading, logout } = useAuth()

  if (loading) return <div className="page">Loading…</div>
  if (!user) return <Login />

  const isForeignAgency = user.roles.includes('Foreign Agency')
  const isInternalStaff = user.roles.some((r) =>
    ['Registrar', 'Manager', 'Admin', 'System Manager'].includes(r),
  )

  return (
    <div className="app-shell">
      <header className="app-header">
        <span>Agency Tracking</span>
        <span className="app-user">
          {user.full_name} ({user.roles.join(', ')})
          <button onClick={() => logout()}>Sign out</button>
        </span>
      </header>
      <main>
        {isForeignAgency && <Portal />}
        {!isForeignAgency && isInternalStaff && <Intake />}
        {!isForeignAgency && !isInternalStaff && (
          <div className="page">
            <p>Signed in, but no screen is built yet for your role ({user.roles.join(', ')}).</p>
          </div>
        )}
      </main>
    </div>
  )
}
