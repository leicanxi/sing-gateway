(() => {
  'use strict';

  const PAGE_SIZE = 60;
  const SEARCH_DEBOUNCE_MS = 120;
  const COPY_FEEDBACK_MS = 1600;

  const grid = document.getElementById('grid');
  const emptyBox = document.getElementById('empty');
  const emptyTitle = emptyBox.querySelector('.empty-title');
  const emptyText = emptyBox.querySelector('.empty-text');
  const statusLine = document.getElementById('status-line');
  const errorBox = document.getElementById('error-box');
  const errorText = document.getElementById('error-text');
  const retryButton = document.getElementById('retry-button');
  const resultCount = document.getElementById('result-count');
  const searchInput = document.getElementById('search');
  const sortSelect = document.getElementById('sort');
  const filterLanguage = document.getElementById('filter-language');
  const filterGender = document.getElementById('filter-gender');
  const loadMoreWrap = document.getElementById('load-more-wrap');
  const loadMoreButton = document.getElementById('load-more');
  const liveRegion = document.getElementById('live');
  const header = document.querySelector('.site-header');
  const catalogSection = document.querySelector('.catalog');
  const cardTemplate = document.getElementById('card-template');
  const communitySection = document.getElementById('community');
  const communityGrid = document.getElementById('community-grid');
  const communityStatus = document.getElementById('community-status');
  const communitySort = document.getElementById('community-sort');
  const communityTemplate = document.getElementById('community-card-template');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  const numberFormat = new Intl.NumberFormat('zh-CN');
  const copyTimers = new WeakMap();

  const LANGUAGE_LABEL = {
    zh: '中文',
    ja: '日语',
    en: '英语',
    ko: '韩语',
    es: '西班牙语',
    fr: '法语',
    de: '德语',
    ru: '俄语',
    pt: '葡萄牙语',
    it: '意大利语',
    other: '其他',
  };
  const GENDER_LABEL = {
    female: '女声',
    male: '男声',
    neutral: '中性',
  };

  let activeSort = 'hot';
  let activeLanguage = '';
  let activeGender = '';
  let query = '';
  let offset = 0;
  let total = 0;
  let loading = false;
  let requestSeq = 0;
  let searchTimer = 0;
  let composing = false;
  let state = 'idle';

  const previewAudio = new Audio();
  previewAudio.preload = 'none';
  let activeListenButton = null;

  function resetListenButton(button) {
    if (!button) return;
    button.classList.remove('is-playing');
    const label = button.querySelector('.listen-label');
    if (label) label.textContent = '试听';
  }

  function stopPreview() {
    previewAudio.pause();
    previewAudio.removeAttribute('src');
    previewAudio.load();
    resetListenButton(activeListenButton);
    activeListenButton = null;
  }

  function togglePreview(button) {
    if (!button || !button.dataset.url) return;
    if (activeListenButton === button && !previewAudio.paused) {
      stopPreview();
      return;
    }
    stopPreview();
    activeListenButton = button;
    button.classList.remove('is-error');
    button.classList.add('is-playing');
    const label = button.querySelector('.listen-label');
    if (label) label.textContent = '暂停';
    liveRegion.textContent = `正在试听 ${button.dataset.label || ''}`;
    previewAudio.src = button.dataset.url;
    previewAudio.play().catch(() => {
      if (activeListenButton !== button) return;
      button.classList.remove('is-playing');
      button.classList.add('is-error');
      if (label) label.textContent = '试听失败';
      liveRegion.textContent = '试听加载失败，请换个音色试试';
      activeListenButton = null;
    });
  }

  previewAudio.addEventListener('ended', stopPreview);
  previewAudio.addEventListener('error', () => {
    if (!activeListenButton) return;
    const button = activeListenButton;
    button.classList.remove('is-playing');
    button.classList.add('is-error');
    const label = button.querySelector('.listen-label');
    if (label) label.textContent = '试听失败';
    activeListenButton = null;
  });

  function itemChips(item, limit) {
    const chips = [];
    const language = LANGUAGE_LABEL[item.language];
    if (language) chips.push(language);
    const gender = GENDER_LABEL[item.gender];
    if (gender) chips.push(gender);
    if (item.type === 'instrumental') chips.push('乐器');
    if (item.rvc_version) chips.push(String(item.rvc_version).toUpperCase());
    for (const raw of item.tags || []) {
      const tag = String(raw || '').trim();
      if (tag && !chips.includes(tag)) chips.push(tag);
    }
    return chips.slice(0, limit || 5);
  }

  function updateLoadMore() {
    const remaining = Math.max(0, total - offset);
    if (remaining <= 0) {
      loadMoreWrap.hidden = true;
      return;
    }
    loadMoreWrap.hidden = false;
    loadMoreButton.textContent = `加载更多（还有 ${numberFormat.format(remaining)} 个）`;
  }

  async function loadPage(reset) {
    if (!reset && loading) return;
    const seq = ++requestSeq;
    loading = true;
    const start = reset ? 0 : offset;

    if (reset) {
      stopPreview();
      offset = 0;
      total = 0;
      state = 'loading';
      grid.replaceChildren();
      emptyBox.hidden = true;
      errorBox.hidden = true;
      loadMoreWrap.hidden = true;
      statusLine.hidden = false;
      statusLine.textContent = '正在加载音色目录…';
      resultCount.textContent = '正在加载…';
    }

    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(start),
      sort: activeSort,
    });
    if (query) params.set('q', query);
    if (activeLanguage) params.set('lang', activeLanguage);
    if (activeGender) params.set('gender', activeGender);

    try {
      const response = await fetch(`/v1/voices/catalog?${params.toString()}`, {
        cache: 'no-store',
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      if (seq !== requestSeq) return;

      const items = Array.isArray(payload.items) ? payload.items : [];
      total = Number(payload.total) || 0;
      if (reset) grid.replaceChildren();
      const fragment = document.createDocumentFragment();
      for (const item of items) {
        fragment.appendChild(createCard(item));
      }
      grid.appendChild(fragment);

      const next = payload.next_offset;
      offset = next === null || next === undefined ? start + items.length : Number(next);
      state = 'ready';
      statusLine.hidden = true;
      errorBox.hidden = true;
      emptyBox.hidden = total !== 0;

      const filtered = Boolean(query || activeLanguage || activeGender);
      emptyTitle.textContent = filtered ? '没有找到匹配的音色' : '音色目录暂无内容';
      emptyText.hidden = !filtered;
      resultCount.textContent = filtered
        ? `找到 ${numberFormat.format(total)} 个音色`
        : `共 ${numberFormat.format(total)} 个音色`;
      updateLoadMore();

      if (!reset && items.length) {
        liveRegion.textContent = `已加载 ${numberFormat.format(items.length)} 个音色`;
      }
    } catch (error) {
      if (seq !== requestSeq) return;
      console.error('加载音色目录失败：', error);
      if (reset) {
        state = 'error';
        grid.replaceChildren();
        emptyBox.hidden = true;
        loadMoreWrap.hidden = true;
        statusLine.hidden = true;
        errorText.textContent = '音色目录加载失败，请检查网络后重试。';
        errorBox.hidden = false;
        resultCount.textContent = '加载失败';
      } else {
        liveRegion.textContent = '加载更多失败，请重试';
      }
    } finally {
      if (seq === requestSeq) loading = false;
    }
  }

  function appendChips(container, item, limit) {
    if (!container) return;
    for (const tag of itemChips(item, limit)) {
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.textContent = tag;
      container.appendChild(chip);
    }
  }

  function createCard(item) {
    const card = cardTemplate.content.firstElementChild.cloneNode(true);

    const label = card.querySelector('.card-label');
    label.textContent = item.label || item.name;
    label.title = label.textContent;

    const favorites = Number(item.favorites) || 0;
    const favBox = card.querySelector('.card-fav');
    if (favorites > 0) {
      const text = numberFormat.format(favorites);
      favBox.querySelector('.fav-count').textContent = text;
      favBox.title = `上游收藏 ${text}`;
    } else {
      favBox.remove();
    }

    appendChips(card.querySelector('.chips'), item, 4);

    const slug = card.querySelector('.slug');
    slug.textContent = item.name;
    slug.title = item.name;

    const copyButton = card.querySelector('.copy');
    copyButton.dataset.slug = item.name;
    copyButton.setAttribute('aria-label', `复制音色名 ${item.name}`);

    const listen = card.querySelector('.listen');
    if (item.preview_url) {
      listen.hidden = false;
      listen.dataset.url = item.preview_url;
      listen.dataset.label = item.label || item.name;
      listen.setAttribute('aria-label', `试听 ${item.label || item.name}`);
    } else {
      listen.remove();
    }

    const download = card.querySelector('.download');
    const foot = card.querySelector('.card-foot');
    if (item.url) {
      download.href = item.url;
    } else {
      download.remove();
    }
    if (foot && !foot.querySelector('.listen') && !foot.querySelector('.download')) {
      foot.remove();
    }

    return card;
  }

  function createCommunityCard(item) {
    const card = communityTemplate.content.firstElementChild.cloneNode(true);

    const label = card.querySelector('.card-label');
    label.textContent = item.label || item.name;
    label.title = label.textContent;

    const author = card.querySelector('.card-author');
    author.textContent = item.author || '社区投稿';

    const usesCount = Number(item.uses) || 0;
    card.querySelector('.uses-count').textContent = numberFormat.format(usesCount);
    card.querySelector('.card-uses').title = `被点歌 ${numberFormat.format(usesCount)} 次`;

    appendChips(card.querySelector('.chips'), item, 6);

    const slug = card.querySelector('.slug');
    slug.textContent = item.name;
    slug.title = item.name;

    const copy = card.querySelector('.copy');
    copy.dataset.slug = item.name;
    copy.setAttribute('aria-label', `复制音色名 ${item.name}`);

    return card;
  }

  function renderCommunity(items) {
    communityGrid.replaceChildren();
    if (!items.length) {
      communitySection.hidden = true;
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const item of items) {
      fragment.appendChild(createCommunityCard(item));
    }
    communityGrid.appendChild(fragment);
    communitySection.hidden = false;
    communityStatus.hidden = true;
  }

  async function loadCommunity() {
    communityStatus.hidden = false;
    communityStatus.textContent = '正在加载社区公开音色…';
    try {
      const response = await fetch(
        `/v1/voices/public?limit=24&sort=${encodeURIComponent(communitySort.value)}`,
        { cache: 'no-store' }
      );
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      renderCommunity(Array.isArray(payload.voices) ? payload.voices : []);
    } catch (error) {
      console.warn('加载社区公开音色失败：', error);
      communitySection.hidden = true;
    }
  }

  function scheduleSearch() {
    clearTimeout(searchTimer);
    searchTimer = window.setTimeout(async () => {
      const nextQuery = searchInput.value.trim().toLowerCase();
      if (nextQuery === query) return;
      query = nextQuery;
      await loadPage(true);
      revealResultsIfNeeded();
    }, SEARCH_DEBOUNCE_MS);
  }

  function revealResultsIfNeeded() {
    if (state !== 'ready' || window.scrollY === 0) return;
    const headerHeight = header.offsetHeight;
    const top = catalogSection.getBoundingClientRect().top;
    if (top >= headerHeight) return;
    window.scrollTo({
      top: window.scrollY + top - headerHeight - 8,
      behavior: reducedMotion.matches ? 'auto' : 'smooth',
    });
  }

  async function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (_) {
        // Fall through to the legacy path.
      }
    }

    const helper = document.createElement('textarea');
    helper.value = text;
    helper.setAttribute('readonly', '');
    helper.style.position = 'fixed';
    helper.style.top = '-9999px';
    helper.style.opacity = '0';
    document.body.appendChild(helper);
    try {
      helper.select();
      helper.setSelectionRange(0, helper.value.length);
      return document.execCommand('copy');
    } catch (_) {
      return false;
    } finally {
      helper.remove();
    }
  }

  function showCopyFeedback(button, succeeded, slug) {
    clearTimeout(copyTimers.get(button));
    button.textContent = succeeded ? '已复制' : '复制失败';
    button.classList.toggle('is-copied', succeeded);
    button.classList.toggle('is-error', !succeeded);
    liveRegion.textContent = succeeded
      ? `已复制音色名 ${slug}`
      : `复制音色名 ${slug} 失败，请手动选择复制`;

    copyTimers.set(button, window.setTimeout(() => {
      button.textContent = '复制';
      button.classList.remove('is-copied', 'is-error');
      copyTimers.delete(button);
    }, COPY_FEEDBACK_MS));
  }

  function handleCopyClick(event) {
    const container = event.currentTarget;
    const target = event.target instanceof Element ? event.target.closest('.copy') : null;
    if (!target || !container.contains(target)) return;
    const slug = target.dataset.slug;
    if (!slug) return;
    copyToClipboard(slug).then((succeeded) => showCopyFeedback(target, succeeded, slug));
  }

  grid.addEventListener('click', handleCopyClick);
  communityGrid.addEventListener('click', handleCopyClick);

  grid.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target.closest('.listen') : null;
    if (!target || !grid.contains(target)) return;
    togglePreview(target);
  });

  searchInput.addEventListener('compositionstart', () => {
    composing = true;
  });

  searchInput.addEventListener('compositionend', () => {
    composing = false;
    scheduleSearch();
  });

  searchInput.addEventListener('input', () => {
    if (!composing) scheduleSearch();
  });

  sortSelect.addEventListener('change', async () => {
    activeSort = sortSelect.value;
    await loadPage(true);
    revealResultsIfNeeded();
  });

  filterLanguage.addEventListener('change', async () => {
    activeLanguage = filterLanguage.value;
    await loadPage(true);
    revealResultsIfNeeded();
  });

  filterGender.addEventListener('change', async () => {
    activeGender = filterGender.value;
    await loadPage(true);
    revealResultsIfNeeded();
  });

  communitySort.addEventListener('change', loadCommunity);

  loadMoreButton.addEventListener('click', async () => {
    await loadPage(false);
    revealResultsIfNeeded();
  });

  retryButton.addEventListener('click', () => loadPage(true));

  loadPage(true);
  loadCommunity();
})();
