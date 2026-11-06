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
                makeRedirect(btn, 'В библиотеке ➜', libraryUrl);
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
        clearBtn.style.display = query ? 'block' : 'none';

        // Отменяем ожидание и прошлый запрос, чтобы старый ответ не перезаписал новый
        clearTimeout(timer);
        if (controller) controller.abort();

        if (query.length < 2) {
            hideResults();
            return;
        }
        timer = setTimeout(() => runSearch(query), 200);
    });

    clearBtn.addEventListener('click', () => {
        searchInput.value = '';
        clearBtn.style.display = 'none';
        hideResults();
        searchInput.focus();
    });

    document.addEventListener('click', e => {
        if (!searchInput.contains(e.target) && !resultsDropdown.contains(e.target) && !clearBtn.contains(e.target)) {
            resultsDropdown.style.display = 'none';
        }
    });
});

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
