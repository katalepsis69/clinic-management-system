// Clinic Management System Client Controller
(function () {
  'use strict';

  // ponytail: anti-inspect deterrent; block contextmenu, devtools shortcuts, debugger trap & DOM wipe on inspection
  document.addEventListener('contextmenu', (e) => e.preventDefault());
  document.addEventListener('keydown', (e) => {
    if (
      e.key === 'F12' ||
      ((e.ctrlKey || e.metaKey) && (
        (e.shiftKey && ['I', 'J', 'C'].includes(e.key.toUpperCase())) ||
        ['U', 'S'].includes(e.key.toUpperCase())
      ))
    ) {
      e.preventDefault();
    }
  });

  setInterval(() => {
    const t0 = performance.now();
    // eslint-disable-next-line no-debugger
    debugger;
    if (performance.now() - t0 > 800) {
      document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;min-height:100vh;background:#121614;color:#ef4444;font-family:sans-serif;font-size:20px;font-weight:700;">Developer Tools Detected - Access Disabled</div>';
    }
    console.clear();
  }, 1000);

  ['log', 'debug', 'info', 'warn', 'error'].forEach((m) => { console[m] = () => {}; });

  const API = {
    auth: {
      login: '/api/auth/login',
      register: '/api/auth/register',
      profile: '/api/auth/profile',
      me: '/api/auth/me',
      logout: '/api/auth/logout',
      setupStatus: '/api/auth/setup-status',
      setupAdmin: '/api/auth/setup-admin',
    },
    admin: {
      users: '/api/admin/users',
    },
    queue: {
      liveStatus: '/api/queue/live-status',
      active: '/api/queue/active',
      myTicket: '/api/queue/my-ticket',
      issue: '/api/queue/issue',
      walkinRegister: '/api/queue/walkin-register',
      callNext: '/api/queue/call-next',
      advance: '/api/queue/advance',
      patients: '/api/queue/patients',
      ws: '/api/queue/ws',
    },
    appointments: {
      doctors: '/api/appointments/doctors',
      book: '/api/appointments/book',
      my: '/api/appointments/my',
      daily: '/api/appointments/daily',
      doctorPending: '/api/appointments/doctor-pending',
      base: '/api/appointments',
      schedule: '/api/appointments/doctor-schedule',
    },
    emr: {
      patient: '/api/emr/patient',
      myPrescriptions: '/api/emr/my-prescriptions',
      createPrescription: '/api/emr/prescription/create',
    },
    billing: {
      create: '/api/billing/create',
      list: '/api/billing/list',
      my: '/api/billing/my',
      receipt: '/api/billing/receipt',
      base: '/api/billing',
    },
    feedback: {
      submit: '/api/feedback',
      analytics: '/api/feedback/analytics',
    },
    chat: {
      history: '/api/chat/history',
      send: '/api/chat/send',
      ws: '/api/chat/ws',
      status: '/api/chat/status',
      sessionsSummary: '/api/chat/sessions/summary',
    },
  };

  const state = {
    user: JSON.parse(localStorage.getItem('user_profile') || 'null'),
    activeTab: 'patient',
    selectedRating: 5,
    selectedTags: [],
    myTicket: localStorage.getItem('my_ticket') || null,
    lastNotifiedTicket: null,
    currentServingTicketId: null,
    selectedEmrPatientId: null,
    // ponytail: fresh UUID per login; random session IDs prevent guest-session enumeration
    chatSessionId: localStorage.getItem('chat_session_id') || crypto.randomUUID(),
    guestChatRemaining: 5,
    chatWs: null,
    chatWsRetryMs: 1000,
    chatWsIntentionalClose: false,
    queueWs: null,
  };
  localStorage.setItem('chat_session_id', state.chatSessionId);

  // Clinic calendar date in UTC+8 (matches CLINIC_UTC_OFFSET on the backend)
  function clinicTodayISO() {
    return new Date(Date.now() + 8 * 3600000).toISOString().split('T')[0];
  }

  // Philippine currency formatter (en-PH -> ₱1,250.00)
  const phpFormatter = new Intl.NumberFormat('en-PH', {
    style: 'currency',
    currency: 'PHP',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  function formatPHP(amount) {
    const val = Number(amount);
    return phpFormatter.format(Number.isFinite(val) ? val : 0);
  }

  // Auto-format Philippine mobile (09XX XXX XXXX / +63 9XX XXX XXXX) and Metro Manila landline ((02) XXXX XXXX)
  function formatPHPhone(raw) {
    const trimmed = String(raw || '').trim();
    if (!trimmed) return '';
    const hasPlus = trimmed.startsWith('+');
    let digits = trimmed.replace(/\D/g, '');
    if (!digits) return '';

    if (digits.startsWith('63') || (hasPlus && digits.startsWith('63'))) {
      digits = digits.slice(0, 12);
      const rest = digits.slice(2);
      const parts = ['+63'];
      if (rest.length > 0) parts.push(rest.slice(0, 3));
      if (rest.length > 3) parts.push(rest.slice(3, 6));
      if (rest.length > 6) parts.push(rest.slice(6, 10));
      return parts.join(' ');
    }

    if (digits.startsWith('9') && digits.length >= 2) {
      digits = '0' + digits;
    }

    if (digits.startsWith('09')) {
      digits = digits.slice(0, 11);
      if (digits.length <= 4) return digits;
      if (digits.length <= 7) return `${digits.slice(0, 4)} ${digits.slice(4)}`;
      return `${digits.slice(0, 4)} ${digits.slice(4, 7)} ${digits.slice(7)}`;
    }

    if (digits.startsWith('02')) {
      digits = digits.slice(0, 10);
      if (digits.length <= 2) return digits;
      if (digits.length <= 6) return `(02) ${digits.slice(2)}`;
      return `(02) ${digits.slice(2, 6)} ${digits.slice(6)}`;
    }

    return trimmed;
  }

  document.addEventListener('input', (e) => {
    const el = e.target;
    if (el && el.matches && el.matches('input[type="tel"]')) {
      const formatted = formatPHPhone(el.value);
      if (formatted !== el.value) el.value = formatted;
    }
  });

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
    user: '<svg class="icon w-5 h-5 text-stone-400 mt-0.5 shrink-0" aria-hidden="true"><use href="#i-user"/></svg>',
    staff: '<svg class="icon w-5 h-5 text-stone-500 mt-0.5 shrink-0" aria-hidden="true"><use href="#i-clipboard"/></svg>',
  };

  // Helper: Toast Notifications
  function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const colors = {
      success: 'bg-brand-600 text-white',
      error: 'bg-red-600 text-white',
      warning: 'bg-amber-600 text-white',
      info: 'bg-stone-900 text-white',
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

  // Keep header auth controls and responsive nav chrome synchronized with activeTab & user state
  function syncChromeNav() {
    const nav = document.getElementById('portalNav');
    const mobNav = document.getElementById('mobileBottomNav');
    const headerLoginBtn = document.getElementById('headerLoginBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    const isLogin = state.activeTab === 'login';

    if (nav) {
      // Toggle sm:block alongside hidden because sm:block in CSS overrides .hidden at >=640px
      nav.classList.add('hidden');
      nav.classList.toggle('sm:block', !isLogin);
    }

    if (headerLoginBtn) {
      headerLoginBtn.classList.toggle('hidden', Boolean(state.user) || isLogin);
    }
    if (logoutBtn) {
      logoutBtn.classList.toggle('hidden', !state.user);
    }

    const visibleMobileTabs = ['patient', 'doctor', 'staff', 'analytics']
      .map(id => document.getElementById(`mob-tab-${id}`))
      .filter(el => el && !el.classList.contains('hidden'));
    const shouldShowMobNav = !isLogin && visibleMobileTabs.length > 1;
    if (mobNav) {
      mobNav.classList.toggle('hidden', !shouldShowMobNav);
    }

    const chatWrap = document.getElementById('chatLauncherWrap');
    if (chatWrap) {
      chatWrap.classList.toggle('bottom-20', shouldShowMobNav);
      chatWrap.classList.toggle('bottom-4', !shouldShowMobNav);
    }
  }

  // Tab Navigation (WAI-ARIA tabs with strict Role-Based Access Control)
  function switchTab(tabName) {
    if (state.user) {
      const allowedRoles = {
        patient: ['patient'],
        doctor: ['doctor'],
        staff: ['staff', 'admin'],
        analytics: ['admin'],
      };
      if (allowedRoles[tabName] && !allowedRoles[tabName].includes(state.user.role)) {
        showToast('Access restricted: your account does not have permission for this portal.', 'warning');
        return;
      }
    } else if (tabName === 'login') {
      state.activeTab = 'login';
      document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.setAttribute('aria-selected', 'false');
      });
      document.querySelectorAll('.tab-content').forEach(sec => {
        sec.classList.add('hidden');
      });
      const activeSec = document.getElementById('portal-login');
      if (activeSec) activeSec.classList.remove('hidden');
      syncChromeNav();
      return;
    } else if (tabName !== 'patient') {
      const roleTarget = tabName === 'analytics' ? 'admin' : tabName;
      showToast('Please sign in with authorized clinic credentials.', 'info');
      openLoginGateway('login', roleTarget);
      return;
    }

    state.activeTab = tabName;
    syncChromeNav();

    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.setAttribute('aria-selected', String(btn.id === `tab-${tabName}`));
    });

    document.querySelectorAll('.mob-nav-btn').forEach(btn => {
      const isSelected = btn.id === `mob-tab-${tabName}`;
      btn.setAttribute('aria-selected', String(isSelected));
      if (isSelected) {
        btn.classList.remove('text-stone-500');
        btn.classList.add('text-brand-600', 'font-bold');
      } else {
        btn.classList.remove('text-brand-600', 'font-bold');
        btn.classList.add('text-stone-500');
      }
    });

    document.querySelectorAll('.tab-content').forEach(sec => {
      sec.classList.add('hidden');
    });
    const activeSec = document.getElementById(`portal-${tabName}`);
    if (activeSec) activeSec.classList.remove('hidden');

    if (tabName === 'doctor') {
      loadPatientDirectory();
      loadDoctorPendingApprovals();
      loadDoctorSchedule();
      loadActiveQueue();
      if (state.selectedEmrPatientId) {
        searchPatientEMR(state.selectedEmrPatientId);
      } else {
        resetDoctorEMRView();
      }
    } else if (tabName === 'staff') {
      loadDoctors();
      loadPatientDirectory();
      fetchQueueStatus();
      loadStaffAppointments();
      loadBillingHistory();
      loadStaffChatInbox();
    } else if (tabName === 'analytics') {
      loadAnalytics();
      loadAdminUsers();
    } else if (tabName === 'patient') {
      loadDoctors();
      fetchQueueStatus();
      if (state.user && state.user.role === 'patient') {
        renderPatientProfile(state.user);
        loadMyAppointments();
        loadMyPrescriptions();
        loadMyInvoices();
      } else {
        renderGuestPatientProfile();
      }
    }
  }

  // Real Authentication & Session Management
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
      showToast(`Welcome, ${state.user.full_name || state.user.email}!`, 'success');

      // Auto-switch to authorized portal
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

  async function logout() {
    try {
      await apiFetch(API.auth.logout, { method: 'POST' }).catch(() => {});
    } finally {
      state.user = null;
      localStorage.removeItem('user_profile');
      localStorage.removeItem('my_ticket');
      state.myTicket = null;
      state.lastNotifiedTicket = null;
      state.selectedEmrPatientId = null;
      resetDoctorEMRView();
      if (state.chatWs) {
        state.chatWsIntentionalClose = true;
        try { state.chatWs.close(); } catch (_) {}
        state.chatWs = null;
      }
      state.chatSessionId = crypto.randomUUID();
      localStorage.setItem('chat_session_id', state.chatSessionId);
      updateUserUI();
      showToast('Logged out successfully', 'info');
      switchTab('login');
    }
  }

  function updateUserUI() {
    const badge = document.getElementById('userProfileBadge');
    const nameEl = document.getElementById('currentUserName');
    const roleEl = document.getElementById('currentUserRole');

    // Role-based portal tab visibility (Desktop & Mobile)
    const tabPatient = document.getElementById('tab-patient');
    const tabDoctor = document.getElementById('tab-doctor');
    const tabStaff = document.getElementById('tab-staff');
    const tabAnalytics = document.getElementById('tab-analytics');

    const mobTabPatient = document.getElementById('mob-tab-patient');
    const mobTabDoctor = document.getElementById('mob-tab-doctor');
    const mobTabStaff = document.getElementById('mob-tab-staff');
    const mobTabAnalytics = document.getElementById('mob-tab-analytics');

    if (state.user) {
      if (badge) {
        badge.className = 'hidden sm:flex items-center gap-2 bg-stone-100 py-1.5 px-3 rounded-full text-xs font-medium text-stone-700';
      }
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
          (roleColors[state.user.role] || 'bg-stone-200 text-stone-800');
      }

      // STRICT ROLE-BASED ACCESS CONTROL FOR TABS
      const showTab = (desktopEl, mobileEl, visible) => {
        if (desktopEl) desktopEl.classList.toggle('hidden', !visible);
        if (mobileEl) mobileEl.classList.toggle('hidden', !visible);
      };

      if (state.user.role === 'patient') {
        showTab(tabPatient, mobTabPatient, true);
        showTab(tabDoctor, mobTabDoctor, false);
        showTab(tabStaff, mobTabStaff, false);
        showTab(tabAnalytics, mobTabAnalytics, false);
        renderPatientProfile(state.user);
      } else if (state.user.role === 'doctor') {
        showTab(tabPatient, mobTabPatient, false);
        showTab(tabDoctor, mobTabDoctor, true);
        showTab(tabStaff, mobTabStaff, false);
        showTab(tabAnalytics, mobTabAnalytics, false);
        const bannerName = document.getElementById('doctorBannerName');
        if (bannerName) bannerName.textContent = state.user.full_name || 'Doctor';
        const prof = state.user.doctor_profile;
        if (prof) {
          const bannerRoom = document.getElementById('doctorBannerRoom');
          if (bannerRoom) bannerRoom.textContent = `${prof.room_number || 'Room N/A'}`;
          const bannerSpec = document.getElementById('doctorBannerSpec');
          if (bannerSpec) bannerSpec.textContent = `${prof.specialization || 'General Medicine'} \u2022 Clinical EMR`;
          const availBtn = document.getElementById('doctorAvailabilityBtn');
          const availLabel = document.getElementById('doctorAvailabilityLabel');
          const isAvail = prof.is_available !== false;
          if (availLabel) availLabel.textContent = isAvail ? 'Accepting Patients' : 'Paused / Unavailable';
          if (availBtn) {
            availBtn.classList.toggle('border-brand-300', isAvail);
            availBtn.classList.toggle('text-brand-800', isAvail);
            availBtn.classList.toggle('bg-brand-50', isAvail);
            availBtn.classList.toggle('border-amber-300', !isAvail);
            availBtn.classList.toggle('text-amber-800', !isAvail);
            availBtn.classList.toggle('bg-amber-50', !isAvail);
          }
        }
      } else if (state.user.role === 'staff') {
        showTab(tabPatient, mobTabPatient, false);
        showTab(tabDoctor, mobTabDoctor, false);
        showTab(tabStaff, mobTabStaff, true);
        showTab(tabAnalytics, mobTabAnalytics, false);
      } else if (state.user.role === 'admin') {
        showTab(tabPatient, mobTabPatient, false);
        showTab(tabDoctor, mobTabDoctor, false);
        showTab(tabStaff, mobTabStaff, true);
        showTab(tabAnalytics, mobTabAnalytics, true);
      }
    } else {
      if (badge) badge.className = 'hidden';

      // Guest / unauthenticated: show Patient view, hide clinical staff tabs
      if (tabPatient) tabPatient.classList.remove('hidden');
      if (mobTabPatient) mobTabPatient.classList.remove('hidden');
      if (tabDoctor) tabDoctor.classList.add('hidden');
      if (mobTabDoctor) mobTabDoctor.classList.add('hidden');
      if (tabStaff) tabStaff.classList.add('hidden');
      if (mobTabStaff) mobTabStaff.classList.add('hidden');
      if (tabAnalytics) tabAnalytics.classList.add('hidden');
      if (mobTabAnalytics) mobTabAnalytics.classList.add('hidden');
      renderGuestPatientProfile();
    }
    syncChromeNav();
    updateChatGuestUI(state.user ? null : state.guestChatRemaining);
  }

  function renderGuestPatientProfile() {
    const nameEl = document.getElementById('patientCardName');
    const subEl = document.getElementById('patientCardSub');
    const initialsEl = document.getElementById('patientCardInitials');
    const dobEl = document.getElementById('patientCardDob');
    const bloodEl = document.getElementById('patientCardBlood');
    const allergiesEl = document.getElementById('patientCardAllergies');
    const historyEl = document.getElementById('patientCardHistory');
    const emergencyEl = document.getElementById('patientCardEmergency');
    const editBtn = document.getElementById('editProfileBtn');

    if (nameEl) nameEl.textContent = 'Guest Patient';
    if (subEl) subEl.textContent = 'Sign in or register to access medical profile';
    if (initialsEl) initialsEl.textContent = 'GP';
    if (dobEl) dobEl.textContent = 'Sign in to view';
    if (bloodEl) bloodEl.textContent = 'Sign in to view';
    if (allergiesEl) {
      allergiesEl.textContent = 'Sign in to view';
      allergiesEl.className = 'font-semibold text-stone-500 block text-xs sm:text-sm mt-0.5 truncate';
    }
    if (historyEl) historyEl.textContent = 'Sign in to view';
    if (emergencyEl) emergencyEl.textContent = 'Sign in to view';
    if (editBtn) editBtn.classList.add('hidden');
    const guestAuthBtn = document.getElementById('patientGuestAuthBtn');
    if (guestAuthBtn) guestAuthBtn.classList.remove('hidden');
    const apptList = document.getElementById('patientAppointmentsList');
    if (apptList) apptList.innerHTML = '<p class="text-stone-600 py-3 text-center">Sign in to view your appointments.</p>';
    const rxList = document.getElementById('patientPrescriptionsList');
    if (rxList) rxList.innerHTML = '<p class="text-stone-600 py-3 text-center">Sign in to view your prescriptions.</p>';
    const invList = document.getElementById('patientInvoicesList');
    if (invList) invList.innerHTML = '<p class="text-stone-600 py-3 text-center">Sign in to view your receipts.</p>';
    syncMyTicketCard(null);
  }

  function renderPatientProfile(user) {
    if (!user) {
      renderGuestPatientProfile();
      return;
    }
    const nameEl = document.getElementById('patientCardName');
    const subEl = document.getElementById('patientCardSub');
    const initialsEl = document.getElementById('patientCardInitials');
    const dobEl = document.getElementById('patientCardDob');
    const bloodEl = document.getElementById('patientCardBlood');
    const allergiesEl = document.getElementById('patientCardAllergies');
    const historyEl = document.getElementById('patientCardHistory');
    const emergencyEl = document.getElementById('patientCardEmergency');
    const editBtn = document.getElementById('editProfileBtn');

    if (nameEl) nameEl.textContent = user.full_name || user.email;
    if (subEl) {
      const pId = user.patient_id ? `#${user.patient_id}` : 'Registered';
      const gender = user.patient_profile?.gender || 'Unspecified';
      subEl.textContent = `Patient ID: ${pId} • ${gender}`;
    }
    if (initialsEl && user.full_name) {
      const parts = user.full_name.trim().split(/\s+/);
      initialsEl.textContent = parts.length > 1
        ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
        : parts[0].slice(0, 2).toUpperCase();
    }

    const prof = user.patient_profile || {};
    if (dobEl) dobEl.textContent = prof.date_of_birth || 'Not recorded';
    if (bloodEl) bloodEl.textContent = prof.blood_group || 'Unknown';
    if (allergiesEl) {
      const allergyVal = prof.allergies || 'None known';
      allergiesEl.textContent = allergyVal;
      if (prof.allergies && prof.allergies.toLowerCase() !== 'none' && prof.allergies.toLowerCase() !== 'none known') {
        allergiesEl.className = 'font-bold text-rose-600 block text-xs sm:text-sm mt-0.5 truncate';
      } else {
        allergiesEl.className = 'font-semibold text-stone-700 block text-xs sm:text-sm mt-0.5 truncate';
      }
    }
    if (historyEl) historyEl.textContent = prof.medical_history || 'None recorded';
    if (emergencyEl) {
      const name = prof.emergency_contact_name || '';
      const phone = formatPHPhone(prof.emergency_contact_phone || '');
      emergencyEl.textContent = (name || phone) ? `${name} (${phone})`.trim() : 'None recorded';
    }
    if (editBtn) editBtn.classList.remove('hidden');
    const guestAuthBtn = document.getElementById('patientGuestAuthBtn');
    if (guestAuthBtn) guestAuthBtn.classList.add('hidden');
  }

  // Dedicated Role-based Login & Sign Up Portal Logic
  let currentLoginRole = 'patient';
  let currentPortalMode = 'login'; // 'login' | 'register'

  const roleMeta = {
    patient: {
      title: 'Patient Portal',
      btnText: 'Sign In as Patient',
      regBtnText: 'Create Patient Account',
      icon: '#i-user',
      emailPlaceholder: 'patient@clinic.com',
    },
    doctor: {
      title: 'Doctor Clinical Console',
      btnText: 'Sign In as Doctor',
      regBtnText: 'Register Doctor Account',
      icon: '#i-stethoscope',
      emailPlaceholder: 'doctor@clinic.com',
    },
    staff: {
      title: 'Staff & Billing Desk',
      btnText: 'Sign In as Staff',
      regBtnText: 'Request Staff Account',
      icon: '#i-clipboard',
      emailPlaceholder: 'staff@clinic.com',
    },
    admin: {
      title: 'Administrator Console',
      btnText: 'Sign In as Administrator',
      regBtnText: 'Request Admin Account',
      icon: '#i-chart',
      emailPlaceholder: 'admin@clinic.com',
    },
  };

  function updatePortalHeader() {
    const meta = roleMeta[currentLoginRole] || roleMeta.patient;
    const titleEl = document.getElementById('loginRoleTitle');
    const roleIcon = document.getElementById('loginRoleIcon');

    if (roleIcon) roleIcon.innerHTML = `<use href="${meta.icon}"/>`;

    if (currentPortalMode === 'register') {
      if (titleEl) titleEl.textContent = `${meta.title} Sign Up`;
    } else {
      if (titleEl) titleEl.textContent = `${meta.title} Sign In`;
    }
  }

  function switchPortalMode(mode) {
    currentPortalMode = mode === 'register' ? 'register' : 'login';

    const signInBtn = document.getElementById('portalModeSignInBtn');
    const regBtn = document.getElementById('portalModeRegisterBtn');
    const loginForm = document.getElementById('portalLoginForm');
    const regForm = document.getElementById('portalRegisterForm');
    const errEl = document.getElementById('portalLoginErrorMsg');
    const infoEl = document.getElementById('portalLoginInfoMsg');
    if (errEl) errEl.classList.add('hidden');
    if (infoEl) infoEl.classList.add('hidden');

    const activeCls = 'flex-1 min-h-[44px] py-2 rounded-lg bg-white text-stone-900 shadow-sm font-bold transition-all';
    const inactiveCls = 'flex-1 min-h-[44px] py-2 rounded-lg text-stone-600 hover:text-stone-900 transition-all font-semibold';

    if (currentPortalMode === 'register') {
      if (signInBtn) {
        signInBtn.className = inactiveCls;
        signInBtn.setAttribute('aria-selected', 'false');
      }
      if (regBtn) {
        regBtn.className = activeCls;
        regBtn.setAttribute('aria-selected', 'true');
      }
      if (loginForm) loginForm.classList.add('hidden');
      if (regForm) regForm.classList.remove('hidden');
    } else {
      if (signInBtn) {
        signInBtn.className = activeCls;
        signInBtn.setAttribute('aria-selected', 'true');
      }
      if (regBtn) {
        regBtn.className = inactiveCls;
        regBtn.setAttribute('aria-selected', 'false');
      }
      if (loginForm) loginForm.classList.remove('hidden');
      if (regForm) regForm.classList.add('hidden');
    }

    updatePortalHeader();
  }

  // Registration Interactive State & Micro-Component Helpers
  const selectedRegAllergyChips = new Set();
  const selectedRegHistoryChips = new Set();

  function selectRegGender(val) {
    const input = document.getElementById('portalRegGender');
    if (input) input.value = val;
    document.querySelectorAll('#regGenderPills .segmented-pill').forEach(btn => {
      btn.setAttribute('aria-selected', btn.getAttribute('data-gender') === val ? 'true' : 'false');
    });
  }

  function selectRegBlood(val) {
    const input = document.getElementById('portalRegBloodGroup');
    if (input) input.value = val;
    const label = document.getElementById('regSelectedBloodLabel');
    if (label) label.textContent = val ? `Type ${val}` : '';
    document.querySelectorAll('#regBloodGroupPills .blood-tile').forEach(btn => {
      btn.setAttribute('aria-selected', btn.getAttribute('data-blood') === val ? 'true' : 'false');
    });
  }

  function updateRegAllergyChipsUI() {
    document.querySelectorAll('#regAllergyPresetChips .tag-chip').forEach(btn => {
      const chip = btn.getAttribute('data-chip');
      btn.setAttribute('aria-pressed', selectedRegAllergyChips.has(chip) ? 'true' : 'false');
    });
  }

  function toggleRegAllergyChip(chip) {
    if (chip === 'None') {
      if (selectedRegAllergyChips.has('None')) {
        selectedRegAllergyChips.delete('None');
      } else {
        selectedRegAllergyChips.clear();
        selectedRegAllergyChips.add('None');
        const customEl = document.getElementById('portalRegCustomAllergies');
        if (customEl) customEl.value = '';
      }
    } else {
      selectedRegAllergyChips.delete('None');
      if (selectedRegAllergyChips.has(chip)) {
        selectedRegAllergyChips.delete(chip);
      } else {
        selectedRegAllergyChips.add(chip);
      }
    }
    updateRegAllergyChipsUI();
  }

  function updateRegHistoryChipsUI() {
    document.querySelectorAll('#regHistoryPresetChips .tag-chip').forEach(btn => {
      const chip = btn.getAttribute('data-chip');
      btn.setAttribute('aria-pressed', selectedRegHistoryChips.has(chip) ? 'true' : 'false');
    });
  }

  function toggleRegHistoryChip(chip) {
    if (chip === 'None') {
      if (selectedRegHistoryChips.has('None')) {
        selectedRegHistoryChips.delete('None');
      } else {
        selectedRegHistoryChips.clear();
        selectedRegHistoryChips.add('None');
        const customEl = document.getElementById('portalRegCustomHistory');
        if (customEl) customEl.value = '';
      }
    } else {
      selectedRegHistoryChips.delete('None');
      if (selectedRegHistoryChips.has(chip)) {
        selectedRegHistoryChips.delete(chip);
      } else {
        selectedRegHistoryChips.add(chip);
      }
    }
    updateRegHistoryChipsUI();
  }

  function selectRegSpecialization(val) {
    const input = document.getElementById('portalRegSpecialization');
    if (input) input.value = val;
    document.querySelectorAll('#regDoctorSpecChips .spec-pill').forEach(btn => {
      btn.setAttribute('aria-selected', btn.getAttribute('data-spec') === val ? 'true' : 'false');
    });
  }

  function selectRegFee(val) {
    const input = document.getElementById('portalRegFee');
    if (input) input.value = val;
    document.querySelectorAll('#regDoctorFeeChips .spec-pill').forEach(btn => {
      btn.setAttribute('aria-selected', btn.getAttribute('data-fee') === val ? 'true' : 'false');
    });
  }

  function openLoginGateway(mode, role) {
    if (role) switchLoginRole(role);
    switchPortalMode(mode || 'login');
    switchTab('login');
    const loginCard = document.getElementById('loginGatewayCard');
    if (loginCard) {
      loginCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function switchLoginRole(role) {
    if (!roleMeta[role]) role = 'patient';
    currentLoginRole = role;

    ['patient', 'doctor', 'staff', 'admin'].forEach(r => {
      const pill = document.getElementById(`pill-${r}`);
      if (pill) {
        pill.setAttribute('aria-selected', r === role ? 'true' : 'false');
      }
    });

    const meta = roleMeta[role];
    const btnTextEl = document.getElementById('portalLoginBtnText');
    const regBtnTextEl = document.getElementById('portalRegBtnText');
    const emailInput = document.getElementById('portalLoginEmail');
    const nameInput = document.getElementById('portalRegFullName');
    const roleBadge = document.getElementById('regRoleBadge');

    if (btnTextEl) btnTextEl.textContent = meta.btnText;
    if (regBtnTextEl) regBtnTextEl.textContent = meta.regBtnText;
    if (emailInput) emailInput.placeholder = meta.emailPlaceholder;

    if (nameInput) {
      const placeholders = {
        patient: 'e.g. Eleanor Vance',
        doctor: 'e.g. Dr. Emily Stone, MD',
        staff: 'e.g. James Wilson, RN',
        admin: 'e.g. Arthur Mitchell, Director',
      };
      nameInput.placeholder = placeholders[role] || 'e.g. Eleanor Vance';
    }

    if (roleBadge) {
      roleBadge.textContent = role.toUpperCase();
      const roleColors = {
        patient: 'bg-emerald-100 text-emerald-800',
        doctor: 'bg-violet-100 text-violet-800',
        staff: 'bg-amber-100 text-amber-800',
        admin: 'bg-rose-100 text-rose-800',
      };
      roleBadge.className = `text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${roleColors[role] || 'bg-brand-100 text-brand-800'}`;
    }

    // Toggle role-specific registration fields
    const patFields = document.getElementById('portalRegPatientFields');
    const docFields = document.getElementById('portalRegDoctorFields');
    const stfFields = document.getElementById('portalRegStaffFields');
    const admFields = document.getElementById('portalRegAdminFields');

    if (patFields) patFields.classList.toggle('hidden', role !== 'patient');
    if (docFields) docFields.classList.toggle('hidden', role !== 'doctor');
    if (stfFields) stfFields.classList.toggle('hidden', role !== 'staff');
    if (admFields) admFields.classList.toggle('hidden', role !== 'admin');

    updatePortalHeader();

    const errEl = document.getElementById('portalLoginErrorMsg');
    if (errEl) errEl.classList.add('hidden');
  }

  async function handlePortalLogin(e) {
    e.preventDefault();
    const errEl = document.getElementById('portalLoginErrorMsg');
    if (errEl) errEl.classList.add('hidden');
    const submitBtn = document.getElementById('portalLoginSubmitBtn');
    if (submitBtn) submitBtn.disabled = true;

    const email = document.getElementById('portalLoginEmail').value.trim();
    const password = document.getElementById('portalLoginPassword').value;
    try {
      await login(email, password);
    } catch (err) {
      if (errEl) {
        errEl.textContent = err.message || 'Incorrect email or password.';
        errEl.classList.remove('hidden');
      }
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  function resetRegisterFormState() {
    document.getElementById('portalRegisterForm')?.reset();
    selectedRegAllergyChips.clear();
    selectedRegHistoryChips.clear();
    updateRegAllergyChipsUI();
    updateRegHistoryChipsUI();
    selectRegGender('');
    selectRegBlood('');
  }

  async function handlePortalRegister(e) {
    e.preventDefault();
    const errEl = document.getElementById('portalLoginErrorMsg');
    const infoEl = document.getElementById('portalLoginInfoMsg');
    if (errEl) errEl.classList.add('hidden');
    if (infoEl) infoEl.classList.add('hidden');
    const submitBtn = document.getElementById('portalRegSubmitBtn');
    if (submitBtn) submitBtn.disabled = true;

    const payload = {
      full_name: document.getElementById('portalRegFullName').value.trim(),
      email: document.getElementById('portalRegEmail').value.trim(),
      password: document.getElementById('portalRegPassword').value,
      phone: document.getElementById('portalRegPhone').value.trim(),
      role: currentLoginRole,
    };

    if (currentLoginRole === 'patient') {
      const customAllergies = (document.getElementById('portalRegCustomAllergies')?.value || '')
        .split(',').map(s => s.trim()).filter(Boolean);
      const combinedAllergies = Array.from(new Set([...selectedRegAllergyChips, ...customAllergies]));
      payload.allergies = combinedAllergies.length > 0 ? combinedAllergies.join(', ') : null;

      const customHistory = (document.getElementById('portalRegCustomHistory')?.value || '')
        .split(',').map(s => s.trim()).filter(Boolean);
      const combinedHistory = Array.from(new Set([...selectedRegHistoryChips, ...customHistory]));
      payload.medical_history = combinedHistory.length > 0 ? combinedHistory.join(', ') : null;

      payload.date_of_birth = document.getElementById('portalRegDob')?.value || null;
      payload.gender = document.getElementById('portalRegGender')?.value || null;
      payload.blood_group = document.getElementById('portalRegBloodGroup')?.value || null;
      payload.emergency_contact_name = document.getElementById('portalRegEmergencyName')?.value.trim() || null;
      payload.emergency_contact_phone = document.getElementById('portalRegEmergencyPhone')?.value.trim() || null;
    } else if (currentLoginRole === 'doctor') {
      payload.specialization = document.getElementById('portalRegSpecialization')?.value.trim() || 'General Medicine';
      payload.license_number = document.getElementById('portalRegLicense')?.value.trim() || 'MD-REG';
      payload.room_number = document.getElementById('portalRegRoom')?.value.trim() || 'Room 101';
      payload.consultation_fee = parseFloat(document.getElementById('portalRegFee')?.value) || 500.00;
    }

    try {
      const data = await apiFetch(API.auth.register, {
        method: 'POST',
        body: payload,
      });

      if (data.pending_approval) {
        resetRegisterFormState();
        switchPortalMode('login');
        const msg = data.message || 'Account request submitted. An administrator must approve it before you can sign in.';
        if (infoEl) {
          infoEl.textContent = msg;
          infoEl.classList.remove('hidden');
        }
        showToast(msg, 'info');
        return;
      }

      resetRegisterFormState();
      state.user = data.user;
      localStorage.setItem('user_profile', JSON.stringify(state.user));
      state.chatSessionId = crypto.randomUUID();
      localStorage.setItem('chat_session_id', state.chatSessionId);

      updateUserUI();
      showToast(`Welcome, ${state.user.full_name}! Your ${state.user.role} account is ready.`, 'success');

      const roleMap = { patient: 'patient', doctor: 'doctor', staff: 'staff', admin: 'analytics' };
      switchTab(roleMap[state.user.role] || 'patient');
    } catch (err) {
      if (errEl) {
        errEl.textContent = err.message || 'Registration failed. Please check your details.';
        errEl.classList.remove('hidden');
      } else {
        showToast(err.message, 'error');
      }
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  function showcaseSelectRole(role, mode) {
    switchLoginRole(role);
    switchPortalMode(mode || 'login');
    const loginCard = document.getElementById('loginGatewayCard');
    if (loginCard) {
      loginCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    if (mode === 'register') {
      const nameInput = document.getElementById('portalRegFullName');
      if (nameInput) {
        setTimeout(() => nameInput.focus(), 350);
      }
    } else {
      const emailInput = document.getElementById('portalLoginEmail');
      if (emailInput) {
        setTimeout(() => emailInput.focus(), 350);
      }
    }
  }

  function showcaseOpenChat() {
    const chatWin = document.getElementById('chatWindow');
    if (chatWin && chatWin.classList.contains('hidden')) {
      toggleChat();
    }
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
      setTimeout(() => chatInput.focus(), 250);
    }
  }

  async function handleSetupAdmin(e) {
    e.preventDefault();
    const errEl = document.getElementById('setupAdminErrorMsg');
    if (errEl) errEl.classList.add('hidden');
    const submitBtn = document.getElementById('setupAdminSubmitBtn');
    if (submitBtn) submitBtn.disabled = true;

    const payload = {
      full_name: document.getElementById('setupAdminFullName').value.trim(),
      email: document.getElementById('setupAdminEmail').value.trim(),
      password: document.getElementById('setupAdminPassword').value,
      phone: document.getElementById('setupAdminPhone')?.value.trim() || null,
    };

    try {
      const data = await apiFetch(API.auth.setupAdmin, {
        method: 'POST',
        body: payload,
      });
      state.user = data.user;
      localStorage.setItem('user_profile', JSON.stringify(state.user));
      state.chatSessionId = crypto.randomUUID();
      localStorage.setItem('chat_session_id', state.chatSessionId);

      const modal = document.getElementById('setupAdminModal');
      if (modal) modal.classList.add('hidden');
      const form = document.getElementById('setupAdminForm');
      if (form) form.reset();

      updateUserUI();
      showToast(`System initialized! Welcome, ${state.user.full_name || state.user.email}.`, 'success');
      switchTab('analytics');
    } catch (err) {
      if (errEl) {
        errEl.textContent = err.message || 'Administrator setup failed.';
        errEl.classList.remove('hidden');
      } else {
        showToast(err.message, 'error');
      }
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  // One-tap seeded logins for demo deployments (row is revealed by init()
  // only when /api/auth/setup-status reports demo_mode).
  async function demoLogin(role) {
    const creds = {
      patient: ['patient@demo.com', 'patient123'],
      doctor: ['doctor@demo.com', 'doctor123'],
      staff: ['staff@demo.com', 'staff123'],
      admin: ['admin@demo.com', 'admin123'],
    };
    const [email, password] = creds[role] || creds.patient;
    try {
      await login(email, password);
    } catch (_) {
      // login() already surfaced the error toast
    }
  }

  function showProfileModal() {
    if (!state.user) {
      openLoginGateway('login', 'patient');
      return;
    }
    const modal = document.getElementById('profileModal');
    if (!modal) return;
    const prof = state.user.patient_profile || {};
    const fnEl = document.getElementById('editFullName');
    const phEl = document.getElementById('editPhone');
    const dobEl = document.getElementById('editDob');
    const emNameEl = document.getElementById('editEmergencyName');
    const emPhEl = document.getElementById('editEmergencyPhone');

    if (fnEl) fnEl.value = state.user.full_name || '';
    if (phEl) phEl.value = formatPHPhone(state.user.phone || '');
    if (dobEl) {
      dobEl.value = prof.date_of_birth || '';
      dobEl.max = clinicTodayISO();
    }
    if (emNameEl) emNameEl.value = prof.emergency_contact_name || '';
    if (emPhEl) emPhEl.value = formatPHPhone(prof.emergency_contact_phone || '');

    // Select Gender & Blood Group pills
    selectProfileGender(prof.gender || '');
    selectProfileBlood(prof.blood_group || '');

    // Populate and sync preset chips for Allergies
    selectedAllergyChips.clear();
    const presetAllergies = ['Penicillin', 'Sulfa', 'Aspirin', 'Peanuts', 'Latex', 'None'];
    const rawAllergies = (prof.allergies || '').split(',').map(s => s.trim()).filter(Boolean);
    const customAllergies = [];
    rawAllergies.forEach(item => {
      const match = presetAllergies.find(p => p.toLowerCase() === item.toLowerCase());
      if (match) {
        selectedAllergyChips.add(match);
      } else {
        customAllergies.push(item);
      }
    });
    const customAllergiesEl = document.getElementById('editCustomAllergies');
    if (customAllergiesEl) customAllergiesEl.value = customAllergies.join(', ');
    updateAllergyChipsUI();

    // Populate and sync preset chips for Medical History
    selectedHistoryChips.clear();
    const presetHistory = ['Hypertension', 'Diabetes', 'Asthma', 'Heart Disease', 'None'];
    const rawHistory = (prof.medical_history || '').split(',').map(s => s.trim()).filter(Boolean);
    const customHistory = [];
    rawHistory.forEach(item => {
      const match = presetHistory.find(p => p.toLowerCase() === item.toLowerCase());
      if (match) {
        selectedHistoryChips.add(match);
      } else {
        customHistory.push(item);
      }
    });
    const customHistEl = document.getElementById('editCustomHistory');
    if (customHistEl) customHistEl.value = customHistory.join(', ');
    updateHistoryChipsUI();

    modal.classList.remove('hidden');
  }

  function hideProfileModal() {
    const modal = document.getElementById('profileModal');
    if (modal) modal.classList.add('hidden');
  }

  // Interactive pill selection state
  function selectProfileGender(val) {
    const input = document.getElementById('editGender');
    if (input) input.value = val;
    document.querySelectorAll('#editGenderPills .segmented-pill').forEach(btn => {
      btn.setAttribute('aria-selected', btn.getAttribute('data-gender') === val ? 'true' : 'false');
    });
  }

  function selectProfileBlood(val) {
    const input = document.getElementById('editBloodGroup');
    if (input) input.value = val;
    const label = document.getElementById('selectedBloodLabel');
    if (label) label.textContent = val ? `Type ${val}` : '';
    document.querySelectorAll('#editBloodGroupPills .blood-tile').forEach(btn => {
      btn.setAttribute('aria-selected', btn.getAttribute('data-blood') === val ? 'true' : 'false');
    });
  }

  // Preset Chips State
  const selectedAllergyChips = new Set();
  const selectedHistoryChips = new Set();

  function updateAllergyChipsUI() {
    document.querySelectorAll('#allergyPresetChips .tag-chip').forEach(btn => {
      const chip = btn.getAttribute('data-chip');
      btn.setAttribute('aria-pressed', selectedAllergyChips.has(chip) ? 'true' : 'false');
    });
  }

  function toggleProfileAllergyChip(chip) {
    if (chip === 'None') {
      if (selectedAllergyChips.has('None')) {
        selectedAllergyChips.delete('None');
      } else {
        selectedAllergyChips.clear();
        selectedAllergyChips.add('None');
        const customEl = document.getElementById('editCustomAllergies');
        if (customEl) customEl.value = '';
      }
    } else {
      selectedAllergyChips.delete('None');
      if (selectedAllergyChips.has(chip)) {
        selectedAllergyChips.delete(chip);
      } else {
        selectedAllergyChips.add(chip);
      }
    }
    updateAllergyChipsUI();
  }

  function updateHistoryChipsUI() {
    document.querySelectorAll('#historyPresetChips .tag-chip').forEach(btn => {
      const chip = btn.getAttribute('data-chip');
      btn.setAttribute('aria-pressed', selectedHistoryChips.has(chip) ? 'true' : 'false');
    });
  }

  function toggleProfileHistoryChip(chip) {
    if (chip === 'None') {
      if (selectedHistoryChips.has('None')) {
        selectedHistoryChips.delete('None');
      } else {
        selectedHistoryChips.clear();
        selectedHistoryChips.add('None');
        const customEl = document.getElementById('editCustomHistory');
        if (customEl) customEl.value = '';
      }
    } else {
      selectedHistoryChips.delete('None');
      if (selectedHistoryChips.has(chip)) {
        selectedHistoryChips.delete(chip);
      } else {
        selectedHistoryChips.add(chip);
      }
    }
    updateHistoryChipsUI();
  }

  async function handleProfileUpdate(e) {
    e.preventDefault();

    // Compile allergies
    const customAllergies = (document.getElementById('editCustomAllergies')?.value || '')
      .split(',').map(s => s.trim()).filter(Boolean);
    const combinedAllergies = Array.from(new Set([...selectedAllergyChips, ...customAllergies]));
    const finalAllergies = combinedAllergies.length > 0 ? combinedAllergies.join(', ') : null;

    // Compile medical history
    const customHistory = (document.getElementById('editCustomHistory')?.value || '')
      .split(',').map(s => s.trim()).filter(Boolean);
    const combinedHistory = Array.from(new Set([...selectedHistoryChips, ...customHistory]));
    const finalHistory = combinedHistory.length > 0 ? combinedHistory.join(', ') : null;

    const payload = {
      full_name: document.getElementById('editFullName').value.trim(),
      phone: document.getElementById('editPhone').value.trim() || null,
      date_of_birth: document.getElementById('editDob').value || null,
      gender: document.getElementById('editGender').value || null,
      blood_group: document.getElementById('editBloodGroup').value || null,
      allergies: finalAllergies,
      medical_history: finalHistory,
      emergency_contact_name: document.getElementById('editEmergencyName').value.trim() || null,
      emergency_contact_phone: document.getElementById('editEmergencyPhone').value.trim() || null,
    };

    const submitBtn = document.getElementById('saveProfileSubmitBtn');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.classList.add('opacity-70');
    }

    try {
      const updated = await apiFetch(API.auth.profile, {
        method: 'PUT',
        body: payload,
      });
      state.user = updated;
      localStorage.setItem('user_profile', JSON.stringify(state.user));
      hideProfileModal();
      renderPatientProfile(state.user);
      updateUserUI();
      showToast('Medical profile updated successfully', 'success');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.classList.remove('opacity-70');
      }
    }
  }
  // Queue Live Updates & Tracker
  async function fetchQueueStatus() {
    try {
      const data = await apiFetch(API.queue.liveStatus);
      renderQueueData(data);
    } catch (err) {
      console.warn('Failed to load queue status:', err);
    }
    if (state.user && state.user.role === 'patient') {
      loadMyActiveTicket();
    } else if (state.user && ['staff', 'doctor', 'admin'].includes(state.user.role)) {
      loadActiveQueue();
    }
  }

  function renderQueueData(data) {
    const serving = data.currently_serving || 'None';
    const hasServing = serving !== 'None';
    // Room label is meaningless when nobody is serving; show nothing instead of a bare "N/A".
    const room = hasServing ? (data.currently_serving_room || '') : '';
    const waiting = data.waiting_tickets || [];
    const count = data.waiting_count !== undefined ? data.waiting_count : waiting.length;
    const est = data.estimated_wait_minutes || (count * 10);

    // Patient Portal
    const patServing = document.getElementById('patientServingTicket');
    const patRoom = document.getElementById('patientServingRoom');
    const patCount = document.getElementById('patientWaitingCount');
    const patLabel = document.getElementById('patientWaitingLabel');
    const patEst = document.getElementById('patientEstWait');
    if (patServing) patServing.textContent = serving;
    if (patRoom) patRoom.textContent = room;
    if (patCount) patCount.textContent = count;
    if (patLabel) patLabel.textContent = count === 1 ? 'patient' : 'patients';
    if (patEst) patEst.textContent = est + ' min';

    // Staff Portal
    state.currentServingTicketId = data.currently_serving_id || null;
    const staffServing = document.getElementById('staffCurrentServing');
    const staffRoom = document.getElementById('staffCurrentRoom');
    const staffCount = document.getElementById('staffWaitingCount');
    const staffList = document.getElementById('staffWaitingList');
    const staffActions = document.getElementById('staffServingActions');
    if (staffServing) staffServing.textContent = serving;
    if (staffRoom) staffRoom.textContent = room;
    if (staffCount) staffCount.textContent = count;
    if (staffActions) staffActions.classList.toggle('hidden', !state.currentServingTicketId);

    if (staffList) {
      if (waiting.length === 0) {
        staffList.innerHTML = '<span class="text-xs text-stone-600">No patients waiting</span>';
      } else {
        staffList.innerHTML = waiting.map(t => `
          <span class="px-2.5 py-1 rounded-lg bg-amber-100 text-amber-800 font-mono font-bold text-xs">
            ${escapeHTML(t)}
          </span>
        `).join('');
      }
    }

    // Check if active ticket was served (toast once per called ticket)
    if (state.myTicket && serving === state.myTicket) {
      if (state.lastNotifiedTicket !== serving) {
        state.lastNotifiedTicket = serving;
        showToast(`Attention: Your ticket ${state.myTicket} is now being called to ${room || 'your consultation room'}!`, 'success');
      }
    } else if (state.lastNotifiedTicket && serving !== state.lastNotifiedTicket) {
      state.lastNotifiedTicket = null;
    }

    // Login-gateway preview box mirrors the same live queue state
    const scServing = document.getElementById('showcaseServing');
    if (scServing) {
      const isServing = serving && serving !== 'None';
      scServing.textContent = isServing ? serving : 'STANDBY';
      const scRoom = document.getElementById('showcaseRoom');
      if (scRoom) scRoom.textContent = isServing ? room : 'Room N/A';
      const scNext = document.getElementById('showcaseNext');
      if (scNext) scNext.textContent = waiting[0] || 'No one waiting';
      const scCount = document.getElementById('showcaseCount');
      if (scCount) scCount.textContent = count;
    }
  }

  function syncMyTicketCard(activeTicket) {
    const ticketCard = document.getElementById('myTicketCard');
    const ticketNum = document.getElementById('myTicketNumber');
    const ticketStatusEl = document.getElementById('myTicketStatusLabel');
    const btn = document.getElementById('issueMyTicketBtn');
    const btnLabel = document.getElementById('issueMyTicketLabel');

    if (activeTicket && activeTicket.ticket_number) {
      state.myTicket = activeTicket.ticket_number;
      localStorage.setItem('my_ticket', state.myTicket);
      if (ticketCard) ticketCard.classList.remove('hidden');
      if (ticketNum) ticketNum.textContent = activeTicket.ticket_number;
      if (ticketStatusEl) {
        const statusText = activeTicket.status === 'called'
          ? `Called to ${activeTicket.room_number || 'Consultation Room'} (${activeTicket.doctor_name || ''})`
          : activeTicket.status === 'in_consultation'
            ? `In Consultation at ${activeTicket.room_number || 'Room'}`
            : `Waiting for ${activeTicket.doctor_name || 'Physician'} (${activeTicket.room_number || 'Room'})`;
        ticketStatusEl.textContent = statusText;
      }
      if (btn) btn.disabled = true;
      if (btnLabel) btnLabel.textContent = `Active Queue Ticket: ${activeTicket.ticket_number}`;
    } else {
      state.myTicket = null;
      localStorage.removeItem('my_ticket');
      if (ticketCard) ticketCard.classList.add('hidden');
      if (btn) btn.disabled = false;
      if (btnLabel) btnLabel.textContent = 'Take Walk-in Queue Ticket';
    }
  }

  async function loadMyActiveTicket() {
    if (!state.user || state.user.role !== 'patient') {
      syncMyTicketCard(null);
      return;
    }
    try {
      const res = await apiFetch(API.queue.myTicket);
      syncMyTicketCard(res ? res.active_ticket : null);
    } catch (_) {}
  }

  async function issueMyQueueTicket() {
    if (!state.user || state.user.role !== 'patient') {
      showToast('Please sign in as a patient to get a queue ticket', 'error');
      openLoginGateway('login', 'patient');
      return;
    }
    const doctorId = parseInt(
      document.getElementById('walkinTicketDoctorSelect')?.value ||
      document.getElementById('appointmentDoctorSelect')?.value,
      10
    );
    if (!doctorId) {
      showToast('Please select a doctor before taking a queue ticket', 'error');
      return;
    }
    try {
      const res = await apiFetch(API.queue.issue, {
        method: 'POST',
        body: { doctor_id: doctorId, priority: 'normal' },
      });
      syncMyTicketCard({
        ticket_number: res.ticket_number,
        status: 'waiting',
        doctor_name: '',
        room_number: '',
      });
      showToast(`Queue ticket ${res.ticket_number} issued successfully!`, 'success');
      fetchQueueStatus();
    } catch (err) {
      showToast(`Failed to get ticket: ${err.message}`, 'error');
    }
  }

  async function loadActiveQueue() {
    if (!state.user || !['staff', 'doctor', 'admin'].includes(state.user.role)) return;
    try {
      const rows = await apiFetch(API.queue.active);
      const staffList = document.getElementById('staffActiveTicketsList');
      if (staffList) {
        if (!rows || rows.length === 0) {
          staffList.innerHTML = '';
        } else {
          staffList.innerHTML = rows.map(t => {
            const isWaiting = t.status === 'waiting';
            const isCalled = t.status === 'called';
            const isConsult = t.status === 'in_consultation';
            const statusCls = isConsult
              ? 'bg-emerald-100 text-emerald-800'
              : (isCalled ? 'bg-brand-100 text-brand-800' : 'bg-amber-100 text-amber-800');
            const btns = isCalled ? `
              <button type="button" onclick="window.ClinicApp.advanceTicketById(${t.id}, 'in_consultation')" class="btn btn-outline btn-sm text-xs">Start</button>
              <button type="button" onclick="window.ClinicApp.advanceTicketById(${t.id}, 'completed')" class="btn btn-primary btn-sm text-xs">Complete</button>
              <button type="button" onclick="window.ClinicApp.advanceTicketById(${t.id}, 'cancelled')" class="btn btn-outline btn-sm text-xs text-rose-700">Cancel</button>
            ` : (isConsult ? `
              <button type="button" onclick="window.ClinicApp.advanceTicketById(${t.id}, 'completed')" class="btn btn-primary btn-sm text-xs">Complete</button>
            ` : `
              <button type="button" onclick="window.ClinicApp.advanceTicketById(${t.id}, 'cancelled')" class="btn btn-outline btn-sm text-xs text-rose-700">Cancel</button>
            `);
            return `
              <div class="p-2.5 rounded-xl bg-white border border-stone-200/80 flex flex-wrap items-center justify-between gap-2">
                <div class="min-w-0">
                  <span class="font-mono font-bold text-stone-900">${escapeHTML(t.ticket_number)}</span>
                  <span class="text-stone-700 font-medium"> ${escapeHTML(t.patient_name)}</span>
                  <span class="text-[11px] text-stone-500 block truncate">${escapeHTML(t.doctor_name)} (${escapeHTML(t.room_number)})${t.priority === 'urgent' ? ' \u2022 URGENT' : ''}</span>
                </div>
                <div class="flex items-center gap-1.5 flex-wrap shrink-0">
                  <span class="pill ${statusCls} uppercase text-[10px] font-bold">${escapeHTML(t.status.replace('_', ' '))}</span>
                  ${btns}
                </div>
              </div>
            `;
          }).join('');
        }
      }

      const docList = document.getElementById('doctorQueueList');
      if (docList && state.user.role === 'doctor') {
        const docId = state.user.doctor_id;
        const mine = (rows || []).filter(t => t.doctor_id === docId);
        if (mine.length === 0) {
          docList.innerHTML = '<p class="text-stone-600 py-2 text-center">No active queue tickets.</p>';
        } else {
          docList.innerHTML = mine.map(t => {
            const isCalled = t.status === 'called';
            const isConsult = t.status === 'in_consultation';
            const statusCls = isConsult
              ? 'bg-emerald-100 text-emerald-800'
              : (isCalled ? 'bg-brand-100 text-brand-800' : 'bg-amber-100 text-amber-800');
            const actions = isCalled ? `
              <div class="flex gap-1.5 mt-2">
                <button type="button" onclick="window.ClinicApp.advanceTicketById(${t.id}, 'in_consultation')" class="btn btn-primary btn-sm flex-1 text-xs">Start Consultation</button>
                <button type="button" onclick="window.ClinicApp.advanceTicketById(${t.id}, 'completed')" class="btn btn-outline btn-sm text-xs">Complete</button>
                <button type="button" onclick="window.ClinicApp.advanceTicketById(${t.id}, 'cancelled')" class="btn btn-outline btn-sm text-xs text-rose-700">No-Show</button>
              </div>
            ` : (isConsult ? `
              <div class="flex gap-1.5 mt-2">
                <button type="button" onclick="window.ClinicApp.advanceTicketById(${t.id}, 'completed')" class="btn btn-primary btn-sm flex-1 text-xs">Mark Completed</button>
              </div>
            ` : '');
            return `
              <div class="p-2.5 rounded-xl bg-stone-50 border border-stone-200/80">
                <div class="flex items-center justify-between gap-2">
                  <div class="min-w-0">
                    <span class="font-mono font-bold text-stone-900">${escapeHTML(t.ticket_number)}</span>
                    <span class="text-stone-700 font-medium"> ${escapeHTML(t.patient_name)}</span>
                  </div>
                  <span class="pill ${statusCls} uppercase text-[10px] font-bold shrink-0">${escapeHTML(t.status.replace('_', ' '))}</span>
                </div>
                ${actions}
              </div>
            `;
          }).join('');
        }
      }
    } catch (err) {
      console.warn('Failed to load active queue:', err);
    }
  }

  async function callNextPatient() {
    const docId = parseInt(document.getElementById('callDoctorId')?.value, 10);
    if (!Number.isFinite(docId) || docId <= 0) {
      showToast('Please select an available doctor first.', 'error');
      return;
    }
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

  async function callMyNextPatient() {
    const docId = state.user?.doctor_id;
    if (!docId) {
      showToast('Doctor profile not found.', 'error');
      return;
    }
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

  async function advanceTicketById(ticketId, targetStatus) {
    if (!ticketId) return;
    try {
      const data = await apiFetch(API.queue.advance, {
        method: 'POST',
        body: { ticket_id: ticketId, to: targetStatus },
      });
      showToast(`Ticket ${data.ticket_number} marked ${targetStatus.replace('_', ' ')}.`, 'success');
      fetchQueueStatus();
    } catch (err) {
      showToast(`Queue update failed: ${err.message}`, 'error');
    }
  }

  async function advanceServingTicket(targetStatus) {
    if (!state.currentServingTicketId) return;
    await advanceTicketById(state.currentServingTicketId, targetStatus);
  }

  let walkinMode = 'existing';

  function switchWalkinMode(mode) {
    walkinMode = mode === 'new' ? 'new' : 'existing';
    const existingBox = document.getElementById('walkinExistingFields');
    const newBox = document.getElementById('walkinNewFields');
    const patientIdInput = document.getElementById('walkinPatientId');
    const newNameInput = document.getElementById('walkinNewName');
    const existingBtn = document.getElementById('walkinModeExistingBtn');
    const newBtn = document.getElementById('walkinModeNewBtn');

    if (existingBox) existingBox.classList.toggle('hidden', walkinMode === 'new');
    if (newBox) newBox.classList.toggle('hidden', walkinMode !== 'new');
    if (patientIdInput) patientIdInput.required = walkinMode === 'existing';
    if (newNameInput) newNameInput.required = walkinMode === 'new';

    if (existingBtn) {
      existingBtn.setAttribute('aria-pressed', String(walkinMode === 'existing'));
      existingBtn.classList.toggle('btn-primary', walkinMode === 'existing');
      existingBtn.classList.toggle('btn-outline', walkinMode !== 'existing');
    }
    if (newBtn) {
      newBtn.setAttribute('aria-pressed', String(walkinMode === 'new'));
      newBtn.classList.toggle('btn-primary', walkinMode === 'new');
      newBtn.classList.toggle('btn-outline', walkinMode !== 'new');
    }
  }

  async function registerWalkin(e) {
    e.preventDefault();
    const doctorId = parseInt(document.getElementById('walkinDoctorSelect').value, 10);
    if (!Number.isFinite(doctorId) || doctorId <= 0) {
      showToast('Please select an attending doctor.', 'error');
      return;
    }
    const priority = document.getElementById('walkinPriority').value || 'normal';

    try {
      let res;
      let resolvedPatientId;
      let resolvedName = '';

      if (walkinMode === 'new') {
        const fullName = (document.getElementById('walkinNewName')?.value || '').trim();
        if (!fullName) {
          showToast('Please enter the walk-in patient full name.', 'error');
          return;
        }
        const phone = formatPHPhone(document.getElementById('walkinNewPhone')?.value || '');
        const gender = document.getElementById('walkinNewGender')?.value || '';
        const allergies = (document.getElementById('walkinNewAllergies')?.value || '').trim();
        res = await apiFetch(API.queue.walkinRegister, {
          method: 'POST',
          body: {
            full_name: fullName,
            phone,
            gender,
            allergies,
            doctor_id: doctorId,
            priority,
          },
        });
        resolvedPatientId = res.patient_id;
        resolvedName = res.patient_name || fullName;
        const walkInput = document.getElementById('walkinPatientId');
        const billInput = document.getElementById('billPatientId');
        const billTicket = document.getElementById('billTicketId');
        if (walkInput) walkInput.value = resolvedPatientId;
        if (billInput) billInput.value = resolvedPatientId;
        if (billTicket && res.id) billTicket.value = res.id;
        loadPatientDirectory();
        ['walkinNewName', 'walkinNewPhone', 'walkinNewGender', 'walkinNewAllergies'].forEach(id => {
          const el = document.getElementById(id);
          if (el) el.value = '';
        });
      } else {
        resolvedPatientId = parseInt(document.getElementById('walkinPatientId').value, 10);
        if (!Number.isFinite(resolvedPatientId) || resolvedPatientId <= 0) {
          showToast('Please select a patient or enter a valid Patient ID.', 'error');
          return;
        }
        res = await apiFetch(API.queue.issue, {
          method: 'POST',
          body: { patient_id: resolvedPatientId, doctor_id: doctorId, priority },
        });
        const billTicket = document.getElementById('billTicketId');
        if (billTicket && res.id) billTicket.value = res.id;
      }

      const resultBox = document.getElementById('walkinTicketResult');
      if (resultBox) {
        resultBox.classList.remove('hidden');
        const who = resolvedName ? `${escapeHTML(resolvedName)} (ID #${resolvedPatientId})` : `Patient ID #${resolvedPatientId}`;
        resultBox.innerHTML = `
          <span class="text-xs text-brand-800 font-semibold block">Ticket Issued Successfully</span>
          <span class="text-3xl font-black text-brand-700 font-mono my-1 block">${escapeHTML(res.ticket_number)}</span>
          <span class="text-[11px] text-brand-600">${who} &bull; Triage: ${escapeHTML(priority)}</span>
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
      const walkTicketSelect = document.getElementById('walkinTicketDoctorSelect');
      const walkSelect = document.getElementById('walkinDoctorSelect');
      const callSelect = document.getElementById('callDoctorId');
      const fbSelect = document.getElementById('feedbackDoctorSelect');

      if (doctors && doctors.length > 0) {
        // Staff selects are narrow: native options clip silently, so the room
        // (the part staff dispatch on) gets the short label there. The patient
        // booking select is wide enough for specialization + room.
        const optionFull = d => `<option value="${d.id}">${escapeHTML(d.name)} (${escapeHTML(d.specialization)}) - ${escapeHTML(String(d.room_number || 'Room 102'))} &bull; ${escapeHTML(formatPHP(d.fee ?? 500))}</option>`;
        const optionBrief = d => `<option value="${d.id}">${escapeHTML(d.name)} - ${escapeHTML(String(d.room_number || 'Room 102'))}</option>`;

        if (appSelect) appSelect.innerHTML = doctors.map(optionFull).join('');
        if (walkTicketSelect) walkTicketSelect.innerHTML = doctors.map(optionBrief).join('');
        if (walkSelect) walkSelect.innerHTML = doctors.map(optionBrief).join('');
        if (callSelect) callSelect.innerHTML = doctors.map(optionBrief).join('');
        if (fbSelect) {
          fbSelect.innerHTML = '<option value="">General Clinic Experience</option>' + doctors.map(optionBrief).join('');
        }
      } else {
        const emptyOpt = '<option value="">No doctors available yet</option>';
        if (appSelect) appSelect.innerHTML = emptyOpt;
        if (walkTicketSelect) walkTicketSelect.innerHTML = emptyOpt;
        if (walkSelect) walkSelect.innerHTML = emptyOpt;
        if (callSelect) callSelect.innerHTML = emptyOpt;
        if (fbSelect) fbSelect.innerHTML = '<option value="">General Clinic Experience</option>';
      }
    } catch (err) {
      console.warn('Failed to load doctors list:', err);
    }
  }

  async function submitAppointment(e) {
    e.preventDefault();
    if (!state.user || state.user.role !== 'patient') {
      showToast('Please sign in as a patient to book an appointment', 'error');
      openLoginGateway('login', 'patient');
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
      showToast(`Appointment requested! Awaiting doctor approval (#${data.appointment_id})`, 'success');
      document.getElementById('appointmentForm').reset();
      const appDate = document.getElementById('appointmentDate');
      if (appDate) appDate.value = clinicTodayISO();
      loadMyAppointments();
    } catch (err) {
      showToast(`Booking error: ${err.message}`, 'error');
    }
  }

  async function loadMyAppointments() {
    const list = document.getElementById('patientAppointmentsList');
    if (!list) return;
    if (!state.user || state.user.role !== 'patient') {
      list.innerHTML = '<p class="text-stone-600 py-3 text-center">Sign in to view your appointments.</p>';
      return;
    }
    try {
      const rows = await apiFetch(API.appointments.my);
      if (!rows || rows.length === 0) {
        list.innerHTML = '<p class="text-stone-600 py-3 text-center">No appointments booked yet.</p>';
        return;
      }
      list.innerHTML = rows.map(a => {
        const isCancelled = a.status === 'cancelled';
        const isCompleted = a.status === 'completed';
        const isPending = a.status === 'pending';
        const statusCls = isCancelled
          ? 'bg-stone-100 text-stone-600'
          : (isCompleted
            ? 'bg-emerald-100 text-emerald-800'
            : (isPending ? 'bg-amber-100 text-amber-800' : 'bg-brand-50 text-brand-700'));
        const cancelBtn = (!isCancelled && !isCompleted)
          ? `<button type="button" onclick="window.ClinicApp.cancelMyAppointment(${a.id})" class="btn btn-outline btn-sm text-rose-700 border-rose-200 hover:bg-rose-50 shrink-0">Cancel</button>`
          : '';
        return `
          <div class="p-3 rounded-xl bg-stone-50 border border-stone-200/80 flex items-center justify-between gap-2">
            <div class="min-w-0">
              <span class="font-bold text-stone-900 block truncate">${escapeHTML(a.appointment_date)} &bull; ${escapeHTML(a.time_slot)}</span>
              <span class="text-[11px] text-stone-600 block truncate">${escapeHTML(a.doctor_name)} (${escapeHTML(a.room_number || 'Room N/A')})</span>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <span class="pill ${statusCls} uppercase text-[10px] font-bold">${escapeHTML(a.status)}</span>
              ${cancelBtn}
            </div>
          </div>
        `;
      }).join('');
    } catch (err) {
      list.innerHTML = `<p class="text-rose-600 py-3 text-center">${escapeHTML(err.message || 'Failed to load appointments')}</p>`;
    }
  }

  async function cancelMyAppointment(appointmentId) {
    try {
      await apiFetch(`${API.appointments.base}/${appointmentId}/cancel`, { method: 'POST' });
      showToast('Appointment cancelled.', 'info');
      loadMyAppointments();
    } catch (err) {
      showToast(`Cancel failed: ${err.message}`, 'error');
    }
  }

  async function loadMyPrescriptions() {
    const list = document.getElementById('patientPrescriptionsList');
    if (!list) return;
    if (!state.user || state.user.role !== 'patient') {
      list.innerHTML = '<p class="text-stone-600 py-3 text-center">Sign in to view your prescriptions.</p>';
      return;
    }
    try {
      const rows = await apiFetch(API.emr.myPrescriptions);
      if (!rows || rows.length === 0) {
        list.innerHTML = '<p class="text-stone-600 py-3 text-center">No prescriptions issued yet.</p>';
        return;
      }
      list.innerHTML = rows.map(rx => {
        const medsHtml = (rx.medications || []).map(m =>
          `<div>&bull; <strong>${escapeHTML(m.drug_name || m.name || '')}</strong> ${escapeHTML(m.dosage || '')} &mdash; ${escapeHTML(m.frequency || '')} (${escapeHTML(m.duration || '')})</div>`
        ).join('');
        const qrHtml = rx.qr_code_image && rx.qr_code_image.startsWith('data:image/')
          ? `<img src="${rx.qr_code_image}" alt="Prescription QR code for ${escapeHTML(rx.qr_code_hash)}" class="w-16 h-16 rounded border border-brand-200 bg-white p-0.5 shrink-0">`
          : '';
        return `
          <div class="p-3 rounded-xl bg-stone-50 border border-stone-200/80 flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1 space-y-1">
              <div class="flex items-center justify-between gap-2">
                <span class="font-bold text-stone-900 truncate">${escapeHTML(rx.diagnosis)}</span>
                <span class="text-[10px] text-stone-600 shrink-0">${escapeHTML(rx.created_at)}</span>
              </div>
              <span class="text-[11px] text-stone-600 block">${escapeHTML(rx.doctor_name)} &bull; ${escapeHTML(rx.specialization || '')}</span>
              ${rx.notes ? `<p class="text-[11px] text-stone-600">${escapeHTML(rx.notes)}</p>` : ''}
              ${medsHtml ? `<div class="text-[11px] text-brand-800 bg-brand-50 p-2 rounded-lg space-y-0.5">${medsHtml}</div>` : ''}
              <span class="text-[10px] font-mono text-stone-600 block">Rx Code: ${escapeHTML(rx.qr_code_hash)}</span>
            </div>
            ${qrHtml}
          </div>
        `;
      }).join('');
    } catch (err) {
      list.innerHTML = `<p class="text-rose-600 py-3 text-center">${escapeHTML(err.message || 'Failed to load prescriptions')}</p>`;
    }
  }

  async function loadMyInvoices() {
    const list = document.getElementById('patientInvoicesList');
    if (!list) return;
    if (!state.user || state.user.role !== 'patient') {
      list.innerHTML = '<p class="text-stone-600 py-3 text-center">Sign in to view your receipts.</p>';
      return;
    }
    try {
      const rows = await apiFetch(API.billing.my);
      if (!rows || rows.length === 0) {
        list.innerHTML = '<p class="text-stone-600 py-3 text-center">No billing receipts recorded yet.</p>';
        return;
      }
      list.innerHTML = rows.map(inv => {
        const qrHtml = inv.qr_code_image && inv.qr_code_image.startsWith('data:image/')
          ? `<img src="${inv.qr_code_image}" alt="Receipt QR code for ${escapeHTML(inv.receipt_number)}" class="w-14 h-14 rounded border border-stone-200 bg-white p-0.5 shrink-0">`
          : '';
        return `
          <div class="p-3 rounded-xl bg-stone-50 border border-stone-200/80 flex items-center justify-between gap-3">
            <div class="min-w-0 flex-1">
              <span class="font-mono font-bold text-stone-900 block truncate">${escapeHTML(inv.receipt_number)}</span>
              <span class="text-[11px] text-stone-600 block">${escapeHTML(inv.paid_at || '')} &bull; ${escapeHTML((inv.payment_method || '').replace('_', ' ').toUpperCase())}</span>
              <span class="text-xs font-extrabold text-brand-700 font-mono tabular-nums mt-0.5 block">${escapeHTML(formatPHP(inv.total_amount || 0))}</span>
            </div>
            ${qrHtml}
          </div>
        `;
      }).join('');
    } catch (err) {
      list.innerHTML = `<p class="text-rose-600 py-3 text-center">${escapeHTML(err.message || 'Failed to load receipts')}</p>`;
    }
  }

  async function loadStaffAppointments() {
    const list = document.getElementById('staffAppointmentsList');
    if (!list || !state.user || (state.user.role !== 'staff' && state.user.role !== 'admin')) return;
    const dateEl = document.getElementById('staffAppointmentsDate');
    const targetDate = (dateEl && dateEl.value) ? dateEl.value : clinicTodayISO();
    if (dateEl && !dateEl.value) dateEl.value = targetDate;
    try {
      const rows = await apiFetch(`${API.appointments.daily}?schedule_date=${encodeURIComponent(targetDate)}`);
      if (!rows || rows.length === 0) {
        list.innerHTML = `<p class="text-stone-600 py-3 text-center">No appointments scheduled for ${escapeHTML(targetDate)}.</p>`;
        return;
      }
      list.innerHTML = rows.map(a => {
        const isCancelled = a.status === 'cancelled';
        const isCompleted = a.status === 'completed';
        const isPending = a.status === 'pending';
        const statusCls = isCancelled
          ? 'bg-rose-100 text-rose-800'
          : (isCompleted
            ? 'bg-emerald-100 text-emerald-800'
            : (isPending ? 'bg-amber-100 text-amber-800' : 'bg-brand-50 text-brand-700'));
        const actions = a.status === 'confirmed' ? `
          <div class="flex flex-wrap gap-1.5 mt-2">
            <button type="button" onclick="window.ClinicApp.checkInAppointment(${a.patient_id}, ${a.doctor_id}, ${a.id})" class="btn btn-primary btn-sm">Check In</button>
            <button type="button" onclick="window.ClinicApp.updateAppointmentStatus(${a.id}, 'completed')" class="btn btn-outline btn-sm">Complete</button>
            <button type="button" onclick="window.ClinicApp.updateAppointmentStatus(${a.id}, 'cancelled')" class="btn btn-outline btn-sm text-rose-700 border-rose-200 hover:bg-rose-50">Cancel</button>
          </div>` : (isPending ? `
          <div class="flex flex-wrap items-center justify-between gap-1.5 mt-2">
            <span class="text-[11px] text-amber-800 font-medium">Awaiting doctor approval</span>
            <button type="button" onclick="window.ClinicApp.updateAppointmentStatus(${a.id}, 'cancelled')" class="btn btn-outline btn-sm text-rose-700 border-rose-200 hover:bg-rose-50">Cancel</button>
          </div>` : '');
        return `
          <div class="p-3 rounded-xl bg-stone-50 border border-stone-200/80">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <span class="font-bold text-stone-900 block truncate">${escapeHTML(a.time_slot)} &bull; ${escapeHTML(a.patient_name)} (#${a.patient_id})</span>
                <span class="text-[11px] text-stone-600 block truncate">${escapeHTML(a.doctor_name)} (${escapeHTML(a.room_number || 'Room N/A')})</span>
              </div>
              <span class="pill ${statusCls} uppercase text-[10px] font-bold shrink-0">${escapeHTML(a.status)}</span>
            </div>
            ${actions}
          </div>
        `;
      }).join('');
    } catch (err) {
      list.innerHTML = `<p class="text-rose-600 py-3 text-center">${escapeHTML(err.message || 'Failed to load appointments')}</p>`;
    }
  }

  async function checkInAppointment(patientId, doctorId, appointmentId = null) {
    try {
      const payload = { patient_id: patientId, doctor_id: doctorId, priority: 'normal' };
      if (appointmentId) payload.appointment_id = appointmentId;
      const res = await apiFetch(API.queue.issue, {
        method: 'POST',
        body: payload,
      });
      selectFoundPatient(patientId, 'staff', 'staffPatientMatches');
      const billTicket = document.getElementById('billTicketId');
      if (billTicket && res.id) billTicket.value = res.id;
      showToast(`Checked in Patient #${patientId} (Ticket ${res.ticket_number})`, 'success');
      fetchQueueStatus();
    } catch (err) {
      showToast(`Check-in failed: ${err.message}`, 'error');
    }
  }

  async function updateAppointmentStatus(appointmentId, targetStatus) {
    try {
      await apiFetch(`${API.appointments.base}/${appointmentId}/status`, {
        method: 'POST',
        body: { status: targetStatus },
      });
      showToast(`Appointment marked ${targetStatus}.`, 'success');
      loadStaffAppointments();
    } catch (err) {
      showToast(`Status update failed: ${err.message}`, 'error');
    }
  }

  async function loadPatientDirectory() {
    if (!state.user || !['staff', 'doctor', 'admin'].includes(state.user.role)) return;
    try {
      const rows = await apiFetch(API.queue.patients);
      const targets = ['walkinPatientSelect', 'billPatientSelect', 'emrPatientSelect'];
      targets.forEach(selectId => {
        const sel = document.getElementById(selectId);
        if (!sel) return;
        const prev = sel.value;
        sel.innerHTML = '<option value="">Select patient...</option>' + (rows || []).map(p =>
          `<option value="${p.id}">${escapeHTML(p.full_name)} (#${p.id})</option>`
        ).join('');
        if (prev && (rows || []).some(p => String(p.id) === String(prev))) {
          sel.value = prev;
        }
      });
    } catch (err) {
      console.warn('Failed to load patient directory:', err);
    }
  }

  function onSelectPatientDropdown(val, targetMode) {
    const pid = parseInt(val, 10);
    if (!pid) return;
    selectFoundPatient(pid, targetMode, targetMode === 'emr' ? 'emrPatientMatches' : 'staffPatientMatches');
  }

  // Shared patient name/ID search helper for Staff check-in/billing and Doctor EMR lookup
  let patientLookupTimer = null;
  function lookupPatients(query, containerId, targetMode) {
    const box = document.getElementById(containerId);
    if (!box) return;
    const term = String(query || '').trim();
    if (!term) {
      box.innerHTML = '';
      box.classList.add('hidden');
      return;
    }
    clearTimeout(patientLookupTimer);
    patientLookupTimer = setTimeout(async () => {
      try {
        const rows = await apiFetch(`${API.queue.patients}?q=${encodeURIComponent(term)}`);
        if (!rows || rows.length === 0) {
          box.innerHTML = '<span class="text-[11px] text-stone-600">No matching patients.</span>';
          box.classList.remove('hidden');
          return;
        }
        box.innerHTML = rows.map(p => `
          <button type="button" onclick="window.ClinicApp.selectFoundPatient(${p.id}, '${targetMode}', '${containerId}')" class="chip text-xs">
            ${escapeHTML(p.full_name)} (#${p.id})
          </button>
        `).join('');
        box.classList.remove('hidden');
      } catch (err) {
        box.innerHTML = `<span class="text-[11px] text-rose-600">${escapeHTML(err.message || 'Lookup failed')}</span>`;
        box.classList.remove('hidden');
      }
    }, 180);
  }

  function selectFoundPatient(patientId, targetMode, containerId) {
    if (targetMode === 'emr') {
      const emrInput = document.getElementById('emrPatientId');
      const emrSel = document.getElementById('emrPatientSelect');
      if (emrInput) emrInput.value = patientId;
      if (emrSel) emrSel.value = String(patientId);
      searchPatientEMR(patientId);
    } else {
      const walkInput = document.getElementById('walkinPatientId');
      const walkSel = document.getElementById('walkinPatientSelect');
      const billInput = document.getElementById('billPatientId');
      const billSel = document.getElementById('billPatientSelect');
      if (walkInput) walkInput.value = patientId;
      if (walkSel) walkSel.value = String(patientId);
      if (billInput) billInput.value = patientId;
      if (billSel) billSel.value = String(patientId);
    }
    const box = document.getElementById(containerId);
    if (box) {
      box.innerHTML = '';
      box.classList.add('hidden');
    }
  }

  async function loadDoctorPendingApprovals() {
    const card = document.getElementById('doctorPendingCard');
    const list = document.getElementById('doctorPendingList');
    const countEl = document.getElementById('doctorPendingCount');
    if (!card || !list) return;
    if (!state.user || state.user.role !== 'doctor') {
      card.classList.add('hidden');
      return;
    }
    try {
      const rows = await apiFetch(API.appointments.doctorPending);
      if (!rows || rows.length === 0) {
        card.classList.add('hidden');
        list.innerHTML = '';
        if (countEl) countEl.textContent = '0';
        return;
      }
      if (countEl) countEl.textContent = String(rows.length);
      card.classList.remove('hidden');
      list.innerHTML = rows.map(a => `
        <div class="p-2.5 rounded-xl bg-white border border-amber-200 space-y-2">
          <div class="min-w-0">
            <span class="font-bold text-stone-900 block truncate">${escapeHTML(a.patient_name)} (#${a.patient_id})</span>
            <span class="text-[11px] text-stone-600 block">${escapeHTML(a.appointment_date)} &bull; ${escapeHTML(a.time_slot)}</span>
            ${a.reason ? `<span class="text-[11px] text-stone-600 block truncate">${escapeHTML(a.reason)}</span>` : ''}
          </div>
          <div class="flex gap-1.5">
            <button type="button" onclick="window.ClinicApp.updateDoctorAppointmentStatus(${a.id}, 'confirmed')" class="btn btn-primary btn-sm flex-1">Approve</button>
            <button type="button" onclick="window.ClinicApp.updateDoctorAppointmentStatus(${a.id}, 'cancelled')" class="btn btn-outline btn-sm text-rose-700 border-rose-200 hover:bg-rose-50">Decline</button>
          </div>
        </div>
      `).join('');
    } catch (err) {
      console.warn('Failed to load pending approvals:', err);
    }
  }

  async function updateDoctorAppointmentStatus(appointmentId, targetStatus) {
    try {
      await apiFetch(`${API.appointments.base}/${appointmentId}/status`, {
        method: 'POST',
        body: { status: targetStatus },
      });
      showToast(targetStatus === 'confirmed' ? 'Appointment approved.' : 'Appointment declined.', 'success');
      loadDoctorPendingApprovals();
      loadDoctorSchedule();
    } catch (err) {
      showToast(`Action failed: ${err.message}`, 'error');
    }
  }

  // Doctor Schedule
  async function loadDoctorSchedule() {
    const docId = state.user?.doctor_id;
    const dateInput = document.getElementById('scheduleFilterDate');
    if (!docId) {
      const list = document.getElementById('scheduleList');
      if (list) list.innerHTML = '<p class="text-xs text-stone-600 py-6 text-center">Sign in as a doctor to view a schedule.</p>';
      return;
    }
    const scheduleDate = dateInput && dateInput.value ? dateInput.value : clinicTodayISO();
    if (dateInput && !dateInput.value) dateInput.value = scheduleDate;

    try {
      const data = await apiFetch(`${API.appointments.schedule}/${docId}?schedule_date=${scheduleDate}`);
      const list = document.getElementById('scheduleList');
      if (!list) return;

      if (!data || data.length === 0) {
        list.innerHTML = '<p class="text-xs text-stone-600 py-6 text-center">No appointments scheduled for this date.</p>';
        return;
      }

      list.innerHTML = data.map(app => {
        const isWalkin = app.entry_type === 'walk_in';
        const isPending = !isWalkin && app.status === 'pending';
        const statusCls = app.status === 'cancelled'
          ? 'bg-rose-100 text-rose-800 border-rose-200'
          : (app.status === 'completed'
            ? 'bg-emerald-100 text-emerald-800 border-emerald-200'
            : ((isWalkin || isPending) ? 'bg-amber-100 text-amber-800 border-amber-200' : 'bg-brand-50 text-brand-700 border-brand-200/60'));
        const typeBadge = isWalkin
          ? '<span class="pill bg-amber-100 text-amber-800 border border-amber-200 text-[10px] font-bold uppercase shrink-0">Walk-In</span>'
          : '';
        const pendingActions = isPending ? `
          <div class="flex gap-1.5 mt-2">
            <button type="button" onclick="window.ClinicApp.updateDoctorAppointmentStatus(${app.id}, 'confirmed')" class="btn btn-primary btn-sm flex-1">Approve</button>
            <button type="button" onclick="window.ClinicApp.updateDoctorAppointmentStatus(${app.id}, 'cancelled')" class="btn btn-outline btn-sm text-rose-700 border-rose-200 hover:bg-rose-50">Decline</button>
          </div>` : '';
        return `
        <div class="schedule-patient-item p-3 rounded-xl bg-white hover:bg-brand-50/70 border border-stone-200/80 text-xs cursor-pointer transition-all shadow-sm hover:border-brand-300"
             data-patient-id="${parseInt(app.patient_id, 10) || ''}"
             data-patient-name="${escapeHTML(app.patient_name || 'Patient')}">
          <div class="flex justify-between items-center gap-2">
            <div class="min-w-0">
              <span class="font-bold text-stone-900 block truncate">${escapeHTML(app.time_slot)} - ${escapeHTML(app.patient_name)}</span>
              <span class="text-stone-600 text-[11px] block truncate">${escapeHTML(app.reason || 'General Consultation')}</span>
            </div>
            <div class="flex items-center gap-1.5 shrink-0">
              ${typeBadge}
              <span class="pill ${statusCls} uppercase border text-[10px] font-bold">${escapeHTML(app.status)}</span>
            </div>
          </div>
          ${pendingActions}
        </div>
      `;
      }).join('');
    } catch (err) {
      console.warn('Failed to load schedule:', err);
    }
  }

  function selectConsultationPatient(patientId, patientName) {
    if (!patientId) return;
    document.querySelectorAll('.schedule-patient-item').forEach(item => {
      const pid = parseInt(item.getAttribute('data-patient-id'), 10);
      if (pid === patientId) {
        item.classList.add('ring-2', 'ring-brand-500', 'bg-brand-50');
      } else {
        item.classList.remove('ring-2', 'ring-brand-500', 'bg-brand-50');
      }
    });

    const emrInput = document.getElementById('emrPatientId');
    if (emrInput) emrInput.value = patientId;
    searchPatientEMR(patientId);

    const rxInput = document.getElementById('rxPatientId');
    if (rxInput) rxInput.value = patientId;

    showToast(`Loaded clinical record for ${patientName || `Patient #${patientId}`}`, 'info');
  }

  // One delegated handler for schedule rows: no dynamic inline JS, so patient
  // controlled text can never reach a JS execution context (XSS fix).
  document.addEventListener('click', (e) => {
    if (e.target.closest('button')) return;
    const row = e.target.closest('.schedule-patient-item');
    if (!row) return;
    const pid = parseInt(row.getAttribute('data-patient-id'), 10);
    if (!pid) return;
    selectConsultationPatient(pid, row.getAttribute('data-patient-name') || '');
  });

  function resetDoctorEMRView() {
    const nameEl = document.getElementById('emrName');
    const dobEl = document.getElementById('emrDob');
    const bloodEl = document.getElementById('emrBlood');
    const allergyEl = document.getElementById('emrAllergies');
    const historyEl = document.getElementById('emrHistory');
    const rxList = document.getElementById('emrPrescriptionsList');
    const rxAlert = document.getElementById('rxAllergyBanner');
    const rxPatientId = document.getElementById('rxPatientId');
    const emrInput = document.getElementById('emrPatientId');
    const rxResult = document.getElementById('prescriptionResultCard');

    if (nameEl) nameEl.textContent = 'No patient selected';
    if (dobEl) dobEl.textContent = 'Select a patient from Today\'s Patient Roster or search by ID';
    if (bloodEl) bloodEl.textContent = '--';
    if (allergyEl) {
      allergyEl.textContent = '--';
      allergyEl.className = 'text-xs font-semibold text-stone-600 bg-stone-100 border border-stone-200/80 px-2.5 py-0.5 rounded-lg';
    }
    if (historyEl) historyEl.textContent = '--';
    if (rxList) rxList.innerHTML = '<p class="text-stone-600 py-2 text-center">Select a patient to view prescription history.</p>';
    if (rxAlert) rxAlert.classList.add('hidden');
    if (rxPatientId) rxPatientId.value = '';
    if (emrInput) emrInput.value = '';
    if (rxResult) rxResult.classList.add('hidden');
  }

  // EMR & Prescriptions
  async function searchPatientEMR(explicitId = null) {
    const idInput = document.getElementById('emrPatientId');
    const parsedInput = idInput ? parseInt(idInput.value, 10) : NaN;
    const patientId = explicitId || (Number.isFinite(parsedInput) && parsedInput > 0 ? parsedInput : null);
    if (!patientId) {
      showToast('Please enter a Patient ID or select a patient from the schedule.', 'info');
      return;
    }

    try {
      const emr = await apiFetch(`${API.emr.patient}/${patientId}`);
      state.selectedEmrPatientId = emr.patient_id || patientId;
      const rxInput = document.getElementById('rxPatientId');
      if (rxInput) rxInput.value = state.selectedEmrPatientId;
      document.getElementById('emrName').textContent = emr.name || `Patient #${patientId}`;
      document.getElementById('emrDob').textContent = `${emr.dob || 'N/A'} / ${emr.gender || 'Unspecified'}`;
      document.getElementById('emrBlood').textContent = emr.blood_group || 'Unknown';
      const allergyEl = document.getElementById('emrAllergies');
      if (allergyEl) {
        allergyEl.textContent = emr.allergies || 'None';
        if (emr.allergies && emr.allergies.toLowerCase() !== 'none' && emr.allergies.toLowerCase() !== 'none known') {
          allergyEl.className = 'text-xs font-bold text-red-700 bg-red-50 border border-red-200/80 px-2.5 py-0.5 rounded-lg';
        } else {
          allergyEl.className = 'text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200/80 px-2.5 py-0.5 rounded-lg';
        }
      }
      document.getElementById('emrHistory').textContent = emr.medical_history || 'No chronic history';

      // Auto-catch: surface allergies next to the prescribing desk so they are
      // impossible to miss when issuing a prescription for this patient.
      const rxAlert = document.getElementById('rxAllergyBanner');
      if (rxAlert) {
        const allergyText = (emr.allergies || '').trim();
        const hasAllergy = allergyText && !['none', 'none known', 'no known allergies', 'nka'].includes(allergyText.toLowerCase());
        rxAlert.classList.toggle('hidden', !hasAllergy);
        const rxAlertText = document.getElementById('rxAllergyText');
        if (rxAlertText) rxAlertText.textContent = hasAllergy ? `Allergy alert: ${allergyText}. Check medications against this list before prescribing.` : '';
      }

      const rxList = document.getElementById('emrPrescriptionsList');
      if (rxList) {
        if (!emr.prescriptions || emr.prescriptions.length === 0) {
          rxList.innerHTML = '<p class="text-stone-600 py-2 text-center">No previous prescriptions on file.</p>';
        } else {
          rxList.innerHTML = emr.prescriptions.map(rx => `
            <div class="p-2.5 rounded-lg bg-white border border-stone-200 shadow-card">
              <div class="flex justify-between gap-2 font-semibold text-stone-800">
                <span class="truncate">Dx: ${escapeHTML(rx.diagnosis)}</span>
                <span class="text-[10px] text-stone-600 shrink-0">${escapeHTML(rx.created_at)}</span>
              </div>
              <p class="text-stone-500 text-[11px] my-1">${escapeHTML(rx.notes || '')}</p>
              <div class="text-[10px] text-brand-700 bg-brand-50 p-1.5 rounded">
                ${rx.medications ? rx.medications.map(m => `&bull; ${escapeHTML(m.drug_name || m.name || '')} ${escapeHTML(m.dosage || '')}`).join('<br>') : ''}
              </div>
            </div>
          `).join('');
        }
      }
    } catch (err) {
      const rxAlert = document.getElementById('rxAllergyBanner');
      if (rxAlert) rxAlert.classList.add('hidden');
      showToast(`EMR lookup failed: ${err.message}`, 'error');
    }
  }

  function addMedicationRow() {
    const container = document.getElementById('medicationsContainer');
    if (!container) return;
    const row = document.createElement('div');
    row.className = 'med-row bg-stone-50 p-2.5 rounded-xl border border-stone-200 space-y-1.5';
    row.innerHTML = `
      <div class="flex justify-between items-center">
        <span class="text-[10px] font-bold text-stone-500 uppercase">Medication Item</span>
        <button type="button" onclick="this.closest('.med-row').remove()" class="btn btn-ghost btn-sm text-rose-600 hover:bg-rose-50 text-xs font-bold">Remove</button>
      </div>
      <div class="grid grid-cols-2 gap-1.5">
        <input type="text" placeholder="Drug Name" aria-label="Drug name" class="med-name input !px-2.5 !py-2" required>
        <input type="text" placeholder="Dosage" aria-label="Dosage" class="med-dosage input !px-2.5 !py-2" required>
      </div>
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-1.5">
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
    if (!Number.isFinite(patientId) || patientId <= 0) {
      showToast('Please select a patient from the schedule or look up their chart by ID first.', 'error');
      return;
    }
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
              <span class="text-[10px] text-brand-700 font-mono break-all">CODE: ${escapeHTML(res.qr_code_hash)}</span>
            </div>
          </div>
          <p class="text-[11px] text-brand-800">Prescription #${res.prescription_id} securely saved and linked to patient record.</p>
        `;
      }
      showToast('Digital prescription generated with verification hash!', 'success');
      const rxForm = document.getElementById('prescriptionForm');
      if (rxForm) rxForm.reset();
      const medsBox = document.getElementById('medicationsContainer');
      if (medsBox) {
        medsBox.querySelectorAll('.med-row').forEach((row, idx) => {
          if (idx > 0) row.remove();
        });
      }
      const rxInputAfter = document.getElementById('rxPatientId');
      if (rxInputAfter) rxInputAfter.value = patientId;
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
    if (prev) prev.textContent = formatPHP(total);
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
    const submitBtn = document.getElementById('billingSubmitBtn');
    if (submitBtn) submitBtn.disabled = true;

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
        const qrImg = res.qr_code_image && res.qr_code_image.startsWith('data:image/')
          ? `<img src="${res.qr_code_image}" alt="Receipt verification QR code" class="w-16 h-16 rounded border border-stone-200 bg-white p-0.5 shrink-0">`
          : '';
        card.classList.remove('hidden');
        card.innerHTML = `
          <div class="flex items-center justify-between gap-3">
            <div class="min-w-0 flex-1">
              <span class="text-xs font-bold text-stone-800 block">Receipt: ${escapeHTML(res.receipt_number)}</span>
              <div class="flex justify-between items-center my-1 text-stone-600 gap-2">
                <span>Total Paid (${escapeHTML(method.toUpperCase())}):</span>
                <span class="font-extrabold text-stone-900 font-mono tabular-nums">${escapeHTML(formatPHP(res.total))}</span>
              </div>
              <span class="text-[10px] text-brand-600 font-semibold block">Transaction Finalized &amp; Paid</span>
            </div>
            ${qrImg}
          </div>
        `;
      }
      showToast(`Invoice ${res.receipt_number} generated!`, 'success');
      loadBillingHistory();
    } catch (err) {
      showToast(`Invoice generation failed: ${err.message}`, 'error');
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  async function loadBillingHistory() {
    const list = document.getElementById('billingHistoryList');
    if (!list || !state.user || (state.user.role !== 'staff' && state.user.role !== 'admin')) return;
    try {
      const rows = await apiFetch(API.billing.list);
      if (!rows || rows.length === 0) {
        list.innerHTML = '<p class="text-stone-600 py-3 text-center">No invoices recorded yet.</p>';
        return;
      }
      list.innerHTML = rows.slice(0, 10).map(inv => `
        <button type="button" onclick="window.ClinicApp.viewReceiptDetail(${inv.id})" class="w-full text-left p-2.5 rounded-xl bg-stone-50 hover:bg-brand-50/60 border border-stone-200/80 hover:border-brand-300 flex items-center justify-between gap-2 transition-colors min-h-[44px]">
          <div class="min-w-0">
            <span class="font-mono font-bold text-stone-900 block truncate">${escapeHTML(inv.receipt_number)}</span>
            <span class="text-[11px] text-stone-500 block truncate">${escapeHTML(inv.patient_name)} &bull; ${escapeHTML((inv.payment_method || '').replace('_', ' ').toUpperCase())}</span>
          </div>
          <span class="font-mono font-bold text-stone-900 tabular-nums shrink-0">${escapeHTML(formatPHP(inv.total_amount || 0))}</span>
        </button>
      `).join('');
    } catch (err) {
      list.innerHTML = `<p class="text-rose-600 py-3 text-center">${escapeHTML(err.message || 'Failed to load receipts')}</p>`;
    }
  }

  function showReceiptModal(inv) {
    const modal = document.getElementById('receiptModal');
    const body = document.getElementById('receiptModalBody');
    if (!modal || !body || !inv) return;
    const qrHtml = inv.qr_code_image && inv.qr_code_image.startsWith('data:image/')
      ? `<img src="${inv.qr_code_image}" alt="Receipt QR code for ${escapeHTML(inv.receipt_number)}" class="w-24 h-24 rounded-xl border border-stone-200 bg-white p-1 mx-auto">`
      : '';
    body.innerHTML = `
      <div class="text-center space-y-2 pb-3 border-b border-stone-100">
        ${qrHtml}
        <span class="font-mono font-bold text-sm text-stone-900 block">${escapeHTML(inv.receipt_number)}</span>
        <span class="text-[11px] text-stone-500 block">${escapeHTML(inv.patient_name)} &bull; ${escapeHTML(inv.paid_at || '')}</span>
      </div>
      <div class="space-y-1.5 text-stone-700">
        <div class="flex justify-between"><span>Consultation Fee</span><span class="font-mono tabular-nums">${escapeHTML(formatPHP(inv.consultation_fee || 0))}</span></div>
        <div class="flex justify-between"><span>Medication Fee</span><span class="font-mono tabular-nums">${escapeHTML(formatPHP(inv.medication_fee || 0))}</span></div>
        <div class="flex justify-between"><span>Other / Lab Fees</span><span class="font-mono tabular-nums">${escapeHTML(formatPHP(inv.other_fees || 0))}</span></div>
        <div class="flex justify-between text-rose-700"><span>Discount</span><span class="font-mono tabular-nums">-${escapeHTML(formatPHP(inv.discount_amount || 0))}</span></div>
      </div>
      <div class="pt-3 border-t border-stone-200 flex justify-between items-center font-bold text-stone-900 text-sm">
        <span>Total Paid (${escapeHTML((inv.payment_method || '').replace('_', ' ').toUpperCase())})</span>
        <span class="font-mono tabular-nums text-brand-700">${escapeHTML(formatPHP(inv.total_amount || 0))}</span>
      </div>
    `;
    modal.classList.remove('hidden');
  }

  function hideReceiptModal() {
    const modal = document.getElementById('receiptModal');
    if (modal) modal.classList.add('hidden');
  }

  async function viewReceiptDetail(invoiceId) {
    try {
      const inv = await apiFetch(`${API.billing.base}/${invoiceId}`);
      showReceiptModal(inv);
    } catch (err) {
      showToast(err.message || 'Could not load receipt', 'error');
    }
  }

  async function lookupReceipt() {
    const input = document.getElementById('receiptLookupInput');
    const code = (input?.value || '').trim();
    if (!code) {
      showToast('Enter a receipt number to search.', 'info');
      return;
    }
    try {
      const inv = await apiFetch(`${API.billing.receipt}/${encodeURIComponent(code)}`);
      showReceiptModal(inv);
    } catch (err) {
      showToast(err.message || 'Receipt not found', 'error');
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
      b.classList.toggle('text-stone-300', !active);
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
      openLoginGateway('login', 'patient');
      return;
    }
    const comment = document.getElementById('feedbackComment').value;
    const rating = state.selectedRating;
    const tags = state.selectedTags;
    const docVal = document.getElementById('feedbackDoctorSelect')?.value;
    const doctorId = docVal ? parseInt(docVal, 10) : null;

    try {
      const data = await apiFetch(API.feedback.submit, {
        method: 'POST',
        body: {
          rating: rating,
          comment_text: comment,
          tags: tags,
          doctor_id: Number.isFinite(doctorId) ? doctorId : null,
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
          sentLabel === 'negative' ? 'bg-rose-100 text-rose-800' : 'bg-stone-100 text-stone-800';

        resBox.innerHTML = `
          <div class="flex justify-between items-center mb-1 gap-2">
            <span class="font-bold text-stone-800">Sentiment Analysis</span>
            <span class="pill ${badgeColor}">${escapeHTML(sentLabel)}</span>
          </div>
          <div class="text-[11px] text-stone-600">
            Score: <strong>${sentScore}</strong>
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
      const hasData = total > 0;
      const avg = hasData ? Number(data.avg_rating ?? data.average_rating ?? 0) : 0;

      // Handle both router schema { positive_pct, negative_pct } and legacy distribution object
      const posPct = !hasData ? 0 :
        (data.positive_pct !== undefined ? data.positive_pct :
        (data.sentiment_distribution ? (data.sentiment_distribution.positive / (total || 1)) * 100 : 0));
      const negPct = !hasData ? 0 :
        (data.negative_pct !== undefined ? data.negative_pct :
        (data.sentiment_distribution ? (data.sentiment_distribution.negative / (total || 1)) * 100 : 0));
      const neuPct = hasData ? Math.max(0, Math.round(100 - posPct - negPct)) : 0;

      // No submissions yet: show no numbers rather than values that look real.
      const nss = hasData ? Math.round(posPct - negPct) : null;

      if (nssEl) {
        nssEl.textContent = nss === null ? 'N/A' : (nss >= 0 ? '+' : '') + nss.toFixed(1);
        nssEl.className = `stat-value font-mono tracking-tight ${nss === null ? 'text-stone-400' : nss >= 0 ? 'text-brand-600' : 'text-rose-600'}`;
      }
      if (nssStatus) {
        nssStatus.textContent = nss === null ? 'No feedback yet' :
          nss >= 50 ? 'Excellent Experience' : nss >= 0 ? 'Good / Neutral' : 'Requires Attention';
      }
      if (avgRating) avgRating.textContent = nss === null ? 'N/A' : avg.toFixed(1);
      if (totalRev) totalRev.textContent = total;

      const starsVis = document.getElementById('statStarsVisual');
      if (starsVis) {
        starsVis.classList.toggle('hidden', nss === null);
        if (nss !== null) {
          const filled = Math.max(0, Math.min(5, Math.round(avg)));
          starsVis.textContent = '\u2605'.repeat(filled) + '\u2606'.repeat(5 - filled);
        }
      }

      // Distribution bars
      document.getElementById('distPositivePercent').textContent = `${Math.round(posPct)}%`;
      document.getElementById('barPositive').style.width = `${Math.round(posPct)}%`;

      document.getElementById('distNeutralPercent').textContent = `${neuPct}%`;
      document.getElementById('barNeutral').style.width = `${neuPct}%`;

      document.getElementById('distNegativePercent').textContent = `${Math.round(negPct)}%`;
      document.getElementById('barNegative').style.width = `${Math.round(negPct)}%`;

      const formatFeedbackDate = (raw) => {
        if (!raw) return '';
        const d = new Date(raw);
        return Number.isNaN(d.getTime())
          ? escapeHTML(raw)
          : escapeHTML(d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }));
      };

      // Critical alerts: check data.critical_alerts or filter from data.items
      const rawAlerts = data.critical_alerts ||
        (data.items ? data.items.filter(i => i.flagged_critical) : []);
      const criticalCount = data.critical_count !== undefined ? data.critical_count : rawAlerts.length;

      const badge = document.getElementById('criticalAlertsBadge');
      if (badge) badge.textContent = `${criticalCount} Active`;

      const list = document.getElementById('criticalAlertsList');
      if (list) {
        if (rawAlerts.length === 0) {
          list.innerHTML = '<p class="text-stone-600 py-6 text-center">No critical negative complaints detected.</p>';
        } else {
          list.innerHTML = rawAlerts.map(a => {
            const r = a.rating ?? 1;
            const score = typeof a.sentiment_score === 'number' ? a.sentiment_score.toFixed(2) : '-';
            const comment = escapeHTML(a.comment ?? a.comment_text ?? '');
            const docMeta = a.doctor_name ? ` &bull; ${escapeHTML(a.doctor_name)}` : '';
            const dt = formatFeedbackDate(a.created_at);
            return `
              <div class="p-3 rounded-xl bg-red-50 border border-red-200">
                <div class="flex justify-between items-center text-red-700 font-bold mb-1 gap-2">
                  <span class="tabular-nums">Rating: ${r} / 5 &bull; Score: ${score}</span>
                  <span class="pill bg-red-200 text-red-900 shrink-0">URGENT</span>
                </div>
                <p class="text-stone-800 break-words leading-relaxed">"${comment}"</p>
                <span class="text-[11px] text-stone-600 mt-1 block">Anonymous Patient${docMeta}${dt ? ` &bull; ${dt}` : ''}</span>
              </div>
            `;
          }).join('');
        }
      }

      // Written feedback list (anonymized patient identity)
      const items = data.items || [];
      const writtenCount = document.getElementById('writtenFeedbackCount');
      if (writtenCount) writtenCount.textContent = `${items.length} Shown`;

      const writtenList = document.getElementById('writtenFeedbackList');
      if (writtenList) {
        if (items.length === 0) {
          writtenList.innerHTML = '<p class="text-stone-600 py-6 text-center">No written feedback submitted yet. Patient comments appear here without identifying details.</p>';
        } else {
          const sentimentMeta = {
            positive: { label: 'Positive', cls: 'bg-brand-100 text-brand-800 border border-brand-200/70' },
            negative: { label: 'Negative', cls: 'bg-rose-100 text-rose-800 border border-rose-200/70' },
            neutral: { label: 'Neutral', cls: 'bg-stone-200 text-stone-800 border border-stone-300/70' },
          };
          writtenList.innerHTML = items.map(item => {
            const r = item.rating ?? 0;
            const sent = sentimentMeta[item.sentiment_label] || sentimentMeta.neutral;
            const comment = escapeHTML(item.comment ?? item.comment_text ?? '');
            const scopeLabel = item.doctor_name ? escapeHTML(item.doctor_name) : 'General Clinic';
            const dt = formatFeedbackDate(item.created_at);
            const tagsHtml = Array.isArray(item.tags) && item.tags.length > 0
              ? `<div class="flex flex-wrap gap-1.5 mt-2">${item.tags.map(t => `<span class="px-2 py-0.5 rounded-full bg-white border border-stone-200 text-stone-700 text-[11px] font-medium">${escapeHTML(t)}</span>`).join('')}</div>`
              : '';
            const urgentBadge = item.flagged_critical
              ? '<span class="pill bg-red-100 text-red-800 border border-red-200/80 uppercase text-[10px]">Urgent</span>'
              : '';
            return `
              <article class="p-3.5 rounded-xl bg-stone-50/80 border border-stone-200/90">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <div class="flex items-center gap-2 min-w-0">
                    <span class="font-semibold text-stone-900">Anonymous Patient</span>
                    <span class="text-stone-600 font-medium tabular-nums" aria-label="Rated ${r} out of 5"><span class="text-amber-600" aria-hidden="true">&#9733;</span> ${r}/5</span>
                  </div>
                  <div class="flex items-center gap-1.5 shrink-0">
                    <span class="pill ${sent.cls}">${sent.label}</span>
                    ${urgentBadge}
                  </div>
                </div>
                <p class="text-sm text-stone-800 leading-relaxed break-words mt-2">${comment}</p>
                ${tagsHtml}
                <div class="text-[11px] text-stone-600 mt-2 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span>${scopeLabel}</span>
                  ${dt ? `<span aria-hidden="true">&bull;</span><span>${dt}</span>` : ''}
                </div>
              </article>
            `;
          }).join('');
        }
      }
    } catch (err) {
      console.warn('Failed to load analytics:', err);
      const writtenList = document.getElementById('writtenFeedbackList');
      if (writtenList) {
        writtenList.innerHTML = '<p class="text-rose-700 py-6 text-center font-medium">Unable to load written feedback. Refresh metrics to try again.</p>';
      }
    }
  }

  // Admin User Management
  function toggleAdminUserRoleFields() {
    const role = document.getElementById('adminUserRole')?.value || 'staff';
    const docFields = document.getElementById('adminUserDoctorFields');
    if (docFields) docFields.classList.toggle('hidden', role !== 'doctor');
  }

  async function loadAdminUsers() {
    const tbody = document.getElementById('adminUsersList');
    if (!tbody || !state.user || state.user.role !== 'admin') return;
    try {
      const users = await apiFetch(API.admin.users);
      if (!users || users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="py-6 text-center text-stone-600">No accounts found.</td></tr>';
        return;
      }
      const roleColors = {
        admin: 'bg-rose-100 text-rose-800',
        doctor: 'bg-violet-100 text-violet-800',
        staff: 'bg-amber-100 text-amber-800',
        patient: 'bg-sky-100 text-sky-800',
      };
      tbody.innerHTML = users.map(u => {
        const badge = roleColors[u.role] || 'bg-stone-100 text-stone-700';
        const isPending = u.is_approved === false;
        const statusPill = isPending
          ? '<span class="pill bg-amber-100 text-amber-900 uppercase text-[10px] font-bold">Pending</span>'
          : '<span class="pill bg-emerald-100 text-emerald-800 uppercase text-[10px] font-bold">Active</span>';
        const profileTag = u.patient_id ? `Patient #${u.patient_id}` : (u.doctor_id ? `Doctor #${u.doctor_id}` : `User #${u.id}`);
        const actions = isPending
          ? `<div class="inline-flex items-center gap-1.5">
              <button type="button" onclick="window.ClinicApp.approveAdminUser(${u.id})" class="btn btn-primary btn-sm text-xs">Approve</button>
              <button type="button" onclick="window.ClinicApp.rejectAdminUser(${u.id})" class="btn btn-outline btn-sm text-xs text-rose-700 border-rose-200 hover:bg-rose-50">Reject</button>
            </div>`
          : `<div class="inline-flex items-center gap-2">
              <span class="font-mono text-[11px] text-stone-500">${escapeHTML(profileTag)}</span>
              ${state.user && u.id !== state.user.id ? `<button type="button" onclick="window.ClinicApp.toggleAdminUserActive(${u.id})" class="btn btn-outline btn-sm text-xs text-rose-700 border-rose-200 hover:bg-rose-50">Deactivate</button>` : ''}
            </div>`;
        return `
          <tr class="border-b border-stone-100 ${isPending ? 'bg-amber-50/40' : ''}">
            <td class="py-2.5 pr-3 font-semibold text-stone-900">${escapeHTML(u.full_name)}</td>
            <td class="py-2.5 pr-3 text-stone-600">${escapeHTML(u.email)}</td>
            <td class="py-2.5 pr-3 whitespace-nowrap"><span class="pill ${badge} uppercase text-[10px] font-bold">${escapeHTML(u.role)}</span></td>
            <td class="py-2.5 pr-3 whitespace-nowrap">${statusPill}</td>
            <td class="py-2.5 text-right whitespace-nowrap">${actions}</td>
          </tr>
        `;
      }).join('');
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="5" class="py-4 text-center text-rose-600">${escapeHTML(err.message || 'Failed to load accounts')}</td></tr>`;
    }
  }

  async function approveAdminUser(userId) {
    try {
      const res = await apiFetch(`${API.admin.users}/${userId}/approve`, { method: 'POST' });
      showToast(`Approved ${res.user.full_name} (${res.user.role})`, 'success');
      loadAdminUsers();
      if (res.user.role === 'doctor') loadDoctors();
    } catch (err) {
      showToast(err.message || 'Failed to approve user', 'error');
    }
  }

  async function rejectAdminUser(userId) {
    try {
      await apiFetch(`${API.admin.users}/${userId}`, { method: 'DELETE' });
      showToast('Pending request removed', 'info');
      loadAdminUsers();
    } catch (err) {
      showToast(err.message || 'Failed to reject request', 'error');
    }
  }

  async function toggleAdminUserActive(userId) {
    try {
      const res = await apiFetch(`${API.admin.users}/${userId}/toggle-active`, { method: 'POST' });
      const active = res.user && res.user.is_approved;
      showToast(`${res.user.full_name} ${active ? 'activated' : 'deactivated'}`, 'info');
      loadAdminUsers();
      if (res.user && res.user.role === 'doctor') loadDoctors();
    } catch (err) {
      showToast(err.message || 'Failed to update account status', 'error');
    }
  }

  async function toggleDoctorAvailability() {
    if (!state.user || state.user.role !== 'doctor' || !state.user.doctor_profile) return;
    const nextAvail = state.user.doctor_profile.is_available === false;
    try {
      const updated = await apiFetch(API.auth.profile, {
        method: 'PUT',
        body: { is_available: nextAvail },
      });
      state.user = updated;
      localStorage.setItem('user_profile', JSON.stringify(updated));
      updateUserUI();
      loadDoctors();
      showToast(nextAvail ? 'You are now listed as accepting patients.' : 'You are now paused from new bookings.', 'info');
    } catch (err) {
      showToast(err.message || 'Failed to update availability', 'error');
    }
  }

  function showDoctorProfileModal() {
    if (!state.user || state.user.role !== 'doctor') return;
    const modal = document.getElementById('doctorProfileModal');
    if (!modal) return;
    const prof = state.user.doctor_profile || {};
    const nameEl = document.getElementById('docEditFullName');
    const phoneEl = document.getElementById('docEditPhone');
    const specEl = document.getElementById('docEditSpec');
    const roomEl = document.getElementById('docEditRoom');
    const feeEl = document.getElementById('docEditFee');
    if (nameEl) nameEl.value = state.user.full_name || '';
    if (phoneEl) phoneEl.value = formatPHPhone(state.user.phone || '');
    if (specEl) specEl.value = prof.specialization || '';
    if (roomEl) roomEl.value = prof.room_number || '';
    if (feeEl) feeEl.value = prof.consultation_fee != null ? String(prof.consultation_fee) : '500.00';
    modal.classList.remove('hidden');
  }

  function hideDoctorProfileModal() {
    const modal = document.getElementById('doctorProfileModal');
    if (modal) modal.classList.add('hidden');
  }

  async function handleDoctorProfileUpdate(e) {
    e.preventDefault();
    const btn = document.getElementById('saveDoctorProfileBtn');
    if (btn) btn.disabled = true;
    try {
      const updated = await apiFetch(API.auth.profile, {
        method: 'PUT',
        body: {
          full_name: document.getElementById('docEditFullName').value.trim(),
          phone: document.getElementById('docEditPhone').value.trim() || null,
          specialization: document.getElementById('docEditSpec').value.trim(),
          room_number: document.getElementById('docEditRoom').value.trim(),
          consultation_fee: parseFloat(document.getElementById('docEditFee').value) || 0,
        },
      });
      state.user = updated;
      localStorage.setItem('user_profile', JSON.stringify(updated));
      hideDoctorProfileModal();
      updateUserUI();
      loadDoctors();
      showToast('Practice profile updated', 'success');
    } catch (err) {
      showToast(err.message || 'Update failed', 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function createAdminUser(e) {
    e.preventDefault();
    const errEl = document.getElementById('adminUserErrorMsg');
    if (errEl) errEl.classList.add('hidden');
    const submitBtn = document.getElementById('adminUserSubmitBtn');
    if (submitBtn) submitBtn.disabled = true;

    const role = document.getElementById('adminUserRole').value;
    const payload = {
      role,
      full_name: document.getElementById('adminUserFullName').value.trim(),
      email: document.getElementById('adminUserEmail').value.trim(),
      password: document.getElementById('adminUserPassword').value,
      phone: document.getElementById('adminUserPhone')?.value.trim() || null,
    };

    if (role === 'doctor') {
      payload.specialization = document.getElementById('adminUserSpec')?.value.trim() || null;
      payload.license_number = document.getElementById('adminUserLicense')?.value.trim() || null;
      payload.room_number = document.getElementById('adminUserRoom')?.value.trim() || null;
      const feeVal = parseFloat(document.getElementById('adminUserFee')?.value);
      if (Number.isFinite(feeVal)) payload.consultation_fee = feeVal;
    }

    try {
      const res = await apiFetch(API.admin.users, {
        method: 'POST',
        body: payload,
      });
      document.getElementById('adminCreateUserForm')?.reset();
      toggleAdminUserRoleFields();
      showToast(`Created ${res.user.role} account for ${res.user.full_name}`, 'success');
      loadAdminUsers();
      if (role === 'doctor') loadDoctors();
    } catch (err) {
      if (errEl) {
        errEl.textContent = err.message || 'Failed to create account.';
        errEl.classList.remove('hidden');
      } else {
        showToast(err.message, 'error');
      }
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  // Live Chat Widget
  const pendingOptimisticMessages = new Set();

  function updateChatGuestUI(remaining) {
    const pill = document.getElementById('chatGuestPill');
    const countEl = document.getElementById('chatGuestRemaining');
    const banner = document.getElementById('chatGuestBanner');
    const input = document.getElementById('chatInput');
    const sendBtn = document.getElementById('chatSendBtn');

    if (state.user) {
      if (pill) pill.classList.add('hidden');
      if (banner) banner.classList.add('hidden');
      if (input) {
        input.disabled = false;
        input.placeholder = 'Ask a question or type a message...';
      }
      if (sendBtn) sendBtn.disabled = false;
      return;
    }

    if (pill) pill.classList.remove('hidden');
    if (typeof remaining === 'number') {
      state.guestChatRemaining = Math.max(0, remaining);
    }
    if (countEl) countEl.textContent = state.guestChatRemaining;

    if (state.guestChatRemaining <= 0) {
      if (banner) banner.classList.remove('hidden');
      if (input) {
        input.disabled = true;
        input.placeholder = 'Guest limit reached (5/5). Please sign in...';
      }
      if (sendBtn) sendBtn.disabled = true;
    } else {
      if (banner) banner.classList.add('hidden');
      if (input) {
        input.disabled = false;
        input.placeholder = 'Ask a question or type a message...';
      }
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  async function checkChatGuestStatus() {
    if (state.user) {
      updateChatGuestUI(null);
      return;
    }
    try {
      const res = await apiFetch(`${API.chat.status}/${state.chatSessionId}`);
      if (res && typeof res.remaining === 'number') {
        updateChatGuestUI(res.remaining);
      }
    } catch (_) {
      updateChatGuestUI(state.guestChatRemaining);
    }
  }

  function formatChatTime(dateStr) {
    if (!dateStr) {
      const d = new Date();
      return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }
    try {
      const d = new Date(dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T'));
      return isNaN(d) ? 'Just now' : d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    } catch (_) {
      return 'Just now';
    }
  }

  function toggleChat() {
    const win = document.getElementById('chatWindow');
    const launcher = document.getElementById('chatLauncher');
    if (!win) return;
    const isHidden = win.classList.contains('hidden');
    if (isHidden) {
      win.classList.remove('hidden');
      if (launcher) launcher.setAttribute('aria-expanded', 'true');
      checkChatGuestStatus();
      loadChatHistory(); // load via REST before WS — works regardless of WS auth timing
      if (!state.chatWs || state.chatWs.readyState !== WebSocket.OPEN) {
        initChatWebSocket();
      }
      const chatInput = document.getElementById('chatInput');
      if (chatInput && !chatInput.disabled) chatInput.focus();
    } else {
      win.classList.add('hidden');
      if (launcher) launcher.setAttribute('aria-expanded', 'false');
    }
  }

  async function loadChatHistory() {
    if (!state.user) return; // not logged in — keep static greeting
    try {
      const history = await apiFetch(`${API.chat.history}/${state.chatSessionId}`);
      if (Array.isArray(history) && history.length) {
        const box = document.getElementById('chatMessages');
        if (box) box.innerHTML = '';
        history.forEach(appendChatMessage);
      }
    } catch (_) { /* no history or not authenticated — keep static greeting */ }
  }

  async function loadStaffChatInbox() {
    const list = document.getElementById('staffChatInboxList');
    if (!list || !state.user || (state.user.role !== 'staff' && state.user.role !== 'admin')) return;
    try {
      const rows = await apiFetch(API.chat.sessionsSummary);
      if (!rows || rows.length === 0) {
        list.innerHTML = '<p class="text-stone-600 py-3 text-center">No active chat conversations yet.</p>';
        return;
      }
      list.innerHTML = rows.map(s => `
        <div class="p-2.5 rounded-xl bg-stone-50 border border-stone-200/80 flex items-center justify-between gap-2">
          <div class="min-w-0 flex-1">
            <span class="font-bold text-stone-900 block truncate">${escapeHTML(s.sender_name || 'Guest')} (${s.message_count})</span>
            <span class="text-[11px] text-stone-600 block truncate">${escapeHTML(s.last_message || '')}</span>
          </div>
          <button type="button" onclick="window.ClinicApp.openStaffChatSession('${escapeHTML(s.session_id)}')" class="btn btn-outline btn-sm shrink-0 text-xs">Join Chat</button>
        </div>
      `).join('');
    } catch (err) {
      list.innerHTML = `<p class="text-rose-600 py-3 text-center">${escapeHTML(err.message || 'Failed to load inbox')}</p>`;
    }
  }

  function openStaffChatSession(sessionId) {
    if (!sessionId) return;
    state.chatSessionId = sessionId;
    localStorage.setItem('chat_session_id', sessionId);
    const box = document.getElementById('chatMessages');
    if (box) box.innerHTML = '';
    if (state.chatWs) {
      state.chatWsIntentionalClose = true;
      try { state.chatWs.close(); } catch (_) {}
      state.chatWs = null;
    }
    const win = document.getElementById('chatWindow');
    if (win && win.classList.contains('hidden')) {
      toggleChat();
    } else {
      loadChatHistory();
      initChatWebSocket();
    }
  }

  function openLoginFromChat() {
    const win = document.getElementById('chatWindow');
    if (win && !win.classList.contains('hidden')) {
      toggleChat();
    }
    openLoginGateway('login', 'patient');
  }

  function initChatWebSocket() {
    if (state.chatWs && (state.chatWs.readyState === WebSocket.OPEN || state.chatWs.readyState === WebSocket.CONNECTING)) {
      return;
    }
    state.chatWsIntentionalClose = false;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${API.chat.ws}/${state.chatSessionId}`;

    try {
      state.chatWs = new WebSocket(wsUrl);

      state.chatWs.onopen = () => {
        state.chatWsRetryMs = 1000;
      };

      state.chatWs.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          const textKey = payload.message || payload.message_text || '';
          const isBot = payload.is_bot_reply || payload.role === 'bot';
          // The server echoes my own message before the bot answers; the echo
          // must not clear the typing indicator or it flashes and vanishes.
          const isMyEcho = !isBot && pendingOptimisticMessages.has(textKey);
          if (!isMyEcho) {
            hideTypingIndicator();
          }
          appendChatMessage(payload);
          if (payload.limit_reached) {
            updateChatGuestUI(0);
            showToast('Guest chat limit reached (5 messages). Sign in to continue.', 'warning');
          } else if (typeof payload.guest_remaining === 'number') {
            updateChatGuestUI(payload.guest_remaining);
          }
        } catch (err) {
          console.warn('Chat parse error:', err);
        }
      };

      state.chatWs.onclose = () => {
        hideTypingIndicator();
        if (state.chatWsIntentionalClose) return;
        const win = document.getElementById('chatWindow');
        if (win && !win.classList.contains('hidden')) {
          setTimeout(initChatWebSocket, state.chatWsRetryMs);
          state.chatWsRetryMs = Math.min(state.chatWsRetryMs * 2, 15000);
        }
      };
    } catch (err) {
      console.warn('WebSocket init failed:', err);
    }
  }

  function setChatSendingState(isSending) {
    const btn = document.getElementById('chatSendBtn');
    const icon = document.getElementById('chatSendIcon');
    const spinner = document.getElementById('chatSendSpinner');
    const text = document.getElementById('chatSendText');
    if (!btn) return;
    btn.disabled = isSending;
    if (isSending) {
      btn.classList.add('opacity-75', 'cursor-not-allowed');
      if (icon) icon.classList.add('hidden');
      if (spinner) spinner.classList.remove('hidden');
      if (text) text.textContent = 'Thinking...';
    } else {
      btn.classList.remove('opacity-75', 'cursor-not-allowed');
      if (icon) icon.classList.remove('hidden');
      if (spinner) spinner.classList.add('hidden');
      if (text) text.textContent = 'Send';
    }
  }

  function showTypingIndicator() {
    const bubble = document.getElementById('chatTypingBubble');
    if (bubble) return;
    const box = document.getElementById('chatMessages');
    if (!box) return;

    const div = document.createElement('div');
    div.id = 'chatTypingBubble';
    div.className = 'flex items-start gap-2 justify-start';
    div.innerHTML = `
      ${ICONS.bot}
      <div class="bg-stone-100 text-stone-600 px-3.5 py-2.5 rounded-2xl rounded-tl-none flex items-center gap-1.5 shadow-sm">
        <span class="w-1.5 h-1.5 rounded-full bg-stone-500 chat-dot inline-block"></span>
        <span class="w-1.5 h-1.5 rounded-full bg-stone-500 chat-dot inline-block"></span>
        <span class="w-1.5 h-1.5 rounded-full bg-stone-500 chat-dot inline-block"></span>
        <span class="text-[10px] text-stone-400 font-medium ml-1">Thinking...</span>
      </div>
    `;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    setChatSendingState(true);
  }

  function hideTypingIndicator() {
    const bubble = document.getElementById('chatTypingBubble');
    if (bubble) bubble.remove();
    setChatSendingState(false);
  }

  function appendChatMessage(msg) {
    const box = document.getElementById('chatMessages');
    if (!box) return;

    const isBot = msg.is_bot_reply || msg.role === 'bot' || msg.sender === 'Clinic Assistant Bot';
    const isMe = !isBot && (
      msg.is_optimistic ||
      (!state.user && (msg.sender === 'Guest' || msg.sender_name === 'Guest')) ||
      (state.user && (msg.sender === state.user.full_name || msg.sender_name === state.user.full_name))
    );

    // Deduplicate optimistic echo
    const textKey = msg.message || msg.message_text || '';
    if (!isBot && !msg.is_optimistic && pendingOptimisticMessages.has(textKey)) {
      pendingOptimisticMessages.delete(textKey);
      return;
    }

    const safeText = escapeHTML(textKey);
    const safeSender = escapeHTML(msg.sender || msg.sender_name || 'Staff');
    const timeStr = formatChatTime(msg.created_at);

    const div = document.createElement('div');
    div.className = `flex items-start gap-2 ${isMe ? 'justify-end' : 'justify-start'}`;

    if (isBot) {
      hideTypingIndicator();
      div.innerHTML = `
        ${ICONS.bot}
        <div class="chat-bubble-content bg-stone-100 text-stone-800 p-3 rounded-2xl rounded-tl-none max-w-[85%] leading-relaxed group relative shadow-sm" data-raw-text="${safeText}">
          <div class="flex items-center justify-between gap-3 mb-1">
            <span class="text-[10px] font-bold text-stone-500">Clinic Virtual Bot</span>
            <button type="button" onclick="window.ClinicApp.copyChatText(this)" class="opacity-60 hover:opacity-100 transition-opacity p-0.5 rounded text-stone-500 hover:text-stone-900" title="Copy response" aria-label="Copy response">
              <svg class="icon w-3.5 h-3.5" aria-hidden="true"><use href="#i-copy"/></svg>
            </button>
          </div>
          <div class="whitespace-pre-wrap">${safeText}</div>
          <span class="text-[9px] text-stone-400 block mt-1 text-right tabular-nums">${timeStr}</span>
        </div>
      `;
    } else if (isMe) {
      div.innerHTML = `
        <div class="bg-brand-600 text-white p-3 rounded-2xl rounded-tr-none max-w-[85%] leading-relaxed shadow-sm">
          <div class="whitespace-pre-wrap">${safeText}</div>
          <span class="text-[9px] text-brand-200 block mt-1 text-right tabular-nums">${timeStr}</span>
        </div>
        ${ICONS.user}
      `;
    } else {
      div.innerHTML = `
        ${ICONS.staff}
        <div class="bg-stone-100 text-stone-800 p-3 rounded-2xl rounded-tl-none max-w-[85%] leading-relaxed shadow-sm">
          <span class="text-[10px] font-bold text-stone-500 block mb-0.5">${safeSender}</span>
          <div class="whitespace-pre-wrap">${safeText}</div>
          <span class="text-[9px] text-stone-400 block mt-1 text-right tabular-nums">${timeStr}</span>
        </div>
      `;
    }

    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  async function copyChatText(btn) {
    const bubble = btn.closest('.chat-bubble-content');
    if (!bubble) return;
    const textToCopy = bubble.getAttribute('data-raw-text') || bubble.innerText.trim();
    try {
      await navigator.clipboard.writeText(textToCopy);
      btn.innerHTML = `<svg class="icon w-3.5 h-3.5 text-brand-600" aria-hidden="true"><use href="#i-check"/></svg>`;
      setTimeout(() => {
        btn.innerHTML = `<svg class="icon w-3.5 h-3.5" aria-hidden="true"><use href="#i-copy"/></svg>`;
      }, 2000);
    } catch (_) {
      showToast('Copied to clipboard', 'info');
    }
  }

  function clearChat() {
    if (!confirm('Clear this chat conversation?')) return;
    if (state.user) {
      // Signed in: a fresh session starts a clean transcript bound to the account.
      state.chatSessionId = crypto.randomUUID();
      localStorage.setItem('chat_session_id', state.chatSessionId);
      state.guestChatRemaining = 5;
      updateChatGuestUI(5);
      if (state.chatWs) {
        try { state.chatWs.close(); } catch (_) {}
        initChatWebSocket();
      }
    }
    // Guests keep their session id: clearing the transcript must not reset the
    // 5-message limit, so this only wipes the visible conversation.
    hideTypingIndicator();
    const box = document.getElementById('chatMessages');
    if (box) {
      box.innerHTML = `
        <div class="flex items-start gap-2">
          ${ICONS.bot}
          <div class="bg-stone-100 text-stone-800 p-3 rounded-2xl rounded-tl-none max-w-[85%] leading-relaxed">
            Welcome to City Health Clinic. I am your virtual assistant. Ask me about opening hours, booking appointments, specialists, general health facts, or our location. (Pwede rin po kayong magtanong sa Tagalog!)
          </div>
        </div>
      `;
    }
    showToast('Conversation cleared', 'info');
  }

  async function sendChatMessage(text) {
    if (!text || !text.trim()) return;
    const msg = text.trim();

    if (!state.user && state.guestChatRemaining <= 0) {
      showToast('Guest chat limit reached (5/5). Please sign in to continue chatting.', 'warning');
      updateChatGuestUI(0);
      return;
    }

    // 1. Optimistic rendering: Render user bubble immediately
    pendingOptimisticMessages.add(msg);
    const box = document.getElementById('chatMessages');
    const prevCount = box ? box.children.length : 0;
    appendChatMessage({
      sender: state.user ? state.user.full_name : 'You',
      sender_name: state.user ? state.user.full_name : 'You',
      message: msg,
      message_text: msg,
      role: state.user ? state.user.role : 'patient',
      is_bot_reply: false,
      is_optimistic: true,
      created_at: null,
    });
    const optimisticBubble = (box && box.children.length > prevCount) ? box.lastElementChild : null;

    // 2. Show in-stream typing indicator
    showTypingIndicator();

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
        pendingOptimisticMessages.delete(msg);
        hideTypingIndicator();
        if (res.bot_reply) {
          appendChatMessage({
            sender: 'Clinic Assistant Bot',
            role: 'bot',
            is_bot_reply: true,
            message: res.bot_reply.message || res.bot_reply.message_text,
            created_at: null,
          });
        }
        if (res.limit_reached) {
          updateChatGuestUI(0);
          showToast('Guest chat limit reached (5 messages). Sign in to continue.', 'warning');
        } else if (typeof res.guest_remaining === 'number') {
          updateChatGuestUI(res.guest_remaining);
        }
      } catch (err) {
        pendingOptimisticMessages.delete(msg);
        if (optimisticBubble) optimisticBubble.remove();
        hideTypingIndicator();
        if (err.message && (err.message.includes('Guest chat limit') || err.message.includes('429'))) {
          updateChatGuestUI(0);
          showToast(err.message, 'warning');
        } else {
          showToast(err.message.includes('authenticated')
            ? 'Please sign in to use live chat'
            : 'Chat service unavailable', 'error');
        }
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
    const receiptModal = document.getElementById('receiptModal');
    if (receiptModal && !receiptModal.classList.contains('hidden')) {
      hideReceiptModal();
      return;
    }
    const doctorModal = document.getElementById('doctorProfileModal');
    if (doctorModal && !doctorModal.classList.contains('hidden')) {
      hideDoctorProfileModal();
      return;
    }
    const profileModal = document.getElementById('profileModal');
    if (profileModal && !profileModal.classList.contains('hidden')) {
      hideProfileModal();
      return;
    }
    const chatWin = document.getElementById('chatWindow');
    if (chatWin && !chatWin.classList.contains('hidden')) {
      toggleChat();
    }
  });

  // PWA Support & Service Worker Registration
  let deferredInstallPrompt = null;
  const APP_BUILD_VERSION = '2.16.0';

  function initPWA() {
    // 0. Automatically purge outdated CacheStorage when build version bumps
    if (window.caches && localStorage.getItem('app_build_version') !== APP_BUILD_VERSION) {
      caches.keys().then((names) => {
        return Promise.all(names.map((name) => caches.delete(name)));
      }).then(() => {
        localStorage.setItem('app_build_version', APP_BUILD_VERSION);
      });
    }

    // 1. Register Service Worker for offline caching & single-reload update
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js', { scope: '/' })
          .then((reg) => {
            console.log('PWA: ServiceWorker registered successfully with scope:', reg.scope);
            reg.update();
          })
          .catch((err) => {
            console.warn('PWA: ServiceWorker registration failed:', err);
          });
      });

      // Reload once when an updated service worker takes control (skipWaiting + clients.claim)
      const hadExistingController = Boolean(navigator.serviceWorker.controller);
      let refreshing = false;
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (hadExistingController && !refreshing) {
          refreshing = true;
          window.location.reload();
        }
      });
    }

    // 2. Capture install prompt on Android Chrome & desktop browsers
    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredInstallPrompt = e;
      const banner = document.getElementById('pwaInstallBanner');
      const headerBtn = document.getElementById('headerInstallBtn');
      if (banner && sessionStorage.getItem('pwa_dismissed') !== 'true') {
        banner.classList.remove('hidden');
      }
      // One install entry point at a time: the header button only when the
      // banner is dismissed or unavailable.
      if (headerBtn && (!banner || sessionStorage.getItem('pwa_dismissed') === 'true')) {
        headerBtn.classList.remove('hidden');
      }
    });

    // 2b. Touch browsers (e.g. Safari/Kiwi) without beforeinstallprompt: show synchronously at boot to avoid post-load shift
    const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    const isTouchBrowser = window.matchMedia('(pointer: coarse)').matches;
    if (!isStandalone && isTouchBrowser && sessionStorage.getItem('pwa_dismissed') !== 'true') {
      const banner = document.getElementById('pwaInstallBanner');
      if (banner) banner.classList.remove('hidden');
    }

    // 3. Listen for successful installation
    window.addEventListener('appinstalled', () => {
      deferredInstallPrompt = null;
      const banner = document.getElementById('pwaInstallBanner');
      const headerBtn = document.getElementById('headerInstallBtn');
      if (banner) banner.classList.add('hidden');
      if (headerBtn) headerBtn.classList.add('hidden');
      showToast('ClinicCare successfully installed on your device!', 'success');
    });

    // 4. Offline & Online connectivity monitor
    function updateOnlineStatus() {
      const offlineBar = document.getElementById('offlineStatusBar');
      if (!offlineBar) return;
      if (navigator.onLine) {
        offlineBar.classList.add('hidden');
      } else {
        offlineBar.classList.remove('hidden');
      }
    }

    window.addEventListener('online', () => {
      updateOnlineStatus();
      showToast('Internet connection restored.', 'success');
      if (!state.queueWs || state.queueWs.readyState !== WebSocket.OPEN) {
        initQueueWebSocket();
      }
    });

    window.addEventListener('offline', () => {
      updateOnlineStatus();
      showToast('Offline Mode: Displaying cached data.', 'warning');
    });

    if (!navigator.onLine) {
      updateOnlineStatus();
    }
  }

  function installPWA() {
    if (!deferredInstallPrompt) {
      showToast('In Kiwi/browser: tap menu (⋮) at top right, then select "Add to Home screen" or "Install app".', 'info');
      return;
    }
    deferredInstallPrompt.prompt();
    deferredInstallPrompt.userChoice.then((choiceResult) => {
      if (choiceResult && choiceResult.outcome === 'accepted') {
        showToast('Installing ClinicCare...', 'info');
      }
      deferredInstallPrompt = null;
      const banner = document.getElementById('pwaInstallBanner');
      const headerBtn = document.getElementById('headerInstallBtn');
      if (banner) banner.classList.add('hidden');
      if (headerBtn) headerBtn.classList.add('hidden');
    });
  }

  function dismissPWABanner() {
    const banner = document.getElementById('pwaInstallBanner');
    if (banner) banner.classList.add('hidden');
    sessionStorage.setItem('pwa_dismissed', 'true');
    // Keep one install entry point alive after dismissal.
    const headerBtn = document.getElementById('headerInstallBtn');
    if (headerBtn && deferredInstallPrompt) headerBtn.classList.remove('hidden');
  }

  // Hide skeleton immediately before revealing the active portal so content never jumps
  function dismissAppSkeleton() {
    const skeleton = document.getElementById('appSkeletonLoader');
    if (!skeleton || skeleton.classList.contains('hidden')) return;
    skeleton.classList.add('hidden');
    skeleton.setAttribute('aria-hidden', 'true');
  }

  // Initialize on page load
  async function init() {
    initPWA();

    const roleMap = { patient: 'patient', doctor: 'doctor', staff: 'staff', admin: 'analytics' };
    let bootSettled = false;

    const revealInitialPortal = (targetTab) => {
      if (bootSettled) return;
      bootSettled = true;
      dismissAppSkeleton();
      updateUserUI();
      switchTab(targetTab);
    };

    // Fallback safety timeout: ensure skeleton clears within 2s even if offline/slow
    const skeletonFallbackTimer = setTimeout(() => {
      const optimisticTab = (state.user && state.user.role && roleMap[state.user.role]) || 'login';
      revealInitialPortal(optimisticTab);
    }, 2000);

    loadDoctors();
    fetchQueueStatus();
    initQueueWebSocket();

    // Inspect deployment status: reveal demo logins only in DEMO_MODE, and
    // show First-Run Administrator Setup when no admin exists yet.
    fetch(API.auth.setupStatus).then(r => r.json()).then(s => {
      if (!s) return;
      if (s.demo_mode) {
        const row = document.getElementById('demoLoginRow');
        if (row) row.classList.remove('hidden');
      }
      const setupModal = document.getElementById('setupAdminModal');
      if (setupModal) {
        setupModal.classList.toggle('hidden', Boolean(s.initialized));
      }
    }).catch(() => {});

    // Pre-connect chat websocket when hovering or touching launcher
    const chatLauncher = document.getElementById('chatLauncher');
    if (chatLauncher) {
      chatLauncher.addEventListener('mouseenter', initChatWebSocket, { once: true });
      chatLauncher.addEventListener('touchstart', initChatWebSocket, { once: true, passive: true });
    }

    // Default appointment date to clinic today (UTC+8)
    const appDate = document.getElementById('appointmentDate');
    if (appDate) appDate.value = clinicTodayISO();

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
      clearTimeout(skeletonFallbackTimer);
      if (bootSettled) {
        updateUserUI();
        switchTab(roleMap[me.role] || 'patient');
      } else {
        revealInitialPortal(roleMap[me.role] || 'patient');
      }
    } catch (_) {
      state.user = null;
      localStorage.removeItem('user_profile');
      clearTimeout(skeletonFallbackTimer);
      if (bootSettled) {
        updateUserUI();
        switchTab('login');
      } else {
        revealInitialPortal('login');
      }
    }
  }

  // Expose methods to window.ClinicApp
  window.ClinicApp = {
    switchTab,
    login,
    logout,
    switchLoginRole,
    switchPortalMode,
    handlePortalLogin,
    handlePortalRegister,
    showProfileModal,
    hideProfileModal,
    handleProfileUpdate,
    selectProfileGender,
    selectProfileBlood,
    toggleProfileAllergyChip,
    toggleProfileHistoryChip,
    fetchQueueStatus,
    loadMyActiveTicket,
    issueMyQueueTicket,
    loadPatientDirectory,
    onSelectPatientDropdown,
    loadActiveQueue,
    callNextPatient,
    callMyNextPatient,
    advanceTicketById,
    advanceServingTicket,
    formatPHPhone,
    switchWalkinMode,
    registerWalkin,
    submitAppointment,
    loadMyAppointments,
    cancelMyAppointment,
    loadMyPrescriptions,
    loadMyInvoices,
    loadStaffAppointments,
    checkInAppointment,
    updateAppointmentStatus,
    lookupPatients,
    selectFoundPatient,
    loadDoctorPendingApprovals,
    updateDoctorAppointmentStatus,
    loadDoctorSchedule,
    selectConsultationPatient,
    searchPatientEMR,
    addMedicationRow,
    generatePrescription,
    calculateBillPreview,
    createInvoice,
    loadBillingHistory,
    viewReceiptDetail,
    lookupReceipt,
    hideReceiptModal,
    setStarRating,
    toggleTag,
    submitFeedback,
    loadAnalytics,
    loadAdminUsers,
    approveAdminUser,
    rejectAdminUser,
    toggleAdminUserActive,
    toggleDoctorAvailability,
    showDoctorProfileModal,
    hideDoctorProfileModal,
    handleDoctorProfileUpdate,
    toggleAdminUserRoleFields,
    createAdminUser,
    handleSetupAdmin,
    toggleChat,
    clearChat,
    copyChatText,
    sendChatMessage,
    sendChatInput,
    sendQuickFaq,
    loadStaffChatInbox,
    openStaffChatSession,
    openLoginFromChat,
    showcaseSelectRole,
    showcaseOpenChat,
    demoLogin,
    openLoginGateway,
    selectRegGender,
    selectRegBlood,
    toggleRegAllergyChip,
    toggleRegHistoryChip,
    selectRegSpecialization,
    selectRegFee,
    installPWA,
    dismissPWABanner,
    dismissAppSkeleton,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();