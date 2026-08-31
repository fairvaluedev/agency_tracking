# Complaints + Chat + Notifications Contract

Source of truth: `agency_tracking/agency_tracking/doctype/{complaint, chat_thread, chat_message,
chat_thread_participant}/*.json` (fields), `agency_tracking/complaint_api.py` +
`agency_tracking/chat_api.py` + `agency_tracking/notification_api.py` (endpoints),
`agency_tracking/state_machine.py` (`ALLOWED_TRANSITIONS["Complaint"]`).

## Complaint

Naming: `CMP-.#####`.

### Field definitions

| Field | Type | Nullable | Read-only? | Enum / Options | Notes |
|---|---|---|---|---|---|
| `placement` | Link | No | **Read-only** | Placement | |
| `contractor` | Link | No | **Read-only** | Contractor | Normally `placement.contractor`, kept explicit for querying. |
| `raised_by` | Select | No | **Read-only** | Foreign Agency / Internal Staff | Set automatically from who called `create_complaint`, not a caller-supplied value. |
| `worker_status_at_complaint` | Select | No | **Read-only** | Deployed / Returned | Caller-supplied at creation, then frozen. |
| `description` | Small Text | No | Writable | | |
| `status` | Select | Yes | **Read-only** (only `transition()`/the functions below set it) | New / Unresolved / Resolved / Returned - Free Replacement Required / Escalated / Dismissed | See state transitions below. |
| `resolution_notes` | Small Text | Yes | Writable | | **Required** when resolving to `Dismissed`. |
| `resolved_by` / `resolved_on` | Link/Date | Yes | **Read-only** | | |

### State transitions

From `state_machine.ALLOWED_TRANSITIONS["Complaint"]` + `STAGE_GATES`:

| From | To | Gate | Who |
|---|---|---|---|
| New | Unresolved | None | Complaint Manager, Admin — via `acknowledge_complaint` |
| Unresolved | Resolved | None | Complaint Manager, Admin — via `resolve_complaint(new_status="Resolved")` |
| Unresolved | Returned - Free Replacement Required | `within_free_replacement_window`: the Placement's `departed_on` must be within 90 days | Complaint Manager, Admin normally; **Manager** too if using `override_reason` (e.g. approving outside the window as an exception) |
| Unresolved | Escalated | None | Complaint Manager, Admin |
| Unresolved | Dismissed | None, but `resolution_notes` is **required** (enforced both in `resolve_complaint` and `Complaint.validate()` as a backstop) | Complaint Manager, Admin |

All four "resolution" outcomes go through the single `resolve_complaint(complaint_name,
new_status, resolution_notes=None, override_reason=None)` — `new_status` must be one of the four
terminal values above or it's rejected with `"'{new_status}' is not a resolution outcome."`.

### Endpoints

All `POST /api/method/agency_tracking.complaint_api.<name>`.

#### `create_complaint(placement, description, worker_status_at_complaint)` — STABLE CONTRACT, LIVE AND TESTED

```json
{
  "name": "CMP-00001",
  "placement": "PLM-00018",
  "contractor": "Test Agency capB3",
  "raised_by": "Internal Staff",
  "worker_status_at_complaint": "Deployed",
  "description": "Worker unresponsive for 3 days",
  "status": "New",
  "resolution_notes": null,
  "resolved_by": null,
  "resolved_on": null,
  "doctype": "Complaint"
}
```
Callable by the linked Foreign Agency for that placement's own contractor (cross-contractor is
denied even for a real second agency, confirmed live in `cc2/`), or any internal staff role.
`worker_status_at_complaint` must be `"Deployed"` or `"Returned"` — no other value validated
against an explicit enum check in the function itself, but the doctype's Select field will reject
anything else on save.

#### `list_unresolved_complaints()` — STABLE CONTRACT, LIVE AND TESTED

