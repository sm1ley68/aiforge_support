import type { OperatorRequest } from './operator-types';

export const customerChatView = '?view=chat';

export type Offer = {
  id: string;
  title: string;
  sku?: string;
  url: string;
  facts: [string, string][];
  reason: string;
};

type Choice = { label: string; text: string };
type Result = { offer: Offer; status: 'fit' | 'alternative' | 'option' | 'check' | 'mismatch' };
type Reply = {
  text: string;
  choices?: Choice[];
  results?: Result[];
  source?: { title: string; url: string };
  changed?: string;
  offerHandoff?: boolean;
};

type Requirements = {
  topic?: 'astra' | 'mail' | 'security';
  device?: 'workstation' | 'server';
  protection?: 'enhanced' | 'maximum';
  platform?: 'Exchange' | 'Microsoft 365';
  endpoints?: 'Windows' | 'mixed';
  seats?: number;
  term?: 12 | 24;
  budget?: number;
  russian?: boolean;
  lastRecommendation?: string;
};

export type DemoTurn = { id: string; message: string; reply: Reply; topic?: Requirements['topic'] };
export type StoreConversation = {
  requirements: Requirements;
  turns: DemoTurn[];
  handoffId?: string;
};

const astraFacts: [string, string][] = [
  ['Назначение', 'Рабочая станция'], ['Архитектура', 'x86-64'], ['Срок', '12 месяцев'],
];

export const voronezh: Offer = {
  id: 'astra-voronezh', title: 'Astra Linux SE «Воронеж»', sku: 'OS2001X8618DIG000WS02-PO12',
  url: 'https://store.softline.ru/astralinux/os2001x8618dig000ws02-po12-488169/',
  facts: [['Уровень защиты', 'Усиленный'], ...astraFacts],
  reason: 'Усиленный уровень защиты для рабочих станций.',
};

const smolensk: Offer = {
  id: 'astra-smolensk', title: 'Astra Linux SE «Смоленск»', sku: 'OS2101X8618DIG000WS02-PO12',
  url: 'https://store.softline.ru/astralinux/os2101x8618dig000ws02-po12-488181/',
  facts: [['Уровень защиты', 'Максимальный'], ...astraFacts],
  reason: 'Максимальный уровень защиты для рабочих станций.',
};

const mdaemon12: Offer = {
  id: 'mdaemon-12', title: 'MDaemon Messaging Server',
  url: 'https://store.softline.ru/alt-n-technologies-ltd/-19579/',
  facts: [['Пользователи', '50'], ['Срок', '12 месяцев']],
  reason: 'Лицензия с подпиской на обновления на один год.',
};
const mdaemon24: Offer = {
  id: 'mdaemon-24', title: 'MDaemon',
  url: 'https://store.softline.ru/alt-n-technologies-ltd/-477654/',
  facts: [['Пользователи', '50'], ['Срок', '24 месяца']],
  reason: 'Двухлетняя лицензия на 50 пользователей.',
};

const securityBundle: Offer = {
  id: 'kaspersky-bundle', title: 'Kaspersky Endpoint Security + защита почты', sku: 'KL4313RAKFS+KL4863RAKFS',
  url: 'https://store.softline.ru/kaspersky/kl4313rakfs-kl4863rakfs-292923/',
  facts: [['Состав', 'Защита рабочих мест и почтовых серверов'], ['Срок', '12 месяцев']],
  reason: 'В каталоге есть комплект из двух продуктов. Проверьте версии инфраструктуры и объём лицензий.',
};

export const starters: Choice[] = [
  { label: 'Сравнить редакции', text: 'Сравни «Воронеж» и «Смоленск» для рабочих станций.' },
  { label: 'Подобрать по задаче', text: 'Хотим защитить почту и файлы для 50 сотрудников.' },
  { label: 'Спросить о лицензии', text: 'На какой срок оформляется эта лицензия Astra Linux?' },
];

function choices(...options: string[]): Choice[] {
  return options.map(text => ({ label: text, text }));
}

export function emptyStoreConversation(): StoreConversation {
  return { requirements: {}, turns: [] };
}

