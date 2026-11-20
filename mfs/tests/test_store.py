"""Витрина: каталог, новости, страницы и ссылки жанров."""
import io
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from ..models import (
    Collection, DiscountExpiryMiddleware, Game, Genre, News, NewsLike, Profile, Review, ReviewVote, Screenshot,
    UserLibrary, expire_discounts,
)
from ..templatetags.store_extras import news_format, news_plain, playtime_words
from ..thumbnails import thumbnail_url
from ..views.store import _pick_featured_game
from .base import StoreTestCase


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

        # Последний запрос — версия сайта для подвала; дальше она берётся из кэша
        with self.assertNumQueries(6):
            self.client.get(reverse('mfs:index'))

        for i in range(5):
            game = Game.objects.create(author=self.other, title=f'G{i}', price=1)
            game.collections.add(collection)
            game.genres.add(genre)

        with self.assertNumQueries(5):
            self.client.get(reverse('mfs:index'))

    def test_game_title_and_description_are_limited(self):
        # Описание — TextField: его длину проверяют формы (в том числе админка), как здесь
        from django.forms import modelform_factory
        GameForm = modelform_factory(Game, fields=['title', 'description', 'long_description'])
        form = GameForm({'title': 'x' * 61, 'description': 'y' * 301, 'long_description': 'z' * 5001})
        self.assertEqual(set(form.errors), {'title', 'description', 'long_description'})
        form = GameForm({'title': 'x' * 60, 'description': 'y' * 300, 'long_description': 'z' * 5000})
        self.assertTrue(form.is_valid(), form.errors)

    def test_game_of_the_week_changes_every_monday(self):
        for i in range(3):
            Game.objects.create(author=self.other, title=f'G{i}', price=1)
        kyiv = ZoneInfo('Europe/Kyiv')
        sunday_night = datetime(2026, 11, 15, 23, 59, tzinfo=kyiv)
        monday = datetime(2026, 11, 16, 0, 0, tzinfo=kyiv)

        this_week, next_rotation = _pick_featured_game(sunday_night)
        self.assertEqual(next_rotation, '2026-11-16T00:00:00+02:00')
        self.assertEqual(_pick_featured_game(datetime(2026, 11, 10, 12, 0, tzinfo=kyiv))[0], this_week)
        self.assertNotEqual(_pick_featured_game(monday)[0], this_week)

        # За полный круг из 5 недель показывается каждая игра
        weeks = [_pick_featured_game(monday + timedelta(weeks=n))[0] for n in range(5)]
        self.assertEqual(len(set(weeks)), 5)

    def test_admin_flags_limit_rotation_only_from_two_games(self):
        Game.objects.filter(pk=self.game2.pk).update(is_game_of_the_week=True)
        Game.objects.create(author=self.other, title='Gamma', price=1)
        start = datetime(2026, 11, 16, tzinfo=ZoneInfo('Europe/Kyiv'))
        # Одна отметка не держит игру навсегда
        weeks = {_pick_featured_game(start + timedelta(weeks=n))[0] for n in range(3)}
        self.assertEqual(len(weeks), 3)

        Game.objects.filter(pk=self.game.pk).update(is_game_of_the_week=True)
        weeks = {_pick_featured_game(start + timedelta(weeks=n))[0] for n in range(4)}
        self.assertEqual(weeks, {self.game, self.game2})

    def test_search_returns_discounted_price(self):
        game = self.client.get(reverse('mfs:game_search_ajax') + '?q=alp').json()['games'][0]
        self.assertEqual((game['price'], game['old_price']), (50, 100))


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

    def test_category_sidebar_and_search_clear_button(self):
        News.objects.create(title='Патч', description='x', category='announcement')
        response = self.client.get(reverse('mfs:news') + '?category=announcement&q=патч')
        # Категории — боковая панель, как в каталоге; выбранная отмечена
        self.assertContains(response, 'class="filter-option filter-option-radio active" aria-current="page"')
        self.assertContains(response, 'id="newsSidebar"')
        # Поиск устроен как в магазине: крестик очистки и кнопка лупы
        self.assertContains(response, 'class="clear-search-btn"')
        self.assertContains(response, 'img/icons/search.png')

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


