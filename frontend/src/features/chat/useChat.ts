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

    useEffect(() => {
        loadMessages();
    }, [telegramId]);

    return { messages, loading, reloadMessages: loadMessages };
};