export const formatTime = (isoString: string): string => {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
};

export const formatDate = (isoString: string): string => {
    if (!isoString) return '';
    const date = new Date(isoString);
    const now = new Date();
    if (date.toDateString() === now.toDateString()) return formatTime(isoString);
    return date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }) + ' ' + formatTime(isoString);
};

export const formatBotAnswer = (htmlText: string): string => {
    let text = htmlText.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    text = text.replace(/&lt;b&gt;/g, '<b>').replace(/&lt;\/b&gt;/g, '</b>');
    text = text.replace(/&lt;i&gt;/g, '<i>').replace(/&lt;\/i&gt;/g, '</i>');
    text = text.replace(/\n/g, '<br>');
    return text;
};