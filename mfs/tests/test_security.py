"""Защита аккаунтов: хеширование паролей, блокировка подбора, ограничения регистрации,
страницы allauth, почта и разрешённые адреса сайта."""
from allauth.account.models import EmailAddress
from allauth.socialaccount.adapter import get_adapter as get_social_adapter
from allauth.socialaccount.models import SocialApp
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, RequestFactory, override_settings
from django.urls import resolve, reverse

from ..security import MAX_FAILURES_PER_ACCOUNT, MAX_FAILURES_PER_IP, MAX_REGISTRATIONS_PER_IP, client_ip
from .base import StoreTestCase

PASSWORD = 'Str0ng-pass-123'


class PasswordHashingTests(StoreTestCase):
    def test_new_passwords_are_hashed_with_scrypt(self):
        self.assertTrue(self.user.password.startswith('scrypt$'))
        self.assertNotIn(PASSWORD, self.user.password)

    def test_old_pbkdf2_hash_is_upgraded_on_login(self):
        self.user.password = make_password(PASSWORD, hasher='pbkdf2_sha256')
        self.user.save()
        self.client.post(reverse('mfs:login'), {'username': 'alice', 'password': PASSWORD})
        self.user.refresh_from_db()
        self.assertTrue(self.user.password.startswith('scrypt$'))


class LoginLockoutTests(StoreTestCase):
    def fail(self, username='alice', **extra):
        return self.client.post(reverse('mfs:login'), {'username': username, 'password': 'wrong-pass'}, **extra)

    def login(self, username='alice', client=None, **extra):
        return (client or self.client).post(reverse('mfs:login'), {'username': username, 'password': PASSWORD}, **extra)

    def test_account_is_locked_after_repeated_failures(self):
        for _ in range(MAX_FAILURES_PER_ACCOUNT):
            self.fail()
        response = self.login()
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertContains(response, 'Слишком много неудачных попыток')

    def test_lock_is_per_address_and_per_account(self):
        for _ in range(MAX_FAILURES_PER_ACCOUNT):
            self.fail()
        # тот же аккаунт с другого адреса и другой аккаунт с того же адреса входят как обычно
        other_ip = Client()
        self.login(client=other_ip, REMOTE_ADDR='10.0.0.9')
        self.assertIn('_auth_user_id', other_ip.session)
        self.login('bob')
        self.assertIn('_auth_user_id', self.client.session)

    def test_successful_login_resets_the_counter(self):
        for _ in range(MAX_FAILURES_PER_ACCOUNT - 1):
            self.fail()
        self.login()
        self.client.post(reverse('mfs:logout'))
        for _ in range(MAX_FAILURES_PER_ACCOUNT - 1):
            self.fail()
        self.login()
        self.assertIn('_auth_user_id', self.client.session)

    def test_address_is_locked_after_guessing_many_accounts(self):
        for i in range(MAX_FAILURES_PER_IP):
            self.fail(f'user{i}')
        self.login('bob')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_admin_login_is_protected_too(self):
        User.objects.filter(pk=self.user.pk).update(is_staff=True, is_superuser=True)
        url = reverse('admin:login')
        for _ in range(MAX_FAILURES_PER_ACCOUNT):
            self.client.post(url, {'username': 'alice', 'password': 'wrong-pass'})
        self.client.post(url, {'username': 'alice', 'password': PASSWORD})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_cloudflare_address_is_trusted_only_behind_proxy(self):
        request = RequestFactory().get('/', REMOTE_ADDR='127.0.0.1', HTTP_CF_CONNECTING_IP='203.0.113.5')
        self.assertEqual(client_ip(request), '127.0.0.1')
        with override_settings(SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https')):
            self.assertEqual(client_ip(request), '203.0.113.5')


class RegistrationProtectionTests(StoreTestCase):
    def register(self, username):
        client = Client()
        response = client.post(reverse('mfs:register'), {'username': username, 'password1': PASSWORD, 'password2': PASSWORD})
        return client, response

    def test_registrations_per_address_are_limited(self):
        for i in range(MAX_REGISTRATIONS_PER_IP):
            self.register(f'player{i}')
        client, response = self.register('one_more')
        self.assertFalse(User.objects.filter(username='one_more').exists())
        self.assertContains(response, 'слишком много аккаунтов')

    def test_long_and_case_duplicate_usernames_are_rejected(self):
        self.register('x' * 25)
        self.register('ALICE')
        self.assertFalse(User.objects.filter(username='x' * 25).exists())
        self.assertEqual(User.objects.filter(username__iexact='alice').count(), 1)

    def test_new_user_stays_logged_in(self):
        client, _ = self.register('newbie')
        self.assertEqual(client.get(reverse('mfs:profile')).status_code, 200)


class SettingsProtectionTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def change_password(self, old):
        return self.client.post(reverse('mfs:settings'), {
            'form': 'password', 'old_password': old, 'new_password': 'N3w-secure-pass', 'confirm_password': 'N3w-secure-pass',
        })

    def test_current_password_guessing_is_limited(self):
        for _ in range(MAX_FAILURES_PER_ACCOUNT):
            self.assertEqual(self.change_password('wrong-pass').status_code, 400)
        self.assertEqual(self.change_password(PASSWORD).status_code, 429)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_deleting_account_requires_password(self):
        self.client.post(reverse('mfs:settings'), {'form': 'delete_account', 'confirmation': 'wrong-pass'})
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.client.post(reverse('mfs:settings'), {'form': 'delete_account', 'confirmation': PASSWORD})
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_social_only_account_confirms_deletion_with_username(self):
        self.user.set_unusable_password()
        self.user.save()
        self.client.force_login(self.user)
        self.client.post(reverse('mfs:settings'), {'form': 'delete_account', 'confirmation': 'bob'})
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.client.post(reverse('mfs:settings'), {'form': 'delete_account', 'confirmation': 'alice'})
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())


