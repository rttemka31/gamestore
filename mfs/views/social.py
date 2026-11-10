"""Друзья, чужие профили и отзывы."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import Friendship, Game, Profile, Review, UserLibrary
from .common import _favorites, _library_stats, _my_profile, _wishlist_games


def _get_relation(me, other):
    return Friendship.objects.filter(
        Q(sender=me, receiver=other) | Q(sender=other, receiver=me)
    ).first()


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
            state = 'none' if p.allow_friend_requests else 'closed'
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
    # Встречная заявка всё равно проходит: человек сам уже позвал вас в друзья
    is_new_request = f is None or f.status == Friendship.Status.REJECTED
    if is_new_request and not target.allow_friend_requests:
        return JsonResponse({'status': 'error', 'message': 'Пользователь не принимает заявки.'}, status=400)

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
        'wishlist_games': _wishlist_games(target.user) if show_library and (is_self or target.show_wishlist) else [],
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
