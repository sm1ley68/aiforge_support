import { useEffect, useState } from 'react';
import { AppIcon } from './AppIcon';
import type { Message } from './agent-types';

export type TranscriptMessage = Message & { id?: string; mine?: boolean; files?: File[] };

const sizeFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });

export function fileSize(bytes: number) {
  if (bytes >= 1024 * 1024) return `${sizeFormat.format(bytes / (1024 * 1024))} МБ`;
  if (bytes >= 1024) return `${sizeFormat.format(bytes / 1024)} КБ`;
  return `${bytes} Б`;
}

export function ChatDownload({ file }: { file: File }) {
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);

  return (
    <a className="chat-file chat-file-download" href={url} download={file.name} aria-label={`Скачать ${file.name}`}>
      <AppIcon name="download" size={16} />
      <span><strong>{file.name}</strong><small>{fileSize(file.size)}</small></span>
    </a>
  );
}

export function RequestMessages({ messages }: { messages: TranscriptMessage[] }) {
  return (
    <div className="thread-messages" aria-label="Сообщения">
      {messages.length ? messages.map((message, index) => (
        <article className={`thread-message thread-message--${message.role}`} data-mine={message.mine || undefined} key={message.id ?? index}>
          <span className="thread-message-icon" aria-hidden="true">
            <AppIcon name={message.role === 'assistant' ? 'agent' : message.role === 'support' ? 'support' : 'client'} size={16} />
          </span>
          <div>
            <h3>{message.role === 'assistant' ? 'Агент Store' : message.role === 'support' ? 'Поддержка' : 'Клиент'}</h3>
            {message.content && <p>{message.content}</p>}
            {Boolean(message.files?.length) && (
              <ul className="chat-files" aria-label="Вложения сообщения">
                {message.files?.map((file, index) => <li key={index}><ChatDownload file={file} /></li>)}
              </ul>
            )}
            {Array.isArray(message.attachments) && message.attachments.length > 0 && (
              <ul className="chat-files" aria-label="Вложения сообщения">
                {message.attachments.map((file, index) => {
                  const url = safeAttachmentUrl(file.url);
                  return (
                    <li key={index}>
                      <a className="chat-file chat-file-download" href={url} download={file.name} aria-label={`Скачать ${file.name}`}>
                        <AppIcon name="download" size={16} />
                        <span><strong>{file.name}</strong><small>{fileSize(file.size)}</small></span>
                      </a>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </article>
      )) : <p className="journal-empty">Сообщений в запросе пока нет.</p>}
    </div>
  );
}

function safeAttachmentUrl(value: string) {
  if (!value) return;
  try {
    const url = new URL(value, window.location.href);
    if (url.protocol === 'http:' || url.protocol === 'https:') return url.href;
  } catch {
    return undefined;
  }
}
