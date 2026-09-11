# TV Display UI Fixes & Edit Medical Profile Redesign Spec

- **Date**: 2026-09-11
- **Status**: Approved
- **Scope**:
  1. TV Queue Display (`display.html`): Mobile header wrapping, clock/date truncation fix, idle state rendering (`STANDBY` instead of `None` / `Please proceed to N/A`).
  2. Edit Medical Profile Modal (`index.html`, `app.js`): Sectioned grouped cards, 1-tap pill selectors for Gender and Blood Group, preset chips for Allergies & Medical History with custom additions, DOB maximum date constraint, and sticky modal footer.

---

## 1. Problem Statement

1. **TV Display (`display.html`)**:
   - In portrait mobile view, the header row wraps poorly; the Audio toggle button and the live Clock/Date collide, truncating the date string (e.g. `Friday, September...`).
   - In idle queue state (no active ticket being served), the center ticket display renders a stark `None` in `9xl` font, and the room pill displays `Please proceed to N/A`, looking broken and unprofessional.

2. **Edit Medical Profile Modal (`index.html`)**:
   - Flat unorganized form lacking visual hierarchy or grouping.
   - Gender field is supported in DB and API but completely missing from UI.
   - Blood Group uses standard HTML `<select>` requiring multi-tap dropdown scrolling.
   - Date of Birth allows future dates (`max` attribute not restricted to current date).
   - Allergies and Medical History are raw text inputs without quick presets for common conditions.
   - Save button is pushed below the fold on mobile screens, forcing users to scroll all the way down.

---

## 2. Technical Architecture & UI Components

### A. TV Display (`app/static/display.html`)

1. **Header Layout**:
   - Change `<header>` to responsive flex:
     - `flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 sm:gap-4 pb-4 sm:pb-6 border-b border-[#232c25]`
   - Clinic title container: `flex items-center gap-3 sm:gap-4 min-w-0`
   - Controls & Clock container:
     - `flex items-center justify-between sm:justify-end gap-3 sm:gap-6 w-full sm:w-auto`
   - Date formatting in JS:
     - Use `weekday: 'short'` on narrow viewports or `Intl.DateTimeFormat` so date reads e.g. `Fri, Sep 11, 2026` cleanly without horizontal clipping.

2. **Idle Display State**:
   - Update `renderQueue(data)`:
     ```javascript
     const isServing = current && current !== 'None' && current !== 'STANDBY';
     ```
   - When idle (`!isServing`):
     - `displayTicket` shows `STANDBY` in amber/emerald with tracking-wider.
     - `displayRoom` container text changes from `Please proceed to <room>` to `Waiting for next patient call`.
   - When serving (`isServing`):
     - `displayTicket` shows the active ticket (e.g., `A-102`).
     - Subtitle shows `Please proceed to <room>`.

---

## 3. Edit Medical Profile Modal (`app/static/index.html` & `app.js`)

1. **Modal Layout & Structure**:
   - Max width `max-w-lg`, max height `max-h-[90vh] flex flex-col`.
   - Modal header: title + close `(X)` button, sticky top.
   - Modal body: `overflow-y-auto flex-1 space-y-4 pr-1`.
   - Modal footer: `sticky bottom-0 bg-white/95 backdrop-blur border-t border-stone-200 py-3 px-6 -mx-6 -mb-6 flex justify-end gap-2 mt-4 z-10`.

2. **Sections**:
   - **Section 1: Personal Details**
     - Full Name (`editFullName`) & Phone Number (`editPhone`).
     - Date of Birth (`editDob`) with `max` set to today's date.
     - Gender (`editGender`): 1-tap pill selector: `Male`, `Female`, `Other`.
   - **Section 2: Clinical Profile**
     - Blood Group (`editBloodGroup`): 1-tap pill selector grid: `A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`, `O+`, `O-`.
     - Allergies:
       - Preset chips: `Penicillin`, `Sulfa`, `Aspirin`, `Peanuts`, `Latex`, `None`.
       - Freeform input for custom allergies.
     - Medical History:
       - Preset chips: `Hypertension`, `Diabetes`, `Asthma`, `Heart Disease`, `None`.
       - Textarea for custom medical history notes.
   - **Section 3: Emergency Contact**
     - Emergency Contact Name (`editEmergencyName`) & Phone (`editEmergencyPhone`).

3. **Form Logic (`app.js`)**:
   - `showProfileModal()`:
     - Populates values from `state.user` and `state.user.patient_profile`.
     - Sets active state on Gender and Blood Group pills.
     - Parses comma-separated allergies and medical history to highlight matched preset chips.
     - Sets `max` attribute on `editDob` to current UTC date.
   - Pill click handlers:
     - Toggling gender or blood group sets hidden input value and updates Tailwind active classes (`bg-brand-600 text-white` vs `bg-stone-100 text-stone-700 hover:bg-stone-200`).
     - Toggling allergy/history preset chips adds/removes item from list.
   - `handleProfileUpdate(e)`:
     - Collects form values including `gender`.
     - Sends `PUT /api/auth/profile`.
     - Updates `state.user`, re-renders patient profile card, shows toast.

---

## 4. Backward Compatibility & Test Verification

- `PUT /api/auth/profile` already accepts all fields (`full_name`, `phone`, `date_of_birth`, `gender`, `blood_group`, `allergies`, `medical_history`, `emergency_contact_name`, `emergency_contact_phone`).
- No database migrations needed.
- All 119 pytest tests must continue passing with zero regressions.
