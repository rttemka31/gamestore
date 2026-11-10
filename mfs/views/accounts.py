"""Вход, регистрация, свой профиль, настройки и экспорт данных."""
import re

from allauth.socialaccount.adapter import get_adapter as get_social_adapter
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from ..models import Friendship, Game, News, Profile, Review, UserLibrary
from ..security import (
    LOCK_SECONDS, login_locked, password_check_locked, record_password_check_failure,
    record_registration, registration_limited,
)
from ..sessions import end_device_session, end_other_sessions, list_devices
from .common import MAX_FAVORITES, _favorites, _library_stats, _safe_url, _user_game_state, _wishlist_games
from .store import CATALOG_SORTS


MAX_USERNAME_LENGTH = 24
MAX_IMAGE_SIZE = 5 * 1024 * 1024
ACCENT_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
SITE_VERSION_RE = re.compile(r'^[vV]?(\d+(?:\.\d+)+)')
LOCK_MINUTES = LOCK_SECONDS // 60


class RegisterForm(UserCreationForm):
    """Регистрация с тем же ограничением длины имени, что и при смене имени в настройках.
    Имена, отличающиеся только регистром (Alice и alice), UserCreationForm отклоняет сам."""

    def clean_username(self):
        username = super().clean_username()
        if username and len(username) > MAX_USERNAME_LENGTH:
            raise ValidationError(f'Имя пользователя должно быть не длиннее {MAX_USERNAME_LENGTH} символов.')
        return username


def _step(value, default=1):
    try:
        return min(2, max(0, int(value)))
    except (TypeError, ValueError):
        return default


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
            profile.reduce_motion = 'reduce_motion' in request.POST
            profile.show_hints = 'show_hints' in request.POST
            profile.save()
            return JsonResponse({'status': 'success'})

        # 3. НАСТРОЙКИ КАТАЛОГА
        elif form_type == 'catalog':
            profile.hide_owned_in_catalog = 'hide_owned_in_catalog' in request.POST
            sort = request.POST.get('default_catalog_sort')
            if sort in CATALOG_SORTS:
                profile.default_catalog_sort = sort
            profile.save()
            return JsonResponse({'status': 'success'})

        # 4. СМЕНА ПАРОЛЯ
        elif form_type == 'password':
            old_password = request.POST.get('old_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')

            if password_check_locked(user):
                return JsonResponse({'status': 'error', 'message': f'Слишком много неверных попыток. Попробуйте через {LOCK_MINUTES} минут.'}, status=429)

            if not user.check_password(old_password):
                record_password_check_failure(user)
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

        # 5. ВЫХОД НА ДРУГИХ УСТРОЙСТВАХ
        elif form_type == 'logout_others':
            ended = end_other_sessions(user, request.session.session_key)
            message = f'Завершено сеансов: {ended}.' if ended else 'Других активных сеансов нет.'
            return JsonResponse({'status': 'success', 'message': message})

        elif form_type == 'logout_device':
            if end_device_session(user, request.POST.get('device', ''), request.session.session_key):
                return JsonResponse({'status': 'success', 'message': 'Сеанс на устройстве завершён.'})
            return JsonResponse({'status': 'error', 'message': 'Сеанс уже завершён.'}, status=404)

        # 6. ПРИВАТНОСТЬ
        elif form_type == 'privacy':
            value = request.POST.get('profile_visibility', 'everyone')
            profile.profile_visibility = value if value in Profile.Visibility.values else Profile.Visibility.EVERYONE
            # В режиме «Только я» библиотека закрыта в любом случае, а выбор сохраняем на будущее
            if profile.profile_visibility != Profile.Visibility.PRIVATE:
                profile.show_library = 'show_library' in request.POST
                profile.show_wishlist = 'show_wishlist' in request.POST
                profile.allow_friend_requests = 'allow_friend_requests' in request.POST
            profile.save()
            return JsonResponse({'status': 'success'})

        # 7. УДАЛЕНИЕ АККАУНТА
        elif form_type == 'delete_account':
            # Подтверждение паролем, а у аккаунтов только со входом через соцсети — именем пользователя:
            # иначе аккаунт удалит любой, кто получил доступ к открытой сессии
            confirmation = request.POST.get('confirmation', '')
            if user.has_usable_password():
                if password_check_locked(user):
                    messages.error(request, f'Слишком много неверных попыток. Попробуйте через {LOCK_MINUTES} минут.')
                    return redirect('mfs:settings')
                confirmed = user.check_password(confirmation)
                if not confirmed:
                    record_password_check_failure(user)
            else:
                confirmed = confirmation == user.username
            if not confirmed:
                messages.error(request, 'Аккаунт не удалён: подтверждение указано неверно.')
                return redirect('mfs:settings')

            username = user.username
            logout(request)
            user.delete()
            messages.success(request, f'Аккаунт {username} удалён.')
            return redirect('mfs:index')

    return render(request, 'users/settings.html', {
        'profile': profile,
        'sort_options': [(key, value[0]) for key, value in CATALOG_SORTS.items()],
        'devices': list_devices(user, request.session.session_key),
        'site_version': _site_version(),
        'site_stats': {
            'games': Game.objects.count(),
            'players': get_user_model().objects.filter(is_active=True).count(),
        },
    })


