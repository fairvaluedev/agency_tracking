import { useState, type FormEvent } from 'react'
import { createApplicant, generateCV, registerApplicant } from '../api/client'

// Matches applicant.py's STANDARD_REGISTERED_REQUIRED_FIELDS (Step 1) — photograph/
// passport_scan are plain URL text fields here rather than a real upload widget; wiring
// Frappe's multipart file-upload endpoint is flagged as out of scope for this pass (see
// BUILD_LOG.md), everything else in this form is real and goes to the live backend.
const initialForm = {
  full_name: '',
  gender: 'Female',
  nationality: 'Ethiopia',
  phone: '',
  address: '',
  national_id: '',
  labor_id: '',
  destination_country: 'Kuwait',
  salary_amount: '',
  salary_currency: 'KWD',
  religion: 'Muslim',
  marital_status: 'Single',
  emergency_contact_name: '',
  emergency_contact_phone: '',
  passport_number: '',
  passport_issue_date: '',
  passport_expiry_date: '',
  passport_issue_place: '',
  date_of_birth: '',
  education: 'High School',
  target_job: '',
  photograph: '/files/placeholder.jpg',
  passport_scan: '/files/placeholder.pdf',
  medical_status: 'FIT',
}

export default function Intake() {
  const [form, setForm] = useState(initialForm)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{ name: string; status: string } | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function update(field: keyof typeof initialForm, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setResult(null)
    setSubmitting(true)
    try {
      setStatus('Creating Draft…')
      const applicant: any = await createApplicant({ entry_track: 'Standard', ...form })
      setStatus('Registering…')
      const registered: any = await registerApplicant(applicant.name)
      setResult({ name: registered.name, status: registered.status })
      setStatus(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
      setStatus(null)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleGenerateCV() {
    if (!result) return
    setError(null)
    setSubmitting(true)
    try {
      const cv: any = await generateCV(result.name)
      setResult({ name: result.name, status: cv.applicant_status })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'CV generation failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page">
      <h1>Intake — Register a Candidate</h1>
      <form className="card form-grid" onSubmit={handleSubmit}>
        <label>
          Full name
          <input value={form.full_name} onChange={(e) => update('full_name', e.target.value)} required />
        </label>
        <label>
          Gender
          <select value={form.gender} onChange={(e) => update('gender', e.target.value)}>
            <option>Female</option>
            <option>Male</option>
            <option>Other</option>
          </select>
        </label>
        <label>
          Nationality (Country)
          <input value={form.nationality} onChange={(e) => update('nationality', e.target.value)} required />
        </label>
        <label>
          Phone
          <input value={form.phone} onChange={(e) => update('phone', e.target.value)} required />
        </label>
        <label className="span-2">
          Address
          <input value={form.address} onChange={(e) => update('address', e.target.value)} required />
        </label>

        <hr className="span-2" />

        <label>
          National ID
          <input value={form.national_id} onChange={(e) => update('national_id', e.target.value)} required />
        </label>
        <label>
          Labor ID
          <input value={form.labor_id} onChange={(e) => update('labor_id', e.target.value)} required />
        </label>
        <label>
          Destination Country
          <select value={form.destination_country} onChange={(e) => update('destination_country', e.target.value)}>
            <option>Kuwait</option>
            <option>Saudi Arabia</option>
          </select>
        </label>
        <label>
          Target Job
          <input value={form.target_job} onChange={(e) => update('target_job', e.target.value)} required />
        </label>
        <label>
          Salary Amount
          <input
            type="number"
            value={form.salary_amount}
            onChange={(e) => update('salary_amount', e.target.value)}
            required
          />
        </label>
        <label>
          Salary Currency
          <select value={form.salary_currency} onChange={(e) => update('salary_currency', e.target.value)}>
            <option>KWD</option>
            <option>SAR</option>
            <option>USD</option>
          </select>
        </label>
        <label>
          Marital Status
          <select value={form.marital_status} onChange={(e) => update('marital_status', e.target.value)}>
            <option>Single</option>
            <option>Married</option>
            <option>Divorced</option>
            <option>Widowed</option>
          </select>
        </label>
        <label>
          Religion
          <input value={form.religion} onChange={(e) => update('religion', e.target.value)} required />
        </label>
        <label>
          Emergency Contact Name
          <input
            value={form.emergency_contact_name}
            onChange={(e) => update('emergency_contact_name', e.target.value)}
            required
          />
        </label>
        <label>
          Emergency Contact Phone
          <input
            value={form.emergency_contact_phone}
            onChange={(e) => update('emergency_contact_phone', e.target.value)}
            required
          />
        </label>
        <label>
          Passport Number
          <input value={form.passport_number} onChange={(e) => update('passport_number', e.target.value)} required />
        </label>
        <label>
          Passport Issue Place
          <input
            value={form.passport_issue_place}
            onChange={(e) => update('passport_issue_place', e.target.value)}
            required
          />
        </label>
        <label>
          Passport Issue Date
          <input
            type="date"
            value={form.passport_issue_date}
            onChange={(e) => update('passport_issue_date', e.target.value)}
            required
          />
        </label>
        <label>
          Passport Expiry Date
          <input
            type="date"
            value={form.passport_expiry_date}
            onChange={(e) => update('passport_expiry_date', e.target.value)}
            required
          />
        </label>
        <label>
          Date of Birth
          <input type="date" value={form.date_of_birth} onChange={(e) => update('date_of_birth', e.target.value)} required />
        </label>
        <label>
          Education
          <input value={form.education} onChange={(e) => update('education', e.target.value)} required />
        </label>
        <label>
          Medical Status
          <select value={form.medical_status} onChange={(e) => update('medical_status', e.target.value)}>
            <option>FIT</option>
            <option>UNFIT</option>
            <option>Pending</option>
          </select>
        </label>

        {error && <p className="error span-2">{error}</p>}
        {status && <p className="span-2">{status}</p>}

        <button type="submit" className="span-2" disabled={submitting}>
          {submitting ? 'Working…' : 'Create + Register'}
        </button>
      </form>

      {result && (
        <div className="card">
          <p>
            <strong>{result.name}</strong> is now <strong>{result.status}</strong>.
          </p>
          {result.status === 'Registered' && (
            <button onClick={handleGenerateCV} disabled={submitting}>
              Generate CV (Standard track → portal-visible)
            </button>
          )}
        </div>
      )}
    </div>
  )
}
