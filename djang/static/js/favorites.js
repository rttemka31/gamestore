// Избранное: перетаскивание игр из библиотеки и профиля, порядок и кнопки-звёздочки.
document.addEventListener('DOMContentLoaded', () => {
    const zone = document.querySelector('[data-favorites]');
    if (!zone) {
        window.gsSyncFavorites = () => {};
        return;
    }

    let draggedId = null;

    const currentIds = () => [...zone.querySelectorAll('[data-fav-id]')].map(el => el.dataset.favId);

    // Звёздочки и счётчики вне зоны избранного следуют за её содержимым
    function syncFavorites() {
        const ids = currentIds();
        document.querySelectorAll('[data-fav-count]').forEach(el => {
            el.textContent = ids.length;
        });
        document.querySelectorAll('[data-fav-toggle][data-on]').forEach(btn => {
            const active = ids.includes(btn.dataset.favToggle);
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active);
            btn.textContent = active ? btn.dataset.on : btn.dataset.off;
        });
    }
    window.gsSyncFavorites = syncFavorites;

    async function save(ids) {
        const body = new URLSearchParams({layout: zone.dataset.layout});
        ids.forEach(id => body.append('ids', id));

        try {
            const data = await window.gsPost(zone.dataset.url, body);
            if (data.status === 'success') {
                zone.innerHTML = data.html;
                syncFavorites();
            } else if (data.status !== 'login_required') {
                window.gsToast(data.message || 'Не удалось сохранить избранное');
            }
        } catch (error) {
            console.error('Ошибка сохранения избранного:', error);
            window.gsToast('Не удалось сохранить избранное');
        }
    }

    function clearDropMarks() {
        zone.classList.remove('is-drag-over');
        zone.querySelectorAll('.drop-before').forEach(el => el.classList.remove('drop-before'));
    }

    // Карточка, перед которой окажется игра; null — в конец списка
    function cardAfterPointer(x, y) {
        const vertical = zone.dataset.layout === 'library';
        const cards = [...zone.querySelectorAll('[data-fav-id]')].filter(el => el.dataset.favId !== draggedId);
        return cards.find(card => {
            const rect = card.getBoundingClientRect();
            if (vertical) return y < rect.top + rect.height / 2;
            return y < rect.top || (y < rect.bottom && x < rect.left + rect.width / 2);
        }) || null;
    }

    document.addEventListener('dragstart', e => {
        const source = e.target.closest ? e.target.closest('[data-fav-source], [data-fav-id]') : null;
        if (!source) return;

        draggedId = source.dataset.favSource || source.dataset.favId;
        e.dataTransfer.setData('text/plain', draggedId);
        e.dataTransfer.effectAllowed = 'move';
        source.classList.add('is-dragging');
        document.body.classList.add('fav-dragging');
    });

    document.addEventListener('dragend', () => {
        draggedId = null;
        clearDropMarks();
        document.querySelectorAll('.is-dragging').forEach(el => el.classList.remove('is-dragging'));
        document.body.classList.remove('fav-dragging');
    });

    zone.addEventListener('dragover', e => {
        if (!draggedId) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';

        clearDropMarks();
        zone.classList.add('is-drag-over');
        const before = cardAfterPointer(e.clientX, e.clientY);
        if (before) before.classList.add('drop-before');
    });

    zone.addEventListener('dragleave', e => {
        if (!zone.contains(e.relatedTarget)) clearDropMarks();
    });

    zone.addEventListener('drop', e => {
        if (!draggedId) return;
        e.preventDefault();

        const before = cardAfterPointer(e.clientX, e.clientY);
        const previous = currentIds();
        const ids = previous.filter(id => id !== draggedId);
        const index = before ? ids.indexOf(before.dataset.favId) : ids.length;
        ids.splice(index, 0, draggedId);

        clearDropMarks();
        if (ids.join() !== previous.join()) save(ids);
    });

    // Кнопки работают и там, где перетаскивания нет: на телефонах и с клавиатуры
    document.addEventListener('click', e => {
        const btn = e.target.closest('[data-fav-toggle]');
        if (!btn || !btn.dataset.favToggle) return;
        e.preventDefault();  // кнопка может лежать внутри ссылки на игру

        const id = btn.dataset.favToggle;
        const ids = currentIds();
        save(ids.includes(id) ? ids.filter(value => value !== id) : [...ids, id]);
    });

    syncFavorites();
});
