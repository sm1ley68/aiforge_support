import importlib.util
import json
import unittest

from aisupport_ml.privacy import PersonalSpan, mask_text, prepare_llm_input


def no_entities(_text):
    return ()


class PrivacyTests(unittest.TestCase):
    def test_masks_identifiers_and_keeps_catalog_values(self):
        text = (
            "ФИО: Иван Петров; телефон +7 (900) 111-22-33; почта demo@example.invalid; "
            "ИНН 123456789012; СНИЛС 123-456-789 01; паспорт: 45 00 123456; "
            "номер заказа ORDER-456; никнейм: @demo_name; IP 192.0.2.17. "
            "Нужны Windows Server 2019, 10 лицензий и артикул 19579."
        )
        result = mask_text(text, entity_detector=no_entities)
        expected = {
            "Иван Петров": "ФИО", "+7 (900) 111-22-33": "ТЕЛЕФОН", "demo@example.invalid": "ПОЧТА",
            "123456789012": "ИНН", "123-456-789 01": "СНИЛС", "45 00 123456": "ПАСПОРТ",
            "ORDER-456": "ЗАКАЗ", "@demo_name": "АККАУНТ", "192.0.2.17": "IP",
        }
        for original, label in expected.items():
            with self.subTest(label=label):
                self.assertNotIn(original, result.text)
                self.assertIn(f"[{label}]", result.text)
        self.assertIn("Windows Server 2019, 10 лицензий и артикул 19579", result.text)

    def test_masks_birth_address_payment_and_device_data(self):
        text = (
            "Дата рождения: 01.02.1990; адрес: ул. Тестовая, 27, кв. 112; "
            "номер карты 4111 1111 1111 1111; device_id=unit-test-secret; IPv6 2001:db8::1; "
            "координаты: 55.7522, 37.6156; полис ОМС 1234567890123456."
        )
        result = mask_text(text, entity_detector=no_entities)
        self.assertTrue({"birth", "address", "payment", "device", "ip", "location", "document"} <= set(result.categories))
        for original in ("01.02.1990", "Тестовая", "4111 1111 1111 1111", "unit-test-secret", "2001:db8::1",
                         "55.7522", "1234567890123456"):
            self.assertNotIn(original, result.text)

    def test_normalizes_obfuscated_identifiers(self):
        result = mask_text("фио иван петров, почта de\u200bmo@example.invalid; +７９００１１１１２３４",
                           entity_detector=no_entities)
        self.assertNotIn("demo@", result.text)
        self.assertNotIn("иван петров", result.text)
        self.assertIn("[ПОЧТА]", result.text)
        self.assertIn("[ТЕЛЕФОН]", result.text)

    def test_local_entity_spans_merge_with_format_rules(self):
        text = "Николай Иванов, demo@example.invalid, Windows 11"
        result = mask_text(text, entity_detector=lambda value: (PersonalSpan(0, value.index(","), "name"),))
        self.assertEqual(result.text, "[ФИО], [ПОЧТА], Windows 11")
        self.assertNotIn("Windows 11", repr(result))

    def test_model_payload_is_constructed_only_from_approved_fields(self):
        result = prepare_llm_input(
            "ФИО: Иван Петров. Нужно локальное резервное копирование для 10 ПК с Windows 11, "
            "локально. В бюджете есть закрытая сумма 75000 рублей.",
            entity_detector=no_entities,
        )
        self.assertIn("[ФИО]", result.masked_message)
        self.assertEqual(result.model_payload, {
            "task": "backup", "device_count": 10, "platform": "windows_11", "deployment": "local",
        })
        self.assertNotIn("75000", json.dumps(result.model_payload))

    def test_unknown_free_text_cannot_leak_through_the_model_payload(self):
        text = "Внутренний код АЛЬФА-БЕТА. Нужны 10 ПК с Windows 11."
        result = prepare_llm_input(text, entity_detector=no_entities)
        self.assertIn("АЛЬФА-БЕТА", result.masked_message)
        self.assertEqual(result.model_payload, {"device_count": 10, "platform": "windows_11"})

    def test_separate_passport_parts_and_issue_date_are_masked(self):
        result = mask_text("Серия паспорта 4500, номер паспорта 123456, дата выдачи 21.04.2021.",
                           entity_detector=no_entities)
        self.assertEqual(result.text, "Серия паспорта [ПАСПОРТ], номер паспорта [ПАСПОРТ], дата выдачи [ДОКУМЕНТ].")

    def test_history_and_saved_state_are_screened_and_never_copied(self):
        result = prepare_llm_input(
            "А сколько стоит?",
            history=["Моя почта old-user@example.invalid"],
            selection={"goal": "резервное копирование", "file_os": "Windows 11",
                       "notes": ["ещё одна почта old-state@example.invalid"], "nodes": 8},
            entity_detector=no_entities,
        )
        self.assertIn("email", result.categories)
        self.assertEqual(result.model_payload, {
            "task": "backup", "platform": "windows_11", "device_count": 8, "fact": "price",
        })
        self.assertNotIn("example.invalid", json.dumps(result.model_payload))

    def test_sensitive_data_blocks_every_source(self):
        for extra in ({}, {"history": ["У меня диабет"]}, {"selection": {"notes": ["Сведения о судимости"]}}):
            text = "10 ПК с Windows 11" if extra else "У меня диагноз; нужно ПО для 10 ПК с Windows 11"
            with self.subTest(source=tuple(extra)):
                result = prepare_llm_input(text, entity_detector=no_entities, **extra)
                self.assertIsNone(result.model_payload)
                self.assertTrue({"health", "sensitive_context"} & set(result.categories))
        attachment = prepare_llm_input("10 ПК с Windows 11", has_attachments=True, entity_detector=no_entities)
        self.assertIsNone(attachment.model_payload)
        self.assertIn("attachment", attachment.categories)

    def test_invalid_inputs_and_detector_errors_block_calls(self):
        def failed_detector(_text):
            raise RuntimeError("internal example error")

        for options in ({"history": "not a list"}, {"selection": {"unknown": {"text": "nested"}}},
                        {"entity_detector": failed_detector}, {"history": ["brief"] * 513}):
            with self.subTest(options=tuple(options)):
                result = prepare_llm_input("10 ПК с Windows 11", **options)
                self.assertIsNone(result.model_payload)
        result = prepare_llm_input("10 ПК с Windows 11 demo@example.invalid", entity_detector=failed_detector)
        self.assertIn("[ПОЧТА]", result.masked_message)
        self.assertIn("entity_detector_unavailable", result.categories)
        self.assertNotIn("internal example error", repr(result))

    def test_old_history_is_screened_without_consuming_the_recent_window(self):
        history = [f"Техническое уточнение {index}" for index in range(24)]
        scanned = []

        def detect(text):
            scanned.append(text)
            return ()

        result = prepare_llm_input("10 ПК с Windows 11", history=history, entity_detector=detect)
        self.assertEqual(result.model_payload, {"platform": "windows_11", "device_count": 10})
        self.assertEqual(scanned, ["10 ПК с Windows 11", *history[-8:]])
        personal = prepare_llm_input("10 ПК с Windows 11", history=["Контакт demo@example.invalid", *history],
                                     entity_detector=no_entities)
        self.assertIn("email", personal.categories)
        sensitive = prepare_llm_input("10 ПК с Windows 11", history=["У меня диабет", *history],
                                      entity_detector=no_entities)
        self.assertIsNone(sensitive.model_payload)

    def test_unverified_catalog_reference_and_conflicts_block_calls(self):
        self.assertIsNone(prepare_llm_input("Сколько стоит артикул 12345?", entity_detector=no_entities).model_payload)
        reference = prepare_llm_input(
            "Уточните артикул 19579", entity_detector=no_entities,
            is_public_reference=lambda code: code == "19579",
        )
        self.assertEqual(reference.model_payload, {"catalog_reference": "19579"})
        for text in ("10 ПК или 20 ПК", "Windows 11 или Linux", "Просто хочу поговорить"):
            self.assertIsNone(prepare_llm_input(text, entity_detector=no_entities).model_payload)

    def test_new_task_does_not_inherit_old_requirements(self):
        result = prepare_llm_input(
            "Нужно резервное копирование на 10 ПК", selection={"goal": "защитить почту и файлы",
            "file_os": "Windows Server 2019", "deployment": "cloud", "nodes": 80},
            entity_detector=no_entities,
        )
        self.assertEqual(result.model_payload, {"task": "backup", "device_count": 10})

    @unittest.skipUnless(importlib.util.find_spec("natasha"), "requires the privacy extra")
    def test_natasha_recognizes_inflected_name_and_location_locally(self):
        result = prepare_llm_input("Синицыну Павлу Павловичу из Казани нужна лицензия для Windows Server 2019.")
        self.assertIn("name", result.categories)
        self.assertIn("location", result.categories)
        self.assertNotIn("Синицыну", result.masked_message)
        self.assertNotIn("Казани", result.masked_message)
        self.assertEqual(result.model_payload, {"platform": "windows_server_2019"})
