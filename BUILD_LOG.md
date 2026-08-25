# Build Log — agency_tracking

Running record of what's built, key decisions made without stopping to ask (per explicit
instruction: proceed autonomously, log decisions, keep this file current so a fresh session
can resume from it if interrupted), and what's next. Source of truth for *why* is
`../../../../agency/master-build-specification.md` (+ addendum + SRS) — this log doesn't
duplicate that content, only records build-order status and decisions made where the spec
was silent or where sequencing required a judgment call.

Bench: `test/` (site `agency-tracking.local`, MariaDB root pw `1234`, admin pw `admin`).
App lives at `test/apps/agency_tracking`, own git repo, **not** derived from
`test/apps/applicant_processing` (the old Gemini prototype — kept untouched as reference only,
see `[[project-agency-tracking-gap-analysis]]` memory for why it wasn't reused).

## Status: Part I sequence

- [x] 1. Core identity + track-aware field floor (Applicant, Standard/Muayena, Musaned gate stub)
- [x] 2. CV generation + Musaned gate wired in
- [x] 3. Portal + atomic selection + `active_placement` locking
- [x] 4. Contract parsing (both tracks) → Placement creation
- [x] 5. Corridor Definition engine (Saudi + Kuwait)
- [x] 6. transition() + gate table + Manager Override (Medical 2 gate)
- [ ] 7. Clearance Step + ToDo permission scoping + LMIS→Ticketing→Departure auto-chain
- [ ] 8. Financial ledger (income/expense, FX, accrual, batching, visibility wall)
- [ ] 9. Reconciliation tool
- [ ] 10. Complaints
- [ ] 11. Notification pipeline
- [ ] 12. Chat
- [ ] 13. Reporting/dashboards
- [ ] 14. Frontend (SPA)
- [ ] 15. Deployment hardening

## Standing decisions (apply to every step, not re-litigated per step)

- **transition() built now, not deferred to Step 6.** CLAUDE.md's hard rule ("every status
  change goes through transition(), never doc.status = X directly") outranks Part I's
  sequencing, which only means the *gate table* grows complex at Step 6 — the function itself
  exists from Step 1 so no step ever bypasses it. Lives in `agency_tracking/state_machine.py`,
  shared across doctypes (`ALLOWED_TRANSITIONS`/`STAGE_GATES` keyed by doctype).
- **No raw `/api/resource/*`.** Every client-facing operation goes through a whitelisted
  function in a module-scoped `*_api.py` file (Part F), starting now with `applicant_api.py`,
  not deferred to later steps.
- **No Frappe Desk client-script UI (.js per doctype).** Part H is explicit the real frontend
  is a framework-agnostic SPA built in Step 14 against the headless API — building Desk
  form scripts now would be throwaway work against a UI nobody will use. Doctypes get
  JSON + Python controller only, per CLAUDE.md's pairing rule (JSON+Python, not JSON+JS).
- **Roles pre-declared.** All 8 Part G roles (Recruitment/Intake, Clearance Officer, Ticketing/
  Dispatch, Complaint Manager, Finance Manager, Manager, Admin, Foreign Agency) are created via
  `install.py:after_install` now rather than one at a time per step — cheap, avoids fragmented
  role creation, and the full RBAC table is already finalized in the spec.
- **Applicant vs Placement status split.** Part B's table only lists `entry_track`,
  `musaned_status`, `active_placement` for Applicant (not exhaustive — SRS clearly implies name/
  phone/gender/etc. too), while Placement explicitly owns `status`. Read this as: Applicant owns
  its own `status` for the pre-Placement stages only (Draft → Registered → CV Generated —
  everything before a foreign agency selects the candidate and a Placement gets created).
  Selected → Processing → Stamped → Ticketed → Departed live on `Placement.status` from Step 3+
  onward. Applicant's `status` Select options are therefore just `Draft`/`Registered`/
  `CV Generated` for now; whether Applicant needs a 4th "locked" marker once Placement exists
  is a Step 3 decision, not resolved here.
- **Environment fixed on the way in:** `test/apps/frappe` was shallow-cloned on `develop`
  (v17.0.0.dev0, needs Python 3.14 — this machine has 3.12), which is almost certainly why the
  old prototype never got a working site either (no site existed under `test/sites/` before this
  session). Re-fetched and checked out `version-15` (matches `applicant_processing`'s own
  `frappe~=15.0.0` pin and the installed Python). `bench setup requirements --python frappe` run
  to make it importable — scoped to `frappe` only, not `applicant_processing`'s heavy OCR deps
  (paddleocr/paddlepaddle), which agency_tracking doesn't need.

## Step 1 — what was built

`agency_tracking/agency_tracking/doctype/applicant/` — `applicant.json` + `applicant.py` +
`test_applicant.py`. Plus `state_machine.py` (shared `transition()`, `ALLOWED_TRANSITIONS`,
`STAGE_GATES`, and the Musaned gate stub) and `applicant_api.py` (whitelisted
`create_applicant`/`register_applicant`, no raw resource access). `install.py` creates the 8
roles on install.

Field-floor source: `business-workflow-srs.md` Stage 1 (Draft: name, gender, nationality, phone,
address) and Stage 2 (Registered, Standard: full list incl. national ID, labor ID, destination
country, salary+currency, religion, marital status, emergency contact, full passport details,
education, target job, photos, passport scan, medical FIT) + master spec A.1 (Muayena: lighter
global-only floor — passport, national ID, medical, photos).

**Assumptions made, not explicitly in spec (flagging per CLAUDE.md rather than silently
picking):**
- `passport_scan` included in *both* tracks' Registered floor. Spec's Muayena floor list says
  "passport" without clarifying whether that includes the scanned document or just passport
  data fields. Included the scan for both since OCR/contract-parsing (Step 4) needs it either
  way and it's needed for real operation regardless of track.
- Uniqueness on `passport_number`/`national_id` implemented as an app-level check in
  `validate()` (skips blank values), not a DB-level `unique=1` field flag — a DB unique index
  would reject multiple blank-passport Draft records (MySQL treats `''` as a real, colliding
  value, not `NULL`), which would break Draft-stage saves since passport isn't required until
  Registered.
- No `Cancelled` status added to Applicant, even though the old prototype had one — not in the
  new spec's documented lifecycle (A.2 lists exactly 9 stages, cancellation only appears later
  at the Ticketed→Stamped revert, which is a Placement-level concern). Not inventing beyond spec.