function astraReply(text: string, requirements: Requirements): Reply {
  if (requirements.russian && !/воронеж|смоленск|astra|астра/.test(text)) {
    return { text: 'Astra Linux указан в Store как российский продукт. Если нужен аналог от другого производителя, уточните требования к уровню защиты для менеджера.', source: { title: voronezh.title, url: voronezh.url }, offerHandoff: true };
  }
  if (requirements.term === 24) {
    return { text: 'Оба артикула оформляются на 12 месяцев. Предложение на 24 месяца нужно проверить отдельно.', source: { title: voronezh.title, url: voronezh.url }, offerHandoff: true };
  }
  if (/совместим|работает ли|поддерживает ли/.test(text)) {
    return { text: 'По данным этой карточки я могу подтвердить архитектуру x86-64. Совместимость с вашей конфигурацией нужно проверить отдельно.', source: { title: voronezh.title, url: voronezh.url }, offerHandoff: true };
  }
  if (/артикул|sku|цен[ауые]|стоимост|срок|месяц|обновлен|архитектур|электронн|для физ|для юр|продлен|оплат|какой уровень/.test(text) && !/сравни/.test(text)) {
    const offer = /смоленск/i.test(text) || requirements.lastRecommendation === smolensk.id && !/эта|этой|открыт|воронеж/i.test(text) ? smolensk : voronezh;
    let answer = 'Эта лицензия предназначена для юридических лиц и ИП. Срок — 12 месяцев, поставка электронная, обновления Тип 2 включены на 12 месяцев.';
    if (/цен[ауые]|стоимост|оплат/.test(text)) answer = 'Актуальная цена и условия оплаты указаны в карточке Store.';
    if (/артикул|sku/.test(text)) answer = `Артикул этой лицензии — ${offer.sku}.`;
    if (/архитектур/.test(text)) answer = 'В карточке для этого артикула указана архитектура x86-64.';
    if (/какой уровень/.test(text)) answer = offer.reason;
    return { text: answer, source: { title: offer.title, url: offer.url } };
  }
  if (requirements.device === 'server') {
    return { text: 'Оба артикула предназначены для рабочих станций. Для серверов нужно проверить отдельные позиции под вашу конфигурацию.', offerHandoff: true };
  }
  if (requirements.protection === 'maximum' || requirements.protection === 'enhanced') {
    const maximum = requirements.protection === 'maximum';
    const offer = maximum ? smolensk : voronezh;
    const other = maximum ? voronezh : smolensk;
    const changed = requirements.lastRecommendation && requirements.lastRecommendation !== offer.id;
    requirements.lastRecommendation = offer.id;
    return {
      text: maximum
        ? 'Для рабочих станций с максимальным уровнем защиты подходит «Смоленск». У «Воронежа» уровень усиленный.'
        : 'Для рабочих станций с усиленным уровнем защиты подходит «Воронеж». «Смоленск» стоит рассмотреть, если понадобится максимальный уровень.',
      changed: changed ? `Рекомендация изменилась на «${maximum ? 'Смоленск' : 'Воронеж'}» после уточнения уровня защиты.` : undefined,
      results: [{ offer, status: 'fit' }, { offer: other, status: maximum ? 'mismatch' : 'alternative' }],
      choices: choices(maximum ? 'Достаточно усиленного уровня' : 'Нужен максимальный уровень'),
    };
  }
  if (/сравни|разниц|отличи|чем отлич|редакци[ияй]/.test(text)) {
    return {
      text: 'У этих двух лицензий совпадают срок и назначение. Ключевое отличие — уровень защиты: усиленный у «Воронежа» и максимальный у «Смоленска». Какой вам нужен?',
      results: [{ offer: voronezh, status: 'option' }, { offer: smolensk, status: 'option' }],
      choices: choices('Достаточно усиленного уровня', 'Нужен максимальный уровень'),
    };
  }
  if (requirements.device === 'workstation') {
    return { text: 'Для рабочих станций доступны «Воронеж» и «Смоленск». Какой уровень защиты требуется?', choices: choices('Достаточно усиленного уровня', 'Нужен максимальный уровень') };
  }
  return { text: 'Где будет работать система? Эта карточка относится к лицензии для рабочих станций.', choices: choices('Рабочие станции', 'Серверы') };
}

function mailReply(text: string, requirements: Requirements): Reply {
  if (requirements.russian) {
    return { text: 'Для российского аналога почтового сервера нужно уточнить способ развёртывания и обязательные функции. Могу передать вопрос менеджеру вместе с уже собранными условиями.', offerHandoff: true };
  }
  if (requirements.seats && requirements.seats !== 50) {
    return { text: `Для ${requirements.seats} пользователей нужен другой вариант лицензирования. В демо есть подтверждённые предложения для 50 пользователей.`, offerHandoff: true };
  }
  if (/сравни|разниц|отлич/.test(text) || requirements.seats === 50) {
    const first = requirements.term === 24 ? mdaemon24 : mdaemon12;
    const second = first === mdaemon12 ? mdaemon24 : mdaemon12;
    return {
      text: 'В Store есть два предложения MDaemon на 50 пользователей. Они отличаются сроком. Обозначение «Standard» у этих позиций не подтверждено.',
      results: [{ offer: first, status: requirements.term ? 'fit' : 'option' }, { offer: second, status: requirements.term ? 'alternative' : 'option' }],
      choices: requirements.term ? undefined : choices('50 пользователей, 12 месяцев', '50 пользователей, 24 месяца'),
    };
  }
  return { text: 'В Store есть MDaemon, но обозначение «Standard» у найденных позиций не подтверждено. На сколько пользователей нужна лицензия?', choices: choices('50 пользователей', 'Сравни предложения MDaemon на 50 пользователей') };
}

