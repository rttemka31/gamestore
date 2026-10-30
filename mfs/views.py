import random
import re
from datetime import datetime, time, timedelta

from allauth.socialaccount.adapter import get_adapter as get_social_adapter
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Prefetch, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Collection, FavoriteGame, Friendship, Game, Genre, News, Profile, Review, UserLibrary, Wishlist

MAX_USERNAME_LENGTH = 24
MAX_IMAGE_SIZE = 5 * 1024 * 1024
ACCENT_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
CATALOG_PAGE_SIZE = 12
NEWS_PAGE_SIZE = 8
MAX_FAVORITES = 6


def custom_page_not_found(request, exception):
    return render(request, '404.html', status=404)

def _step(value, default=1):
    try:
        return min(2, max(0, int(value)))
    except (TypeError, ValueError):
        return default


def _is_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def _safe_url(request, url, fallback):
    """Возвращает url, только если он ведёт на наш сайт (защита от open redirect)."""
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return fallback


def _social_providers(request):
    """Соцсети, для которых настроены OAuth-приложения: без них кнопка входа роняет страницу."""
    return {app.provider for app in get_social_adapter().list_apps(request)}


def _clean_image(uploaded):
    """Проверяет, что загруженный файл — настоящая картинка. Возвращает текст ошибки или None."""
    if uploaded.size > MAX_IMAGE_SIZE:
        return 'Файл слишком большой: максимум 5 МБ.'
    try:
        forms.ImageField().clean(uploaded)
    except ValidationError:
        return 'Загрузите изображение в формате JPG, PNG, WEBP или GIF.'
    return None


def _account_error(user, username, email):
    """Проверяет новые логин и почту. Возвращает текст ошибки или None."""
    if username != user.username:
        if not username or len(username) > MAX_USERNAME_LENGTH:
            return f'Имя пользователя должно быть от 1 до {MAX_USERNAME_LENGTH} символов.'
        try:
            UnicodeUsernameValidator()(username)
        except ValidationError:
            return 'Имя может содержать только буквы, цифры и символы @ . + - _'
        if get_user_model().objects.filter(username__iexact=username).exclude(pk=user.pk).exists():
            return 'Это имя пользователя уже занято.'

    if email and email != user.email:
        try:
            validate_email(email)
        except ValidationError:
            return 'Укажите корректный email.'
    return None