**Verified, not just written:** `bench migrate` synced the doctype cleanly; all 8 Part G roles
exist (`install.py:create_roles`, ran manually once since the app had already been
`install-app`'d before `install.py` existed — will fire automatically via `after_install` on
any fresh install from here on); `run-tests --module ...test_applicant` → 15/15 passing; a
console smoke test drove the actual `applicant_api` functions end-to-end (create → blocked at
register with a structured missing-fields message → filled the floor → registered → fetched)
to confirm the real API path works, not just the unit tests in isolation.

**Not yet done (explicitly deferred, not forgotten):**
- `active_placement` field — Part I Step 3 (needs Placement doctype to exist as a Link target
  first, and its atomic-lock semantics are literally what Step 3 is).
- Musaned gate is a stub (`musaned_gate_passed()` exists and is tested) but nothing calls it yet
  — wiring into CV generation is Step 2 by name.
- `Country` values used for `destination_country`/`nationality` rely on Frappe's shipped core
  Country doctype (standard ISO names e.g. "Saudi Arabia", "Kuwait", "Ethiopia") — no new
  doctype needed for this.

## Step 2 — what was built

`agency_tracking/agency_tracking/doctype/cv_record/` — `cv_record.json` (Submittable,
`applicant` Link, `generated_on`/`generated_by` auto-set on insert) + `cv_record.py` +
`test_cv_record.py`. Plus `cv_api.py` (`generate_cv`, Part F module-scoped whitelisted
function). `state_machine.py` gained the `("Registered", "CV Generated")` edge and its gate
(`cv_generation_gate`), which composes the existing `musaned_gate_passed` stub with an
entry-track check — this is the "wired in" part of the step's name. CV Record's own
`validate()` independently re-checks Standard-track + Registered-status + Musaned gate with
specific error messages (checked first, before `transition()`'s generic gate runs as a
backstop) — belt-and-braces per the production-quality directive: a CV Record should never be
able to exist for a candidate that violates these invariants, regardless of which code path
created it.

