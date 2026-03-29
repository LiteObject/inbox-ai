function toDateKey(date) {
    const year = date.getFullYear();
    const month = `${date.getMonth() + 1}`.padStart(2, '0');
    const day = `${date.getDate()}`.padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function startOfDay(date) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date, count) {
    const next = new Date(date);
    next.setDate(next.getDate() + count);
    return next;
}

function isSameMonth(left, right) {
    return left.getFullYear() === right.getFullYear()
        && left.getMonth() === right.getMonth();
}

function parseDateValue(value) {
    if (!value) {
        return null;
    }

    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatDateKey(dateKey) {
    if (!dateKey) {
        return 'Selected day';
    }

    const parsed = parseDateValue(`${dateKey}T00:00:00`);
    if (!parsed) {
        return 'Selected day';
    }

    return parsed.toLocaleDateString(undefined, {
        weekday: 'long',
        month: 'long',
        day: 'numeric',
    });
}

function parseTaskNode(node) {
    const dueDate = parseDateValue(node.dataset.taskDueAt || '');

    return {
        sourceType: 'follow-up',
        taskId: node.dataset.taskId || '',
        emailUid: node.dataset.emailUid || '',
        emailSubject: node.dataset.emailSubject || '(no subject)',
        emailSender: node.dataset.emailSender || 'Unknown sender',
        action: node.dataset.taskAction || 'Follow up',
        status: node.dataset.taskStatus || 'open',
        dueAt: node.dataset.taskDueAt || '',
        dueAtDisplay: node.dataset.taskDueDisplay || 'No due date',
        completedAt: node.dataset.taskCompletedAt || '',
        dueDate,
        dateKey: dueDate ? toDateKey(dueDate) : null,
        calendarEventId: node.dataset.calendarEventId || '',
        calendarEventUrl: node.dataset.calendarEventId
            ? `https://calendar.google.com/calendar/r/events/${node.dataset.calendarEventId}`
            : '',
        sourceLabel: 'Follow-up',
        isAllDay: false,
    };
}

function normalizeCalendarEvent(event) {
    const dueDate = event.isAllDay && event.dateKey
        ? parseDateValue(`${event.dateKey}T12:00:00`)
        : parseDateValue(event.startsAt || '');
    const eventId = event.id || '';
    const dateKey = event.dateKey || (dueDate ? toDateKey(dueDate) : null);

    return {
        sourceType: 'calendar-event',
        taskId: `calendar:${eventId}`,
        emailUid: '',
        emailSubject: event.location || 'Google Calendar',
        emailSender: event.location || 'Google Calendar',
        action: event.summary || 'Untitled event',
        status: 'scheduled',
        dueAt: event.startsAt || '',
        dueAtDisplay: event.startsAtDisplay || 'Scheduled',
        dueDate,
        dateKey,
        calendarEventId: eventId,
        calendarEventUrl: event.eventUrl || '',
        sourceLabel: event.location
            ? `Google Calendar · ${event.location}`
            : 'Google Calendar',
        isAllDay: Boolean(event.isAllDay),
    };
}

function compareTasks(a, b) {
    if (a.dueDate && b.dueDate) {
        return a.dueDate - b.dueDate;
    }
    if (a.dueDate) {
        return -1;
    }
    if (b.dueDate) {
        return 1;
    }
    return a.action.localeCompare(b.action);
}

function normalizeGroupingText(value) {
    return (value || '')
        .trim()
        .replace(/\s+/g, ' ')
        .toLowerCase();
}

function toMinuteKey(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
        return '';
    }

    return date.toISOString().slice(0, 16);
}

function compareDisplayItems(left, right) {
    return compareTasks(left.primaryTask, right.primaryTask);
}

const CALENDAR_RAIL_COLLAPSED_STORAGE_KEY = 'dashboard.calendarRail.calendarCollapsed';
const CALENDAR_EVENTS_ENDPOINT = '/api/calendar/events';

