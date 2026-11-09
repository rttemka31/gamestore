"""Уменьшенные копии картинок (превью) для показа на сайте.

Скриншоты и HD-обложки загружаются по 1–5 МБ, а показываются в миниатюрах размером 100×55
или в блоке шириной ~700 px. Превью создаётся один раз при первом показе и лежит рядом
с остальными файлами: media/thumbs/<размер>/<путь исходника>.webp. Если исходник новее
превью (картинку заменили), превью пересоздаётся.
"""
import logging
import os
import re

from django.conf import settings
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

SPEC_RE = re.compile(r'^(\d{2,4})(?:x(\d{2,4}))?$')
THUMBS_DIR = 'thumbs'


def thumbnail_url(field, spec):
    """URL превью для ImageField.

    spec — «ШxВ» (обрезать по центру ровно под этот размер) или «Ш» (уменьшить до этой
    ширины, сохранив пропорции; маленькие картинки не увеличиваются). При любой ошибке
    возвращается адрес исходной картинки — страница не должна ломаться из-за превью.
    """
    if not field:
        return ''
    match = SPEC_RE.match(str(spec))
    original_url = field.url
    if not match:
        return original_url

    try:
        source = field.path
    except (NotImplementedError, ValueError):
        return original_url
    if not os.path.exists(source):
        return original_url  # файл пропал с диска — отдаём его адрес, как и без превью

    name = os.path.splitext(field.name)[0] + '.webp'
    relative = f'{THUMBS_DIR}/{spec}/{name}'
    target = os.path.join(settings.MEDIA_ROOT, *relative.split('/'))

    try:
        if not os.path.exists(target) or os.path.getmtime(target) < os.path.getmtime(source):
            _make_thumbnail(source, target, int(match[1]), int(match[2]) if match[2] else None)
    except (OSError, ValueError, Image.DecompressionBombError):
        logger.warning('Не удалось сделать превью %s (%s)', field.name, spec, exc_info=True)
        return original_url

    return settings.MEDIA_URL + relative


def _make_thumbnail(source, target, width, height):
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert('RGBA' if image.mode in ('RGBA', 'LA', 'P') else 'RGB')
        if height:
            image = ImageOps.fit(image, (width, height), Image.Resampling.LANCZOS)
        elif image.width > width:
            image = image.resize((width, round(image.height * width / image.width)), Image.Resampling.LANCZOS)

        os.makedirs(os.path.dirname(target), exist_ok=True)
        # Пишем во временный файл и подменяем: параллельный запрос не увидит недописанное превью
        temporary = f'{target}.{os.getpid()}.tmp'
        try:
            image.save(temporary, 'WEBP', quality=82, method=4)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
