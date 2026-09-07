// Clinic Management System Client Controller
(function () {
  'use strict';

  const API = {
    auth: {
      login: '/api/auth/login',
      me: '/api/auth/me',
      logout: '/api/auth/logout',
    },
    queue: {
      liveStatus: '/api/queue/live-status',
      issue: '/api/queue/issue',
      callNext: '/api/queue/call-next',
      ws: '/api/queue/ws',
    },
    appointments: {
      doctors: '/api/appointments/doctors',
      book: '/api/appointments/book',
      schedule: '/api/appointments/doctor-schedule',
    },
    emr: {
      patient: '/api/emr/patient',
      createPrescription: '/api/emr/prescription/create',
    },
    billing: {
      create: '/api/billing/create',
      list: '/api/billing/list',
    },
    feedback: {
      submit: '/api/feedback',
      analytics: '/api/feedback/analytics',
    },
    chat: {
      history: '/api/chat/history',
      send: '/api/chat/send',
      ws: '/api/chat/ws',
    },
  };

  const state = {
    user: JSON.parse(localStorage.getItem('user_profile') || 'null'),
    activeTab: 'patient',
    selectedRating: 5,
    selectedTags: [],
    myTicket: localStorage.getItem('my_ticket') || null,
    // ponytail: fresh UUID per login; random session IDs prevent guest-session enumeration
    chatSessionId: localStorage.getItem('chat_session_id') || crypto.randomUUID(),
    chatWs: null,
    queueWs: null,
  };
  localStorage.setItem('chat_session_id', state.chatSessionId);

  // Helper: Escape HTML to prevent DOM XSS vulnerabilities
  function escapeHTML(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Inline SVG avatars for generated chat markup (kept in sync with index.html sprite)
  const ICONS = {
    bot: '<svg class="icon w-5 h-5 text-brand-600 mt-0.5 shrink-0" aria-hidden="true"><use href="#i-bot"/></svg>',
    user: '<svg class="icon w-5 h-5 text-slate-400 mt-0.5 shrink-0" aria-hidden="true"><use href="#i-user"/></svg>',
    staff: '<svg class="icon w-5 h-5 text-slate-500 mt-0.5 shrink-0" aria-hidden="true"><use href="#i-clipboard"/></svg>',
  };

  // Helper: Toast Notifications
  function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const colors = {
      success: 'bg-brand-600 text-white',
      error: 'bg-red-600 text-white',
      info: 'bg-slate-900 text-white',
    };

    const toast = document.createElement('div');
    toast.className = `p-3.5 rounded-xl text-xs font-semibold shadow-lg transition-all duration-300 translate-x-4 opacity-0 ${colors[type] || colors.info}`;
    toast.textContent = message;
    container.appendChild(toast);

    requestAnimationFrame(() => {
      toast.classList.remove('translate-x-4', 'opacity-0');
    });

    setTimeout(() => {
      toast.classList.add('opacity-0', 'translate-x-4');
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  // Helper: Fetch using the httpOnly session cookie (same-origin credentials are default)
  async function apiFetch(url, options = {}) {
    options.headers = options.headers || {};
    if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(options.body);
    }

    try {
      const res = await fetch(url, options);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const errorDetail = data.detail || (typeof data === 'string' ? data : 'API Error');
        throw new Error(errorDetail);
      }
      return data;
    } catch (err) {
      console.warn('API Fetch Error:', err.message);
      throw err;
    }
  }

  // Tab Navigation (WAI-ARIA tabs: visual state driven by aria-selected)
  function switchTab(tabName) {
    state.activeTab = tabName;
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.setAttribute('aria-selected', String(btn.id === `tab-${tabName}`));
    });

    document.querySelectorAll('.tab-content').forEach(sec => {
      sec.classList.add('hidden');
    });
    const activeSec = document.getElementById(`portal-${tabName}`);
    if (activeSec) activeSec.classList.remove('hidden');

    if (tabName === 'doctor') {
      loadDoctorSchedule();
      searchPatientEMR(1);
    } else if (tabName === 'staff') {
      fetchQueueStatus();
    } else if (tabName === 'analytics') {
      loadAnalytics();
    } else if (tabName === 'patient') {
      loadDoctors();
      fetchQueueStatus();
    }
  }

  // Auth & Demo Accounts
  const DEMO_ACCOUNTS = {
    patient: { email: 'patient@demo.com', password: 'patient123' },
    doctor: { email: 'doctor@demo.com', password: 'doctor123' },
    staff: { email: 'staff@demo.com', password: 'staff123' },
    admin: { email: 'admin@demo.com', password: 'admin123' },
  };

  async function login(email, password) {
    try {
      const data = await apiFetch(API.auth.login, {
        method: 'POST',
        body: { email, password },
      });
      state.user = data.user;
      localStorage.setItem('user_profile', JSON.stringify(state.user));
      // Fresh chat transcript per login — sessions never carry across accounts
      state.chatSessionId = crypto.randomUUID();
      localStorage.setItem('chat_session_id', state.chatSessionId);

      updateUserUI();
      showToast(`Welcome back, ${state.user.full_name || state.user.email}!`, 'success');

      // Auto-switch to their matching portal
      const roleMap = { patient: 'patient', doctor: 'doctor', staff: 'staff', admin: 'analytics' };
      if (roleMap[state.user.role]) {
        switchTab(roleMap[state.user.role]);
      }
      return data;
    } catch (err) {
      showToast(`Sign in failed: ${err.message}`, 'error');
      throw err;
    }
  }

  async function quickLogin(role) {
    const creds = DEMO_ACCOUNTS[role];
    if (creds) {
      await login(creds.email, creds.password);
    }
  }

  async function logout() {
    try {
      await apiFetch(API.auth.logout, { method: 'POST' }).catch(() => {});
    } finally {
      state.user = null;
      localStorage.removeItem('user_profile');
      localStorage.removeItem('my_ticket');
      state.myTicket = null;
      // New chat session so the next user never inherits this transcript
      state.chatSessionId = crypto.randomUUID();
      localStorage.setItem('chat_session_id', state.chatSessionId);
      updateUserUI();
      showToast('Logged out successfully', 'info');
      switchTab('patient');
    }
  }

  function updateUserUI() {
    const badge = document.getElementById('userProfileBadge');
    const nameEl = document.getElementById('currentUserName');
    const roleEl = document.getElementById('currentUserRole');
    const manualLoginBtn = document.getElementById('manualLoginBtn');
    const logoutBtn = document.getElementById('logoutBtn');

    if (state.user) {
      if (badge) badge.classList.remove('hidden');
      if (nameEl) nameEl.textContent = state.user.full_name || state.user.email;
      if (roleEl) {
        const roleColors = {
          patient: 'bg-sky-100 text-sky-700',
          doctor: 'bg-violet-100 text-violet-700',
          staff: 'bg-amber-100 text-amber-700',
          admin: 'bg-rose-100 text-rose-700',
        };
        roleEl.textContent = state.user.role;
        roleEl.className = 'uppercase px-2 py-0.5 rounded-full text-[10px] font-bold ' +
          (roleColors[state.user.role] || 'bg-slate-200 text-slate-800');
      }
      if (manualLoginBtn) manualLoginBtn.classList.add('hidden');
      if (logoutBtn) logoutBtn.classList.remove('hidden');
    } else {
      if (badge) badge.classList.add('hidden');
      if (manualLoginBtn) manualLoginBtn.classList.remove('hidden');
      if (logoutBtn) logoutBtn.classList.add('hidden');
    }
  }

  // Modals
  function showLoginModal() {
    const modal = document.getElementById('loginModal');
    if (!modal) return;
    modal.classList.remove('hidden');
    const emailInput = document.getElementById('loginEmail');
    if (emailInput) emailInput.focus();
  }

  function hideLoginModal() {
    const modal = document.getElementById('loginModal');
    if (modal) modal.classList.add('hidden');
  }

  async function handleManualLogin(e) {
    e.preventDefault();
    const email = document.getElementById('loginEmail').value;
    const password = document.getElementById('loginPassword').value;
    try {
      await login(email, password);
      hideLoginModal();
    } catch (_) {}
  }
  // Queue Live Updates & Tracker
  async function fetchQueueStatus() {
    try {
      const data = await apiFetch(API.queue.liveStatus);
      renderQueueData(data);
    } catch (err) {
      console.warn('Failed to load queue status:', err);
    }
  }

  function renderQueueData(data) {
    const serving = data.currently_serving || 'None';
    const room = data.currently_serving_room || 'Room N/A';
    const waiting = data.waiting_tickets || [];
    const count = data.waiting_count !== undefined ? data.waiting_count : waiting.length;
    const est = data.estimated_wait_minutes || (count * 10);

    // Patient Portal
    const patServing = document.getElementById('patientServingTicket');
    const patRoom = document.getElementById('patientServingRoom');
    const patCount = document.getElementById('patientWaitingCount');
    const patEst = document.getElementById('patientEstWait');
    if (patServing) patServing.textContent = serving;
    if (patRoom) patRoom.textContent = room;
    if (patCount) patCount.textContent = count;
    if (patEst) patEst.textContent = est + ' min';

    // Staff Portal
    const staffServing = document.getElementById('staffCurrentServing');
    const staffRoom = document.getElementById('staffCurrentRoom');
    const staffCount = document.getElementById('staffWaitingCount');
    const staffList = document.getElementById('staffWaitingList');
    if (staffServing) staffServing.textContent = serving;
    if (staffRoom) staffRoom.textContent = room;
    if (staffCount) staffCount.textContent = count;

    if (staffList) {
      if (waiting.length === 0) {
        staffList.innerHTML = '<span class="text-xs text-slate-400">No patients waiting</span>';
      } else {
        staffList.innerHTML = waiting.map(t => `
          <span class="px-2.5 py-1 rounded-lg bg-amber-100 text-amber-800 font-mono font-bold text-xs">
            ${escapeHTML(t)}
          </span>
        `).join('');
      }
    }

    // Check if active ticket was served
    if (state.myTicket && serving === state.myTicket) {
      showToast(`Attention: Your ticket ${state.myTicket} is now being called to ${room}!`, 'success');
    }
  }

  async function issueMyQueueTicket() {
    if (!state.user || state.user.role !== 'patient') {
      showToast('Please sign in as a patient to get a queue ticket', 'error');
      showLoginModal();
      return;
    }
    const doctorId = parseInt(document.getElementById('appointmentDoctorSelect')?.value, 10);
    try {
      const res = await apiFetch(API.queue.issue, {
        method: 'POST',
        body: doctorId ? { doctor_id: doctorId, priority: 'normal' } : { priority: 'normal' },
      });
      state.myTicket = res.ticket_number;
      localStorage.setItem('my_ticket', state.myTicket);

      const ticketCard = document.getElementById('myTicketCard');
      const ticketNum = document.getElementById('myTicketNumber');
      if (ticketCard && ticketNum) {
        ticketNum.textContent = res.ticket_number;
        ticketCard.classList.remove('hidden');
      }
      showToast(`Queue ticket ${res.ticket_number} issued successfully!`, 'success');
      fetchQueueStatus();
    } catch (err) {
      showToast(`Failed to get ticket: ${err.message}`, 'error');
    }
  }

  async function callNextPatient() {
    const docId = document.getElementById('callDoctorId')?.value || 1;
    try {
      const data = await apiFetch(`${API.queue.callNext}?doctor_id=${docId}`, {
        method: 'POST',
      });
      showToast(`Called patient with ticket: ${data.called_ticket}`, 'success');
      fetchQueueStatus();
    } catch (err) {
      showToast(`Call next failed: ${err.message}`, 'error');
    }
  }

  async function registerWalkin(e) {
    e.preventDefault();
    const patientId = parseInt(document.getElementById('walkinPatientId').value, 10) || 1;
    const doctorId = parseInt(document.getElementById('walkinDoctorSelect').value, 10) || 1;
    const priority = document.getElementById('walkinPriority').value || 'normal';

    try {
      const res = await apiFetch(API.queue.issue, {
        method: 'POST',
        body: { patient_id: patientId, doctor_id: doctorId, priority: priority },
      });

      const resultBox = document.getElementById('walkinTicketResult');
      if (resultBox) {
        resultBox.classList.remove('hidden');
        resultBox.innerHTML = `
          <span class="text-xs text-brand-800 font-semibold block">Ticket Issued Successfully</span>
          <span class="text-3xl font-black text-brand-700 font-mono my-1 block">${escapeHTML(res.ticket_number)}</span>
          <span class="text-[11px] text-brand-600">Patient ID #${patientId} &bull; Triage: ${escapeHTML(priority)}</span>
        `;
      }
      showToast(`Ticket ${res.ticket_number} created!`, 'success');
      fetchQueueStatus();
    } catch (err) {
      showToast(`Walk-in ticket failed: ${err.message}`, 'error');
    }
  }

  // Queue WebSocket with exponential backoff and polling fallback
  let queueWsRetryMs = 1000;
  let queuePollTimer = null;

  function startQueuePolling() {
    if (!queuePollTimer) queuePollTimer = setInterval(fetchQueueStatus, 5000);
  }

  function stopQueuePolling() {
    if (queuePollTimer) {
      clearInterval(queuePollTimer);
      queuePollTimer = null;
    }
  }

  function initQueueWebSocket() {
    if (state.queueWs) {
      try {
        state.queueWs.onclose = null;
        state.queueWs.close();
      } catch (_) {}
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${API.queue.ws}`;

    try {
      state.queueWs = new WebSocket(wsUrl);
    } catch (_) {
      startQueuePolling();
      return;
    }

    state.queueWs.onopen = () => {
      queueWsRetryMs = 1000;
      stopQueuePolling();
      fetchQueueStatus();
    };

    state.queueWs.onmessage = () => {
      fetchQueueStatus();
    };

    state.queueWs.onclose = () => {
      startQueuePolling();
      setTimeout(initQueueWebSocket, queueWsRetryMs);
      queueWsRetryMs = Math.min(queueWsRetryMs * 2, 15000);
    };
  }

  // Appointments
  async function loadDoctors() {
    try {
      const doctors = await apiFetch(API.appointments.doctors);
      const appSelect = document.getElementById('appointmentDoctorSelect');
      const walkSelect = document.getElementById('walkinDoctorSelect');
      const callSelect = document.getElementById('callDoctorId');

      if (doctors && doctors.length > 0) {
        const optionsHtml = doctors.map(d => `
          <option value="${d.id}">${escapeHTML(d.name)} (${escapeHTML(d.specialization)}) - Room ${escapeHTML(String(d.room_number || '102'))}</option>
        `).join('');

        if (appSelect) appSelect.innerHTML = optionsHtml;
        if (walkSelect) walkSelect.innerHTML = optionsHtml;
        if (callSelect) callSelect.innerHTML = optionsHtml;
      }
    } catch (err) {
      console.warn('Failed to load doctors list:', err);
    }
  }

  async function submitAppointment(e) {
    e.preventDefault();
    if (!state.user || state.user.role !== 'patient') {
      showToast('Please sign in as a patient to book an appointment', 'error');
      showLoginModal();
      return;
    }
    const doctorId = parseInt(document.getElementById('appointmentDoctorSelect').value, 10);
    const appointmentDate = document.getElementById('appointmentDate').value;
    const timeSlot = document.getElementById('appointmentTimeSlot').value;
    const reason = document.getElementById('appointmentReason').value;

    try {
      const data = await apiFetch(API.appointments.book, {
        method: 'POST',
        body: {
          doctor_id: doctorId,
          appointment_date: appointmentDate,
          time_slot: timeSlot,
          reason_for_visit: reason,
        },
      });
      showToast(`Appointment confirmed! Booking ID: #${data.appointment_id}`, 'success');
      document.getElementById('appointmentForm').reset();
    } catch (err) {
      showToast(`Booking error: ${err.message}`, 'error');
    }
  }

  // Doctor Schedule
  async function loadDoctorSchedule() {
    const docId = state.user?.doctor_id;
    const dateInput = document.getElementById('scheduleFilterDate');
    if (!docId) {
      const list = document.getElementById('scheduleList');
      if (list) list.innerHTML = '<p class="text-xs text-slate-400 py-6 text-center">Sign in as a doctor to view a schedule.</p>';
      return;
    }
    const scheduleDate = dateInput && dateInput.value ? dateInput.value : new Date().toISOString().split('T')[0];
    if (dateInput && !dateInput.value) dateInput.value = scheduleDate;

    try {
      const data = await apiFetch(`${API.appointments.schedule}/${docId}?schedule_date=${scheduleDate}`);
      const list = document.getElementById('scheduleList');
      if (!list) return;

      if (!data || data.length === 0) {
        list.innerHTML = '<p class="text-xs text-slate-400 py-6 text-center">No appointments scheduled for this date.</p>';
        return;
      }

      list.innerHTML = data.map(app => `
        <div class="p-3 rounded-xl bg-slate-50 border border-slate-200 text-xs flex justify-between items-center gap-2">
          <div class="min-w-0">
            <span class="font-bold text-slate-800 block truncate">${escapeHTML(app.time_slot)} - ${escapeHTML(app.patient_name)}</span>
            <span class="text-slate-500 text-[11px] block truncate">${escapeHTML(app.reason || 'General Consultation')}</span>
          </div>
          <span class="pill bg-brand-100 text-brand-800 uppercase shrink-0">${escapeHTML(app.status)}</span>
        </div>
      `).join('');
    } catch (err) {
      console.warn('Failed to load schedule:', err);
    }
  }

  // EMR & Prescriptions
  async function searchPatientEMR(explicitId = null) {
    const idInput = document.getElementById('emrPatientId');
    const patientId = explicitId || (idInput ? parseInt(idInput.value, 10) : 1) || 1;

    try {
      const emr = await apiFetch(`${API.emr.patient}/${patientId}`);
      document.getElementById('emrName').textContent = emr.name || 'Sarah Connor';
      document.getElementById('emrDob').textContent = `${emr.dob || '1990-05-14'} / ${emr.gender || 'Female'}`;
      document.getElementById('emrBlood').textContent = emr.blood_group || 'O+';
      document.getElementById('emrAllergies').textContent = emr.allergies || 'None';
      document.getElementById('emrHistory').textContent = emr.medical_history || 'No chronic history';

      const rxList = document.getElementById('emrPrescriptionsList');
      if (rxList) {
        if (!emr.prescriptions || emr.prescriptions.length === 0) {
          rxList.innerHTML = '<p class="text-slate-400 py-2 text-center">No previous prescriptions on file.</p>';
        } else {
          rxList.innerHTML = emr.prescriptions.map(rx => `
            <div class="p-2.5 rounded-lg bg-white border border-slate-200 shadow-card">
              <div class="flex justify-between gap-2 font-semibold text-slate-800">
                <span class="truncate">Dx: ${escapeHTML(rx.diagnosis)}</span>
                <span class="text-[10px] text-slate-400 shrink-0">${escapeHTML(rx.created_at)}</span>
              </div>
              <p class="text-slate-500 text-[11px] my-1">${escapeHTML(rx.notes || '')}</p>
              <div class="text-[10px] text-brand-700 bg-brand-50 p-1.5 rounded">
                ${rx.medications ? rx.medications.map(m => `&bull; ${escapeHTML(m.drug_name || m.name || '')} ${escapeHTML(m.dosage || '')}`).join('<br>') : ''}
              </div>
            </div>
          `).join('');
        }
      }
    } catch (err) {
      showToast(`EMR lookup failed: ${err.message}`, 'error');
    }
  }

  function addMedicationRow() {
    const container = document.getElementById('medicationsContainer');
    if (!container) return;
    const row = document.createElement('div');
    row.className = 'med-row bg-slate-50 p-2.5 rounded-xl border border-slate-200 space-y-1.5';
    row.innerHTML = `
      <div class="flex justify-between items-center">
        <span class="text-[10px] font-bold text-slate-500 uppercase">Medication Item</span>
        <button type="button" onclick="this.closest('.med-row').remove()" class="text-red-500 hover:text-red-700 text-xs font-bold px-2 py-1">Remove</button>
      </div>
      <div class="grid grid-cols-2 gap-1.5">
        <input type="text" placeholder="Drug Name" aria-label="Drug name" class="med-name input !px-2.5 !py-2" required>
        <input type="text" placeholder="Dosage" aria-label="Dosage" class="med-dosage input !px-2.5 !py-2" required>
      </div>
      <div class="grid grid-cols-3 gap-1.5">
        <input type="text" placeholder="Frequency" aria-label="Frequency" class="med-freq input !px-2.5 !py-2" required>
        <input type="text" placeholder="Duration" aria-label="Duration" class="med-duration input !px-2.5 !py-2" required>
        <input type="text" placeholder="Instructions" aria-label="Instructions" class="med-instructions input !px-2.5 !py-2">
      </div>
    `;
    container.appendChild(row);
  }

  async function generatePrescription(e) {
    e.preventDefault();
    const patientId = parseInt(document.getElementById('rxPatientId').value, 10);
    const diagnosis = document.getElementById('rxDiagnosis').value;
    const clinicalNotes = document.getElementById('rxNotes').value;

    const rows = document.querySelectorAll('#medicationsContainer .med-row');
    const medications = [];
    rows.forEach(r => {
      medications.push({
        drug_name: r.querySelector('.med-name').value,
        dosage: r.querySelector('.med-dosage').value,
        frequency: r.querySelector('.med-freq').value,
        duration: r.querySelector('.med-duration').value,
        instructions: r.querySelector('.med-instructions').value || '',
      });
    });

    try {
      const res = await apiFetch(API.emr.createPrescription, {
        method: 'POST',
        body: {
          patient_id: patientId,
          diagnosis: diagnosis,
          clinical_notes: clinicalNotes,
          medications: medications,
        },
      });

      const card = document.getElementById('prescriptionResultCard');
      if (card) {
        const qrImg = res.qr_code_image
          ? `<img src="${res.qr_code_image}" alt="Prescription verification QR code" class="w-14 h-14 rounded border border-brand-300 bg-white p-0.5">`
          : `<div class="w-12 h-12 bg-white rounded-lg border border-brand-300 flex items-center justify-center font-mono font-bold text-xl text-brand-700 shadow-card shrink-0">QR</div>`;
        card.classList.remove('hidden');
        card.innerHTML = `
          <div class="flex items-center gap-3 mb-2">
            ${qrImg}
            <div class="min-w-0">
              <span class="text-brand-900 font-bold block">Digital Prescription Issued</span>
              <span class="text-[10px] text-brand-700 font-mono break-all">HASH: ${escapeHTML(res.qr_code_hash)}</span>
            </div>
          </div>
          <p class="text-[11px] text-brand-800">Prescription #${res.prescription_id} securely saved and linked to patient record.</p>
        `;
      }
      showToast('Digital prescription generated with tamper-proof QR hash!', 'success');
      searchPatientEMR(patientId);
    } catch (err) {
      showToast(`Prescription creation failed: ${err.message}`, 'error');
    }
  }

  // Billing & Invoicing
  function calculateBillPreview() {
    const cFee = parseFloat(document.getElementById('billConsultation').value) || 0;
    const mFee = parseFloat(document.getElementById('billMedication').value) || 0;
    const oFee = parseFloat(document.getElementById('billOther').value) || 0;
    const discount = parseFloat(document.getElementById('billDiscount').value) || 0;
    const total = Math.max(0, (cFee + mFee + oFee) - discount);
    const prev = document.getElementById('billTotalPreview');
    if (prev) prev.textContent = `$${total.toFixed(2)}`;
  }

  async function createInvoice(e) {
    e.preventDefault();
    const patientId = parseInt(document.getElementById('billPatientId').value, 10);
    const ticketIdInput = document.getElementById('billTicketId').value;
    const ticketId = ticketIdInput ? parseInt(ticketIdInput, 10) : null;
    const cFee = parseFloat(document.getElementById('billConsultation').value) || 0;
    const mFee = parseFloat(document.getElementById('billMedication').value) || 0;
    const oFee = parseFloat(document.getElementById('billOther').value) || 0;
    const discount = parseFloat(document.getElementById('billDiscount').value) || 0;
    const method = document.getElementById('billPaymentMethod').value;

    try {
      const res = await apiFetch(API.billing.create, {
        method: 'POST',
        body: {
          patient_id: patientId,
          queue_ticket_id: ticketId,
          consultation_fee: cFee,
          medication_fee: mFee,
          other_fees: oFee,
          discount_amount: discount,
          payment_method: method,
        },
      });

      const card = document.getElementById('billingResultCard');
      if (card) {
        card.classList.remove('hidden');
        card.innerHTML = `
          <span class="text-xs font-bold text-slate-800 block">Receipt: ${escapeHTML(res.receipt_number)}</span>
          <div class="flex justify-between items-center my-1 text-slate-600">
            <span>Total Paid (${escapeHTML(method.toUpperCase())}):</span>
            <span class="font-extrabold text-slate-900">$${res.total.toFixed(2)}</span>
          </div>
          <span class="text-[10px] text-brand-600 font-semibold block">Transaction Finalized &amp; Paid</span>
        `;
      }
      showToast(`Invoice ${res.receipt_number} generated!`, 'success');
    } catch (err) {
      showToast(`Invoice generation failed: ${err.message}`, 'error');
    }
  }
  // Feedback & Sentiment Analytics
  function setStarRating(rating) {
    state.selectedRating = rating;
    const input = document.getElementById('feedbackRating');
    if (input) input.value = rating;

    const btns = document.querySelectorAll('#starRatingGroup .star-btn');
    btns.forEach((b, idx) => {
      const active = idx < rating;
      b.classList.toggle('text-amber-400', active);
      b.classList.toggle('text-slate-300', !active);
      b.setAttribute('aria-pressed', String(active));
    });
  }

  function toggleTag(el) {
    const text = el.textContent.trim();
    const idx = state.selectedTags.indexOf(text);
    const pressed = idx === -1;
    if (pressed) {
      state.selectedTags.push(text);
    } else {
      state.selectedTags.splice(idx, 1);
    }
    el.setAttribute('aria-pressed', String(pressed));
  }

  async function submitFeedback(e) {
    e.preventDefault();
    if (!state.user || state.user.role !== 'patient') {
      showToast('Please sign in as a patient to submit feedback', 'error');
      showLoginModal();
      return;
    }
    const comment = document.getElementById('feedbackComment').value;
    const rating = state.selectedRating;
    const tags = state.selectedTags;

    try {
      const data = await apiFetch(API.feedback.submit, {
        method: 'POST',
        body: {
          rating: rating,
          comment_text: comment,
          tags: tags,
        },
      });

      const resBox = document.getElementById('feedbackSentimentResult');
      if (resBox) {
        resBox.classList.remove('hidden');
        const sent = data.sentiment || data;
        const sentLabel = sent.sentiment_label || 'neutral';
        const sentScore = (sent.sentiment_score ?? 0).toFixed(3);
        const isCritical = Boolean(sent.flagged_critical || sent.is_critical);

        const badgeColor = sentLabel === 'positive' ? 'bg-brand-100 text-brand-800' :
          sentLabel === 'negative' ? 'bg-rose-100 text-rose-800' : 'bg-slate-100 text-slate-800';

        resBox.innerHTML = `
          <div class="flex justify-between items-center mb-1 gap-2">
            <span class="font-bold text-slate-800">VADER Sentiment Analysis</span>
            <span class="pill ${badgeColor}">${escapeHTML(sentLabel)}</span>
          </div>
          <div class="text-[11px] text-slate-600">
            Compound Score: <strong>${sentScore}</strong>
            ${isCritical ? '<span class="ml-2 text-red-600 font-bold">CRITICAL ALERT</span>' : ''}
          </div>
        `;
      }
      showToast('Thank you! Feedback analyzed successfully.', 'success');
      document.getElementById('feedbackForm').reset();
      setStarRating(5);
      // Reset tags so the next submission doesn't inherit the previous review's chips
      state.selectedTags = [];
      document.querySelectorAll('#feedbackTagsGroup .chip').forEach(chip => {
        chip.setAttribute('aria-pressed', 'false');
      });
    } catch (err) {
      showToast(`Feedback submission failed: ${err.message}`, 'error');
    }
  }

  async function loadAnalytics() {
    try {
      const data = await apiFetch(API.feedback.analytics);
      const nssEl = document.getElementById('statNSS');
      const nssStatus = document.getElementById('statNSSStatus');
      const avgRating = document.getElementById('statAvgRating');
      const totalRev = document.getElementById('statTotalReviews');

      const total = data.total ?? data.total_feedbacks ?? 0;
      const avg = data.avg_rating ?? data.average_rating ?? 5.0;

      // Handle both router schema { positive_pct, negative_pct } and legacy distribution object
      const posPct = data.positive_pct !== undefined ? data.positive_pct :
        (data.sentiment_distribution ? (data.sentiment_distribution.positive / (total || 1)) * 100 : 0);
      const negPct = data.negative_pct !== undefined ? data.negative_pct :
        (data.sentiment_distribution ? (data.sentiment_distribution.negative / (total || 1)) * 100 : 0);
      const neuPct = Math.max(0, Math.round(100 - posPct - negPct));

      const nss = Math.round(posPct - negPct);

      if (nssEl) {
        nssEl.textContent = (nss >= 0 ? '+' : '') + nss.toFixed(1);
        nssEl.className = `stat-value ${nss >= 0 ? 'text-brand-600' : 'text-rose-600'}`;
      }
      if (nssStatus) {
        nssStatus.textContent = nss >= 50 ? 'Excellent Experience' : nss >= 0 ? 'Good / Neutral' : 'Requires Attention';
      }
      if (avgRating) avgRating.textContent = Number(avg).toFixed(1);
      if (totalRev) totalRev.textContent = total;

      // Distribution bars
      document.getElementById('distPositivePercent').textContent = `${Math.round(posPct)}%`;
      document.getElementById('barPositive').style.width = `${Math.round(posPct)}%`;

      document.getElementById('distNeutralPercent').textContent = `${neuPct}%`;
      document.getElementById('barNeutral').style.width = `${neuPct}%`;

      document.getElementById('distNegativePercent').textContent = `${Math.round(negPct)}%`;
      document.getElementById('barNegative').style.width = `${Math.round(negPct)}%`;

      // Critical alerts: check data.critical_alerts or filter from data.items
      const rawAlerts = data.critical_alerts ||
        (data.items ? data.items.filter(i => i.flagged_critical) : []);
      const criticalCount = data.critical_count !== undefined ? data.critical_count : rawAlerts.length;

      const badge = document.getElementById('criticalAlertsBadge');
      if (badge) badge.textContent = `${criticalCount} Active`;

      const list = document.getElementById('criticalAlertsList');
      if (list) {
        if (rawAlerts.length === 0) {
          list.innerHTML = '<p class="text-slate-400 py-6 text-center">No critical negative complaints detected.</p>';
        } else {
          list.innerHTML = rawAlerts.map(a => {
            const r = a.rating ?? 1;
            const score = a.sentiment_score !== undefined ? a.sentiment_score.toFixed(2) : '-';
            const comment = escapeHTML(a.comment ?? a.comment_text ?? '');
            const pId = a.patient_id ? `Patient ID: #${a.patient_id} &bull; ` : '';
            const dt = escapeHTML(a.created_at || '');
            return `
              <div class="p-3 rounded-xl bg-red-50 border border-red-200">
                <div class="flex justify-between items-center text-red-700 font-bold mb-1 gap-2">
                  <span>Rating: ${r} / 5 &bull; Score: ${score}</span>
                  <span class="pill bg-red-200 text-red-900 shrink-0">URGENT</span>
                </div>
                <p class="text-slate-800">"${comment}"</p>
                <span class="text-[10px] text-slate-500 mt-1 block">${pId}${dt}</span>
              </div>
            `;
          }).join('');
        }
      }
    } catch (err) {
      console.warn('Failed to load analytics:', err);
    }
  }

  // Live Chat Widget
  function toggleChat() {
    const win = document.getElementById('chatWindow');
    const launcher = document.getElementById('chatLauncher');
    if (!win) return;
    const isHidden = win.classList.contains('hidden');
    if (isHidden) {
      win.classList.remove('hidden');
      if (launcher) launcher.setAttribute('aria-expanded', 'true');
      if (!state.chatWs || state.chatWs.readyState !== WebSocket.OPEN) {
        initChatWebSocket();
      }
      const chatInput = document.getElementById('chatInput');
      if (chatInput) chatInput.focus();
    } else {
      win.classList.add('hidden');
      if (launcher) launcher.setAttribute('aria-expanded', 'false');
    }
  }

  function initChatWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${API.chat.ws}/${state.chatSessionId}`;

    state.chatWs = new WebSocket(wsUrl);

    state.chatWs.onopen = async () => {
      // Load persisted history once WS is ready
      try {
        const history = await apiFetch(`${API.chat.history}/${state.chatSessionId}`);
        if (Array.isArray(history) && history.length) {
          const box = document.getElementById('chatMessages');
          if (box) box.innerHTML = ''; // clear the static greeting so we show real history
          history.forEach(appendChatMessage);
        }
      } catch (_) { /* not authenticated yet or no history — keep static greeting */ }
    };

    state.chatWs.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        appendChatMessage(payload);
      } catch (err) {
        console.warn('Chat parse error:', err);
      }
    };

    state.chatWs.onclose = () => {
      console.log('Chat WebSocket closed');
    };
  }

  function appendChatMessage(msg) {
    const box = document.getElementById('chatMessages');
    if (!box) return;

    const isBot = msg.is_bot_reply || msg.role === 'bot' || msg.sender === 'Clinic Assistant Bot';
    // Identity-based: a message is "mine" only if the server says it came from me
    const isMe = !isBot && state.user && (msg.sender === state.user.full_name || msg.sender_name === state.user.full_name);
    const safeText = escapeHTML(msg.message || msg.message_text || '');
    const safeSender = escapeHTML(msg.sender || msg.sender_name || 'Staff');

    const div = document.createElement('div');
    div.className = `flex items-start gap-2 ${isMe && !isBot ? 'justify-end' : 'justify-start'}`;

    if (isBot) {
      div.innerHTML = `
        ${ICONS.bot}
        <div class="bg-slate-100 text-slate-800 p-3 rounded-2xl rounded-tl-none max-w-[85%] leading-relaxed">
          <span class="text-[10px] font-bold text-slate-500 block mb-0.5">Clinic Virtual Bot</span>
          ${safeText}
        </div>
      `;
    } else if (isMe) {
      div.innerHTML = `
        <div class="bg-brand-600 text-white p-3 rounded-2xl rounded-tr-none max-w-[85%] leading-relaxed">
          ${safeText}
        </div>
        ${ICONS.user}
      `;
    } else {
      div.innerHTML = `
        ${ICONS.staff}
        <div class="bg-slate-100 text-slate-800 p-3 rounded-2xl rounded-tl-none max-w-[85%] leading-relaxed">
          <span class="text-[10px] font-bold text-slate-500 block mb-0.5">${safeSender}</span>
          ${safeText}
        </div>
      `;
    }

    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  async function sendChatMessage(text) {
    if (!text || !text.trim()) return;
    const msg = text.trim();

    // Identity (name/role) is derived server-side from the session cookie
    const payload = {
      session_id: state.chatSessionId,
      message: msg,
      message_text: msg,
    };

    if (state.chatWs && state.chatWs.readyState === WebSocket.OPEN) {
      state.chatWs.send(JSON.stringify(payload));
    } else {
      // Fallback to REST API
      try {
        const res = await apiFetch(API.chat.send, {
          method: 'POST',
          body: payload,
        });
        appendChatMessage(payload);
        if (res.bot_reply) {
          appendChatMessage({
            sender: 'Clinic Assistant Bot',
            role: 'bot',
            is_bot_reply: true,
            message: res.bot_reply.message || res.bot_reply.message_text,
          });
        }
      } catch (err) {
        showToast(err.message.includes('authenticated')
          ? 'Please sign in to use live chat'
          : 'Chat service unavailable', 'error');
      }
    }
  }

  function sendChatInput(e) {
    e.preventDefault();
    const input = document.getElementById('chatInput');
    if (!input) return;
    const text = input.value;
    input.value = '';
    sendChatMessage(text);
  }

  function sendQuickFaq(question) {
    sendChatMessage(question);
  }

  // Close overlays with the Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const loginModal = document.getElementById('loginModal');
    if (loginModal && !loginModal.classList.contains('hidden')) {
      hideLoginModal();
      return;
    }
    const chatWin = document.getElementById('chatWindow');
    if (chatWin && !chatWin.classList.contains('hidden')) {
      toggleChat();
    }
  });

  // Initialize on page load
  async function init() {
    updateUserUI();
    loadDoctors();
    fetchQueueStatus();
    initQueueWebSocket();

    // Default appointment date to today
    const appDate = document.getElementById('appointmentDate');
    if (appDate) appDate.value = new Date().toISOString().split('T')[0];

    // Restore persisted ticket card
    if (state.myTicket) {
      const ticketCard = document.getElementById('myTicketCard');
      const ticketNum = document.getElementById('myTicketNumber');
      if (ticketCard && ticketNum) {
        ticketNum.textContent = state.myTicket;
        ticketCard.classList.remove('hidden');
      }
    }

    // Restore session from the httpOnly cookie (cookie auth is the single source of truth)
    try {
      const me = await apiFetch(API.auth.me);
      state.user = me;
      localStorage.setItem('user_profile', JSON.stringify(me));
    } catch (_) {
      state.user = null;
      localStorage.removeItem('user_profile');
    }
    updateUserUI();
    switchTab('patient');
  }

  // Expose methods to window.ClinicApp
  window.ClinicApp = {
    switchTab,
    login,
    quickLogin,
    logout,
    showLoginModal,
    hideLoginModal,
    handleManualLogin,
    fetchQueueStatus,
    issueMyQueueTicket,
    callNextPatient,
    registerWalkin,
    submitAppointment,
    loadDoctorSchedule,
    searchPatientEMR,
    addMedicationRow,
    generatePrescription,
    calculateBillPreview,
    createInvoice,
    setStarRating,
    toggleTag,
    submitFeedback,
    loadAnalytics,
    toggleChat,
    sendChatMessage,
    sendChatInput,
    sendQuickFaq,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();