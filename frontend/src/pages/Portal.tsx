import { useEffect, useState } from 'react'
import { listPortalCandidates, selectCandidate, type PortalCandidate } from '../api/client'

export default function Portal() {
  const [candidates, setCandidates] = useState<PortalCandidate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selecting, setSelecting] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setCandidates(await listPortalCandidates())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load candidates')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function handleSelect(applicantName: string) {
    setSelecting(applicantName)
    setError(null)
    try {
      const placement: any = await selectCandidate(applicantName)
      setSelected(`${applicantName} → Placement ${placement.name} (${placement.status})`)
      // Part A.2 Stage 4: the instant one agency selects, they vanish from every agency's
      // view — reload to prove it against the live backend, not just trust the response.
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Selection failed')
    } finally {
      setSelecting(null)
    }
  }

  return (
    <div className="page">
      <h1>Portal — Available Candidates</h1>
      {loading && <p>Loading…</p>}
      {error && <p className="error">{error}</p>}
      {selected && <p className="success">Selected: {selected}</p>}
      <div className="candidate-grid">
        {candidates.map((c) => (
          <div key={c.name} className="card candidate-card">
            <h3>{c.full_name}</h3>
            <p>{c.name}</p>
            <p>
              {c.gender} · {c.nationality} · born {c.date_of_birth}
            </p>
            <p>
              {c.target_job} · {c.education}
            </p>
            <button onClick={() => handleSelect(c.name)} disabled={selecting === c.name}>
              {selecting === c.name ? 'Selecting…' : 'Select this candidate'}
            </button>
          </div>
        ))}
        {!loading && candidates.length === 0 && <p>No candidates currently available for your country.</p>}
      </div>
    </div>
  )
}
