"""Витрина: главная, каталог, страница игры, новости, поиск и 404."""
from datetime import date, datetime, time, timedelta
import random

from django.core.paginator import Paginator
from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from ..models import Collection, Game, Genre, News, Profile
from .common import _user_game_state


CATALOG_PAGE_SIZE = 12
NEWS_PAGE_SIZE = 8


def custom_page_not_found(request, exception):
    return render(request, '404.html', status=404)


# Отсчёт недель для игры недели ведём от понедельника, чтобы смена была ровно в пн 0:00
FEATURED_EPOCH = date(2024, 1, 1)


def _pick_featured_game(now=None):
    """Игра недели. Меняется каждый понедельник в 0:00 по времени сайта на следующую игру.

    Игры идут по кругу в перемешанном (но постоянном) порядке, поэтому подряд одна и та же
    игра не повторяется, а за полный круг покажутся все. Если в админке отмечено «Игра недели»
    хотя бы у двух игр, круг идёт только по ним; одна отметка ни на что не влияет, иначе
    игра недели застрянет на одной игре навсегда.
    """
    games = list(Game.objects.order_by('pk').values_list('pk', 'is_game_of_the_week'))
    flagged = [pk for pk, is_flagged in games if is_flagged]
    ids = flagged if len(flagged) >= 2 else [pk for pk, _ in games]
    if not ids:
        return None, ''

    random.Random('featured-order').shuffle(ids)
    today = timezone.localtime(now or timezone.now()).date()
    week_number = (today - FEATURED_EPOCH).days // 7
    game_id = ids[week_number % len(ids)]

    monday_date = today + timedelta(days=7 - today.weekday())
    next_monday = timezone.make_aware(datetime.combine(monday_date, time.min))
    return Game.objects.get(pk=game_id), next_monday.isoformat()


def home(request):
    collections = Collection.objects.prefetch_related(
        Prefetch('game_products', queryset=Game.objects.prefetch_related('genres'))
    )
    featured_game, next_rotation_iso = _pick_featured_game()

    return render(request, 'store/index.html', {
        'featured_game': featured_game,
        'next_rotation_iso': next_rotation_iso,
        # Подборки без игр не показываем, чтобы не было пустых секций
        'collections': [c for c in collections if c.game_products.all()],
        **_user_game_state(request),
    })


CATALOG_SORTS = {
    'new': ('Сначала новые', ['-release_date', '-pk']),
    'price_asc': ('Сначала дешевле', ['final_price', 'title']),
    'price_desc': ('Сначала дороже', ['-final_price', 'title']),
    'discount': ('По размеру скидки', ['-discount', 'title']),
    'rating': ('По рейтингу', [F('avg_rating').desc(nulls_last=True), 'title']),
    'title': ('По названию', ['title']),
}


def _catalog_categories():
    """Автоматические категории каталога: ключ → (название, условие отбора)."""
    return {
        'free': ('Бесплатные', Q(price=0) | Q(discount__gte=100)),
        'sale': ('Со скидкой', Q(price__gt=0, discount__gt=0)),
        'exclusive': ('Эксклюзивы', Q(is_not_on_steam=True)),
        'new': ('Новинки', Q(release_date__gte=timezone.localdate() - timedelta(days=365))),
    }


def _catalog_category_options(categories, selected, hidden_ids=()):
    """Пункты меню категорий: подборки из админки и автоматические категории, в которых есть игры."""
    counts = Game.objects.exclude(pk__in=hidden_ids).aggregate(
        total=Count('pk'),
        **{key: Count('pk', filter=condition) for key, (_, condition) in categories.items()},
    )
    # Подборка только из бесплатных игр дублировала бы категорию «Бесплатные»,
    # поэтому в меню она появляется, лишь когда на неё перешли со страницы магазина
    collections = Collection.objects.annotate(
        games_count=Count('game_products', filter=~Q(game_products__in=hidden_ids)),
        paid_count=Count('game_products', filter=Q(game_products__price__gt=0, game_products__discount__lt=100)),
    ).filter(Q(paid_count__gt=0) | Q(slug=selected)).order_by('title')

    options = [{'value': '', 'label': 'Все игры', 'count': counts['total']}]
    options += [{'value': c.slug, 'label': c.title, 'count': c.games_count} for c in collections]
    options += [
        {'value': key, 'label': label, 'count': counts[key]}
        for key, (label, _) in categories.items() if counts[key]
    ]
    return options


