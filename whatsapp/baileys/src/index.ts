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

// ── Очистка сессии ───────────────────────────────────────────
function clearSessionData(): void {
    try {
        if (fs.existsSync(AUTH_DIR)) {
            fs.rmSync(AUTH_DIR, { recursive: true, force: true });
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

    sock = makeWASocket({
        auth: {
            creds: state.creds,
            keys: makeCacheableSignalKeyStore(state.keys, logger)
        },
        printQRInTerminal: true,
        logger,
        browser: ['Academy Bot', 'Chrome', '120.0.0'],
        generateHighQualityLinkPreview: false,
    });

    // ── Сохраняем credentials при обновлении ──────────────────
    sock.ev.on('creds.update', saveCreds);

    // ── Обработка состояния подключения ───────────────────────
    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            console.log('Новый QR-код сгенерирован и отправлен на фронтенд');
            currentStatus = 'QR_READY';
            currentQR = qr;
        }

        if (connection === 'open') {
            console.log('WhatsApp клиент успешно запущен и готов к работе!');
            currentStatus = 'READY';
            currentQR = '';
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
                currentStatus = 'RECONNECTING';
                console.log('Переподключение к WhatsApp...');
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

        if (targetMedia && fs.existsSync(targetMedia)) {
            try {
                const mimetype = getMimeType(targetMedia);
                const isPdf = targetMedia.toLowerCase().endsWith('.pdf');
                const isImage = isImageFile(targetMedia);

                if (isImage) {
                    // Отправляем как изображение с подписью
                    await sock.sendMessage(chat_id, {
                        image: { url: targetMedia },
                        caption: text
                    });
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
