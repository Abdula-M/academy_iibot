import React, { useEffect, useState } from 'react';
import QRCode from 'react-qr-code';
import { useWhatsApp } from './useWhatsApp';

interface Props {
    isOpen: boolean;
    onClose: () => void;
}

export const WhatsAppModal: React.FC<Props> = ({ isOpen, onClose }) => {
    const { status, qrCode, loadStatus, logout } = useWhatsApp();
    const [intervalId, setIntervalId] = useState<number | null>(null);

    useEffect(() => {
        if (isOpen) {
            loadStatus();
            const id = setInterval(() => {
                loadStatus().then(st => {
                    if (st === 'authenticated') clearInterval(id);
                });
            }, 3000);
            setIntervalId(id as unknown as number);
        } else {
            if (intervalId) clearInterval(intervalId);
        }
        return () => {
            if (intervalId) clearInterval(intervalId);
        };
    }, [isOpen]);

    if (!isOpen) return null;

    return (
        <div className="modal-overlay open" onClick={(e) => { if(e.target === e.currentTarget) onClose() }}>
            <div className="modal-content">
                <div className="modal-close" onClick={onClose}>&times;</div>
                <h3 style={{ marginBottom: 12, fontSize: 22 }}>WhatsApp Подключение</h3>
                <p style={{ fontSize: 14, color: 'var(--text-dim)' }}>{status}</p>
                {qrCode && (
                    <div id="qr-container" style={{ display: 'flex', justifyContent: 'center', padding: '20px', background: 'white', borderRadius: '8px', marginBottom: '16px' }}>
                        {qrCode.startsWith('data:image') 
                            ? <img src={qrCode} alt="WhatsApp QR Code" /> 
                            : <QRCode value={qrCode} size={256} />}
                    </div>
                )}
                {status.includes('подключен') && (
                    <button className="btn-danger" onClick={logout}>Отвязать WhatsApp</button>
                )}
            </div>
        </div>
    );
};