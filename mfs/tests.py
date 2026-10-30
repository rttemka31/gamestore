import io
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import Collection, FavoriteGame, Friendship, Game, Genre, News, Profile, Review, UserLibrary, Wishlist
from .templatetags.store_extras import news_format, news_plain

MEDIA_ROOT = tempfile.mkdtemp()


def make_png():
    buffer = io.BytesIO()
    Image.new('RGB', (2, 2)).save(buffer, 'PNG')
    return SimpleUploadedFile('a.png', buffer.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class StoreTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user('alice', password='Str0ng-pass-123')
        self.other = User.objects.create_user('bob', password='Str0ng-pass-123')
        self.game = Game.objects.create(author=self.other, title='Alpha', price=Decimal('100'), discount=50)
        self.game2 = Game.objects.create(author=self.other, title='Beta', price=Decimal('300'))

    def ajax_add(self, game):
        return self.client.post(
            reverse('mfs:add_to_cart', args=[game.pk]), headers={'x-requested-with': 'XMLHttpRequest'}
        )


class AuthTests(StoreTestCase):
    def test_register_logs_user_in_and_creates_profile(self):
        response = self.client.post(reverse('mfs:register'), {
            'username': 'newbie', 'password1': 'Str0ng-pass-123', 'password2': 'Str0ng-pass-123',
        })
        self.assertRedirects(response, reverse('mfs:index'))
        self.assertTrue(Profile.objects.filter(user__username='newbie').exists())
        self.assertEqual(int(self.client.session['_auth_user_id']), User.objects.get(username='newbie').pk)

    def test_login_honours_safe_next_only(self):
        data = {'username': 'alice', 'password': 'Str0ng-pass-123'}
        response = self.client.post(reverse('mfs:login') + '?next=/library/', data)
        self.assertRedirects(response, '/library/')

        self.client.logout()
        response = self.client.post(reverse('mfs:login') + '?next=https://evil.example/', data)
        self.assertRedirects(response, reverse('mfs:index'))

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.client.get(reverse('mfs:logout'))
        self.assertIn('_auth_user_id', self.client.session)
        self.client.post(reverse('mfs:logout'))
        self.assertNotIn('_auth_user_id', self.client.session)


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


class CatalogTests(StoreTestCase):
    def test_sort_by_final_price_uses_discount(self):
        # Alpha: 100 со скидкой 50% = 50; Beta: 300
        games = list(self.client.get(reverse('mfs:catalog') + '?sort=price_desc').context['page'])
        self.assertEqual([g.title for g in games], ['Beta', 'Alpha'])

    def test_filters(self):
        genre = Genre.objects.create(name='RPG', slug='rpg')
        collection = Collection.objects.create(title='Top', slug='top')
        self.game.genres.add(genre)
        self.game2.collections.add(collection)

        for query, expected in (
            ('?genre=rpg', ['Alpha']),
            ('?category=top', ['Beta']),
            ('?category=sale', ['Alpha']),
            ('?category=unknown', ['Alpha', 'Beta']),
            ('?q=bet', ['Beta']),
            ('?sort=rating&page=999', ['Alpha', 'Beta']),
        ):
            games = self.client.get(reverse('mfs:catalog') + query).context['page']
            self.assertEqual(sorted(g.title for g in games), expected, query)

    def test_automatic_categories(self):
        free = Game.objects.create(author=self.other, title='Free', price=0)
        gift = Game.objects.create(author=self.other, title='Gift', price=50, discount=100)
        exclusive = Game.objects.create(author=self.other, title='Excl', price=10, is_not_on_steam=True)
        Game.objects.filter(pk__in=[self.game.pk, self.game2.pk, free.pk, gift.pk, exclusive.pk]).update(
            release_date='2000-01-01'
        )
        fresh = Game.objects.create(author=self.other, title='Fresh', price=10)

        for category, expected in (
            ('free', ['Free', 'Gift']),
            ('exclusive', ['Excl']),
            ('new', ['Fresh']),
        ):
            games = self.client.get(reverse('mfs:catalog') + f'?category={category}').context['page']
            self.assertEqual(sorted(g.title for g in games), expected, category)
        self.assertEqual(fresh.title, 'Fresh')

    def test_several_genres_do_not_duplicate_games(self):
        first = Genre.objects.create(name='RPG', slug='rpg')
        second = Genre.objects.create(name='MOBA', slug='moba')
        self.game.genres.add(first, second)
        self.game2.genres.add(second)

        response = self.client.get(reverse('mfs:catalog') + '?genre=rpg&genre=moba')
        self.assertEqual(sorted(g.title for g in response.context['page']), ['Alpha', 'Beta'])
        self.assertEqual(response.context['page'].paginator.count, 2)

    def test_category_menu_hides_empty_and_all_free_collections(self):
        paid = Collection.objects.create(title='Top', slug='top')
        only_free = Collection.objects.create(title='Free games', slug='free-games')
        Collection.objects.create(title='Empty', slug='empty')
        self.game2.collections.add(paid)
        Game.objects.create(author=self.other, title='Free', price=0).collections.add(only_free)

        def values(url):
            return [o['value'] for o in self.client.get(url).context['category_options']]

        menu = values(reverse('mfs:catalog'))
        self.assertIn('top', menu)
        self.assertIn('free', menu)
        self.assertIn('sale', menu)
        self.assertNotIn('free-games', menu)
        self.assertNotIn('empty', menu)
        # Со страницы магазина ссылка «Смотреть все» открывает и такую подборку
        self.assertIn('free-games', values(reverse('mfs:catalog') + '?category=free-games'))

    def test_shop_page_has_no_genre_filters(self):
        genre = Genre.objects.create(name='RPG', slug='rpg')
        collection = Collection.objects.create(title='Top', slug='top')
        self.game.collections.add(collection)
        self.game2.collections.add(collection)
        self.game2.genres.add(genre)

        response = self.client.get(reverse('mfs:index') + '?genre=rpg')
        self.assertNotContains(response, 'categories-filter')
        self.assertEqual(len(response.context['collections'][0].game_products.all()), 2)

    def test_home_query_count_does_not_grow_with_games(self):
        collection = Collection.objects.create(title='Top', slug='top')
        genre = Genre.objects.create(name='RPG', slug='rpg')
        self.game.collections.add(collection)
        self.game.genres.add(genre)

        with self.assertNumQueries(6):
            self.client.get(reverse('mfs:index'))

        for i in range(5):
            game = Game.objects.create(author=self.other, title=f'G{i}', price=1)
            game.collections.add(collection)
            game.genres.add(genre)

        with self.assertNumQueries(6):
            self.client.get(reverse('mfs:index'))

    def test_admin_flag_chooses_game_of_the_week(self):
        Game.objects.filter(pk=self.game2.pk).update(is_game_of_the_week=True)
        self.assertEqual(self.client.get(reverse('mfs:index')).context['featured_game'], self.game2)

    def test_search_returns_discounted_price(self):
        game = self.client.get(reverse('mfs:game_search_ajax') + '?q=alp').json()['games'][0]
        self.assertEqual((game['price'], game['old_price']), (50, 100))


class ProfileAndSettingsTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def post_settings(self, **data):
        return self.client.post(reverse('mfs:settings'), data)

    def test_rejects_taken_and_unsafe_usernames(self):
        for username in ('BOB', '<img src=x onerror=alert(1)>', 'a/b', '', 'x' * 25):
            response = self.post_settings(form='profile', username=username)
            self.assertEqual(response.status_code, 400, username)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'alice')

    def test_rejects_bad_email_and_saves_valid_data(self):
        self.assertEqual(self.post_settings(form='profile', username='alice', email='nope').status_code, 400)
        self.assertEqual(self.post_settings(form='profile', username='alice2', email='a@b.co', bio='hi').status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual((self.user.username, self.user.email, self.user.profile.bio), ('alice2', 'a@b.co', 'hi'))

    def test_rejects_fake_image_and_accepts_real_one(self):
        fake = SimpleUploadedFile('evil.png', b'<script>alert(1)</script>', content_type='image/png')
        self.assertEqual(self.post_settings(form='profile', username='alice', avatar=fake).status_code, 400)
        self.assertFalse(self.user.profile.avatar)

        self.assertEqual(self.post_settings(form='profile', username='alice', avatar=make_png()).status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.avatar)

    def test_accent_color_must_be_hex(self):
        self.post_settings(form='appearance', accent_color='red;}body{display:none')
        self.assertEqual(Profile.objects.get(user=self.user).accent_color, '#6865f2')
        self.post_settings(form='appearance', accent_color='#10b981')
        self.assertEqual(Profile.objects.get(user=self.user).accent_color, '#10b981')

    def test_password_validators_apply(self):
        response = self.post_settings(
            form='password', old_password='Str0ng-pass-123', new_password='12345678', confirm_password='12345678'
        )
        self.assertEqual(response.status_code, 400)

    def test_privacy_settings(self):
        target = self.other.profile
        url = reverse('mfs:user_profile', args=['bob'])

        self.assertIs(self.client.get(url).context['show_library'], True)

        target.show_library = False
        target.save()
        self.assertIs(self.client.get(url).context['show_library'], False)

        target.profile_visibility = 'friends'
        target.save()
        self.assertTrue(self.client.get(url).context['restricted'])

        Friendship.objects.create(sender=self.user.profile, receiver=target, status=Friendship.Status.ACCEPTED)
        self.assertNotIn('restricted', self.client.get(url).context)

    def test_private_profile_hidden_from_search_and_requests(self):
        search = reverse('mfs:friends_search') + '?q=bo'
        self.assertEqual(len(self.client.get(search).json()['users']), 1)

        Profile.objects.filter(user=self.other).update(profile_visibility='private')
        self.assertEqual(self.client.get(search).json()['users'], [])
        response = self.client.post(reverse('mfs:friend_request'), {'username': 'bob'})
        self.assertEqual(response.status_code, 400)

    def test_own_profile_shows_real_stats(self):
        UserLibrary.objects.create(user=self.user, game=self.game, playtime_hours=7)
        response = self.client.get(reverse('mfs:profile'))
        self.assertEqual((response.context['games_count'], response.context['total_hours']), (1, 7))


class PrivacyTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.game.owners.add(self.other)
        UserLibrary.objects.create(user=self.other, game=self.game, last_played=timezone.now())
        FavoriteGame.objects.create(user=self.other, game=self.game)
        self.url = reverse('mfs:user_profile', args=['bob'])
        Profile.objects.filter(user=self.other).update(profile_visibility='private', show_library=True)

    def assert_library_hidden(self):
        response = self.client.get(self.url)
        self.assertTrue(response.context['restricted'])
        self.assertNotContains(response, 'Alpha')
        self.assertNotContains(response, 'Недавняя активность')

    def test_private_profile_hides_library_even_if_it_is_allowed(self):
        self.client.force_login(self.user)
        self.assert_library_hidden()

    def test_private_profile_hides_library_from_friends_and_staff(self):
        Friendship.objects.create(
            sender=self.user.profile, receiver=self.other.profile, status=Friendship.Status.ACCEPTED
        )
        self.client.force_login(self.user)
        self.assert_library_hidden()

        self.client.force_login(User.objects.create_superuser('root', password='Str0ng-pass-123'))
        self.assert_library_hidden()

    def test_owner_still_sees_own_private_profile(self):
        self.client.force_login(self.other)
        self.assertContains(self.client.get(self.url), 'Alpha')

    def test_hidden_library_also_hides_favorites_wishlist_and_counters(self):
        Profile.objects.filter(user=self.other).update(profile_visibility='everyone', show_library=False)
        wishlist = Wishlist.objects.create(user=self.other)
        wishlist.games.add(self.game2)

        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertNotContains(response, 'Alpha')
        self.assertNotContains(response, 'Beta')
        self.assertNotContains(response, 'Часов')

    def test_private_mode_keeps_library_choice_for_later(self):
        self.client.force_login(self.other)
        self.client.post(reverse('mfs:settings'), {'form': 'privacy', 'profile_visibility': 'private'})
        self.assertTrue(Profile.objects.get(user=self.other).show_library)


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


class NewsTests(StoreTestCase):
    def test_drafts_are_visible_only_to_staff(self):
        draft = News.objects.create(title='Draft', description='x', is_published=False)
        self.assertNotContains(self.client.get(reverse('mfs:news')), 'Draft')
        self.assertEqual(self.client.get(draft.get_absolute_url()).status_code, 404)

        self.client.force_login(User.objects.create_superuser('root', password='Str0ng-pass-123'))
        self.assertContains(self.client.get(draft.get_absolute_url()), 'Черновик')

    def test_pinned_news_go_first(self):
        News.objects.create(title='Old pinned', description='x', is_pinned=True)
        News.objects.create(title='New regular', description='x')
        response = self.client.get(reverse('mfs:news'))
        self.assertEqual([n.title for n in response.context['page']], ['Old pinned', 'New regular'])

    def test_filters_search_and_pagination(self):
        News.objects.create(title='Большое Обновление', description='x', category='tech')
        for i in range(9):
            News.objects.create(title=f'N{i}', description='x')

        def titles(query):
            return [n.title for n in self.client.get(reverse('mfs:news') + query).context['page']]

        self.assertEqual(titles('?category=tech'), ['Большое Обновление'])
        # Регистр кириллицы не важен
        self.assertEqual(titles('?q=обновление'), ['Большое Обновление'])
        self.assertEqual(len(titles('')), 8)
        self.assertEqual(len(titles('?page=2')), 2)
        self.assertEqual(len(titles('?category=unknown')), 8)

    def test_format_escapes_html_and_keeps_markup(self):
        html = news_format('**Важно** <script>alert(1)</script>\n\n- пункт\n\nhttps://example.com/a')
        self.assertIn('<strong>Важно</strong>', html)
        self.assertNotIn('<script>', html)
        self.assertIn('<li>пункт</li>', html)
        self.assertIn('href="https://example.com/a"', html)
        self.assertIn('<li>старый маркер</li>', news_format('• старый маркер'))
        self.assertEqual(news_plain('**Важно**\n- пункт'), 'Важно пункт')

    def test_detail_links_to_neighbours(self):
        first = News.objects.create(title='First', description='x')
        second = News.objects.create(title='Second', description='x')
        response = self.client.get(first.get_absolute_url())
        self.assertEqual(response.context['newer'], second)
        self.assertIsNone(response.context['older'])


class PagesTests(StoreTestCase):
    def test_cart_shows_exclusive_and_discount_badges_together(self):
        Game.objects.filter(pk=self.game.pk).update(is_not_on_steam=True)
        self.client.force_login(self.user)
        self.ajax_add(self.game)

        response = self.client.get(reverse('mfs:cart_detail'))
        self.assertContains(response, 'cart-badges')
        self.assertContains(response, '<span class="exclusive">Эксклюзив</span>')
        self.assertContains(response, '-50%')

    def test_cart_count_agrees_with_number(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('mfs:cart_detail')), '0 товаров')
        self.ajax_add(self.game)
        self.assertContains(self.client.get(reverse('mfs:cart_detail')), '1 товар\n')
        self.ajax_add(self.game2)
        self.assertContains(self.client.get(reverse('mfs:cart_detail')), '2 товара')

    def test_public_pages_render(self):
        News.objects.create(title='N', description='D')
        for name, args in (('index', []), ('catalog', []), ('news', []), ('cart_detail', []), ('login', []),
                           ('register', []), ('game_detail', [self.game.pk])):
            self.assertEqual(self.client.get(reverse(f'mfs:{name}', args=args)).status_code, 200, name)

    def test_bad_news_month_is_ignored(self):
        News.objects.create(title='N', description='D')
        for month in ('99999-1', '0001-01', 'abc', '2026'):
            response = self.client.get(reverse('mfs:news') + f'?month={month}')
            self.assertEqual(response.status_code, 200, month)
            self.assertEqual(len(response.context['page']), 1, month)

    def test_review_shows_author_status(self):
        admin = User.objects.create_superuser('root', password='Str0ng-pass-123')
        staff = User.objects.create_user('mod', password='Str0ng-pass-123', is_staff=True)
        for user in (admin, staff, self.user):
            Review.objects.create(user=user, game=self.game, rating=5)

        response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        for status in ('Создатель', 'Админ', 'Пользователь'):
            self.assertContains(response, f'{status}</span>')

    def test_message_is_displayed(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('mfs:review_submit', args=[self.game.pk]), {'rating': '9'}, follow=True)
        self.assertContains(response, 'message-toast')