export class CalendarRailController {
    constructor(options = {}) {
        this.root = options.root;
        this.dataRoot = options.dataRoot;
        this.onSelectEmail = options.onSelectEmail;

        if (!this.root || !this.dataRoot) {
            return;
        }

        this.grid = this.root.querySelector('#calendar-rail-grid');
        this.monthLabel = this.root.querySelector('#calendar-rail-month-label');
        this.monthMeta = this.root.querySelector('#calendar-rail-month-meta');
        this.agenda = this.root.querySelector('#calendar-rail-agenda');
        this.agendaMeta = this.root.querySelector('#calendar-rail-agenda-meta');
        this.focusBody = this.root.querySelector('#calendar-rail-focus-body');
        this.focusMeta = this.root.querySelector('#calendar-rail-focus-meta');
        this.monthSection = this.root.querySelector('#calendar-rail-month');
        this.focusSection = this.root.querySelector('#calendar-rail-focus');
        this.prevButton = this.root.querySelector('#calendar-rail-prev');
        this.nextButton = this.root.querySelector('#calendar-rail-next');
        this.todayButton = this.root.querySelector('#calendar-rail-today');
        this.toggleButton = this.root.querySelector('#calendar-rail-toggle');

        this.followUpTasks = Array.from(this.dataRoot.querySelectorAll('[data-calendar-rail-task]'))
            .map(parseTaskNode)
            .sort(compareTasks);
        this.externalMonthEvents = [];
        this.externalAgendaEvents = [];
        this.calendarEventCache = new Map();
        this.externalEventsRequestId = 0;

        const firstDatedTask = this.followUpTasks.find((task) => task.dueDate);
        const initialDate = firstDatedTask?.dueDate ?? new Date();
        this.currentMonth = new Date(initialDate.getFullYear(), initialDate.getMonth(), 1);
        this.selectedDateKey = firstDatedTask?.dateKey ?? toDateKey(new Date());
        this.selectedEmailUid = null;
        this.pendingSelectedDateKey = null;
        this.collapsedGroupKeys = new Set();
        this.isCalendarCollapsed = this.loadCalendarCollapsedPreference();

        this.handleWindowTaskUpdate = this.handleWindowTaskUpdate.bind(this);

        this.prevButton?.addEventListener('click', () => this.shiftMonth(-1));
        this.nextButton?.addEventListener('click', () => this.shiftMonth(1));
        this.todayButton?.addEventListener('click', () => this.jumpToToday());
        this.toggleButton?.addEventListener('click', () => this.toggleCalendarVisibility());
        window.addEventListener('inboxai:calendar-followup-updated', this.handleWindowTaskUpdate);

        this.updateCalendarVisibility();
        this.render();
        void this.refreshExternalEvents();
    }

    getAllEntries() {
        const entries = [...this.followUpTasks];
        const syncedCalendarIds = new Set(
            this.followUpTasks
                .map((task) => task.calendarEventId)
                .filter(Boolean),
        );
        const seenTaskIds = new Set(entries.map((entry) => String(entry.taskId)));

        [this.externalMonthEvents, this.externalAgendaEvents].forEach((collection) => {
            collection.forEach((entry) => {
                if (entry.calendarEventId && syncedCalendarIds.has(entry.calendarEventId)) {
                    return;
                }

                const entryKey = String(entry.taskId);
                if (seenTaskIds.has(entryKey)) {
                    return;
                }

                seenTaskIds.add(entryKey);
                entries.push(entry);
            });
        });

        return entries.sort(compareTasks);
    }

    getPairingKey(task) {
        if (!task?.dateKey) {
            return null;
        }

        const titleKey = normalizeGroupingText(task.action);
        if (!titleKey) {
            return null;
        }

        const momentKey = task.isAllDay
            ? `${task.dateKey}|all-day`
            : toMinuteKey(task.dueDate);
        if (!momentKey) {
            return null;
        }

        return `${task.dateKey}|${momentKey}|${titleKey}`;
    }

    buildDisplayItem(task) {
        return {
            id: `single:${task.taskId}`,
            sourceType: task.sourceType,
            primaryTask: task,
            followUp: task.sourceType === 'follow-up' ? task : null,
            calendarEvent: task.sourceType === 'calendar-event' ? task : null,
            dueDate: task.dueDate,
            dateKey: task.dateKey,
            dueAtDisplay: task.dueAtDisplay,
            emailUid: task.emailUid || '',
            status: task.status,
        };
    }

    buildPairedDisplayItem(followUp, calendarEvent) {
        return {
            id: `paired:${followUp.taskId}:${calendarEvent.taskId}`,
            sourceType: 'paired',
            primaryTask: followUp,
            followUp,
            calendarEvent,
            dueDate: followUp.dueDate || calendarEvent.dueDate,
            dateKey: followUp.dateKey || calendarEvent.dateKey,
            dueAtDisplay: followUp.dueAtDisplay || calendarEvent.dueAtDisplay,
            emailUid: followUp.emailUid || '',
            status: followUp.status,
        };
    }

    getDisplayItems(entries = this.getAllEntries()) {
        const groupedEntries = new Map();
        const displayItems = [];

        entries.forEach((entry) => {
            const pairingKey = this.getPairingKey(entry);
            if (!pairingKey) {
                displayItems.push(this.buildDisplayItem(entry));
                return;
            }

            if (!groupedEntries.has(pairingKey)) {
                groupedEntries.set(pairingKey, {
                    followUps: [],
                    calendarEvents: [],
                });
            }

            const bucket = groupedEntries.get(pairingKey);
            if (entry.sourceType === 'follow-up') {
                bucket.followUps.push(entry);
            } else if (entry.sourceType === 'calendar-event') {
                bucket.calendarEvents.push(entry);
            } else {
                displayItems.push(this.buildDisplayItem(entry));
            }
        });

        groupedEntries.forEach((bucket) => {
            bucket.followUps.sort(compareTasks);
            bucket.calendarEvents.sort(compareTasks);

            while (bucket.followUps.length > 0 && bucket.calendarEvents.length > 0) {
                displayItems.push(
                    this.buildPairedDisplayItem(
                        bucket.followUps.shift(),
                        bucket.calendarEvents.shift(),
                    ),
                );
            }

            bucket.followUps.forEach((entry) => {
                displayItems.push(this.buildDisplayItem(entry));
            });
            bucket.calendarEvents.forEach((entry) => {
                displayItems.push(this.buildDisplayItem(entry));
            });
        });

        return displayItems.sort(compareDisplayItems);
    }

