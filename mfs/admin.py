from django.contrib import admin
from django.utils.html import format_html

from .models import Collection, Dlc, Game, Genre, News, Review, Screenshot

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
    fields = ('image', 'image_preview')  # Если поле картинки называется по-другому, замените 'image'
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        if hasattr(obj, 'image') and obj.image:  # Проверка наличия файла
            return format_html(
                '<img src="{}" style="max-height: 80px; max-width: 150px; border-radius: 5px; object-fit: cover;"/>', 
                obj.image.url
            )
        return "Нет изображения"
    image_preview.short_description = "Превью"


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    # Ваши существующие настройки списка
    list_display = ('title', 'price', 'discount', 'is_not_on_steam', 'is_game_of_the_week')
    list_editable = ('is_not_on_steam', 'is_game_of_the_week')
    filter_horizontal = ('genres', 'collections')  # Сохранены и genres, и collections
    inlines = [ScreenshotInline]

    # Только для чтения — подставьте сюда имена ваших превью-методов
    readonly_fields = ('icon_preview', 'cover_preview')

    # Группировка полей (Замените названия полей на те, что у вас в models.py!)
    fieldsets = (
        ('Основная информация', {
            'fields': (
                'title',
                'author',
                'description',
                'long_description',
            )
        }),
        ('Медиафайлы', {
            'fields': (
                ('icon', 'icon_preview'),
                ('cover', 'cover_preview'),
                'cover_hd',
                'trailer_file',
            ),
        }),
        ('Продажи и Статус', {
            'fields': (
                ('price', 'discount'),
                ('is_not_on_steam', 'is_game_of_the_week'),  # Переключатели в одну строку
                'release_date'
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
        if obj.icon:
            return format_html('<img src="{}" style="max-height: 50px; border-radius: 5px;"/>', obj.icon.url)
        return "—"
    icon_preview.short_description = "Превью иконки"

    def cover_preview(self, obj):
        if obj.cover:
            return format_html('<img src="{}" style="max-height: 80px; border-radius: 15px;"/>', obj.cover.url)
        return "—"
    cover_preview.short_description = "Превью обложки"

@admin.register(Dlc)
class DlcAdmin(admin.ModelAdmin):
    list_display = ('title', 'price', 'discount')

@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "is_published", "is_pinned", "created_at")
    list_editable = ("is_published", "is_pinned")
    list_filter = ("is_published", "is_pinned", "category")
    search_fields = ("title", "description")
    date_hierarchy = "created_at"
    actions = ("publish", "unpublish")
    fieldsets = (
        (None, {"fields": ("title", "category", "description", "image")}),
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
