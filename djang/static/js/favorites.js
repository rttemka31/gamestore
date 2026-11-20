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

    // Игра встаёт в избранное перед карточкой под указателем (или в конец)
    function dropAt(x, y) {
        const before = cardAfterPointer(x, y);
        const previous = currentIds();
        const ids = previous.filter(id => id !== draggedId);
        const index = before ? ids.indexOf(before.dataset.favId) : ids.length;
        ids.splice(index, 0, draggedId);

        clearDropMarks();
        if (ids.join() !== previous.join()) save(ids);
    }

    zone.addEventListener('drop', e => {
        if (!draggedId) return;
        e.preventDefault();
        dropAt(e.clientX, e.clientY);
    });

    // ---------- Перетаскивание пальцем ----------
    // На телефонах HTML5 drag-and-drop не работает. Долгое нажатие (0.35 с) «поднимает» игру,
    // дальше её ведут пальцем в избранное; у краёв экрана страница сама прокручивается.
    // Короткое касание открывает игру, а движение пальцем до «подъёма» — обычная прокрутка.
    const LONG_PRESS = 350;
    let touch = null;
    let suppressClick = false;

    const overZone = (x, y) => {
        const rect = zone.getBoundingClientRect();
        return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
    };

    function endTouch() {
        if (!touch) return;
        clearTimeout(touch.timer);
        cancelAnimationFrame(touch.frame);
        touch.ghost?.remove();
        touch.source.classList.remove('is-dragging');
        document.body.classList.remove('fav-dragging');
        clearDropMarks();
        draggedId = null;
        touch = null;
    }

    function markDropTarget(x, y) {
        clearDropMarks();
        if (!overZone(x, y)) return;
        zone.classList.add('is-drag-over');
        const before = cardAfterPointer(x, y);
        if (before) before.classList.add('drop-before');
    }

    // Пока палец у верхнего или нижнего края — плавно прокручиваем страницу
    function autoScroll() {
        if (!touch?.active) return;
        const edge = 70;
        const speed = touch.y < edge ? -(edge - touch.y) / 4 : touch.y > innerHeight - edge ? (touch.y - innerHeight + edge) / 4 : 0;
        if (speed) {
            scrollBy(0, speed);
            markDropTarget(touch.x, touch.y);
        }
        touch.frame = requestAnimationFrame(autoScroll);
    }

    function liftTouch() {
        const rect = touch.source.getBoundingClientRect();
        const ghost = touch.source.cloneNode(true);
        ghost.classList.add('fav-touch-ghost');
        ghost.removeAttribute('href');
        Object.assign(ghost.style, {width: `${rect.width}px`, left: `${rect.left}px`, top: `${rect.top}px`});
        document.body.append(ghost);

        touch.ghost = ghost;
        touch.dx = touch.x - rect.left;
        touch.dy = touch.y - rect.top;
        touch.active = true;
        draggedId = touch.id;
        touch.source.classList.add('is-dragging');
        document.body.classList.add('fav-dragging');
        navigator.vibrate?.(15);
        touch.frame = requestAnimationFrame(autoScroll);
    }

    document.addEventListener('touchstart', e => {
        if (e.touches.length !== 1) return endTouch();
        const source = e.target.closest('[data-fav-source], [data-fav-id]');
        if (!source || e.target.closest('[data-fav-toggle], button')) return;

        const point = e.touches[0];
        touch = {
            source,
            id: source.dataset.favSource || source.dataset.favId,
            x: point.clientX,
            y: point.clientY,
            startX: point.clientX,
            startY: point.clientY,
            active: false,
        };
        touch.timer = setTimeout(liftTouch, LONG_PRESS);
    }, {passive: true});

    document.addEventListener('touchmove', e => {
        if (!touch) return;
        const point = e.touches[0];
        touch.x = point.clientX;
        touch.y = point.clientY;

        if (!touch.active) {
            // палец сдвинулся до «подъёма» — это прокрутка, перетаскивание не начинаем
            if (Math.hypot(touch.x - touch.startX, touch.y - touch.startY) > 10) endTouch();
            return;
        }
        e.preventDefault();  // пока игра «в руке», страница не прокручивается от пальца
        touch.ghost.style.left = `${touch.x - touch.dx}px`;
        touch.ghost.style.top = `${touch.y - touch.dy}px`;
        markDropTarget(touch.x, touch.y);
    }, {passive: false});

    document.addEventListener('touchend', () => {
        if (!touch) return;
        if (touch.active) {
            // после «подъёма» касание не должно открывать ссылку на игру
            suppressClick = true;
            setTimeout(() => { suppressClick = false; }, 500);
            if (overZone(touch.x, touch.y)) dropAt(touch.x, touch.y);
        }
        endTouch();
    });

    document.addEventListener('touchcancel', endTouch);

    // Меню ссылки по долгому нажатию не нужно, пока игру держат пальцем
    document.addEventListener('contextmenu', e => {
        if (touch) e.preventDefault();
    });

    document.addEventListener('click', e => {
        if (!suppressClick) return;
        e.preventDefault();
        e.stopPropagation();
        suppressClick = false;
    }, true);

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
