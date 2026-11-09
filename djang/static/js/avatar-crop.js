// Кроп аватарки: после выбора файла открывается окно, как у баннера. Картинку можно сдвинуть
// и увеличить внутри круглой рамки; на сервер уходит уже вырезанный квадрат 512×512.
// Использование: window.gsAvatarCrop.open(file, {onDone(file, url), onCancel()}).
(() => {
    const SIZE = 512;         // сторона готовой аватарки в пикселях
    const MIN_ZOOM = 100;
    const MAX_ZOOM = 300;

    let modal, stage, frame, img, zoom;
    let callbacks = {};
    let naturalW = 0, naturalH = 0, baseScale = 1, scale = 1;
    let offsetX = 0, offsetY = 0;
    let dragging = false, startX = 0, startY = 0, startOffsetX = 0, startOffsetY = 0;

    function build() {
        modal = document.createElement('div');
        modal.className = 'banner-crop-modal avatar-crop-modal';
        modal.style.display = 'none';
        modal.innerHTML = `
            <div class="banner-crop-box avatar-crop-box" role="dialog" aria-modal="true" aria-labelledby="avatarCropTitle">
                <h3 id="avatarCropTitle">Расположите аватар</h3>
                <div class="banner-crop-stage avatar-crop-stage">
                    <img alt="" draggable="false">
                    <div class="banner-crop-frame avatar-crop-frame"></div>
                </div>
                <div class="banner-crop-controls">
                    <button type="button" class="zoom-btn" data-zoom-step="-20" aria-label="Уменьшить">−</button>
                    <input type="range" class="crop-zoom" min="${MIN_ZOOM}" max="${MAX_ZOOM}" value="${MIN_ZOOM}" aria-label="Масштаб">
                    <button type="button" class="zoom-btn" data-zoom-step="20" aria-label="Увеличить">+</button>
                </div>
                <div class="banner-crop-actions">
                    <button type="button" class="btn-secondary" data-crop-cancel>Отмена</button>
                    <button type="button" class="btn-primary" data-crop-save>Применить</button>
                </div>
            </div>`;
        document.body.append(modal);

        stage = modal.querySelector('.avatar-crop-stage');
        frame = modal.querySelector('.avatar-crop-frame');
        img = stage.querySelector('img');
        zoom = modal.querySelector('.crop-zoom');

        zoom.addEventListener('input', () => setZoom(zoom.value));
        modal.querySelectorAll('[data-zoom-step]').forEach(btn => {
            btn.addEventListener('click', () => setZoom(Number(zoom.value) + Number(btn.dataset.zoomStep)));
        });
        stage.addEventListener('wheel', e => {
            e.preventDefault();
            setZoom(Number(zoom.value) + (e.deltaY < 0 ? 10 : -10));
        }, {passive: false});

        // Перетаскивание мышью и пальцем
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
        modal.querySelector('[data-crop-save]').addEventListener('click', save);
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && modal.style.display !== 'none') cancel();
        });
    }

    function applyTransform() {
        const imgW = naturalW * scale;
        const imgH = naturalH * scale;
        img.style.width = imgW + 'px';
        img.style.height = imgH + 'px';

        // Картинка не должна открывать пустое место внутри рамки
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
        const pct = (zoom.value - MIN_ZOOM) / (MAX_ZOOM - MIN_ZOOM) * 100;
        zoom.style.background = `linear-gradient(to right, var(--accent) ${pct}%, rgba(255,255,255,.15) ${pct}%)`;
        applyTransform();
    }

    function close() {
        modal.style.display = 'none';
        document.body.style.overflow = '';
    }

    function cancel() {
        close();
        callbacks.onCancel?.();
    }

    function save() {
        const stageRect = stage.getBoundingClientRect();
        const frameRect = frame.getBoundingClientRect();
        const left = (stageRect.width - naturalW * scale) / 2 + offsetX;
        const top = (stageRect.height - naturalH * scale) / 2 + offsetY;

        const sx = (frameRect.left - stageRect.left - left) / scale;
        const sy = (frameRect.top - stageRect.top - top) / scale;
        const side = frameRect.width / scale;

        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = SIZE;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#16171d';  // фон под прозрачными PNG, JPEG прозрачность не хранит
        ctx.fillRect(0, 0, SIZE, SIZE);
        ctx.drawImage(img, sx, sy, side, side, 0, 0, SIZE, SIZE);

        canvas.toBlob(blob => {
            if (!blob) return;
            close();
            const file = new File([blob], 'avatar.jpg', {type: 'image/jpeg'});
            callbacks.onDone?.(file, URL.createObjectURL(blob));
        }, 'image/jpeg', 0.9);
    }

    function open(file, options = {}) {
        if (!file || !file.type.startsWith('image/')) {
            options.onCancel?.();
            return;
        }
        if (!modal) build();
        callbacks = options;

        const reader = new FileReader();
        reader.onload = e => {
            img.onload = () => {
                naturalW = img.naturalWidth;
                naturalH = img.naturalHeight;
                modal.style.display = 'flex';
                document.body.style.overflow = 'hidden';
                const frameRect = frame.getBoundingClientRect();
                baseScale = Math.max(frameRect.width / naturalW, frameRect.height / naturalH);
                offsetX = offsetY = 0;
                setZoom(MIN_ZOOM);
            };
            img.onerror = () => options.onCancel?.();
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);
    }

    window.gsAvatarCrop = {open};
})();
