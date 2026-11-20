// Админка: превью картинки обновляется сразу при выборе файла, а не только после сохранения.
// Превью — <img data-preview-for="имя поля"> из mfs/admin.py; ищем его в той же строке формы
// (у скриншотов — в той же строке таблицы), поэтому работает и для новых строк «Добавить ещё».
document.addEventListener('change', e => {
    const input = e.target;
    if (input.type !== 'file' || !input.files || !input.files[0]) return;
    if (!input.files[0].type.startsWith('image/')) return;

    const field = input.name.split('-').pop();  // «screenshots-0-image» → «image»
    // Сначала строка таблицы (скриншоты), потом строка формы: в Django 6 у каждого поля ещё
    // свой маленький <fieldset>, и поиск по нему превью из соседней ячейки не находил
    const scope = input.closest('tr') || input.closest('.form-row') || input.closest('fieldset.module') || document;
    const img = scope.querySelector(`img[data-preview-for="${field}"]`);
    const url = URL.createObjectURL(input.files[0]);
    refreshCoverFrames(field, url);
    if (!img) return;

    if (img.dataset.objectUrl) URL.revokeObjectURL(img.dataset.objectUrl);
    img.dataset.objectUrl = url;
    img.src = url;
    img.hidden = false;
    const placeholder = img.parentElement.querySelector('[data-preview-empty]');
    if (placeholder) placeholder.hidden = true;
});

// Блок «Обложки на сайте»: та же картинка в пропорциях разных мест сайта.
// Места для HD обложки берут её, а без неё — обычную обложку, как и сам сайт
function refreshCoverFrames(field, url) {
    const box = document.querySelector('[data-cover-frames]');
    if (!box || (field !== 'cover' && field !== 'cover_hd')) return;
    box.dataset[field === 'cover' ? 'cover' : 'coverHd'] = url;
    const sources = {cover: box.dataset.cover, hd: box.dataset.coverHd || box.dataset.cover};
    box.querySelectorAll('img[data-frame]').forEach(frame => {
        const src = sources[frame.dataset.frame];
        frame.hidden = !src;
        if (src) frame.src = src;
    });
}
