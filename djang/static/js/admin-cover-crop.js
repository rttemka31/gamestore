// Админка: кроп обложки и HD обложки игры. После выбора файла открывается окно «Расположите обложку»,
// как у баннера в профиле: картинку можно сдвинуть и увеличить внутри рамки 16:9. Пунктиром показано,
// какая полоса кадра видна в других местах сайта. «Применить» кладёт в поле вырезанную картинку,
// «Без обрезки» оставляет исходный файл, «Отмена» сбрасывает выбор.
(() => {
    const RATIO = 16 / 9;
    const MIN_ZOOM = 100;
    const MAX_ZOOM = 300;
    const GUIDE_COLORS = ['#ffd84d', '#5ee0ff', '#ff8ad8'];

    // Полосы других мест сайта: подпись, пропорции места и вертикальная точка кадрирования (object-position)
    const FIELDS = {
        cover: {
            title: 'Расположите обложку',
            width: 1280,
            guides: [
                ['Корзина, избранное', 2 / 1, 0.5],
                ['Карточка в магазине', 389 / 150, 0.5],
            ],
        },
        cover_hd: {
            title: 'Расположите HD обложку',
            width: 1920,
            guides: [
                ['Игра недели', 755 / 375, 0.5],
                ['Шапка библиотеки', 1190 / 400, 0.3],
                ['Шапка библиотеки, широкий экран', 1670 / 400, 0.3],
            ],
        },
    };

    const STYLE = `
        .cover-crop-modal { position: fixed; inset: 0; z-index: 3000; display: flex; align-items: center; justify-content: center;
            padding: 16px; background: rgba(0, 0, 0, 0.7); }
        .cover-crop-modal[hidden] { display: none; }
        .cover-crop-box { width: min(900px, 100%); max-height: 100%; overflow: auto; padding: 20px; box-sizing: border-box;
            color: var(--body-fg); background: var(--body-bg); border: 1px solid var(--hairline-color); border-radius: 12px; }
        .cover-crop-box h3 { margin: 0 0 4px; padding: 0; font-size: 18px; color: var(--body-fg); background: none; text-transform: none; }
        .cover-crop-hint { margin: 0 0 12px; color: var(--body-quiet-color); }
        .cover-crop-stage { position: relative; width: 100%; aspect-ratio: 16 / 10.5; overflow: hidden; background: #000;
            border-radius: 8px; cursor: grab; touch-action: none; user-select: none; }
        .cover-crop-stage.dragging { cursor: grabbing; }
        .cover-crop-stage img { position: absolute; top: 0; left: 0; max-width: none; transform-origin: 0 0; pointer-events: none; }
        .cover-crop-frame { position: absolute; left: 5%; right: 5%; top: 50%; aspect-ratio: 16 / 9; transform: translateY(-50%);
            border: 2px solid #fff; box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.6); pointer-events: none; box-sizing: border-box; }
        .cover-crop-guide { position: absolute; left: 0; right: 0; border-top: 2px dashed var(--guide);
            border-bottom: 2px dashed var(--guide); box-sizing: border-box; }
        .cover-crop-guide span { position: absolute; top: 2px; padding: 1px 6px; font-size: 11px; line-height: 16px; color: #111;
            background: var(--guide); border-radius: 4px; white-space: nowrap; }
        .cover-crop-controls { display: flex; align-items: center; gap: 10px; margin: 14px 0; }
        .cover-crop-controls input { flex: 1; accent-color: var(--primary); }
        .cover-crop-controls .button { min-width: 36px; }
        .cover-crop-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
    `;

    let modal, stage, frame, img, zoom, title, guides;
    let input = null, file = null, field = null;
    let naturalW = 0, naturalH = 0, baseScale = 1, scale = 1, offsetX = 0, offsetY = 0;
    let dragging = false, startX = 0, startY = 0, startOffsetX = 0, startOffsetY = 0;

    function build() {
        const style = document.createElement('style');
        style.textContent = STYLE;
        document.head.append(style);

        modal = document.createElement('div');
        modal.className = 'cover-crop-modal';
        modal.hidden = true;
        modal.innerHTML = `
            <div class="cover-crop-box" role="dialog" aria-modal="true" aria-labelledby="coverCropTitle">
                <h3 id="coverCropTitle"></h3>
                <p class="cover-crop-hint">Сплошная рамка — сохранённый кадр 16:9 (так он виден в галерее и на обложке трейлера).
                    Пунктир — полоса, которая остаётся в других местах сайта.</p>
                <div class="cover-crop-stage">
                    <img alt="" draggable="false">
                    <div class="cover-crop-frame"></div>
                </div>
                <div class="cover-crop-controls">
                    <button type="button" class="button" data-zoom-step="-20" aria-label="Уменьшить">−</button>
                    <input type="range" min="${MIN_ZOOM}" max="${MAX_ZOOM}" value="${MIN_ZOOM}" aria-label="Масштаб">
                    <button type="button" class="button" data-zoom-step="20" aria-label="Увеличить">+</button>
                </div>
                <div class="cover-crop-actions">
                    <button type="button" class="button" data-crop-cancel>Отмена</button>
                    <button type="button" class="button" data-crop-original>Без обрезки</button>
                    <button type="button" class="button default" data-crop-save>Применить</button>
                </div>
            </div>`;
        document.body.append(modal);

        title = modal.querySelector('h3');
        stage = modal.querySelector('.cover-crop-stage');
        frame = modal.querySelector('.cover-crop-frame');
        img = stage.querySelector('img');
        zoom = modal.querySelector('input[type="range"]');

        zoom.addEventListener('input', () => setZoom(zoom.value));
        modal.querySelectorAll('[data-zoom-step]').forEach(btn => {
            btn.addEventListener('click', () => setZoom(Number(zoom.value) + Number(btn.dataset.zoomStep)));
        });
        stage.addEventListener('wheel', e => {
            e.preventDefault();
            setZoom(Number(zoom.value) + (e.deltaY < 0 ? 10 : -10));
        }, {passive: false});

        stage.addEventListener('pointerdown', e => {
            dragging = true;
            stage.classList.add('dragging');
            stage.setPointerCapture(e.pointerId);
            [startX, startY, startOffsetX, startOffsetY] = [e.clientX, e.clientY, offsetX, offsetY];
        });
        stage.addEventListener('pointermove', e => {
            if (!dragging) return;
            offsetX = startOffsetX + (e.clientX - startX);
            offsetY = startOffsetY + (e.clientY - startY);
            applyTransform();
        });
        const stop = () => { dragging = false; stage.classList.remove('dragging'); };
        stage.addEventListener('pointerup', stop);
        stage.addEventListener('pointercancel', stop);

        modal.querySelector('[data-crop-cancel]').addEventListener('click', cancel);
        modal.querySelector('[data-crop-original]').addEventListener('click', keepOriginal);
        modal.querySelector('[data-crop-save]').addEventListener('click', save);
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && !modal.hidden) cancel();
        });
    }

    // Полосы в долях высоты рамки 16:9: высота = (16/9) / пропорции места, отступ — как у object-position
    function drawGuides() {
        guides?.forEach(guide => guide.remove());
        guides = FIELDS[field].guides.map(([label, ratio, y], index) => {
            const height = RATIO / ratio;
            const guide = document.createElement('div');
            guide.className = 'cover-crop-guide';
            guide.style.setProperty('--guide', GUIDE_COLORS[index]);  // у каждой полосы свой цвет, чтобы линии не путались
            guide.style.top = `${(1 - height) * y * 100}%`;
            guide.style.height = `${height * 100}%`;
            const caption = document.createElement('span');
            caption.textContent = label;
            caption.style.left = `${6 + index * 30}%`;  // подписи соседних полос не накладываются
            guide.append(caption);
            frame.append(guide);
            return guide;
        });
    }

    function applyTransform() {
        const imgW = naturalW * scale;
        const imgH = naturalH * scale;
        img.style.width = imgW + 'px';
        img.style.height = imgH + 'px';

        // Картинка не открывает пустое место внутри рамки
        const frameRect = frame.getBoundingClientRect();
        const maxX = Math.max(0, (imgW - frameRect.width) / 2);
        const maxY = Math.max(0, (imgH - frameRect.height) / 2);
        offsetX = Math.min(maxX, Math.max(-maxX, offsetX));
        offsetY = Math.min(maxY, Math.max(-maxY, offsetY));

        const stageRect = stage.getBoundingClientRect();
        const left = (stageRect.width - imgW) / 2 + offsetX;
        const top = (stageRect.height - imgH) / 2 + offsetY;
        img.style.transform = `translate(${left}px, ${top}px)`;
    }

    function setZoom(value) {
        zoom.value = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
        scale = baseScale * (zoom.value / 100);
        applyTransform();
    }

    function close() {
        modal.hidden = true;
        document.body.style.overflow = '';
    }

    // Отдаём файл в поле так, будто его выбрали сами: admin-preview.js обновит превью
    function commit(result) {
        const files = new DataTransfer();
        files.items.add(result);
        input.files = files.files;
        input.dataset.cropDone = '1';
        input.dispatchEvent(new Event('change', {bubbles: true}));
        delete input.dataset.cropDone;
    }

    function cancel() {
        close();
        input.value = '';
    }

    function keepOriginal() {
        close();
        commit(file);
    }

    function save() {
        const stageRect = stage.getBoundingClientRect();
        const frameRect = frame.getBoundingClientRect();
        const left = (stageRect.width - naturalW * scale) / 2 + offsetX;
        const top = (stageRect.height - naturalH * scale) / 2 + offsetY;
        const sx = (frameRect.left - stageRect.left - left) / scale;
        const sy = (frameRect.top - stageRect.top - top) / scale;
        const sw = frameRect.width / scale;
        const sh = frameRect.height / scale;

        // Маленький исходник не растягиваем: берём его настоящий размер
        const width = Math.round(Math.min(FIELDS[field].width, sw));
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = Math.round(width / RATIO);
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#16171d';  // фон под прозрачными PNG: JPEG прозрачность не хранит
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);

        canvas.toBlob(blob => {
            if (!blob) return;
            close();
            const name = file.name.replace(/\.[^.]+$/, '') + '.jpg';
            commit(new File([blob], name, {type: 'image/jpeg'}));
        }, 'image/jpeg', 0.92);
    }

    function open() {
        if (!modal) build();
        title.textContent = FIELDS[field].title;
        const url = URL.createObjectURL(file);
        img.onload = () => {
            URL.revokeObjectURL(url);
            naturalW = img.naturalWidth;
            naturalH = img.naturalHeight;
            modal.hidden = false;
            document.body.style.overflow = 'hidden';
            drawGuides();
            const frameRect = frame.getBoundingClientRect();
            baseScale = Math.max(frameRect.width / naturalW, frameRect.height / naturalH);
            offsetX = offsetY = 0;
            setZoom(MIN_ZOOM);
        };
        img.onerror = () => { URL.revokeObjectURL(url); };  // не картинка — пусть поле само покажет ошибку при сохранении
        img.src = url;
    }

    // Ловим выбор файла раньше admin-preview.js (фаза перехвата): превью обновится уже после кропа
    document.addEventListener('change', e => {
        const target = e.target;
        if (target.type !== 'file' || !(target.name in FIELDS) || target.dataset.cropDone) return;
        if (!target.files || !target.files[0] || !target.files[0].type.startsWith('image/')) return;
        e.stopPropagation();
        input = target;
        field = target.name;
        file = target.files[0];
        open();
    }, true);
})();
