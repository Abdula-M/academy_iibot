import React, { useCallback, useRef } from 'react';
import { getPlatformIcon } from '../../shared/ui/Icons';
import { formatDate } from '../../shared/utils/date';
import type { User } from '../../shared/types';

interface UserListProps {
    users: User[];
    selectedUser: User | null;
    hasMore: boolean;
    loadingMore: boolean;
    onSelectUser: (user: User) => void;
    onLoadMore: () => void;
}

const UserItem = React.memo<{
    user: User;
    isActive: boolean;
    onSelect: (user: User) => void;
}>(({ user, isActive, onSelect }) => (
    <div
        className={`user-item ${isActive ? 'active' : ''}`}
        onClick={() => onSelect(user)}
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
));

UserItem.displayName = 'UserItem';

export const UserList = React.memo<UserListProps>(({
    users,
    selectedUser,
    hasMore,
    loadingMore,
    onSelectUser,
    onLoadMore,
}) => {
    const observerRef = useRef<IntersectionObserver | null>(null);

    const lastUserRef = useCallback(
        (node: HTMLDivElement | null) => {
            if (loadingMore) return;
            if (observerRef.current) observerRef.current.disconnect();

            observerRef.current = new IntersectionObserver(entries => {
                if (entries[0].isIntersecting && hasMore) {
                    onLoadMore();
                }
            });

            if (node) observerRef.current.observe(node);
        },
        [loadingMore, hasMore, onLoadMore],
    );

    return (
        <aside className="sidebar">
            <div className="users-list">
                {users.length === 0 ? (
                    <div className="empty-state" style={{ padding: 20, fontSize: 13 }}>Нет данных</div>
                ) : (
                    users.map((user, idx) => (
                        <div
                            key={user.telegram_id}
                            ref={idx === users.length - 1 ? lastUserRef : undefined}
                        >
                            <UserItem
                                user={user}
                                isActive={selectedUser?.telegram_id === user.telegram_id}
                                onSelect={onSelectUser}
                            />
                        </div>
                    ))
                )}
                {loadingMore && (
                    <div style={{ padding: 12, textAlign: 'center', color: 'var(--text-dim)', fontSize: 12 }}>
                        Загрузка...
                    </div>
                )}
            </div>
        </aside>
    );
});

UserList.displayName = 'UserList';