class AuthorDeletionTests(StoreTestCase):
    def test_deleting_author_account_keeps_their_games(self):
        # bob — автор обеих игр, alice одну из них купила
        self.user.purchased_games.add(self.game)
        self.client.force_login(self.other)
        self.client.post(reverse('mfs:settings'), {'form': 'delete_account', 'confirmation': PASSWORD})
        self.assertFalse(User.objects.filter(pk=self.other.pk).exists())

        self.game.refresh_from_db()
        self.assertIsNone(self.game.author)
        self.assertTrue(self.user.purchased_games.filter(pk=self.game.pk).exists())
        self.assertContains(self.client.get(reverse('mfs:game_detail', args=[self.game.pk])), 'Не указан')


class AllauthPagesTests(StoreTestCase):
    """От allauth на сайте работает только вход через соцсети; его собственные страницы закрыты."""

    def test_builtin_pages_lead_to_site_pages(self):
        self.assertRedirects(self.client.get('/accounts/signup/'), reverse('mfs:register'))
        for page in ('', 'login/', 'password/reset/', 'email/'):
            self.assertRedirects(self.client.get(f'/accounts/{page}'), reverse('mfs:login'))
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get('/accounts/password/change/'), reverse('mfs:settings'))

    def test_signup_and_password_reset_cannot_be_posted(self):
        users = User.objects.count()
        self.client.post('/accounts/signup/', {
            'username': 'x' * 40, 'email': 'a@b.co', 'password1': PASSWORD, 'password2': PASSWORD,
        })
        self.assertEqual(User.objects.count(), users)
        self.assertRedirects(self.client.post('/accounts/password/reset/', {'email': 'a@b.co'}), reverse('mfs:login'))
        self.assertEqual(len(mail.outbox), 0)

    def test_social_login_addresses_still_belong_to_allauth(self):
        for path, name in (
            ('/accounts/google/login/', 'google_login'),
            ('/accounts/discord/login/callback/', 'discord_callback'),
            ('/accounts/3rdparty/signup/', 'socialaccount_signup'),
        ):
            self.assertEqual(resolve(path).url_name, name)


class EmailOwnershipTests(StoreTestCase):
    EMAIL = 'victim@gmail.com'

    def google_login(self):
        """Вход через Google с адресом EMAIL — таким, каким его видит allauth после ответа Google."""
        SocialApp.objects.create(provider='google', name='Google', client_id='id', secret='secret')
        request = RequestFactory().get('/accounts/google/login/callback/')
        provider = get_social_adapter().get_provider(request, 'google')
        return provider.sociallogin_from_response(request, {'sub': '1', 'email': self.EMAIL, 'email_verified': True})

    def test_email_typed_in_settings_does_not_capture_social_login(self):
        # Чужой адрес, вписанный в свой профиль, не должен приводить его владельца в этот аккаунт
        self.user.email = self.EMAIL
        self.user.save()
        self.assertIsNone(get_social_adapter().authenticate_by_email(self.google_login()))

    def test_verified_email_still_links_social_login(self):
        EmailAddress.objects.create(user=self.other, email=self.EMAIL, verified=True, primary=True)
        user, email = get_social_adapter().authenticate_by_email(self.google_login())
        self.assertEqual((user, email), (self.other, self.EMAIL))

    def test_email_of_another_account_is_rejected(self):
        self.other.email = self.EMAIL
        self.other.save()
        EmailAddress.objects.create(user=self.other, email='social@gmail.com', verified=True, primary=True)

        self.client.force_login(self.user)
        for email in (self.EMAIL, 'VICTIM@gmail.com', 'social@gmail.com'):
            response = self.client.post(reverse('mfs:settings'), {'form': 'profile', 'username': 'alice', 'email': email})
            self.assertEqual(response.status_code, 400)
            self.assertIn('уже используется', response.json()['message'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')

        # Свою почту владелец сохраняет как раньше
        self.client.force_login(self.other)
        response = self.client.post(reverse('mfs:settings'), {'form': 'profile', 'username': 'bob', 'email': self.EMAIL})
        self.assertEqual(response.status_code, 200)


class AllowedHostsTests(StoreTestCase):
    def test_unknown_host_is_rejected(self):
        self.assertEqual(self.client.get(reverse('mfs:index'), headers={'host': 'evil.example'}).status_code, 400)