class AccentAndGenreLinkTests(StoreTestCase):
    def test_user_accent_comes_after_page_stylesheets(self):
        Profile.objects.filter(user=self.user).update(accent_color='#10b981')
        self.client.force_login(self.user)

        for url, stylesheet in ((reverse('mfs:library'), 'library.css'), (reverse('mfs:cart_detail'), 'cart.css')):
            content = self.client.get(url).content.decode()
            self.assertLess(content.index(stylesheet), content.index('--accent: #10b981'), url)

    def test_game_page_genres_link_to_catalog(self):
        genre = Genre.objects.create(name='Песочница', slug='sandbox')
        self.game.genres.add(genre)
        response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        self.assertContains(response, f'href="{reverse("mfs:catalog")}?genre=sandbox"')


class PagesTests(StoreTestCase):
    def test_cart_shows_exclusive_and_discount_badges_together(self):
        Game.objects.filter(pk=self.game.pk).update(is_not_on_steam=True)
        self.client.force_login(self.user)
        self.ajax_add(self.game)

        response = self.client.get(reverse('mfs:cart_detail'))
        self.assertContains(response, 'cart-badges')
        self.assertContains(response, '<span class="badge badge-exclusive">Эксклюзив</span>')
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

    def test_review_shows_author_avatar_or_letter(self):
        Profile.objects.filter(user=self.other).update(avatar='avatars/bob.png')
        Review.objects.create(user=self.other, game=self.game, rating=4)
        Review.objects.create(user=self.user, game=self.game, rating=5)
        with self.assertNumQueries(7):  # аватарки берутся тем же запросом, что и отзывы
            response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        self.assertContains(response, 'class="review-avatar"', count=2)
        self.assertContains(response, 'src="/media/avatars/bob.png"')
        self.assertContains(response, '<span>A</span>')

    def test_owned_game_button_opens_it_in_library(self):
        self.game.owners.add(self.user)
        self.client.force_login(self.user)
        response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        self.assertContains(response, f'data-url="{reverse("mfs:library")}?active={self.game.pk}"')
        # Ещё не купленная игра знает свой id — для перехода после бесплатного получения
        response = self.client.get(reverse('mfs:game_detail', args=[self.game2.pk]))
        self.assertContains(response, f'data-game-id="{self.game2.pk}"')

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


class FooterTests(StoreTestCase):
    def test_footer_shows_links_and_current_version(self):
        News.objects.create(title='V1.1.0', description='x')
        response = self.client.get(reverse('mfs:index'))
        self.assertContains(response, 'site-footer')
        self.assertContains(response, '>V1.1.0</a>')
        self.assertContains(response, reverse('mfs:register'))  # гостю — вход и регистрация

        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('mfs:index')), reverse('mfs:settings'))

    def test_new_version_appears_without_waiting_for_cache(self):
        News.objects.create(title='V1.1.0', description='x')
        self.client.get(reverse('mfs:index'))  # версия попадает в кэш
        News.objects.create(title='V1.2.0', description='x')
        self.assertContains(self.client.get(reverse('mfs:index')), '>V1.2.0</a>')


class BadgeAndMenuTests(StoreTestCase):
    def test_game_card_uses_shared_badges(self):
        Game.objects.filter(pk=self.game.pk).update(is_not_on_steam=True)
        response = self.client.get(reverse('mfs:catalog'))
        self.assertContains(response, 'badge badge-discount')
        self.assertContains(response, 'badge badge-exclusive game-card-label')
        self.assertNotContains(response, 'not-on-steam-badge2')

    def test_catalog_title_and_cart_price_style(self):
        response = self.client.get(reverse('mfs:catalog'))
        self.assertEqual(response.context['title'], 'Каталог')
        self.assertContains(response, '<title>GameStore | Каталог</title>', html=False)

        self.client.force_login(self.user)
        self.ajax_add(self.game)
        response = self.client.get(reverse('mfs:cart_detail'))
        # Цена в корзине в том же виде, что в карточках: значок скидки, старая и новая цена
        self.assertContains(response, 'class="game-bottom cart-price-line"')
        self.assertContains(response, '<span class="badge badge-discount">-50%</span>')
        self.assertContains(response, '<span class="price">50₴</span>')

    def test_hint_has_title_strip(self):
        Game.objects.filter(pk=self.game.pk).update(is_not_on_steam=True)
        response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        self.assertContains(response, 'data-hint-title="Эксклюзив"')

    def test_header_has_mobile_menu_button(self):
        for url in (reverse('mfs:index'), reverse('mfs:login')):
            response = self.client.get(url)
            self.assertContains(response, 'class="nav-toggle"')
            self.assertContains(response, 'aria-controls="siteNav navRight"')