def _site_version():
    """Версия сайта берётся из последней опубликованной новости с номером версии, например «V1.2.0»."""
    item = (
        News.objects.filter(is_published=True, title__iregex=r'^v?[0-9]+(\.[0-9]+)+')
        .order_by('-created_at', '-pk')
        .first()
    )
    if item is None:
        return None
    return {
        'number': SITE_VERSION_RE.match(item.title).group(1),
        'date': item.created_at,
        'url': item.get_absolute_url(),
    }


@login_required
def export_data(request):
    """Все данные пользователя одним JSON-файлом. Пароль и чужие данные в него не входят."""
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)
    friendships = Friendship.objects.filter(
        Q(sender=profile) | Q(receiver=profile), status=Friendship.Status.ACCEPTED
    ).select_related('sender__user', 'receiver__user')

    data = {
        'account': {
            'username': user.username,
            'email': user.email,
            'date_joined': user.date_joined.isoformat(),
            'bio': profile.bio or '',
        },
        'library': [
            {
                'game': entry.game.title,
                'purchased_at': entry.purchased_at.isoformat(),
                'last_played': entry.last_played.isoformat() if entry.last_played else None,
                'playtime_minutes': entry.playtime_seconds // 60,
            }
            for entry in UserLibrary.objects.filter(user=user).select_related('game').order_by('purchased_at')
        ],
        'favorites': [favorite.game.title for favorite in _favorites(user)],
        'wishlist': list(_wishlist_games(user).values_list('title', flat=True)),
        'reviews': [
            {
                'game': review.game.title,
                'rating': review.rating,
                'text': review.text,
                'created_at': review.created_at.isoformat(),
            }
            for review in Review.objects.filter(user=user).select_related('game')
        ],
        'friends': [
            (f.receiver if f.sender_id == profile.pk else f.sender).user.username
            for f in friendships
        ],
    }

    response = JsonResponse(data, json_dumps_params={'ensure_ascii': False, 'indent': 2})
    response['Content-Disposition'] = 'attachment; filename="gamestore-data.json"'
    return response


def login_view(request):
    next_url = _safe_url(request, request.GET.get('next'), reverse('mfs:index'))

    if request.user.is_authenticated:
        return redirect(next_url)

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect(next_url)
        if login_locked(request, request.POST.get('username')):
            messages.error(request, f'Слишком много неудачных попыток входа. Попробуйте снова через {LOCK_MINUTES} минут.')
        else:
            messages.error(request, 'Неверное имя пользователя или пароль')
    else:
        form = AuthenticationForm()

    return render(request, 'users/login.html', {'form': form, 'social_providers': _social_providers(request)})


def logout_view(request):
    # Только POST: иначе разлогинить можно обычной ссылкой или картинкой с чужого сайта
    if request.method == 'POST':
        logout(request)
    return redirect('mfs:index')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('mfs:index')

    if request.method == 'POST' and registration_limited(request):
        # Защита от ботов, создающих аккаунты пачками
        messages.error(request, 'С вашего адреса недавно создано слишком много аккаунтов. Попробуйте позже.')
        form = RegisterForm()
    elif request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            record_registration(request)
            # Бэкендов авторизации два (Django и allauth), поэтому указываем явно
            login(request, user, backend='mfs.security.RateLimitedModelBackend')
            return redirect('mfs:index')
    else:
        form = RegisterForm()
        
    return render(request, 'users/register.html', {'form': form, 'social_providers': _social_providers(request)})


@login_required
def profile(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    if request.method == 'POST':
        changed = False

        # Ник и описание правятся прямо в профиле — с теми же проверками, что и в настройках
        if 'username' in request.POST:
            username = request.POST['username'].strip()
            error = _account_error(user, username, user.email)
            if error:
                messages.error(request, error)
                return redirect('mfs:profile')
            if username != user.username:
                user.username = username
                user.save(update_fields=['username'])
        if 'bio' in request.POST:
            profile.bio = request.POST['bio'].strip()[:150]
            changed = True

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
        'max_username_length': MAX_USERNAME_LENGTH,
        'wishlist_games': _wishlist_games(user),
        **_user_game_state(request),
        'friends': friends,
        'incoming_requests': incoming,
        'outgoing_requests': outgoing,
    }

    return render(request, 'users/profile.html', context)
