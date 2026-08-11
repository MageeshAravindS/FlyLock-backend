// Base API URL configuration for GitHub Pages
const getApiBase = () => {
  if (window.location.hostname.endsWith('github.io')) {
    const urlParams = new URLSearchParams(window.location.search);
    const paramUrl = urlParams.get('backend_url');
    if (paramUrl) {
      localStorage.setItem('FLYLOCK_BACKEND_URL', paramUrl);
      return paramUrl.replace(/\/$/, '');
    }
    return (localStorage.getItem('FLYLOCK_BACKEND_URL') || 'https://bitsathy-flylock.onrender.com').replace(/\/$/, '');
  }
  return '';
};

const API_BASE = getApiBase();

// Custom fetch wrapper supporting CORS credentials and token authorization
const customFetch = (url, options = {}) => {
  const absoluteUrl = url.startsWith('http') ? url : (API_BASE + url);
  options.credentials = 'include';
  
  // Set headers object
  options.headers = options.headers || {};
  
  return fetch(absoluteUrl, options);
};

document.addEventListener('DOMContentLoaded', () => {
  const state = {
    student: null,
    currentExamAttempt: null,
    currentQuestionIndex: 0,
    userAnswers: {},
    timerInterval: null,
    heartbeatInterval: null
  };

  const toastContainer = document.getElementById('toast-container');
  const attendLockedView = document.getElementById('attend-locked-view');
  const attendExamView = document.getElementById('attend-exam-view');
  const attendSubmittedView = document.getElementById('attend-submitted-view');
  const tokenStatusText = document.getElementById('token-status-text');
  const tokenIndicatorDot = document.getElementById('token-indicator-dot');
  const btnRetryTokenVerify = document.getElementById('btn-retry-token-verify');

  // Student Auth Selectors
  const studentBadge = document.getElementById('student-badge');
  const btnStudentLoginModal = document.getElementById('btn-student-login-modal');
  const btnStudentLogout = document.getElementById('btn-student-logout');
  const modalStudentLogin = document.getElementById('modal-student-login');
  const btnCloseStudentModal = document.getElementById('btn-close-student-modal');
  const formStudentLogin = document.getElementById('form-student-login');
  const inputStudentEmail = document.getElementById('input-student-email');

  const examCodeTag = document.getElementById('exam-code-tag');
  const examTitle = document.getElementById('exam-title');
  const timerDisplay = document.getElementById('timer-display');
  const questionNavGrid = document.getElementById('question-nav-grid');
  const qNumLabel = document.getElementById('q-num-label');
  const qTextBody = document.getElementById('q-text-body');
  const qOptionsContainer = document.getElementById('q-options-container');
  const btnPrevQ = document.getElementById('btn-prev-q');
  const btnNextQ = document.getElementById('btn-next-q');
  const btnSubmitExam = document.getElementById('btn-submit-exam');

  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<strong>[${type.toUpperCase()}]</strong> ${message}`;
    toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  async function checkStudentAuth() {
    try {
      const res = await customFetch('/api/v1/auth/student-me');
      const data = await res.json();
      if (res.ok && data.student) {
        state.student = data.student;
        updateStudentUI();
      } else {
        state.student = null;
        updateStudentUI();
      }
    } catch (e) {
      state.student = null;
      updateStudentUI();
    }
  }

  function updateStudentUI() {
    if (state.student) {
      if (studentBadge) {
        studentBadge.textContent = `Student: ${state.student.email}`;
        studentBadge.className = 'user-badge creator';
      }
      if (btnStudentLoginModal) btnStudentLoginModal.classList.add('hidden');
      if (btnStudentLogout) btnStudentLogout.classList.remove('hidden');
    } else {
      if (studentBadge) {
        studentBadge.textContent = 'Not Logged In';
        studentBadge.className = 'user-badge guest';
      }
      if (btnStudentLoginModal) btnStudentLoginModal.classList.remove('hidden');
      if (btnStudentLogout) btnStudentLogout.classList.add('hidden');
    }
  }

  if (btnStudentLoginModal) btnStudentLoginModal.addEventListener('click', () => modalStudentLogin.classList.remove('hidden'));
  if (btnCloseStudentModal) btnCloseStudentModal.addEventListener('click', () => modalStudentLogin.classList.add('hidden'));

  // Google SSO Callback for Students
  window.handleStudentGoogleCredentialResponse = async function(response) {
    if (!response || !response.credential) return;
    try {
      const res = await customFetch('/api/v1/auth/student-google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idToken: response.credential })
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.message || data.error, 'error');
        return;
      }
      state.student = data.user;
      updateStudentUI();
      modalStudentLogin.classList.add('hidden');
      showToast(`Authenticated as ${data.user.email}`, 'success');
      verifyExamAccess();
    } catch (err) {
      showToast('Google student login failed', 'error');
    }
  };

  // Student Email Login
  if (formStudentLogin) {
    formStudentLogin.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = inputStudentEmail.value.trim().toLowerCase();
      if (!email.endswith('@bitsathy.ac.in')) {
        showToast('Only institutional emails ending in @bitsathy.ac.in are allowed.', 'error');
        return;
      }

      try {
        const res = await customFetch('/api/v1/auth/student-login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email })
        });
        const data = await res.json();
        if (!res.ok) {
          showToast(data.message || data.error, 'error');
          return;
        }
        state.student = data.user;
        updateStudentUI();
        modalStudentLogin.classList.add('hidden');
        showToast(`Logged in as student: ${data.user.email}`, 'success');
        verifyExamAccess();
      } catch (err) {
        showToast('Student login failed', 'error');
      }
    });
  }

  if (btnStudentLogout) {
    btnStudentLogout.addEventListener('click', async () => {
      await customFetch('/api/v1/auth/student-logout', { method: 'POST' });
      state.student = null;
      updateStudentUI();
      showToast('Student logged out', 'info');
      verifyExamAccess();
    });
  }

  let verifyRetryCount = 0;
  const maxVerifyRetries = 25;

  async function verifyExamAccess() {
    let token = null;
    let code = null;

    // Check search params first, then pathname, then hash params
    const searchParams = new URLSearchParams(window.location.search);
    token = searchParams.get('token');
    code = searchParams.get('code');
    const emailParam = searchParams.get('email');

    if (emailParam && emailParam.endsWith('@bitsathy.ac.in') && (!state.student || state.student.email !== emailParam)) {
      try {
        const loginRes = await customFetch('/api/v1/auth/student-login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: emailParam })
        });
        const loginData = await loginRes.json();
        if (loginRes.ok && loginData.user) {
          state.student = loginData.user;
          updateStudentUI();
        }
      } catch (e) {}
    }

    if (!code && window.location.pathname.includes('/assessment/')) {
      const parts = window.location.pathname.split('/assessment/');
      const rawCode = parts[parts.length - 1].split('?')[0].split('#')[0].replace(/\/$/, '');
      if (rawCode && rawCode !== 'index.html' && rawCode !== 'portal.html') {
        code = rawCode;
      }
    }

    if (!token && window.location.hash.includes('?')) {
      const hashParams = new URLSearchParams(window.location.hash.split('?')[1] || '');
      if (!token) token = hashParams.get('token');
      if (!code) code = hashParams.get('code');
    }

    try {
      let url = '/assessment/verify';
      const queryParts = [];
      if (token) queryParts.push(`token=${encodeURIComponent(token)}`);
      if (code) queryParts.push(`code=${encodeURIComponent(code)}`);
      if (queryParts.length > 0) url += '?' + queryParts.join('&');

      const res = await customFetch(url);
      const data = await res.json();

      if (!res.ok || !data.valid) {
        attendLockedView.classList.remove('hidden');
        attendExamView.classList.add('hidden');
        attendSubmittedView.classList.add('hidden');
        
        const lockTitle = document.getElementById('attend-lock-title');
        const lockDesc = document.getElementById('attend-lock-desc');

        if (res.status === 401 || data.error === 'STUDENT_AUTH_REQUIRED') {
          if (lockTitle) lockTitle.textContent = 'Student Authentication Required';
          if (lockDesc) lockDesc.textContent = data.message || 'Please log in with your @bitsathy.ac.in institutional email address to attend this assessment.';
          tokenIndicatorDot.className = 'status-indicator warning';
          tokenStatusText.textContent = 'Student Authentication Required (@bitsathy.ac.in email)';
          if (modalStudentLogin) modalStudentLogin.classList.remove('hidden');
        } else if (res.status === 404) {
          if (lockTitle) lockTitle.textContent = 'Invalid Assessment PIN';
          if (lockDesc) lockDesc.textContent = `The 5-digit PIN code "${code || ''}" was not found or is currently inactive. Please check your PIN code and try again.`;
          tokenIndicatorDot.className = 'status-indicator danger';
          tokenStatusText.textContent = `Invalid PIN Code "${code || ''}" (HTTP 404)`;
        } else {
          if (lockTitle) lockTitle.textContent = 'Assessment Locked';
          if (lockDesc) lockDesc.textContent = data.message || data.error || 'Access Blocked: Assessments can ONLY be accessed from inside FlyLock Browser.';
          tokenIndicatorDot.className = 'status-indicator danger';
          tokenStatusText.textContent = data.error || data.message || 'Access Denied: FlyLock authorization required.';
        }
        return;
      }

      state.currentExamAttempt = data.attempt;
      state.currentQuestionIndex = 0;
      state.userAnswers = JSON.parse(data.attempt.saved_answers || '{}');

      renderExamUI();
    } catch (err) {
      console.error(err);
      if (verifyRetryCount < maxVerifyRetries) {
        verifyRetryCount++;
        tokenIndicatorDot.className = 'status-indicator warning';
        tokenStatusText.textContent = `Connecting to backend... Waking up server (Attempt ${verifyRetryCount}/${maxVerifyRetries}), please wait...`;
        setTimeout(verifyExamAccess, 3000);
      } else {
        tokenIndicatorDot.className = 'status-indicator danger';
        tokenStatusText.textContent = 'Connection error: Backend server is unreachable. Please try again later.';
      }
    }
  }

  function renderExamUI() {
    attendLockedView.classList.add('hidden');
    attendSubmittedView.classList.add('hidden');
    attendExamView.classList.remove('hidden');

    const att = state.currentExamAttempt;
    examCodeTag.textContent = att.exam_code;
    examTitle.textContent = att.title;

    questionNavGrid.innerHTML = '';
    att.questions.forEach((q, idx) => {
      const btn = document.createElement('button');
      btn.className = `q-nav-btn ${idx === state.currentQuestionIndex ? 'current' : ''} ${state.userAnswers[q.id] !== undefined ? 'answered' : ''}`;
      btn.textContent = idx + 1;
      btn.addEventListener('click', () => {
        state.currentQuestionIndex = idx;
        renderCurrentQuestion();
      });
      questionNavGrid.appendChild(btn);
    });

    renderCurrentQuestion();
    startExamTimer(att.duration_minutes * 60);
    startHeartbeat();
  }

  function renderCurrentQuestion() {
    const att = state.currentExamAttempt;
    if (!att || !att.questions || att.questions.length === 0) {
      if (qNumLabel) qNumLabel.textContent = "Question 0 of 0";
      if (qTextBody) qTextBody.textContent = "No questions found in this assessment.";
      if (qOptionsContainer) qOptionsContainer.innerHTML = "";
      if (btnPrevQ) btnPrevQ.disabled = true;
      if (btnNextQ) btnNextQ.disabled = true;
      return;
    }

    const q = att.questions[state.currentQuestionIndex];
    if (!q) return;

    if (qNumLabel) qNumLabel.textContent = `Question ${state.currentQuestionIndex + 1} of ${att.questions.length}`;
    if (qTextBody) qTextBody.textContent = q.text || "";

    if (qOptionsContainer) qOptionsContainer.innerHTML = '';
    const selectedOptId = state.userAnswers[q.id];

    if (q.options) {
      q.options.forEach(opt => {
        const label = document.createElement('label');
        label.className = `option-item ${selectedOptId === opt.id ? 'selected' : ''}`;

        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = `q_${q.id}`;
        radio.className = 'option-radio';
        radio.checked = selectedOptId === opt.id;
        radio.addEventListener('change', () => {
          state.userAnswers[q.id] = opt.id;
          renderCurrentQuestion();
          const navBtns = questionNavGrid.querySelectorAll('.q-nav-btn');
          if (navBtns[state.currentQuestionIndex]) navBtns[state.currentQuestionIndex].classList.add('answered');
        });

        const spanText = document.createElement('span');
        spanText.className = 'option-text';
        spanText.textContent = opt.text;

        label.appendChild(radio);
        label.appendChild(spanText);
        qOptionsContainer.appendChild(label);
      });
    }

    if (btnPrevQ) btnPrevQ.disabled = state.currentQuestionIndex === 0;
    if (btnNextQ) btnNextQ.disabled = state.currentQuestionIndex === att.questions.length - 1;
  }

  btnPrevQ.addEventListener('click', () => {
    if (state.currentQuestionIndex > 0) {
      state.currentQuestionIndex--;
      renderCurrentQuestion();
    }
  });

  btnNextQ.addEventListener('click', () => {
    if (state.currentQuestionIndex < state.currentExamAttempt.questions.length - 1) {
      state.currentQuestionIndex++;
      renderCurrentQuestion();
    }
  });

  function startExamTimer(secondsLeft) {
    if (state.timerInterval) clearInterval(state.timerInterval);
    state.timerInterval = setInterval(() => {
      secondsLeft--;
      if (secondsLeft <= 0) {
        clearInterval(state.timerInterval);
        executeSubmit();
        return;
      }
      const mins = Math.floor(secondsLeft / 60);
      const secs = secondsLeft % 60;
      timerDisplay.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }, 1000);
  }

  function startHeartbeat() {
    if (state.heartbeatInterval) clearInterval(state.heartbeatInterval);
    state.heartbeatInterval = setInterval(async () => {
      if (!state.currentExamAttempt) return;
      try {
        await customFetch(`/api/v1/assessments/${state.currentExamAttempt.exam_code}/heartbeat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ answers: state.userAnswers })
        });
      } catch (e) {}
    }, 15000);
  }

  const modalSubmitConfirm = document.getElementById('modal-submit-confirm');
  const btnCloseSubmitModal = document.getElementById('btn-close-submit-modal');
  const btnCancelSubmit = document.getElementById('btn-cancel-submit');
  const btnConfirmFinalSubmit = document.getElementById('btn-confirm-final-submit');

  function openSubmitModal() {
    if (modalSubmitConfirm) modalSubmitConfirm.classList.remove('hidden');
  }

  function closeSubmitModal() {
    if (modalSubmitConfirm) modalSubmitConfirm.classList.add('hidden');
  }

  btnSubmitExam.addEventListener('click', () => {
    openSubmitModal();
  });

  if (btnCloseSubmitModal) btnCloseSubmitModal.addEventListener('click', closeSubmitModal);
  if (btnCancelSubmit) btnCancelSubmit.addEventListener('click', closeSubmitModal);

  if (btnConfirmFinalSubmit) {
    btnConfirmFinalSubmit.addEventListener('click', async () => {
      closeSubmitModal();
      await executeSubmit();
    });
  }

  async function executeSubmit() {
    if (!state.currentExamAttempt) return;
    try {
      const res = await customFetch(`/api/v1/assessments/${state.currentExamAttempt.exam_code}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers: state.userAnswers })
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.error || 'Submission failed', 'error');
        return;
      }
      clearInterval(state.timerInterval);
      clearInterval(state.heartbeatInterval);
      
      const studentEmail = state.currentExamAttempt.student_email || state.currentExamAttempt.student_identifier || '';
      state.currentExamAttempt = null;

      attendExamView.classList.add('hidden');
      attendSubmittedView.classList.remove('hidden');

      const scoreDisplay = document.getElementById('submitted-score-display');
      const emailDisplay = document.getElementById('submitted-email-display');
      if (scoreDisplay && data.score !== undefined) {
        scoreDisplay.textContent = `Score: ${data.score} / ${data.totalQuestions} (${data.percentage}%)`;
      }
      if (emailDisplay && studentEmail) {
        emailDisplay.textContent = `Student Email: ${studentEmail}`;
      }

      showToast('Assessment submitted successfully!', 'success');
    } catch (err) {
      showToast('Network error submitting assessment', 'error');
    }
  }

  btnRetryTokenVerify.addEventListener('click', () => verifyExamAccess());

  checkStudentAuth().then(() => verifyExamAccess());
});