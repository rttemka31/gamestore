"""Корзина и покупка."""
from decimal import Decimal

from django.urls import reverse

from ..models import UserLibrary
from .base import StoreTestCase


class CartTests(StoreTestCase):
    def test_get_never_changes_cart_or_buys(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('mfs:add_to_cart', args=[self.game.pk])).status_code, 405)

        self.ajax_add(self.game)
        self.assertEqual(self.client.get(reverse('mfs:remove_from_cart', args=[self.game.pk])).status_code, 405)
        self.client.get(reverse('mfs:checkout'))
        self.assertFalse(self.user.purchased_games.exists())

    def test_anonymous_ajax_add_gets_401(self):
        self.assertEqual(self.ajax_add(self.game).status_code, 401)

    def test_add_unknown_game_is_404(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse('mfs:add_to_cart', args=[9999])).status_code, 404)

    def test_owned_game_is_not_added(self):
        self.client.force_login(self.user)
        self.game.owners.add(self.user)
        self.assertEqual(self.ajax_add(self.game).json(), {'status': 'owned', 'cart_count': 0})

    def test_foreign_referer_is_not_followed(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('mfs:add_to_cart', args=[self.game.pk]), headers={'referer': 'https://evil.example/'}
        )
        self.assertRedirects(response, reverse('mfs:index'), fetch_redirect_response=False)

    def test_checkout_then_remove_keeps_library_consistent(self):
        self.client.force_login(self.user)
        self.ajax_add(self.game)
        self.assertEqual(self.client.get(reverse('mfs:cart_detail')).context['total_price'], Decimal('50.00'))

        self.client.post(reverse('mfs:checkout'))
        self.assertTrue(self.user.purchased_games.filter(pk=self.game.pk).exists())
        self.assertTrue(UserLibrary.objects.filter(user=self.user, game=self.game).exists())
        self.assertEqual(self.client.session['cart'], {})

        response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        self.assertIn(self.game.pk, response.context['owned_game_ids'])

        self.client.post(reverse('mfs:remove_from_library', args=[self.game.pk]))
        self.assertFalse(UserLibrary.objects.filter(user=self.user, game=self.game).exists())
