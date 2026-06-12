import React, { useState } from 'react';
import { useStats } from './features/stats/useStats';
import { useUsers } from './features/users/useUsers';
import { useChat } from './features/chat/useChat';
import { useVacancies } from './features/vacancy/useVacancies';
import { WhatsAppModal } from './features/whatsapp/WhatsAppModal';
import { VacancyModal } from './features/vacancy/VacancyModal';
import { getPlatformIcon } from './shared/ui/Icons';
import { formatDate, formatTime, formatBotAnswer } from './shared/utils/date';
import type { User, VacancyApplication } from './shared/types';

function App() {
    const [currentTab, setCurrentTab] = useState<'chat' | 'vacancy'>('chat');
    const [selectedUser, setSelectedUser] = useState<User | null>(null);
    const [isWaModalOpen, setIsWaModalOpen] = useState(false);
    const [selectedVacancy, setSelectedVacancy] = useState<VacancyApplication | null>(null);

    const { stats, lastUpdate, reloadStats } = useStats();
    const { users, reloadUsers } = useUsers();
    const { messages, loading: chatLoading, reloadMessages } = useChat(selectedUser ? selectedUser.telegram_id : null);
    const { vacancies, markAsRead } = useVacancies();

    const handleSelectUser = (user: User) => {
        setSelectedUser(user);
        reloadMessages().then(() => {
            reloadUsers();
        });
    };

    const handleOpenVacancy = (app: VacancyApplication) => {
        setSelectedVacancy(app);
        if (!app.is_read) {
            markAsRead(app.id).then(() => {
                reloadStats();
            });
        }
    };

    return (
        <div className="app-container" data-theme="dark">
            <header className="header">
                <div className="header-title">
                    <span style={{ fontSize: 28, marginRight: 8 }}>🌌</span>
                    AI Центр Диалогов
                </div>
                <div className="header-stats">
                    <div className="stat-card">
                        <div className="stat-label">Всего</div>
                        <div className="stat-value">{stats?.total_users || 0}</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">За сегодня</div>
                        <div className="stat-value">{stats?.today_users || 0}</div>
                    </div>
                    <div className="stat-card">
                        <div className="stat-label">Сообщений</div>
                        <div className="stat-value">{stats?.today_messages || 0}</div>
                    </div>
                    <div className="stat-card" style={{ background: 'rgba(255,255,255,0.02)', border: 'none', cursor: 'pointer' }} onClick={() => setIsWaModalOpen(true)}>
                        <div className="stat-label" style={{ color: '#34d399' }}>Настройки</div>
                        <div className="stat-value" style={{ fontSize: 13, marginTop: 4 }}>WhatsApp &nbsp;⚙️</div>
                    </div>
                </div>
            </header>

            <div className="tabs">
                <div className={`tab ${currentTab === 'chat' ? 'active' : ''}`} onClick={() => setCurrentTab('chat')}>
                    💬 Диалоги
                </div>
                <div className={`tab ${currentTab === 'vacancy' ? 'active' : ''}`} onClick={() => setCurrentTab('vacancy')}>
                    📋 Заявки 
                    {(stats?.unread_applications ?? 0) > 0 && (
                        <span className="badge" style={{ background: 'red', color: 'white', borderRadius: '50%', padding: '2px 6px', fontSize: 10, marginLeft: 4 }}>
                            {stats!.unread_applications}
                        </span>
                    )}
                </div>
                <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-dim)', alignSelf: 'center' }}>
                    {lastUpdate ? `Обновлено в ${lastUpdate}` : ''}
                </div>
            </div>

            <main className="main-content" style={{ display: currentTab === 'chat' ? 'flex' : 'none' }}>
                <aside className={`sidebar ${selectedUser ? 'mobile-hidden' : ''}`}>
                    <div className="search-bar">
                        <input type="text" placeholder="Поиск по диалогам..." />
                    </div>
                    <div className="users-list">
                        {users.length === 0 ? (
                            <div className="empty-state" style={{ padding: 20, fontSize: 13 }}>Нет данных</div>
                        ) : (
                            users.map(user => (
                                <div 
                                    key={user.telegram_id} 
                                    className={`user-item ${selectedUser?.telegram_id === user.telegram_id ? 'active' : ''}`}
                                    onClick={() => handleSelectUser(user)}
                                >
                                    <div className="user-header">
                                        <div className="user-name">
                                            {getPlatformIcon(user.platform || 'telegram')}
                                            @{user.username}
                                        </div>
                                        <div className="user-time">{formatDate(user.last_time)}</div>
                                    </div>
                                    <div className="user-preview">{user.last_question}</div>
                                    {user.msg_count > 0 && <div className="user-badge">{user.msg_count}</div>}
                                </div>
                            ))
                        )}
                    </div>
                </aside>
                
                <div className={`chat-area ${selectedUser ? 'mobile-active' : ''}`}>
                    {selectedUser ? (
                        <>
                            <div className="chat-header">
                                <button className="mobile-back-btn" onClick={() => setSelectedUser(null)}>‹</button>
                                <div>
                                    <div className="chat-header-title">
                                        {getPlatformIcon(selectedUser.platform || 'telegram')}
                                        <span style={{ marginLeft: 6 }}>@{selectedUser.username}</span>
                                    </div>
                                    <div className="chat-header-sub">{selectedUser.platform || 'telegram'} · ID: {selectedUser.telegram_id}</div>
                                </div>
                            </div>
                            <div className="chat-messages">
                                {chatLoading ? (
                                    <div className="loading"><div className="spinner"></div></div>
                                ) : messages.length === 0 ? (
                                    <div className="empty-state">Нет сообщений</div>
                                ) : (
                                    messages.map((msg, idx) => {
                                        const prevMsgDate = idx > 0 ? new Date(messages[idx - 1].created_at).toDateString() : null;
                                        const msgDate = new Date(msg.created_at).toDateString();
                                        const showDate = prevMsgDate !== msgDate;
                                        let displayDate = new Date(msg.created_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
                                        const today = new Date().toDateString();
                                        const yesterday = new Date(Date.now() - 86400000).toDateString();
                                        if (msgDate === today) displayDate = 'Сегодня';
                                        else if (msgDate === yesterday) displayDate = 'Вчера';

                                        return (
                                            <React.Fragment key={idx}>
                                                {showDate && <div className="date-divider"><span>{displayDate}</span></div>}
                                                <div className="msg-wrapper user">
                                                    <div className="msg-bubble">{msg.question}</div>
                                                    <div className="msg-time">{formatTime(msg.created_at)}</div>
                                                </div>
                                                <div className="msg-wrapper bot">
                                                    <div className="msg-bubble" dangerouslySetInnerHTML={{ __html: formatBotAnswer(msg.answer) }} />
                                                    <div className="msg-time">Ассистент</div>
                                                </div>
                                            </React.Fragment>
                                        );
                                    })
                                )}
                            </div>
                        </>
                    ) : (
                        <div className="empty-state">
                            <div className="icon">🌌</div>
                            <div style={{ fontSize: 18, fontWeight: 500, marginBottom: 8 }}>Выберите диалог</div>
                            <div style={{ fontSize: 14 }}>чтобы просмотреть историю сообщений</div>
                        </div>
                    )}
                </div>
            </main>

            <div className="vacancy-container" style={{ display: currentTab === 'vacancy' ? 'block' : 'none' }}>
                <table className="vacancy-table">
                    <thead>
                        <tr>
                            <th>Дата</th>
                            <th>Платформа</th>
                            <th>Пользователь</th>
                            <th>Содержание заявки</th>
                        </tr>
                    </thead>
                    <tbody>
                        {vacancies.length === 0 ? (
                            <tr><td colSpan={4} style={{ textAlign: 'center', padding: 40, color: 'var(--text-dim)' }}>Загрузка...</td></tr>
                        ) : (
                            vacancies.map(app => (
                                <tr key={app.id} onClick={() => handleOpenVacancy(app)} style={{ cursor: 'pointer', fontWeight: app.is_read ? 'normal' : 'bold', background: app.is_read ? 'transparent' : 'rgba(255,255,255,0.05)' }}>
                                    <td style={{ whiteSpace: 'nowrap' }}>{formatDate(app.created_at)}</td>
                                    <td>
                                        <span className={`platform-badge ${app.platform}`}>
                                            {getPlatformIcon(app.platform)}
                                            {app.platform}
                                        </span>
                                    </td>
                                    <td>{app.username}</td>
                                    <td className="vacancy-preview">{app.application_text.substring(0, 120)}</td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            <WhatsAppModal isOpen={isWaModalOpen} onClose={() => setIsWaModalOpen(false)} />
            <VacancyModal application={selectedVacancy} onClose={() => setSelectedVacancy(null)} />
        </div>
    );
}

export default App;