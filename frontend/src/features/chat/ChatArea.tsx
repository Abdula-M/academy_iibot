import React, { useEffect, useRef, useCallback } from 'react';
import { getPlatformIcon } from '../../shared/ui/Icons';
import { formatTime, formatBotAnswer } from '../../shared/utils/date';
import type { User, Message } from '../../shared/types';

interface ChatAreaProps {
    selectedUser: User | null;
    messages: Message[];
    loading: boolean;
    loadingOlder: boolean;
    hasOlder: boolean;
    onBack: () => void;
    onLoadOlder: () => void;
}

const MessageBubble = React.memo<{
    msg: Message;
    showDate: boolean;
    displayDate: string;
    isFirstUnread: boolean;
}>(({ msg, showDate, displayDate, isFirstUnread }) => (
    <>
        {isFirstUnread && <div id="first-unread-message" />}
        {showDate && <div className="date-divider"><span>{displayDate}</span></div>}
        <div className="msg-wrapper user">
            <div className="msg-bubble">{msg.question}</div>
            <div className="msg-time">{formatTime(msg.created_at)}</div>
        </div>
        <div className="msg-wrapper bot">
            <div className="msg-bubble" dangerouslySetInnerHTML={{ __html: formatBotAnswer(msg.answer) }} />
            <div className="msg-time">Ассистент</div>
        </div>
    </>
));

MessageBubble.displayName = 'MessageBubble';

export const ChatArea = React.memo<ChatAreaProps>(({
    selectedUser,
    messages,
    loading,
    loadingOlder,
    hasOlder,
    onBack,
    onLoadOlder,
}) => {
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const chatContainerRef = useRef<HTMLDivElement>(null);
    const prevMessagesLenRef = useRef(0);

    // Скролл к непрочитанным или вниз при первой загрузке
    useEffect(() => {
        if (messages.length === 0) return;

        // Если подгрузили старые сообщения — не скроллить
        if (prevMessagesLenRef.current > 0 && messages.length > prevMessagesLenRef.current) {
            prevMessagesLenRef.current = messages.length;
            return;
        }

        prevMessagesLenRef.current = messages.length;

        if (selectedUser && selectedUser.msg_count > 0) {
            const firstUnreadEl = document.getElementById('first-unread-message');
            if (firstUnreadEl) {
                firstUnreadEl.scrollIntoView({ behavior: 'auto' });
                return;
            }
        }

        messagesEndRef.current?.scrollIntoView({ behavior: 'auto' });
    }, [messages, selectedUser]);

    // Подгрузка старых сообщений при скролле вверх
    const handleScroll = useCallback(() => {
        const container = chatContainerRef.current;
        if (!container || loadingOlder || !hasOlder) return;

        if (container.scrollTop < 100) {
            onLoadOlder();
        }
    }, [loadingOlder, hasOlder, onLoadOlder]);

    if (!selectedUser) {
        return (
            <div className="chat-area">
                <div className="empty-state">
                    <div className="icon">
                        <img src="/logo.png" alt="logo" style={{ width: 80, height: 80, borderRadius: 20, opacity: 0.5, filter: 'drop-shadow(0 0 20px rgba(59,130,246,0.3))' }} />
                    </div>
                    <div style={{ fontSize: 18, fontWeight: 500, marginBottom: 8, marginTop: 16 }}>Выберите диалог</div>
                    <div style={{ fontSize: 14 }}>чтобы просмотреть историю сообщений</div>
                </div>
            </div>
        );
    }

    const today = new Date().toDateString();
    const yesterday = new Date(Date.now() - 86400000).toDateString();

    return (
        <div className="chat-area">
            <div className="chat-header">
                <button className="mobile-back-btn" onClick={onBack}>‹</button>
                <div>
                    <div className="chat-header-title">
                        {getPlatformIcon(selectedUser.platform || 'telegram')}
                        <span style={{ marginLeft: 6 }}>@{selectedUser.username}</span>
                    </div>
                    <div className="chat-header-sub">{selectedUser.platform || 'telegram'} · ID: {selectedUser.telegram_id}</div>
                </div>
            </div>
            <div
                className="chat-messages"
                ref={chatContainerRef}
                onScroll={handleScroll}
            >
                {loadingOlder && (
                    <div style={{ padding: 12, textAlign: 'center', color: 'var(--text-dim)', fontSize: 12 }}>
                        Загрузка старых сообщений...
                    </div>
                )}
                {hasOlder && !loadingOlder && (
                    <div
                        style={{ padding: 8, textAlign: 'center', color: 'var(--text-dim)', fontSize: 12, cursor: 'pointer' }}
                        onClick={onLoadOlder}
                    >
                        ↑ Загрузить ещё
                    </div>
                )}
                {loading ? (
                    <div className="loading"><div className="spinner"></div></div>
                ) : messages.length === 0 ? (
                    <div className="empty-state">Нет сообщений</div>
                ) : (
                    messages.map((msg, idx) => {
                        const prevMsgDate = idx > 0 ? new Date(messages[idx - 1].created_at).toDateString() : null;
                        const msgDate = new Date(msg.created_at).toDateString();
                        const showDate = prevMsgDate !== msgDate;
                        let displayDate = new Date(msg.created_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
                        if (msgDate === today) displayDate = 'Сегодня';
                        else if (msgDate === yesterday) displayDate = 'Вчера';

                        const isFirstUnread = selectedUser.msg_count > 0 && idx === Math.max(0, messages.length - selectedUser.msg_count);

                        return (
                            <MessageBubble
                                key={msg.id}
                                msg={msg}
                                showDate={showDate}
                                displayDate={displayDate}
                                isFirstUnread={isFirstUnread}
                            />
                        );
                    })
                )}
                <div ref={messagesEndRef} />
            </div>
        </div>
    );
});

ChatArea.displayName = 'ChatArea';