Complaint Manager, Admin, Manager only. Array, oldest-first, **lightweight** (not the full
Complaint dict):
```json
[
  { "name": "CMP-00001", "placement": "PLM-00018", "contractor": "Test Agency capB3", "description": "Worker unresponsive for 3 days", "creation": "2026-08-31 11:49:36.050288" }
]
```
Only status `"Unresolved"` rows appear — a fresh `"New"` complaint (not yet acknowledged) is
**absent** from this list. If the frontend needs to show brand-new unacknowledged complaints too,
that's a different/additional query — flag if needed (PROVISIONAL: no `list_all_complaints` or
status-filterable list exists today).

#### `acknowledge_complaint(complaint_name)` — STABLE CONTRACT, LIVE AND TESTED

Full Complaint dict, `status: "Unresolved"`. Complaint Manager, Admin only.

#### `resolve_complaint(complaint_name, new_status, resolution_notes=None, override_reason=None)` — STABLE CONTRACT, LIVE AND TESTED (Dismissed outcome captured)

```json
{
  "name": "CMP-00001",
  "status": "Dismissed",
  "resolution_notes": "Investigated, found to be a communication delay, not abuse.",
  "resolved_by": "Administrator",
  "resolved_on": "2026-08-31",
  "..." : "(full Complaint dict)"
}
```
417 if `new_status` isn't one of the four terminal values, or if `new_status="Dismissed"` with no
`resolution_notes`.

## Chat

Naming: `CHT-.#####` (Chat Thread), `CHM-.#####` (Chat Message).

### Field definitions

**Chat Thread**

| Field | Type | Nullable | Read-only? | Enum / Options | Notes |
|---|---|---|---|---|---|
| `thread_type` | Select | No | **Read-only** | Agency / Internal | Agency: exactly the Contractor's portal user + their routed Communication Manager, never more. Internal: open staff-to-staff. |
| `contractor` | Link | Yes | **Read-only** | Contractor | Set only for Agency threads — the cross-agency isolation boundary; always filter by this, never just by participant rows. |
| `context_type` | Select | Yes | **Read-only** | General / Placement / Complaint | |
| `context_reference` | Data | Yes | **Read-only** | | Name of the referenced Placement/Complaint. Read access to it still goes through that record's own permission check — a thread reference is a link, not a permission grant. |
| `last_message_at` | Datetime | Yes | **Read-only** | | |
| `participants` | Table | Yes | **Read-only** from outside | child table → `Chat Thread Participant` (`user`, `last_read_at`) | |

**Chat Message**

| Field | Type | Nullable | Read-only? | Enum / Options | Notes |
|---|---|---|---|---|---|
| `thread` | Link | No | **Read-only** | Chat Thread | |
| `sender` | Link | No | **Read-only** | User | Always the calling user — not settable. |
| `message` | Small Text | Yes | Writable | | Message must have `message` and/or `attachment` — both null is rejected. |
| `attachment` | Attach | Yes | Writable | | See `06-file-upload-contracts.md` (batch 4, not yet written) for the upload sequence. |
| `mentioned_applicant` / `mentioned_placement` | Link | Yes | Writable | Applicant / Placement | A typed-search @mention, not a permission grant — the mentioned record's own read permission is still checked at send time (throws if the sender can't actually read it). |

### Endpoints

All `POST /api/method/agency_tracking.chat_api.<name>`. **Naming note**: there is no single
`create_thread` function — it's split into `create_agency_thread()` (no params, Foreign Agency
only, routes server-side, never pick a recipient) and `create_internal_thread(other_user,
context_type="General", context_reference=None)` (internal staff only). Use whichever matches
the calling user's role; calling the wrong one throws a clear `PermissionError` naming the correct
function to use instead.

#### `create_agency_thread()` — STABLE CONTRACT, LIVE AND TESTED