function securityReply(requirements: Requirements): Reply {
  const scope = requirements.seats ? ` для ${requirements.seats} сотрудников` : '';
  if (requirements.russian) {
    return { text: `Я не подтвердил в рамках демо российский аналог, который закрывает и почту, и файлы${scope}. Менеджеру можно передать уже собранные требования для проверки.`, offerHandoff: true };
  }
  if (!requirements.platform) {
    return { text: `Подбираем защиту почты и файлов${scope}. Где сейчас работает ваша корпоративная почта?`, choices: choices('Локальный Exchange', 'Microsoft 365') };
  }
  if (!requirements.endpoints) {
    return { text: 'Какие устройства нужно защитить вместе с почтой? От этого зависит состав комплекта.', choices: choices('Рабочие станции Windows', 'Смешанная инфраструктура') };
  }
  if (requirements.platform !== 'Exchange' || requirements.endpoints !== 'Windows') {
    return { text: 'По этим условиям я не могу подтвердить совместимость комплекта из демо-каталога. Могу передать вашу платформу и типы устройств менеджеру для проверки.', offerHandoff: true };
  }
  const budget = requirements.budget
    ? ` Цену для вашего бюджета до ${new Intl.NumberFormat('ru-RU').format(requirements.budget)} ₽ также нужно подтвердить.`
    : '';
  return {
    text: `Для локального Exchange и рабочих станций Windows${scope} нашёл в Store комплект для проверки. Версию Exchange и количество покрываемых устройств нужно подтвердить отдельно.${budget}`,
    results: [{ offer: securityBundle, status: 'check' }],
    choices: choices('Есть российский аналог?'),
  };
}

export function replyToStoreMessage(message: string, current: Requirements): { reply: Reply; requirements: Requirements; handoff: boolean } {
  const text = message.toLocaleLowerCase('ru-RU');
  const topic = /mdaemon|мдемон/.test(text) ? 'mail'
    : /защит\S*\s+(почту|файлы)|почт\S*\s+и\s+файл/.test(text) ? 'security'
    : /astra|астра|воронеж|смоленск/.test(text) ? 'astra' : undefined;
  if (/позов\S*\s+менеджер|свяж\S*\s+с\s+менеджер|перед\S*\s+(?:запрос\s+)?менеджер|нужен\s+менеджер/.test(text)) {
    return {
      reply: { text: 'Запрос передан в демо-очередь менеджера. История и требования доступны в карточке обращения.' },
      requirements: { ...current, topic: current.topic ?? topic },
      handoff: true,
    };
  }
  const requirements: Requirements = topic && topic !== current.topic ? { topic } : { ...current };

  const seats = text.match(/(\d{1,6})\s*(?:пользовател\S*|сотрудник\S*|рабочих мест|пк)/);
  if (seats && Number(seats[1]) > 0) requirements.seats = Number(seats[1]);
  const budget = text.match(/бюджет\S*\s+(?:до\s+)?(\d[\d\s]*)(тыс)?/);
  if (budget) {
    const amount = Number(budget[1].replace(/\s/g, '')) * (budget[2] ? 1000 : 1);
    if (Number.isSafeInteger(amount) && amount > 0) requirements.budget = amount;
  }
  if (/24\s*мес|2\s*года|два года/.test(text)) requirements.term = 24;
  else if (/12\s*мес|1\s*год|на год/.test(text)) requirements.term = 12;
  if (/максимальн\S*\s+уров/.test(text) && !/достаточно|усиленн/.test(text)) requirements.protection = 'maximum';
  else if (/усиленн\S*\s+уров/.test(text)) requirements.protection = 'enhanced';

  if (/российск\S*\s+(?:аналог|решени)|отечественн\S*\s+аналог/.test(text)) requirements.russian = true;

  if (requirements.topic === 'security') {
    if (/exchange/.test(text)) requirements.platform = 'Exchange';
    if (/microsoft\s*365|office\s*365/.test(text)) requirements.platform = 'Microsoft 365';
    if (/windows/.test(text)) requirements.endpoints = 'Windows';
    if (/смешанн/.test(text)) requirements.endpoints = 'mixed';
    return { reply: securityReply(requirements), requirements, handoff: false };
  }
  if (requirements.topic === 'mail') return { reply: mailReply(text, requirements), requirements, handoff: false };
  if (/сервер/.test(text) && !/рабоч\S*\s+станц/.test(text)) requirements.device = 'server';
  if (/рабоч\S*\s+станц|рабочих мест|\d+\s*пк/.test(text)) requirements.device = 'workstation';
  if (requirements.topic === 'astra' || /сравни|редакци|лицензи|срок|сервер|станц|sku|артикул|цен[ауые]|уровень защиты/.test(text)) {
    requirements.topic = 'astra';
    return { reply: astraReply(text, requirements), requirements, handoff: false };
  }
  return {
    reply: { text: 'Что хотите подобрать? Напишите название продукта, артикул или задачу. Если вопрос касается открытой карточки, укажите, что хотите узнать о лицензии.', offerHandoff: true },
    requirements,
    handoff: false,
  };
}

