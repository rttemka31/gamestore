// Общие скрипты магазина: корзина и живой поиск.
document.addEventListener('DOMContentLoaded', () => {
    const { cartUrl, libraryUrl, loginUrl } = document.body.dataset;
    const csrfToken = document.querySelector('meta[name="csrf-token"]').content;

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
            const response = await fetch(btn.dataset.url, {
                method: 'POST',
                headers: {'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrfToken},
            });

            if (response.status === 401) {
                const next = window.location.pathname + window.location.search;
                window.location.href = `${loginUrl}?next=${encodeURIComponent(next)}`;
                return;
            }
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();
            if (data.status === 'owned') {
                btn.classList.add('owned');
                makeRedirect(btn, 'В библиотеке ➜', libraryUrl);
                return;
            }

            btn.classList.add('in-cart');
            makeRedirect(btn, '✓ Добавлено', cartUrl);

            const badge = document.querySelector('.cart-badge');
            if (badge) {
                badge.textContent = data.cart_count;
                badge.style.display = 'inline-block';
            }
        } catch (error) {
            console.error('Ошибка добавления в корзину:', error);
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
                        ${game.discount ? `<span class="discount">-${Number(game.discount)}%</span>` : ''}
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
