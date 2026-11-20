(function () {
    var root = document.documentElement, KEY = 'gs-halloween';
    var d = new Date(), m = d.getMonth(), day = d.getDate();
    // Сезон — с 15 октября по 14 ноября включительно. В сезон тема включена сама, и её можно
    // выключить переключателем; после 14 ноября она пропадает вместе с переключателем,
    // а сохранённый выбор забывается, чтобы в следующем году сезон начался заново
    var inSeason = (m === 9 && day >= 15) || (m === 10 && day <= 14);
    var auto = inSeason;
    var pref = null;

    try {
        var q = new URLSearchParams(location.search).get('halloween');
        if (!inSeason) {
            localStorage.removeItem(KEY);
            pref = q === '1' ? 'on' : null;  // ?halloween=1 — посмотреть тему вне сезона, без сохранения
        } else {
            if (q === '1') localStorage.setItem(KEY, 'on');
            else if (q === '0') localStorage.setItem(KEY, 'off');
            else if (q === 'auto') localStorage.removeItem(KEY);
            pref = localStorage.getItem(KEY);
        }
    } catch (e) {}

    function isOn() { return root.getAttribute('data-season') === 'halloween'; }

    function setIcon(on) {
        var l = document.getElementById('siteIcon');
        if (!l) return;
        var u = on ? l.dataset.halloween : l.dataset.default;
        if (u && l.getAttribute('href') !== u) l.setAttribute('href', u);
    }

    function apply(on) {
        if (on) root.setAttribute('data-season', 'halloween');
        else root.removeAttribute('data-season');
        setIcon(on);
    }
    apply(pref ? pref === 'on' : auto);

    function mount() {
        setIcon(isOn());
        if (!inSeason || document.getElementById('seasonToggle')) return;
        var host = document.querySelector('.nav-right') || document.querySelector('.navbar');
        if (!host) return;

        var btn = document.createElement('button');
        btn.id = 'seasonToggle';
        btn.type = 'button';
        btn.className = 'season-toggle';
        btn.title = 'Хэллоуин-тема';
        btn.setAttribute('aria-label', 'Хэллоуин-тема');
        btn.innerHTML = '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path fill="#ff7a1a" d="M12 7.2c-1.1-.6-2.5-.8-3.8-.5C5 7.4 3 10.2 3 13.6S5 19.9 8.2 20.6c1.4.3 2.7 0 3.8-.6 1.1.6 2.4.9 3.8.6C19 19.9 21 17 21 13.6s-2-6.2-5.2-6.9c-1.3-.3-2.7-.1-3.8.5Z"/><path fill="none" stroke="#b34700" stroke-width="1.2" stroke-linecap="round" d="M12 8v11.5M8.6 7.6c-1.6 1.6-2 9.4 0 12.4M15.4 7.6c1.6 1.6 2 9.4 0 12.4"/><path fill="#4caf50" d="M11.3 7.4c0-2 .6-3.5 2-4.5l1.1 1c-1.1.9-1.5 2-1.5 3.5Z"/></svg><span class="season-switch" aria-hidden="true"></span>';

        function sync() { btn.setAttribute('aria-pressed', isOn() ? 'true' : 'false'); }
        btn.addEventListener('click', function () {
            var on = !isOn();
            apply(on);
            try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch (e) {}
            sync();
        });

        host.insertBefore(btn, host.firstChild);
        sync();
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
    else mount();
})();