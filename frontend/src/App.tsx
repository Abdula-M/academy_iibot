import React, { useState, useCallback } from 'react';
import { useStats } from './features/stats/useStats';
import { useUsers } from './features/users/useUsers';
import { useChat } from './features/chat/useChat';
import { useVacancies } from './features/vacancy/useVacancies';
import { useWhatsApp } from './features/whatsapp/useWhatsApp';
import { WhatsAppModal } from './features/whatsapp/WhatsAppModal';
import { VacancyModal } from './features/vacancy/VacancyModal';
import { UserList } from './features/users/UserList';
import { ChatArea } from './features/chat/ChatArea';
import { VacancyTab } from './features/vacancy/VacancyTab';
import type { User, VacancyApplication } from './shared/types';

import QRCode from 'react-qr-code';

function App() {
    const [currentTab, setCurrentTab] = useState<'chat' | 'vacancy'>('chat');
    const [selectedUser, setSelectedUser] = useState<User | null>(null);
    const [isWaModalOpen, setIsWaModalOpen] = useState(false);
    const [selectedVacancy, setSelectedVacancy] = useState<VacancyApplication | null>(null);

    const { stats, lastUpdate, reloadStats } = useStats();
    const { users, hasMore: usersHasMore, loadingMore: usersLoadingMore, reloadUsers, loadMore: loadMoreUsers } = useUsers();
    const { messages, loading: chatLoading, loadingOlder, hasOlder, reloadMessages, loadOlder } = useChat(selectedUser ? selectedUser.telegram_id : null);
    const { vacancies, loading: vacanciesLoading, hasMore: vacanciesHasMore, loadingMore: vacanciesLoadingMore, loadMore: loadMoreVacancies, markAsRead } = useVacancies();
    const { status: waStatus, qrCode, loadStatus } = useWhatsApp();

    React.useEffect(() => {
        loadStatus();
        const interval = waStatus.includes('подключен') ? 30000 : 5000;
        const id = setInterval(loadStatus, interval);
        return () => clearInterval(id);
    }, [waStatus]);

    const handleSelectUser = useCallback((user: User) => {
        setSelectedUser(user);
        reloadMessages().then(() => {
            reloadUsers();
        });
    }, [reloadMessages, reloadUsers]);

    const handleBack = useCallback(() => {
        setSelectedUser(null);
    }, []);

    const handleOpenVacancy = useCallback((app: VacancyApplication) => {
        setSelectedVacancy(app);
        if (!app.is_read) {
            markAsRead(app.id).then(() => {
                reloadStats();
            });
        }
    }, [markAsRead, reloadStats]);

    const handleCloseVacancy = useCallback(() => {
        setSelectedVacancy(null);
    }, []);

    const handleOpenWaModal = useCallback(() => {
        setIsWaModalOpen(true);
    }, []);

    const handleCloseWaModal = useCallback(() => {
        setIsWaModalOpen(false);
    }, []);

    return (
        <div id="app-root" data-theme="dark">
            <header className="header">
                <div className="header-title">
                    <img src="/logo.png" alt="logo" style={{ width: 36, height: 36, borderRadius: 10, marginRight: 8, boxShadow: '0 4px 10px rgba(59,130,246,0.3)' }} />
                    AI Центр Диалогов
                </div>
                <div className="tab-switcher" style={{ margin: '0 auto' }}>
                    <button className={`tab-btn ${currentTab === 'chat' ? 'active' : ''}`} onClick={() => setCurrentTab('chat')}>
                        💬 Диалоги
                    </button>
                    <button className={`tab-btn ${currentTab === 'vacancy' ? 'active' : ''}`} onClick={() => setCurrentTab('vacancy')}>
                        📋 Заявки 
                        {(stats?.unread_applications ?? 0) > 0 && (
                            <span className="badge" style={{ background: 'red', color: 'white', borderRadius: '50%', padding: '2px 6px', fontSize: 10, marginLeft: 4 }}>
                                {stats!.unread_applications}
                            </span>
                        )}
                    </button>
                </div>

                <div className="header-stats">
                    {lastUpdate && <div style={{ fontSize: 12, color: 'var(--text-dim)', marginRight: 8 }}>Обновлено: {lastUpdate}</div>}
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
                    
                    <div 
                        className="stat-card" 
                        style={{ 
                            background: qrCode ? 'rgba(245,158,11,0.1)' : 'rgba(255,255,255,0.02)', 
                            border: qrCode ? '1px solid rgba(245,158,11,0.3)' : 'none', 
                            cursor: 'pointer', 
                            padding: qrCode ? '4px 12px' : '6px 12px', 
                            borderRadius: 8,
                            display: 'flex',
                            alignItems: 'center',
                            gap: 12
                        }} 
                        onClick={handleOpenWaModal}
                    >
                        {qrCode ? (
                            <>
                                <div style={{ width: 44, height: 44, borderRadius: 4, background: '#fff', padding: 2, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                                    {qrCode.startsWith('data:image') 
                                        ? <img src={qrCode} alt="QR" style={{ width: '100%', height: '100%', objectFit: 'contain' }} /> 
                                        : <QRCode value={qrCode} size={40} style={{ width: '100%', height: '100%' }} />}
                                </div>
                                <div>
                                    <div className="stat-label" style={{ color: '#f59e0b' }}>WhatsApp</div>
                                    <div className="stat-value" style={{ fontSize: 11, marginTop: 2, color: '#fcd34d' }}>Отсканируйте QR ⚙️</div>
                                </div>
                            </>
                        ) : waStatus.includes('подключен') ? (
                            <div>
                                <div className="stat-label" style={{ color: '#10b981' }}>WhatsApp</div>
                                <div className="stat-value" style={{ fontSize: 13, marginTop: 4, color: '#34d399' }}>Подключен ✅</div>
                            </div>
                        ) : (
                            <div>
                                <div className="stat-label" style={{ color: '#9ca3af' }}>WhatsApp</div>
                                <div className="stat-value" style={{ fontSize: 13, marginTop: 4 }}>Загрузка... ⏳</div>
                            </div>
                        )}
                    </div>
                </div>
            </header>

            <main className={`app-container ${selectedUser ? 'chat-active' : ''}`} style={{ display: currentTab === 'chat' ? 'flex' : 'none' }}>
                <UserList
                    users={users}
                    selectedUser={selectedUser}
                    hasMore={usersHasMore}
                    loadingMore={usersLoadingMore}
                    onSelectUser={handleSelectUser}
                    onLoadMore={loadMoreUsers}
                />
                <ChatArea
                    selectedUser={selectedUser}
                    messages={messages}
                    loading={chatLoading}
                    loadingOlder={loadingOlder}
                    hasOlder={hasOlder}
                    onBack={handleBack}
                    onLoadOlder={loadOlder}
                />
            </main>

            <div style={{ display: currentTab === 'vacancy' ? 'block' : 'none' }}>
                <VacancyTab
                    vacancies={vacancies}
                    loading={vacanciesLoading}
                    hasMore={vacanciesHasMore}
                    loadingMore={vacanciesLoadingMore}
                    onOpenVacancy={handleOpenVacancy}
                    onLoadMore={loadMoreVacancies}
                />
            </div>

            <WhatsAppModal isOpen={isWaModalOpen} onClose={handleCloseWaModal} />
            <VacancyModal application={selectedVacancy} onClose={handleCloseVacancy} />
        </div>
    );
}

export default App;