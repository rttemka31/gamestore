"""Общая подготовка для тестов магазина."""
import io
import shutil
import tempfile
from decimal import Decimal

from PIL import Image
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from ..models import Game


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
        cache.clear()  # счётчики попыток входа и регистрации не должны переходить из теста в тест
        self.user = User.objects.create_user('alice', password='Str0ng-pass-123')
        self.other = User.objects.create_user('bob', password='Str0ng-pass-123')
        self.game = Game.objects.create(author=self.other, title='Alpha', price=Decimal('100'), discount=50)
        self.game2 = Game.objects.create(author=self.other, title='Beta', price=Decimal('300'))

    def ajax_add(self, game):
        return self.client.post(
            reverse('mfs:add_to_cart', args=[game.pk]), headers={'x-requested-with': 'XMLHttpRequest'}
        )
