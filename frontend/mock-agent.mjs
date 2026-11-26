const ASTRA_DESKTOP_URL = 'https://store.softline.ru/astralinux/astra-linux-special-edition/';
const ASTRA_SERVER_URL = 'https://store.softline.ru/astralinux/os2101x8618boxsktsr01-po36-487955/';
const ASTRA_VORONEZH_URL = 'https://store.softline.ru/astralinux/os2001x8618dig000ws02-po12-488169/';
const ASTRA_SMOLENSK_URL = 'https://store.softline.ru/astralinux/os2101x8618dig000ws02-po12-488181/';
const R7_URL = 'https://store.softline.ru/novcommtech/ao-r7-dlya-biznesa/';
const MAXIMUM_REPLY = 'Нужен максимальный уровень защиты';
const ENHANCED_REPLY = 'Достаточно усиленного уровня защиты';
const QUOTE_REPLY = 'Подготовить запрос на КП';

const desktopProduct = {
  id: 'astra-linux-special-edition', name: 'Astra Linux Special Edition', version: '1.8',
  summary: 'ОС для защищённых рабочих мест.',
  detail: 'Предварительный кандидат для защищённого контура. Редакцию, совместимость, тип лицензии и услуги нужно уточнить под проект.',
  features: ['Сертифицированная редакция', 'Рабочие станции', 'Для защищённого контура'], url: ASTRA_DESKTOP_URL, recommended: true,
};
const enhancedProduct = {
  ...desktopProduct,
  id: 'astra-linux-voronezh', name: 'Astra Linux SE «Воронеж»',
  summary: 'Редакция для рабочих станций с усиленным уровнем защиты.',
  detail: 'Пример поставки из каталога: электронная лицензия x86-64 на 12 месяцев с обновлениями типа 2. Применимость к вашему контуру нужно подтвердить.',
  features: ['Усиленный уровень защиты', 'Рабочие станции', 'Электронная лицензия на 12 месяцев'],
  url: ASTRA_VORONEZH_URL,
};
const maximumProduct = {
  ...desktopProduct,
  id: 'astra-linux-smolensk', name: 'Astra Linux SE «Смоленск»',
  summary: 'Редакция для рабочих станций с максимальным уровнем защиты.',
  detail: 'Пример поставки из каталога: электронная лицензия x86-64 на 12 месяцев с обновлениями типа 2. Применимость к вашему контуру нужно подтвердить.',
  features: ['Максимальный уровень защиты', 'Рабочие станции', 'Электронная лицензия на 12 месяцев'],
  url: ASTRA_SMOLENSK_URL,
};
const serverProduct = {
  id: 'astra-linux-server', name: 'Astra Linux для серверов', version: '1.8',
  summary: 'Вариант для серверного сценария; точную редакцию следует согласовать.',
  detail: 'Используется как пример кандидата для запроса на сервер. Страница каталога не подтверждает совместимость или доступность конкретной конфигурации.',
  features: ['Серверный сценарий', 'Редакцию и конфигурацию уточнить', 'Коммерческие условия требуют подтверждения'], url: ASTRA_SERVER_URL, recommended: true,
};
const r7Product = {
  id: 'r7-office-business', name: 'Р7-Офис для бизнеса', version: 'корпоративная редакция',
  summary: 'Офисные приложения и совместная работа для организаций.',
  detail: 'Кандидат для команды, которой нужны офисные приложения. Вариант локального развёртывания, состав поставки и совместимость требуют проверки.',
  features: ['Документы, таблицы и презентации', 'Совместная работа', 'Условия локального развёртывания уточнить'], url: R7_URL, recommended: true,
};
const sourcesFor = (products) => products.map(({ name, url }) => ({ title: name, url, label: 'Справочная карточка Softline Store · демо' }));
const demoReply = 'Для 80 рабочих станций с усиленным уровнем защиты предварительно подходит Astra Linux Special Edition 1.8 «Воронеж». Применимость редакции, лицензию и стоимость миграции нужно подтвердить по параметрам проекта.';