def catalog(request):
    query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()
    selected_genres = request.GET.getlist('genre')
    prefs = Profile.objects.filter(user=request.user).first() if request.user.is_authenticated else None

    sort = request.GET.get('sort')
    if sort not in CATALOG_SORTS:
        sort = prefs.default_catalog_sort if prefs and prefs.default_catalog_sort in CATALOG_SORTS else 'new'

    hidden_ids = []
    if prefs and prefs.hide_owned_in_catalog:
        hidden_ids = list(request.user.purchased_games.values_list('id', flat=True))

    games = Game.objects.exclude(pk__in=hidden_ids).prefetch_related('genres').annotate(
        final_price=ExpressionWrapper(
            F('price') * (100 - F('discount')) / 100,
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        avg_rating=Avg('reviews__rating'),
    )
    if query:
        games = games.filter(title__icontains=query)
    if selected_genres:
        # Подзапрос вместо JOIN: игра с двумя выбранными жанрами не задвоится
        games = games.filter(pk__in=Game.objects.filter(genres__slug__in=selected_genres).values('pk'))

    title = 'Каталог'
    categories = _catalog_categories()
    if category in categories:
        title, condition = categories[category]
        games = games.filter(condition)
    elif category:
        collection = Collection.objects.filter(slug=category).first()
        if collection:
            title = collection.title
            games = games.filter(collections=collection)
        else:
            category = ''

    page = Paginator(games.order_by(*CATALOG_SORTS[sort][1]), CATALOG_PAGE_SIZE).get_page(request.GET.get('page'))

    # Параметры фильтров без номера страницы — для ссылок пагинатора
    params = request.GET.copy()
    params.pop('page', None)

    return render(request, 'store/catalog.html', {
        'page': page,
        'title': title,
        'query': query,
        'category_options': _catalog_category_options(categories, category, hidden_ids),
        'selected_category': category,
        'genres': Genre.objects.annotate(
            games_count=Count('games', filter=~Q(games__in=hidden_ids)),
        ).filter(games_count__gt=0).order_by('name'),
        'selected_genres': selected_genres,
        'owned_hidden': bool(hidden_ids),
        'has_filters': bool(query or category or selected_genres),
        'sort': sort,
        'sort_options': [(key, value[0]) for key, value in CATALOG_SORTS.items()],
        'filter_query': params.urlencode(),
        **_user_game_state(request),
    })


def game_detail(request, game_id):
    game = get_object_or_404(
        Game.objects.select_related('author').prefetch_related('genres', 'collections', 'screenshots'),
        pk=game_id,
    )

    stats = game.reviews.aggregate(avg=Avg('rating'), count=Count('id'))
    avg_rating = stats['avg'] or 0

    my_review = None
    if request.user.is_authenticated:
        my_review = game.reviews.filter(user=request.user).first()

    return render(request, 'store/game_detail.html', {
        'game': game,
        'reviews': game.reviews.select_related('user__profile'),  # профиль — для аватарки
        'avg_rating': avg_rating,
        'avg_percent': avg_rating / 5 * 100,
        'reviews_count': stats['count'],
        'my_review': my_review,
        **_user_game_state(request),
    })


def news(request):
    selected_category = request.GET.get('category', '').strip()
    selected_month = request.GET.get('month', '').strip()  # Ожидаем формат 'YYYY-MM'
    query = request.GET.get('q', '').strip()

    published = News.objects.filter(is_published=True)
    news_qs = published.order_by('-is_pinned', '-created_at', '-pk')

    # Фильтрация по категории
    if selected_category in dict(News.CATEGORY_CHOICES):
        news_qs = news_qs.filter(category=selected_category)
    else:
        selected_category = ''

    # Уникальные сочетания Месяц + Год, в которых есть новости
    archive_months = list(published.dates('created_at', 'month', order='DESC'))

    # Фильтрация по году и месяцу: принимаем только месяцы из архива
    selected_date = next((d for d in archive_months if d.strftime('%Y-%m') == selected_month), None)
    if selected_date:
        news_qs = news_qs.filter(created_at__year=selected_date.year, created_at__month=selected_date.month)
    else:
        selected_month = ''

    # Ищем в Python: LIKE в SQLite не умеет игнорировать регистр кириллицы, а новостей немного
    if query:
        needle = query.casefold()
        news_qs = [n for n in news_qs if needle in n.title.casefold() or needle in n.description.casefold()]

    page = Paginator(news_qs, NEWS_PAGE_SIZE).get_page(request.GET.get('page'))

    counts = dict(published.order_by().values_list('category').annotate(Count('id')))
    categories = [(code, label, counts.get(code, 0)) for code, label in News.CATEGORY_CHOICES]

    return render(request, 'store/news.html', {
        'page': page,
        'pinned_news': [n for n in page if n.is_pinned],
        'regular_news': [n for n in page if not n.is_pinned],
        'categories': categories,
        'total_count': sum(counts.values()),
        'archive_months': archive_months,
        'selected_category': selected_category,
        'selected_month': selected_month,
        'query': query,
        'has_filters': bool(selected_category or selected_month or query),
    })


def news_detail(request, pk):
    # Черновик видят только администраторы: так его можно проверить перед публикацией
    queryset = News.objects.all() if request.user.is_staff else News.objects.filter(is_published=True)
    item = get_object_or_404(queryset, pk=pk)
    published = News.objects.filter(is_published=True)
    # pk различает новости, созданные в один и тот же момент
    same_moment = Q(created_at=item.created_at)

    return render(request, 'store/news_detail.html', {
        'item': item,
        'newer': published.filter(
            Q(created_at__gt=item.created_at) | (same_moment & Q(pk__gt=item.pk))
        ).order_by('created_at', 'pk').first(),
        'older': published.filter(
            Q(created_at__lt=item.created_at) | (same_moment & Q(pk__lt=item.pk))
        ).order_by('-created_at', '-pk').first(),
    })


def game_search_ajax(request):
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return JsonResponse({'games': []})

    games = Game.objects.filter(title__icontains=query).prefetch_related('genres').order_by('title')[:5]
    results = []

    for game in games:
        results.append({
            'id': game.id,
            'title': game.title,
            'price': int(game.discounted_price),
            'old_price': int(game.price) if game.discount > 0 else None,
            'discount': game.discount,
            'cover_url': game.cover.url if game.cover else '',
            'genres': ", ".join(g.name for g in game.genres.all()),
            'is_exclusive': game.is_not_on_steam,
        })

    return JsonResponse({'games': results})
