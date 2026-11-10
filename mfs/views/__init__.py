"""Представления магазина, разложенные по разделам сайта.

urls.py и handler404 обращаются к ним как views.<имя>, поэтому все публичные представления
реэкспортируются отсюда.
"""
from .store import custom_page_not_found, home, catalog, game_detail, news, news_detail, game_search_ajax
from .cart import remove_from_cart, add_to_cart, cart_detail, checkout
from .library import library, remove_from_library, launch_game, stop_game, wishlist_toggle, favorites_update
from .accounts import login_view, logout_view, register_view, settings_view, export_data, profile
from .social import friends_search, friend_request, friend_respond, friend_remove, user_profile, review_submit, review_delete

__all__ = [
    'custom_page_not_found',
    'home',
    'catalog',
    'game_detail',
    'news',
    'news_detail',
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
    'login_view',
    'logout_view',
    'register_view',
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
]
