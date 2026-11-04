(() => {
  'use strict';

  const MAX_BYTES = 300 * 1024 * 1024;
  const form = document.getElementById('upload-form');
  const labelInput = document.getElementById('label');
  const authCard = document.getElementById('auth-card');
  const accountBar = document.getElementById('account-bar');
  const accountName = document.getElementById('account-name');
  const logoutButton = document.getElementById('logout-button');
  const loginBanner = document.getElementById('login-banner');
  const fileField = document.getElementById('file-field');
  const urlField = document.getElementById('url-field');
  const fileInput = document.getElementById('file');
  const urlInput = document.getElementById('url');
  const submitButton = document.getElementById('submit-button');
  const formStatus = document.getElementById('form-status');
  const progress = document.getElementById('progress');
  const progressBar = document.getElementById('progress-bar');
  const resultBox = document.getElementById('result-box');
  const resultTitle = document.getElementById('result-title');
  const resultReason = document.getElementById('result-reason');
  const resultNameRow = document.getElementById('result-name-row');
  const resultName = document.getElementById('result-name');
  const resultUsage = document.getElementById('result-usage');
  const copyName = document.getElementById('copy-name');
  const statusLine = document.getElementById('status-line');
  const liveRegion = document.getElementById('live');
  const descriptionInput = document.getElementById('description');
  const languageSelect = document.getElementById('language');
  const genderSelect = document.getElementById('gender');
  const tagsInput = document.getElementById('tags');
  const resultActions = document.getElementById('result-actions');
  const publishButton = document.getElementById('publish-button');
  const copyShare = document.getElementById('copy-share');
  const resultPublic = document.getElementById('result-public');

  let busy = false;
  let busyPublish = false;
  let account = null;
  let lastResult = null;

  function shareText(name) {
    return `用音色 ${name} 唱一首《歌名》试试：/点歌 歌名 ${name}`;
  }

  async function copyText(text, button) {
    const original = button.textContent || '复制';
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const helper = document.createElement('textarea');
        helper.value = text;
        helper.style.position = 'fixed';
        helper.style.top = '-9999px';
        document.body.appendChild(helper);
        helper.select();
        document.execCommand('copy');
        helper.remove();
      }
      button.textContent = '已复制';
      liveRegion.textContent = `已复制：${text}`;
      window.setTimeout(() => {
        button.textContent = original;
      }, 1600);
    } catch (_) {
      button.textContent = '复制失败';
    }
  }

  function currentMode() {
    const checked = form.querySelector('input[name="mode"]:checked');
    return checked ? checked.value : 'file';
  }

  function refreshMode() {
    const mode = currentMode();
    fileField.hidden = mode !== 'file';
    urlField.hidden = mode !== 'url';
  }

  form.querySelectorAll('input[name="mode"]').forEach((radio) => {
    radio.addEventListener('change', refreshMode);
  });

  function setStatus(text, isError) {
    formStatus.textContent = text;
    formStatus.classList.toggle('is-error', Boolean(isError));
  }

  function resetResult() {
    resultBox.hidden = true;
    resultTitle.textContent = '';
    resultReason.textContent = '';
    resultNameRow.hidden = true;
    resultUsage.hidden = true;
    resultActions.hidden = true;
    resultPublic.hidden = true;
    resultPublic.textContent = '';
    lastResult = null;
  }

  function showResult(payload) {
    resetResult();
    lastResult = payload;
    const approved = payload.status === 'approved';
    resultTitle.textContent = approved ? '审核通过，音色已可用 🎉' : '未通过审核';
    resultTitle.classList.toggle('is-rejected', !approved);
    resultReason.textContent = payload.reason || '';
    if (approved && payload.name) {
      resultName.textContent = payload.name;
      resultNameRow.hidden = false;
      resultUsage.hidden = false;
      resultActions.hidden = false;
      publishButton.disabled = false;
      const isPublic = payload.visibility === 'public';
      publishButton.hidden = isPublic;
      resultPublic.hidden = !isPublic;
      resultPublic.textContent = isPublic ? '已公开到广场' : '';
      liveRegion.textContent = `审核通过，音色名 ${payload.name}`;
    } else {
      liveRegion.textContent = '提交未通过审核';
    }
    resultBox.hidden = false;
  }

  function validate() {
    const label = labelInput.value.trim();
    if (!label) {
      setStatus('请填写音色显示名', true);
      labelInput.focus();
      return null;
    }
    const mode = currentMode();
    if (mode === 'file') {
      const file = fileInput.files && fileInput.files[0];
      if (!file) {
        setStatus('请选择要上传的 zip 文件', true);
        return null;
      }
      if (!/\.zip$/i.test(file.name)) {
        setStatus('仅支持 .zip 文件', true);
        return null;
      }
      if (file.size > MAX_BYTES) {
        setStatus('文件超过 300MB 上限', true);
        return null;
      }
    } else if (!/^https?:\/\//i.test(urlInput.value.trim())) {
      setStatus('请填写 http/https 直链', true);
      urlInput.focus();
      return null;
    }
    setStatus('');
    return { label, mode };
  }

  function submit() {
    if (busy) return;
    const data = validate();
    if (!data) return;
    busy = true;
    submitButton.disabled = true;
    progress.hidden = false;
    progressBar.style.width = '0%';
    setStatus('正在上传并审核…');
    resetResult();

    const body = new FormData();
    body.append('label', data.label);
    body.append('description', descriptionInput.value.trim());
    body.append('language', languageSelect.value);
    body.append('gender', genderSelect.value);
    body.append('tags', tagsInput.value.trim());
    if (data.mode === 'file') {
      body.append('file', fileInput.files[0]);
    } else {
      body.append('url', urlInput.value.trim());
    }

    const request = new XMLHttpRequest();
    request.open('POST', '/v1/voice-requests');
    request.responseType = 'json';
    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 100);
        progressBar.style.width = `${percent}%`;
        if (percent >= 100) setStatus('上传完成，正在审核…');
      }
    });
    request.addEventListener('load', () => {
      busy = false;
      submitButton.disabled = false;
      progress.hidden = true;
      const payload = request.response;
      if (request.status === 401) {
        account = null;
        showAuthGate('登录已过期，请重新登录后提交。');
        return;
      }
      if (request.status >= 200 && request.status < 300 && payload) {
        setStatus('');
        showResult(payload);
      } else {
        const detail = payload && (payload.detail || payload.error);
        setStatus(detail ? String(detail) : `提交失败（HTTP ${request.status}）`, true);
      }
    });
    request.addEventListener('error', () => {
      busy = false;
      submitButton.disabled = false;
      progress.hidden = true;
      setStatus('网络错误，请稍后重试', true);
    });
    request.send(body);
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    submit();
  });

  copyName.addEventListener('click', () => {
    const text = resultName.textContent || '';
    if (text) copyText(text, copyName);
  });

  copyShare.addEventListener('click', () => {
    if (lastResult && lastResult.name) {
      copyText(shareText(lastResult.name), copyShare);
    }
  });

  publishButton.addEventListener('click', async () => {
    if (!lastResult || !lastResult.id || busyPublish) return;
    busyPublish = true;
    publishButton.disabled = true;
    try {
      const response = await fetch(
        `/v1/voice-requests/${encodeURIComponent(lastResult.id)}/publish`,
        { method: 'POST' }
      );
      if (response.status === 401) {
        showAuthGate('登录已过期，请重新登录后操作。');
        return;
      }
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = payload && payload.detail;
        throw new Error(detail ? String(detail) : `HTTP ${response.status}`);
      }
      if (payload && payload.submission) {
        lastResult = { ...lastResult, ...payload.submission };
      }
      publishButton.hidden = true;
      resultPublic.hidden = false;
      resultPublic.textContent = '已公开到广场';
      liveRegion.textContent = `已公开音色 ${lastResult.name}`;
    } catch (error) {
      console.error('公开失败：', error);
      publishButton.disabled = false;
      loginBanner.hidden = false;
      loginBanner.textContent = `公开失败：${error.message || '请稍后重试'}`;
    } finally {
      busyPublish = false;
    }
  });

  async function loadStatus(requestId) {
    statusLine.hidden = false;
    statusLine.textContent = '正在查询提交状态…';
    try {
      const response = await fetch(`/v1/voice-requests/${encodeURIComponent(requestId)}`, {
        cache: 'no-cache',
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      statusLine.hidden = true;
      showResult(payload);
    } catch (error) {
      console.error('查询提交状态失败：', error);
      statusLine.textContent = '没有找到这条提交记录（链接可能不完整或已过期）。';
    }
  }

  function showAuthGate(message) {
    authCard.hidden = false;
    form.hidden = true;
    accountBar.hidden = true;
    if (message) {
      loginBanner.hidden = false;
      loginBanner.textContent = message;
    }
  }

  function showAccount(me) {
    account = me;
    authCard.hidden = true;
    loginBanner.hidden = true;
    form.hidden = false;
    accountBar.hidden = false;
    accountName.textContent = me.name || me.username;
  }

  async function checkAuth() {
    try {
      const response = await fetch('/v1/auth/me', { cache: 'no-store' });
      if (response.ok) {
        showAccount(await response.json());
        return;
      }
    } catch (_) {
      // fall through to the login gate
    }
    showAuthGate();
  }

  logoutButton.addEventListener('click', async () => {
    try {
      await fetch('/v1/auth/logout', { method: 'POST' });
    } catch (_) {
      // ignore; gate will show either way
    }
    account = null;
    showAuthGate();
  });

  refreshMode();
  const params = new URLSearchParams(window.location.search);
  if (params.get('login') === 'failed') {
    const reason = params.get('reason');
    loginBanner.hidden = false;
    loginBanner.textContent = reason ? `登录失败：${reason}` : '登录失败，请重试。';
  }
  const requestId = params.get('id');
  if (requestId) {
    loadStatus(requestId);
  }
  checkAuth();
})();
