import { useLayoutEffect, useRef, useState } from 'react';
import { AppIcon } from './AppIcon';

const viewport = { width: 1280, height: 760 };
const options = [
  { id: 'integrated', title: 'Тест внутри панели', description: 'Фильтры остаются сверху, а «Тест агента» открывается из панели разбора.' },
  { id: 'compact', title: 'Графитовая рейка справа', description: 'Узкая колонка с двумя переходами вверху и тестом агента внизу.' },
  { id: 'left', title: 'Навигация слева', description: 'Кнопки с подписями и счётчик обращений на проверку.' },
];

function PreviewCard({ option }: { option: typeof options[number] }) {
  const frame = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0);
  const href = `?nav-preview=${option.id}`;

  useLayoutEffect(() => {
    const element = frame.current;
    if (!element) return;
    const resize = () => setScale(element.clientWidth / viewport.width);
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return (
    <article className="nav-option">
      <header className="nav-option-heading">
        <h2>{option.title}</h2>
        <p>{option.description}</p>
      </header>
      <div className="nav-option-frame" ref={frame} style={{ aspectRatio: `${viewport.width} / ${viewport.height}` }}>
        <iframe
          title={option.title}
          src={href}
          width={viewport.width}
          height={viewport.height}
          style={{ transform: `scale(${scale})` }}
          aria-hidden="true"
          tabIndex={-1}
        />
      </div>
      <a className="nav-option-open" href={href} target="_blank" rel="noreferrer">Открыть в полный размер <AppIcon name="external" size={17} /></a>
    </article>
  );
}

export function NavigationPreview() {
  return (
    <main className="nav-comparison">
      <header className="nav-comparison-heading">
        <h1>Варианты навигации</h1>
        <a href="./">Текущий журнал</a>
      </header>
      <div className="nav-comparison-grid">
        {options.map(option => <PreviewCard key={option.id} option={option} />)}
      </div>
    </main>
  );
}