class ThumbnailTests(StoreTestCase):
    def make_screenshot(self, size):
        buffer = io.BytesIO()
        Image.new('RGB', size, 'red').save(buffer, 'PNG')
        return Screenshot.objects.create(
            game=self.game, image=SimpleUploadedFile('shot.png', buffer.getvalue(), content_type='image/png'),
        )

    def thumb_file(self, url):
        return os.path.join(settings.MEDIA_ROOT, *url.removeprefix(settings.MEDIA_URL).split('/'))

    def test_crop_and_width_previews(self):
        shot = self.make_screenshot((1600, 1000))
        cropped = thumbnail_url(shot.image, '200x110')
        self.assertTrue(cropped.startswith('/media/thumbs/200x110/screenshots/') and cropped.endswith('.webp'))
        with Image.open(self.thumb_file(cropped)) as image:
            self.assertEqual((image.format, image.size), ('WEBP', (200, 110)))

        with Image.open(self.thumb_file(thumbnail_url(shot.image, '1280'))) as image:
            self.assertEqual(image.size, (1280, 800))

    def test_small_image_is_not_upscaled_and_errors_fall_back(self):
        shot = self.make_screenshot((300, 200))
        with Image.open(self.thumb_file(thumbnail_url(shot.image, '1280'))) as image:
            self.assertEqual(image.size, (300, 200))

        self.assertEqual(thumbnail_url(shot.image, 'huge'), shot.image.url)
        os.remove(shot.image.path)
        # Исходник пропал — отдаём его адрес, страница не падает
        self.assertEqual(thumbnail_url(shot.image, '640'), shot.image.url)

    def test_game_page_uses_previews(self):
        self.make_screenshot((1600, 900))
        response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        self.assertContains(response, 'src="/media/thumbs/200x110/screenshots/')
        self.assertContains(response, 'data-full="/media/thumbs/1280/screenshots/')


class Round5Tests(StoreTestCase):
    def test_featured_game_has_muted_trailer_loaded_on_demand(self):
        Game.objects.update(cover='covers/c.png', trailer_file='trailers/t.mp4')
        response = self.client.get(reverse('mfs:index'))
        # Видео без звука и без предзагрузки: файл подставляется скриптом только при долгом наведении
        self.assertContains(response, 'class="featured-trailer" muted loop playsinline preload="none"')
        self.assertContains(response, 'data-src="/media/trailers/t.mp4"')

    def test_catalog_hides_genres_after_first_eight_except_selected(self):
        genres = [Genre.objects.create(name=f'Жанр {i:02}', slug=f'g{i:02}') for i in range(12)]
        self.game.genres.set(genres)
        response = self.client.get(reverse('mfs:catalog'), {'genre': 'g11'})
        html = response.content.decode()
        self.assertEqual(html.count('class="filter-option filter-option-extra"'), 3)  # 12 жанров − 8 видимых − 1 отмеченный
        self.assertContains(response, 'id="genreMore"')

    def test_admin_preview_is_ready_before_saving(self):
        admin = User.objects.create_superuser('root', password='Str0ng-pass-123')
        self.client.force_login(admin)
        response = self.client.get(reverse('admin:mfs_game_add'))
        # Пустое превью уже на странице (скрытое), скрипт подставит в него выбранный файл
        self.assertContains(response, 'data-preview-for="cover"')
        self.assertContains(response, 'data-preview-for="icon"')
        self.assertContains(response, 'js/admin-preview.js')


