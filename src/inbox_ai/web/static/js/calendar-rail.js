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

function parseTaskNode(node) {
    const dueAt = node.dataset.taskDueAt ? new Date(node.dataset.taskDueAt) : null;
    const dueDate = dueAt && !Number.isNaN(dueAt.getTime()) ? dueAt : null;

    return {
        taskId: node.dataset.taskId || '',
        emailUid: node.dataset.emailUid || '',
        emailSubject: node.dataset.emailSubject || '(no subject)',
        emailSender: node.dataset.emailSender || 'Unknown sender',
        action: node.dataset.taskAction || 'Follow up',
        status: node.dataset.taskStatus || 'open',
        dueAt: node.dataset.taskDueAt || '',
        dueAtDisplay: node.dataset.taskDueDisplay || 'No due date',
        dueDate,
        dateKey: dueDate ? toDateKey(dueDate) : null,
        calendarEventId: node.dataset.calendarEventId || '',
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

const CALENDAR_RAIL_COLLAPSED_STORAGE_KEY = 'dashboard.calendarRail.calendarCollapsed';

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

        this.tasks = Array.from(this.dataRoot.querySelectorAll('[data-calendar-rail-task]'))
            .map(parseTaskNode)
            .sort(compareTasks);

        const firstDatedTask = this.tasks.find((task) => task.dueDate);
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
            const emailTasks = this.tasks
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
    }

    shiftMonth(offset) {
        this.currentMonth = new Date(
            this.currentMonth.getFullYear(),
            this.currentMonth.getMonth() + offset,
            1,
        );
        this.render();
    }

    jumpToToday() {
        const today = new Date();
        this.selectedDateKey = toDateKey(today);
        this.currentMonth = new Date(today.getFullYear(), today.getMonth(), 1);
        this.render();
    }

    selectDate(dateKey) {
        this.selectedDateKey = dateKey;
        this.renderCalendarGrid();
    }

    selectTask(task) {
        if (task?.dateKey && task.dueDate) {
            this.selectedDateKey = task.dateKey;
            this.pendingSelectedDateKey = task.dateKey;
            this.currentMonth = new Date(
                task.dueDate.getFullYear(),
                task.dueDate.getMonth(),
                1,
            );
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

            this.tasks = this.tasks.filter((task) => String(task.taskId) !== String(taskId));

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

    buildAgendaGroups() {
        const today = startOfDay(new Date());
        const nextWeekEnd = addDays(today, 7);
        const agendaTasks = this.tasks.filter((task) => task.dueDate && task.status !== 'done');

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

        const index = this.tasks.findIndex((task) => String(task.taskId) === String(updated.id));
        if (index === -1) {
            return;
        }

        const nextDueDate = updated.dueAt ? new Date(updated.dueAt) : null;
        const dueDate = nextDueDate && !Number.isNaN(nextDueDate.getTime()) ? nextDueDate : null;
        this.tasks[index] = {
            ...this.tasks[index],
            status: updated.status || this.tasks[index].status,
            dueAt: updated.dueAt || this.tasks[index].dueAt,
            dueAtDisplay: updated.dueAtDisplay || this.tasks[index].dueAtDisplay,
            dueDate,
            dateKey: dueDate ? toDateKey(dueDate) : null,
            calendarEventId: updated.calendarEventId || '',
        };
        this.tasks.sort(compareTasks);
        this.render();
    }

    render() {
        this.renderMonthHeader();
        this.renderCalendarGrid();
        this.renderFocus();
        this.renderAgenda();
    }

    renderMonthHeader() {
        const monthFormatter = new Intl.DateTimeFormat(undefined, {
            month: 'long',
            year: 'numeric',
        });
        this.monthLabel.textContent = monthFormatter.format(this.currentMonth);
        const today = new Date();

        const taskCount = this.tasks.filter((task) => {
            if (!task.dueDate) {
                return false;
            }
            return task.dueDate.getFullYear() === this.currentMonth.getFullYear()
                && task.dueDate.getMonth() === this.currentMonth.getMonth();
        }).length;
        this.monthMeta.textContent = taskCount === 0
            ? 'Nothing dated this month'
            : `${taskCount} due${taskCount === 1 ? '' : 's'} this month`;

        if (this.todayButton) {
            this.todayButton.disabled = isSameMonth(this.currentMonth, today)
                && this.selectedDateKey === toDateKey(today);
        }
    }

    renderCalendarGrid() {
        const monthStart = new Date(this.currentMonth.getFullYear(), this.currentMonth.getMonth(), 1);
        const gridStart = new Date(monthStart);
        gridStart.setDate(monthStart.getDate() - monthStart.getDay());

        const todayKey = toDateKey(new Date());
        const focusDateKeys = new Set(
            this.tasks
                .filter((task) => task.emailUid === this.selectedEmailUid && task.dateKey)
                .map((task) => task.dateKey),
        );

        const cells = [];
        for (let dayOffset = 0; dayOffset < 42; dayOffset += 1) {
            const cellDate = new Date(gridStart);
            cellDate.setDate(gridStart.getDate() + dayOffset);
            const dateKey = toDateKey(cellDate);
            const taskCount = this.tasks.filter((task) => task.dateKey === dateKey).length;
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
        if (!this.selectedEmailUid) {
            this.focusMeta.textContent = 'Choose one';
            this.focusBody.innerHTML = '<p>Select an email to pin its due dates on the month grid.</p>';
            return;
        }

        const emailTasks = this.tasks.filter((task) => task.emailUid === this.selectedEmailUid);
        const firstTask = emailTasks[0];

        if (!firstTask) {
            this.focusMeta.textContent = 'No follow-ups';
            this.focusBody.innerHTML = '<p>This email does not have follow-up tasks yet.</p>';
            return;
        }

        const openTasks = emailTasks.filter((task) => task.status !== 'done').length;
        const datedTasks = emailTasks.filter((task) => task.dueDate);
        const nextDue = datedTasks[0]?.dueAtDisplay || 'No due date';

        this.focusMeta.textContent = openTasks === 0
            ? 'All done'
            : `${openTasks} open`;
        this.focusBody.innerHTML = `
            <p class="calendar-rail__focus-kicker">Selected message</p>
            <p class="calendar-rail__focus-title">${firstTask.emailSubject}</p>
            <p class="calendar-rail__focus-caption">${firstTask.emailSender}</p>
            <div class="calendar-rail__focus-chip-row">
                <span class="calendar-rail__focus-chip">${emailTasks.length} total</span>
                <span class="calendar-rail__focus-chip">Due: ${nextDue}</span>
            </div>
        `;
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
                    <p class="calendar-rail__empty-copy">Open follow-ups only show up here when they are overdue, due today, or due within the next 7 days.</p>
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
                                    <button type="button" class="calendar-rail__agenda-item-select" data-task-id="${task.taskId}">
                                        <p class="calendar-rail__agenda-time">${task.dueAtDisplay || 'No time set'}</p>
                                        <div class="calendar-rail__agenda-main">
                                            <p class="calendar-rail__agenda-title">${task.action}</p>
                                            <p class="calendar-rail__agenda-subtitle">${task.emailSubject}</p>
                                            <div class="calendar-rail__agenda-badges">
                                                ${group.key === 'overdue' ? '<span class="calendar-rail__agenda-badge calendar-rail__agenda-badge--overdue">Late</span>' : ''}
                                                ${task.calendarEventId ? '<span class="calendar-rail__agenda-badge calendar-rail__agenda-badge--calendar">In calendar</span>' : ''}
                                            </div>
                                        </div>
                                    </button>
                                    <button
                                        type="button"
                                        class="md3-icon-button calendar-rail__agenda-delete"
                                        data-task-delete-id="${task.taskId}"
                                        aria-label="Delete follow-up task ${task.action}"
                                        title="Delete follow-up"
                                    >
                                        <span class="material-icons" aria-hidden="true">delete_outline</span>
                                    </button>
                                </div>
                            `;
            }).join('')}
                    </div>
                </section>
            `;
        }).join('');

        this.agenda.querySelectorAll('[data-task-id]').forEach((button) => {
            button.addEventListener('click', () => {
                const task = this.tasks.find((entry) => String(entry.taskId) === String(button.dataset.taskId));
                if (task) {
                    this.selectTask(task);
                }
            });
        });

        this.agenda.querySelectorAll('[data-task-delete-id]').forEach((button) => {
            button.addEventListener('click', (event) => {
                event.stopPropagation();
                this.deleteTask(button.dataset.taskDeleteId, button);
            });
        });

        this.agenda.querySelectorAll('[data-agenda-group-toggle]').forEach((button) => {
            button.addEventListener('click', () => this.toggleAgendaGroup(button.dataset.agendaGroupToggle));
        });
    }
}

export default CalendarRailController;