@login_required
def settings_view(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    if request.method == 'POST':
        form_type = request.POST.get('form')

        # 1. ОБРАБОТКА ПРОФИЛЯ
        if form_type == 'profile':
            username = request.POST.get('username', user.username).strip()
            email = request.POST.get('email', user.email).strip()
            error = _account_error(user, username, email)

            for field in ('avatar', 'banner'):
                if not error and field in request.FILES:
                    error = _clean_image(request.FILES[field])

            if error:
                return JsonResponse({'status': 'error', 'message': error}, status=400)

            user.username = username
            user.email = email
            user.save()

            profile.bio = request.POST.get('bio', '').strip()[:150]
            for field in ('avatar', 'banner'):
                if field in request.FILES:
                    setattr(profile, field, request.FILES[field])

            profile.save()
            return JsonResponse({'status': 'success'})


        # 2. ОБРАБОТКА ВНЕШНЕГО ВИДА И УВЕДОМЛЕНИЙ
        elif form_type == 'appearance':
            profile.disable_blur = 'disable_blur' in request.POST
            accent_color = request.POST.get('accent_color', '')
            if ACCENT_COLOR_RE.match(accent_color):
                profile.accent_color = accent_color
            profile.hide_stats = 'hide_stats' in request.POST
            profile.font_size = _step(request.POST.get('font_size'))
            profile.radius_size = _step(request.POST.get('radius_size'))
            profile.save()
            return JsonResponse({'status': 'success'})

        # 3. СМЕНА ПАРОЛЯ
        elif form_type == 'password':
            old_password = request.POST.get('old_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')

            if not user.check_password(old_password):
                return JsonResponse({'status': 'error', 'message': 'Текущий пароль указан неверно.'}, status=400)

            if new_password != confirm_password:
                return JsonResponse({'status': 'error', 'message': 'Пароли не совпадают.'}, status=400)

            try:
                validate_password(new_password, user)
            except ValidationError as e:
                return JsonResponse({'status': 'error', 'message': ' '.join(e.messages)}, status=400)

            user.set_password(new_password)
            user.save()
            update_session_auth_hash(request, user)
            return JsonResponse({'status': 'success', 'message': 'Пароль изменён.'})

        # 4. ПРИВАТНОСТЬ
        elif form_type == 'privacy':
            value = request.POST.get('profile_visibility', 'everyone')
            profile.profile_visibility = value if value in Profile.Visibility.values else Profile.Visibility.EVERYONE
            # В режиме «Только я» библиотека закрыта в любом случае, а выбор сохраняем на будущее
            if profile.profile_visibility != Profile.Visibility.PRIVATE:
                profile.show_library = 'show_library' in request.POST
            profile.save()
            return JsonResponse({'status': 'success'})

        # 5. УДАЛЕНИЕ АККАУНТА
        elif form_type == 'delete_account':
            username = user.username
            logout(request)
            user.delete()
            messages.success(request, f'Аккаунт {username} удалён.')
            return redirect('mfs:index')

    return render(request, 'users/settings.html', {'profile': profile})

def _user_game_state(request):
    """Какие игры пользователь уже купил, какие лежат в корзине и в списке желаемого."""
    owned, wishlist = [], []
    if request.user.is_authenticated:
        owned = list(request.user.purchased_games.values_list('id', flat=True))
        wishlist = list(_wishlist_games(request.user).values_list('id', flat=True))
    return {'owned_game_ids': owned, 'cart_ids': _cart_ids(request), 'wishlist_ids': wishlist}


def _wishlist_games(user):
    return Game.objects.filter(wishlist__user=user).prefetch_related('genres').order_by('title')


def _favorites(user):
    return list(FavoriteGame.objects.filter(user=user).select_related('game'))


def _pick_featured_game():
    """Игра недели: выбор из отмеченных в админке, а если таких нет — из всех игр."""
    ids = list(Game.objects.filter(is_game_of_the_week=True).order_by('pk').values_list('pk', flat=True))
    if not ids:
        ids = list(Game.objects.order_by('pk').values_list('pk', flat=True))
    if not ids:
        return None, ''

    now = timezone.localtime(timezone.now())
    year, week, _ = now.isocalendar()
    game_id = random.Random(f"{year}-{week}-featured").choice(ids)

    monday_date = now.date() + timedelta(days=7 - now.weekday())
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


def _catalog_category_options(categories, selected):
    """Пункты меню категорий: подборки из админки и автоматические категории, в которых есть игры."""
    counts = Game.objects.aggregate(
        total=Count('pk'),
        **{key: Count('pk', filter=condition) for key, (_, condition) in categories.items()},
    )
    # Подборка только из бесплатных игр дублировала бы категорию «Бесплатные»,
    # поэтому в меню она появляется, лишь когда на неё перешли со страницы магазина
    collections = Collection.objects.annotate(
        games_count=Count('game_products'),
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
    sort = request.GET.get('sort')
    if sort not in CATALOG_SORTS:
        sort = 'new'

    games = Game.objects.prefetch_related('genres').annotate(
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

    title = 'Каталог игр'
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
        'category_options': _catalog_category_options(categories, category),
        'selected_category': category,
        'genres': Genre.objects.annotate(games_count=Count('games')).filter(games_count__gt=0).order_by('name'),
        'selected_genres': selected_genres,
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
        'reviews': game.reviews.select_related('user'),
        'avg_rating': avg_rating,
        'avg_percent': avg_rating / 5 * 100,
        'reviews_count': stats['count'],
        'my_review': my_review,
        **_user_game_state(request),
    })


def login_view(request):
    next_url = _safe_url(request, request.GET.get('next'), reverse('mfs:index'))

    if request.user.is_authenticated:
        return redirect(next_url)

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect(next_url)
        messages.error(request, 'Неверное имя пользователя или пароль')
    else:
        form = AuthenticationForm()

    return render(request, 'users/login.html', {'form': form, 'social_providers': _social_providers(request)})


def logout_view(request):
    # Только POST: иначе разлогинить можно обычной ссылкой или картинкой с чужого сайта
    if request.method == 'POST':
        logout(request)
    return redirect('mfs:index')


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


def _get_cart(request):
    """Корзина в сессии — словарь {id игры: 1}; старые сессии могли хранить список."""
    cart = request.session.get('cart', {})
    if isinstance(cart, list):
        cart = {str(item): 1 for item in cart}
    elif not isinstance(cart, dict):
        cart = {}
    return cart


def _cart_ids(request):
    return [int(key) for key in _get_cart(request) if str(key).isdigit()]


@require_POST
def remove_from_cart(request, game_id):
    cart = _get_cart(request)
    cart.pop(str(game_id), None)
    request.session['cart'] = cart
    return redirect('mfs:cart_detail')


@require_POST
def add_to_cart(request, game_id):
    back_url = _safe_url(request, request.META.get('HTTP_REFERER'), reverse('mfs:index'))

    if not request.user.is_authenticated:
        if _is_ajax(request):
            return JsonResponse({'status': 'login_required'}, status=401)
        return redirect_to_login(back_url)

    game = get_object_or_404(Game, pk=game_id)
    cart = _get_cart(request)
    owned = request.user.purchased_games.filter(pk=game.pk).exists()

    if not owned:
        cart[str(game.pk)] = 1
        request.session['cart'] = cart

    if _is_ajax(request):
        return JsonResponse({'status': 'owned' if owned else 'ok', 'cart_count': len(cart)})

    return redirect(back_url)


def cart_detail(request):
    game_ids = _cart_ids(request)
    state = _user_game_state(request)

    cart_items = list(Game.objects.filter(id__in=game_ids).prefetch_related('genres'))
    recommended_games = (
        Game.objects.exclude(id__in=game_ids + state['owned_game_ids'])
        .prefetch_related('genres')[:3]
    )

    total_price = sum(game.discounted_price for game in cart_items)
    full_price = sum(game.price for game in cart_items)
    total_discount = full_price - total_price

    return render(request, 'store/cart.html', {
        'cart_items': cart_items,
        'total_price': total_price,
        'total_discount': total_discount,
        'recommended_games': recommended_games,
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


@login_required
def checkout(request):
    # Только POST: покупка не должна срабатывать от перехода по ссылке
    if request.method != 'POST':
        return redirect('mfs:cart_detail')

    games = list(Game.objects.filter(id__in=_cart_ids(request)))

    with transaction.atomic():
        request.user.purchased_games.add(*games)
        UserLibrary.objects.bulk_create(
            [UserLibrary(user=request.user, game=game) for game in games],
            ignore_conflicts=True,
        )
        Wishlist.games.through.objects.filter(wishlist__user=request.user, game__in=games).delete()

    request.session['cart'] = {}

    if games:
        messages.success(request, 'Покупка завершена! Игры добавлены в библиотеку.')
    return redirect('mfs:library')


@login_required
def library(request):
    user_games = list(request.user.purchased_games.all().order_by('title'))

    played = dict(
        UserLibrary.objects
        .filter(user=request.user, last_played__isnull=False)
        .values_list('game_id', 'last_played')
    )
    for g in user_games:
        g.user_last_played = played.get(g.id)

    active_id = request.GET.get('active')
    is_launched = request.GET.get('launched') == '1'

    context = {
        'games': user_games,
        'favorites': _favorites(request.user),
        'max_favorites': MAX_FAVORITES,
        'active_id': int(active_id) if active_id and active_id.isdigit() else None,
        'is_launched': is_launched,
    }
    return render(request, 'store/library.html', context)


@login_required
@require_POST
def remove_from_library(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    with transaction.atomic():
        request.user.purchased_games.remove(game)
        UserLibrary.objects.filter(user=request.user, game=game).delete()
        FavoriteGame.objects.filter(user=request.user, game=game).delete()
    return redirect('mfs:library')


@require_POST
def wishlist_toggle(request, game_id):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'login_required'}, status=401)

    game = get_object_or_404(Game, pk=game_id)
    wishlist, _ = Wishlist.objects.get_or_create(user=request.user)
    in_wishlist = not wishlist.games.filter(pk=game.pk).exists()
    if in_wishlist:
        wishlist.games.add(game)
    else:
        wishlist.games.remove(game)

    return JsonResponse({'status': 'success', 'in_wishlist': in_wishlist})


@require_POST
def favorites_update(request):
    """Сохраняет избранное целиком: перетаскивание и кнопки присылают новый порядок игр."""
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'login_required'}, status=401)

    try:
        game_ids = list(dict.fromkeys(int(value) for value in request.POST.getlist('ids')))
    except ValueError:
        return JsonResponse({'status': 'error', 'message': 'Неверный список игр.'}, status=400)

    if len(game_ids) > MAX_FAVORITES:
        return JsonResponse({'status': 'error', 'message': f'В избранное можно добавить до {MAX_FAVORITES} игр.'}, status=400)

    owned = set(request.user.purchased_games.filter(pk__in=game_ids).values_list('pk', flat=True))
    if owned != set(game_ids):
        return JsonResponse({'status': 'error', 'message': 'В избранное можно добавить только купленные игры.'}, status=400)

    with transaction.atomic():
        FavoriteGame.objects.filter(user=request.user).exclude(game_id__in=game_ids).delete()
        for position, game_id in enumerate(game_ids):
            FavoriteGame.objects.update_or_create(
                user=request.user, game_id=game_id, defaults={'position': position}
            )

    template = 'store/_library_favorites.html' if request.POST.get('layout') == 'library' else 'users/_favorites.html'
    html = render_to_string(template, {
        'favorites': _favorites(request.user),
        'max_favorites': MAX_FAVORITES,
        'can_edit': True,
    }, request=request)

    return JsonResponse({'status': 'success', 'html': html, 'ids': game_ids})