    getVisibleMonthRange() {
        const monthStart = new Date(this.currentMonth.getFullYear(), this.currentMonth.getMonth(), 1);
        const gridStart = new Date(monthStart);
        gridStart.setDate(monthStart.getDate() - monthStart.getDay());

        const gridEnd = new Date(gridStart);
        gridEnd.setDate(gridStart.getDate() + 42);

        return { start: gridStart, end: gridEnd };
    }

    getAgendaRange() {
        const today = startOfDay(new Date());
        return {
            start: today,
            end: addDays(today, 8),
        };
    }

    async fetchCalendarEvents(startDate, endDate) {
        const cacheKey = `${startDate.toISOString()}|${endDate.toISOString()}`;
        if (this.calendarEventCache.has(cacheKey)) {
            return this.calendarEventCache.get(cacheKey);
        }

        const url = new URL(CALENDAR_EVENTS_ENDPOINT, window.location.origin);
        url.searchParams.set('start', startDate.toISOString());
        url.searchParams.set('end', endDate.toISOString());

        const response = await fetch(url.toString());
        const payload = await response.json();

        if (!response.ok || payload.success === false) {
            if (payload.connected === false && !payload.error) {
                this.calendarEventCache.set(cacheKey, []);
                return [];
            }

            throw new Error(payload.error || 'Failed to load Google Calendar events');
        }

        const events = Array.isArray(payload.events)
            ? payload.events.map(normalizeCalendarEvent).filter((event) => event.dueDate)
            : [];
        this.calendarEventCache.set(cacheKey, events);
        return events;
    }

    async refreshExternalEvents() {
        const requestId = ++this.externalEventsRequestId;
        const monthRange = this.getVisibleMonthRange();
        const agendaRange = this.getAgendaRange();

        try {
            const [monthEvents, agendaEvents] = await Promise.all([
                this.fetchCalendarEvents(monthRange.start, monthRange.end),
                this.fetchCalendarEvents(agendaRange.start, agendaRange.end),
            ]);

            if (requestId !== this.externalEventsRequestId) {
                return;
            }

            this.externalMonthEvents = monthEvents;
            this.externalAgendaEvents = agendaEvents;
            this.render();
        } catch (error) {
            if (requestId !== this.externalEventsRequestId) {
                return;
            }

            console.error('Failed to load Google Calendar events:', error);
        }
    }

    loadCalendarCollapsedPreference() {
        try {
            return window.localStorage.getItem(CALENDAR_RAIL_COLLAPSED_STORAGE_KEY) === 'true';
        } catch {
            return false;
        }
    }

    persistCalendarCollapsedPreference() {
        try {
            window.localStorage.setItem(
                CALENDAR_RAIL_COLLAPSED_STORAGE_KEY,
                String(this.isCalendarCollapsed),
            );
        } catch {
            // Ignore storage failures and keep the control functional for the session.
        }
    }

    toggleCalendarVisibility() {
        this.isCalendarCollapsed = !this.isCalendarCollapsed;
        this.persistCalendarCollapsedPreference();
        this.updateCalendarVisibility();
    }

    updateCalendarVisibility() {
        this.root.classList.toggle('calendar-rail--calendar-collapsed', this.isCalendarCollapsed);

        if (this.monthSection) {
            this.monthSection.hidden = this.isCalendarCollapsed;
        }

        if (this.focusSection) {
            this.focusSection.hidden = this.isCalendarCollapsed;
        }

        if (this.toggleButton) {
            this.toggleButton.setAttribute('aria-expanded', String(!this.isCalendarCollapsed));
            this.toggleButton.innerHTML = this.isCalendarCollapsed
                ? '<span class="material-icons" aria-hidden="true">visibility</span><span>Show calendar</span>'
                : '<span class="material-icons" aria-hidden="true">visibility_off</span><span>Hide calendar</span>';
        }
    }

    setSelectedEmail(uid) {
        this.selectedEmailUid = uid || null;

        if (this.selectedEmailUid) {
            const emailTasks = this.followUpTasks
                .filter((task) => task.emailUid === this.selectedEmailUid && task.dueDate)
                .sort(compareTasks);
            if (emailTasks.length > 0) {
                const preservedDateKey = [this.pendingSelectedDateKey, this.selectedDateKey]
                    .find((candidate) => candidate && emailTasks.some((task) => task.dateKey === candidate));
                const focusTask = preservedDateKey
                    ? emailTasks.find((task) => task.dateKey === preservedDateKey)
                    : emailTasks[0];
                this.selectedDateKey = focusTask?.dateKey ?? emailTasks[0].dateKey;
                this.currentMonth = new Date(
                    focusTask.dueDate.getFullYear(),
                    focusTask.dueDate.getMonth(),
                    1,
                );
            }
        }

        this.pendingSelectedDateKey = null;

        this.render();
        void this.refreshExternalEvents();
    }

