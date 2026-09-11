# TV Display UI Fix & Edit Medical Profile Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the TV queue display mobile header and idle serving layout, and overhaul the Edit Medical Profile modal into a clean, sectioned interface with 1-tap pill selectors and preset chips.

**Architecture:** Client-side HTML/CSS/JS enhancements in `display.html`, `index.html`, and `app.js` with zero backend breaking changes, fully preserving the existing `PUT /api/auth/profile` contract and test suite.

**Tech Stack:** Vanilla JavaScript (ES2022), Tailwind CSS 3.4.17, FastAPI backend, Pytest test suite.

## Global Constraints
- Ponytail mode: Use native DOM APIs and existing CSS utility classes; avoid unnecessary dependencies.
- Caveman mode: Concise, high-density updates.
- Test integrity: All 119 unit/integration tests must pass at every step.
- Raw CSS link in `index.html` must remain exact `href="/static/css/app.css"` without cache query strings.

---

### Task 1: TV Display UI Fixes (`app/static/display.html`)

**Files:**
- Modify: `app/static/display.html`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `/api/queue/live-status` response payload (`currently_serving`, `currently_serving_room`, `waiting_tickets`).
- Produces: Polished responsive header and `STANDBY` idle state in TV display.

- [ ] **Step 1: Update header flex layout in `display.html`**
  Modify the `<header>` element and its clock container so it stacks gracefully on mobile screens:
  - Header: `flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 sm:gap-4 border-b border-[#232c25] pb-4 sm:pb-6`
  - Control & Clock row: `flex items-center justify-between sm:justify-end gap-3 sm:gap-6 w-full sm:w-auto shrink-0`

- [ ] **Step 2: Update clock date formatting in `display.html`**
  Update `updateClock()` so narrow viewports use a concise date format (`weekday: 'short'`) preventing line clipping:
  ```javascript
  const isNarrow = window.innerWidth < 480;
  document.getElementById('tvDate').textContent = now.toLocaleDateString(undefined, {
    weekday: isNarrow ? 'short' : 'long',
    year: 'numeric',
    month: isNarrow ? 'short' : 'long',
    day: 'numeric'
  });
  ```

- [ ] **Step 3: Update idle state rendering in `renderQueue(data)`**
  Update `display.html` so when `currently_serving` is empty or `'None'`:
  - `displayTicket` shows `STANDBY` with pulse styling.
  - Room text displays `Waiting for next patient call` instead of `Please proceed to N/A`.
  - When a patient ticket is active, smoothly render ticket and `Please proceed to <room>`.

- [ ] **Step 4: Run tests**
  Run `python -m pytest tests/test_main.py` to ensure route responses and headers are intact.

- [ ] **Step 5: Commit Task 1**
  ```bash
  git add app/static/display.html
  git commit -m "fix(display): improve mobile header layout and idle queue standby display"
  ```

---

### Task 2: Edit Medical Profile Modal Markup (`app/static/index.html`)

**Files:**
- Modify: `app/static/index.html` (modal `#profileModal`)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: Existing form structure.
- Produces: Structured, sectioned modal dialog with 1-tap pill selectors for Gender and Blood Group, preset chips for Allergies and Conditions, and a sticky footer.

- [ ] **Step 1: Replace `#profileModal` with sectioned card layout**
  Update `#profileModal` in `index.html`:
  - Outer card: `card max-w-lg w-full card-pad my-4 sm:my-8 max-h-[90vh] flex flex-col overflow-hidden`
  - Scrollable content container: `overflow-y-auto flex-1 space-y-5 pr-1`
  - Section 1: Personal & Demographics:
    - Full Name (`editFullName`) & Phone Number (`editPhone`).
    - DOB (`editDob`) with `max` date attribute.
    - Gender 1-tap pill grid (`Male`, `Female`, `Other`) with hidden input `editGender`.
  - Section 2: Clinical Profile:
    - Blood Group 1-tap pill grid (`A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`, `O+`, `O-`) with hidden input `editBloodGroup`.
    - Allergies: Preset chips (`Penicillin`, `Sulfa`, `Aspirin`, `Peanuts`, `Latex`, `None`) + input for custom allergy text.
    - Medical History: Preset chips (`Hypertension`, `Diabetes`, `Asthma`, `Heart Disease`, `None`) + textarea for custom history.
  - Section 3: Emergency Contact:
    - Name (`editEmergencyName`) & Phone (`editEmergencyPhone`).
  - Sticky footer:
    - `sticky bottom-0 bg-white/95 backdrop-blur border-t border-stone-200 py-3 px-6 -mx-6 -mb-6 flex justify-end gap-2 mt-4 z-10` with Cancel and Save buttons.

- [ ] **Step 2: Verify HTML syntax & test suite**
  Run `python -m pytest tests/test_main.py` to verify no broken HTML assertions.

- [ ] **Step 3: Commit Task 2**
  ```bash
  git add app/static/index.html
  git commit -m "feat(ui): redesign edit medical profile modal with sections, pills, and sticky footer"
  ```

---

### Task 3: Profile Modal Logic & Chip Management (`app/static/app.js`)

**Files:**
- Modify: `app/static/app.js`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `PUT /api/auth/profile`, `state.user`.
- Produces: Interactive pill selection, chip toggling, dynamic form population, and profile updates.

- [ ] **Step 1: Add pill selector & preset chip helper functions in `app.js`**
  - Implement `selectProfileGender(val)` to update hidden input and active button styles.
  - Implement `selectProfileBlood(val)` to update hidden input and active button styles.
  - Implement `toggleProfileAllergyChip(chipText)` and `toggleProfileHistoryChip(chipText)` to toggle chip states and sync with custom text inputs.

- [ ] **Step 2: Update `showProfileModal()` in `app.js`**
  - Pre-fill `editFullName`, `editPhone`, `editDob`.
  - Set `max` on `editDob` to today's date string.
  - Pre-select active Gender pill and Blood Group pill based on `state.user.patient_profile`.
  - Parse existing `allergies` and `medical_history` strings to set active states on preset chips and put custom remainder into text inputs.

- [ ] **Step 3: Update `handleProfileUpdate(e)` in `app.js`**
  - Combine active allergy preset chips with custom allergy text input.
  - Combine active condition preset chips with custom history textarea.
  - Send `PUT /api/auth/profile` with all fields including `gender`.
  - On success, update `state.user`, hide modal, re-render patient profile card, show toast.

- [ ] **Step 4: Expose new helper methods to `window.ClinicApp`**
  Ensure helper functions (`selectProfileGender`, `selectProfileBlood`, `toggleProfileAllergyChip`, `toggleProfileHistoryChip`) are exported in `window.ClinicApp`.

- [ ] **Step 5: Run tests**
  Run `python -m pytest` to ensure complete suite passes.

- [ ] **Step 6: Commit Task 3**
  ```bash
  git add app/static/app.js
  git commit -m "feat(profile): add interactive pill and chip handlers for medical profile editing"
  ```

---

### Task 4: CSS Rebuild & Full Verification

**Files:**
- Modify: `app/static/css/app.css` (if needed)
- Test: Full pytest suite

- [ ] **Step 1: Rebuild Tailwind CSS**
  Run: `npx tailwindcss@3.4.17 -i app/static/css/input.css -o app/static/css/app.css --minify`

- [ ] **Step 2: Run all 119 tests**
  Run: `python -m pytest`
  Verify: 119 passed, 0 failures.

- [ ] **Step 3: Commit and push**
  ```bash
  git add -A
  git commit -m "chore: compile tailwind assets and finalize verification"
  git push
  ```
