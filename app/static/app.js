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
    if (performance.now() - t0 > 100) {
      document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;min-height:100vh;background:#121614;color:#ef4444;font-family:sans-serif;font-size:20px;font-weight:700;">Developer Tools Detected - Access Disabled</div>';
    }
    console.clear();
  }, 500);

  ['log', 'debug', 'info', 'warn', 'error'].forEach((m) => { console[m] = () => {}; });

  const API = {
    auth: {
      login: '/api/auth/login',
      register: '/api/auth/register',
      profile: '/api/auth/profile',
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
      status: '/api/chat/status',
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
    guestChatRemaining: 5,
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
      const nav = document.getElementById('portalNav');
      if (nav) nav.classList.add('hidden');
      const mobNav = document.getElementById('mobileBottomNav');
      if (mobNav) mobNav.classList.add('hidden');
      return;
    } else if (tabName !== 'patient') {
      showToast('Please sign in with authorized clinic credentials.', 'info');
      switchTab('login');
      return;
    }

    state.activeTab = tabName;
    const nav = document.getElementById('portalNav');
    if (nav) nav.classList.remove('hidden');

    const mobNav = document.getElementById('mobileBottomNav');
    if (mobNav) mobNav.classList.remove('hidden');

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
      loadDoctorSchedule();
      searchPatientEMR(1);
    } else if (tabName === 'staff') {
      fetchQueueStatus();
    } else if (tabName === 'analytics') {
      loadAnalytics();
    } else if (tabName === 'patient') {
      loadDoctors();
      fetchQueueStatus();
      if (state.user && state.user.role === 'patient') {
        renderPatientProfile(state.user);
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
    const manualLoginBtn = document.getElementById('manualLoginBtn');
    const registerNavBtn = document.getElementById('registerNavBtn');
    const logoutBtn = document.getElementById('logoutBtn');

    // Role-based portal tab visibility (Desktop & Mobile)
    const tabPatient = document.getElementById('tab-patient');
    const tabDoctor = document.getElementById('tab-doctor');
    const tabStaff = document.getElementById('tab-staff');
    const tabAnalytics = document.getElementById('tab-analytics');

    const mobTabPatient = document.getElementById('mob-tab-patient');
    const mobTabDoctor = document.getElementById('mob-tab-doctor');
    const mobTabStaff = document.getElementById('mob-tab-staff');
    const mobTabAnalytics = document.getElementById('mob-tab-analytics');

    const nav = document.getElementById('portalNav');
    const mobNav = document.getElementById('mobileBottomNav');

    if (state.user) {
      if (nav) nav.classList.remove('hidden');
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
      if (manualLoginBtn) manualLoginBtn.classList.add('hidden');
      if (registerNavBtn) registerNavBtn.classList.add('hidden');
      if (logoutBtn) logoutBtn.classList.remove('hidden');

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

      // Sync mobile bottom nav: only show when user has >1 accessible tab on mobile
      const visibleMobileTabs = [mobTabPatient, mobTabDoctor, mobTabStaff, mobTabAnalytics].filter(
        (t) => t && !t.classList.contains('hidden')
      );
      const shouldShowMobNav = state.activeTab !== 'login' && visibleMobileTabs.length > 1;
      if (mobNav) mobNav.classList.toggle('hidden', !shouldShowMobNav);

      const chatWrap = document.getElementById('chatLauncherWrap');
      if (chatWrap) {
        if (shouldShowMobNav) {
          chatWrap.classList.add('bottom-20');
          chatWrap.classList.remove('bottom-4');
        } else {
          chatWrap.classList.add('bottom-4');
          chatWrap.classList.remove('bottom-20');
        }
      }
    } else {
      if (state.activeTab === 'login') {
        if (nav) nav.classList.add('hidden');
        if (mobNav) mobNav.classList.add('hidden');
      } else {
        if (nav) nav.classList.remove('hidden');
        if (mobNav) mobNav.classList.remove('hidden');
      }

      const chatWrap = document.getElementById('chatLauncherWrap');
      if (chatWrap) {
        chatWrap.classList.add('bottom-4');
        chatWrap.classList.remove('bottom-20');
      }

      if (badge) badge.className = 'hidden';
      if (manualLoginBtn) manualLoginBtn.classList.remove('hidden');
      if (registerNavBtn) registerNavBtn.classList.remove('hidden');
      if (logoutBtn) logoutBtn.classList.add('hidden');

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
      const phone = prof.emergency_contact_phone || '';
      emergencyEl.textContent = (name || phone) ? `${name} (${phone})`.trim() : 'None recorded';
    }
    if (editBtn) editBtn.classList.remove('hidden');
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
      emailPlaceholder: 'patient@demo.com',
    },
    doctor: {
      title: 'Doctor Clinical Console',
      btnText: 'Sign In as Doctor',
      regBtnText: 'Register Doctor Account',
      icon: '#i-stethoscope',
      emailPlaceholder: 'doctor@demo.com',
    },
    staff: {
      title: 'Staff & Billing Desk',
      btnText: 'Sign In as Staff',
      regBtnText: 'Register Staff Account',
      icon: '#i-clipboard',
      emailPlaceholder: 'staff@demo.com',
    },
    admin: {
      title: 'Administrator Console',
      btnText: 'Sign In as Administrator',
      regBtnText: 'Register Administrator Account',
      icon: '#i-chart',
      emailPlaceholder: 'admin@demo.com',
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
    if (errEl) errEl.classList.add('hidden');

    if (currentPortalMode === 'register') {
      if (signInBtn) {
        signInBtn.className = 'flex-1 py-2 rounded-lg text-stone-500 hover:text-stone-900 transition-all font-semibold';
      }
      if (regBtn) {
        regBtn.className = 'flex-1 py-2 rounded-lg bg-white text-stone-900 shadow-sm font-bold transition-all';
      }
      if (loginForm) loginForm.classList.add('hidden');
      if (regForm) regForm.classList.remove('hidden');
    } else {
      if (signInBtn) {
        signInBtn.className = 'flex-1 py-2 rounded-lg bg-white text-stone-900 shadow-sm font-bold transition-all';
      }
      if (regBtn) {
        regBtn.className = 'flex-1 py-2 rounded-lg text-stone-500 hover:text-stone-900 transition-all font-semibold';
      }
      if (loginForm) loginForm.classList.remove('hidden');
      if (regForm) regForm.classList.add('hidden');
    }

    updatePortalHeader();
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

    if (btnTextEl) btnTextEl.textContent = meta.btnText;
    if (regBtnTextEl) regBtnTextEl.textContent = meta.regBtnText;
    if (emailInput) emailInput.placeholder = meta.emailPlaceholder;

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

  async function handlePortalRegister(e) {
    e.preventDefault();
    const errEl = document.getElementById('portalLoginErrorMsg');
    if (errEl) errEl.classList.add('hidden');
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
      payload.date_of_birth = document.getElementById('portalRegDob').value || null;
      payload.gender = document.getElementById('portalRegGender').value || null;
      payload.blood_group = document.getElementById('portalRegBloodGroup').value || null;
      payload.emergency_contact_name = document.getElementById('portalRegEmergencyName').value.trim() || null;
      payload.emergency_contact_phone = document.getElementById('portalRegEmergencyPhone').value.trim() || null;
      payload.allergies = document.getElementById('portalRegAllergies').value.trim() || null;
      payload.medical_history = document.getElementById('portalRegHistory').value.trim() || null;
    } else if (currentLoginRole === 'doctor') {
      payload.specialization = document.getElementById('portalRegSpecialization').value.trim() || 'General Medicine';
      payload.license_number = document.getElementById('portalRegLicense').value.trim() || 'MD-REG';
      payload.room_number = document.getElementById('portalRegRoom').value.trim() || 'Room 101';
      payload.consultation_fee = parseFloat(document.getElementById('portalRegFee').value) || 60.00;
    } else if (currentLoginRole === 'staff') {
      payload.department = document.getElementById('portalRegDepartment').value;
    } else if (currentLoginRole === 'admin') {
      payload.admin_title = document.getElementById('portalRegAdminTitle').value.trim() || 'Clinic Administrator';
    }

    try {
      const data = await apiFetch(API.auth.register, {
        method: 'POST',
        body: payload,
      });
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

  function showcaseSelectRole(role) {
    switchLoginRole(role);
    switchPortalMode('login');
    const loginCard = document.getElementById('loginGatewayCard');
    if (loginCard) {
      loginCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    const emailInput = document.getElementById('portalLoginEmail');
    if (emailInput) {
      setTimeout(() => emailInput.focus(), 350);
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

  function showProfileModal() {
    if (!state.user) {
      switchTab('login');
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
    if (phEl) phEl.value = state.user.phone || '';
    if (dobEl) {
      dobEl.value = prof.date_of_birth || '';
      dobEl.max = new Date().toISOString().split('T')[0];
    }
    if (emNameEl) emNameEl.value = prof.emergency_contact_name || '';
    if (emPhEl) emPhEl.value = prof.emergency_contact_phone || '';

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
        staffList.innerHTML = '<span class="text-xs text-stone-400">No patients waiting</span>';
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
      switchTab('login');
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
      switchTab('login');
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
      if (list) list.innerHTML = '<p class="text-xs text-stone-400 py-6 text-center">Sign in as a doctor to view a schedule.</p>';
      return;
    }
    const scheduleDate = dateInput && dateInput.value ? dateInput.value : new Date().toISOString().split('T')[0];
    if (dateInput && !dateInput.value) dateInput.value = scheduleDate;

    try {
      const data = await apiFetch(`${API.appointments.schedule}/${docId}?schedule_date=${scheduleDate}`);
      const list = document.getElementById('scheduleList');
      if (!list) return;

      if (!data || data.length === 0) {
        list.innerHTML = '<p class="text-xs text-stone-400 py-6 text-center">No appointments scheduled for this date.</p>';
        return;
      }

      list.innerHTML = data.map(app => `
        <div onclick="window.ClinicApp.selectConsultationPatient(${app.patient_id}, '${escapeHTML(app.patient_name || 'Patient')}')"
             class="schedule-patient-item p-3 rounded-xl bg-white hover:bg-brand-50/70 border border-stone-200/80 text-xs flex justify-between items-center gap-2 cursor-pointer transition-all shadow-sm hover:border-brand-300"
             data-patient-id="${app.patient_id}">
          <div class="min-w-0">
            <span class="font-bold text-stone-900 block truncate">${escapeHTML(app.time_slot)} - ${escapeHTML(app.patient_name)}</span>
            <span class="text-stone-500 text-[11px] block truncate">${escapeHTML(app.reason || 'General Consultation')}</span>
          </div>
          <span class="pill bg-brand-50 text-brand-700 uppercase shrink-0 border border-brand-200/60 text-[10px] font-bold">${escapeHTML(app.status)}</span>
        </div>
      `).join('');
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

  // EMR & Prescriptions
  async function searchPatientEMR(explicitId = null) {
    const idInput = document.getElementById('emrPatientId');
    const patientId = explicitId || (idInput ? parseInt(idInput.value, 10) : 1) || 1;

    try {
      const emr = await apiFetch(`${API.emr.patient}/${patientId}`);
      document.getElementById('emrName').textContent = emr.name || 'Sarah Connor';
      document.getElementById('emrDob').textContent = `${emr.dob || '1990-05-14'} / ${emr.gender || 'Female'}`;
      document.getElementById('emrBlood').textContent = emr.blood_group || 'O+';
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

      const rxList = document.getElementById('emrPrescriptionsList');
      if (rxList) {
        if (!emr.prescriptions || emr.prescriptions.length === 0) {
          rxList.innerHTML = '<p class="text-stone-400 py-2 text-center">No previous prescriptions on file.</p>';
        } else {
          rxList.innerHTML = emr.prescriptions.map(rx => `
            <div class="p-2.5 rounded-lg bg-white border border-stone-200 shadow-card">
              <div class="flex justify-between gap-2 font-semibold text-stone-800">
                <span class="truncate">Dx: ${escapeHTML(rx.diagnosis)}</span>
                <span class="text-[10px] text-stone-400 shrink-0">${escapeHTML(rx.created_at)}</span>
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
        <button type="button" onclick="this.closest('.med-row').remove()" class="text-red-500 hover:text-red-700 text-xs font-bold px-2 py-1">Remove</button>
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
          <span class="text-xs font-bold text-stone-800 block">Receipt: ${escapeHTML(res.receipt_number)}</span>
          <div class="flex justify-between items-center my-1 text-stone-600">
            <span>Total Paid (${escapeHTML(method.toUpperCase())}):</span>
            <span class="font-extrabold text-stone-900">$${res.total.toFixed(2)}</span>
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
      switchTab('login');
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
          sentLabel === 'negative' ? 'bg-rose-100 text-rose-800' : 'bg-stone-100 text-stone-800';

        resBox.innerHTML = `
          <div class="flex justify-between items-center mb-1 gap-2">
            <span class="font-bold text-stone-800">VADER Sentiment Analysis</span>
            <span class="pill ${badgeColor}">${escapeHTML(sentLabel)}</span>
          </div>
          <div class="text-[11px] text-stone-600">
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
          list.innerHTML = '<p class="text-stone-400 py-6 text-center">No critical negative complaints detected.</p>';
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
                <p class="text-stone-800">"${comment}"</p>
                <span class="text-[10px] text-stone-500 mt-1 block">${pId}${dt}</span>
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

  function initChatWebSocket() {
    if (state.chatWs && (state.chatWs.readyState === WebSocket.OPEN || state.chatWs.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${API.chat.ws}/${state.chatSessionId}`;

    try {
      state.chatWs = new WebSocket(wsUrl);

      state.chatWs.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          hideTypingIndicator();
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
        console.log('Chat WebSocket closed');
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
    const isMe = !isBot && (msg.is_optimistic || (state.user && (msg.sender === state.user.full_name || msg.sender_name === state.user.full_name)));

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
    state.chatSessionId = crypto.randomUUID();
    localStorage.setItem('chat_session_id', state.chatSessionId);
    state.guestChatRemaining = 5;
    updateChatGuestUI(5);
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
    if (state.chatWs) {
      try { state.chatWs.close(); } catch (_) {}
      initChatWebSocket();
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
  const APP_BUILD_VERSION = '2.8.0';

  function initPWA() {
    // 0. Automatically purge outdated CacheStorage when build version bumps
    if (window.caches && localStorage.getItem('app_build_version') !== APP_BUILD_VERSION) {
      caches.keys().then((names) => {
        return Promise.all(names.map((name) => caches.delete(name)));
      }).then(() => {
        localStorage.setItem('app_build_version', APP_BUILD_VERSION);
      });
    }

    // 1. Register Service Worker for offline caching & handle auto-refresh
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js', { scope: '/' })
          .then((reg) => {
            console.log('PWA: ServiceWorker registered successfully with scope:', reg.scope);
            // Check for service worker updates immediately on page load
            reg.update();
            reg.addEventListener('updatefound', () => {
              const newWorker = reg.installing;
              if (newWorker) {
                newWorker.addEventListener('statechange', () => {
                  if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                    // New code deployed: auto-reload to display latest changes
                    window.location.reload();
                  }
                });
              }
            });
          })
          .catch((err) => {
            console.warn('PWA: ServiceWorker registration failed:', err);
          });
      });

      // Reload once when service worker controller takes over
      let refreshing = false;
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (!refreshing) {
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
      if (headerBtn) headerBtn.classList.remove('hidden');
    });

    // 2b. For browsers like Kiwi or Safari that suppress beforeinstallprompt:
    const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    if (!isStandalone && sessionStorage.getItem('pwa_dismissed') !== 'true') {
      setTimeout(() => {
        const banner = document.getElementById('pwaInstallBanner');
        if (banner) banner.classList.remove('hidden');
      }, 1200);
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
  }

  // Initialize on page load
  async function init() {
    initPWA();

    // Immediately set active portal tab before network roundtrip to eliminate reload flicker
    const roleMap = { patient: 'patient', doctor: 'doctor', staff: 'staff', admin: 'analytics' };
    if (state.user && state.user.role && roleMap[state.user.role]) {
      switchTab(roleMap[state.user.role]);
    } else {
      switchTab('login');
    }

    updateUserUI();
    loadDoctors();
    fetchQueueStatus();
    initQueueWebSocket();

    // Pre-connect chat websocket when hovering or touching launcher
    const chatLauncher = document.getElementById('chatLauncher');
    if (chatLauncher) {
      chatLauncher.addEventListener('mouseenter', initChatWebSocket, { once: true });
      chatLauncher.addEventListener('touchstart', initChatWebSocket, { once: true, passive: true });
    }

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
      updateUserUI();
      const roleMap = { patient: 'patient', doctor: 'doctor', staff: 'staff', admin: 'analytics' };
      switchTab(roleMap[me.role] || 'patient');
    } catch (_) {
      state.user = null;
      localStorage.removeItem('user_profile');
      updateUserUI();
      switchTab('login');
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
    issueMyQueueTicket,
    callNextPatient,
    registerWalkin,
    submitAppointment,
    loadDoctorSchedule,
    selectConsultationPatient,
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
    clearChat,
    copyChatText,
    sendChatMessage,
    sendChatInput,
    sendQuickFaq,
    showcaseSelectRole,
    showcaseOpenChat,
    installPWA,
    dismissPWABanner,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();