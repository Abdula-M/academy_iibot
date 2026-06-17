import makeWASocket, {
    DisconnectReason,
    useMultiFileAuthState,
    makeCacheableSignalKeyStore,
    downloadMediaMessage,
    WASocket,
    proto,
    fetchLatestBaileysVersion
} from '@whiskeysockets/baileys';
import { Boom } from '@hapi/boom';
import express, { Request, Response } from 'express';
import axios from 'axios';
import fs from 'fs';
import path from 'path';
import pino from 'pino';

// ── Конфигурация ─────────────────────────────────────────────
const app = express();
app.use(express.json());

const FASTAPI_WEBHOOK_URL = process.env.WEBHOOK_URL || 'http://localhost:8000/api/whatsapp/webhook';
const PORT = process.env.PORT || 3000;
const AUTH_DIR = path.join(process.cwd(), '.baileys_auth');

// Тихий логгер для Baileys (по умолчанию он очень шумный)
const logger = pino({ level: process.env.LOG_LEVEL || 'silent' });

// ── Состояние ────────────────────────────────────────────────
let currentStatus = 'STARTING';
let currentQR = '';
let sock: WASocket | null = null;
let reconnectAttempts = 0;

// ── Очистка сессии ───────────────────────────────────────────
function clearSessionData(): void {
    try {
        if (fs.existsSync(AUTH_DIR)) {
            const files = fs.readdirSync(AUTH_DIR);
            for (const file of files) {
                fs.rmSync(path.join(AUTH_DIR, file), { recursive: true, force: true });
            }
            console.log('Папка сессии очищена:', AUTH_DIR);
        }
    } catch (err) {
        console.error('Ошибка при очистке папки сессии:', err);
    }
}

// ── Определение MIME-типа по расширению ──────────────────────
function getMimeType(filePath: string): string {
    const ext = path.extname(filePath).toLowerCase();
    const mimeMap: Record<string, string> = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.mp4': 'video/mp4',
        '.mp3': 'audio/mpeg',
        '.ogg': 'audio/ogg',
        '.pdf': 'application/pdf',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    };
    return mimeMap[ext] || 'application/octet-stream';
}

// ── Проверка: является ли файл изображением ──────────────────
function isImageFile(filePath: string): boolean {
    const ext = path.extname(filePath).toLowerCase();
    return ['.jpg', '.jpeg', '.png', '.gif', '.webp'].includes(ext);
}

