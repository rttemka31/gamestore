from django import template

register = template.Library()


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
