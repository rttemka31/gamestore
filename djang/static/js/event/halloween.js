(function () {
    var root = document.documentElement, KEY = 'gs-halloween';
    var d = new Date(), m = d.getMonth(), day = d.getDate();
    var auto = (m === 9 && day >= 15) || (m === 10 && day <= 3);
    var pref = null;

    try {
        var q = new URLSearchParams(location.search).get('halloween');
        if (q === '1') localStorage.setItem(KEY, 'on');
        else if (q === '0') localStorage.setItem(KEY, 'off');
        else if (q === 'auto') localStorage.removeItem(KEY);
        pref = localStorage.getItem(KEY);
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
        if (document.getElementById('seasonToggle')) return;
        var host = document.querySelector('.nav-right') || document.querySelector('.navbar');
        if (!host) return;

        var btn = document.createElement('button');
        btn.id = 'seasonToggle';
        btn.type = 'button';
        btn.className = 'season-toggle';
        btn.title = 'Хэллоуин-тема';
        btn.setAttribute('aria-label', 'Хэллоуин-тема');
        btn.innerHTML = '<span aria-hidden="true">🎃</span><span class="season-switch" aria-hidden="true"></span>';

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