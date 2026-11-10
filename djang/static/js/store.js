// Общие скрипты магазина: уведомления, корзина, желаемое и живой поиск.

// POST-запрос с CSRF. Анонимного пользователя отправляет на вход и возвращает обратно.
window.gsPost = async function (url, body) {
    const response = await fetch(url, {
        method: 'POST',
        body,
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content,
        },
    });

    if (response.status === 401) {
        const next = window.location.pathname + window.location.search;
        window.location.href = `${document.body.dataset.loginUrl}?next=${encodeURIComponent(next)}`;
        return {status: 'login_required'};
    }

    try {
        return await response.json();
    } catch (error) {
        return {status: 'error'};
    }
};

// То же уведомление, что и у сообщений Django в base.html
window.gsToast = function (text, tag = 'error') {
    let stack = document.querySelector('.messages-stack');
    if (!stack) {
        stack = document.createElement('div');
        stack.className = 'messages-stack';
        stack.setAttribute('role', 'status');
        document.body.appendChild(stack);
    }
    const toast = document.createElement('div');
    toast.className = `message-toast ${tag}`;
    toast.textContent = text;
    stack.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
};

document.addEventListener('DOMContentLoaded', () => {
    const { cartUrl, libraryUrl } = document.body.dataset;

    const esc = s => String(s).replace(/[&<>"']/g, c =>
        ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

    // ---------- Кнопки "В корзину" и переходы ----------
    function makeRedirect(btn, text, url) {
        btn.textContent = text;
        btn.classList.remove('js-add-to-cart');
        btn.classList.add('js-redirect');
        btn.dataset.url = url;
    }

    document.addEventListener('click', async e => {
        const btn = e.target.closest('.js-add-to-cart, .js-redirect');
        if (!btn) return;
        e.preventDefault();

        if (btn.classList.contains('js-redirect')) {
            window.location.href = btn.dataset.url;
            return;
        }

        btn.disabled = true;
        try {
            const data = await window.gsPost(btn.dataset.url);
            if (data.status === 'owned') {
                btn.classList.add('owned');
                // сразу на страницу этой игры в библиотеке, а не на библиотеку вообще
                const gameId = btn.dataset.gameId;
                makeRedirect(btn, 'В библиотеке ➜', gameId ? `${libraryUrl}?active=${gameId}` : libraryUrl);
            } else if (data.status === 'ok') {
                btn.classList.add('in-cart');
                makeRedirect(btn, '✓ Добавлено', cartUrl);

                // счётчик есть и в шапке, и у мобильной иконки корзины
                document.querySelectorAll('.cart-badge').forEach(badge => {
                    badge.textContent = data.cart_count;
                    badge.style.display = 'inline-block';
                });
            } else if (data.status !== 'login_required') {
                window.gsToast(data.message || 'Не удалось добавить игру в корзину');
            }
        } catch (error) {
            console.error('Ошибка добавления в корзину:', error);
            window.gsToast('Не удалось добавить игру в корзину');
        } finally {
            btn.disabled = false;
        }
    });

    // ---------- Желаемое ----------
    document.addEventListener('click', async e => {
        const btn = e.target.closest('.js-wishlist-toggle');
        if (!btn) return;
        e.preventDefault();  // кнопка может лежать внутри карточки-ссылки

        btn.disabled = true;
        try {
            const data = await window.gsPost(btn.dataset.url);
            if (data.status === 'success') {
                if (!data.in_wishlist && btn.hasAttribute('data-reload-on-remove')) {
                    window.location.reload();
                    return;
                }
                btn.classList.toggle('active', data.in_wishlist);
                btn.setAttribute('aria-pressed', data.in_wishlist);
                // сердце закрашивается через .active; у кнопки на странице игры ещё меняется надпись
                const label = btn.querySelector('.js-wishlist-label');
                if (label) label.textContent = data.in_wishlist ? btn.dataset.on : btn.dataset.off;
            } else if (data.status !== 'login_required') {
                window.gsToast(data.message || 'Не удалось обновить список желаемого');
            }
        } catch (error) {
            console.error('Ошибка списка желаемого:', error);
            window.gsToast('Не удалось обновить список желаемого');
        } finally {
            btn.disabled = false;
        }
    });

    // ---------- Поля поиска: крестик очистки и кнопка лупы ----------
    // Крестик виден, пока в поле есть текст. Если страница уже отфильтрована по запросу
    // (каталог, новости), очистка сразу отправляет форму, чтобы сбросить результаты.
    document.querySelectorAll('.search-box').forEach(box => {
        const input = box.querySelector('input[type="search"]');
        const clear = box.querySelector('.clear-search-btn');
        if (!input || !clear) return;

        const sync = () => { clear.hidden = !input.value; };
        sync();
        input.addEventListener('input', sync);

        clear.addEventListener('click', () => {
            const hadQuery = input.defaultValue !== '';
            input.value = '';
            input.dispatchEvent(new Event('input', {bubbles: true}));
            input.focus();
            if (hadQuery && input.form) input.form.requestSubmit();
        });

        // Лупа у живого поиска (без формы) просто повторяет поиск
        const trigger = box.querySelector('[data-search-trigger]');
        if (trigger) {
            trigger.addEventListener('click', () => {
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.focus();
            });
        }
    });

    // ---------- Живой поиск ----------
    const searchInput = document.getElementById('game-search-input');
    const resultsDropdown = document.getElementById('search-results-dropdown');
    const clearBtn = document.getElementById('clear-search');
    if (!searchInput || !resultsDropdown || !clearBtn) return;

    let timer;
    let controller = null;

    function hideResults() {
        resultsDropdown.innerHTML = '';
        resultsDropdown.style.display = 'none';
    }

    function renderGame(game) {
        const cover = game.cover_url
            ? `<img src="${esc(game.cover_url)}" class="search-result-cover" alt="">`
            : '';
        return `
            <a href="/game/${Number(game.id)}/" class="search-result-item">
                <div class="search-cover-wrapper">${cover}</div>
                <div class="search-result-info">
                    <span class="search-title">${esc(game.title)}</span>
                </div>
                <div class="search-result-right">
                    <div class="search-badges">
                        ${game.discount ? `<span class="badge badge-discount">-${Number(game.discount)}%</span>` : ''}
                    </div>
                    <div class="search-price-block">
                        ${game.old_price ? `<span class="old-price">${Number(game.old_price)}₴</span>` : ''}
                        <span class="search-price">${Number(game.price)}₴</span>
                    </div>
                </div>
            </a>
        `;
    }

    async function runSearch(query) {
        controller = new AbortController();
        try {
            const url = `${searchInput.dataset.searchUrl}?q=${encodeURIComponent(query)}`;
            const response = await fetch(url, {signal: controller.signal});
            const data = await response.json();

            if (data.games && data.games.length > 0) {
                resultsDropdown.innerHTML = data.games.map(renderGame).join('');
                resultsDropdown.style.display = 'block';
            } else {
                hideResults();
            }
        } catch (error) {
            if (error.name !== 'AbortError') console.error('Ошибка поиска:', error);
        }
    }

    searchInput.addEventListener('input', () => {
        const query = searchInput.value.trim();

        // Отменяем ожидание и прошлый запрос, чтобы старый ответ не перезаписал новый
        clearTimeout(timer);
        if (controller) controller.abort();

        if (query.length < 2) {
            hideResults();
            return;
        }
        timer = setTimeout(() => runSearch(query), 200);
    });

    document.addEventListener('click', e => {
        if (!searchInput.contains(e.target) && !resultsDropdown.contains(e.target) && !clearBtn.contains(e.target)) {
            resultsDropdown.style.display = 'none';
        }
    });
});

// ---------- Подсказки «?» ----------
// Значок .hint хранит текст в data-hint. Окошко одно на страницу и висит прямо в body: так его
// не обрезают карточки с overflow: hidden. Показ — при наведении, фокусе с клавиатуры или нажатии
// (на телефоне), скрытие — когда курсор ушёл, при прокрутке, Esc или нажатии в другом месте.
(() => {
    let bubble = null;
    let current = null;

    function place(hint) {
        const gap = 8;
        const icon = hint.getBoundingClientRect();
        const box = bubble.getBoundingClientRect();
        const left = Math.min(Math.max(gap, icon.left + icon.width / 2 - box.width / 2), window.innerWidth - box.width - gap);
        let top = icon.top - box.height - gap;
        if (top < gap) top = icon.bottom + gap;  // сверху не помещается — показываем снизу
        bubble.style.left = `${left}px`;
        bubble.style.top = `${top}px`;
    }

    function show(hint) {
        if (!bubble) {
            bubble = document.createElement('div');
            bubble.className = 'hint-bubble';
            bubble.id = 'hintBubble';
            bubble.setAttribute('role', 'tooltip');
            document.body.append(bubble);
        }
        current?.classList.remove('hint-open');
        current = hint;
        hint.classList.add('hint-open');
        bubble.replaceChildren();
        if (hint.dataset.hintTitle) {
            const title = document.createElement('div');
            title.className = 'hint-bubble-title';
            title.textContent = hint.dataset.hintTitle;
            bubble.append(title);
        }
        // Текст вида «вступление||Пункт — пояснение||…»: пункты раскладываются колонками
        const [intro, ...items] = hint.dataset.hint.split('||');
        const text = document.createElement('div');
        text.className = 'hint-bubble-text';
        text.textContent = intro;
        bubble.append(text);
        bubble.classList.toggle('hint-bubble-wide', items.length > 0);
        if (items.length) {
            const cols = document.createElement('div');
            cols.className = 'hint-bubble-cols';
            items.forEach(item => {
                const [rawHead, ...rest] = item.split(' — ');
                const col = document.createElement('div');
                const title = document.createElement('strong');
                // «{creator}Создатель» — значок роли из спрайта _role_icons.html и подпись
                const role = rawHead.match(/^\{(creator|admin|user)\}/);
                const head = role ? rawHead.slice(role[0].length) : rawHead;
                if (role) {
                    const svgNS = 'http://www.w3.org/2000/svg';
                    const icon = document.createElementNS(svgNS, 'svg');
                    icon.setAttribute('class', `role-icon role-icon-${role[1]}`);
                    icon.setAttribute('aria-hidden', 'true');
                    const use = document.createElementNS(svgNS, 'use');
                    use.setAttribute('href', `#role-${role[1]}`);
                    icon.append(use);
                    title.append(icon);
                }
                title.append(head);
                col.append(title, document.createTextNode(rest.join(' — ')));
                cols.append(col);
            });
            bubble.append(cols);
        }
        bubble.classList.add('is-visible');
        place(hint);
    }

    function hide() {
        if (!current) return;
        current.classList.remove('hint-open');
        current = null;
        bubble.classList.remove('is-visible');
    }

    document.addEventListener('mouseover', e => {
        const hint = e.target.closest('.hint');
        if (hint && hint !== current) show(hint);
    });
    document.addEventListener('mouseout', e => {
        const hint = e.target.closest('.hint');
        if (hint && hint === current && document.activeElement !== hint) hide();
    });
    document.addEventListener('focusin', e => { if (e.target.matches?.('.hint')) show(e.target); });
    document.addEventListener('focusout', e => { if (e.target === current) hide(); });

    // Нажатие на значок не должно срабатывать как нажатие на ссылку или подпись вокруг него
    document.addEventListener('click', e => {
        const hint = e.target.closest('.hint');
        if (hint) {
            e.preventDefault();
            e.stopPropagation();
            show(hint);
        } else {
            hide();
        }
    }, true);
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') hide();
        if ((e.key === 'Enter' || e.key === ' ') && e.target.matches?.('.hint')) {
            e.preventDefault();
            show(e.target);
        }
    });
    window.addEventListener('scroll', hide, {passive: true});
    window.addEventListener('resize', hide);
})();

