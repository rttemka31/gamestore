from django.contrib import admin
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from .models import Collection, Dlc, Game, Genre, Gift, News, Review, Screenshot, UserLibrary
from .templatetags.store_extras import playtime
from .thumbnails import thumbnail_url

def _preview(file, field, style, empty='—'):
    """Превью картинки в админке. <img data-preview-for> есть всегда (без файла — скрытый):
    admin-preview.js подставляет в него выбранный файл сразу, ещё до сохранения."""
    if file:
        return format_html('<img src="{}" data-preview-for="{}" style="{}" alt="">', file.url, field, style)
    return format_html('<img data-preview-for="{}" style="{}" alt="" hidden><span data-preview-empty>{}</span>',
                       field, style, empty)


# Где на сайте видны обложки: подпись, размер кадра (ширина, высота), точка кадрирования, подпись размера.
# Картинка заполняет кадр и обрезается по краям, как на сайте (object-fit: cover)
HD_COVER_FRAMES = (
    ('Игра недели — компьютер', 755, 375, 'center', '755×375'),
    ('Игра недели — телефон', 345, 220, 'center', '345×220'),
    ('Шапка библиотеки — экран 1440px', 1190, 400, 'center 30%', '1190×400'),
    ('Шапка библиотеки — экран 1920px', 1670, 400, 'center 30%', '1670×400'),
    ('Шапка библиотеки — телефон', 375, 240, 'center 30%', '375×240'),
    ('Обложка трейлера', 16, 9, 'center', '16:9'),
)
COVER_FRAMES = (
    ('Карточка в магазине и каталоге', 389, 150, 'center', '389×150'),
    ('Галерея на странице игры', 16, 9, 'center', '16:9'),
    ('Корзина, избранное, активность', 2, 1, 'center', '2:1'),
)
FRAME_HEIGHT = 110  # высота кадров в админке: так помещаются в строку и видна разница пропорций


def _cover_frames(kind, frames, url):
    """Ряд кадров с одной картинкой в пропорциях разных мест сайта."""
    hidden = mark_safe('' if url else ' hidden')
    return format_html_join('', (
        '<figure style="margin: 0; max-width: 100%;">'
        '<div style="width: {}px; max-width: 100%; aspect-ratio: {} / {}; overflow: hidden; border-radius: 8px; '
        'background: var(--darkened-bg); border: 1px solid var(--hairline-color);">'
        '<img data-frame="{}" src="{}" alt="" style="width: 100%; height: 100%; object-fit: cover; object-position: {}; display: block;"{}>'
        '</div><figcaption style="margin-top: 4px; font-size: 12px; color: var(--body-quiet-color);">{} · {}</figcaption></figure>'
    ), ((round(FRAME_HEIGHT * w / h), w, h, kind, url, position, hidden, label, size)
        for label, w, h, position, size in frames))


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug')
    prepopulated_fields = {'slug': ('title',)}