    shiftMonth(offset) {
        this.currentMonth = new Date(
            this.currentMonth.getFullYear(),
            this.currentMonth.getMonth() + offset,
            1,
        );
        this.render();
        void this.refreshExternalEvents();
    }

    jumpToToday() {
        const today = new Date();
        this.selectedDateKey = toDateKey(today);
        this.currentMonth = new Date(today.getFullYear(), today.getMonth(), 1);
        this.render();
        void this.refreshExternalEvents();
    }

    selectDate(dateKey) {
        this.selectedDateKey = dateKey;
        this.render();
    }

    selectTask(task) {
        if (!task) {
            return;
        }

        if (task?.dateKey && task.dueDate) {
            this.selectedDateKey = task.dateKey;
            this.pendingSelectedDateKey = task.dateKey;
            this.currentMonth = new Date(
                task.dueDate.getFullYear(),
                task.dueDate.getMonth(),
                1,
            );
        }

        if (task.sourceType === 'calendar-event') {
            this.render();
            if (task.calendarEventUrl) {
                window.open(task.calendarEventUrl, '_blank', 'noopener');
            }
            return;
        }

        this.selectedEmailUid = task?.emailUid || this.selectedEmailUid;
        this.render();

        if (task?.emailUid && typeof this.onSelectEmail === 'function') {
            this.onSelectEmail(task.emailUid);
        }
    }

    toggleAgendaGroup(groupKey) {
        if (this.collapsedGroupKeys.has(groupKey)) {
            this.collapsedGroupKeys.delete(groupKey);
        } else {
            this.collapsedGroupKeys.add(groupKey);
        }
        this.renderAgenda();
    }

    getCsrfToken() {
        const tokenInput = document.querySelector('input[name="csrf_token"]');
        return tokenInput ? tokenInput.value : '';
    }

    updateTaskSourceNode(taskId, followUpData) {
        const sourceNode = this.dataRoot.querySelector(`[data-calendar-rail-task][data-task-id="${CSS.escape(String(taskId))}"]`);
        if (!sourceNode) {
            return;
        }

        sourceNode.dataset.taskStatus = followUpData.status || '';
        sourceNode.dataset.taskDueAt = followUpData.dueAt || '';
        sourceNode.dataset.taskDueDisplay = followUpData.dueAtDisplay || '';
        sourceNode.dataset.taskCompletedAt = followUpData.completedAt || '';
        sourceNode.dataset.calendarEventId = followUpData.calendarEventId || '';
    }

    updateVisibleFollowUpState(taskId, followUpData) {
        const taskItems = document.querySelectorAll(`[data-follow-up-task-id="${CSS.escape(String(taskId))}"]`);
        taskItems.forEach((taskItem) => {
            const badges = taskItem.querySelectorAll('.task-badge');
            const dueBadge = badges[0];
            const statusBadge = taskItem.querySelector('.task-badge--status');
            if (dueBadge) {
                dueBadge.textContent = followUpData.dueAtDisplay
                    ? `Due ${followUpData.dueAtDisplay}`
                    : 'No due date';
            }

            if (statusBadge) {
                statusBadge.classList.toggle('task-badge--done', followUpData.status === 'done');
                statusBadge.textContent = `Status: ${followUpData.status}`;
            }

            const form = taskItem.querySelector(`form[action="/follow-ups/${CSS.escape(String(taskId))}/status"]`);
            if (!form) {
                return;
            }

            const statusInput = form.querySelector('input[name="status"]');
            if (statusInput) {
                statusInput.value = followUpData.status === 'done' ? 'open' : 'done';
            }

            const submitButton = form.querySelector('button[type="submit"]');
            if (submitButton) {
                submitButton.innerHTML = followUpData.status === 'done'
                    ? '<span class="material-icons" aria-hidden="true">undo</span>Reopen'
                    : '<span class="material-icons" aria-hidden="true">check_circle</span>Mark done';
            }
        });
    }

