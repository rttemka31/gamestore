// Меню-«бургер» шапки на телефонах: открывается кнопкой ☰, закрывается по Esc,
// по нажатию мимо меню, при переходе по ссылке и при расширении окна до размеров компьютера.
document.addEventListener('DOMContentLoaded', () => {
    const header = document.querySelector('.navbar');
    const toggle = header && header.querySelector('.nav-toggle');
    if (!toggle) return;

    const setOpen = open => {
        header.classList.toggle('menu-open', open);
        toggle.setAttribute('aria-expanded', String(open));
        toggle.setAttribute('aria-label', open ? 'Закрыть меню' : 'Открыть меню');
    };
    const isOpen = () => header.classList.contains('menu-open');

    toggle.addEventListener('click', e => {
        e.stopPropagation();
        setOpen(!isOpen());
    });

    document.addEventListener('click', e => {
        if (isOpen() && !header.contains(e.target)) setOpen(false);
    });

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && isOpen()) {
            setOpen(false);
            toggle.focus();
        }
    });

    header.addEventListener('click', e => {
        const link = e.target.closest('.nav-links a, .nav-right a');
        if (link && !link.matches('#userMenuBtn')) setOpen(false);
    });

    window.matchMedia('(min-width: 769px)').addEventListener('change', e => {
        if (e.matches) setOpen(false);
    });
});
