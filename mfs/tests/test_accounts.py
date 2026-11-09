"""Вход, профиль, настройки и приватность."""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from ..models import FavoriteGame, Friendship, Genre, News, Profile, Review, UserLibrary, Wishlist
from .base import make_png, StoreTestCase


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

    def test_reduce_motion_is_saved_and_applied_to_pages(self):
        self.assertNotContains(self.client.get(reverse('mfs:index')), 'data-motion')
        self.post_settings(form='appearance', reduce_motion='on')
        self.assertContains(self.client.get(reverse('mfs:index')), 'data-motion="reduced"')

    def test_catalog_uses_saved_sort_unless_url_overrides_it(self):
        self.post_settings(form='catalog', default_catalog_sort='title')
        url = reverse('mfs:catalog')
        self.assertEqual(self.client.get(url).context['sort'], 'title')
        self.assertEqual(self.client.get(url, {'sort': 'discount'}).context['sort'], 'discount')

        self.post_settings(form='catalog', default_catalog_sort='<script>')
        self.assertEqual(Profile.objects.get(user=self.user).default_catalog_sort, 'title')

    def test_catalog_can_hide_owned_games_and_counts_follow(self):
        genre = Genre.objects.create(name='Экшен', slug='action')
        self.game.genres.add(genre)
        self.game2.genres.add(genre)
        self.game.owners.add(self.user)
        url = reverse('mfs:catalog')

        self.assertEqual(self.client.get(url).context['page'].paginator.count, 2)

        self.post_settings(form='catalog', default_catalog_sort='new', hide_owned_in_catalog='on')
        response = self.client.get(url)
        self.assertEqual([g.title for g in response.context['page']], ['Beta'])
        self.assertEqual(response.context['category_options'][0]['count'], 1)
        self.assertEqual(response.context['genres'].get().games_count, 1)
        self.assertContains(response, 'Купленные игры скрыты')

    def test_wishlist_can_be_hidden_separately_from_library(self):
        Wishlist.objects.create(user=self.other).games.add(self.game)
        url = reverse('mfs:user_profile', args=['bob'])
        self.assertEqual(len(self.client.get(url).context['wishlist_games']), 1)

        Profile.objects.filter(user=self.other).update(show_wishlist=False)
        response = self.client.get(url)
        self.assertEqual(len(response.context['wishlist_games']), 0)
        self.assertIs(response.context['show_library'], True)

    def test_closed_friend_requests_still_allow_answering_theirs(self):
        Profile.objects.filter(user=self.other).update(allow_friend_requests=False)
        request_url = reverse('mfs:friend_request')

        self.assertEqual(self.client.post(request_url, {'username': 'bob'}).status_code, 400)
        self.assertFalse(Friendship.objects.exists())
        search = self.client.get(reverse('mfs:friends_search') + '?q=bo').json()
        self.assertEqual(search['users'][0]['state'], 'closed')
        self.assertContains(self.client.get(reverse('mfs:user_profile', args=['bob'])), 'Не принимает заявки')

        Friendship.objects.create(sender=self.other.profile, receiver=self.user.profile)
        self.assertEqual(self.client.post(request_url, {'username': 'bob'}).status_code, 200)
        self.assertEqual(Friendship.objects.get().status, Friendship.Status.ACCEPTED)

    def test_private_mode_keeps_new_privacy_choices(self):
        self.post_settings(form='privacy', profile_visibility='private')
        profile = Profile.objects.get(user=self.user)
        self.assertTrue(profile.show_wishlist)
        self.assertTrue(profile.allow_friend_requests)

    def test_logout_others_ends_only_my_other_sessions(self):
        mine = Client()
        mine.force_login(self.user)
        theirs = Client()
        theirs.force_login(self.other)

        response = self.post_settings(form='logout_others')
        self.assertIn('1', response.json()['message'])

        self.assertEqual(mine.get(reverse('mfs:profile')).status_code, 302)
        self.assertEqual(self.client.get(reverse('mfs:profile')).status_code, 200)
        self.assertEqual(theirs.get(reverse('mfs:profile')).status_code, 200)

    def test_settings_lists_devices_and_ends_one_session(self):
        phone = Client(HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36')
        phone.post(reverse('mfs:login'), {'username': 'alice', 'password': 'Str0ng-pass-123'})
        phone.get(reverse('mfs:profile'))

        devices = self.client.get(reverse('mfs:settings')).context['devices']
        self.assertEqual(len(devices), 2)
        self.assertTrue(devices[0]['current'])
        other = devices[1]
        self.assertEqual((other['name'], other['is_mobile']), ('Chrome · Android', True))
        self.assertIsNotNone(other['started'])
        # Ключ сессии в страницу не попадает — только его хеш
        self.assertNotIn(phone.session.session_key, self.client.get(reverse('mfs:settings')).content.decode())

        self.assertEqual(self.post_settings(form='logout_device', device=other['id']).status_code, 200)
        self.assertEqual(phone.get(reverse('mfs:profile')).status_code, 302)
        self.assertEqual(self.post_settings(form='logout_device', device=other['id']).status_code, 404)
        # Свой текущий сеанс так не завершить
        self.post_settings(form='logout_device', device=devices[0]['id'])
        self.assertEqual(self.client.get(reverse('mfs:profile')).status_code, 200)

    def test_old_sessions_without_device_are_grouped(self):
        from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
        from django.contrib.sessions.backends.db import SessionStore
        for _ in range(3):
            old = SessionStore()
            old.update({SESSION_KEY: str(self.user.pk), BACKEND_SESSION_KEY: 'mfs.security.RateLimitedModelBackend',
                        HASH_SESSION_KEY: self.user.get_session_auth_hash()})
            old.create()

        devices = self.client.get(reverse('mfs:settings')).context['devices']
        self.assertEqual([d.get('legacy_count') for d in devices], [None, 3])
        self.assertEqual(self.post_settings(form='logout_device', device='legacy').status_code, 200)
        self.assertEqual(len(self.client.get(reverse('mfs:settings')).context['devices']), 1)

    def test_user_agent_names(self):
        from ..sessions import describe_user_agent
        self.assertEqual(describe_user_agent('Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Safari/537.36 Edg/130.0')[0], 'Edge · Windows')
        self.assertEqual(describe_user_agent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Version/17.0 Mobile Safari/604.1'), ('Safari · iPhone', True))
        self.assertEqual(describe_user_agent('Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Firefox/131.0')[0], 'Firefox · Linux')
        self.assertEqual(describe_user_agent('')[0], 'Неизвестное устройство')

    def test_export_contains_my_data_and_downloads_as_file(self):
        Profile.objects.filter(user=self.user).update(bio='hi')
        self.game.owners.add(self.user)
        UserLibrary.objects.create(user=self.user, game=self.game, playtime_seconds=3 * 60)
        Wishlist.objects.create(user=self.user).games.add(self.game2)
        Review.objects.create(user=self.user, game=self.game, rating=5, text='Отлично')
        Friendship.objects.create(sender=self.user.profile, receiver=self.other.profile, status=Friendship.Status.ACCEPTED)

        response = self.client.get(reverse('mfs:export_data'))
        data = response.json()

        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(data['account']['bio'], 'hi')
        self.assertEqual(data['library'][0]['playtime_minutes'], 3)
        self.assertEqual(data['wishlist'], ['Beta'])
        self.assertEqual(data['reviews'][0]['text'], 'Отлично')
        self.assertEqual(data['friends'], ['bob'])
        self.assertNotIn('password', response.content.decode())

    def test_about_section_shows_creators_stats_and_latest_version(self):
        News.objects.create(title='V1.1.0', description='Текст')
        newest = News.objects.create(title='v1.2.0 — большое обновление', description='Текст')
        News.objects.create(title='Обычная новость', description='Текст')
        News.objects.create(title='V9.9.9', description='Текст', is_published=False)

        response = self.client.get(reverse('mfs:settings'))
        self.assertEqual(response.context['site_version']['number'], '1.2.0')
        self.assertEqual(response.context['site_version']['url'], newest.get_absolute_url())
        self.assertEqual(response.context['site_stats'], {'games': 2, 'players': 2})
        self.assertContains(response, 'rttemka31')
        self.assertContains(response, 'Claude')
        self.assertContains(response, 'Версия 1.2.0')

    def test_about_section_works_without_version_news(self):
        response = self.client.get(reverse('mfs:settings'))
        self.assertIsNone(response.context['site_version'])
        self.assertContains(response, 'О сайте')
        self.assertNotContains(response, 'Версия ')

    def test_export_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('mfs:export_data')).status_code, 302)

    def test_own_profile_shows_real_stats(self):
        UserLibrary.objects.create(user=self.user, game=self.game, playtime_seconds=7 * 3600 + 59 * 60)
        response = self.client.get(reverse('mfs:profile'))
        self.assertEqual((response.context['games_count'], response.context['total_hours']), (1, 8.0))
        self.assertContains(response, '<strong>8</strong>')

    def test_profile_hours_have_tenths(self):
        UserLibrary.objects.create(user=self.user, game=self.game, playtime_seconds=12 * 3600 + 36 * 60)
        self.assertContains(self.client.get(reverse('mfs:profile')), '<strong>12,6</strong>')


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
