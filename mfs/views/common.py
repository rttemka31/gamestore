"""Общие константы и вспомогательные функции для всех разделов."""
from django.db.models import Count, Sum
from django.utils.http import url_has_allowed_host_and_scheme

from ..models import FavoriteGame, Game, Profile, UserLibrary


MAX_FAVORITES = 6


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
    stats['total_hours'] = (stats.pop('total_seconds') or 0) // 3600
    return stats


def _my_profile(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return profile
