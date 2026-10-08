import os
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.db.models.signals import pre_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.models import AbstractUser

# 1. ЖАНРЫ И ПОДБОРКИ
class Genre(models.Model):
    name = models.CharField(max_length=100, verbose_name="Название жанра")
    slug = models.SlugField(unique=True, verbose_name="URL-слаг")

    class Meta:
        verbose_name = "Жанр"
        verbose_name_plural = "Жанры"

    def __str__(self):
        return self.name


class Collection(models.Model):
    title = models.CharField(max_length=100, verbose_name="Название подборки")
    slug = models.SlugField(unique=True, verbose_name="URL-слаг")

    class Meta:
        verbose_name = "Подборка"
        verbose_name_plural = "Подборки"

    def __str__(self):
        return self.title


# 2. ИГРЫ И МЕДИА
class BaseMediaProduct(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=200, verbose_name="Название")
    description = models.TextField(verbose_name="Описание", blank=True)
    long_description = models.TextField(verbose_name="Детальное описание", blank=True)
    icon = models.ImageField(upload_to='icons/', verbose_name="Иконка", blank=True, null=True)
    cover = models.ImageField(upload_to='covers/', verbose_name="Обложка", blank=True, null=True)
    cover_hd = models.ImageField(upload_to='covers_hd/', verbose_name="HD Обложка", blank=True, null=True)
    trailer_file = models.FileField(upload_to='trailers/', blank=True, null=True, verbose_name="Файл трейлера")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Цена")
    discount = models.IntegerField(default=0, verbose_name="Скидка (%)")
    release_date = models.DateField(verbose_name="Дата выхода", default=timezone.now)

    @property
    def discounted_price(self):
        if self.discount > 0:
            multiplier = Decimal(1) - (Decimal(self.discount) / Decimal(100))
            return (self.price * multiplier).quantize(Decimal('0.01'))
        return self.price

    class Meta:
        abstract = True

    def __str__(self):
        return self.title


class Game(BaseMediaProduct):
    genres = models.ManyToManyField(Genre, related_name='games', verbose_name="Жанры", blank=True)
    collections = models.ManyToManyField(Collection, related_name='game_products', verbose_name="Подборки", blank=True)
    is_game_of_the_week = models.BooleanField(default=False, verbose_name="Игра недели")
    is_not_on_steam = models.BooleanField(default=False, verbose_name="Нет в Steam")
    
    # ИСПРАВЛЕНО: Заменено User на settings.AUTH_USER_MODEL
    owners = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='purchased_games', blank=True)

    class Meta:
        verbose_name = "Игра"
        verbose_name_plural = "Игры"

    @property
    def get_icon_url(self):
        if self.icon and hasattr(self.icon, 'url'):
            return self.icon.url
        return '/media/default_icon.png'

    @property
    def get_cover_url(self):
        if self.cover_hd:
            return self.cover_hd.url
        elif self.cover:
            return self.cover.url
        return None


class Screenshot(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='screenshots')
    image = models.ImageField(upload_to='screenshots/', max_length=250)

    def __str__(self):
        return f"Скриншот для {self.game.title}"


class Dlc(BaseMediaProduct):
    class Meta:
        verbose_name = "DLC"
        verbose_name_plural = "DLC"


# 3. ПРОФИЛЬ И СИГНАЛЫ
class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    nickname = models.CharField(max_length=30)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    avatar_color = models.CharField(max_length=7, default='#2a2a2a')
    bio = models.TextField(max_length=150, blank=True, null=True, verbose_name="О себе") # <-- bio здесь
    birth_date = models.DateField(blank=True, null=True)

    banner = models.ImageField(upload_to='banners/', blank=True, null=True)
    accent_color = models.CharField(max_length=7, default='#6865f2')
    disable_blur = models.BooleanField(default=False)
    hide_stats = models.BooleanField(default=False)

    def __str__(self):
        return f'Профиль {self.user.username}'


@receiver(pre_save, sender=Profile)
def delete_old_avatar_on_change(sender, instance, **kwargs):
    if not instance.pk:
        return

    try:
        old_profile = Profile.objects.get(pk=instance.pk)
    except Profile.DoesNotExist:
        return

    if old_profile.avatar and old_profile.avatar != instance.avatar:
        if os.path.isfile(old_profile.avatar.path):
            os.remove(old_profile.avatar.path)


@receiver(post_delete, sender=Profile)
def delete_avatar_on_profile_delete(sender, instance, **kwargs):
    if instance.avatar and os.path.isfile(instance.avatar.path):
        os.remove(instance.avatar.path)


# 4. ВЗАИМОДЕЙСТВИЯ ПОЛЬЗОВАТЕЛЕЙ
class Friendship(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает'
        ACCEPTED = 'accepted', 'Принято'
        REJECTED = 'rejected', 'Отклонено'

    sender = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='sent_friend_requests')
    receiver = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='received_friend_requests')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['sender', 'receiver'], name='unique_friend_request'),
        ]

    def __str__(self):
        return f'{self.sender} → {self.receiver} ({self.status})'


class Review(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='reviews')
    text = models.TextField(max_length=150)
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    created_at = models.DateTimeField(auto_now_add=True)


class Wishlist(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    games = models.ManyToManyField(Game, blank=True)


class Cart(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    games = models.ManyToManyField(Game, blank=True)


class ProfileComment(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='comments')
    text = models.TextField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)


class Message(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages')
    receiver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_messages')
    text = models.TextField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)


# 5. НОВОСТИ И БИБЛИОТЕКА
class News(models.Model):
    CATEGORY_CHOICES = [
        ('update', '↻ Обновление'),
        ('announcement', '⮂ Фикс'),
        ('tech', '⮃ Тех. работы'),
    ]

    title = models.CharField(max_length=200, verbose_name="Заголовок")
    description = models.TextField(verbose_name="Описание")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата публикации")
    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        default='update',
        verbose_name="Тип публикации"
    )

    class Meta:
        verbose_name = "Новость"
        verbose_name_plural = "Новости"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class UserLibrary(models.Model):
    # ИСПРАВЛЕНО: Заменено User на settings.AUTH_USER_MODEL
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='library')
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    purchased_at = models.DateTimeField(auto_now_add=True)
    last_played = models.DateTimeField(null=True, blank=True)
    playtime_hours = models.PositiveIntegerField(default=0, verbose_name="Сыграно часов")

    class Meta:
        verbose_name = 'Игра пользователя'
        verbose_name_plural = 'Библиотека пользователей'

    def __str__(self):
        return f"{self.user.username} — {self.game.title}"