class Round7Tests(StoreTestCase):
    def genre_names(self):
        return [g.name for g in self.client.get(reverse('mfs:catalog')).context['genres']]

    def test_genres_sorted_by_popularity_or_name(self):
        shooter = Genre.objects.create(name='Шутер', slug='shooter')
        coop = Genre.objects.create(name='Для нескольких игроков', slug='coop')
        arcade = Genre.objects.create(name='Аркада', slug='arcade')
        self.game.genres.set([shooter, coop, arcade])
        self.game2.genres.set([coop])
        Game.objects.create(author=self.other, title='Gamma', price=1).genres.set([coop, shooter])
        # По умолчанию — больше игр выше, при равенстве по алфавиту
        self.assertEqual(self.genre_names(), ['Для нескольких игроков', 'Шутер', 'Аркада'])

        self.client.force_login(self.user)
        self.client.post(reverse('mfs:settings'), {'form': 'catalog', 'genre_sort': 'name', 'default_catalog_sort': 'new'})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.genre_sort, 'name')
        self.assertEqual(self.genre_names(), ['Аркада', 'Для нескольких игроков', 'Шутер'])

        # Неизвестное значение не сохраняется
        self.client.post(reverse('mfs:settings'), {'form': 'catalog', 'genre_sort': 'junk'})
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.genre_sort, 'name')
        self.assertContains(self.client.get(reverse('mfs:settings')), 'name="genre_sort"')

    def test_author_links_to_profile_and_has_developer_role(self):
        response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        self.assertContains(response, f'href="{reverse("mfs:user_profile", args=["bob"])}" class="detail-author-link">bob</a>')
        # bob — автор игр: роль «Разработчик»; alice без игр — «Пользователь»
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('mfs:user_profile', args=['bob'])), '#role-developer"></use></svg>Разработчик')
        self.assertContains(self.client.get(reverse('mfs:profile')), '#role-user"></use></svg>Пользователь')

        Game.objects.update(author=None)
        self.assertContains(self.client.get(reverse('mfs:game_detail', args=[self.game.pk])), '<span>Не указан</span>')

    def test_age_rating_next_to_title(self):
        url = reverse('mfs:game_detail', args=[self.game.pk])
        self.assertNotContains(self.client.get(url), 'class="game-age-rating"')
        Game.objects.filter(pk=self.game.pk).update(age_rating='18+')
        self.assertContains(self.client.get(url), '<span class="game-age-rating" title="Возрастной рейтинг">18+</span>')

    def test_sensitive_screenshot_and_trailer_are_blurred(self):
        Screenshot.objects.create(game=self.game, image='screenshots/a.png', sensitive='violence')
        Screenshot.objects.create(game=self.game, image='screenshots/b.png')
        url = reverse('mfs:game_detail', args=[self.game.pk])
        response = self.client.get(url)
        html = response.content.decode()
        self.assertEqual(html.count('data-sensitive="жестокость"'), 1)
        # Первый скриншот (обложки и трейлера нет) неприятный — большой кадр размыт сразу, без скрипта
        self.assertContains(response, 'class="main-image-box is-sensitive"')
        self.assertContains(response, '<span id="sensitiveKind">жестокость</span>')

        Game.objects.filter(pk=self.game.pk).update(trailer_file='trailers/t.mp4', trailer_sensitive='nudity')
        response = self.client.get(url)
        self.assertContains(response, 'class="thumb video-thumb active" data-sensitive="нагота"')
        self.assertContains(response, 'class="main-image-box is-sensitive"')

        # Неприятный трейлер не включается сам на игре недели
        Game.objects.update(cover='covers/c.png', trailer_file='trailers/t.mp4', trailer_sensitive='violence')
        self.assertNotContains(self.client.get(reverse('mfs:index')), 'class="featured-trailer"')

    def test_sensitive_screenshot_in_library_and_admin(self):
        Screenshot.objects.create(game=self.game, image='screenshots/a.png', sensitive='nudity')
        self.game.owners.add(self.user)
        self.client.force_login(self.user)
        response = self.client.get(reverse('mfs:library'))
        self.assertContains(response, 'data-sensitive="нагота" class="sensitive-media"')

        admin = User.objects.create_superuser('root', password='Str0ng-pass-123')
        self.client.force_login(admin)
        response = self.client.get(reverse('admin:mfs_game_change', args=[self.game.pk]))
        self.assertContains(response, 'name="screenshots-0-sensitive"')
        self.assertContains(response, 'name="trailer_sensitive"')
        self.assertContains(response, 'name="age_rating"')


class Round8Tests(StoreTestCase):
    def test_admin_shows_cover_previews_in_form_and_list(self):
        admin = User.objects.create_superuser('root', password='Str0ng-pass-123')
        self.client.force_login(admin)
        response = self.client.get(reverse('admin:mfs_game_add'))
        # Превью HD обложки есть сразу (пустое) — скрипт подставит выбранный файл до сохранения
        self.assertContains(response, 'data-preview-for="cover_hd"')
        response = self.client.get(reverse('admin:mfs_game_changelist'))
        self.assertContains(response, 'column-cover_thumb')

    def test_sensitive_thumb_is_wrapped_so_border_stays_sharp(self):
        Screenshot.objects.create(game=self.game, image='screenshots/a.png', sensitive='violence')
        response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        # Рамка у обёртки, размывается только картинка внутри
        self.assertContains(response, 'class="thumb media-thumb active"')