**Scope call:** did not build actual CV/dossier PDF rendering (the "two-page CV" visual
output) — the technical spec (Part B/C/F) only requires `CV Record` to exist as a submittable
audit artifact gating the Applicant's status move; the visual document is a presentation
concern more naturally handled by a Frappe Print Format or the Step 14 SPA, not called out
anywhere in the state-machine/RBAC spec that's been the basis for every other decision so far.
Flagging so it isn't mistaken for an oversight — build if/when it's actually needed.

**Verified:** `bench migrate` synced cleanly; 6/6 new tests passing, all 15 Step-1 tests still
passing (21/21 total) — Kuwait Standard candidates generate CVs with no Musaned involvement,
Saudi Standard candidates are blocked until `ALTEYAZECHEM`, Muayena and un-Registered
Applicants are rejected outright.

**Not yet done (deferred):** portal visibility of CV-Generated candidates is Step 3's
concern (that's literally what "Portal" means in Step 3's name) — nothing here exposes CV
Records to any agency-facing query yet.

## Step 3 — what was built

`Contractor` doctype (minimal: `contractor_name`, `country`, one `user` Link per contractor —
see assumption below) and `Placement` doctype (minimal: `applicant`, `contractor`,
`destination_country`, `status` — options just `"Selected"` for now, `cv_record`; richer
Part B fields — `contract_signed_date`, `manual_commission_amount`, `is_free_replacement` —
deliberately **not** added yet, see "Standing decisions" correction below). `Applicant`
gained `active_placement` (Link -> Placement, read-only, set only through the API). New
`portal_api.py`: `list_portal_candidates()` (own-country catalog, non-PII field subset —
judgment call, spec doesn't enumerate exact portal fields) and `select_candidate()` — the
atomic, globally-exclusive selection, using `SELECT ... FOR UPDATE` on the Applicant row to
close the race window between two agencies both reading `active_placement` as empty.

**Resolved an open question from Step 1's log:** whether Applicant needs a 4th status value
once Placement exists. Answer: no. Part B splits ownership — Applicant's own `status` only
ever covers the pre-Placement pipeline (Draft/Registered/CV Generated); once a Placement
exists, the real lifecycle state lives on `Placement.status` and `active_placement` is simply
the pointer/lock. This also explains why Muayena candidates (who skip CV/portal) will end up
with `Applicant.status` frozen at `"Registered"` forever once Step 4 gives them a Placement —
that's correct, not a bug.

**Standing-decision correction:** Step 1/2 added `musaned_status` and (implicitly) treated
Part B's per-doctype field notes as license to add fields ahead of the logic using them. On
reflection that's the same "fields exist, nothing uses them" smell flagged in the
Gemini-prototype gap analysis as an anti-pattern to avoid. Revised rule going forward: add a
field only in the step that actually gates or reads it (`musaned_status` gets a pass — it was
explicitly named "Musaned gate stub" in Step 1's own title, a deliberate one-step-early
exception, not the general pattern). `Placement.contract_signed_date` lands in Step 4,
`manual_commission_amount` in Step 8, `is_free_replacement` in Step 10 — not now.

**Assumption flagged:** one Contractor <-> one portal User. The spec doesn't describe
multi-user agencies; if an agency needs several staff logging in, `Contractor.user` becomes a
child table later — cheap to extend, not blocking anything downstream.

**Verified:** `bench migrate` synced cleanly; 4/4 new Placement tests + 6/6 new portal API
tests (catalog country-filtering, atomic select, cross-agency invisibility, double-selection
rejection, cross-country rejection, non-Foreign-Agency rejection) — 31/31 total across the
whole app.

**Not yet done (deferred):** Muayena's direct-to-Selected entry path (no portal, contract
already in hand) is Step 4, alongside the contract-parsing utility that fills
`contract_signed_date` for both tracks.