def register_view(request):
    if request.user.is_authenticated:
        return redirect('mfs:index')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Бэкендов авторизации два (Django и allauth), поэтому указываем явно
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('mfs:index')
    else:
        form = UserCreationForm()
        
    return render(request, 'users/register.html', {'form': form, 'social_providers': _social_providers(request)})


def _library_stats(user):
    stats = UserLibrary.objects.filter(user=user).aggregate(
        games_count=Count('id'), total_hours=Sum('playtime_hours')
    )
    stats['total_hours'] = stats['total_hours'] or 0
    return stats


@login_required
def profile(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    if request.method == 'POST':
        changed = False

        for field in ('avatar', 'banner'):
            if field in request.FILES:
                error = _clean_image(request.FILES[field])
                if error:
                    messages.error(request, error)
                    return redirect('mfs:profile')
                setattr(profile, field, request.FILES[field])
                changed = True

        if changed:
            profile.save()

        return redirect('mfs:profile')

    recent_games = UserLibrary.objects.filter(
        user=user, 
        last_played__isnull=False
    ).select_related('game').order_by('-last_played')[:3]

    stats = _library_stats(user)

    friendships = Friendship.objects.filter(
        Q(sender=profile) | Q(receiver=profile)
    ).select_related('sender__user', 'receiver__user')

    friends, incoming, outgoing = [], [], []
    for f in friendships:
        if f.status == Friendship.Status.ACCEPTED:
            other = f.receiver if f.sender_id == profile.id else f.sender
            friends.append({'id': f.pk, 'profile': other})
        elif f.status == Friendship.Status.PENDING:
            (outgoing if f.sender_id == profile.id else incoming).append(f)

    context = {
        'recent_games': recent_games,
        'games_count': stats['games_count'],
        'total_hours': stats['total_hours'],
        'achievements_count': 0,
        'owned_games': user.purchased_games.order_by('title'),
        'favorites': _favorites(user),
        'max_favorites': MAX_FAVORITES,
        'can_edit': True,
        'wishlist_games': _wishlist_games(user),
        **_user_game_state(request),
        'friends': friends,
        'incoming_requests': incoming,
        'outgoing_requests': outgoing,
    }

    return render(request, 'users/profile.html', context)

@login_required
@require_POST
def launch_game(request, game_id):
    game = get_object_or_404(request.user.purchased_games, id=game_id)

    library_item, _ = UserLibrary.objects.get_or_create(
        user=request.user,
        game=game
    )

    now = timezone.now()
    library_item.last_played = now
    library_item.save(update_fields=['last_played'])

    if _is_ajax(request):
        return JsonResponse({
            'status': 'success',
            'game_id': game.id,
            'last_played_display': timezone.localtime(now).strftime('%d.%m.%Y в %H:%M'),
        })

    return redirect(f"{reverse('mfs:library')}?active={game_id}&launched=1")

def _get_relation(me, other):
    return Friendship.objects.filter(
        Q(sender=me, receiver=other) | Q(sender=other, receiver=me)
    ).first()


def _my_profile(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return profile

@login_required
def friends_search(request):
    me = _my_profile(request)
    q = request.GET.get('q', '').strip()

    if len(q) < 2:
        return JsonResponse({'users': []})

    profiles = (
        Profile.objects
        .filter(
            Q(user__username__icontains=q) |
            Q(nickname__icontains=q)
        )
        .exclude(pk=me.pk)
        .exclude(profile_visibility='private')
        .select_related('user')
        .order_by('user__username')[:8]
    )

    relations = {}

    for f in Friendship.objects.filter(
        Q(sender=me) | Q(receiver=me)
    ):
        other_id = (
            f.receiver_id if f.sender_id == me.id
            else f.sender_id
        )
        relations[other_id] = f

    users = []

    for p in profiles:
        f = relations.get(p.pk)

        if f is None or f.status == Friendship.Status.REJECTED:
            state = 'none'
        elif f.status == Friendship.Status.ACCEPTED:
            state = 'friends'
        else:
            state = 'sent' if f.sender_id == me.id else 'received'

        users.append({
            'username': p.user.username,
            'nickname': p.nickname or p.user.username,
            'avatar': p.avatar.url if p.avatar else '',
            'color': p.avatar_color or '#2a2a2a',
            'url': reverse('mfs:user_profile', args=[p.user.username]),
            'state': state,
        })

    return JsonResponse({'users': users})


@login_required
@require_POST
def friend_request(request):
    me = _my_profile(request)
    username = request.POST.get('username', '').strip()
    target = Profile.objects.filter(user__username=username).first()

    if not target or target.pk == me.pk:
        return JsonResponse({'status': 'error', 'message': 'Пользователь не найден.'}, status=400)

    if target.profile_visibility == 'private':
        return JsonResponse({'status': 'error', 'message': 'Пользователь не принимает заявки.'}, status=400)

    f = _get_relation(me, target)
    if f is None:
        Friendship.objects.create(sender=me, receiver=target)
    elif f.status == Friendship.Status.ACCEPTED:
        return JsonResponse({'status': 'error', 'message': 'Вы уже друзья.'}, status=400)
    elif f.status == Friendship.Status.PENDING:
        if f.sender_id == me.id:
            return JsonResponse({'status': 'error', 'message': 'Заявка уже отправлена.'}, status=400)
        # человек уже отправил заявку вам — встречная заявка = принятие
        f.status = Friendship.Status.ACCEPTED
        f.save()
    else:  # REJECTED — разрешаем отправить заново
        f.sender, f.receiver = me, target
        f.status = Friendship.Status.PENDING
        f.save()

    return JsonResponse({'status': 'success'})


@login_required
@require_POST
def friend_respond(request, pk):
    me = _my_profile(request)
    f = get_object_or_404(Friendship, pk=pk, receiver=me, status=Friendship.Status.PENDING)
    action = request.POST.get('action')

    if action == 'accept':
        f.status = Friendship.Status.ACCEPTED
    elif action == 'reject':
        f.status = Friendship.Status.REJECTED
    else:
        return JsonResponse({'status': 'error', 'message': 'Неверное действие.'}, status=400)

    f.save()
    return JsonResponse({'status': 'success'})


@login_required
@require_POST
def friend_remove(request, pk):
    """Удалить из друзей или отменить исходящую заявку."""
    me = _my_profile(request)
    f = get_object_or_404(Friendship, Q(sender=me) | Q(receiver=me), pk=pk)
    f.delete()
    return JsonResponse({'status': 'success'})


@login_required
def user_profile(request, username):
    target = get_object_or_404(
        Profile.objects.select_related('user'),
        user__username=username
    )

    me = _my_profile(request)

    # Определяем состояние дружбы
    if me.pk == target.pk:
        state = 'self'
    else:
        relation = _get_relation(me, target)

        if relation is None or relation.status == Friendship.Status.REJECTED:
            state = 'none'
        elif relation.status == Friendship.Status.ACCEPTED:
            state = 'friends'
        elif relation.sender_id == me.pk:
            state = 'sent'
        else:
            state = 'received'


    is_self = (state == 'self')
    visibility = target.profile_visibility

    # «Только я» значит только сам пользователь: администратор этот режим не обходит
    can_view = (
        is_self
        or (request.user.is_staff and visibility != Profile.Visibility.PRIVATE)
        or visibility == 'everyone'
        or (visibility == 'friends' and state == 'friends')
    )

    if not can_view:
        return render(request, 'users/user_profile.html', {
            'target': target,
            'state': state,
            'restricted': True,
        })

    show_library = is_self or target.show_library

    # Недавняя активность пользователя
    recent_games = []
    if show_library:
        recent_games = UserLibrary.objects.filter(
            user=target.user, last_played__isnull=False
        ).select_related('game').order_by('-last_played')[:3]

    stats = _library_stats(target.user)

    # Список друзей пользователя
    friendships = Friendship.objects.filter(
        Q(sender=target) | Q(receiver=target),
        status=Friendship.Status.ACCEPTED
    ).select_related('sender__user', 'receiver__user')

    friends = []

    for friendship in friendships:
        other = (
            friendship.receiver
            if friendship.sender_id == target.pk
            else friendship.sender
        )

        friends.append({
            'id': friendship.pk,
            'profile': other,
        })

    context = {
        'target': target,
        'state': state,
        'recent_games': recent_games,
        'show_library': show_library,
        'favorites': _favorites(target.user) if show_library else [],
        'wishlist_games': _wishlist_games(target.user) if show_library else [],
        'games_count': stats['games_count'],
        'total_hours': stats['total_hours'],
        'friends': friends,
    }

    return render(
        request,
        'users/user_profile.html',
        context
    )

@login_required
@require_POST
def review_submit(request, game_id):
    game = get_object_or_404(Game, pk=game_id)

    try:
        rating = int(request.POST.get('rating', ''))
    except ValueError:
        rating = 0

    if not 1 <= rating <= 5:
        messages.error(request, 'Выберите оценку от 1 до 5.')
        return redirect(f"{reverse('mfs:game_detail', args=[game.pk])}#reviews")

    text = request.POST.get('text', '').strip()[:150]

    Review.objects.update_or_create(
        user=request.user, game=game,
        defaults={'rating': rating, 'text': text},
    )
    return redirect(f"{reverse('mfs:game_detail', args=[game.pk])}#reviews")


@login_required
@require_POST
def review_delete(request, game_id):
    Review.objects.filter(user=request.user, game_id=game_id).delete()
    return redirect(f"{reverse('mfs:game_detail', args=[game_id])}#reviews")