// ---------- Просмотр картинок на весь экран ----------
// window.gsLightbox.open(urls, index). Любая ссылка или картинка с data-lightbox="группа" и
// data-original открывает просмотр по нажатию; стрелки листают картинки той же группы.
(() => {
    let box, img, counter, urls = [], index = 0, lastFocus = null;

    function build() {
        box = document.createElement('div');
        box.className = 'lightbox';
        box.hidden = true;
        box.setAttribute('role', 'dialog');
        box.setAttribute('aria-modal', 'true');
        box.setAttribute('aria-label', 'Просмотр картинки');
        box.innerHTML = `
            <button type="button" class="lightbox-btn lightbox-close" aria-label="Закрыть">×</button>
            <button type="button" class="lightbox-btn lightbox-prev" aria-label="Предыдущая">‹</button>
            <img class="lightbox-img" alt="">
            <button type="button" class="lightbox-btn lightbox-next" aria-label="Следующая">›</button>
            <div class="lightbox-counter" aria-live="polite"></div>`;
        document.body.append(box);
        img = box.querySelector('.lightbox-img');
        counter = box.querySelector('.lightbox-counter');

        box.querySelector('.lightbox-close').addEventListener('click', close);
        box.querySelector('.lightbox-prev').addEventListener('click', () => show(index - 1));
        box.querySelector('.lightbox-next').addEventListener('click', () => show(index + 1));
        // нажатие по тёмному фону вокруг картинки закрывает просмотр
        box.addEventListener('click', e => { if (e.target === box) close(); });

        // на телефоне — листание свайпом
        let startX = null;
        box.addEventListener('touchstart', e => { startX = e.touches[0].clientX; }, {passive: true});
        box.addEventListener('touchend', e => {
            if (startX === null) return;
            const dx = e.changedTouches[0].clientX - startX;
            if (Math.abs(dx) > 50) show(index + (dx < 0 ? 1 : -1));
            startX = null;
        });
    }

    function show(i) {
        index = (i + urls.length) % urls.length;
        img.src = urls[index];
        const several = urls.length > 1;
        counter.textContent = several ? `${index + 1} / ${urls.length}` : '';
        box.querySelectorAll('.lightbox-prev, .lightbox-next').forEach(btn => { btn.hidden = !several; });
    }

    function open(list, start = 0) {
        if (!list.length) return;
        if (!box) build();
        urls = list;
        lastFocus = document.activeElement;
        box.hidden = false;
        document.body.style.overflow = 'hidden';
        show(start);
        box.querySelector('.lightbox-close').focus();
    }

    function close() {
        if (!box || box.hidden) return;
        box.hidden = true;
        img.removeAttribute('src');
        document.body.style.overflow = '';
        lastFocus?.focus?.();
    }

    document.addEventListener('keydown', e => {
        if (!box || box.hidden) return;
        if (e.key === 'Escape') close();
        else if (e.key === 'ArrowLeft') show(index - 1);
        else if (e.key === 'ArrowRight') show(index + 1);
    });

    // Ссылки-миниатюры (например, скриншоты в библиотеке)
    document.addEventListener('click', e => {
        const item = e.target.closest('a[data-lightbox]');
        if (!item) return;
        e.preventDefault();
        const group = [...document.querySelectorAll(`a[data-lightbox="${item.dataset.lightbox}"]`)];
        open(group.map(el => el.dataset.original), group.indexOf(item));
    });

    window.gsLightbox = {open, close};
})();