    async setTaskStatus(taskId, nextStatus, statusButton) {
        const originalLabel = statusButton?.innerHTML || '';

        if (statusButton) {
            statusButton.disabled = true;
            statusButton.innerHTML = '<span class="material-icons rotating" aria-hidden="true">hourglass_empty</span>';
        }

        try {
            const response = await fetch(`/api/follow-ups/${taskId}/status`, {
                method: 'POST',
                headers: {
                    'X-CSRF-Token': this.getCsrfToken(),
                },
                body: new URLSearchParams({ status: nextStatus }),
            });
            const data = await response.json();
            if (!response.ok || !data.success || !data.followUp) {
                throw new Error(data.error || 'Failed to update follow-up');
            }

            this.updateTaskSourceNode(taskId, data.followUp);
            this.updateVisibleFollowUpState(taskId, data.followUp);
            window.dispatchEvent(new CustomEvent('inboxai:calendar-followup-updated', {
                detail: {
                    taskId,
                    followUp: data.followUp,
                },
            }));

            window.InboxAI?.toast?.show?.(
                nextStatus === 'done' ? 'Follow-up marked done.' : 'Follow-up reopened.',
                'success',
            );
        } catch (error) {
            console.error('Failed to update follow-up task:', error);
            window.InboxAI?.toast?.show?.(
                error instanceof Error ? error.message : 'Failed to update follow-up',
                'error',
            );

            if (statusButton) {
                statusButton.disabled = false;
                statusButton.innerHTML = originalLabel;
            }
        }
    }

    async deleteTask(taskId, deleteButton) {
        const originalLabel = deleteButton?.innerHTML || '';

        if (deleteButton) {
            deleteButton.disabled = true;
            deleteButton.innerHTML = '<span class="material-icons rotating" aria-hidden="true">hourglass_empty</span>';
        }

        try {
            const response = await fetch(`/api/follow-ups/${taskId}`, {
                method: 'DELETE',
                headers: {
                    'X-CSRF-Token': this.getCsrfToken(),
                },
            });

            const data = await response.json();
            if (!data.success) {
                throw new Error(data.message || 'Failed to delete follow-up');
            }

            this.followUpTasks = this.followUpTasks.filter((task) => String(task.taskId) !== String(taskId));

            const sourceNode = this.dataRoot.querySelector(`[data-calendar-rail-task][data-task-id="${CSS.escape(String(taskId))}"]`);
            if (sourceNode) {
                sourceNode.remove();
            }

            window.dispatchEvent(new CustomEvent('inboxai:calendar-followup-deleted', {
                detail: { taskId },
            }));

            this.render();
            window.InboxAI?.toast?.show?.('Follow-up deleted.', 'success');
        } catch (error) {
            console.error('Failed to delete follow-up task:', error);
            window.InboxAI?.toast?.show?.(
                error instanceof Error ? error.message : 'Failed to delete follow-up',
                'error',
            );

            if (deleteButton) {
                deleteButton.disabled = false;
                deleteButton.innerHTML = originalLabel;
            }
        }
    }

    async convertEventToFollowUp(eventId, summary, startsAt, button) {
        const originalLabel = button?.innerHTML || '';

        if (button) {
            button.disabled = true;
            button.innerHTML = '<span class="material-icons rotating" aria-hidden="true">hourglass_empty</span>';
        }

        try {
            const response = await fetch('/api/calendar/events/to-follow-up', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': this.getCsrfToken(),
                },
                body: JSON.stringify({
                    eventId: eventId || '',
                    summary: summary || '',
                    startsAt: startsAt || '',
                }),
            });

            const data = await response.json();
            if (!response.ok || !data.success || !data.followUp) {
                throw new Error(data.error || 'Failed to create follow-up');
            }

            if (data.already_exists) {
                window.InboxAI?.toast?.show?.('Follow-up already exists for this event.', 'info');
            } else {
                const followUp = data.followUp;
                const dueDate = parseDateValue(followUp.dueAt || '');
                this.followUpTasks.push({
                    sourceType: 'follow-up',
                    taskId: String(followUp.id),
                    emailUid: '',
                    emailSubject: 'Google Calendar',
                    emailSender: 'Google Calendar',
                    action: followUp.action || summary,
                    status: followUp.status || 'open',
                    dueAt: followUp.dueAt || '',
                    dueAtDisplay: followUp.dueAtDisplay || 'No due date',
                    completedAt: followUp.completedAt || '',
                    dueDate,
                    dateKey: dueDate ? toDateKey(dueDate) : null,
                    calendarEventId: followUp.calendarEventId || '',
                    calendarEventUrl: followUp.calendarEventId
                        ? `https://calendar.google.com/calendar/r/events/${followUp.calendarEventId}`
                        : '',
                    sourceLabel: 'Follow-up',
                    isAllDay: false,
                });
                this.followUpTasks.sort(compareTasks);
                window.InboxAI?.toast?.show?.('Follow-up created from calendar event.', 'success');
            }