// ── Основная функция подключения к WhatsApp ──────────────────
async function startWhatsApp(): Promise<void> {
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version } = await fetchLatestBaileysVersion();
    console.log(`Используем WA версию: ${version.join('.')}`);

    sock = makeWASocket({
        version,
        auth: {
            creds: state.creds,
            keys: makeCacheableSignalKeyStore(state.keys, logger)
        },
        logger,
        browser: ['Ubuntu', 'Chrome', '120.0.0'],
        generateHighQualityLinkPreview: false,
    });

    // ── Сохраняем credentials при обновлении ──────────────────
    sock.ev.on('creds.update', saveCreds);

    // ── Обработка состояния подключения ───────────────────────
    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            console.log('Новый QR-код сгенерирован');
            currentStatus = 'QR_READY';
            currentQR = qr;
            // Выводим QR в терминал для удобства
            try {
                // eslint-disable-next-line @typescript-eslint/no-var-requires
                const qrTerminal = require('qrcode-terminal');
                qrTerminal.generate(qr, { small: true });
            } catch (e) {
                console.log('QR строка (для дашборда):', qr.substring(0, 50) + '...');
            }
        }

        if (connection === 'open') {
            console.log('WhatsApp клиент успешно запущен и готов к работе!');
            currentStatus = 'READY';
            currentQR = '';
            reconnectAttempts = 0;
        }

        if (connection === 'close') {
            const statusCode = (lastDisconnect?.error as Boom)?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;

            console.log(`Соединение закрыто. Код: ${statusCode}. Переподключение: ${shouldReconnect}`);

            if (statusCode === DisconnectReason.loggedOut) {
                currentStatus = 'DISCONNECTED';
                currentQR = '';
                clearSessionData();
                console.log('Пользователь вышел, сессия очищена. Перезапуск...');
                process.exit(0);
            }

            if (shouldReconnect) {
                reconnectAttempts++;
                if (reconnectAttempts > 10) {
                    console.error('Слишком много неудачных попыток переподключения. Выход для перезапуска Docker-контейнера...');
                    process.exit(1);
                }
                currentStatus = 'RECONNECTING';
                console.log(`Переподключение к WhatsApp через 3 секунды (попытка ${reconnectAttempts})...`);
                await new Promise(resolve => setTimeout(resolve, 3000));
                await startWhatsApp();
            }
        }
    });

    // ── Обработка входящих сообщений ──────────────────────────
    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        // Обрабатываем только новые сообщения (не историю)
        if (type !== 'notify') return;

        for (const msg of messages) {
            // Пропускаем свои исходящие
            if (msg.key.fromMe) continue;

            const from = msg.key.remoteJid;
            if (!from) continue;

            // Игнорируем старые сообщения (старше 5 минут)
            // Это предотвращает спам вебхуками, если бот был оффлайн и накопил очередь
            const msgTimestamp = Number(msg.messageTimestamp);
            if (msgTimestamp) {
                const now = Math.floor(Date.now() / 1000);
                if (now - msgTimestamp > 300) {
                    console.log(`[DEBUG] Пропущено старое сообщение от ${from} (возраст: ${now - msgTimestamp} сек)`);
                    continue;
                }
            }

            // Извлекаем текст из разных типов сообщений
            const messageContent = msg.message;
            if (!messageContent) continue;

            const text =
                messageContent.conversation ||
                messageContent.extendedTextMessage?.text ||
                messageContent.imageMessage?.caption ||
                messageContent.videoMessage?.caption ||
                '';

            const msgType = Object.keys(messageContent).filter(k => k !== 'messageContextInfo')[0] || 'unknown';
            console.log(`[DEBUG] Входящее сообщение от ${from}: ${text.substring(0, 50)} (type: ${msgType})`);

            // Игнорируем группы и статусы
            if (from.endsWith('@g.us') || from === 'status@broadcast') {
                console.log(`[DEBUG] Сообщение проигнорировано (status или группа)`);
                continue;
            }
            try {
                // Отмечаем сообщение как прочитанное (синие галочки)
                await sock!.readMessages([msg.key]);
            } catch (e) {
                // Не критично если не удалось отметить
            }

            try {
                // Имя отправителя
                const senderName = msg.pushName || undefined;

                // Обрабатываем аудио/голосовые сообщения
                let audioBase64: string | undefined;
                if (messageContent.audioMessage) {
                    try {
                        const buffer = await downloadMediaMessage(
                            msg,
                            'buffer',
                            {},
                            {
                                logger,
                                reuploadRequest: sock!.updateMediaMessage
                            }
                        );
                        audioBase64 = (buffer as Buffer).toString('base64');
                    } catch (e) {
                        console.error('Ошибка загрузки аудио:', e);
                    }
                }

                // Отправляем вебхук в FastAPI (тот же формат, что был раньше)
                await axios.post(FASTAPI_WEBHOOK_URL, {
                    chat_id: from,
                    text,
                    sender_name: senderName,
                    audio_base64: audioBase64
                }, { timeout: 30000 });

            } catch (error) {
                console.error('Ошибка при отправке вебхука в FastAPI:', error);
            }
        }
    });

    console.log('Запуск WhatsApp клиента...');
}

