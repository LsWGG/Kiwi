/* Kiwi portal interactions — no dependencies. */
(() => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const finePointer = window.matchMedia('(pointer: fine)').matches;

  /* ---------- header + scroll progress ---------- */
  const header = document.querySelector('.site-header');
  const progressBar = document.querySelector('.scroll-progress span');

  const onScroll = () => {
    const y = window.scrollY;
    header?.classList.toggle('is-scrolled', y > 12);
    const max = document.documentElement.scrollHeight - window.innerHeight;
    if (progressBar) {
      progressBar.style.transform = `scaleX(${max > 0 ? Math.min(y / max, 1) : 0})`;
    }
  };

  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  /* ---------- mobile menu ---------- */
  const toggle = document.querySelector('.nav-toggle');
  const menu = document.getElementById('mobile-menu');

  const closeMenu = () => {
    if (!menu || !toggle) return;
    menu.classList.remove('is-open');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', '打开菜单');
  };

  toggle?.addEventListener('click', () => {
    if (!menu) return;
    const open = menu.classList.toggle('is-open');
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? '关闭菜单' : '打开菜单');
  });

  menu?.querySelectorAll('a').forEach((link) => link.addEventListener('click', closeMenu));

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeMenu();
  });

  window.addEventListener('resize', () => {
    if (window.innerWidth > 1120) closeMenu();
  });

  /* ---------- scroll reveal ---------- */
  const revealTargets = [...document.querySelectorAll('[data-reveal]')];

  if (reduceMotion || !('IntersectionObserver' in window)) {
    revealTargets.forEach((el) => el.classList.add('is-visible'));
  } else {
    const groupCounts = new Map();
    revealTargets.forEach((el) => {
      const parent = el.parentElement;
      const index = groupCounts.get(parent) || 0;
      groupCounts.set(parent, index + 1);
      el.style.setProperty('--delay', `${Math.min(index, 4) * 65}ms`);
    });

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -7% 0px' });

    revealTargets.forEach((el) => observer.observe(el));
  }

  /* ---------- nav scroll spy ---------- */
  const navLinks = [...document.querySelectorAll('.nav-links a[href^="#"]')];
  const linkById = new Map(navLinks.map((link) => [link.getAttribute('href').slice(1), link]));

  if ('IntersectionObserver' in window && navLinks.length) {
    const spy = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        navLinks.forEach((link) => link.classList.toggle('is-active', link === linkById.get(entry.target.id)));
      });
    }, { rootMargin: '-38% 0px -55% 0px', threshold: 0 });

    linkById.forEach((_, id) => {
      const section = document.getElementById(id);
      if (section) spy.observe(section);
    });
  }

  /* ---------- card spotlight ---------- */
  if (finePointer && !reduceMotion) {
    document.querySelectorAll('.bento-card').forEach((card) => {
      card.addEventListener('pointermove', (event) => {
        const rect = card.getBoundingClientRect();
        card.style.setProperty('--mx', `${event.clientX - rect.left}px`);
        card.style.setProperty('--my', `${event.clientY - rect.top}px`);
      });
    });
  }

  /* ---------- tabbed showcases (gallery + editor modes) ---------- */
  const setupShowcase = ({ showcaseTabs, image, panel, title, desc, count, start = 0 }) => {
    if (!showcaseTabs.length || !image || !panel) return;
    let active = start;
    let token = 0;
    showcaseTabs.forEach((tab, index) => {
      tab.classList.toggle('is-active', index === active);
      tab.setAttribute('aria-selected', String(index === active));
      tab.tabIndex = index === active ? 0 : -1;
    });

    const selectTab = (next, focus = false) => {
      if (next < 0 || next >= showcaseTabs.length || next === active) return;
      const tab = showcaseTabs[next];
      const previous = showcaseTabs[active];

      previous.classList.remove('is-active');
      previous.setAttribute('aria-selected', 'false');
      previous.tabIndex = -1;

      tab.classList.add('is-active');
      tab.setAttribute('aria-selected', 'true');
      tab.tabIndex = 0;
      if (focus) tab.focus();

      if (title) title.textContent = tab.dataset.title;
      if (desc) desc.textContent = tab.dataset.desc;
      if (count) count.textContent = `${String(next + 1).padStart(2, '0')} / ${String(showcaseTabs.length).padStart(2, '0')}`;
      panel.setAttribute('aria-labelledby', tab.id);

      const ticket = ++token;
      panel.classList.add('is-swapping');

      const preload = new Image();
      preload.src = tab.dataset.src;

      const commit = () => {
        if (ticket !== token) return;
        image.src = tab.dataset.src;
        image.alt = tab.dataset.alt;
        requestAnimationFrame(() => panel.classList.remove('is-swapping'));
      };

      if (preload.decode) {
        preload.decode().then(commit, commit);
      } else {
        preload.onload = commit;
        preload.onerror = commit;
      }

      active = next;
    };

    showcaseTabs.forEach((tab, index) => {
      tab.addEventListener('click', () => selectTab(index));
      tab.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
          event.preventDefault();
          selectTab((active + 1) % showcaseTabs.length, true);
        } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
          event.preventDefault();
          selectTab((active - 1 + showcaseTabs.length) % showcaseTabs.length, true);
        } else if (event.key === 'Home') {
          event.preventDefault();
          selectTab(0, true);
        } else if (event.key === 'End') {
          event.preventDefault();
          selectTab(showcaseTabs.length - 1, true);
        }
      });
    });

    const warm = () => showcaseTabs.forEach((tab) => { const preload = new Image(); preload.src = tab.dataset.src; });
    if ('requestIdleCallback' in window) {
      window.requestIdleCallback(warm, { timeout: 3000 });
    } else {
      window.addEventListener('load', warm, { once: true });
    }
  };

  const galleryTabs = [...document.querySelectorAll('.gallery-tab')];
  const galleryCount = document.getElementById('gallery-count');
  if (galleryCount && galleryTabs.length) {
    galleryCount.textContent = `01 / ${String(galleryTabs.length).padStart(2, '0')}`;
  }
  setupShowcase({
    showcaseTabs: galleryTabs,
    image: document.getElementById('gallery-image'),
    panel: document.getElementById('gallery-panel'),
    title: document.getElementById('gallery-title'),
    desc: document.getElementById('gallery-desc'),
    count: galleryCount,
  });

  setupShowcase({
    showcaseTabs: [...document.querySelectorAll('.editor-mode')],
    image: document.getElementById('editor-image'),
    panel: document.getElementById('editor-panel'),
    title: document.getElementById('editor-title'),
    desc: document.getElementById('editor-desc'),
    count: null,
  });

  /* ---------- terminal tabs ---------- */
  const terminalTabs = [...document.querySelectorAll('.terminal-tab')];
  const terminalPanels = [...document.querySelectorAll('.terminal-panel')];

  terminalTabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      terminalTabs.forEach((item) => {
        const selected = item === tab;
        item.classList.toggle('is-active', selected);
        item.setAttribute('aria-selected', String(selected));
      });
      terminalPanels.forEach((panel) => {
        const selected = panel.dataset.panel === tab.dataset.panelTab;
        panel.classList.toggle('is-active', selected);
        panel.hidden = !selected;
      });
    });
  });

  /* ---------- copy buttons ---------- */
  const copyText = async (text) => {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  };

  document.querySelectorAll('.copy-btn').forEach((button) => {
    button.addEventListener('click', async () => {
      const activePanel = document.querySelector('.terminal-tab.is-active');
      const commands = activePanel?.dataset.panelTab === 'docker'
        ? button.dataset.copyDocker
        : button.dataset.copyLocal;
      const label = button.querySelector('.copy-label');
      const original = label ? label.textContent : '';

      try {
        await copyText(commands || button.dataset.copy || '');
        button.classList.add('is-copied');
        if (label) label.textContent = '已复制';
      } catch {
        if (label) label.textContent = '复制失败';
      }

      window.setTimeout(() => {
        button.classList.remove('is-copied');
        if (label) label.textContent = original;
      }, 1800);
    });
  });

  /* ---------- starfield ---------- */
  const canvas = document.getElementById('starfield');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const TAU = Math.PI * 2;
  const palette = [
    [214, 226, 255], [214, 226, 255], [214, 226, 255], [214, 226, 255],
    [186, 245, 109], [92, 242, 182], [139, 149, 255], [200, 170, 255],
  ];

  let width = 0;
  let height = 0;
  let dpr = 1;
  let stars = [];
  let links = [];
  let raf = 0;
  let running = false;
  let pointerX = 0;
  let pointerY = 0;
  let targetX = 0;
  let targetY = 0;

  const build = () => {
    width = window.innerWidth;
    height = window.innerHeight;
    dpr = Math.min(window.devicePixelRatio || 1, 2);

    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const density = width < 720 ? 16000 : 11500;
    const count = Math.max(46, Math.min(170, Math.round((width * height) / density)));

    stars = Array.from({ length: count }, () => {
      const color = palette[Math.floor(Math.random() * palette.length)];
      return {
        x: Math.random() * width,
        y: Math.random() * height,
        r: Math.random() * 1.15 + 0.28,
        alpha: Math.random() * 0.5 + 0.16,
        speed: Math.random() * 0.85 + 0.25,
        phase: Math.random() * TAU,
        depth: Math.random() * 0.85 + 0.15,
        color: `${color[0]}, ${color[1]}, ${color[2]}`,
      };
    });

    links = [];
    for (let i = 0; i < stars.length; i += 1) {
      for (let j = i + 1; j < stars.length; j += 1) {
        if (links.length >= 46) break;
        const dx = stars[i].x - stars[j].x;
        const dy = stars[i].y - stars[j].y;
        if (Math.hypot(dx, dy) < 132 && Math.random() < 0.32) {
          links.push([i, j]);
        }
      }
      if (links.length >= 46) break;
    }
  };

  const draw = (time) => {
    ctx.clearRect(0, 0, width, height);

    pointerX += (targetX - pointerX) * 0.045;
    pointerY += (targetY - pointerY) * 0.045;

    ctx.lineWidth = 0.55;
    for (const [a, b] of links) {
      const starA = stars[a];
      const starB = stars[b];
      ctx.strokeStyle = 'rgba(148, 178, 255, 0.085)';
      ctx.beginPath();
      ctx.moveTo(starA.x + pointerX * starA.depth, starA.y + pointerY * starA.depth);
      ctx.lineTo(starB.x + pointerX * starB.depth, starB.y + pointerY * starB.depth);
      ctx.stroke();
    }

    for (const star of stars) {
      const twinkle = 0.64 + 0.36 * Math.sin(time * 0.00085 * star.speed + star.phase);
      const alpha = star.alpha * twinkle;
      const x = star.x + pointerX * star.depth;
      const y = star.y + pointerY * star.depth;

      if (star.r > 1.05) {
        ctx.beginPath();
        ctx.arc(x, y, star.r * 3.4, 0, TAU);
        ctx.fillStyle = `rgba(${star.color}, ${alpha * 0.055})`;
        ctx.fill();
      }

      ctx.beginPath();
      ctx.arc(x, y, star.r, 0, TAU);
      ctx.fillStyle = `rgba(${star.color}, ${alpha})`;
      ctx.fill();
    }
  };

  const frame = (time) => {
    draw(time);
    raf = window.requestAnimationFrame(frame);
  };

  const start = () => {
    if (running || reduceMotion) return;
    running = true;
    raf = window.requestAnimationFrame(frame);
  };

  const stop = () => {
    running = false;
    window.cancelAnimationFrame(raf);
  };

  build();
  draw(0);

  if (!reduceMotion) {
    start();

    if (finePointer) {
      window.addEventListener('pointermove', (event) => {
        targetX = (event.clientX / width - 0.5) * 16;
        targetY = (event.clientY / height - 0.5) * 12;
      }, { passive: true });
    }

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) stop();
      else start();
    });
  }

  let resizeTimer = 0;
  window.addEventListener('resize', () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      const wasRunning = running;
      stop();
      build();
      draw(performance.now());
      if (wasRunning) start();
    }, 180);
  });
})();
