import { useState, useEffect } from 'react';
import { apiFetch } from '../../shared/api';
import type { Message } from '../../shared/types';

export const useChat = (telegramId: number | null) => {
    const [messages, setMessages] = useState<Message[]>([]);
    const [loading, setLoading] = useState(false);

    const loadMessages = async () => {
        if (!telegramId) return;
        setLoading(true);
        try {
            const data = await apiFetch<Message[]>(`/messages/${telegramId}`);
            setMessages(data);
        } catch (err) {
            console.error('Ошибка загрузки сообщений', err);
        } finally {
            setLoading(false);
        }
    };

    const sendMessage = async (text: string) => {
        if (!telegramId) return;
        try {
            await apiFetch(`/messages/${telegramId}/reply`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
            });
            await loadMessages();
        } catch (err) {
            console.error('Ошибка отправки сообщения', err);
            throw err;
        }
    };

    useEffect(() => {
        loadMessages();
    }, [telegramId]);

    return { messages, loading, reloadMessages: loadMessages, sendMessage };
};