// ── Эндпоинт: отправка сообщений ─────────────────────────────
app.post('/send', async (req: Request, res: Response) => {
    try {
        if (currentStatus !== 'READY') {
            return res.status(503).json({ error: 'WhatsApp client is not ready' });
        }

        if (!sock) {
            return res.status(503).json({ error: 'WhatsApp socket is not initialized' });
        }

        const { chat_id, text, photo_path, media_path } = req.body;

        if (!chat_id || !text) {
            return res.status(400).json({ error: 'chat_id and text are required' });
        }

        const targetMedia = media_path || photo_path;
        console.log(`Received request to send message. targetMedia: ${targetMedia}`);

        // Имитируем набор текста / запись для реалистичности
        try {
            await sock.sendPresenceUpdate('composing', chat_id);
            await new Promise(resolve => setTimeout(resolve, 1500));
        } catch (e) { /* ignore */ }

        if (targetMedia && fs.existsSync(targetMedia)) {
            try {
                const mimetype = getMimeType(targetMedia);
                const isImage = isImageFile(targetMedia);
                const isAudio = targetMedia.toLowerCase().endsWith('.ogg') || targetMedia.toLowerCase().endsWith('.mp3');

                if (isImage) {
                    // Отправляем как изображение с подписью
                    await sock.sendMessage(chat_id, {
                        image: { url: targetMedia },
                        caption: text
                    });
                } else if (isAudio) {
                    // Отправляем как голосовое сообщение (Voice Note)
                    await sock.sendPresenceUpdate('recording', chat_id);
                    await sock.sendMessage(chat_id, {
                        audio: { url: targetMedia },
                        mimetype: 'audio/ogg; codecs=opus',
                        ptt: true
                    });
                    if (text && text.trim() !== '') {
                        await sock.sendMessage(chat_id, { text });
                    }
                } else {
                    // Отправляем как документ
                    await sock.sendMessage(chat_id, {
                        document: { url: targetMedia },
                        mimetype,
                        fileName: path.basename(targetMedia),
                        caption: text
                    });
                }
                console.log('Message with media sent successfully.');
            } catch (mediaError) {
                console.error(`Не удалось отправить медиа ${targetMedia}:`, mediaError);
                // Если медиа не удалось — отправляем хотя бы текст
                await sock.sendMessage(chat_id, { text });
                console.log('Fallback: sent text only.');
            }
        } else {
            await sock.sendMessage(chat_id, { text });
            console.log('Message (text only) sent successfully.');
        }

        try {
            await sock.sendPresenceUpdate('paused', chat_id);
        } catch (e) { /* ignore */ }

        res.json({ success: true });
    } catch (error) {
        console.error('Ошибка при отправке сообщения в WhatsApp:', error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

// ── Эндпоинт: статус и QR-код ────────────────────────────────
app.get('/status', (_req: Request, res: Response) => {
    res.json({
        status: currentStatus,
        qr: currentQR
    });
});

// ── Эндпоинт: принудительный выход ───────────────────────────
app.post('/logout', async (_req: Request, res: Response) => {
    try {
        console.log('Запрошен выход (отвязка) WhatsApp...');
        currentStatus = 'STARTING';
        currentQR = '';

        if (sock) {
            try { await sock.logout(); } catch (e) { /* ignore */ }
            try { sock.end(undefined); } catch (e) { /* ignore */ }
        }

        clearSessionData();
        res.json({ success: true });

        setTimeout(() => {
            console.log('Перезапуск контейнера после принудительной отвязки...');
            process.exit(0);
        }, 1000);
    } catch (error) {
        console.error('Ошибка при отвязке WhatsApp:', error);
        res.status(500).json({ error: 'Failed to logout' });
    }
});

// ── Запуск ────────────────────────────────────────────────────
app.listen(PORT, () => {
    console.log(`Express сервер запущен на порту ${PORT}`);
    startWhatsApp().catch((err) => {
        console.error('Ошибка запуска WhatsApp:', err);
        process.exit(1);
    });
});

// ── Обработка необработанных ошибок ──────────────────────────
process.on('unhandledRejection', (reason, promise) => {
    console.error('Unhandled Rejection at:', promise, 'reason:', reason);
});

process.on('uncaughtException', (err) => {
    console.error('Uncaught Exception:', err);
    process.exit(1);
});

// ── Graceful shutdown ────────────────────────────────────────
process.on('SIGTERM', async () => {
    console.log('SIGTERM: завершение работы...');
    try {
        if (sock) { sock.end(undefined); }
    } catch (e) { /* ignore */ }
    process.exit(0);
});

process.on('SIGINT', async () => {
    console.log('SIGINT: завершение работы...');
    try {
        if (sock) { sock.end(undefined); }
    } catch (e) { /* ignore */ }
    process.exit(0);
});
