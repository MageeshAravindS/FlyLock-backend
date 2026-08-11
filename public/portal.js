// Base API URL configuration for GitHub Pages
const getApiBase = () => {
  if (window.location.hostname.endsWith('github.io')) {
    const urlParams = new URLSearchParams(window.location.search);
    const paramUrl = urlParams.get('backend_url');
    if (paramUrl) {
      localStorage.setItem('FLYLOCK_BACKEND_URL', paramUrl);
      return paramUrl.replace(/\/$/, '');
    }
    return (localStorage.getItem('FLYLOCK_BACKEND_URL') || 'https://flylock-backend.onrender.com').replace(/\/$/, '');
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
    user: null,
    currentSurface: 'create',
    rawCsvContent: null
  };

  // Selectors
  const navTabs = document.querySelectorAll('.nav-tab[data-surface]');
  const surfaces = document.querySelectorAll('.surface-container');
  const toastContainer = document.getElementById('toast-container');

  const userBadge = document.getElementById('user-badge');
  const btnLoginModal = document.getElementById('btn-login-modal');
  const btnLogout = document.getElementById('btn-logout');
  const modalLogin = document.getElementById('modal-login');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const formLogin = document.getElementById('form-login');

  // Surface 1: Create
  const modeTabManual = document.getElementById('mode-tab-manual');
  const modeTabCsv = document.getElementById('mode-tab-csv');
  const modeTabPublished = document.getElementById('mode-tab-published');
  const builderManualPanel = document.getElementById('builder-manual-panel');
  const builderCsvPanel = document.getElementById('builder-csv-panel');
  const builderPublishedPanel = document.getElementById('builder-published-panel');
  const formCreateAssessment = document.getElementById('form-create-assessment');
  const questionsListContainer = document.getElementById('questions-list-container');
  const btnAddQuestion = document.getElementById('btn-add-question');
  const createUnauthMsg = document.getElementById('create-unauth-msg');

  // CSV Elements
  const csvModeNew = document.getElementById('csv-mode-new');
  const csvModeAppend = document.getElementById('csv-mode-append');
  const csvNewMetadataSection = document.getElementById('csv-new-metadata-section');
  const csvAppendMetadataSection = document.getElementById('csv-append-metadata-section');
  const inputCsvExamCode = document.getElementById('input-csv-exam-code');
  const btnCsvGenPin = document.getElementById('btn-csv-gen-pin');
  const inputCsvDuration = document.getElementById('input-csv-duration');
  const inputCsvExamTitle = document.getElementById('input-csv-exam-title');
  const inputCsvExamDesc = document.getElementById('input-csv-exam-desc');
  const selectTargetAssessment = document.getElementById('select-target-assessment');
  const csvDropzone = document.getElementById('csv-dropzone');
  const inputCsvFile = document.getElementById('input-csv-file');
  const btnBrowseCsv = document.getElementById('btn-browse-csv');
  const csvPreviewBox = document.getElementById('csv-preview-box');
  const csvPreviewTable = document.getElementById('csv-preview-table');
  const csvValidationReport = document.getElementById('csv-validation-report');
  const btnConfirmCsvImport = document.getElementById('btn-confirm-csv-import');

  // Published Assessments Elements
  const tablePublishedAssessmentsBody = document.querySelector('#table-published-assessments tbody');
  const btnRefreshPublished = document.getElementById('btn-refresh-published');

  // Student Responses Elements
  const modeTabResponses = document.getElementById('mode-tab-responses');
  const builderResponsesPanel = document.getElementById('builder-responses-panel');
  const tableStudentResponsesBody = document.querySelector('#table-student-responses tbody');
  const btnRefreshResponses = document.getElementById('btn-refresh-responses');
  const inputFilterStudentEmail = document.getElementById('input-filter-student-email');
  const modalResponseDetail = document.getElementById('modal-response-detail');
  const btnCloseResponseModal = document.getElementById('btn-close-response-modal');
  const responseDetailContent = document.getElementById('response-detail-content');

  // Surface 2: Admin Elements
  const formAddAllowlist = document.getElementById('form-add-allowlist');
  const tableAllowlistBody = document.querySelector('#table-allowlist tbody');
  const tableAdminAttemptsBody = document.querySelector('#table-admin-attempts tbody');
  const tableAuditLogsBody = document.querySelector('#table-audit-logs tbody');

  // Surface 3: Simulator Elements
  const simClientId = document.getElementById('sim-client-id');
  const simExamCode = document.getElementById('sim-exam-code');
  const simBtnFetchToken = document.getElementById('sim-btn-fetch-token');
  const simJsonOutput = document.getElementById('sim-json-output');
  const simBtnLaunchBrowser = document.getElementById('sim-btn-launch-browser');
  const simBtnTestReplay = document.getElementById('sim-btn-test-replay');

  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<strong>[${type.toUpperCase()}]</strong> ${message}`;
    toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  function switchSurface(surfaceId) {
    state.currentSurface = surfaceId;
    navTabs.forEach(tab => {
      if (tab.dataset.surface === surfaceId) {
        tab.classList.add('active');
      } else {
        tab.classList.remove('active');
      }
    });

    surfaces.forEach(surf => {
      if (surf.id === `surface-${surfaceId}`) {
        surf.classList.add('active');
      } else {
        surf.classList.remove('active');
      }
    });

    if (surfaceId === 'admin') loadAdminData();
    else if (surfaceId === 'create') loadAssessmentsListForCsv();
  }

  navTabs.forEach(tab => {
    tab.addEventListener('click', () => switchSurface(tab.dataset.surface));
  });

  // Authentication
  async function checkAuth() {
    try {
      const res = await customFetch('/api/v1/auth/me');
      if (res.ok) {
        const data = await res.json();
        state.user = data.user;
        updateUserUI();
      } else {
        state.user = null;
        updateUserUI();
      }
    } catch (e) {
      state.user = null;
      updateUserUI();
    }
  }

  function updateUserUI() {
    if (state.user) {
      userBadge.textContent = `${state.user.email} (${state.user.role.toUpperCase()})`;
      userBadge.className = `user-badge ${state.user.role}`;
      btnLoginModal.classList.add('hidden');
      btnLogout.classList.remove('hidden');
      if (createUnauthMsg) createUnauthMsg.classList.add('hidden');
    } else {
      userBadge.textContent = 'Not Logged In';
      userBadge.className = 'user-badge guest';
      btnLoginModal.classList.remove('hidden');
      btnLogout.classList.add('hidden');
      if (createUnauthMsg) createUnauthMsg.classList.remove('hidden');
    }
  }

  btnLoginModal.addEventListener('click', () => modalLogin.classList.remove('hidden'));
  btnCloseModal.addEventListener('click', () => modalLogin.classList.add('hidden'));

  // Google SSO Callback
  window.handleGoogleCredentialResponse = async function(response) {
    if (!response || !response.credential) return;
    try {
      const res = await customFetch('/api/v1/auth/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idToken: response.credential })
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.message || data.error, 'error');
        return;
      }
      state.user = data.user;
      updateUserUI();
      modalLogin.classList.add('hidden');
      showToast(`Authenticated via Google SSO as ${data.user.email}`, 'success');
      if (state.currentSurface === 'admin') loadAdminData();
    } catch (err) {
      showToast('Google login failed', 'error');
    }
  };
  window.onGoogleLibraryCallback = window.handleGoogleCredentialResponse;

  // Email Login
  formLogin.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('input-login-email').value.trim();
    try {
      const res = await customFetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(data.message || data.error, 'error');
        return;
      }
      state.user = data.user;
      updateUserUI();
      modalLogin.classList.add('hidden');
      showToast(`Logged in as ${data.user.email}`, 'success');
      if (state.currentSurface === 'admin') loadAdminData();
    } catch (err) {
      showToast('Login request failed', 'error');
    }
  });

  btnLogout.addEventListener('click', async () => {
    await customFetch('/api/v1/auth/logout', { method: 'POST' });
    state.user = null;
    updateUserUI();
    showToast('Logged out', 'info');
  });

  // Create Mode Tabs
  modeTabManual.addEventListener('click', () => {
    modeTabManual.classList.add('active');
    modeTabCsv.classList.remove('active');
    modeTabPublished.classList.remove('active');
    if (modeTabResponses) modeTabResponses.classList.remove('active');
    builderManualPanel.classList.remove('hidden');
    builderCsvPanel.classList.add('hidden');
    builderPublishedPanel.classList.add('hidden');
    if (builderResponsesPanel) builderResponsesPanel.classList.add('hidden');
  });

  modeTabCsv.addEventListener('click', () => {
    modeTabCsv.classList.add('active');
    modeTabManual.classList.remove('active');
    modeTabPublished.classList.remove('active');
    if (modeTabResponses) modeTabResponses.classList.remove('active');
    builderCsvPanel.classList.remove('hidden');
    builderManualPanel.classList.add('hidden');
    builderPublishedPanel.classList.add('hidden');
    if (builderResponsesPanel) builderResponsesPanel.classList.add('hidden');
    loadAssessmentsListForCsv();
    if (!inputCsvExamCode.value) generateCsvRandomPin();
  });

  modeTabPublished.addEventListener('click', () => {
    modeTabPublished.classList.add('active');
    modeTabManual.classList.remove('active');
    modeTabCsv.classList.remove('active');
    if (modeTabResponses) modeTabResponses.classList.remove('active');
    builderPublishedPanel.classList.remove('hidden');
    builderManualPanel.classList.add('hidden');
    builderCsvPanel.classList.add('hidden');
    if (builderResponsesPanel) builderResponsesPanel.classList.add('hidden');
    loadPublishedAssessments();
  });

  if (modeTabResponses) {
    modeTabResponses.addEventListener('click', () => {
      modeTabResponses.classList.add('active');
      modeTabManual.classList.remove('active');
      modeTabCsv.classList.remove('active');
      modeTabPublished.classList.remove('active');
      builderResponsesPanel.classList.remove('hidden');
      builderManualPanel.classList.add('hidden');
      builderCsvPanel.classList.add('hidden');
      builderPublishedPanel.classList.add('hidden');
      loadStudentResponses();
    });
  }

  // CSV Import Mode Toggle (New vs Append)
  if (csvModeNew && csvModeAppend) {
    csvModeNew.addEventListener('change', () => {
      csvNewMetadataSection.classList.remove('hidden');
      csvAppendMetadataSection.classList.add('hidden');
    });
    csvModeAppend.addEventListener('change', () => {
      csvAppendMetadataSection.classList.remove('hidden');
      csvNewMetadataSection.classList.add('hidden');
      loadAssessmentsListForCsv();
    });
  }

  function generateCsvRandomPin() {
    const pin = Math.floor(10000 + Math.random() * 90000).toString();
    if (inputCsvExamCode) inputCsvExamCode.value = pin;
  }
  if (btnCsvGenPin) btnCsvGenPin.addEventListener('click', generateCsvRandomPin);

  function addManualQuestionRow() {
    const qIndex = questionsListContainer.children.length + 1;
    const qDiv = document.createElement('div');
    qDiv.className = 'q-builder-item';

    qDiv.innerHTML = `
      <div class="q-builder-header">
        <strong style="color: var(--accent);">Question #${qIndex}</strong>
        <button type="button" class="btn btn-sm btn-ghost btn-remove-q" style="color: var(--danger);">[REMOVE QUESTION]</button>
      </div>
      <div class="form-group">
        <input type="text" class="form-input q-text-input" placeholder="Enter question text..." required>
      </div>
      <div class="form-group">
        <label>Options (Select radio for correct answer)</label>
        <div class="options-builder-grid">
          <div class="opt-builder-row">
            <input type="radio" name="correct_q_${qIndex}" checked>
            <input type="text" class="form-input opt-text-input" placeholder="Option 1 text..." required>
          </div>
          <div class="opt-builder-row">
            <input type="radio" name="correct_q_${qIndex}">
            <input type="text" class="form-input opt-text-input" placeholder="Option 2 text..." required>
          </div>
          <div class="opt-builder-row">
            <input type="radio" name="correct_q_${qIndex}">
            <input type="text" class="form-input opt-text-input" placeholder="Option 3 text...">
          </div>
          <div class="opt-builder-row">
            <input type="radio" name="correct_q_${qIndex}">
            <input type="text" class="form-input opt-text-input" placeholder="Option 4 text...">
          </div>
        </div>
      </div>
      <div class="form-group">
        <input type="text" class="form-input q-reason-input" placeholder="Optional explanation/reason for answer...">
      </div>
    `;

    qDiv.querySelector('.btn-remove-q').addEventListener('click', () => qDiv.remove());
    questionsListContainer.appendChild(qDiv);
  }

  const btnGenPin = document.getElementById('btn-gen-pin');
  function generateRandomPin() {
    const pin = Math.floor(10000 + Math.random() * 90000).toString();
    const inputExamCode = document.getElementById('input-exam-code');
    if (inputExamCode) inputExamCode.value = pin;
  }
  if (btnGenPin) btnGenPin.addEventListener('click', generateRandomPin);
  generateRandomPin();

  if (btnAddQuestion) btnAddQuestion.addEventListener('click', addManualQuestionRow);
  addManualQuestionRow();

  formCreateAssessment.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!state.user) {
      showToast('Please log in with your @bitsathy.ac.in email first.', 'error');
      modalLogin.classList.remove('hidden');
      return;
    }

    const examCode = document.getElementById('input-exam-code').value.trim();
    const durationMinutes = parseInt(document.getElementById('input-duration').value);
    const title = document.getElementById('input-exam-title').value.trim();
    const description = document.getElementById('input-exam-desc').value.trim();

    const qItems = questionsListContainer.querySelectorAll('.q-builder-item');
    const questionsPayload = [];

    qItems.forEach(qDiv => {
      const text = qDiv.querySelector('.q-text-input').value.trim();
      const reason = qDiv.querySelector('.q-reason-input').value.trim();
      const optRows = qDiv.querySelectorAll('.opt-builder-row');

      const optionsPayload = [];
      optRows.forEach(optRow => {
        const optText = optRow.querySelector('.opt-text-input').value.trim();
        const isCorrect = optRow.querySelector('input[type="radio"]').checked;
        if (optText) optionsPayload.push({ text: optText, isCorrect });
      });

      if (text && optionsPayload.length >= 2) {
        questionsPayload.push({ text, reason, options: optionsPayload });
      }
    });

    if (questionsPayload.length === 0) {
      showToast('Please add at least 1 valid question with 2 options.', 'error');
      return;
    }

    try {
      const res = await customFetch('/api/v1/assessments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ examCode, durationMinutes, title, description, questions: questionsPayload })
      });

      const data = await res.json();
      if (!res.ok) {
        showToast(data.error || 'Failed to create assessment', 'error');
        return;
      }

      showToast(`Assessment ${examCode} published successfully!`, 'success');
      formCreateAssessment.reset();
      questionsListContainer.innerHTML = '';
      addManualQuestionRow();
    } catch (err) {
      showToast('Error publishing assessment', 'error');
    }
  });

  async function loadAssessmentsListForCsv() {
    try {
      const res = await customFetch('/api/v1/assessments/list');
      if (!res.ok) return;
      const data = await res.json();
      selectTargetAssessment.innerHTML = '';
      data.assessments.forEach(a => {
        const opt = document.createElement('option');
        opt.value = a.id;
        opt.textContent = `${a.exam_code} - ${a.title} (${a.question_count} Qs)`;
        selectTargetAssessment.appendChild(opt);
      });
    } catch (e) {}
  }

  btnBrowseCsv.addEventListener('click', () => inputCsvFile.click());
  csvDropzone.addEventListener('click', (e) => {
    if (e.target !== btnBrowseCsv) inputCsvFile.click();
  });

  inputCsvFile.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) handleCsvFile(file);
  });

  function handleCsvFile(file) {
    const reader = new FileReader();
    reader.onload = (evt) => {
      state.rawCsvContent = evt.target.result;
      renderCsvPreview(evt.target.result);
    };
    reader.readAsText(file);
  }

  function renderCsvPreview(csvText) {
    csvPreviewBox.classList.remove('hidden');
    const lines = csvText.split(/\r?\n/).filter(l => l.trim());
    if (lines.length === 0) return;

    const headers = lines[0].split(',').map(h => h.replace(/^["']|["']$/g, '').trim());
    const thead = csvPreviewTable.querySelector('thead');
    const tbody = csvPreviewTable.querySelector('tbody');

    thead.innerHTML = `<tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr>`;
    tbody.innerHTML = '';

    lines.slice(1, 6).forEach(rowStr => {
      const cells = rowStr.split(',').map(c => c.replace(/^["']|["']$/g, '').trim());
      const tr = document.createElement('tr');
      tr.innerHTML = cells.map(c => `<td>${c}</td>`).join('');
      tbody.appendChild(tr);
    });

    csvValidationReport.classList.add('hidden');
  }

  btnConfirmCsvImport.addEventListener('click', async () => {
    if (!state.user) {
      showToast('Please log in with your @bitsathy.ac.in email first.', 'error');
      modalLogin.classList.remove('hidden');
      return;
    }
    if (!state.rawCsvContent) {
      showToast('Please select a CSV file first.', 'error');
      return;
    }

    const isNewMode = csvModeNew.checked;

    if (isNewMode) {
      const examCode = inputCsvExamCode.value.trim();
      const title = inputCsvExamTitle.value.trim();
      const description = inputCsvExamDesc.value.trim();
      const durationMinutes = parseInt(inputCsvDuration.value);

      if (!title) {
        showToast('Please enter an Assessment Title for the new CSV import.', 'error');
        return;
      }

      try {
        const res = await customFetch('/api/v1/assessments/import-csv-new', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            examCode,
            title,
            description,
            durationMinutes,
            csvContent: state.rawCsvContent
          })
        });

        const data = await res.json();
        if (!res.ok) {
          if (data.report) {
            csvValidationReport.classList.remove('hidden');
            csvValidationReport.innerHTML = `
              <strong>CSV Validation Errors (${data.report.length} found):</strong>
              <ul>${data.report.map(err => `<li>Row ${err.row}: ${err.message}</li>`).join('')}</ul>
            `;
          } else showToast(data.error || 'CSV import failed', 'error');
          return;
        }

        showToast(data.message, 'success');
        csvPreviewBox.classList.add('hidden');
        state.rawCsvContent = null;
        inputCsvExamTitle.value = '';
        inputCsvExamDesc.value = '';
        generateCsvRandomPin();
      } catch (err) {
        showToast('CSV import request error', 'error');
      }
    } else {
      const assessmentId = selectTargetAssessment.value;
      if (!assessmentId) {
        showToast('Select an assessment to append to.', 'error');
        return;
      }

      try {
        const res = await customFetch(`/api/v1/assessments/${assessmentId}/import-csv`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ csvContent: state.rawCsvContent })
        });

        const data = await res.json();
        if (!res.ok) {
          if (data.report) {
            csvValidationReport.classList.remove('hidden');
            csvValidationReport.innerHTML = `
              <strong>CSV Validation Errors (${data.report.length} found):</strong>
              <ul>${data.report.map(err => `<li>Row ${err.row}: ${err.message}</li>`).join('')}</ul>
            `;
          } else showToast(data.error || 'CSV import failed', 'error');
          return;
        }

        showToast(data.message, 'success');
        csvPreviewBox.classList.add('hidden');
        state.rawCsvContent = null;
        loadAssessmentsListForCsv();
      } catch (err) {
        showToast('CSV import request error', 'error');
      }
    }
  });

  // Published Assessments Tab Management
  async function loadPublishedAssessments() {
    try {
      const res = await customFetch('/api/v1/assessments/list');
      if (!res.ok) return;
      const data = await res.json();
      tablePublishedAssessmentsBody.innerHTML = '';

      if (data.assessments.length === 0) {
        tablePublishedAssessmentsBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted);">No published assessments found. Create one using Manual MCQ Builder or Bulk CSV Import!</td></tr>`;
        return;
      }

      data.assessments.forEach(ass => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong class="code-font" style="font-size: 1.1rem; letter-spacing: 1px;">${ass.exam_code}</strong></td>
          <td>
            <strong>${ass.title}</strong>
            ${ass.description ? `<br><small style="color: var(--text-muted);">${ass.description}</small>` : ''}
          </td>
          <td>${ass.duration_minutes} mins</td>
          <td><strong>${ass.question_count}</strong> Qs</td>
          <td>${ass.total_attempts || 0}</td>
          <td>
            <span class="user-badge ${ass.is_active ? 'admin' : 'guest'}">
              ${ass.is_active ? 'ACTIVE' : 'INACTIVE'}
            </span>
          </td>
          <td><small>${ass.creator_email}</small></td>
          <td>
            <div style="display: flex; gap: 4px; flex-wrap: wrap;">
              <button class="btn btn-sm ${ass.is_active ? 'btn-outline' : 'btn-success'} btn-toggle-active" data-id="${ass.id}" data-active="${ass.is_active}">
                ${ass.is_active ? 'Deactivate' : 'Activate'}
              </button>
              <button class="btn btn-sm btn-danger btn-delete-assessment" data-id="${ass.id}" data-code="${ass.exam_code}" data-title="${ass.title}">
                Delete / Revoke
              </button>
            </div>
          </td>
        `;
        tablePublishedAssessmentsBody.appendChild(tr);
      });

      tablePublishedAssessmentsBody.querySelectorAll('.btn-toggle-active').forEach(btn => {
        btn.addEventListener('click', async () => {
          const assId = btn.dataset.id;
          const currentActive = btn.dataset.active === '1' || btn.dataset.active === 'true';
          try {
            const res = await customFetch(`/api/v1/assessments/${assId}/update`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ is_active: !currentActive })
            });
            if (res.ok) {
              showToast(`Assessment status updated.`, 'success');
              loadPublishedAssessments();
            }
          } catch (e) {}
        });
      });

      tablePublishedAssessmentsBody.querySelectorAll('.btn-delete-assessment').forEach(btn => {
        btn.addEventListener('click', async () => {
          const assId = btn.dataset.id;
          const code = btn.dataset.code;
          const title = btn.dataset.title;
          if (confirm(`Are you sure you want to REVOKE and DELETE assessment '${title}' (PIN: ${code})? This will delete all questions and student attempts.`)) {
            try {
              const res = await customFetch(`/api/v1/assessments/${assId}/delete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
              });
              const data = await res.json();
              if (res.ok) {
                showToast(data.message || 'Assessment deleted', 'success');
                loadPublishedAssessments();
              } else {
                showToast(data.error || 'Failed to delete assessment', 'error');
              }
            } catch (e) {}
          }
        });
      });

    } catch (e) {
      showToast('Failed to load published assessments', 'error');
    }
  }

  if (btnRefreshPublished) {
    btnRefreshPublished.addEventListener('click', loadPublishedAssessments);
  }

  // Student Responses Tab & Live Session Control
  let rawStudentResponses = [];
  const selectFilterAssessment = document.getElementById('select-filter-assessment');
  const statTotalAttempts = document.getElementById('stat-total-attempts');
  const statInprogressAttempts = document.getElementById('stat-inprogress-attempts');
  const statSubmittedAttempts = document.getElementById('stat-submitted-attempts');
  const statTerminatedAttempts = document.getElementById('stat-terminated-attempts');

  async function loadStudentResponses() {
    try {
      const res = await customFetch('/api/v1/assessments/responses');
      if (!res.ok) {
        if (res.status === 401 || res.status === 403) {
          showToast('Creator/Admin login required to view student responses.', 'warning');
          modalLogin.classList.remove('hidden');
        } else {
          showToast('Failed to load student responses', 'error');
        }
        return;
      }
      const data = await res.json();
      rawStudentResponses = data.responses || [];

      // Populate assessment filter dropdown
      if (selectFilterAssessment) {
        const currentSel = selectFilterAssessment.value;
        selectFilterAssessment.innerHTML = '<option value="">All Assessments</option>';
        const uniqueAss = new Map();
        rawStudentResponses.forEach(r => {
          if (!uniqueAss.has(r.exam_code)) {
            uniqueAss.set(r.exam_code, r.assessment_title);
          }
        });
        uniqueAss.forEach((title, code) => {
          const opt = document.createElement('option');
          opt.value = code;
          opt.textContent = `${code} - ${title}`;
          selectFilterAssessment.appendChild(opt);
        });
        selectFilterAssessment.value = currentSel;
      }

      renderStudentResponsesTable();
    } catch (e) {
      showToast('Failed to load student responses', 'error');
    }
  }

  function renderStudentResponsesTable() {
    if (!tableStudentResponsesBody) return;
    tableStudentResponsesBody.innerHTML = '';

    const filterEmail = (inputFilterStudentEmail ? inputFilterStudentEmail.value : '').trim().toLowerCase();
    const filterAssCode = (selectFilterAssessment ? selectFilterAssessment.value : '').trim();

    const filtered = rawStudentResponses.filter(r => {
      const emailMatch = !filterEmail || (r.student_email && r.student_email.toLowerCase().includes(filterEmail));
      const codeMatch = !filterAssCode || (r.exam_code === filterAssCode);
      return emailMatch && codeMatch;
    });

    // Update Live Session Stats Counters
    if (statTotalAttempts) statTotalAttempts.textContent = filtered.length;
    if (statInprogressAttempts) statInprogressAttempts.textContent = filtered.filter(r => r.status === 'in_progress').length;
    if (statSubmittedAttempts) statSubmittedAttempts.textContent = filtered.filter(r => r.status === 'submitted').length;
    if (statTerminatedAttempts) statTerminatedAttempts.textContent = filtered.filter(r => r.status === 'terminated').length;

    if (filtered.length === 0) {
      tableStudentResponsesBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 2rem;">No student responses or active sessions found for selected filter.</td></tr>`;
      return;
    }

    filtered.forEach(resp => {
      const tr = document.createElement('tr');
      const pctClass = resp.percentage >= 80 ? 'admin' : resp.percentage >= 50 ? 'creator' : 'guest';
      const studentEmail = resp.student_email || resp.student_identifier;
      const statusBadgeClass = resp.status === 'submitted' ? 'success' : resp.status === 'in_progress' ? 'warning' : 'danger';
      const statusLabel = resp.status === 'in_progress' ? 'IN PROGRESS (LIVE)' : resp.status.toUpperCase();

      tr.innerHTML = `
        <td>#${resp.id}</td>
        <td><strong>${studentEmail}</strong></td>
        <td>
          <strong class="code-font">${resp.exam_code}</strong> - ${resp.assessment_title}
        </td>
        <td>
          <span class="user-badge ${pctClass}">
            ${resp.score} / ${resp.total_questions} (${resp.percentage}%)
          </span>
        </td>
        <td>
          <span class="status-indicator ${statusBadgeClass}"></span>
          <strong>${statusLabel}</strong>
        </td>
        <td><small>${new Date(resp.started_at).toLocaleTimeString()}</small></td>
        <td><small>${resp.submitted_at ? new Date(resp.submitted_at).toLocaleTimeString() : (resp.last_heartbeat ? 'Active: ' + new Date(resp.last_heartbeat).toLocaleTimeString() : '-')}</small></td>
        <td>
          <div style="display: flex; gap: 4px; flex-wrap: wrap;">
            <button class="btn btn-sm btn-outline btn-view-response" data-id="${resp.id}">
              View Answers
            </button>
            <button class="btn btn-sm btn-danger btn-grant-reattempt" data-id="${resp.id}" data-email="${studentEmail}" data-code="${resp.exam_code}">
              Grant Re-attempt
            </button>
          </div>
        </td>
      `;
      tableStudentResponsesBody.appendChild(tr);
    });

    tableStudentResponsesBody.querySelectorAll('.btn-view-response').forEach(btn => {
      btn.addEventListener('click', () => openResponseDetailModal(btn.dataset.id));
    });

    tableStudentResponsesBody.querySelectorAll('.btn-grant-reattempt').forEach(btn => {
      btn.addEventListener('click', async () => {
        const attemptId = btn.dataset.id;
        const email = btn.dataset.email;
        const code = btn.dataset.code;
        if (confirm(`Grant re-attempt for ${email} on assessment PIN ${code}?\n\nThis will reset their session state so they can log back in and retake the assessment.`)) {
          try {
            const res = await customFetch('/api/v1/assessments/attempts/reset', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ attemptId, action: 'reset' })
            });
            const data = await res.json();
            if (res.ok) {
              showToast(data.message || 'Re-attempt granted successfully!', 'success');
              loadStudentResponses();
              if (state.currentSurface === 'admin') loadAdminData();
            } else {
              showToast(data.error || 'Failed to grant re-attempt', 'error');
            }
          } catch (err) {
            showToast('Request error granting re-attempt', 'error');
          }
        }
      });
    });
  }

  if (inputFilterStudentEmail) {
    inputFilterStudentEmail.addEventListener('input', renderStudentResponsesTable);
  }
  if (selectFilterAssessment) {
    selectFilterAssessment.addEventListener('change', renderStudentResponsesTable);
  }
  if (btnRefreshResponses) {
    btnRefreshResponses.addEventListener('click', loadStudentResponses);
  }

  async function openResponseDetailModal(attemptId) {
    if (!modalResponseDetail || !responseDetailContent) return;
    responseDetailContent.innerHTML = `<p style="padding: 1rem; color: var(--text-muted);">Loading response details...</p>`;
    modalResponseDetail.classList.remove('hidden');

    try {
      const res = await customFetch(`/api/v1/assessments/responses/${attemptId}`);
      if (!res.ok) {
        responseDetailContent.innerHTML = `<p style="color: var(--danger); padding: 1rem;">Failed to fetch attempt details.</p>`;
        return;
      }
      const data = await res.json();
      const att = data.attempt;

      let html = `
        <div style="background: var(--bg-dark); padding: 1rem; border: 1px solid var(--border-color); margin-bottom: 1rem;">
          <div style="display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;">
            <div>
              <strong>Student:</strong> ${att.student_email}<br>
              <strong>Assessment:</strong> [${att.exam_code}] ${att.assessment_title}
            </div>
            <div>
              <strong>Status:</strong> <span class="user-badge ${att.status === 'submitted' ? 'admin' : 'guest'}">${att.status.toUpperCase()}</span><br>
              <strong>Final Score:</strong> <span class="user-badge ${att.percentage >= 80 ? 'admin' : 'creator'}">${att.score} / ${att.total_questions} (${att.percentage}%)</span>
            </div>
          </div>
        </div>

        <h4 style="margin-bottom: 1rem;">Question-by-Question Response Audit</h4>
        <div style="display: flex; flex-direction: column; gap: 1rem;">
      `;

      att.questions.forEach((q, idx) => {
        const verdictClass = q.is_correct_choice ? 'admin' : (q.selected_option_id ? 'guest' : 'guest');
        const verdictLabel = q.is_correct_choice ? 'CORRECT (+1.0)' : (q.selected_option_id ? 'INCORRECT (0.0)' : 'UNANSWERED (0.0)');
        const borderColor = q.is_correct_choice ? 'var(--success)' : (q.selected_option_id ? 'var(--danger)' : 'var(--warning)');

        html += `
          <div class="card" style="padding: 1rem; border-left: 4px solid ${borderColor};">
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem; gap: 0.5rem; align-items: flex-start;">
              <strong>Q${idx + 1}. ${q.text}</strong>
              <span class="user-badge ${verdictClass}">${verdictLabel}</span>
            </div>

            <div style="display: flex; flex-direction: column; gap: 0.25rem; margin: 0.5rem 0;">
        `;

        q.options.forEach(opt => {
          const isSelected = q.selected_option_id === opt.id;
          const isCorrect = opt.is_correct === 1;

          let optStyle = "padding: 6px 10px; border: 1px solid var(--border-color); background: white;";
          if (isCorrect && isSelected) {
            optStyle = "padding: 6px 10px; border: 2px solid var(--success); background: #dcfce7; font-weight: bold; color: #15803d;";
          } else if (isCorrect) {
            optStyle = "padding: 6px 10px; border: 2px dashed var(--success); background: #f0fdf4; color: #15803d;";
          } else if (isSelected) {
            optStyle = "padding: 6px 10px; border: 2px solid var(--danger); background: #fee2e2; color: #b91c1c;";
          }

          html += `
            <div style="${optStyle}">
              ${isSelected ? '<strong>[STUDENT SELECTION]</strong> ' : ''}
              ${isCorrect ? '<strong>[CORRECT ANSWER]</strong> ' : ''}
              ${opt.text}
            </div>
          `;
        });

        html += `
            </div>
            ${q.reason ? `<small style="color: var(--text-muted); display: block; margin-top: 0.25rem;"><strong>Reason:</strong> ${q.reason}</small>` : ''}
          </div>
        `;
      });

      html += `</div>`;
      responseDetailContent.innerHTML = html;

    } catch (e) {
      responseDetailContent.innerHTML = `<p style="color: var(--danger); padding: 1rem;">Error loading response breakdown.</p>`;
    }
  }

  if (btnCloseResponseModal) {
    btnCloseResponseModal.addEventListener('click', () => modalResponseDetail.classList.add('hidden'));
  }

  // Admin Controls
  async function loadAdminData() {
    loadAllowlist();
    loadAdminAttempts();
    loadAuditLogs();
  }

  async function loadAllowlist() {
    try {
      const res = await customFetch('/api/v1/admin/allowlist');
      if (!res.ok) return;
      const data = await res.json();
      tableAllowlistBody.innerHTML = '';
      data.allowlist.forEach(item => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${item.email}</strong></td>
          <td>${item.added_by}</td>
          <td><span class="user-badge ${item.status === 'active' ? 'admin' : 'guest'}">${item.status}</span></td>
          <td>${new Date(item.added_at).toLocaleString()}</td>
          <td>
            ${item.status === 'active' ? 
              `<button class="btn btn-sm btn-danger btn-revoke-email" data-email="${item.email}">Revoke</button>` :
              `<button class="btn btn-sm btn-outline btn-add-email" data-email="${item.email}">Re-activate</button>`}
          </td>
        `;
        tableAllowlistBody.appendChild(tr);
      });

      tableAllowlistBody.querySelectorAll('.btn-revoke-email').forEach(btn => {
        btn.addEventListener('click', () => updateAllowlistStatus(btn.dataset.email, 'revoke'));
      });
      tableAllowlistBody.querySelectorAll('.btn-add-email').forEach(btn => {
        btn.addEventListener('click', () => updateAllowlistStatus(btn.dataset.email, 'add'));
      });
    } catch (e) {}
  }

  formAddAllowlist.addEventListener('submit', (e) => {
    e.preventDefault();
    const email = document.getElementById('input-allowlist-email').value.trim();
    updateAllowlistStatus(email, 'add');
  });

  async function updateAllowlistStatus(email, action) {
    try {
      const res = await customFetch('/api/v1/admin/allowlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, action })
      });
      if (res.ok) {
        showToast(`Allowlist updated for ${email}`, 'success');
        document.getElementById('input-allowlist-email').value = '';
        loadAllowlist();
      }
    } catch (e) {}
  }

  async function loadAdminAttempts() {
    try {
      const res = await customFetch('/api/v1/admin/attempts');
      if (!res.ok) return;
      const data = await res.json();
      tableAdminAttemptsBody.innerHTML = '';
      data.attempts.forEach(att => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>#${att.id}</td>
          <td class="code-font">${att.student_identifier.substring(0, 16)}...</td>
          <td><strong>${att.exam_code}</strong></td>
          <td><span class="status-indicator ${att.status === 'in_progress' ? 'warning' : att.status === 'submitted' ? 'success' : 'danger'}"></span> ${att.status}</td>
          <td>${new Date(att.started_at).toLocaleTimeString()}</td>
          <td>${att.submitted_at ? new Date(att.submitted_at).toLocaleTimeString() : '-'}</td>
          <td>
            <button class="btn btn-sm btn-outline btn-reset-attempt" data-id="${att.id}">Reset Attempt</button>
          </td>
        `;
        tableAdminAttemptsBody.appendChild(tr);
      });

      tableAdminAttemptsBody.querySelectorAll('.btn-reset-attempt').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (confirm(`Reset attempt #${btn.dataset.id} back to not_started?`)) {
            await resetAttempt(btn.dataset.id);
          }
        });
      });
    } catch (e) {}
  }

  async function resetAttempt(attemptId) {
    try {
      const res = await customFetch('/api/v1/admin/attempts/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ attemptId, newStatus: 'not_started' })
      });
      if (res.ok) {
        showToast(`Attempt #${attemptId} reset back to not_started`, 'success');
        loadAdminAttempts();
      }
    } catch (e) {}
  }

  async function loadAuditLogs() {
    try {
      const res = await customFetch('/api/v1/admin/audit-logs');
      if (!res.ok) return;
      const data = await res.json();
      tableAuditLogsBody.innerHTML = '';
      data.logs.forEach(log => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${new Date(log.timestamp).toLocaleTimeString()}</td>
          <td><strong style="color: var(--accent);">${log.event_type}</strong></td>
          <td>${log.actor}</td>
          <td>${log.exam_code || '-'}</td>
          <td style="max-width: 300px; word-break: break-all;">${log.details || ''}</td>
        `;
        tableAuditLogsBody.appendChild(tr);
      });
    } catch (e) {}
  }

  // Simulator
  let simGuid = localStorage.getItem('flylock_sim_guid');
  if (!simGuid) {
    simGuid = 'FLYLOCK-CLIENT-' + Math.random().toString(36).substring(2, 9).toUpperCase();
    localStorage.setItem('flylock_sim_guid', simGuid);
  }
  simClientId.value = simGuid;

  simBtnFetchToken.addEventListener('click', async () => {
    const examCode = simExamCode.value.trim();
    const clientId = simClientId.value.trim();

    simJsonOutput.textContent = `// Requesting single-use token from /api/v1/sessions/launch...`;

    try {
      const res = await customFetch('/api/v1/sessions/launch', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-FlyLock-Client': 'HMAC-SHA256-SIMULATED-SIGNATURE'
        },
        body: JSON.stringify({ examCode, clientId })
      });

      const data = await res.json();
      simJsonOutput.textContent = JSON.stringify(data, null, 2);

      if (!res.ok) {
        showToast(data.message || data.error, 'error');
        simBtnLaunchBrowser.disabled = true;
        simBtnTestReplay.disabled = true;
        return;
      }

      state.simulatedToken = data.launchToken;
      state.simulatedExamCode = examCode;

      simBtnLaunchBrowser.disabled = false;
      simBtnTestReplay.disabled = false;
      showToast('Single-use Launch Token obtained (45s TTL)!', 'success');
    } catch (err) {
      simJsonOutput.textContent = `// Launch token request failed: ${err.message}`;
    }
  });

  simBtnLaunchBrowser.addEventListener('click', () => {
    if (!state.simulatedToken) return;
    const targetUrl = `/index.html?code=${encodeURIComponent(state.simulatedExamCode)}&token=${encodeURIComponent(state.simulatedToken)}`;
    window.open(targetUrl, '_blank');
  });

  simBtnTestReplay.addEventListener('click', async () => {
    if (!state.simulatedToken) return;
    showToast('Attempting second redemption of burned token...', 'info');
    try {
      const res = await customFetch(`/assessment/verify?token=${encodeURIComponent(state.simulatedToken)}&code=${encodeURIComponent(state.simulatedExamCode)}`);
      const data = await res.json();
      if (!res.ok) {
        showToast(`Replay Blocked! Response: "${data.message}"`, 'success');
        simJsonOutput.textContent += `\n\n// REPLAY ATTACK TEST RESULT:\n` + JSON.stringify(data, null, 2);
      }
    } catch (e) {}
  });

  checkAuth();
  loadStudentResponses();
});