import React, { useMemo } from 'react';
import type { VacancyApplication } from '../../shared/types';
import { getPlatformIcon } from '../../shared/ui/Icons';
import { formatDate } from '../../shared/utils/date';

interface Props {
    application: VacancyApplication | null;
    onClose: () => void;
}

export const VacancyModal: React.FC<Props> = ({ application, onClose }) => {
    
    const parsedText = useMemo(() => {
        if (!application) return [];
        let text = application.application_text.replace(/\[\/?VACANCY_APPLICATION\]/g, '').trim();
        const lines = text.split('\n').filter(l => l.trim() !== '');
        
        const items = [];
        let currentKey = '';
        let currentValue = '';

        for (let line of lines) {
            const match = line.match(/^(\d+\.?\s*.*?|.*?):\s*(.*)$/);
            if (match) {
                if (currentKey) items.push({ key: currentKey, value: currentValue });
                currentKey = match[1].replace(/^\d+\.\s*/, '').trim();
                currentValue = match[2].trim();
            } else {
                if (currentKey) currentValue += '\n' + line.trim();
                else currentValue += line.trim() + '\n';
            }
        }
        if (currentKey || currentValue) items.push({ key: currentKey || 'Информация', value: currentValue });
        return items;
    }, [application]);

    if (!application) return null;

    return (
        <div className="vacancy-modal-overlay open" onClick={(e) => { if(e.target === e.currentTarget) onClose() }}>
            <div className="vacancy-modal-body">
                <div className="modal-close" onClick={onClose}>&times;</div>
                <h3 style={{ marginBottom: 8, fontSize: 20 }}>📋 Заявка на вакансию</h3>
                <p style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 20 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        {getPlatformIcon(application.platform)} {application.username} · {application.platform} · {formatDate(application.created_at)}
                    </div>
                </p>
                <div className="vacancy-grid">
                    {parsedText.map((item, idx) => (
                        <div key={idx} className={`vacancy-item ${item.value.length > 100 ? 'full-width' : ''}`}>
                            <div className="vacancy-label">{item.key}</div>
                            <div className="vacancy-value" dangerouslySetInnerHTML={{ __html: item.value.replace(/\n/g, '<br>') }} />
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
};