class Round10Tests(StoreTestCase):
    def test_wishlist_button_is_icon_only_with_accessible_label(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        self.assertContains(response, 'purchase-icon-btn js-wishlist-toggle')
        self.assertContains(response, 'aria-label="Добавить в желаемое"')
        self.assertNotContains(response, 'js-wishlist-label')


class Round14Tests(StoreTestCase):
    def test_trailer_thumb_uses_same_hd_cover_as_video(self):
        Game.objects.filter(pk=self.game.pk).update(cover='covers/c.png', cover_hd='covers_hd/h.png', trailer_file='trailers/t.mp4')
        response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        # Исходника нет на диске — превью отдаёт его же адрес; главное, что это HD обложка, как у постера видео
        self.assertContains(response, '<img src="/media/covers_hd/h.png" alt="Трейлер"')

    def test_admin_shows_covers_in_site_proportions(self):
        admin = User.objects.create_superuser('root', password='Str0ng-pass-123')
        self.client.force_login(admin)
        Game.objects.filter(pk=self.game.pk).update(cover='covers/c.png')
        response = self.client.get(reverse('admin:mfs_game_change', args=[self.game.pk]))
        self.assertContains(response, 'data-cover-frames')
        self.assertContains(response, 'Шапка библиотеки')
        # Без HD обложки места для неё показывают обычную, как и сайт
        self.assertContains(response, 'data-frame="hd" src="/media/covers/c.png"')
        # При выборе файла обложку можно расположить в рамке, как баннер в профиле
        self.assertContains(response, 'js/admin-cover-crop.js')


class NewsLikeTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.news = News.objects.create(title='Патч', description='Текст')
        self.url = reverse('mfs:news_like', args=[self.news.pk])

    def test_like_toggles_and_returns_count(self):
        self.client.force_login(self.user)
        data = self.client.post(self.url).json()
        self.assertEqual((data['active'], data['count']), (True, 1))
        data = self.client.post(self.url).json()
        self.assertEqual((data['active'], data['count']), (False, 0))

    def test_guest_is_sent_to_login_and_draft_cannot_be_liked(self):
        self.assertEqual(self.client.post(self.url).status_code, 401)
        self.client.force_login(self.user)
        draft = News.objects.create(title='Черновик', description='—', is_published=False)
        self.assertEqual(self.client.post(reverse('mfs:news_like', args=[draft.pk])).status_code, 404)

    def test_list_and_detail_show_count_and_my_like(self):
        NewsLike.objects.create(user=self.other, news=self.news)
        NewsLike.objects.create(user=self.user, news=self.news)
        self.client.force_login(self.user)
        for url in (reverse('mfs:news'), reverse('mfs:news_detail', args=[self.news.pk])):
            response = self.client.get(url)
            self.assertContains(response, 'count-toggle js-toggle-count active')
            self.assertContains(response, '<span class="js-count">2</span>')


class ReviewHelpfulTests(StoreTestCase):
    def test_review_remembers_playtime_at_the_moment(self):
        UserLibrary.objects.create(user=self.user, game=self.game, playtime_seconds=45000)
        self.client.force_login(self.user)
        self.client.post(reverse('mfs:review_submit', args=[self.game.pk]), {'rating': 5, 'text': 'Класс'})
        UserLibrary.objects.filter(user=self.user).update(playtime_seconds=90000)  # играл дальше — в отзыве прежнее время
        response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        self.assertContains(response, '12,5 часа в игре')

    def test_playtime_in_words(self):
        cases = {0: '0 минут', 61: '1 минута', 17 * 60: '17 минут', 22 * 60: '22 минуты',
                 3600: '1 час', 3 * 3600: '3 часа', 5 * 3600: '5 часов', 45000: '12,5 часа'}
        for seconds, text in cases.items():
            self.assertEqual(playtime_words(seconds), text)

    def test_review_without_game_in_library_has_no_playtime(self):
        self.client.force_login(self.user)
        self.client.post(reverse('mfs:review_submit', args=[self.game.pk]), {'rating': 4})
        self.assertIsNone(Review.objects.get(user=self.user).playtime_seconds)

    def test_vote_toggles_but_not_on_own_review(self):
        review = Review.objects.create(user=self.other, game=self.game, rating=5)
        mine = Review.objects.create(user=self.user, game=self.game, rating=3)
        self.client.force_login(self.user)
        url = reverse('mfs:review_vote', args=[review.pk])
        self.assertEqual(self.client.post(url).json()['count'], 1)
        self.assertEqual(self.client.post(url).json()['count'], 0)
        response = self.client.post(reverse('mfs:review_vote', args=[mine.pk]))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ReviewVote.objects.exists())

    def test_helpful_reviews_go_first_and_new_sort_by_date(self):
        old = Review.objects.create(user=self.other, game=self.game, rating=5, text='Старый полезный')
        Review.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=3))
        Review.objects.create(user=self.user, game=self.game, rating=2, text='Свежий')
        ReviewVote.objects.create(user=User.objects.create_user('carol'), review=old)
        url = reverse('mfs:game_detail', args=[self.game.pk])

        content = self.client.get(url).content.decode()
        self.assertLess(content.index('Старый полезный'), content.index('Свежий'))
        content = self.client.get(url + '?reviews=new').content.decode()
        self.assertLess(content.index('Свежий'), content.index('Старый полезный'))