            this.render();
        } catch (error) {
            console.error('Failed to create follow-up from calendar event:', error);
            window.InboxAI?.toast?.show?.(
                error instanceof Error ? error.message : 'Failed to create follow-up',
                'error',
            );

            if (button) {
                button.disabled = false;
                button.innerHTML = originalLabel;
            }
        }
    }

    buildAgendaGroups() {
        const today = startOfDay(new Date());
        const nextWeekEnd = addDays(today, 7);
        const agendaEntries = this.getAllEntries().filter((task) => task.dueDate && task.status !== 'done');
        const agendaTasks = this.getDisplayItems(agendaEntries);

        return [
            {
                key: 'overdue',
                label: 'Overdue',
                tasks: agendaTasks.filter((task) => startOfDay(task.dueDate) < today),
            },
            {
                key: 'today',
                label: 'Today',
                tasks: agendaTasks.filter((task) => toDateKey(task.dueDate) === toDateKey(today)),
            },
            {
                key: 'next-7-days',
                label: 'Next 7 days',
                tasks: agendaTasks.filter((task) => {
                    const taskDay = startOfDay(task.dueDate);
                    return taskDay > today && taskDay <= nextWeekEnd;
                }),
            },
        ].map((group) => ({
            ...group,
            tasks: group.tasks.sort(compareTasks),
        }));
    }

    handleWindowTaskUpdate(event) {
        const updated = event.detail?.followUp;
        if (!updated?.id) {
            return;
        }

        const index = this.followUpTasks.findIndex((task) => String(task.taskId) === String(updated.id));
        if (index === -1) {
            return;
        }

        const dueDate = parseDateValue(updated.dueAt || '');
        this.followUpTasks[index] = {
            ...this.followUpTasks[index],
            status: updated.status || this.followUpTasks[index].status,
            dueAt: updated.dueAt || this.followUpTasks[index].dueAt,
            dueAtDisplay: updated.dueAtDisplay || this.followUpTasks[index].dueAtDisplay,
            completedAt: updated.completedAt || '',
            dueDate,
            dateKey: dueDate ? toDateKey(dueDate) : null,
            calendarEventId: updated.calendarEventId || '',
            calendarEventUrl: updated.calendarEventId
                ? `https://calendar.google.com/calendar/r/events/${updated.calendarEventId}`
                : '',
        };
        this.followUpTasks.sort(compareTasks);
        this.render();
    }

    render() {
        this.renderMonthHeader();
        this.renderCalendarGrid();
        this.renderFocus();
        this.renderAgenda();
    }

    renderMonthHeader() {
        const entries = this.getDisplayItems();
        const monthFormatter = new Intl.DateTimeFormat(undefined, {
            month: 'long',
            year: 'numeric',
        });
        this.monthLabel.textContent = monthFormatter.format(this.currentMonth);
        const today = new Date();

        const taskCount = entries.filter((task) => {
            if (!task.dueDate) {
                return false;
            }
            return task.dueDate.getFullYear() === this.currentMonth.getFullYear()
                && task.dueDate.getMonth() === this.currentMonth.getMonth();
        }).length;
        this.monthMeta.textContent = taskCount === 0
            ? 'Nothing scheduled this month'
            : `${taskCount} item${taskCount === 1 ? '' : 's'} this month`;

        if (this.todayButton) {
            this.todayButton.disabled = isSameMonth(this.currentMonth, today)
                && this.selectedDateKey === toDateKey(today);
        }
    }

    renderCalendarGrid() {
        const monthStart = new Date(this.currentMonth.getFullYear(), this.currentMonth.getMonth(), 1);
        const gridStart = new Date(monthStart);
        gridStart.setDate(monthStart.getDate() - monthStart.getDay());
        const entries = this.getDisplayItems();

        const todayKey = toDateKey(new Date());
        const focusDateKeys = new Set(
            this.followUpTasks
                .filter((task) => task.emailUid === this.selectedEmailUid && task.dateKey)
                .map((task) => task.dateKey),
        );

        const cells = [];
        for (let dayOffset = 0; dayOffset < 42; dayOffset += 1) {
            const cellDate = new Date(gridStart);
            cellDate.setDate(gridStart.getDate() + dayOffset);
            const dateKey = toDateKey(cellDate);
            const taskCount = entries.filter((task) => task.dateKey === dateKey).length;
            const isOutside = cellDate.getMonth() !== this.currentMonth.getMonth();
            const classes = [
                'calendar-rail__day',
                isOutside ? 'calendar-rail__day--outside' : '',
                dateKey === todayKey ? 'calendar-rail__day--today' : '',
                dateKey === this.selectedDateKey ? 'calendar-rail__day--selected' : '',
                focusDateKeys.has(dateKey) ? 'calendar-rail__day--has-email-focus' : '',
            ].filter(Boolean).join(' ');

            cells.push(`
                <button type="button" class="${classes}" data-date-key="${dateKey}" aria-label="${cellDate.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}">
                    <span class="calendar-rail__day-number">${cellDate.getDate()}</span>
                    ${taskCount > 0 ? `<span class="calendar-rail__day-marker">${taskCount}</span>` : '<span class="calendar-rail__day-marker" aria-hidden="true"></span>'}
                </button>
            `);
        }

        this.grid.innerHTML = cells.join('');
        this.grid.querySelectorAll('[data-date-key]').forEach((button) => {
            button.addEventListener('click', () => this.selectDate(button.dataset.dateKey));
        });
    }

    renderFocus() {
        const selectedDateLabel = formatDateKey(this.selectedDateKey);
        const entries = this.getDisplayItems()
            .filter((task) => task.dateKey === this.selectedDateKey)
            .sort(compareDisplayItems);
        const pinnedEntries = this.selectedEmailUid
            ? entries.filter((task) => task.emailUid === this.selectedEmailUid)
            : [];

        this.focusMeta.textContent = entries.length === 0
            ? 'Nothing scheduled'
            : `${entries.length} item${entries.length === 1 ? '' : 's'}`;

        if (entries.length === 0) {
            this.focusBody.innerHTML = `
                <p class="calendar-rail__focus-kicker">Selected day</p>
                <p class="calendar-rail__focus-title">${selectedDateLabel}</p>
                <p class="calendar-rail__focus-caption">No follow-ups or calendar events are scheduled for this day.</p>
            `;
            return;
        }

        const chipMarkup = [
            `<span class="calendar-rail__focus-chip">${entries.filter((task) => task.calendarEvent).length} calendar</span>`,
            `<span class="calendar-rail__focus-chip">${entries.filter((task) => task.followUp).length} follow-up${entries.filter((task) => task.followUp).length === 1 ? '' : 's'}</span>`,
            pinnedEntries.length > 0
                ? `<span class="calendar-rail__focus-chip">${pinnedEntries.length} for selected email</span>`
                : '',
        ].filter(Boolean).join('');

        this.focusBody.innerHTML = `
            <p class="calendar-rail__focus-kicker">Selected day</p>
            <p class="calendar-rail__focus-title">${selectedDateLabel}</p>
            <div class="calendar-rail__focus-chip-row">${chipMarkup}</div>
            <div class="calendar-rail__focus-list">
                ${entries.map((task) => `
                    <div class="calendar-rail__agenda-item ${task.emailUid === this.selectedEmailUid ? 'calendar-rail__agenda-item--focused' : ''}">
                        <button type="button" class="calendar-rail__agenda-item-select" data-focus-entry-id="${task.id}">
                            <p class="calendar-rail__agenda-time">${task.dueAtDisplay || 'No time set'}</p>
                            <div class="calendar-rail__agenda-main">
                                <p class="calendar-rail__agenda-title">${task.primaryTask.action}</p>
                                <p class="calendar-rail__agenda-subtitle">${task.followUp ? task.followUp.emailSubject : task.calendarEvent?.sourceLabel || 'Google Calendar'}</p>
                                <div class="calendar-rail__agenda-badges">
                                    ${task.followUp ? '<span class="calendar-rail__agenda-badge">Follow-up</span>' : ''}
                                    ${task.calendarEvent ? '<span class="calendar-rail__agenda-badge calendar-rail__agenda-badge--calendar">Google Calendar</span>' : ''}
                                    ${task.emailUid && task.emailUid === this.selectedEmailUid
                                        ? '<span class="calendar-rail__agenda-badge">Selected email</span>'
                                        : ''}
                                </div>
                            </div>
                        </button>
                    </div>
                `).join('')}
            </div>
        `;

        this.focusBody.querySelectorAll('[data-focus-entry-id]').forEach((button) => {
            button.addEventListener('click', () => {
                const task = this.getDisplayItems().find((entry) => String(entry.id) === String(button.dataset.focusEntryId));
                if (task) {
                    this.selectTask(task.followUp || task.calendarEvent || task.primaryTask);
                }
            });
        });
    }

    renderAgenda() {
        const groups = this.buildAgendaGroups();
        const visibleGroups = groups.filter((group) => group.tasks.length > 0);
        const totalCount = visibleGroups.reduce((sum, group) => sum + group.tasks.length, 0);

        this.agendaMeta.textContent = totalCount === 0
            ? 'Clear through next week'
            : `${totalCount} due soon`;

        if (visibleGroups.length === 0) {
            this.agenda.innerHTML = `
                <div class="calendar-rail__empty-state">
                    <p class="calendar-rail__empty-title">Nothing urgent is due.</p>
                    <p class="calendar-rail__empty-copy">Follow-ups and Google Calendar events only show up here when they are overdue, due today, or due within the next 7 days.</p>
                </div>
            `;
            return;
        }

        this.agenda.innerHTML = visibleGroups.map((group) => {
            const isCollapsed = this.collapsedGroupKeys.has(group.key);
            const groupClasses = [
                'calendar-rail__agenda-group',
                group.key === 'overdue' ? 'calendar-rail__agenda-group--overdue' : '',
            ].filter(Boolean).join(' ');
            return `
                <section class="${groupClasses}" aria-labelledby="calendar-rail-group-${group.key}">
                    <header class="calendar-rail__agenda-group-header">
                        <button
                            type="button"
                            class="calendar-rail__agenda-group-toggle"
                            data-agenda-group-toggle="${group.key}"
                            aria-expanded="${!isCollapsed}"
                            aria-controls="calendar-rail-group-list-${group.key}"
                        >
                            <span class="calendar-rail__agenda-group-summary">
                                <h5 class="calendar-rail__agenda-group-label" id="calendar-rail-group-${group.key}">${group.label}</h5>
                            </span>
                            <span class="calendar-rail__agenda-group-trailing">
                                <span class="calendar-rail__agenda-group-count">${group.tasks.length}</span>
                                <span class="material-icons calendar-rail__agenda-group-icon" aria-hidden="true">expand_more</span>
                            </span>
                        </button>
                    </header>
                    <div class="calendar-rail__agenda-group-list" id="calendar-rail-group-list-${group.key}" ${isCollapsed ? 'hidden' : ''}>
                        ${group.tasks.map((task) => {
                const classes = [
                    'calendar-rail__agenda-item',
                    group.key === 'overdue' ? 'calendar-rail__agenda-item--overdue' : '',
                    task.emailUid === this.selectedEmailUid ? 'calendar-rail__agenda-item--focused' : '',
                ].filter(Boolean).join(' ');
                return `
                                <div class="${classes}">
                                    <button type="button" class="calendar-rail__agenda-item-select" data-task-id="${task.id}">
                                        <p class="calendar-rail__agenda-time">${task.dueAtDisplay || 'No time set'}</p>
                                        <div class="calendar-rail__agenda-main">
                                            <p class="calendar-rail__agenda-title">${task.primaryTask.action}</p>
                                            <p class="calendar-rail__agenda-subtitle">${task.followUp ? task.followUp.emailSubject : task.calendarEvent?.sourceLabel || 'Google Calendar'}</p>
                                            <div class="calendar-rail__agenda-badges">
                                                ${group.key === 'overdue' ? '<span class="calendar-rail__agenda-badge calendar-rail__agenda-badge--overdue">Late</span>' : ''}
                                                ${task.followUp ? '<span class="calendar-rail__agenda-badge">Follow-up</span>' : ''}
                                                ${task.calendarEvent ? '<span class="calendar-rail__agenda-badge calendar-rail__agenda-badge--calendar">Google Calendar</span>' : ''}
                                            </div>
                                        </div>
                                    </button>
                                    ${task.followUp
                ? `
                                    <div class="calendar-rail__agenda-actions">
                                        <button
                                            type="button"
                                            class="md3-icon-button calendar-rail__agenda-done"
                                            data-task-status-id="${task.followUp.taskId}"
                                            data-task-next-status="done"
                                            aria-label="Mark follow-up task ${task.primaryTask.action} done"
                                            title="Mark done"
                                        >
                                            <span class="material-icons" aria-hidden="true">check_circle</span>
                                        </button>
                                        <button
                                            type="button"
                                            class="md3-icon-button calendar-rail__agenda-delete"
                                            data-task-delete-id="${task.followUp.taskId}"
                                            aria-label="Delete follow-up task ${task.primaryTask.action}"
                                            title="Delete follow-up"
                                        >
                                            <span class="material-icons" aria-hidden="true">delete_outline</span>
                                        </button>
                                    </div>
                                    `
                : task.calendarEvent && !task.followUp
                    ? `
                                    <div class="calendar-rail__agenda-actions">
                                        <button
                                            type="button"
                                            class="md3-icon-button calendar-rail__agenda-to-followup"
                                            data-event-to-followup-id="${task.calendarEvent.calendarEventId}"
                                            data-event-summary="${task.calendarEvent.action}"
                                            data-event-starts-at="${task.calendarEvent.dueAt}"
                                            aria-label="Create follow-up from ${task.primaryTask.action}"
                                            title="Create follow-up"
                                        >
                                            <span class="material-icons" aria-hidden="true">add_task</span>
                                        </button>
                                    </div>
                                    `
                    : ''}
                                </div>
                            `;
            }).join('')}
                    </div>
                </section>
            `;
        }).join('');

        this.agenda.querySelectorAll('[data-task-id]').forEach((button) => {
            button.addEventListener('click', () => {
                const task = this.getDisplayItems().find((entry) => String(entry.id) === String(button.dataset.taskId));
                if (task) {
                    this.selectTask(task.followUp || task.calendarEvent || task.primaryTask);
                }
            });
        });

        this.agenda.querySelectorAll('[data-task-delete-id]').forEach((button) => {
            button.addEventListener('click', (event) => {
                event.stopPropagation();
                this.deleteTask(button.dataset.taskDeleteId, button);
            });
        });

        this.agenda.querySelectorAll('[data-task-status-id]').forEach((button) => {
            button.addEventListener('click', (event) => {
                event.stopPropagation();
                this.setTaskStatus(
                    button.dataset.taskStatusId,
                    button.dataset.taskNextStatus || 'done',
                    button,
                );
            });
        });

        this.agenda.querySelectorAll('[data-agenda-group-toggle]').forEach((button) => {
            button.addEventListener('click', () => this.toggleAgendaGroup(button.dataset.agendaGroupToggle));
        });

        this.agenda.querySelectorAll('[data-event-to-followup-id]').forEach((button) => {
            button.addEventListener('click', (event) => {
                event.stopPropagation();
                this.convertEventToFollowUp(
                    button.dataset.eventToFollowupId,
                    button.dataset.eventSummary,
                    button.dataset.eventStartsAt,
                    button,
                );
            });
        });
    }
}

export default CalendarRailController;