const conversationKey = 'store-advisor-customer-demo-v1';
export const handoffKey = 'store-advisor-demo-handoffs-v1';
export const handoffChanged = 'store-advisor-demo-handoffs-changed';

export function loadStoreConversation(): StoreConversation {
  try {
    const stored = JSON.parse(sessionStorage.getItem(conversationKey) ?? 'null');
    if (stored?.requirements && Array.isArray(stored.turns)) return stored;
  } catch { /* A blocked or unavailable storage still allows a new demo chat. */ }
  return emptyStoreConversation();
}

export function saveStoreConversation(conversation: StoreConversation) {
  try { sessionStorage.setItem(conversationKey, JSON.stringify(conversation)); } catch { /* The open chat still works. */ }
}

export function readDemoHandoffs(): OperatorRequest[] {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(handoffKey) ?? '[]');
    if (Array.isArray(stored)) return stored;
  } catch { /* An unavailable queue is handled by saveDemoHandoff. */ }
  return [];
}

export function saveDemoHandoff(id: string, conversation: StoreConversation) {
  const { requirements, turns } = conversation;
  const last = turns.at(-1);
  const relatedTurns = turns.filter(turn => turn.topic === requirements.topic);
  const latestResults = relatedTurns.findLast(turn => turn.reply.results?.length)?.reply.results ?? [];
  const requirementsRows = [
    ['Пользователи', requirements.seats?.toString()],
    ['Устройства', requirements.device === 'workstation' ? 'Рабочие станции' : requirements.device === 'server' ? 'Серверы' : requirements.endpoints],
    ['Уровень защиты', requirements.protection === 'maximum' ? 'Максимальный' : requirements.protection === 'enhanced' ? 'Усиленный' : undefined],
    ['Почтовая платформа', requirements.platform],
    ['Срок', requirements.term ? `${requirements.term} мес.` : undefined],
    ['Бюджет', requirements.budget ? `До ${new Intl.NumberFormat('ru-RU').format(requirements.budget)} ₽` : undefined],
    ['Происхождение', requirements.russian ? 'Российский аналог' : undefined],
  ].flatMap(([label, value]) => label && value ? [{ label, value }] : []);
  const sources = new Map(latestResults.map(({ offer }) => [offer.url, { title: offer.title, url: offer.url }]));
  for (const turn of relatedTurns) if (turn.reply.source) sources.set(turn.reply.source.url, turn.reply.source);
  const request: OperatorRequest = {
    id, title: (relatedTurns[0] ?? turns[0])?.message.slice(0, 105) || 'Запрос связи с менеджером',
    customer: 'Клиент демо-чата', updatedAt: new Date().toISOString(), status: 'review',
    scenario: requirements.topic === 'security' ? 'discovery' : requirements.topic ? 'known' : 'question',
    issue: { label: 'Запрос менеджера', detail: 'Клиент попросил подключить менеджера в чате витрины.', checks: ['Изучить вопрос клиента и подтверждённые позиции'] },
    response: {
      conversationId: id,
      messages: turns.flatMap(({ id: turnId, message, reply }) => [
        { id: `${turnId}-user`, role: 'user' as const, content: message },
        { id: `${turnId}-assistant`, role: 'assistant' as const, content: reply.text },
      ]),
      reply: last?.reply.text ?? '', requirements: requirementsRows,
      products: latestResults.map(({ offer, status }) => ({
        id: offer.id, name: offer.title, summary: offer.reason, url: offer.url, recommended: status === 'fit',
      })),
      sources: [...sources.values()], suggestedReplies: [],
      trace: [{ label: 'Обращение из демо-чата', detail: 'Подбор и переписка доступны для проверки.' }],
    },
  };
  const queue = readDemoHandoffs();
  localStorage.setItem(handoffKey, JSON.stringify([request, ...queue.filter(item => item.id !== id)].slice(0, 20)));
  window.dispatchEvent(new Event(handoffChanged));
}
