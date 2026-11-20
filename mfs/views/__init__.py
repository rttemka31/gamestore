"""Представления магазина, разложенные по разделам сайта.

urls.py и handler404 обращаются к ним как views.<имя>, поэтому все публичные представления
реэкспортируются отсюда.
"""
from .store import custom_page_not_found, home, catalog, game_detail, news, news_detail, news_like, game_search_ajax
from .cart import remove_from_cart, add_to_cart, cart_detail, checkout, gift_game, gifts_seen
from .library import (
    library, remove_from_library, launch_game, stop_game, library_seen, wishlist_toggle, favorites_update,
)
from .accounts import (
    allauth_page_redirect, login_view, logout_view, register_view, settings_view, export_data, profile,
    password_reset, password_reset_confirm,
)
from .social import (
    friends_search, friend_request, friend_respond, friend_remove, user_profile, review_submit, review_delete,
    review_vote, wall_post, wall_delete,
)
from .stats import admin_stats

__all__ = [
    'custom_page_not_found',
    'home',
    'catalog',
    'game_detail',
    'news',
    'news_detail',
    'news_like',
    'game_search_ajax',
    'remove_from_cart',
    'add_to_cart',
    'cart_detail',
    'checkout',
    'library',
    'remove_from_library',
    'launch_game',
    'stop_game',
    'wishlist_toggle',
    'favorites_update',
    'allauth_page_redirect',
    'login_view',
    'logout_view',
    'register_view',
    'password_reset',
    'password_reset_confirm',
    'settings_view',
    'export_data',
    'profile',
    'friends_search',
    'friend_request',
    'friend_respond',
    'friend_remove',
    'user_profile',
    'review_submit',
    'review_delete',
    'review_vote',
    'admin_stats',
    'wall_post',
    'wall_delete',
]
