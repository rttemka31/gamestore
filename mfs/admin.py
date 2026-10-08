from django.contrib import admin
from .models import Genre, Collection, Game, Dlc
from .models import Game, Screenshot
from .models import News

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
                '<img src="{}" style="max-height: 80px; max-width: 150px; border-radius: 6px; object-fit: cover;"/>', 
                obj.image.url
            )
        return "Нет изображения"
    image_preview.short_description = "Превью"

from django.contrib import admin
from django.utils.html import format_html
from .models import Game


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
                'description', 
                # Если второго описания нет — просто удалите эту строку или укажите правильное имя из models.py
            )
        }),
        ('Медиафайлы', {
            'fields': (
                ('icon', 'icon_preview'),
                ('cover', 'cover_preview'),
                # Укажите тут реальное поле для HD обложки, если оно есть (например: 'banner', 'hd_cover_image')
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

    # Методы превью картинок
    def icon_preview(self, obj):
        if obj.icon:
            return format_html('<img src="{}" style="max-height: 50px; border-radius: 4px;"/>', obj.icon.url)
        return "—"
    icon_preview.short_description = "Превью иконки"

    def cover_preview(self, obj):
        if obj.cover:
            return format_html('<img src="{}" style="max-height: 80px; border-radius: 4px;"/>', obj.cover.url)
        return "—"
    cover_preview.short_description = "Превью обложки"

@admin.register(Dlc)
class DlcAdmin(admin.ModelAdmin):
    list_display = ('title', 'price', 'discount')

@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "created_at",
    )

    search_fields = (
        "title",
    )