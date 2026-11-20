"""Корзина и оформление покупки."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import Game, Gift, UserLibrary, Wishlist
from .common import _cart_ids, _friend_profiles, _get_cart, _is_ajax, _my_profile, _safe_url, _user_game_state

GIFT_MESSAGE_LENGTH = 200


@require_POST
def remove_from_cart(request, game_id):
    cart = _get_cart(request)
    cart.pop(str(game_id), None)
    request.session['cart'] = cart
    return redirect('mfs:cart_detail')


@require_POST
def add_to_cart(request, game_id):
    back_url = _safe_url(request, request.META.get('HTTP_REFERER'), reverse('mfs:index'))

    if not request.user.is_authenticated:
        if _is_ajax(request):
            return JsonResponse({'status': 'login_required'}, status=401)
        return redirect_to_login(back_url)

    game = get_object_or_404(Game, pk=game_id)
    cart = _get_cart(request)
    owned = request.user.purchased_games.filter(pk=game.pk).exists()

    if not owned:
        cart[str(game.pk)] = 1
        request.session['cart'] = cart

    if _is_ajax(request):
        return JsonResponse({'status': 'owned' if owned else 'ok', 'cart_count': len(cart)})

    return redirect(back_url)


def cart_detail(request):
    game_ids = _cart_ids(request)
    state = _user_game_state(request)

    cart_items = list(Game.objects.filter(id__in=game_ids).prefetch_related('genres'))
    recommended_games = (
        Game.objects.exclude(id__in=game_ids + state['owned_game_ids'])
        .prefetch_related('genres')[:3]
    )

    total_price = sum(game.discounted_price for game in cart_items)
    full_price = sum(game.price for game in cart_items)
    total_discount = full_price - total_price

    return render(request, 'store/cart.html', {
        'cart_items': cart_items,
        'total_price': total_price,
        'total_discount': total_discount,
        'recommended_games': recommended_games,
    })


@login_required
def checkout(request):
    # Только POST: покупка не должна срабатывать от перехода по ссылке
    if request.method != 'POST':
        return redirect('mfs:cart_detail')

    games = list(Game.objects.filter(id__in=_cart_ids(request)))

    with transaction.atomic():
        request.user.purchased_games.add(*games)
        UserLibrary.objects.bulk_create(
            # Цена со скидкой на момент покупки — для статистики продаж в админке
            [UserLibrary(user=request.user, game=game, price_paid=game.discounted_price) for game in games],
            ignore_conflicts=True,
        )
        Wishlist.games.through.objects.filter(wishlist__user=request.user, game__in=games).delete()

    request.session['cart'] = {}

    if games:
        messages.success(request, 'Покупка завершена! Игры добавлены в библиотеку.')
    return redirect('mfs:library')


@login_required
@require_POST
def gift_game(request, game_id):
    """Дарит платную игру другу: она сразу попадает в его библиотеку, как при обычной покупке."""
    game = get_object_or_404(Game, pk=game_id)
    back = reverse('mfs:game_detail', args=[game.pk])

    if game.discounted_price <= 0:
        messages.error(request, 'Подарить можно только платную игру.')
        return redirect(back)

    # Дарить можно только друзьям: id получателя сверяется со списком друзей, а не берётся на веру
    friend_id = request.POST.get('friend', '')
    friend = next(
        (p.user for p in _friend_profiles(_my_profile(request)) if str(p.user_id) == friend_id), None,
    )
    if friend is None:
        messages.error(request, 'Выберите друга, которому хотите подарить игру.')
        return redirect(back)

    message = request.POST.get('message', '').strip()[:GIFT_MESSAGE_LENGTH]

    with transaction.atomic():
        if game.owners.filter(pk=friend.pk).exists():
            messages.error(request, f'У {friend.username} уже есть эта игра.')
            return redirect(back)
        game.owners.add(friend)
        UserLibrary.objects.get_or_create(user=friend, game=game, defaults={'price_paid': game.discounted_price})
        Wishlist.games.through.objects.filter(wishlist__user=friend, game=game).delete()
        Gift.objects.create(sender=request.user, receiver=friend, game=game, message=message)

    messages.success(request, f'Игра «{game.title}» подарена {friend.username}!')
    return redirect(back)


@login_required
@require_POST
def gifts_seen(request):
    """Получатель закрыл окно «Вам подарили игру»: больше его не показываем."""
    ids = [int(pk) for pk in request.POST.getlist('ids') if pk.isdigit()]
    Gift.objects.filter(receiver=request.user, pk__in=ids).update(seen=True)
    return JsonResponse({'status': 'success'})
