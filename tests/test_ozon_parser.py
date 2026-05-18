from books_catalog.parser import (
    cleanup_ozon_title,
    detect_ozon_antibot,
    extract_best_from_srcset,
    extract_product_id_from_ozon_url,
    normalize_price,
)


def test_normalize_price_spaces():
    assert normalize_price("1 457 ₽") == "1 457 ₽"
    assert normalize_price("1 457 ₽") == "1 457 ₽"
    assert normalize_price("1457 руб.") == "1 457 ₽"


def test_extract_product_id():
    url = "https://www.ozon.ru/product/momenty-schastya-v-iskusstve-vospevanie-zhizni-3672162343/?from=share"
    assert extract_product_id_from_ozon_url(url) == "3672162343"


def test_srcset_extract():
    srcset = "https://a.jpg 100w, https://b.jpg 400w, https://c.jpg 800w"
    assert extract_best_from_srcset(srcset) == "https://c.jpg"


def test_antibot_detection():
    assert detect_ozon_antibot("Проверка безопасности. Подтвердите, что вы не робот")


def test_title_cleanup():
    text = "Моменты счастья в искусстве. Воспевание жизни купить на OZON"
    assert cleanup_ozon_title(text) == "Моменты счастья в искусстве. Воспевание жизни"
