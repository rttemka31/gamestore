"""Общие константы и вспомогательные функции для всех разделов."""
from django.db.models import Count, Q, Sum
from django.utils.http import url_has_allowed_host_and_scheme

from ..models import FavoriteGame, Friendship, Game, NewsLike, Profile, ProfileComment, UserLibrary


MAX_FAVORITES = 6
WALL_LIMIT = 30  # записей стены на странице профиля


def _wall_context(owner, can_post):
    """Последние записи на стене профиля owner и можно ли текущему пользователю писать на ней."""
    comments = ProfileComment.objects.filter(profile=owner).select_related('author__profile')[:WALL_LIMIT]
    return {'wall_comments': comments, 'wall_owner': owner, 'can_post_wall': can_post}


def _with_likes(request, items):
    """Проставляет новостям likes_count и liked (лайкнул ли текущий пользователь) — двумя запросами на все."""
    items = list(items)
    ids = [item.pk for item in items]
    counts = dict(NewsLike.objects.filter(news_id__in=ids).values_list('news_id').annotate(Count('id')))
    liked = set()
    if request.user.is_authenticated:
        liked = set(NewsLike.objects.filter(user=request.user, news_id__in=ids).values_list('news_id', flat=True))
    for item in items:
        item.likes_count = counts.get(item.pk, 0)
        item.liked = item.pk in liked
    return items


def _is_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def _safe_url(request, url, fallback):
    """Возвращает url, только если он ведёт на наш сайт (защита от open redirect)."""
    if url and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return fallback


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


def _library_stats(user):
    stats = UserLibrary.objects.filter(user=user).aggregate(
        games_count=Count('id'), total_seconds=Sum('playtime_seconds')
    )
    # Часы с десятыми, как и время в отдельных играх: 12,6 ч, а не 12
    stats['total_hours'] = round((stats.pop('total_seconds') or 0) / 3600, 1)
    return stats


def _friend_profiles(profile):
    """Профили друзей (принятые заявки в обе стороны) вместе с пользователями, одним запросом."""
    friendships = Friendship.objects.filter(
        Q(sender=profile) | Q(receiver=profile), status=Friendship.Status.ACCEPTED,
    ).select_related('sender__user', 'receiver__user')
    return [f.receiver if f.sender_id == profile.pk else f.sender for f in friendships]


def _my_profile(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return profile
