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
    token: localStorage.getItem('access_token') || null,
    user: JSON.parse(localStorage.getItem('user_profile') || 'null'),
    activeTab: 'patient',
    selectedRating: 5,
    selectedTags: [],
    myTicket: localStorage.getItem('my_ticket') || null,
    chatSessionId: localStorage.getItem('chat_session_id') || ('sess_' + Math.random().toString(36).substring(2, 9)),
    chatWs: null,
    queueWs: null,
  };
  localStorage.setItem('chat_session_id', state.chatSessionId);

  // Helper: Toast Notifications
  function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const colors = {
      success: 'bg-emerald-600 text-white border-emerald-700',
      error: 'bg-red-600 text-white border-red-700',
      info: 'bg-slate-900 text-white border-slate-950',
    };

    const toast = document.createElement('div');
    toast.className = `p-3 rounded-xl text-xs font-semibold shadow-lg border transition-all duration-300 transform translate-x-4 opacity-0 ${colors[type] || colors.info}`;
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

  // Helper: Fetch with Bearer Auth
  async function apiFetch(url, options = {}) {
    options.headers = options.headers || {};
    if (state.token) {
      options.headers['Authorization'] = `Bearer ${state.token}`;
    }
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

  // Tab Navigation
  function switchTab(tabName) {
    state.activeTab = tabName;
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.classList.remove('tab-active');
    });
    const activeBtn = document.getElementById(`tab-${tabName}`);
    if (activeBtn) activeBtn.classList.add('tab-active');

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
      state.token = data.access_token;
      state.user = data.user;
      localStorage.setItem('access_token', state.token);
      localStorage.setItem('user_profile', JSON.stringify(state.user));

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
      state.token = null;
      state.user = null;
      localStorage.removeItem('access_token');
      localStorage.removeItem('user_profile');
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
        roleEl.textContent = state.user.role;
        roleEl.className = 'uppercase px-2 py-0.5 rounded-full text-[10px] font-bold ' +
          (state.user.role === 'patient' ? 'bg-blue-100 text-blue-700' :
           state.user.role === 'doctor' ? 'bg-purple-100 text-purple-700' :
           state.user.role === 'staff' ? 'bg-amber-100 text-amber-700' : 'bg-rose-100 text-rose-700');
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
    if (modal) modal.classList.remove('hidden');
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
            ${t}
          </span>
        `).join('');
      }
    }

    // Check if active ticket was served
    if (state.myTicket && serving === state.myTicket) {
      showToast(`🔔 Attention: Your ticket ${state.myTicket} is now being called to ${room}!`, 'success');
    }
  }

  async function issueMyQueueTicket() {
    try {
      const res = await apiFetch(API.queue.issue, {
        method: 'POST',
        body: { patient_id: 1, doctor_id: 1, priority: 'normal' },
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
          <span class="text-xs text-emerald-800 font-semibold block">Ticket Issued Successfully</span>
          <span class="text-3xl font-black text-emerald-700 font-mono my-1 block">${res.ticket_number}</span>
          <span class="text-[11px] text-emerald-600">Patient ID #${patientId} &bull; Triage: ${priority}</span>
        `;
      }
      showToast(`Ticket ${res.ticket_number} created!`, 'success');
      fetchQueueStatus();
    } catch (err) {
      showToast(`Walk-in ticket failed: ${err.message}`, 'error');
    }
  }

  // Queue WebSocket
  function initQueueWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${API.queue.ws}`;

    state.queueWs = new WebSocket(wsUrl);

    state.queueWs.onopen = () => {
      fetchQueueStatus();
    };

    state.queueWs.onmessage = () => {
      fetchQueueStatus();
    };

    state.queueWs.onclose = () => {
      setTimeout(initQueueWebSocket, 3000);
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
          <option value="${d.id}">${d.name} (${d.specialization}) - Room ${d.room_number || '102'}</option>
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
    if (!state.user) {
      await quickLogin('patient');
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
    const docId = 1;
    const dateInput = document.getElementById('scheduleFilterDate');
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
        <div class="p-3 rounded-xl bg-slate-50 border border-slate-200 text-xs flex justify-between items-center">
          <div>
            <span class="font-bold text-slate-800 block">${app.time_slot} - ${app.patient_name}</span>
            <span class="text-slate-500 text-[11px]">${app.reason || 'General Consultation'}</span>
          </div>
          <span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 uppercase">
            ${app.status}
          </span>
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
            <div class="p-2.5 rounded-lg bg-white border border-slate-200 shadow-sm">
              <div class="flex justify-between font-semibold text-slate-800">
                <span>Dx: ${rx.diagnosis}</span>
                <span class="text-[10px] text-slate-400">${rx.created_at}</span>
              </div>
              <p class="text-slate-500 text-[11px] my-1">${rx.notes || ''}</p>
              <div class="text-[10px] text-purple-700 bg-purple-50 p-1.5 rounded">
                ${rx.medications ? rx.medications.map(m => `&bull; ${m.drug_name || m.name} ${m.dosage || ''}`).join('<br>') : ''}
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
    row.className = 'med-row bg-slate-50 p-2.5 rounded-lg border border-slate-200 space-y-1.5';
    row.innerHTML = `
      <div class="flex justify-between items-center">
        <span class="text-[10px] font-bold text-slate-500 uppercase">Medication Item</span>
        <button type="button" onclick="this.closest('.med-row').remove()" class="text-red-500 hover:text-red-700 text-xs font-bold">✕ Remove</button>
      </div>
      <div class="grid grid-cols-2 gap-1.5">
        <input type="text" placeholder="Drug Name" class="med-name rounded border border-slate-300 p-1.5" required>
        <input type="text" placeholder="Dosage" class="med-dosage rounded border border-slate-300 p-1.5" required>
      </div>
      <div class="grid grid-cols-3 gap-1.5">
        <input type="text" placeholder="Frequency" class="med-freq rounded border border-slate-300 p-1.5" required>
        <input type="text" placeholder="Duration" class="med-duration rounded border border-slate-300 p-1.5" required>
        <input type="text" placeholder="Instructions" class="med-instructions rounded border border-slate-300 p-1.5">
      </div>
    `;
    container.appendChild(row);
  }

  async function generatePrescription(e) {
    e.preventDefault();
    const patientId = parseInt(document.getElementById('rxPatientId').value, 10);
    const doctorId = parseInt(document.getElementById('rxDoctorId').value, 10);
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
          doctor_id: doctorId,
          diagnosis: diagnosis,
          clinical_notes: clinicalNotes,
          medications: medications,
        },
      });

      const card = document.getElementById('prescriptionResultCard');
      if (card) {
        card.classList.remove('hidden');
        card.innerHTML = `
          <div class="flex items-center space-x-3 mb-2">
            <div class="w-12 h-12 bg-white rounded-lg border border-purple-300 flex items-center justify-center font-mono font-bold text-xl text-purple-700 shadow-sm">
              QR
            </div>
            <div>
              <span class="text-purple-900 font-bold block">Digital Prescription Issued</span>
              <span class="text-[10px] text-purple-700 font-mono">HASH: ${res.qr_code_hash}</span>
            </div>
          </div>
          <p class="text-[11px] text-purple-800">Prescription #${res.prescription_id} securely saved and linked to patient record.</p>
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
          <span class="text-xs font-bold text-slate-800 block">Receipt: ${res.receipt_number}</span>
          <div class="flex justify-between items-center my-1 text-slate-600">
            <span>Total Paid (${method.toUpperCase()}):</span>
            <span class="font-extrabold text-slate-900">$${res.total.toFixed(2)}</span>
          </div>
          <span class="text-[10px] text-emerald-600 font-semibold block">✓ Transaction Finalized & Paid</span>
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
      if (idx < rating) {
        b.classList.remove('text-slate-300');
        b.classList.add('text-amber-400');
      } else {
        b.classList.remove('text-amber-400');
        b.classList.add('text-slate-300');
      }
    });
  }

  function toggleTag(el) {
    const text = el.textContent.trim();
    const idx = state.selectedTags.indexOf(text);
    if (idx > -1) {
      state.selectedTags.splice(idx, 1);
      el.classList.remove('bg-emerald-600', 'text-white', 'border-emerald-600');
      el.classList.add('bg-slate-100', 'text-slate-700', 'border-slate-200');
    } else {
      state.selectedTags.push(text);
      el.classList.remove('bg-slate-100', 'text-slate-700', 'border-slate-200');
      el.classList.add('bg-emerald-600', 'text-white', 'border-emerald-600');
    }
  }

  async function submitFeedback(e) {
    e.preventDefault();
    if (!state.user) {
      await quickLogin('patient');
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
          doctor_id: 1,
        },
      });

      const resBox = document.getElementById('feedbackSentimentResult');
      if (resBox) {
        resBox.classList.remove('hidden');
        const badgeColor = data.sentiment_label === 'positive' ? 'bg-emerald-100 text-emerald-800' :
          data.sentiment_label === 'negative' ? 'bg-rose-100 text-rose-800' : 'bg-slate-100 text-slate-800';

        resBox.innerHTML = `
          <div class="flex justify-between items-center mb-1">
            <span class="font-bold text-slate-800">VADER Sentiment Analysis</span>
            <span class="px-2 py-0.5 rounded-full text-[10px] font-extrabold uppercase ${badgeColor}">
              ${data.sentiment_label}
            </span>
          </div>
          <div class="text-[11px] text-slate-600">
            Compound Score: <strong>${data.sentiment_score.toFixed(3)}</strong>
            ${data.is_critical ? '<span class="ml-2 text-red-600 font-bold">⚠️ CRITICAL ALERT</span>' : ''}
          </div>
        `;
      }
      showToast('Thank you! Feedback analyzed successfully.', 'success');
      document.getElementById('feedbackForm').reset();
      setStarRating(5);
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

      if (nssEl) {
        const nss = data.net_sentiment_score || 0;
        nssEl.textContent = (nss >= 0 ? '+' : '') + nss.toFixed(1);
        nssEl.className = `text-4xl font-black ${nss >= 0 ? 'text-emerald-600' : 'text-rose-600'}`;
      }
      if (nssStatus) {
        const nss = data.net_sentiment_score || 0;
        nssStatus.textContent = nss >= 50 ? 'Excellent Experience' : nss >= 0 ? 'Good / Neutral' : 'Requires Attention';
      }
      if (avgRating) avgRating.textContent = (data.average_rating || 0).toFixed(1);
      if (totalRev) totalRev.textContent = data.total_feedbacks || 0;

      // Distribution bars
      const dist = data.sentiment_distribution || { positive: 0, neutral: 0, negative: 0 };
      const total = (dist.positive + dist.neutral + dist.negative) || 1;

      const pPct = Math.round((dist.positive / total) * 100);
      const nPct = Math.round((dist.neutral / total) * 100);
      const negPct = Math.round((dist.negative / total) * 100);

      document.getElementById('distPositivePercent').textContent = `${pPct}% (${dist.positive})`;
      document.getElementById('barPositive').style.width = `${pPct}%`;

      document.getElementById('distNeutralPercent').textContent = `${nPct}% (${dist.neutral})`;
      document.getElementById('barNeutral').style.width = `${nPct}%`;

      document.getElementById('distNegativePercent').textContent = `${negPct}% (${dist.negative})`;
      document.getElementById('barNegative').style.width = `${negPct}%`;

      // Critical alerts
      const alerts = data.critical_alerts || [];
      const badge = document.getElementById('criticalAlertsBadge');
      if (badge) badge.textContent = `${alerts.length} Active`;

      const list = document.getElementById('criticalAlertsList');
      if (list) {
        if (alerts.length === 0) {
          list.innerHTML = '<p class="text-slate-400 py-6 text-center">No critical negative complaints detected.</p>';
        } else {
          list.innerHTML = alerts.map(a => `
            <div class="p-3 rounded-xl bg-red-50 border border-red-200 text-xs">
              <div class="flex justify-between items-center text-red-700 font-bold mb-1">
                <span>Rating: ${a.rating} ★ &bull; Score: ${a.sentiment_score ? a.sentiment_score.toFixed(2) : '-'}</span>
                <span class="text-[10px] bg-red-200 text-red-900 px-2 py-0.5 rounded-full font-bold">URGENT</span>
              </div>
              <p class="text-slate-800">"${a.comment_text}"</p>
              <span class="text-[10px] text-slate-500 mt-1 block">Patient ID: #${a.patient_id} &bull; ${a.created_at || ''}</span>
            </div>
          `).join('');
        }
      }
    } catch (err) {
      console.warn('Failed to load analytics:', err);
    }
  }

  // Live Chat Widget
  function toggleChat() {
    const win = document.getElementById('chatWindow');
    if (!win) return;
    const isHidden = win.classList.contains('hidden');
    if (isHidden) {
      win.classList.remove('hidden');
      if (!state.chatWs || state.chatWs.readyState !== WebSocket.OPEN) {
        initChatWebSocket();
      }
    } else {
      win.classList.add('hidden');
    }
  }

  function initChatWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${API.chat.ws}/${state.chatSessionId}`;

    state.chatWs = new WebSocket(wsUrl);

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

    const isMe = msg.role === 'patient' || (state.user && msg.sender === state.user.full_name);
    const isBot = msg.is_bot_reply || msg.role === 'bot' || msg.sender === 'Clinic Assistant Bot';

    const div = document.createElement('div');
    div.className = `flex items-start gap-2 ${isMe && !isBot ? 'justify-end' : 'justify-start'}`;

    if (isBot) {
      div.innerHTML = `
        <span class="text-base">🤖</span>
        <div class="bg-emerald-50 text-emerald-950 border border-emerald-200 p-3 rounded-2xl rounded-tl-none max-w-[85%] leading-relaxed">
          <span class="text-[10px] font-bold text-emerald-700 block mb-0.5">Clinic Virtual Bot</span>
          ${msg.message || msg.message_text}
        </div>
      `;
    } else if (isMe) {
      div.innerHTML = `
        <div class="bg-blue-600 text-white p-3 rounded-2xl rounded-tr-none max-w-[85%] leading-relaxed">
          ${msg.message || msg.message_text}
        </div>
        <span class="text-base">👤</span>
      `;
    } else {
      div.innerHTML = `
        <span class="text-base">📋</span>
        <div class="bg-slate-100 text-slate-800 p-3 rounded-2xl rounded-tl-none max-w-[85%] leading-relaxed">
          <span class="text-[10px] font-bold text-slate-600 block mb-0.5">${msg.sender || 'Staff'}</span>
          ${msg.message || msg.message_text}
        </div>
      `;
    }

    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  async function sendChatMessage(text) {
    if (!text || !text.trim()) return;
    const msg = text.trim();
    const senderName = state.user ? state.user.full_name : 'Patient (Guest)';
    const senderRole = state.user ? state.user.role : 'patient';

    const payload = {
      session_id: state.chatSessionId,
      sender_name: senderName,
      sender: senderName,
      sender_role: senderRole,
      role: senderRole,
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
          body: {
            session_id: state.chatSessionId,
            sender_name: senderName,
            role: senderRole,
            message: msg,
          },
        });
        appendChatMessage(payload);
        if (res.reply) {
          appendChatMessage({
            sender: 'Clinic Assistant Bot',
            role: 'bot',
            is_bot_reply: true,
            message: res.reply,
          });
        }
      } catch (err) {
        showToast('Chat service unavailable', 'error');
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

  // Initialize on page load
  async function init() {
    updateUserUI();
    loadDoctors();
    fetchQueueStatus();
    initQueueWebSocket();

    // Default appointment date to today
    const appDate = document.getElementById('appointmentDate');
    if (appDate) appDate.value = new Date().toISOString().split('T')[0];

    // Check existing token validity
    if (state.token) {
      try {
        const me = await apiFetch(API.auth.me);
        state.user = me;
        localStorage.setItem('user_profile', JSON.stringify(me));
        updateUserUI();
      } catch (_) {
        state.token = null;
        state.user = null;
        localStorage.removeItem('access_token');
        localStorage.removeItem('user_profile');
        updateUserUI();
      }
    }
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

