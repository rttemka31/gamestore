"""Статистика для администраторов: продажи, популярные игры и новые пользователи по дням."""
from datetime import datetime, time, timedelta

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from ..models import Review, UserLibrary

STATS_PERIODS = (7, 30, 90)
TOP_GAMES = 10


def _by_day(queryset, field, days, start, **values):
    """Значения по дням за период; дни без записей тоже есть — с нулями, чтобы график не прерывался."""
    rows = (
        queryset.annotate(day=TruncDate(field, tzinfo=timezone.get_current_timezone()))
        .values('day').annotate(**values).order_by('day')
    )
    found = {row['day']: row for row in rows}
    result = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        row = found.get(day, {})
        result.append({'day': day, **{name: row.get(name) or 0 for name in values}})
    return result


def _with_bars(series, key):
    """Высота столбика в процентах от самого большого значения за период."""
    peak = max((item[key] for item in series), default=0)
    for item in series:
        item['bar'] = round(item[key] / peak * 100) if peak else 0
    return series


@staff_member_required
def admin_stats(request):
    try:
        days = int(request.GET.get('days', 30))
    except ValueError:
        days = 30
    if days not in STATS_PERIODS:
        days = 30

    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    since = timezone.make_aware(datetime.combine(start, time.min))

    library = UserLibrary.objects.filter(purchased_at__gte=since)
    users = get_user_model().objects.filter(date_joined__gte=since)

    sales = _by_day(library, 'purchased_at', days, start, count=Count('id'), revenue=Sum('price_paid'))
    signups = _by_day(users, 'date_joined', days, start, count=Count('id'))

    top_games = (
        library.values('game_id', 'game__title')
        .annotate(count=Count('id'), revenue=Sum('price_paid'))
        .order_by('-count', 'game__title')[:TOP_GAMES]
    )

    totals = library.aggregate(count=Count('id'), revenue=Sum('price_paid'))
    return render(request, 'admin/stats.html', {
        **admin.site.each_context(request),  # шапка и меню админки
        'title': 'Статистика',
        'days': days,
        'periods': STATS_PERIODS,
        'sales': _with_bars(sales, 'count'),
        'signups': _with_bars(signups, 'count'),
        'top_games': top_games,
        'totals': {
            'purchases': totals['count'],
            'revenue': totals['revenue'] or 0,
            'paid': library.filter(price_paid__gt=0).count(),
            'unknown_price': library.filter(price_paid__isnull=True).count(),
            'users': users.count(),
            'reviews': Review.objects.filter(created_at__gte=since).count(),
        },
    })
