"""Друзья, чужие профили и отзывы."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import Friendship, Game, Profile, ProfileComment, Review, ReviewVote, UserLibrary
from .common import _favorites, _library_stats, _my_profile, _wall_context, _wishlist_games

WALL_TEXT_LENGTH = 150


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
    relation = None
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
            'friendship_id': relation.pk if relation else None,
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
        'friendship_id': relation.pk if relation else None,
        'recent_games': recent_games,
        'show_library': show_library,
        'favorites': _favorites(target.user) if show_library else [],
        'wishlist_games': _wishlist_games(target.user) if show_library and (is_self or target.show_wishlist) else [],
        'games_count': stats['games_count'],
        'total_hours': stats['total_hours'],
        'friends': friends,
        # Писать на стене могут владелец и друзья (закрытый профиль друзья не видят — сюда не дойдёт)
        **_wall_context(target, state in ('self', 'friends')),
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

    # Время в игре на момент отзыва; у того, у кого игры нет в библиотеке, — пусто
    entry = UserLibrary.objects.filter(user=request.user, game=game).first()

    Review.objects.update_or_create(
        user=request.user, game=game,
        defaults={'rating': rating, 'text': text, 'playtime_seconds': entry.playtime_seconds if entry else None},
    )
    return redirect(f"{reverse('mfs:game_detail', args=[game.pk])}#reviews")


def _wall_url(request, owner):
    if owner.user_id == request.user.pk:
        return reverse('mfs:profile') + '#wall'
    return reverse('mfs:user_profile', args=[owner.user.username]) + '#wall'


@login_required
@require_POST
def wall_post(request, username):
    """Новая запись на стене профиля. Писать могут владелец и его друзья."""
    owner = get_object_or_404(Profile.objects.select_related('user'), user__username=username)
    me = _my_profile(request)
    back = _wall_url(request, owner)

    relation = None if me.pk == owner.pk else _get_relation(me, owner)
    is_friend = (
        relation is not None and relation.status == Friendship.Status.ACCEPTED
        and owner.profile_visibility != Profile.Visibility.PRIVATE
    )
    if me.pk != owner.pk and not is_friend:
        messages.error(request, 'Оставлять комментарии могут только друзья.')
        return redirect(back)

    text = request.POST.get('text', '').strip()[:WALL_TEXT_LENGTH]
    if not text:
        messages.error(request, 'Комментарий не может быть пустым.')
        return redirect(back)

    ProfileComment.objects.create(author=request.user, profile=owner, text=text)
    return redirect(back)


@login_required
@require_POST
def wall_delete(request, pk):
    """Удалить запись со стены может её автор, владелец стены и администратор."""
    comment = get_object_or_404(ProfileComment.objects.select_related('profile__user'), pk=pk)
    if request.user.pk in (comment.author_id, comment.profile.user_id) or request.user.is_staff:
        comment.delete()
    return redirect(_wall_url(request, comment.profile))


@require_POST
def review_vote(request, review_id):
    """Ставит или снимает отметку «Полезно» на чужом отзыве."""
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'login_required'}, status=401)
    review = get_object_or_404(Review, pk=review_id)
    if review.user_id == request.user.pk:
        return JsonResponse({'status': 'error', 'message': 'Свой отзыв отметить нельзя.'}, status=400)
    vote, created = ReviewVote.objects.get_or_create(user=request.user, review=review)
    if not created:
        vote.delete()
    return JsonResponse({'status': 'success', 'active': created, 'count': review.votes.count()})


@login_required
@require_POST
def review_delete(request, game_id):
    Review.objects.filter(user=request.user, game_id=game_id).delete()
    return redirect(f"{reverse('mfs:game_detail', args=[game_id])}#reviews")
