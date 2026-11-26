import unittest

from aisupport_ml.commerce.routing import choose_first_route


class FirstRouteTests(unittest.TestCase):
    def test_fixed_decision_priority_and_model_fallback(self):
        names = {"netdesk mail", "netdesk", "astra linux"}
        cases = (
            ("Какую версию NetDesk Mail лучше выбрать для офиса?", None, 0.0, "find_named_product"),
            ("NetDesk Mail", None, 0.0, "find_named_product"),
            ("Подскажите, какую версию Астра Линукс можно поставить?", "answer_product_question", .91, "find_named_product"),
            ("Какую версию NetDesk Mail можно приобрести для переговорных?", None, 0.0, "find_named_product"),
            ("Мне нужен NetDesk Mail. Есть ли возможность заказать?", "handoff", .98, "answer_product_question"),
            ("Можете помочь со спецификацией?", "handoff", .99, "clarify"),
            ("Хотим защитить входящие письма на 50 сотрудников. Что купить?", None, 0.0, "recommend_by_need"),
            ("Не знаю, что нужно, но хотим защитить почту и файлы на 50 сотрудников", None, 0.0, "recommend_by_need"),
            ("Нужна лицензия, чтобы работали таблицы и презентации. Какую выбрать?", None, 0.0, "recommend_by_need"),
            ("Сколько стоит лицензия на одного пользователя?", "answer_product_question", .78, "clarify"),
            ("Переключите меня на менеджера", "answer_product_question", .8, "handoff"),
            ("Возможна персональная скидка на NetDesk Mail?", None, 0.0, "handoff"),
            ("Не переключайте к оператору. NetDesk Mail какая цена?", "handoff", .9, "answer_product_question"),
            ("Как подключить оператора к системе?", "handoff", .9, "clarify"),
            ("Дайте доступ оператору в программе", "handoff", .9, "clarify"),
            ("Инструмент для работы с договорами", "recommend_by_need", .29, "clarify"),
            ("Инструмент для работы с договорами", "recommend_by_need", .6, "recommend_by_need"),
        )
        for text, hint, score, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(choose_first_route(text, matches_catalog=names.__contains__,
                                                    suggested_route=hint, score=score), expected)
