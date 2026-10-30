import io
import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Collection, Friendship, Game, Genre, News, Profile, Review, UserLibrary

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


class PagesTests(StoreTestCase):
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
            self.assertEqual(len(response.context['news_list']), 1, month)

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
