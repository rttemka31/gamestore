from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.urls import reverse
from django.utils import timezone

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
class SensitiveContent(models.TextChoices):
    """Пометка скриншота или трейлера, который может быть неприятен: на сайте он размыт,
    пока посетитель сам не нажмёт «Показать»."""
    NONE = '', 'Нет'
    VIOLENCE = 'violence', 'Жестокость'
    NUDITY = 'nudity', 'Нагота'


class BaseMediaProduct(models.Model):
    # SET_NULL, а не CASCADE: удаление аккаунта автора не должно стирать игру из магазина
    # и из библиотек всех, кто её купил
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Автор",
    )
    # Длины ограничены, чтобы название и описание помещались в карточки и страницы игры
    title = models.CharField(max_length=60, verbose_name="Название", help_text="До 60 символов.")
    description = models.TextField(
        max_length=300, verbose_name="Описание", blank=True,
        help_text="Короткое описание для страницы игры и игры недели, до 300 символов.",
    )
    long_description = models.TextField(
        max_length=5000, verbose_name="Детальное описание", blank=True, help_text="До 5000 символов.",
    )
    icon = models.ImageField(upload_to='icons/', verbose_name="Иконка", blank=True, null=True)
    cover = models.ImageField(upload_to='covers/', verbose_name="Обложка", blank=True, null=True)
    cover_hd = models.ImageField(upload_to='covers_hd/', verbose_name="HD Обложка", blank=True, null=True)
    trailer_file = models.FileField(upload_to='trailers/', blank=True, null=True, verbose_name="Файл трейлера")
    trailer_sensitive = models.CharField(
        max_length=10, choices=SensitiveContent.choices, default=SensitiveContent.NONE, blank=True,
        verbose_name="Неприятный контент в трейлере",
        help_text="Трейлер будет размыт, пока посетитель сам не нажмёт «Показать».",
    )
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Цена")
    discount = models.IntegerField(default=0, verbose_name="Скидка (%)")
    discount_until = models.DateTimeField(
        null=True, blank=True, verbose_name="Скидка до",
        help_text="Пусто — скидка без срока. Когда срок пройдёт, скидка снимется сама.",
    )
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
    class AgeRating(models.TextChoices):
        NONE = '', 'Не указан'
        AGE_0 = '0+', '0+'
        AGE_3 = '3+', '3+'
        AGE_7 = '7+', '7+'
        AGE_12 = '12+', '12+'
        AGE_16 = '16+', '16+'
        AGE_18 = '18+', '18+'

    genres = models.ManyToManyField(Genre, related_name='games', verbose_name="Жанры", blank=True)
    # Показывается справа от названия на странице игры
    age_rating = models.CharField(
        max_length=3, choices=AgeRating.choices, default=AgeRating.NONE, blank=True,
        verbose_name="Возрастной рейтинг",
    )
    collections = models.ManyToManyField(Collection, related_name='game_products', verbose_name="Подборки", blank=True)
    is_game_of_the_week = models.BooleanField(default=False, verbose_name="Игра недели")
    is_not_on_steam = models.BooleanField(default=False, verbose_name="Нет в Steam")
    size_gb = models.DecimalField(
        max_digits=6, decimal_places=1, blank=True, null=True,
        validators=[MinValueValidator(Decimal('0.1'))],
        verbose_name="Размер игры (ГБ)",
    )

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
    sensitive = models.CharField(
        max_length=10, choices=SensitiveContent.choices, default=SensitiveContent.NONE, blank=True,
        verbose_name="Неприятный контент",
    )

    def __str__(self):
        return f"Скриншот для {self.game.title}"


class Dlc(BaseMediaProduct):
    class Meta:
        verbose_name = "DLC"
        verbose_name_plural = "DLC"


def expire_discounts(now=None):
    """Снимает скидки, у которых прошёл срок «Скидка до». Обновляет базу, а не только показ:
    сортировка и фильтр по цене в каталоге считают цену запросом по полю discount."""
    now = now or timezone.now()
    for model in (Game, Dlc):
        model.objects.filter(discount_until__lte=now).update(discount=0, discount_until=None)


class DiscountExpiryMiddleware:
    """Проверяет сроки скидок не чаще раза в минуту, чтобы не тратить запрос на каждую страницу."""
    CACHE_KEY = 'discounts-checked'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.core.cache import cache
        if cache.add(self.CACHE_KEY, True, 60):
            expire_discounts()
        return self.get_response(request)


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

    font_size = models.PositiveSmallIntegerField(default=1)    # 0 мелкий, 1 средний, 2 крупный
    radius_size = models.PositiveSmallIntegerField(default=1)  # 0 острые, 1 средние, 2 круглые
    reduce_motion = models.BooleanField(default=False)
    show_hints = models.BooleanField(default=True)  # значки «?» с пояснениями на сайте

    class Design(models.TextChoices):
        DEFAULT = 'default', 'Обычный'
        GLASS = 'glass', 'Liquid Glass'

    # Дизайн сайта: обычный или «стеклянный» (демо). Включается атрибутом data-design на <html>
    design = models.CharField(max_length=10, choices=Design.choices, default=Design.DEFAULT)

    hide_owned_in_catalog = models.BooleanField(default=False)
    default_catalog_sort = models.CharField(max_length=20, default='new')

    class GenreSort(models.TextChoices):
        POPULAR = 'popular', 'По популярности'
        NAME = 'name', 'По алфавиту'

    # Порядок жанров в фильтре каталога: сначала жанры с большим числом игр или по алфавиту
    genre_sort = models.CharField(max_length=10, choices=GenreSort.choices, default=GenreSort.POPULAR)

    class Visibility(models.TextChoices):
        EVERYONE = 'everyone', 'Все'
        FRIENDS = 'friends', 'Только друзья'
        PRIVATE = 'private', 'Только я'

    profile_visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.EVERYONE)
    show_library = models.BooleanField(default=True)
    show_wishlist = models.BooleanField(default=True)
    allow_friend_requests = models.BooleanField(default=True)

    def __str__(self):
        return f'Профиль {self.user.username}'


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
    text = models.TextField(max_length=150, blank=True)
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Время в игре на момент отзыва (или его правки); пусто у отзывов, написанных до появления поля
    playtime_seconds = models.PositiveIntegerField(null=True, blank=True, verbose_name="Время в игре на момент отзыва")

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'game'], name='one_review_per_user_game'),
        ]

    def __str__(self):
        return f'{self.user} → {self.game} ({self.rating}★)'


