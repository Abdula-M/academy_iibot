from __future__ import annotations

import asyncio
import tempfile
import unittest
import json
import struct
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from voice_service.audio import pcm16_rms, pcm16_to_ulaw, ulaw_to_pcm16
from voice_service.config import VoiceSettings
from voice_service.knowledge import VoiceKnowledgeBase
from voice_service.main import create_app
from voice_service.session import MemorySessionStore
from voice_service.telephony import parse_asterisk_control


class RecordingAgent:
    mode = "deepseek"

    def __init__(self) -> None:
        self.calls = 0

    async def reply(self, user_message, context, history) -> str:
        del user_message, context, history
        self.calls += 1
        return "Ответ внешнего ИИ."

    async def close(self) -> None:
        return None


class SlowRecordingAgent(RecordingAgent):
    async def reply(self, user_message, context, history) -> str:
        await asyncio.sleep(0.25)
        return await super().reply(user_message, context, history)


class VoiceAudioTests(unittest.TestCase):
    def test_ulaw_roundtrip_preserves_frame_and_signal(self) -> None:
        pcm = b"".join(struct.pack("<h", 8_000) for _ in range(160))

        encoded = pcm16_to_ulaw(pcm)
        decoded = ulaw_to_pcm16(encoded)

        self.assertEqual(len(encoded), 160)
        self.assertEqual(len(decoded), 320)
        self.assertGreater(pcm16_rms(decoded), 7_000)

    def test_asterisk_control_supports_json_and_plain_text(self) -> None:
        json_event, json_format = parse_asterisk_control(
            '{"event":"MEDIA_START","format":"ulaw"}',
        )
        plain_event, plain_format = parse_asterisk_control(
            "MEDIA_START format:ulaw optimal_frame_size:160",
        )

        self.assertEqual(json_format, "json")
        self.assertEqual(json_event["format"], "ulaw")
        self.assertEqual(plain_format, "plain-text")
        self.assertEqual(plain_event["optimal_frame_size"], "160")


class VoiceKnowledgeBaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.knowledge_path = Path(self.temp_dir.name) / "knowledge.txt"
        self.knowledge_path.write_text(
            "ОБЩАЯ ИНФОРМАЦИЯ\n"
            "• Адрес: проспект Гамидова, 18м\n"
            "\n"
            "НАПРАВЛЕНИЯ ОБУЧЕНИЯ\n"
            "1. Сестринское дело (Код: 34.02.01)\n"
            "• Обучение на базе 9 классов: 2 года 10 месяцев, 120 000 рублей.\n"
            "• Обучение на базе 11 классов: 1 год 10 месяцев, 120 000 рублей.\n"
            "\n"
            "ВАКАНСИИ И ТРУДОУСТРОЙСТВО В АКАДЕМИИ\n"
            "• Для анкеты укажите адрес места проживания.\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_search_returns_relevant_specialty(self) -> None:
        knowledge = VoiceKnowledgeBase(self.knowledge_path)

        results = knowledge.search("стоимость сестринского дела после 11 класса")

        self.assertTrue(results)
        self.assertIn("120 000", results[0].text)
        self.assertIn("НАПРАВЛЕНИЯ ОБУЧЕНИЯ", results[0].section)

    def test_contact_address_outranks_vacancy_address(self) -> None:
        knowledge = VoiceKnowledgeBase(self.knowledge_path)

        results = knowledge.search("Какой адрес академии?")

        self.assertTrue(results)
        self.assertIn("Гамидова", results[0].text)

    def test_missing_file_is_reported_as_not_ready(self) -> None:
        knowledge = VoiceKnowledgeBase(Path(self.temp_dir.name) / "missing.txt")

        self.assertFalse(knowledge.ready)
        self.assertEqual(knowledge.chunk_count, 0)


class VoiceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.knowledge_path = Path(self.temp_dir.name) / "knowledge.txt"
        self.knowledge_path.write_text(
            "ОБЩАЯ ИНФОРМАЦИЯ И КОНТАКТЫ\n"
            "• Адрес: пр. Гамидова, 18м\n"
            "• Телефон приемной комиссии: 8 992 900 00 54\n"
            "\n"
            "НАПРАВЛЕНИЯ ОБУЧЕНИЯ\n"
            "1. Сестринское дело (Код: 34.02.01)\n"
            "• Обучение на базе 9 классов: 2 года 10 месяцев, стоимость 120 000 рублей.\n"
            "• Обучение на базе 11 классов: 1 год 10 месяцев, стоимость 120 000 рублей.\n"
            "\n"
            "АДМИНИСТРАТИВНАЯ ИНФОРМАЦИЯ\n"
            "Необходимые документы для поступления:\n"
            "• Паспорт.\n"
            "• СНИЛС и ИНН.\n"
            "• Аттестат или диплом.\n"
            "• Шесть фотографий 3х4.\n"
            "• Медицинская справка 086-У.\n",
            encoding="utf-8",
        )
        settings = VoiceSettings(
            knowledge_file=self.knowledge_path,
            llm_provider="local",
            session_backend="memory",
        )
        self.app = create_app(
            settings,
            sessions=MemorySessionStore(ttl_seconds=300),
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_health_reports_isolated_test_mode(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "healthy")
        self.assertEqual(payload["llm_provider"], "local-test")
        self.assertFalse(payload["telephony_ready"])

    def test_simulation_uses_shared_knowledge(self) -> None:
        response = self.client.post(
            "/api/voice/simulate",
            json={"call_id": "test-call", "message": "Какой адрес академии?"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("Гамидова", payload["answer"])
        self.assertFalse(payload["transfer_requested"])

    def test_operator_request_bypasses_llm(self) -> None:
        response = self.client.post(
            "/api/voice/simulate",
            json={"call_id": "transfer-call", "message": "Соедините с оператором"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["transfer_requested"])

    def test_simulation_respects_requested_education_base(self) -> None:
        response = self.client.post(
            "/api/voice/simulate",
            json={
                "call_id": "cost-call",
                "message": "Сколько стоит сестринское дело после 11 класса?",
            },
        )

        self.assertEqual(response.status_code, 200)
        answer = response.json()["answer"]
        self.assertIn("базе 11 классов", answer)
        self.assertIn("1 год 10 месяцев", answer)

    def test_unambiguous_address_skips_external_llm(self) -> None:
        agent = RecordingAgent()
        settings = VoiceSettings(
            knowledge_file=self.knowledge_path,
            llm_provider="local",
            session_backend="memory",
        )
        app = create_app(
            settings,
            agent=agent,
            sessions=MemorySessionStore(ttl_seconds=300),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/voice/simulate",
                json={"call_id": "fast-address", "message": "Какой адрес колледжа?"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Гамидова", response.json()["answer"])
        self.assertEqual(agent.calls, 0)

    def test_ambiguous_question_still_uses_external_llm(self) -> None:
        agent = RecordingAgent()
        settings = VoiceSettings(
            knowledge_file=self.knowledge_path,
            llm_provider="local",
            session_backend="memory",
        )
        app = create_app(
            settings,
            agent=agent,
            sessions=MemorySessionStore(ttl_seconds=300),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/voice/simulate",
                json={"call_id": "complex", "message": "Расскажите про обучение"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Ответ внешнего ИИ.")
        self.assertEqual(agent.calls, 1)

    def test_document_list_skips_external_llm(self) -> None:
        agent = RecordingAgent()
        settings = VoiceSettings(
            knowledge_file=self.knowledge_path,
            llm_provider="local",
            session_backend="memory",
        )
        app = create_app(
            settings,
            agent=agent,
            sessions=MemorySessionStore(ttl_seconds=300),
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/voice/simulate",
                json={"call_id": "fast-documents", "message": "Какие нужны документы?"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Паспорт", response.json()["answer"])
        self.assertEqual(agent.calls, 0)


class VoiceTelephonyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.knowledge_path = Path(self.temp_dir.name) / "knowledge.txt"
        self.knowledge_path.write_text(
            "ОБЩАЯ ИНФОРМАЦИЯ И КОНТАКТЫ\n"
            "• Адрес: пр. Гамидова, 18м\n",
            encoding="utf-8",
        )
        self.settings = VoiceSettings(
            knowledge_file=self.knowledge_path,
            llm_provider="local",
            session_backend="memory",
            speech_provider="mock",
            telephony_enabled=True,
            telephony_token="test-secret-that-is-not-used-in-production",
            telephony_test_mode=True,
        )
        self.app = create_app(
            self.settings,
            sessions=MemorySessionStore(ttl_seconds=300),
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_websocket_rejects_missing_secret(self) -> None:
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect("/ws/telephony/asterisk"):
                pass

        self.assertEqual(caught.exception.code, 1008)

    def test_mock_call_barge_in_and_operator_handoff(self) -> None:
        url = (
            "/ws/telephony/asterisk"
            "?token=test-secret-that-is-not-used-in-production"
        )
        with self.client.websocket_connect(url) as websocket:
            websocket.send_json(
                {
                    "event": "MEDIA_START",
                    "connection_id": "test-call-id",
                    "format": "ulaw",
                    "optimal_frame_size": 160,
                    "ptime": 20,
                },
            )
            self.assertEqual(
                self._next_command(websocket, "START_MEDIA_BUFFERING")["command"],
                "START_MEDIA_BUFFERING",
            )

            loud_pcm = b"".join(struct.pack("<h", 10_000) for _ in range(160))
            websocket.send_bytes(pcm16_to_ulaw(loud_pcm))
            self.assertEqual(
                self._next_command(websocket, "FLUSH_MEDIA")["command"],
                "FLUSH_MEDIA",
            )

            websocket.send_json(
                {"event": "TEST_TRANSCRIPT", "text": "Соедините с оператором"},
            )
            mark_command = self._next_command(websocket, "MARK_MEDIA")
            mark = mark_command["correlation_id"]
            websocket.send_json(
                {"event": "MEDIA_MARK_PROCESSED", "correlation_id": mark},
            )
            self.assertEqual(
                self._next_command(websocket, "HANGUP")["command"],
                "HANGUP",
            )

    @staticmethod
    def _next_command(websocket, expected: str) -> dict[str, str]:
        for _ in range(12):
            message = websocket.receive()
            text = message.get("text")
            if not text:
                continue
            payload = json.loads(text)
            if payload.get("command") == expected:
                return payload
        raise AssertionError(f"Команда {expected} не получена")


class VoiceBrowserTestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.knowledge_path = Path(self.temp_dir.name) / "knowledge.txt"
        self.knowledge_path.write_text(
            "ОБЩАЯ ИНФОРМАЦИЯ И КОНТАКТЫ\n"
            "• Адрес: пр. Гамидова, 18м\n",
            encoding="utf-8",
        )
        settings = VoiceSettings(
            knowledge_file=self.knowledge_path,
            llm_provider="local",
            session_backend="memory",
            speech_provider="mock",
            telephony_test_mode=True,
            browser_test_enabled=True,
            browser_test_token="browser-test-secret",
        )
        self.app = create_app(
            settings,
            sessions=MemorySessionStore(ttl_seconds=300),
        )
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_page_requires_secret(self) -> None:
        self.assertEqual(self.client.get("/test-call").status_code, 404)

        response = self.client.get(
            "/test-call",
            params={"token": "browser-test-secret"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Тестовый звонок", response.text)

    def test_mock_browser_call_returns_text_and_audio(self) -> None:
        with self.client.websocket_connect(
            "/ws/test-call?token=browser-test-secret",
        ) as websocket:
            ready = websocket.receive_json()
            self.assertEqual(ready["type"], "ready")
            self.assertEqual(ready["sample_rate"], 8000)

            websocket.send_json(
                {"type": "test_transcript", "text": "Какой адрес колледжа?"},
            )
            answer_event = self._next_event(websocket, "answer")
            self.assertIn("Гамидова", answer_event["text"])

            self._next_event(websocket, "audio_start")
            audio_message = websocket.receive()
            self.assertTrue(audio_message.get("bytes"))
            self._next_event(websocket, "audio_end")

    def test_slow_answer_gets_short_spoken_acknowledgement(self) -> None:
        settings = VoiceSettings(
            knowledge_file=self.knowledge_path,
            llm_provider="local",
            session_backend="memory",
            speech_provider="mock",
            telephony_test_mode=True,
            browser_test_enabled=True,
            browser_test_token="browser-test-secret",
            thinking_prompt_delay_seconds=0.2,
        )
        app = create_app(
            settings,
            agent=SlowRecordingAgent(),
            sessions=MemorySessionStore(ttl_seconds=300),
        )
        with TestClient(app) as client:
            with client.websocket_connect(
                "/ws/test-call?token=browser-test-secret",
            ) as websocket:
                self.assertEqual(websocket.receive_json()["type"], "ready")
                self._next_event(websocket, "audio_end")
                websocket.send_json({"type": "audio_played"})
                websocket.send_json(
                    {"type": "test_transcript", "text": "Расскажите про обучение"},
                )
                acknowledgement = self._next_event(websocket, "audio_start")
                self.assertIn(
                    acknowledgement["text"],
                    {
                        "Сейчас уточню.",
                        "Одну секунду, пожалуйста.",
                        "Секунду, проверяю.",
                    },
                )
                answer = self._next_event(websocket, "answer")
                self.assertEqual(answer["text"], "Ответ внешнего ИИ.")

    @staticmethod
    def _next_event(websocket, expected: str) -> dict[str, object]:
        for _ in range(12):
            message = websocket.receive()
            text = message.get("text")
            if not text:
                continue
            payload = json.loads(text)
            if payload.get("type") == expected:
                return payload
        raise AssertionError(f"Событие {expected} не получено")


if __name__ == "__main__":
    unittest.main()
