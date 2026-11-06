"""Витрина: каталог, новости, страницы и ссылки жанров."""
from django.contrib.auth.models import User
from django.urls import reverse

from ..models import Collection, Game, Genre, News, Profile, Review
from ..templatetags.store_extras import news_format, news_plain
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

        # 7-й запрос — версия сайта для подвала; дальше она берётся из кэша
        with self.assertNumQueries(7):
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
        self.assertContains(response, 'Версия 1.1.0')
        self.assertContains(response, reverse('mfs:register'))  # гостю — вход и регистрация

        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('mfs:index')), reverse('mfs:settings'))

    def test_new_version_appears_without_waiting_for_cache(self):
        News.objects.create(title='V1.1.0', description='x')
        self.client.get(reverse('mfs:index'))  # версия попадает в кэш
        News.objects.create(title='V1.2.0', description='x')
        self.assertContains(self.client.get(reverse('mfs:index')), 'Версия 1.2.0')


class BadgeAndMenuTests(StoreTestCase):
    def test_game_card_uses_shared_badges(self):
        Game.objects.filter(pk=self.game.pk).update(is_not_on_steam=True)
        response = self.client.get(reverse('mfs:catalog'))
        self.assertContains(response, 'badge badge-discount')
        self.assertContains(response, 'badge badge-exclusive game-card-label')
        self.assertNotContains(response, 'not-on-steam-badge2')

    def test_header_has_mobile_menu_button(self):
        for url in (reverse('mfs:index'), reverse('mfs:login')):
            response = self.client.get(url)
            self.assertContains(response, 'class="nav-toggle"')
            self.assertContains(response, 'aria-controls="siteNav navRight"')