class ReviewVote(models.Model):
    """Отметка «Полезно» на чужом отзыве."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='review_votes')
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name='votes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'review'], name='one_vote_per_user_review'),
        ]


class Wishlist(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    games = models.ManyToManyField(Game, blank=True)


class FavoriteGame(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='favorite_games')
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'Избранная игра'
        verbose_name_plural = 'Избранные игры'
        ordering = ['position', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['user', 'game'], name='unique_favorite_game'),
        ]

    def __str__(self):
        return f'{self.user} ★ {self.game}'


class Cart(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    games = models.ManyToManyField(Game, blank=True)


class ProfileComment(models.Model):
    """Запись на стене профиля. Писать могут владелец и его друзья."""
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='comments')
    text = models.TextField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Запись на стене'
        verbose_name_plural = 'Записи на стенах'
        ordering = ['-created_at', '-pk']


class Message(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages')
    receiver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_messages')
    text = models.TextField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)


# 5. НОВОСТИ И БИБЛИОТЕКА
class News(models.Model):
    CATEGORY_CHOICES = [
        ('update', 'Обновление'),
        ('announcement', 'Фикс'),
        ('tech', 'Тех. работы'),
    ]

    title = models.CharField(max_length=200, verbose_name="Заголовок")
    description = models.TextField(
        verbose_name="Текст",
        help_text="Пустая строка начинает новый абзац. **текст** — жирный, строка с «- » — пункт списка, ссылки становятся кликабельными.",
    )
    image = models.ImageField(upload_to='news/', blank=True, null=True, verbose_name="Обложка")
    games = models.ManyToManyField(
        Game, blank=True, related_name='news', verbose_name="Игры",
        help_text="Новость появится на странице этих игр в библиотеке.",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата публикации")
    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        default='update',
        verbose_name="Тип публикации"
    )
    is_published = models.BooleanField(
        default=True,
        verbose_name="Опубликовано",
        help_text="Без галочки новость остаётся черновиком: её видят только администраторы.",
    )
    is_pinned = models.BooleanField(
        default=False,
        verbose_name="Закреплено",
        help_text="Закреплённые новости показываются первыми.",
    )

    class Meta:
        verbose_name = "Новость"
        verbose_name_plural = "Новости"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('mfs:news_detail', args=[self.pk])


class NewsLike(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='news_likes')
    news = models.ForeignKey(News, on_delete=models.CASCADE, related_name='likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'news'], name='one_like_per_user_news'),
        ]


class UserLibrary(models.Model):
    # ИСПРАВЛЕНО: Заменено User на settings.AUTH_USER_MODEL
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='library')
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    purchased_at = models.DateTimeField(auto_now_add=True)
    last_played = models.DateTimeField(null=True, blank=True)
    playtime_seconds = models.PositiveIntegerField(default=0, verbose_name="Время в игре (секунд)")
    # Начало текущего сеанса; пусто, пока игра не запущена
    session_started_at = models.DateTimeField(null=True, blank=True, verbose_name="Запущена в")
    # Игру купили или подарили, но ещё не открывали в библиотеке — её считает счётчик у «Библиотеки»
    is_new = models.BooleanField(default=True, verbose_name="Новая игра")
    # Сколько заплатили (со скидкой) — для статистики продаж; пусто у покупок до появления поля
    price_paid = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Цена покупки",
    )

    class Meta:
        verbose_name = 'Игра пользователя'
        verbose_name_plural = 'Библиотека пользователей'
        constraints = [
            models.UniqueConstraint(fields=['user', 'game'], name='unique_library_entry'),
        ]

    def __str__(self):
        return f"{self.user.username} — {self.game.title}"

class Gift(models.Model):
    """Игра, подаренная другу: получатель видит в библиотеке, от кого она."""
    # SET_NULL: удаление аккаунта дарителя не должно стирать запись о подарке у получателя
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='gifts_sent', verbose_name="От кого",
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='gifts_received', verbose_name="Кому",
    )
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='gifts', verbose_name="Игра")
    message = models.CharField(max_length=200, blank=True, verbose_name="Сообщение")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Подарено")
    # Получатель ещё не видел уведомление о подарке
    seen = models.BooleanField(default=False, verbose_name="Просмотрен")

    class Meta:
        verbose_name = 'Подарок'
        verbose_name_plural = 'Подарки'
        ordering = ['-created_at']

    def __str__(self):
        sender = self.sender.username if self.sender else 'удалённый пользователь'
        return f'{sender} → {self.receiver.username}: {self.game.title}'