class LinkPreviewTests(StoreTestCase):
    def test_game_page_has_cover_title_and_price(self):
        Game.objects.filter(pk=self.game.pk).update(cover_hd='covers_hd/h.png')
        response = self.client.get(reverse('mfs:game_detail', args=[self.game.pk]))
        self.assertContains(response, '<meta property="og:title" content="Alpha — 50₴ (−50%)">')
        self.assertContains(response, '<meta property="og:image" content="http://testserver/media/covers_hd/h.png">')
        self.assertContains(response, '<meta name="twitter:card" content="summary_large_image">')

    def test_other_pages_have_site_preview(self):
        response = self.client.get(reverse('mfs:catalog'))
        self.assertContains(response, '<meta property="og:title" content="GameStore">')
        self.assertContains(response, 'og:image" content="http://testserver/static/img/icons/gamestore.png')


class DiscountDeadlineTests(StoreTestCase):
    def test_expired_discount_is_removed(self):
        Game.objects.filter(pk=self.game.pk).update(discount_until=timezone.now() - timedelta(minutes=1))
        Game.objects.filter(pk=self.game2.pk).update(discount=10, discount_until=timezone.now() + timedelta(days=2))
        expire_discounts()
        self.game.refresh_from_db()
        self.game2.refresh_from_db()
        self.assertEqual((self.game.discount, self.game.discount_until), (0, None))
        self.assertEqual(self.game2.discount, 10)

    def test_pages_check_deadlines_and_show_countdown(self):
        Game.objects.filter(pk=self.game.pk).update(discount_until=timezone.now() - timedelta(minutes=1))
        Game.objects.filter(pk=self.game2.pk).update(discount=10, discount_until=timezone.now() + timedelta(days=2))
        cache.delete(DiscountExpiryMiddleware.CACHE_KEY)
        response = self.client.get(reverse('mfs:game_detail', args=[self.game2.pk]))
        self.assertContains(response, 'js-deadline')
        self.assertContains(response, 'Скидка до')
        self.game.refresh_from_db()
        self.assertEqual(self.game.discount, 0)  # сроки проверил middleware при открытии страницы


class AdminStatsTests(StoreTestCase):
    def test_stats_page_counts_sales_and_signups(self):
        UserLibrary.objects.create(user=self.user, game=self.game, price_paid=50)
        UserLibrary.objects.create(user=self.other, game=self.game, price_paid=50)
        UserLibrary.objects.create(user=self.user, game=self.game2, price_paid=None)
        admin = User.objects.create_superuser('root', password='Str0ng-pass-123')
        self.client.force_login(admin)
        response = self.client.get(reverse('admin_stats') + '?days=7')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['totals']['purchases'], 3)
        self.assertEqual(response.context['totals']['revenue'], 100)
        self.assertEqual(response.context['top_games'][0]['game__title'], 'Alpha')
        self.assertEqual(len(response.context['sales']), 7)
        self.assertEqual(response.context['signups'][-1]['count'], 3)  # alice, bob и root зарегистрированы сегодня

    def test_stats_are_for_staff_only(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('admin_stats')).status_code, 302)

    def test_checkout_remembers_price_paid(self):
        self.client.force_login(self.user)
        self.ajax_add(self.game)
        self.client.post(reverse('mfs:checkout'))
        self.assertEqual(UserLibrary.objects.get(user=self.user, game=self.game).price_paid, 50)