## Step 4 — what was built

`contract_parser.py` (app root, not a doctype): PyMuPDF text extraction +
`extract_contract_signed_date()` (English and Arabic date-label regexes) + `parse_contract_file()`
wrapper that resolves a Frappe file_url to a filesystem path. **Deliberately narrow** — the old
Gemini prototype's equivalent (`applicant_processing/utils/contract_parser.py`) extracts ~20
sponsor/employer/agency sub-fields via ~1000 lines of regex; nothing in Part B ties any of that
to a Placement field, so building it here would be speculative surface with no spec-required
consumer. The one field the spec actually calls for (Part A.4: "contract-age clock starts from
the contract's own signed date, extracted at parse time") is what's built, tested against both
a synthetic and a real generated PDF (PyMuPDF smoke-tested end-to-end via console, not just the
missing-file fallback path).

`Placement` gained `contract_file` (Attach) and `contract_signed_date` (Date) — the two fields
flagged as deferred in Step 3's log. New `placement_api.py`: `upload_contract()` (Standard
track — attaches a contract to the Placement Step 3 already created) and
`create_muayena_placement()` (Muayena track — the direct "contract in hand" entry Part A.1
describes, no portal or CV involved at all).

**Placement.validate() invariant revised** (was: "Muayena blocked, not wired in yet"; now: a
track-aware floor) — Standard requires `Applicant.status == "CV Generated"` (came through the
portal), Muayena requires `"Registered"` (their terminal intake status, since they never touch
CV Generated). This also required updating three Step-3 tests that had been asserting against
the old "Registered is enough" placeholder invariant — not a regression, the invariant simply
didn't exist correctly until this step gave Muayena a real creation path to test against.

**Real bug caught and fixed before commit:** `upload_contract()`'s first draft gated the "is
this an agency or staff" branch on `"Foreign Agency" in frappe.get_roles()`. That's wrong — the
special `Administrator` user is assigned literally every role in the system (verified via
console), so the check always took the agency branch and rejected Administrator as "not the
right contractor." Fixed to key off whether the session user has an actual linked `Contractor`
record instead, which is the real signal and doesn't misfire for Administrator/System Manager.
Worth remembering for every future permission check in this codebase: never gate on role
membership alone when `Administrator` needs to be handled correctly, check a concrete
relationship (linked record, assignment, ownership) instead.

**Verified:** `bench migrate` clean; 8 new contract-parser tests + 8 new placement-api tests +
revised Placement tests — 46/46 total across the whole app. Console smoke test generated a real
PDF with PyMuPDF and confirmed `contract_signed_date` extraction end-to-end (not mocked).
`pymupdf` added to `pyproject.toml` (was working only because it leaked in from the other app's
shared venv — now properly declared).

**Not yet done (deferred):** no gate/transition wiring for Placement's own lifecycle yet
(Selected -> Processing -> ...) — that's Corridor Definition (Step 5) and the full gate table
(Step 6).

## Step 5 — what was built

