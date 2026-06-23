import React from 'react';
import { getPlatformIcon } from '../../shared/ui/Icons';
import { formatDate } from '../../shared/utils/date';
import type { VacancyApplication } from '../../shared/types';

interface VacancyTabProps {
    vacancies: VacancyApplication[];
    hasMore: boolean;
    loadingMore: boolean;
    onOpenVacancy: (app: VacancyApplication) => void;
    onLoadMore: () => void;
}

const VacancyRow = React.memo<{
    app: VacancyApplication;
    onOpen: (app: VacancyApplication) => void;
}>(({ app, onOpen }) => (
    <tr
        onClick={() => onOpen(app)}
        style={{
            cursor: 'pointer',
            fontWeight: app.is_read ? 'normal' : 'bold',
            background: app.is_read ? 'transparent' : 'rgba(255,255,255,0.05)',
        }}
    >
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
));

VacancyRow.displayName = 'VacancyRow';

export const VacancyTab = React.memo<VacancyTabProps>(({
    vacancies,
    hasMore,
    loadingMore,
    onOpenVacancy,
    onLoadMore,
}) => (
    <div className="vacancy-container">
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
                        <VacancyRow key={app.id} app={app} onOpen={onOpenVacancy} />
                    ))
                )}
            </tbody>
        </table>
        {hasMore && (
            <div style={{ padding: 16, textAlign: 'center' }}>
                <button
                    onClick={onLoadMore}
                    disabled={loadingMore}
                    style={{
                        background: 'rgba(255,255,255,0.05)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        color: 'var(--text-dim)',
                        padding: '8px 24px',
                        borderRadius: 8,
                        cursor: loadingMore ? 'wait' : 'pointer',
                        fontSize: 13,
                    }}
                >
                    {loadingMore ? 'Загрузка...' : 'Загрузить ещё'}
                </button>
            </div>
        )}
    </div>
));

VacancyTab.displayName = 'VacancyTab';
