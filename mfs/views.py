import os
import profile
import random
from datetime import timedelta

from django.template import context
from django.urls import reverse
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Prefetch, Sum
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib import messages
from django.http import JsonResponse, request
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from django.db.models import Prefetch, Sum, Q
from .models import Game, Genre, Collection, UserLibrary, Profile, Dlc, Screenshot, News, Friendship
from django.utils import timezone

def custom_page_not_found(request, exception):
    return render(request, '404.html', status=404)

@login_required
def settings_view(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    if request.method == 'POST':
        form_type = request.POST.get('form')

        # 1. ОБРАБОТКА ПРОФИЛЯ
        if form_type == 'profile':
            user.username = request.POST.get('username', user.username)
            user.email = request.POST.get('email', user.email)
            user.save()

            profile.bio = request.POST.get('bio', '')
            if 'avatar' in request.FILES:
                profile.avatar = request.FILES['avatar']
            if 'banner' in request.FILES:
                profile.banner = request.FILES['banner']

            profile.save()
            return JsonResponse({'status': 'success'})

        # 2. ОБРАБОТКА ВНЕШНЕГО ВИДА И УВЕДОМЛЕНИЙ
        elif form_type == 'appearance':
            profile.disable_blur = 'disable_blur' in request.POST
            profile.accent_color = request.POST.get('accent_color', '#6865f2')
            profile.hide_stats = 'hide_stats' in request.POST
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

            if len(new_password) < 8:
                return JsonResponse({'status': 'error', 'message': 'Пароль должен быть не короче 8 символов.'}, status=400)

            user.set_password(new_password)
            user.save()
            update_session_auth_hash(request, user)
            return JsonResponse({'status': 'success', 'message': 'Пароль изменён.'})

        # 4. ПРИВАТНОСТЬ
        elif form_type == 'privacy':
            profile.profile_visibility = request.POST.get('profile_visibility', 'everyone')
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

@login_required
@require_POST
def update_profile(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    bio = request.POST.get('bio', '').strip()[:150]
    profile.bio = bio
    profile.save()
    return JsonResponse({'status': 'success', 'bio': bio})

def index(request):
    games = list(Game.objects.all())
    game_of_the_week = None
    next_rotation_iso = ""

    if games:
        now = timezone.localtime(timezone.now())
        year, week, _ = now.isocalendar()

        rnd = random.Random(f"{year}-{week}")
        game_of_the_week = rnd.choice(games)

        days_until_monday = 7 - now.weekday()
        next_monday = (now + timedelta(days=days_until_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        next_rotation_iso = next_monday.strftime("%Y-%m-%dT%H:%M:%S")

    return render(request, 'store/index.html', {
        'game_of_the_week': game_of_the_week,
        'next_rotation_iso': next_rotation_iso,
    })


def home(request):
    genres = Genre.objects.all()
    selected_genre_slug = request.GET.get('genre')
    games_queryset = Game.objects.all()
 
    if selected_genre_slug:
        games_queryset = games_queryset.filter(genres__slug=selected_genre_slug).distinct()
 
    collections = Collection.objects.prefetch_related(
        Prefetch(
            'game_products',
            queryset=games_queryset.prefetch_related('genres')
        )
    ).distinct()
 
    # --- Игра недели: детерминированный выбор по номеру недели ---
    # Все пользователи в рамках одной недели видят одну и ту же игру,
    # а в понедельник (ISO-неделя меняется) выбор автоматически обновится.
    featured_game = None
    all_games = list(Game.objects.all())
 
    if all_games:
        now = timezone.localtime(timezone.now())
        year, week, _ = now.isocalendar()
        rnd = random.Random(f"{year}-{week}-featured")  # свой "сид", отдельный от index()
        featured_game = rnd.choice(all_games)
 
    return render(request, 'store/index.html', {
        'featured_game': featured_game,
        'genres': genres,
        'collections': collections,
        'selected_genre_slug': selected_genre_slug,
    })


def game_detail(request, game_id):
    game = get_object_or_404(Game, pk=game_id)
    
    owned_game_ids = []
    if request.user.is_authenticated:
        owned_game_ids = list(UserLibrary.objects.filter(user=request.user).values_list('game_id', flat=True))
    
    cart = request.session.get('cart', {})
    if not isinstance(cart, dict):
        cart = {}

    cart_ids = [int(k) for k in cart.keys() if str(k).isdigit()]

    return render(request, 'store/game_detail.html', {
        'game': game,
        'owned_game_ids': owned_game_ids,
        'cart_ids': cart_ids,
    })


def login_view(request):
    if request.user.is_authenticated:
        return redirect('mfs:index')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('mfs:index')
            else:
                messages.error(request, 'Неверное имя пользователя или пароль')
        else:
            messages.error(request, 'Неверное имя пользователя или пароль')
    else:
        form = AuthenticationForm()

    return render(request, 'users/login.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('mfs:index')


def news(request):
    selected_category = request.GET.get('category', '').strip()
    selected_month = request.GET.get('month', '').strip()  # Ожидаем формат 'YYYY-MM'

    news_qs = News.objects.all().order_by('-created_at')

    # Фильтрация по категории
    if selected_category:
        news_qs = news_qs.filter(category=selected_category)

    # Фильтрация по году и месяцу
    if selected_month:
        try:
            year, month = map(int, selected_month.split('-'))
            news_qs = news_qs.filter(created_at__year=year, created_at__month=month)
        except ValueError:
            pass

    # Получаем уникальные сочетания Месяц + Год, в которых есть новости
    archive_months = News.objects.dates('created_at', 'month', order='DESC')

    # Категории из модели (тут используем CATEGORY_CHOICES из News)
    categories = News.CATEGORY_CHOICES if hasattr(News, 'CATEGORY_CHOICES') else []

    context = {
        'news_list': news_qs,
        'categories': categories,
        'archive_months': archive_months,
        'selected_category': selected_category,
        'selected_month': selected_month,
    }
    return render(request, 'store/news.html', context)


def get_clean_cart(request):
    cart = request.session.get('cart', {})
    if isinstance(cart, list):
        cart = {str(item): 1 for item in cart}
    elif not isinstance(cart, dict):
        cart = {}
    return cart


def remove_from_cart(request, game_id):
    cart = get_clean_cart(request)
    cart.pop(str(game_id), None)
    cart.pop(int(game_id), None)
    
    request.session['cart'] = cart
    request.session.modified = True
    return redirect('mfs:cart_detail')


@login_required
def add_to_cart(request, game_id):
    cart = request.session.get('cart', {})
    if isinstance(cart, list):
        cart = {str(item): 1 for item in cart}
    elif not isinstance(cart, dict):
        cart = {}
    
    str_id = str(game_id)
    if str_id not in cart:
        cart[str_id] = 1
    
    request.session['cart'] = cart
    request.session.modified = True
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'status': 'ok',
            'cart_count': len(cart)
        })
        
    return redirect(request.META.get('HTTP_REFERER', 'mfs:index'))


def cart_detail(request):
    cart = request.session.get('cart', [])
    
    if isinstance(cart, dict):
        game_ids = list(cart.keys())
    elif isinstance(cart, list):
        game_ids = cart
    else:
        game_ids = []

    cart_items = Game.objects.filter(id__in=game_ids)
    recommended_games = Game.objects.exclude(id__in=game_ids)[:3]

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

    games = Game.objects.filter(title__icontains=query)[:5]
    results = []

    for game in games:
        genres_str = ", ".join([g.name for g in game.genres.all()]) if hasattr(game, 'genres') else ""
        discount = getattr(game, 'discount', 0)
        
        if discount > 0:
            if hasattr(game, 'old_price') and game.old_price:
                old_p = int(game.old_price)
                curr_p = int(game.price)
            else:
                old_p = int(game.price)
                curr_p = int(float(game.price) * (1 - discount / 100))
        else:
            old_p = None
            curr_p = int(game.price)

        results.append({
            'id': game.id,
            'title': game.title,
            'price': curr_p,
            'old_price': old_p,
            'discount': discount,
            'cover_url': game.cover.url if game.cover else '',
            'genres': genres_str,
            'is_exclusive': getattr(game, 'is_not_on_steam', False),
        })

    return JsonResponse({'games': results})


@login_required
def checkout(request):
    cart = request.session.get('cart', [])
    game_ids = list(cart.keys()) if isinstance(cart, dict) else cart

    games = Game.objects.filter(id__in=game_ids)
    for game in games:
        game.owners.add(request.user)

    request.session['cart'] = []
    request.session.modified = True

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
        'active_id': int(active_id) if active_id and active_id.isdigit() else None,
        'is_launched': is_launched,
    }
    return render(request, 'store/library.html', context)


@login_required
@require_POST
def remove_from_library(request, game_id):
    game = get_object_or_404(Game, id=game_id)
    request.user.purchased_games.remove(game)
    return redirect('mfs:library')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('mfs:index')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('mfs:index')
    else:
        form = UserCreationForm()
        
    return render(request, 'users/register.html', {'form': form})


@login_required
def profile(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    if request.method == 'POST':
        changed = False

        if 'avatar' in request.FILES:
            profile.avatar = request.FILES['avatar']
            changed = True

        if 'banner' in request.FILES:
            profile.banner = request.FILES['banner']
            changed = True

        if changed:
            profile.save()

        return redirect('mfs:profile')

    recent_games = UserLibrary.objects.filter(
        user=user, 
        last_played__isnull=False
    ).select_related('game').order_by('-last_played')[:3]

    games_count = UserLibrary.objects.filter(user=user).count()

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
        'games_count': games_count,
        'total_hours': 0,
        'achievements_count': 0,
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

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'status': 'success',
            'game_id': game.id,
            'last_played_display': timezone.localtime(now).strftime('%d.%m.%Y в %H:%M'),
        })

    return redirect(f"{reverse('mfs:library')}?active={game_id}&launched=1")

# Вспомогательная функция для очистки неиспользуемых файлов (вызывать при необходимости)
def clean_media_files():
    used_files = set()

    def add_file(field):
        if field and getattr(field, 'name', None):
            try:
                if os.path.exists(field.path):
                    used_files.add(os.path.normpath(field.path))
            except ValueError:
                pass

    for g in Game.objects.all():
        for attr in ['cover', 'trailer_file', 'icon', 'cover_hd']:
            if hasattr(g, attr): 
                add_file(getattr(g, attr))

    for d in Dlc.objects.all():
        for attr in ['cover', 'trailer_file', 'icon', 'cover_hd']:
            if hasattr(d, attr): 
                add_file(getattr(d, attr))

    for sc in Screenshot.objects.all():
        if hasattr(sc, 'image'): 
            add_file(sc.image)

    deleted_count = 0
    media_dir = settings.MEDIA_ROOT

    for root, dirs, files in os.walk(media_dir):
        for file in files:
            file_path = os.path.normpath(os.path.join(root, file))
            if file_path not in used_files:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    print(f"Ошибка удаления {file}: {e}")

    print(f"Готово! Очищено файлов: {deleted_count}")

def _get_relation(me, other):
    return Friendship.objects.filter(
        Q(sender=me, receiver=other) | Q(sender=other, receiver=me)
    ).first()


def _my_profile(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return profile


from django.db.models import Q
from django.urls import reverse


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
        .select_related('user')[:8]
    )

    relations = {}

    for f in Friendship.objects.filter(
        Q(sender=me) | Q(receiver=me)
    ):
        other_id = (
            f.receiver_id
            if f.sender_id == me.id
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
            state = (
                'sent'
                if f.sender_id == me.id
                else 'received'
            )

        users.append({
            'username': p.user.username,
            'nickname': p.nickname or p.user.username,
            'avatar': p.avatar.url if p.avatar else '',
            'color': p.avatar_color or '#2a2a2a',
            'url': reverse(
                'mfs:user_profile',
                args=[p.user.username]
            ),
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
    profile = get_object_or_404(
        Profile.objects.select_related('user'),
        user__username=username
    )

    return render(request, 'users/user_profile.html', {
        'profile': profile,
    })