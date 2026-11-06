"""Библиотека, желаемое, избранное и сеансы игры."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from ..models import FavoriteGame, Friendship, Game, News, Profile, Review, UserLibrary, Wishlist
from ..templatetags.store_extras import playtime
from .base import StoreTestCase


class LibraryPanelTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.game.owners.add(self.user)
        self.url = reverse('mfs:library')

    def panel_game(self):
        return self.client.get(self.url).context['games'][0]

    def test_shows_playtime_size_and_missing_size(self):
        UserLibrary.objects.create(user=self.user, game=self.game, playtime_seconds=2 * 3600 + 5 * 60)
        self.assertContains(self.client.get(self.url), '2 ч 5 мин')
        self.assertContains(self.client.get(self.url), 'Не указан')

        Game.objects.filter(pk=self.game.pk).update(size_gb=Decimal('85.5'))
        response = self.client.get(self.url)
        self.assertContains(response, '85,5 ГБ')
        self.assertNotContains(response, 'Не указан')

    def test_about_section_is_collapsed_below_the_news(self):
        Game.objects.filter(pk=self.game.pk).update(description='Рекламный текст')
        News.objects.create(title='Про эту игру', description='Текст').games.add(self.game)
        content = self.client.get(self.url).content.decode()
        self.assertIn('<details class="library-about">', content)
        self.assertLess(content.index('Новости игры'), content.index('Рекламный текст'))

    def test_only_published_news_of_this_game_are_shown(self):
        News.objects.create(title='Новость магазина', description='Текст')
        News.objects.create(title='Про другую игру', description='Текст').games.add(self.game2)

        response = self.client.get(self.url)
        self.assertEqual(response.context['games'][0].game_news, [])
        self.assertNotContains(response, 'Новости игры')
        self.assertNotContains(response, 'Новость магазина')

        own = News.objects.create(title='Про эту игру', description='Текст')
        own.games.add(self.game)
        News.objects.create(title='Черновик', description='Текст', is_published=False).games.add(self.game)

        response = self.client.get(self.url)
        self.assertEqual(response.context['games'][0].game_news, [own])
        self.assertContains(response, 'Новости игры')

    def test_friends_who_hide_their_games_are_not_listed(self):
        self.game.owners.add(self.other)
        stranger = User.objects.create_user('carol', password='Str0ng-pass-123')
        self.game.owners.add(stranger)
        self.assertEqual(self.panel_game().friends_with_game, [])

        Friendship.objects.create(sender=self.user.profile, receiver=self.other.profile, status=Friendship.Status.ACCEPTED)
        Friendship.objects.create(sender=stranger.profile, receiver=self.user.profile)
        self.assertEqual(self.panel_game().friends_with_game, [self.other.profile])

        Profile.objects.filter(user=self.other).update(show_library=False)
        self.assertEqual(self.panel_game().friends_with_game, [])

        Profile.objects.filter(user=self.other).update(show_library=True, profile_visibility='private')
        self.assertEqual(self.panel_game().friends_with_game, [])

    def test_review_block_follows_my_review(self):
        self.assertContains(self.client.get(self.url), 'Оставить отзыв')
        Review.objects.create(user=self.user, game=self.game, rating=4, text='Хорошая')
        response = self.client.get(self.url)
        self.assertContains(response, 'Оценка: 4 из 5')
        self.assertContains(response, 'Изменить отзыв')

    def test_game_panel_escapes_news_and_review_text(self):
        Review.objects.create(user=self.user, game=self.game, rating=5, text='<script>alert(1)</script>')
        self.assertNotContains(self.client.get(self.url), '<script>alert(1)')

    def test_empty_library_still_renders(self):
        self.game.owners.remove(self.user)
        self.assertContains(self.client.get(self.url), 'В вашей библиотеке пока нет игр')


class WishlistTests(StoreTestCase):
    def toggle(self, game):
        return self.client.post(reverse('mfs:wishlist_toggle', args=[game.pk]))

    def test_toggle_adds_and_removes(self):
        self.client.force_login(self.user)
        self.assertTrue(self.toggle(self.game).json()['in_wishlist'])
        self.assertContains(self.client.get(reverse('mfs:profile')), 'Alpha')
        self.assertFalse(self.toggle(self.game).json()['in_wishlist'])
        self.assertFalse(Wishlist.objects.get(user=self.user).games.exists())

    def test_requires_login_and_post(self):
        self.assertEqual(self.toggle(self.game).status_code, 401)

        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('mfs:wishlist_toggle', args=[self.game.pk])).status_code, 405)
        self.assertEqual(self.client.post(reverse('mfs:wishlist_toggle', args=[9999])).status_code, 404)

    def test_heart_is_on_every_cover_and_works_for_owned_games(self):
        self.client.force_login(self.user)
        self.game.owners.add(self.user)

        response = self.client.get(reverse('mfs:catalog'))
        self.assertContains(response, 'wishlist-btn', count=2)
        self.assertTrue(self.toggle(self.game).json()['in_wishlist'])

    def test_no_heart_outside_catalog_game_page_and_own_wishlist(self):
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse('mfs:index')), 'js-wishlist-toggle')
        self.assertContains(self.client.get(reverse('mfs:game_detail', args=[self.game.pk])), 'js-wishlist-toggle')

        self.toggle(self.game)
        self.assertContains(self.client.get(reverse('mfs:profile')), 'js-wishlist-toggle')

        self.client.force_login(self.other)
        response = self.client.get(reverse('mfs:user_profile', args=[self.user.username]))
        self.assertContains(response, 'Alpha')
        self.assertNotContains(response, 'js-wishlist-toggle')

    def test_purchase_removes_game_from_wishlist(self):
        self.client.force_login(self.user)
        self.toggle(self.game)
        self.toggle(self.game2)
        self.ajax_add(self.game)
        self.client.post(reverse('mfs:checkout'))
        self.assertEqual(list(Wishlist.objects.get(user=self.user).games.all()), [self.game2])


class FavoritesTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.game.owners.add(self.user)
        self.game2.owners.add(self.user)

    def save(self, *games, layout='profile'):
        return self.client.post(reverse('mfs:favorites_update'), {'ids': [g.pk for g in games], 'layout': layout})

    def stored(self):
        return [f.game for f in FavoriteGame.objects.filter(user=self.user)]

    def test_add_reorder_and_remove(self):
        self.assertEqual(self.save(self.game, self.game2).status_code, 200)
        self.assertEqual(self.stored(), [self.game, self.game2])

        response = self.save(self.game2, self.game)
        self.assertEqual(self.stored(), [self.game2, self.game])
        self.assertIn('Beta', response.json()['html'])

        self.save(self.game)
        self.assertEqual(self.stored(), [self.game])

    def test_library_layout_uses_library_markup(self):
        self.assertIn('fav-row', self.save(self.game, layout='library').json()['html'])

    def test_only_owned_games(self):
        foreign = Game.objects.create(author=self.other, title='Foreign', price=1)
        self.assertEqual(self.save(foreign).status_code, 400)
        self.assertEqual(self.stored(), [])

    def test_limit_and_bad_input(self):
        games = [Game.objects.create(author=self.other, title=f'G{i}', price=1) for i in range(7)]
        self.user.purchased_games.add(*games)
        self.assertEqual(self.save(*games).status_code, 400)
        self.assertEqual(self.client.post(reverse('mfs:favorites_update'), {'ids': ['abc']}).status_code, 400)
        self.assertEqual(self.client.get(reverse('mfs:favorites_update')).status_code, 405)

    def test_anonymous_gets_login_response(self):
        self.client.logout()
        self.assertEqual(self.save(self.game).status_code, 401)

    def test_removed_from_library_leaves_favorites(self):
        self.save(self.game)
        self.client.post(reverse('mfs:remove_from_library', args=[self.game.pk]))
        self.assertEqual(self.stored(), [])

    def test_shown_on_public_profile_without_edit_controls(self):
        self.save(self.game)
        self.client.force_login(self.other)
        response = self.client.get(reverse('mfs:user_profile', args=['alice']))
        self.assertContains(response, 'fav-card')
        self.assertNotContains(response, 'data-fav-toggle')


class PlaySessionTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.game.owners.add(self.user)
        self.game2.owners.add(self.user)

    def post(self, name, game):
        return self.client.post(reverse(name, args=[game.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def entry(self, game):
        return UserLibrary.objects.get(user=self.user, game=game)

    def started(self, game, ago):
        UserLibrary.objects.filter(user=self.user, game=game).update(session_started_at=timezone.now() - ago)

    def test_launch_then_stop_adds_the_session_to_playtime(self):
        self.assertEqual(self.post('mfs:launch_game', self.game).json()['session_seconds'], 0)
        self.assertIsNotNone(self.entry(self.game).session_started_at)

        self.started(self.game, timedelta(minutes=25, seconds=10))
        data = self.post('mfs:stop_game', self.game).json()
        self.assertEqual(data['session_display'], '25 мин')
        self.assertEqual(self.entry(self.game).playtime_seconds, 25 * 60 + 10)
        self.assertIsNone(self.entry(self.game).session_started_at)

        # Повторная остановка ничего не добавляет
        self.post('mfs:stop_game', self.game)
        self.assertEqual(self.entry(self.game).playtime_seconds, 25 * 60 + 10)

    def test_launching_another_game_closes_the_running_one(self):
        self.post('mfs:launch_game', self.game)
        self.started(self.game, timedelta(hours=1))

        data = self.post('mfs:launch_game', self.game2).json()
        self.assertEqual(data['closed'], [{'game_id': self.game.pk, 'playtime_display': '1 ч'}])
        self.assertIsNone(self.entry(self.game).session_started_at)
        self.assertIsNotNone(self.entry(self.game2).session_started_at)

    def test_relaunching_the_same_game_keeps_the_session(self):
        self.post('mfs:launch_game', self.game)
        self.started(self.game, timedelta(minutes=5))
        self.assertGreaterEqual(self.post('mfs:launch_game', self.game).json()['session_seconds'], 300)

    def test_forgotten_session_counts_at_most_twelve_hours(self):
        self.post('mfs:launch_game', self.game)
        self.started(self.game, timedelta(days=3))

        response = self.client.get(reverse('mfs:library'))
        self.assertIsNone(response.context['running'])
        self.assertEqual(self.entry(self.game).playtime_seconds, 12 * 3600)

    def test_library_reports_the_running_game(self):
        self.post('mfs:launch_game', self.game2)
        response = self.client.get(reverse('mfs:library'))
        self.assertEqual(response.context['running']['game_id'], self.game2.pk)
        self.assertEqual(response.context['active_id'], self.game2.pk)
        self.assertContains(response, f'data-running-game="{self.game2.pk}"')

    def test_profiles_show_playtime_and_who_is_playing_now(self):
        UserLibrary.objects.create(user=self.user, game=self.game, playtime_seconds=95 * 60, last_played=timezone.now())
        self.assertContains(self.client.get(reverse('mfs:profile')), '1 ч 35 мин в игре')

        self.post('mfs:launch_game', self.game)
        self.assertContains(self.client.get(reverse('mfs:profile')), 'Сейчас в игре')

        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse('mfs:user_profile', args=['alice'])), 'Сейчас в игре')

    def test_only_owned_games_can_be_launched(self):
        self.game.owners.remove(self.user)
        self.assertEqual(self.post('mfs:launch_game', self.game).status_code, 404)
        self.assertEqual(self.post('mfs:stop_game', self.game).status_code, 404)

    def test_playtime_format(self):
        cases = {0: '0 мин', 59: '0 мин', 45 * 60: '45 мин', 3600: '1 ч', 3 * 3600 + 20 * 60: '3 ч 20 мин', 127 * 3600 + 59 * 60: '127 ч'}
        for seconds, expected in cases.items():
            self.assertEqual(playtime(seconds), expected, seconds)
