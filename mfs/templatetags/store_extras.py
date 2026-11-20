import re

from django import template
from django.core.cache import cache
from django.utils.html import escape
from django.utils.safestring import mark_safe

from ..models import Gift, UserLibrary

register = template.Library()

BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
URL_RE = re.compile(r'https?://[^\s<]+')


def _format_inline(text):
    html = BOLD_RE.sub(r'<strong>\1</strong>', escape(text))
    return URL_RE.sub(lambda m: f'<a href="{m.group(0)}" target="_blank" rel="noopener noreferrer">{m.group(0)}</a>', html)


@register.filter
def thumb(field, spec):
    """Превью картинки: {{ shot.image|thumb:"200x110" }} — обрезка, {{ game.cover_hd|thumb:"1280" }} — по ширине."""
    from ..thumbnails import thumbnail_url
    return thumbnail_url(field, spec)


@register.filter
def absolute_url(url, request):
    """Полный адрес с доменом — для превью ссылок (og:image): Discord и Telegram не понимают относительные."""
    return request.build_absolute_uri(url) if request and url else url


@register.filter
def playtime(seconds):
    """Время в игре: до часа — минуты («45 мин»), дальше часы с десятыми («12,6 ч», «3 ч»)."""
    seconds = int(seconds or 0)
    if seconds < 3600:
        return f'{seconds // 60} мин'
    return f'{hours_display(seconds)} ч'


@register.filter
def playtime_words(seconds):
    """Время в игре словами: «17 минут», «1 час», «12,5 часа», «5 часов»."""
    seconds = int(seconds or 0)
    if seconds < 3600:
        minutes = seconds // 60
        return f'{minutes} {ru_plural(minutes, "минута,минуты,минут")}'
    hours = hours_display(seconds)
    if ',' in hours:  # дробное число часов: «12,5 часа»
        return f'{hours} часа'
    return f'{hours} {ru_plural(int(hours), "час,часа,часов")}'


def hours_display(seconds):
    """Часы с одной цифрой после запятой, без лишнего нуля: 12,6 / 3 / 128."""
    text = f'{round(seconds / 3600, 1):.1f}'.removesuffix('.0')
    return text.replace('.', ',')


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


def is_developer(user):
    """Автор хотя бы одной игры. Результат запоминается на объекте: в списках друзей
    и отзывах роль одного человека может понадобиться несколько раз."""
    if not hasattr(user, '_is_developer'):
        user._is_developer = user.game_set.exists()
    return user._is_developer


@register.filter
def user_status(user):
    """Роль пользователя со своим значком: «Создатель», «Админ», «Разработчик» или «Пользователь».

    «Разработчик» выдаётся сам — любому, кто указан автором хотя бы одной игры.
    Значки — символы из спрайта _role_icons.html, который подключён в base.html.
    """
    if user.is_superuser:
        key, label = 'creator', 'Создатель'
    elif user.is_staff:
        key, label = 'admin', 'Админ'
    elif is_developer(user):
        key, label = 'developer', 'Разработчик'
    else:
        key, label = 'user', 'Пользователь'
    return mark_safe(
        f'<svg class="role-icon role-icon-{key}" aria-hidden="true"><use href="#role-{key}"></use></svg>{label}'
    )


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


@register.simple_tag(takes_context=True)
def new_gifts(context):
    """Подарки, о которых получатель ещё не знает: окно «Вам подарили игру» показывается на любой странице."""
    user = getattr(context.get('request'), 'user', None)
    if not user or not user.is_authenticated:
        return []
    return list(Gift.objects.filter(receiver=user, seen=False).select_related('sender', 'game').order_by('created_at'))


@register.simple_tag(takes_context=True)
def library_new_count(context):
    """Сколько игр куплено или подарено, но ещё не открыто в библиотеке: счётчик у «Библиотеки» в шапке."""
    user = getattr(context.get('request'), 'user', None)
    if not user or not user.is_authenticated:
        return 0
    return UserLibrary.objects.filter(user=user, is_new=True).count()
