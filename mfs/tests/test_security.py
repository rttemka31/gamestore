"""Защита аккаунтов: хеширование паролей, блокировка подбора, ограничения регистрации."""
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

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
