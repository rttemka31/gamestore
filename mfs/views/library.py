"""Библиотека: запуск и остановка игр, избранное и желаемое."""
from collections import defaultdict
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import FavoriteGame, Friendship, Game, News, Profile, Review, UserLibrary, Wishlist
from ..templatetags.store_extras import playtime
from .common import MAX_FAVORITES, _favorites, _is_ajax, _my_profile


LIBRARY_NEWS_COUNT = 3
MAX_SESSION = timedelta(hours=12)  # дольше игру, скорее всего, просто забыли закрыть


def _library_news(games):
    """Последние опубликованные новости каждой игры."""
    links = (
        News.games.through.objects
        .filter(game__in=games, news__is_published=True)
        .select_related('news')
        .order_by('-news__created_at', '-news__pk')
    )
    by_game = defaultdict(list)
    for link in links:
        if len(by_game[link.game_id]) < LIBRARY_NEWS_COUNT:
            by_game[link.game_id].append(link.news)
    return by_game


def _friends_by_game(request, games):
    """Друзья с каждой игрой. Тех, кто скрыл библиотеку или весь профиль, не показываем."""
    me = _my_profile(request)
    friendships = Friendship.objects.filter(
        Q(sender=me) | Q(receiver=me), status=Friendship.Status.ACCEPTED
    ).values_list('sender_id', 'receiver_id')
    friend_ids = {sender if receiver == me.pk else receiver for sender, receiver in friendships}

    friends = {
        profile.user_id: profile
        for profile in Profile.objects.filter(pk__in=friend_ids, show_library=True)
        .exclude(profile_visibility=Profile.Visibility.PRIVATE)
        .select_related('user')
    }
    by_game = defaultdict(list)
    owners = Game.owners.through.objects.filter(game__in=games, user_id__in=friends).values_list('game_id', 'user_id')
    for game_id, user_id in owners:
        by_game[game_id].append(friends[user_id])
    return by_game


@login_required
def library(request):
    user_games = list(
        request.user.purchased_games.prefetch_related('genres', 'screenshots').order_by('title')
    )

    now = timezone.now()
    entries = {entry.game_id: entry for entry in UserLibrary.objects.filter(user=request.user)}
    reviews = {review.game_id: review for review in Review.objects.filter(user=request.user)}
    news_by_game = _library_news(user_games)
    friends_by_game = _friends_by_game(request, user_games)

    running = None
    for entry in entries.values():
        if entry.session_started_at and now - entry.session_started_at >= MAX_SESSION:
            _finish_session(entry, now)  # игру забыли закрыть: засчитываем максимум и закрываем
        elif entry.session_started_at:
            running = {'game_id': entry.game_id, 'seconds': int((now - entry.session_started_at).total_seconds())}

    for g in user_games:
        entry = entries.get(g.id)
        g.user_last_played = entry.last_played if entry else None
        g.user_purchased_at = entry.purchased_at if entry else None
        g.user_playtime = entry.playtime_seconds if entry else 0
        g.user_review = reviews.get(g.id)
        g.game_news = news_by_game.get(g.id, [])
        g.friends_with_game = friends_by_game.get(g.id, [])

    active_id = request.GET.get('active')
    if active_id and active_id.isdigit():
        active_id = int(active_id)
    else:
        active_id = running['game_id'] if running else None

    context = {
        'games': user_games,
        'favorites': _favorites(request.user),
        'max_favorites': MAX_FAVORITES,
        'active_id': active_id,
        'running': running,
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


def _finish_session(entry, now):
    """Закрывает сеанс игры и прибавляет его ко времени в игре. Брошенный сеанс засчитывается не дольше MAX_SESSION."""
    if entry.session_started_at is None:
        return 0
    seconds = int(min(max(now - entry.session_started_at, timedelta(0)), MAX_SESSION).total_seconds())
    entry.playtime_seconds += seconds
    entry.session_started_at = None
    entry.save(update_fields=['playtime_seconds', 'session_started_at'])
    return seconds


@login_required
@require_POST
def launch_game(request, game_id):
    game = get_object_or_404(request.user.purchased_games, id=game_id)
    now = timezone.now()

    closed = []
    with transaction.atomic():
        # Одновременно запущена только одна игра: предыдущую закрываем и засчитываем
        running = UserLibrary.objects.select_for_update().filter(user=request.user, session_started_at__isnull=False)
        for other in running.exclude(game=game):
            _finish_session(other, now)
            closed.append({'game_id': other.game_id, 'playtime_display': playtime(other.playtime_seconds)})

        entry, _ = UserLibrary.objects.get_or_create(user=request.user, game=game)
        if entry.session_started_at is None:
            entry.session_started_at = now
        entry.last_played = now
        entry.save(update_fields=['session_started_at', 'last_played'])

    if _is_ajax(request):
        return JsonResponse({
            'status': 'success',
            'game_id': game.id,
            'last_played_display': timezone.localtime(now).strftime('%d.%m.%Y в %H:%M'),
            'session_seconds': int((now - entry.session_started_at).total_seconds()),
            'closed': closed,
        })

    return redirect(f"{reverse('mfs:library')}?active={game_id}")


@login_required
@require_POST
def stop_game(request, game_id):
    entry = get_object_or_404(UserLibrary, user=request.user, game_id=game_id)
    with transaction.atomic():
        entry = UserLibrary.objects.select_for_update().get(pk=entry.pk)
        session_seconds = _finish_session(entry, timezone.now())

    if _is_ajax(request):
        return JsonResponse({
            'status': 'success',
            'game_id': game_id,
            'session_display': playtime(session_seconds),
            'playtime_seconds': entry.playtime_seconds,
            'playtime_display': playtime(entry.playtime_seconds),
        })

    return redirect(f"{reverse('mfs:library')}?active={game_id}")