`Corridor Definition` (one per `destination_country`, unique) + child table `Corridor Step`
(`step_type`, `sequence_order`, `is_mandatory`) — exactly Part B's schema. `validate()` enforces
unique `sequence_order` and unique `step_type` within one corridor. New `corridor_engine.py`:
`get_corridor_steps()`, `get_first_step_type()`, `get_next_step_type()`, `is_last_step()` — all
pure data lookups, no country names hardcoded anywhere in the module. `install.py` seeds Saudi
Arabia (LMIS Clearance → Taeshir → Injaz → Embassy/Wakala) and Kuwait (LMIS Police Clearance →
Telesign → Kuwait Embassy → LMIS Work Permit) per the business SRS's Stage 5 sequences, all
steps mandatory (the spec doesn't call out an optional step in either corridor yet — `Corridor
Step.is_mandatory` exists and works, just nothing sets it to 0 in the seed data).

**Proved the actual design goal, not just built the schema.** Part A.3's whole point is "new
corridors are added as data, never a code deployment" — `test_new_corridor_added_as_pure_data_no_code_change`
inserts a throwaway UAE corridor with an optional third step, using the exact same
`corridor_engine` functions already exercised against the seeded Saudi/Kuwait data, and gets
correct ordering/mandatory-flag results with zero code changes. That test is the actual
acceptance criterion for this step, not incidental coverage.

**Verified:** `bench migrate` clean; 8 new tests (3 Corridor Definition invariants, 5 corridor
engine, including the no-code-change proof) — 54/54 total. Manually ran `create_corridors()`
once via console (same catch-up situation as Step 1's roles — this site was installed before
the seeding code existed); confirmed `Saudi Arabia` and `Kuwait` both exist with correct steps.

**Not yet done (deferred):** nothing in this step touches Placement or Clearance Step yet —
Corridor Definition is pure reference data until Step 7 (Clearance Step) starts creating
per-candidate step records from it, gated by Step 6's expanded `STAGE_GATES`.

## Step 6 — what was built

**Retrofitted a gap from Step 1, not scope creep:** Part C says `transition()` "writes the
Process Event audit entry atomically" — that was true of every `transition()` call since Step 1,
but the `Process Event` doctype itself didn't exist yet (nothing needed it urgently until
Manager Override, this step's actual deliverable, needed somewhere to record the mandatory
written reason). Built now: `Process Event` (Part B's audit trail — `reference_doctype`/
`reference_name` dynamic link, `event_type` Transition/Override/Cancelled/Restored,
`from_status`/`to_status`/`actor`/`remarks`), immutable by design (no doctype permission grants
write/delete/create to anyone but System Manager — `transition()` writes rows via
`ignore_permissions=True`, the only sanctioned writer). `get_permission_query_conditions()` in
`process_event.py` is the addendum's own scoping function transcribed verbatim (Admin/Manager
see everything, Finance Manager sees Applicant-Transaction-linked rows only, everyone else sees
only their own actions) — wired into `hooks.py`. The Finance Manager and Complaint Manager
branches are inert until Step 8/10 create the doctypes they reference; the function is complete
now because CLAUDE.md says build permission logic alongside its doctype, not retrofit it later.

`transition()` gained `override`/`override_reason` params: a gate-blocked move throws normally
unless `override=True`, which then requires `{Manager, Admin}` role AND a non-empty
`override_reason` (business-workflow-srs.md: "always with a written reason") — enforced inside
`transition()` itself, not any caller. Every call now logs a `Process Event`, `Transition` or
`Override` depending on whether a gate was actually bypassed. **Override only ever bypasses a
gate, never the `ALLOWED_TRANSITIONS` topology itself** — flagging this as a judgment call since
the spec doesn't explicitly say either way, but nothing in the business workflow describes
skipping an entire lifecycle stage, only forcing past a blocked condition.

`Placement` gained its full status vocabulary (`Selected → Processing → Stamped → Ticketed →
Departed`, matching Part A.2 stages 5–9) and `medical_2_status` (the pre-departure ~72h check,
distinct from the Applicant's earlier registration-time FIT check). `STAGE_GATES` gained
`("Ticketed", "Departed")` → `medical_2_gate` — the step's explicitly-named deliverable.
`Selected→Processing` and `Stamped→Ticketed` are intentionally left ungated (nothing to check
yet); `Processing→Stamped`'s real gate ("all mandatory corridor steps issued") depends on
Clearance Step and is explicitly Step 7's job, not stubbed here.

New `placement_api.py:advance_placement()` — a direct/manual progression + override entry
point, restricted to internal staff (Placement's doctype permissions grant nothing to Foreign
Agency, verified by test). This is scaffolding for Step 7's real auto-chain (LMIS → Ticketing →
Departure), not a replacement for it.

**Verified:** `bench migrate` clean; 13 new tests (state machine mechanics — ungated transitions
log correctly, gate blocks, override requires role + reason, disallowed edges never overridable;
Process Event validation + permission scoping; `advance_placement` wiring) — 67/67 total across
the app.

**Not yet done (deferred):** the real Processing→Stamped gate, Clearance Step doctype, ToDo-based
per-row permission scoping, and the LMIS→Ticketing→Departure auto-chain are all Step 7.