export const demoConversation = {
  conversationId: 'demo-astra',
  messages: [
    { role: 'user', content: 'Нужна Astra Linux для рабочих станций.' },
    { role: 'assistant', content: 'Сколько рабочих мест планируется и какой уровень защиты нужен?' },
    { role: 'user', content: 'Около 80 мест, физические ПК. Нужен усиленный уровень защиты. Также интересуют поддержка и миграция.' },
    { role: 'assistant', content: demoReply },
  ],
  reply: demoReply,
  requirements: [
    { label: 'Рабочие места', value: 'Около 80' }, { label: 'Уровень защиты', value: 'Усиленный' },
    { label: 'Развёртывание', value: 'Физические ПК' }, { label: 'Услуги', value: 'Поддержка и миграция рассматриваются' },
  ],
  products: [{ ...enhancedProduct }, { ...maximumProduct, recommended: false }],
  sources: sourcesFor([enhancedProduct, maximumProduct]),
  trace: [{ label: 'Уточнение учтено', detail: '80 рабочих мест, усиленный уровень защиты, физические ПК.' }, { label: 'Выбрана редакция', detail: '«Воронеж» соответствует запрошенному уровню в демонстрационном подборе.' }],
  suggestedReplies: [MAXIMUM_REPLY, 'Нужна серверная ОС', 'Уточнить миграцию'],
};

function hasAny(text, words) { return words.some((word) => text.includes(word)); }
function userText(request) { return [request.message ?? '', ...(request.history ?? []).filter((item) => item.role === 'user').map((item) => item.content ?? '')].join(' ').toLowerCase(); }
function latestUserInputs(request) {
  return [request.message, ...(request.history ?? []).filter(item => item.role === 'user').map(item => item.content).reverse()];
}
function deploymentFor(request) {
  for (const input of latestUserInputs(request)) {
    const text = input?.toLowerCase() ?? '';
    if (hasAny(text, ['сервер'])) return 'Серверная инфраструктура';
    if (hasAny(text, ['рабоч', 'пк', 'компьютер'])) return 'Рабочие станции';
  }
}
function protectionFor(request) {
  for (const input of latestUserInputs(request)) {
    const text = input?.toLowerCase() ?? '';
    if (text.includes('смоленск') || /максимальн\S* уров(?:ень|ня) защиты/.test(text)) return 'Максимальный';
    if (text.includes('воронеж') || /усиленн\S* уров(?:ень|ня) защиты/.test(text)) return 'Усиленный';
  }
}
function inferScenario(request, text) {
  if (request.conversationId === 'demo-astra' || request.catalogProductId) return 'known';
  const opening = (request.history?.find(({ role }) => role === 'user')?.content ?? request.message).toLowerCase();
  if (hasAny(opening, ['цена', 'стоим', 'налич', 'поставка', 'когда получить', 'есть ли'])) return 'question';
  return hasAny(text, ['astra', 'linux']) ? 'known' : 'discovery';
}
function put(list, label, value) {
  const idx = list.findIndex((item) => item.label === label);
  if (idx < 0) list.push({ label, value }); else list[idx] = { label, value };
}
function requirementsFor(text, scenario, deployment) {
  const out = [];
  if (scenario === 'known') {
    put(out, 'Продукт', 'Astra Linux');
    const seats = text.match(/\b(\d{1,4})\s*(?:мест|пользовател|рабоч)/i);
    if (seats) put(out, 'Количество', `${seats[1]} рабочих мест`);
    if (hasAny(text, ['сертифиц', 'защищ'])) put(out, 'Безопасность', 'Сертифицированная редакция / защищённый контур');
    if (deployment) put(out, 'Сценарий', deployment);
    if (hasAny(text, ['миграц', 'поддерж'])) put(out, 'Услуги', 'Поддержка или миграция рассматриваются');
  } else if (scenario === 'discovery') {
    put(out, 'Задача', 'Подбор офисного ПО');
    const users = text.match(/\b(\d{1,4})\s*(?:человек|пользовател|сотрудник|мест)/i);
    if (users) put(out, 'Пользователи', users[1]);
    if (hasAny(text, ['документ', 'текст'])) put(out, 'Приложения', 'Работа с документами');
    if (hasAny(text, ['таблиц'])) put(out, 'Приложения', 'Документы и таблицы');
    if (hasAny(text, ['презентац'])) put(out, 'Приложения', 'Документы, таблицы и презентации');
    if (hasAny(text, ['совместн', 'редактирован'])) put(out, 'Совместная работа', 'Нужна');
    if (hasAny(text, ['локальн', 'своей инфраструктур', 'наши сервер'])) put(out, 'Размещение данных', 'В инфраструктуре заказчика');
    else if (hasAny(text, ['облак'])) put(out, 'Размещение данных', 'Облачный вариант');
    if (hasAny(text, ['почт'])) put(out, 'Почта', 'Нужна; платформу уточнить');
  } else {
    put(out, 'Вопрос', 'Наличие, цена и условия поставки');
    if (hasAny(text, ['astra', 'linux'])) put(out, 'Продукт', 'Astra Linux');
    const qty = text.match(/\b(\d{1,4})\s*(?:лиценз|шт\.?)/i);
    if (qty) put(out, 'Количество', `${qty[1]} лицензий`);
    const cities = [['москв', 'Москва'], ['санкт-петербург', 'Санкт-Петербург'], ['казан', 'Казань'], ['екатеринбург', 'Екатеринбург']];
    const city = cities.find(([keyword]) => text.includes(keyword));
    if (city) put(out, 'Регион', city[1]);
    if (hasAny(text, ['до конца месяца', 'к концу месяца'])) put(out, 'Желаемый срок', 'До конца месяца');
    put(out, 'Наличие, цена, условия', 'Требует подтверждения');
  }
  return out;
}
function abortableDelay(signal, ms = 760) {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, ms);
    function abort() { clearTimeout(timer); signal?.removeEventListener('abort', abort); reject(signal.reason ?? new DOMException('Aborted', 'AbortError')); }
    signal?.addEventListener('abort', abort, { once: true });
  });
}

