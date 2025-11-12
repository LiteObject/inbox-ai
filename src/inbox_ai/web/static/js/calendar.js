/**
 * Google Calendar sync functionality for follow-up tasks
 */

import { ToastManager } from "./modules/toast.js";

(function () {
    'use strict';

    // Initialize toast manager with the existing container
    const toastManager = new ToastManager({
        container: document.getElementById("toast-container"),
    });

    // Get CSRF token
    function getCsrfToken() {
        const tokenInput = document.querySelector('input[name="csrf_token"]');
        return tokenInput ? tokenInput.value : '';
    }

    // Sync follow-up to calendar
    async function syncToCalendar(taskId, button) {
        const originalText = button.innerHTML;
        button.disabled = true;
        button.innerHTML = '<span class="material-icons rotating" aria-hidden="true">hourglass_empty</span> Syncing...';

        try {
            const response = await fetch(`/api/follow-ups/${taskId}/sync-calendar`, {
                method: 'POST',
                headers: {
                    'X-CSRF-Token': getCsrfToken(),
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();

            if (data.success) {
                if (data.already_synced) {
                    // Already synced - convert to view button
                    toastManager.show('Task already synced to calendar', 'info');
                    convertToViewButton(button, data.event_url);
                } else {
                    // Newly synced
                    toastManager.show('Follow-up added to Google Calendar!', 'success');
                    convertToViewButton(button, data.event_url);
                }

                // Update the follow-up task data in the DOM if available
                if (data.followUp) {
                    updateFollowUpInDOM(taskId, data.followUp);
                }
            } else {
                // Handle error
                toastManager.show(data.error || 'Failed to sync to calendar', 'error');
                button.disabled = false;
                button.innerHTML = originalText;
            }
        } catch (error) {
            console.error('Calendar sync error:', error);
            toastManager.show('Failed to sync to calendar. Please try again.', 'error');
            button.disabled = false;
            button.innerHTML = originalText;
        }
    }

    // Update follow-up data in the DOM
    function updateFollowUpInDOM(taskId, followUpData) {
        // Store in a data attribute so it persists across page refreshes
        const taskElement = document.querySelector(`[data-task-id="${taskId}"]`);
        if (taskElement) {
            taskElement.dataset.calendarEventId = followUpData.calendarEventId || '';
            taskElement.dataset.calendarSyncedAt = followUpData.calendarSyncedAt || '';
        }
    }

    // Convert sync button to view button
    function convertToViewButton(button, eventUrl) {
        // Get task ID and event ID from the button or extract from URL
        const taskId = button.dataset.taskId;
        const eventIdMatch = eventUrl.match(/events\/([^/?]+)/);
        const eventId = eventIdMatch ? eventIdMatch[1] : null;

        // Create a new anchor element to match template structure
        const link = document.createElement('a');
        link.href = 'javascript:void(0)';  // Changed from '#' to prevent navigation
        link.className = 'md3-button md3-button--text calendar-view-btn';
        link.dataset.taskId = taskId;
        link.dataset.eventId = eventId;
        link.dataset.eventUrl = eventUrl;  // Store the full URL for later use
        link.title = 'View in Google Calendar';
        link.innerHTML = `
            <span class="material-icons" aria-hidden="true">event</span>
            View Calendar
        `;

        // Replace the button with the link
        button.parentNode.replaceChild(link, button);

        // Event listener will be attached via event delegation, no need to attach here
    }

    // Unified click handler for all calendar buttons
    function handleCalendarClick(e) {
        // Check for view button click FIRST (higher priority)
        const viewButton = e.target.closest('.calendar-view-btn');
        if (viewButton) {
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();

            // Prevent any default link behavior
            if (viewButton.tagName === 'A') {
                viewButton.onclick = function () { return false; };
            }

            const taskId = viewButton.dataset.taskId;
            const eventId = viewButton.dataset.eventId;
            const eventUrl = viewButton.dataset.eventUrl;

            console.log('View button clicked:', { taskId, eventId, eventUrl });

            if (!taskId) {
                toastManager.show('Invalid task ID', 'error');
                return false;
            }

            // Check if the calendar event still exists
            checkAndHandleCalendarEvent(taskId, eventId, eventUrl, viewButton);
            return false; // Explicitly prevent any further action
        }

        // Check for sync button click
        const syncButton = e.target.closest('.calendar-sync-btn');
        if (syncButton) {
            e.preventDefault();
            e.stopPropagation();

            const taskId = syncButton.dataset.taskId;
            if (!taskId) {
                toastManager.show('Invalid task ID', 'error');
                return false;
            }

            syncToCalendar(taskId, syncButton);
            return false;
        }
    }

    // Separate async function for checking calendar event
    async function checkAndHandleCalendarEvent(taskId, eventId, eventUrl, viewButton) {
        console.log('Checking calendar event existence for task:', taskId);

        try {
            const response = await fetch(`/api/follow-ups/${taskId}/check-calendar-event`);
            const data = await response.json();

            console.log('Calendar check response:', data);

            if (!data.success) {
                if (data.exists === false) {
                    // Event was deleted - revert button to "Add to Calendar"
                    console.log('Event was deleted, converting button back');
                    toastManager.show('Calendar event was deleted. You can add it again.', 'warning');
                    convertToSyncButton(viewButton);
                } else {
                    // Other error
                    console.log('Error checking event:', data.error);
                    toastManager.show(data.error || 'Failed to verify calendar event', 'error');
                }
                return;
            }

            // Event exists - open it in Google Calendar
            console.log('Event exists, opening in calendar');
            // Use the API response URL, or construct it from eventId if needed
            const urlToOpen = data.event_url || eventUrl || (eventId ? `https://calendar.google.com/calendar/r/events/${eventId}` : null);
            if (urlToOpen) {
                console.log('Opening URL:', urlToOpen);
                window.open(urlToOpen, '_blank', 'noopener,noreferrer');
            } else {
                toastManager.show('Unable to open calendar event', 'error');
            }
        } catch (error) {
            console.error('Failed to check calendar event:', error);
            toastManager.show('Failed to verify calendar event', 'error');
        }
    }

    // Convert view button back to sync button
    function convertToSyncButton(oldElement) {
        const taskId = oldElement.dataset.taskId;

        // Create a new button element
        const button = document.createElement('button');
        button.className = 'md3-button md3-button--text calendar-sync-btn';
        button.type = 'button';
        button.dataset.taskId = taskId;
        button.title = 'Add to Google Calendar';
        button.innerHTML = `
            <span class="material-icons" aria-hidden="true">event</span>
            Add to Calendar
        `;

        // Replace the old element with the new button
        oldElement.parentNode.replaceChild(button, oldElement);

        // Event listener will be attached via event delegation, no need to attach here
    }

    // Initialize calendar sync buttons with event delegation
    function initCalendarButtons() {
        // Only register once - check if already registered
        if (!window.InboxAI?.calendar?.initialized) {
            // Use capturing phase so we intercept before other handlers
            document.addEventListener('click', handleCalendarClick, true);

            // Fallback to block default navigation on view links
            document.addEventListener(
                'click',
                (event) => {
                    const link = event.target.closest('.calendar-view-btn');
                    if (link && link.tagName === 'A') {
                        event.preventDefault();
                        event.stopPropagation();
                    }
                },
                true,
            );

            // Mark as initialized
            window.InboxAI = window.InboxAI || {};
            window.InboxAI.calendar = window.InboxAI.calendar || {};
            window.InboxAI.calendar.initialized = true;
            console.log('Calendar button handlers initialised (capturing phase)');
        }
    }

    // Initialize on page load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCalendarButtons);
    } else {
        initCalendarButtons();
    }

    // Export for potential external use
    window.InboxAI = window.InboxAI || {};
    window.InboxAI.calendar = {
        ...window.InboxAI.calendar,
        sync: syncToCalendar,
        init: initCalendarButtons
    };
})();