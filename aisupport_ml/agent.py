import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic

from .contracts import (
    Action, Claim, Evidence, IntentModel, Proposal, ReadTools, Step, TemporaryReadError,
    Ticket, Usage,
)
from .intent import classify


@dataclass(frozen=True)
class Investigation:
    proposal: Proposal
    steps: tuple[Step, ...]
    usage: Usage | None
    duration_ms: int


class ReadUnavailable(Exception):
    pass


class InvestigationRun:
    def __init__(self, ticket, tools, version, now, max_calls, timeout, read_timeout):
        self.ticket = ticket
        self.tools = tools
        self.version = version
        self.now = now
        self.remaining_calls = max_calls
        self.started = monotonic()
        self.deadline = self.started + timeout
        self.read_timeout = read_timeout
        self.retry_available = True
        self.evidence = {}
        self.steps = []
        self.claims = []
        self.usage = None

    def remaining_time(self):
        return max(0.0, self.deadline - monotonic())

    def record(self, evidence: Evidence, source: str):
        if (not evidence.id or evidence.source != source or not evidence.record_id
                or evidence.observed_at.tzinfo is None):
            raise ReadUnavailable
        previous = self.evidence.get(evidence.id)
        if previous is not None and previous != evidence:
            raise ReadUnavailable
        self.evidence[evidence.id] = evidence
        return evidence.id

    async def read(self, name, reason, *args, capture=lambda result: ()):
        if name not in self.ticket.allowed_tools:
            self.steps.append(Step(name, reason, "unavailable", 0))
            raise ReadUnavailable
        while self.remaining_calls > 0 and self.remaining_time() > 0:
            self.remaining_calls -= 1
            start = monotonic()
            try:
                async with asyncio.timeout(min(self.read_timeout, self.remaining_time())):
                    result = await getattr(self.tools, name)(self.ticket, *args)
                ids = capture(result)
            except (TemporaryReadError, TimeoutError):
                retry = self.retry_available and self.remaining_calls > 0 and self.remaining_time() > 0
                self.steps.append(Step(name, reason, "retry" if retry else "unavailable", elapsed(start)))
                if retry:
                    self.retry_available = False
                    continue
                raise ReadUnavailable from None
            except ReadUnavailable:
                self.steps.append(Step(name, reason, "unavailable", elapsed(start)))
                raise
            self.steps.append(Step(name, reason, "ok", elapsed(start), ids))
            return result
        self.steps.append(Step(name, reason, "unavailable", 0))
        raise ReadUnavailable

    def finish(self, outcome, summary, missing=(), reply=None, action=None):
        proposal = Proposal(
            self.version, outcome, summary, tuple(self.claims), tuple(self.evidence.values()),
            action, reply, missing, "support" if outcome == "escalate" else None,
        )
        return Investigation(proposal, tuple(self.steps), self.usage, elapsed(self.started))

    def escalate(self, summary, *missing):
        return self.finish("escalate", summary, missing)

    async def investigate(self, model):
        try:
            async with asyncio.timeout(self.remaining_time()):
                intent, self.usage = await classify(model, self.ticket.text)
        except (TimeoutError, ValueError, TemporaryReadError):
            return self.escalate("Не удалось определить тип обращения.", "intent")
        if intent.kind != "delivery_delay":
            return self.escalate("Обращение требует ручной обработки.", "supported_intent")

        customer = await self.read(
            "get_customer_for_ticket", "Подтвердить связь тикета с клиентом.",
            capture=lambda item: (self.record(item, "crm"),) if item else (),
        )
        if customer is None:
            return self.finish(
                "needs_clarification", "CRM не подтверждает связь тикета с клиентом.",
                ("customer_link",), "Уточните, пожалуйста, номер заказа.",
            )
        candidates = await self.read(
            "find_orders", "Найти заказ подтверждённого клиента.", customer.record_id, intent.order_hint,
        )
        candidates = tuple(dict.fromkeys(candidates))
        if len(candidates) != 1 or (intent.order_hint and candidates[0] != intent.order_hint):
            return self.finish(
                "needs_clarification", "Не удалось однозначно определить заказ.",
                ("order_id",), "Уточните, пожалуйста, номер заказа.",
            )

        def capture_order(order):
            if order is None:
                return ()
            if (order.id != candidates[0] or order.customer_id != customer.record_id
                    or order.evidence.record_id != order.id or not order.evidence.version
                    or order.promised_at.tzinfo is None):
                raise ReadUnavailable
            return (self.record(order.evidence, "orders"),)

        order = await self.read(
            "get_order", "Перепроверить принадлежность, статус и версию заказа.",
            customer.record_id, candidates[0], capture=capture_order,
        )
        if order is None:
            return self.escalate("Источник не подтвердил заказ.", "verified_order")

        overdue = self.now > order.promised_at
        if intent.disputed_status or (overdue and order.status != "delayed"):
            event = await self.read(
                "get_order_events", "Сверить статус заказа с последним событием доставки.", order.id,
                capture=lambda item: (self.record(item.evidence, "orders"),) if item else (),
            )
            if event is None or event.status != order.status:
                return self.escalate("Статус доставки требует сверки.", "consistent_delivery_status")
        if intent.prior_contact:
            await self.read(
                "get_related_cases", "Проверить дубли и предыдущие обещания.", order.id,
                capture=lambda items: tuple(self.record(item, "crm") for item in items),
            )

        if not overdue or order.status != "delayed":
            return self.escalate("Данные заказа не подтверждают просрочку доставки.", "confirmed_delay")
        self.claims.append(Claim("Срок доставки прошёл, заказ в статусе задержки.", (order.evidence.id,)))

        for query in ("задержка доставки", "просрочка срок доставки"):
            policies = await self.read(
                "search_policy", "Найти выдержку регламента по задержке.", order, query,
                capture=lambda items: tuple(self.record(item, "kb") for item in items),
            )
            if policies:
                break

        decision = await self.read(
            "authorize_delivery_inquiry", "Проверить утверждённые правила, исключения и дубли.",
            order, tuple(self.evidence.values()),
            capture=lambda item: tuple(self.record(evidence, "kb") for evidence in item.evidence),
        )
        if not decision.allowed:
            return self.escalate(
                decision.reason or "Регламент не разрешает предложить запрос.",
                *decision.missing_data,
            )
        if not decision.evidence or any(not item.version for item in decision.evidence):
            return self.escalate("Нет подтверждения действующей версии правила.", "approved_policy")
        ids = tuple(dict.fromkeys(
            [customer.id, order.evidence.id, *(item.id for item in decision.evidence)]
        ))
        return self.finish(
            "resolved", "Срок доставки прошёл. Можно предложить запрос в службу доставки.",
            reply="По данным заказа, доставка задерживается.",
            action=Action("act_1", "create_delivery_inquiry", order.id, ids),
        )


def elapsed(start):
    return round((monotonic() - start) * 1000)


async def investigate(
    ticket: Ticket, tools: ReadTools, model: IntentModel, *,
    version: int = 1, max_calls: int = 8, timeout: float = 45.0,
    read_timeout: float = 5.0, now: datetime | None = None,
) -> Investigation:
    """Worker entry point. Adapters must enforce access and respect cancellation."""
    now = now if now is not None else datetime.now(timezone.utc)
    if version < 1 or max_calls < 1 or timeout <= 0 or read_timeout <= 0 or now.tzinfo is None:
        raise ValueError("Invalid investigation configuration")
    run = InvestigationRun(ticket, tools, version, now, max_calls, timeout, read_timeout)
    try:
        return await run.investigate(model)
    except ReadUnavailable:
        step = run.steps[-1]
        return run.escalate("Не удалось завершить обязательную проверку.", step.tool)