Get-or-create — idempotent, always returns the agency's one thread:
```json
{
  "name": "CHT-00002",
  "thread_type": "Agency",
  "contractor": "Test Agency capB3",
  "context_type": "General",
  "context_reference": null,
  "last_message_at": null,
  "participants": [ { "name": "8drhknmovd", "user": "agency-capb3@example.com", "last_read_at": null } ]
}
```

#### `create_internal_thread(other_user, context_type="General", context_reference=None)` — STABLE CONTRACT, LIVE AND TESTED

Get-or-create between the calling user and `other_user` (User name/email):
```json
{
  "name": "CHT-00001",
  "thread_type": "Internal",
  "contractor": null,
  "context_type": "Placement",
  "context_reference": "PLM-00018",
  "last_message_at": null,
  "participants": [ { "user": "capb3-staff1@example.com" }, "..." ]
}
```

#### `send_message(thread_name, message=None, mentioned_applicant=None, mentioned_placement=None, attachment=None)` — STABLE CONTRACT, LIVE AND TESTED

```json
{
  "name": "CHM-00001",
  "thread": "CHT-00001",
  "sender": "capb3-staff1@example.com",
  "mentioned_applicant": null,
  "mentioned_placement": null,
  "message": "Please review this placement's clearance status.",
  "attachment": null,
  "doctype": "Chat Message"
}
```

#### `list_threads()` — STABLE CONTRACT, LIVE AND TESTED

```json
[ { "name": "CHT-00001", "thread_type": "Internal", "context_type": "Placement", "context_reference": "PLM-00018", "last_message_at": "2026-08-31 11:49:36.770646" } ]
```
Scoped to threads the caller participates in — a Foreign Agency additionally gets a redundant
own-contractor filter (belt-and-suspenders against ever leaking another agency's thread).

#### `get_thread_messages(thread_name)` — STABLE CONTRACT, LIVE AND TESTED

```json
[ { "name": "CHM-00001", "sender": "capb3-staff1@example.com", "message": "Please review this placement's clearance status.", "attachment": null, "mentioned_applicant": null, "mentioned_placement": null, "creation": "2026-08-31 11:49:36.736804" } ]
```

#### `mark_read(thread_name)` — STABLE CONTRACT, LIVE AND TESTED

```json
{ "status": "read" }
```
Updates the caller's own `last_read_at` on the thread's participant row — no per-message read
receipts, just a single "read up to now" timestamp per participant per thread.

#### `add_participant(thread_name, user)` — STABLE CONTRACT, LIVE AND TESTED

Internal threads only — throws `ValidationError` outright on an Agency thread ("start a separate
internal thread instead"). `user` is a User name/email. Returns the full updated Chat Thread.

## Notifications

### `subscribe_to_push(endpoint, p256dh, auth)` — STABLE CONTRACT, LIVE AND TESTED

Standard Web Push subscription keys (from the browser's `PushManager.subscribe()` result). Always
for the calling user, never on behalf of anyone else:
```json
{ "status": "subscribed" }
```

### `get_push_subscription_status()` — STABLE CONTRACT, LIVE AND TESTED

```json
{ "subscribed": true }
```
Use this to decide whether to show a manual "enable notifications" fallback button (for when the
browser's native permission prompt was dismissed/denied without the frontend catching it).

### `trigger_wakala_reminder(clearance_step_name)` — STABLE CONTRACT, LIVE BUT NOT TESTED this pass

Only meaningful for an `Embassy`/`Kuwait Embassy` step (throws otherwise). Manual escape hatch
alongside the automatic Fri/Sat/Sun watchdog. Returns `{"status": "reminder sent"}`. Requires read
access to the referenced Clearance Step.

### Push Subscription / Notification Config doctypes — PROVISIONAL, no dedicated read/list endpoint

There's no whitelisted `list_notifications`/`get_notification_history` today — the two endpoints
above (`subscribe_to_push`, `get_push_subscription_status`) are the entire notification-facing API
surface. If the frontend needs an in-app notification feed/history (not just push), that doesn't
exist yet — flag it explicitly rather than assuming it's hiding somewhere.
