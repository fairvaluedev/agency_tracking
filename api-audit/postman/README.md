# Postman 1-Click API Testing Guide

This Postman test suite is **100% pre-configured and pre-populated** with verified request payloads and authentication scripts for the Agency Tracking platform.

---

## ⚡ Quick Start (1-Click Run)

1. **Import Files into Postman:**
   * Import `API-Collection.postman_collection.json` (or root `postman_collection.json`)
   * Import `API-Environment.postman_environment.json` (or root `postman_environment.json`)
2. **Select Environment:**
   * In Postman's top-right dropdown, select **`Agency Tracking Local Environment`**.
3. **Authenticate:**
   * Open `00 - Authentication` folder.
   * Click **`Login - Administrator`** (or any role) and click **Send**.
   * *The test script automatically captures session cookies and CSRF tokens into `{{csrfToken}}`!*
4. **Execute Requests:**
   * Navigate to `01 - Administrator (Master Complete Suite)` or `02 - Roles` &rarr; `[Your Role]`.
   * Open any request and click **Send** — all body payloads and IDs are pre-filled!

---

## 📁 Collection Structure

```text
API Collection
│
├── 00 - Authentication
│   ├── 00 - Bootstrap CSRF Token
│   ├── Login - Administrator
│   ├── Login - System Manager
│   ├── Login - [Every Role...]
│   └── Logout (Guest Session)
│
├── 01 - Administrator (Master Complete Suite)
│   ├── 01 - Authentication & Session
│   ├── 02 - Applicants & Registration
│   ├── 03 - CV Management
│   ├── 04 - Portal & Candidate Discovery
│   ├── 05 - Placements & Logistics
│   ├── 06 - Clearances & Embassies
│   ├── 07 - Finance & Ledger
│   ├── 08 - Bank Reconciliation
│   ├── 09 - Complaints & Disputes
│   ├── 10 - Chat & Messages
│   ├── 11 - Notifications
│   ├── 12 - Contractors & Foreign Agencies
│   ├── 13 - Reports & Analytics
│   ├── 14 - API Documentation
│   └── 15 - Core RPC & File Storage
│
├── 02 - Roles
│   ├── Role - Administrator
│   ├── Role - System Manager
│   ├── Role - Registrar
│   ├── Role - Manager
│   ├── Role - Clearance Officer
│   ├── Role - Ticketer
│   ├── Role - Complaint Manager
│   ├── Role - Finance Manager
│   ├── Role - Foreign Agency
│   ├── Role - Communication Manager
│   ├── Role - Contract Parser
│   ├── Role - Saudi LMIS
│   ├── Role - Saudi Taeshir
│   ├── Role - Saudi Embassy
│   ├── Role - Kuwait LMIS
│   ├── Role - Kuwait Telesign
│   ├── Role - Kuwait Embassy
│   └── Role - Guest
│
└── 90 - Negative Tests
    ├── Missing Authentication
    ├── Unauthorized Access
    ├── Invalid Enum Value
    └── Nonexistent Resource
```

---

## 🔑 Pre-Configured Test Credentials

| Role | Email | Password |
| :--- | :--- | :--- |
| **Administrator** | `Administrator` | `Admin@123` |
| **System Manager** | `api.test.system_manager@example.local` | `Admin@123` |
| **Admin** | `api.test.admin@example.local` | `Admin@123` |
| **Manager** | `api.test.manager@example.local` | `Admin@123` |
| **Registrar** | `api.test.registrar@example.local` | `Admin@123` |
| **Clearance Officer** | `api.test.clearance_officer@example.local` | `Admin@123` |
| **Ticketer** | `api.test.ticketer@example.local` | `Admin@123` |
| **Complaint Manager** | `api.test.complaint_manager@example.local` | `Admin@123` |
| **Finance Manager** | `api.test.finance_manager@example.local` | `Admin@123` |
| **Foreign Agency** | `api.test.foreign_agency@example.local` | `Admin@123` |
| **Communication Manager** | `api.test.communication_manager@example.local` | `Admin@123` |
| **Contract Parser** | `api.test.contract_parser@example.local` | `Admin@123` |
| **Saudi LMIS / Taeshir / Embassy** | `api.test.saudi_*@example.local` | `Admin@123` |
| **Kuwait LMIS / Telesign / Embassy** | `api.test.kuwait_*@example.local` | `Admin@123` |