// ---------- Индикатор загрузки картинок и видео ----------
// Пока картинка не загрузилась, CSS рисует под ней белый индикатор. Здесь отмечаем загруженные
// (класс is-loaded), чтобы индикатор не просвечивал сквозь прозрачные PNG, и показываем его
// поверх видео, когда оно останавливается на подгрузку.
(() => {
    const done = el => el.classList.add('is-loaded');
    const isVideo = el => el.tagName === 'VIDEO';

    // load и error не всплывают, поэтому слушаем на фазе перехвата
    document.addEventListener('load', e => { if (e.target.tagName === 'IMG') done(e.target); }, true);
    document.addEventListener('error', e => {
        if (e.target.tagName === 'IMG') done(e.target);
        if (e.target.tagName === 'SOURCE') done(e.target.parentElement);  // видео не загрузилось
    }, true);
    document.addEventListener('loadedmetadata', e => { if (isVideo(e.target)) done(e.target); }, true);

    // Что успело загрузиться до запуска скрипта (в том числе из кэша)
    document.querySelectorAll('img').forEach(img => { if (img.complete && img.getAttribute('src')) done(img); });
    document.querySelectorAll('video').forEach(video => { if (video.readyState >= 1) done(video); });

    // Скрипт сменил картинку (обложка в библиотеке, галерея игры) — снова ждём загрузки
    new MutationObserver(changes => changes.forEach(c => c.target.classList.remove('is-loaded')))
        .observe(document.body, {subtree: true, attributes: true, attributeFilter: ['src']});

    document.addEventListener('waiting', e => {
        if (isVideo(e.target)) e.target.parentElement.classList.add('is-buffering');
    }, true);
    ['playing', 'pause', 'canplay', 'ended'].forEach(type => document.addEventListener(type, e => {
        if (isVideo(e.target)) e.target.parentElement.classList.remove('is-buffering');
    }, true));
})();

// ---------- Аватары ----------
// Если файл аватара пропал с сервера, вместо пустого кружка или подписи картинки показываем первую букву имени
(() => {
    const showLetter = img => {
        const letter = document.createElement('span');
        letter.textContent = img.dataset.letter;
        if (img.className) letter.className = img.className;
        if (img.id === 'avatarImg') letter.id = 'avatarLetter';
        img.replaceWith(letter);
    };
    // события error у картинок не всплывают, поэтому слушаем на этапе перехвата
    document.addEventListener('error', e => {
        if (e.target instanceof HTMLImageElement && e.target.dataset.letter) showLetter(e.target);
    }, true);
    // картинки, которые не загрузились ещё до этого скрипта
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('img[data-letter]').forEach(img => {
            if (img.complete && !img.naturalWidth) showLetter(img);
        });
    });
})();