class ScreenshotInline(admin.TabularInline):  # Табличный вид вместо слоистого
    model = Screenshot
    extra = 1
    fields = ('image', 'image_preview', 'sensitive')
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        return _preview(obj.image if obj else None, 'image',
                        'max-height: 80px; max-width: 150px; border-radius: 5px; object-fit: cover;', 'Нет изображения')
    image_preview.short_description = "Превью"

    class Media:
        js = ('js/admin-preview.js',)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    # Ваши существующие настройки списка
    list_display = ('cover_thumb', 'title', 'price', 'discount', 'discount_until', 'is_not_on_steam', 'is_game_of_the_week')
    # Нажатие на обложку или название открывает игру — там обложку можно заменить
    list_display_links = ('cover_thumb', 'title')
    list_editable = ('is_not_on_steam', 'is_game_of_the_week')
    filter_horizontal = ('genres', 'collections')  # Сохранены и genres, и collections
    inlines = [ScreenshotInline]

    # Только для чтения — подставьте сюда имена ваших превью-методов
    readonly_fields = ('icon_preview', 'cover_preview', 'cover_hd_preview', 'cover_site_preview')

    # Группировка полей (Замените названия полей на те, что у вас в models.py!)
    fieldsets = (
        ('Основная информация', {
            'fields': (
                'title',
                'author',
                'age_rating',
                'description',
                'long_description',
            )
        }),
        ('Медиафайлы', {
            'fields': (
                ('icon', 'icon_preview'),
                ('cover', 'cover_preview'),
                ('cover_hd', 'cover_hd_preview'),
                'cover_site_preview',
                ('trailer_file', 'trailer_sensitive'),
            ),
        }),
        ('Продажи и Статус', {
            'fields': (
                ('price', 'discount', 'discount_until'),
                ('is_not_on_steam', 'is_game_of_the_week'),  # Переключатели в одну строку
                'release_date',
                'size_gb',
            ),
        }),
        ('Категории', {
            'fields': ('genres', 'collections'),
        }),
    )

    def get_changeform_initial_data(self, request):
        # Автор новой игры по умолчанию — тот, кто её добавляет
        return {'author': request.user.pk, **super().get_changeform_initial_data(request)}

    # Методы превью картинок
    def icon_preview(self, obj):
        return _preview(obj.icon if obj else None, 'icon', 'max-height: 50px; border-radius: 5px;')
    icon_preview.short_description = "Превью иконки"

    def cover_preview(self, obj):
        return _preview(obj.cover if obj else None, 'cover', 'max-height: 80px; border-radius: 15px;')
    cover_preview.short_description = "Превью обложки"

    def cover_hd_preview(self, obj):
        return _preview(obj.cover_hd if obj else None, 'cover_hd', 'max-height: 80px; border-radius: 15px;')
    cover_hd_preview.short_description = "Превью HD обложки"

    @admin.display(description='Обложки на сайте')
    def cover_site_preview(self, obj):
        # Видно, что останется от картинки в каждом месте сайта; admin-preview.js
        # подставляет сюда выбранный файл сразу, ещё до сохранения
        cover = obj.cover.url if obj and obj.cover else ''
        cover_hd = obj.cover_hd.url if obj and obj.cover_hd else ''
        row = 'display: flex; flex-wrap: wrap; gap: 12px; margin-top: 6px;'
        return format_html(
            '<div data-cover-frames data-cover="{}" data-cover-hd="{}" style="display: flex; flex-direction: column; gap: 16px;">'
            '<div><strong>HD обложка</strong> <span class="help">— если её нет, сайт берёт обычную</span>'
            '<div style="{}">{}</div></div>'
            '<div><strong>Обычная обложка</strong><div style="{}">{}</div></div>'
            '</div>',
            cover, cover_hd,
            row, _cover_frames('hd', HD_COVER_FRAMES, cover_hd or cover),
            row, _cover_frames('cover', COVER_FRAMES, cover),
        )

    @admin.display(description='Обложка')
    def cover_thumb(self, obj):
        # В списке игр — маленькая обложка (HD, если есть), чтобы игру было видно сразу
        field = obj.cover_hd or obj.cover
        if not field:
            return '—'
        return format_html('<img src="{}" alt="" style="width: 96px; height: 48px; object-fit: cover; border-radius: 6px; display: block;">',
                           thumbnail_url(field, '192x96'))

    class Media:
        # admin-cover-crop.js — окно кропа обложки при выборе файла
        js = ('js/admin-preview.js', 'js/admin-cover-crop.js')

@admin.register(Dlc)
class DlcAdmin(admin.ModelAdmin):
    list_display = ('title', 'price', 'discount', 'discount_until')

@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_published", "is_pinned", "created_at")
    list_editable = ("is_published", "is_pinned")
    list_filter = ("is_published", "is_pinned", "category")
    search_fields = ("title", "description")
    date_hierarchy = "created_at"
    actions = ("publish", "unpublish")
    filter_horizontal = ("games",)
    fieldsets = (
        (None, {"fields": ("title", "category", "description", "image", "games")}),
        ("Публикация", {"fields": ("is_published", "is_pinned")}),
    )

    @admin.action(description="Опубликовать выбранные новости")
    def publish(self, request, queryset):
        queryset.update(is_published=True)

    @admin.action(description="Снять с публикации (в черновики)")
    def unpublish(self, request, queryset):
        queryset.update(is_published=False)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('game', 'user', 'rating', 'created_at')
    list_filter = ('rating',)
    search_fields = ('game__title', 'user__username', 'text')
    list_select_related = ('game', 'user')


@admin.register(Gift)
class GiftAdmin(admin.ModelAdmin):
    list_display = ('game', 'sender', 'receiver', 'created_at', 'seen')
    list_filter = ('seen',)
    search_fields = ('game__title', 'sender__username', 'receiver__username')
    list_select_related = ('game', 'sender', 'receiver')
    readonly_fields = ('created_at',)


@admin.register(UserLibrary)
class UserLibraryAdmin(admin.ModelAdmin):
    list_display = ('user', 'game', 'playtime_display', 'last_played', 'session_started_at', 'purchased_at')
    list_filter = (('session_started_at', admin.EmptyFieldListFilter),)
    search_fields = ('game__title', 'user__username')
    list_select_related = ('game', 'user')
    readonly_fields = ('purchased_at',)

    @admin.display(description='Время в игре', ordering='playtime_seconds')
    def playtime_display(self, obj):
        return playtime(obj.playtime_seconds)
