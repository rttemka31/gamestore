from django.urls import path
from . import views
from django.views.defaults import page_not_found

# Задаём пространство имён приложения (рекомендуется):
app_name = 'mfs'

urlpatterns = [
    path('', views.home, name='index'),
    path('catalog/', views.catalog, name='catalog'),
    path('game/<int:game_id>/', views.game_detail, name='game_detail'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/<int:game_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/remove/<int:game_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('api/search/', views.game_search_ajax, name='game_search_ajax'),
    path('library/', views.library, name='library'),
    path('checkout/', views.checkout, name='checkout'),
    path('library/remove/<int:game_id>/', views.remove_from_library, name='remove_from_library'),
    path("news/", views.news, name="news"),
    path("news/<int:pk>/", views.news_detail, name="news_detail"),
    path('wishlist/toggle/<int:game_id>/', views.wishlist_toggle, name='wishlist_toggle'),
    path('favorites/update/', views.favorites_update, name='favorites_update'),
    path('register/', views.register_view, name='register'),
    path('test-404/', lambda request: page_not_found(request, Exception())),
    path("settings/export/", views.export_data, name="export_data"),
    path("profile/", views.profile, name="profile"),
    path('settings/', views.settings_view, name='settings'),
    path('library/launch/<int:game_id>/', views.launch_game, name='launch_game'),
    path('library/stop/<int:game_id>/', views.stop_game, name='stop_game'),
    path('friends/search/', views.friends_search, name='friends_search'),
    path('friends/request/', views.friend_request, name='friend_request'),
    path('friends/respond/<int:pk>/', views.friend_respond, name='friend_respond'),
    path('friends/remove/<int:pk>/', views.friend_remove, name='friend_remove'),
    path('game/<int:game_id>/review/', views.review_submit, name='review_submit'),
    path('game/<int:game_id>/review/delete/', views.review_delete, name='review_delete'),
    path(
        'profile/<str:username>/',
        views.user_profile,
        name='user_profile'
    )
]