export async function mockAgent(request, { signal } = {}) {
  await abortableDelay(signal);
  const text = userText(request);
  const scenario = request.scenario ?? inferScenario(request, text);
  const deployment = scenario === 'known' ? deploymentFor(request) : undefined;
  const requirements = requirementsFor(text, scenario, deployment);
  const protection = scenario === 'known' ? protectionFor(request) : undefined;
  if (protection) put(requirements, 'Уровень защиты', protection);
  let products = [];
  let reply;
  let suggestedReplies;
  let trace;
  if (scenario === 'known') {
    const server = deployment === 'Серверная инфраструктура';
    const clarified = protection || hasAny(text, ['сертифик', 'защищ', 'сервер', 'рабоч', 'пк', 'компьютер']);
    const workstation = protection === 'Максимальный' ? maximumProduct : protection === 'Усиленный' ? enhancedProduct : desktopProduct;
    const selected = server ? serverProduct : workstation;
    const alternative = server ? workstation : protection === 'Максимальный' ? enhancedProduct : protection === 'Усиленный' ? maximumProduct : serverProduct;
    if (clarified) products = [{ ...selected }, { ...alternative, recommended: false }];
    reply = !clarified
      ? 'Уточните, пожалуйста: Astra Linux нужна для рабочих станций или серверов? Сколько устройств и нужна ли сертифицированная редакция?'
      : server
        ? 'Для серверного сценария рассмотрите серверную редакцию Astra Linux; точный продукт и конфигурацию нужно подтвердить по нагрузке и требованиям защиты. Если речь о Special Edition для рабочих станций, это другой вариант. Цена, наличие и лицензирование требуют подтверждения.'
        : 'Для рабочих станций в защищённом контуре предварительно подходит Astra Linux Special Edition 1.8. Уточните объём миграции и поддержку, если они нужны. Цена, наличие и лицензирование требуют подтверждения.';
    suggestedReplies = clarified
      ? [server ? 'Нужны рабочие станции' : protection === 'Максимальный' ? ENHANCED_REPLY : MAXIMUM_REPLY, server ? 'Нужна поддержка' : 'Нужна серверная ОС', 'Уточнить миграцию']
      : ['80 ПК, нужен усиленный уровень защиты', 'Нужна серверная ОС', 'Обычные офисные ПК'];
    trace = clarified ? [{ label: 'Сценарий учтён', detail: server ? 'Запрос переключён на серверный вариант.' : 'Запрос сопоставлен с рабочими станциями.' }, { label: 'Коммерческие условия', detail: 'Требуют подтверждения.' }] : [{ label: 'Нужно уточнение', detail: 'Пока недостаточно сведений для рекомендации.' }];
    if (!server && protection) {
      reply = `Для рабочих станций с уровнем защиты «${protection.toLowerCase()}» предварительно подходит ${selected.name} ${selected.version}. Применимость редакции и коммерческие условия нужно подтвердить по параметрам проекта.`;
      trace.splice(1, 0, { label: 'Выбрана редакция', detail: `Учтён указанный уровень защиты: ${protection.toLowerCase()}.` });
    }
  } else if (scenario === 'discovery') {
    const clarified = hasAny(text, ['документ', 'таблиц', 'презентац', 'совместн', 'локальн', 'облак', 'почт']);
    if (clarified) products = [{ ...r7Product }];
    const bits = [];
    const userCount = requirements.find((r) => r.label === 'Пользователи');
    if (userCount) bits.push(`${userCount.value} пользователей`);
    const apps = requirements.find((r) => r.label === 'Приложения');
    if (apps) bits.push(apps.value.toLowerCase());
    if (requirements.some((r) => r.label === 'Совместная работа')) bits.push('совместное редактирование');
    const placement = requirements.find((r) => r.label === 'Размещение данных');
    if (placement) bits.push(placement.value.toLowerCase());
    reply = clarified
      ? `По указанным требованиям${bits.length ? ` (${bits.join(', ')})` : ''} можно рассмотреть Р7-Офис для бизнеса. Уточните почтовую платформу и целевую инфраструктуру; локальный вариант и состав поставки требуют подтверждения.`
      : 'Чтобы подобрать офисное ПО, уточните число пользователей, нужные приложения, совместную работу и требования к хранению данных.';
    suggestedReplies = clarified ? ['Уточнить инфраструктуру', 'Почта на Exchange', 'Сравнить лицензии'] : ['35 человек, документы и таблицы', 'Нужно совместное редактирование', 'Данные храним локально'];
    trace = clarified ? [{ label: 'Требования учтены', detail: 'Рекомендация сформирована по параметрам из сообщений пользователя.' }, { label: 'Условия поставки', detail: 'Конфигурацию и локальное размещение нужно подтвердить.' }] : [{ label: 'Нужно уточнение', detail: 'Категория известна, параметры команды пока не собраны.' }];
  } else {
    const product = hasAny(text, ['astra', 'linux']) ? desktopProduct : null;
    if (product) products = [{ ...product }];
    const facts = requirements.filter((r) => !['Вопрос', 'Наличие, цена, условия'].includes(r.label)).map((r) => `${r.label.toLowerCase()}: ${r.value}`);
    reply = `Проверка ${facts.length ? `по запросу (${facts.join('; ')}) ` : ''}не может быть подтверждена демо-данными. Актуальные наличие, цена, лицензирование и сроки требуют подтверждения у Softline Store.`;
    suggestedReplies = ['Уточнить тип лицензии', 'Добавить регион', 'Уточнить срок поставки'];
    trace = [{ label: 'Запрос зафиксирован', detail: facts.length ? facts.join('; ') : 'Продуктовые и поставочные параметры пока не указаны.' }, { label: 'Нужна проверка', detail: 'Наличие, цена и сроки требуют подтверждения.' }];
  }
  if (products.length && request.message.trim().toLowerCase() === QUOTE_REPLY.toLowerCase()) {
    const product = products[0];
    const quoteLabels = ['Количество', 'Пользователи', 'Регион', 'Желаемый срок', 'Размещение данных', 'Услуги'];
    const quoteDetails = requirements
      .filter(({ label }) => quoteLabels.includes(label))
      .map(({ label, value }) => `${label} — ${value}.`);
    reply = [
      'Черновик запроса на КП для Softline Store',
      `Просим подготовить предложение по продукту ${product.name} (${product.version}). Укажите тип лицензии, цену, доступность и срок поставки.`,
      ...quoteDetails,
      'Статус — черновик в чате.',
    ].join('\n');
    trace.push({ label: 'Подготовлен черновик', detail: 'Добавлены текущий кандидат и известные параметры проекта.' });
  }
  return {
    conversationId: request.conversationId ?? `demo-${globalThis.crypto?.randomUUID?.() ?? Date.now().toString(36)}`,
    messages: [...(request.history ?? []), { role: 'user', content: request.message }, { role: 'assistant', content: reply }],
    reply, requirements, products, sources: sourcesFor(products), trace, suggestedReplies,
  };
}
