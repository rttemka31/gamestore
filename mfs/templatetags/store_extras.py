import re

from django import template
from django.core.cache import cache
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
URL_RE = re.compile(r'https?://[^\s<]+')


def _format_inline(text):
    html = BOLD_RE.sub(r'<strong>\1</strong>', escape(text))
    return URL_RE.sub(lambda m: f'<a href="{m.group(0)}" target="_blank" rel="noopener noreferrer">{m.group(0)}</a>', html)


@register.filter
def playtime(seconds):
    """Время в игре: «45 мин», «3 ч 20 мин», «127 ч»."""
    hours, minutes = divmod(int(seconds or 0) // 60, 60)
    if not hours:
        return f'{minutes} мин'
    if hours >= 10 or not minutes:
        return f'{hours} ч'
    return f'{hours} ч {minutes} мин'


@register.filter
def news_format(text):
    """Текст новости в HTML: абзацы, **жирный**, списки «- пункт» и ссылки. Всё остальное экранируется."""
    blocks, paragraph, items = [], [], []

    def flush():
        if paragraph:
            blocks.append(f'<p>{"<br>".join(paragraph)}</p>')
            paragraph.clear()
        if items:
            blocks.append(f'<ul>{"".join(f"<li>{item}</li>" for item in items)}</ul>')
            items.clear()

    for line in str(text).splitlines():
        line = line.strip()
        if line.startswith(('- ', '* ', '• ')):
            if paragraph:
                flush()
            items.append(_format_inline(line[2:]))
        elif line:
            if items:
                flush()
            paragraph.append(_format_inline(line))
        else:
            flush()
    flush()

    return mark_safe(''.join(blocks))


@register.filter
def news_plain(text):
    """Текст новости без разметки — для короткого анонса в списке."""
    return ' '.join(re.sub(r'\*\*|^\s*[-*] ', '', str(text), flags=re.M).split())


@register.filter
def user_status(user):
    """Статус пользователя: те же подписи, что и в профиле."""
    if user.is_superuser:
        return '👑 Создатель'
    if user.is_staff:
        return '🛡️ Админ'
    return '🎮 Пользователь'


@register.filter
def ru_plural(value, forms):
    """{{ count|ru_plural:"отзыв,отзыва,отзывов" }} — русское склонение по числу."""
    one, few, many = forms.split(',')
    number = abs(int(value))
    if 11 <= number % 100 <= 14:
        return many
    if number % 10 == 1:
        return one
    if 2 <= number % 10 <= 4:
        return few
    return many


SITE_VERSION_CACHE_KEY = 'site-version'


@register.simple_tag
def site_version():
    """Версия сайта для подвала: та же, что в разделе «О сайте» настроек.
    Подвал есть на каждой странице, поэтому версия кэшируется; при изменении новостей кэш сбрасывается."""
    from ..views.accounts import _site_version  # здесь, а не наверху: представления сами импортируют эти фильтры
    return cache.get_or_set(SITE_VERSION_CACHE_KEY, lambda: _site_version() or {}, 300)
