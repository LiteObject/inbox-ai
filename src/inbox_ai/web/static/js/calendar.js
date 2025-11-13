/**
 * Google Calendar sync functionality for follow-up tasks
 */

import { ToastManager } from "./modules/toast.js";

/*
 * calendar.js
 *
 * Client-side logic for syncing follow-up tasks to Google Calendar and
 * keeping the UI in sync with calendar state.
 *
 * Key behaviors:
 *  - When a user clicks "Add to Calendar" the client calls the server
 *    endpoint to create the calendar event and updates DOM state.
 *  - When a user clicks "View Calendar" the client checks whether the
 *    calendar event still exists before navigating to Google Calendar.
 *  - Event delegation (on the document) handles dynamic DOM updates and
 *    avoids leaking per-element listeners.
 */
(function () {
    'use strict';

    // Initialize toast manager with the existing container
    const toastManager = new ToastManager({
        container: document.getElementById("toast-container"),
    });

    // Get CSRF token
    // Return the CSRF token value from the page. This is used by
    // sync operations that perform POST requests to prevent CSRF attacks.
    function getCsrfToken() {
        const tokenInput = document.querySelector('input[name="csrf_token"]');
        return tokenInput ? tokenInput.value : '';
    }

    // Sync follow-up to calendar
    // Create a calendar event for the given follow-up task.
    // The function disables the UI during the request, calls the backend
    // POST /api/follow-ups/{id}/sync-calendar and then converts the
    // button to a "View Calendar" link on success.
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
    // When a follow-up is modified, we persist the calendar-related
    // metadata into the DOM so that other client code (and the template)
    // can read the current sync state without a full refresh.
    // This keeps button rendering and logic consistent across refreshes.
    function updateFollowUpInDOM(taskId, followUpData) {
        // Store in a data attribute so it persists across page refreshes
        const taskElement = document.querySelector(`[data-task-id="${taskId}"]`);
        if (taskElement) {
            taskElement.dataset.calendarEventId = followUpData.calendarEventId || '';
            taskElement.dataset.calendarSyncedAt = followUpData.calendarSyncedAt || '';
        }
    }

    // Convert sync button to view button
    // Convert an "Add to Calendar" button into a "View Calendar" link.
    // We build an anchor tag with data attributes and replace the button
    // element in the DOM. Event handling is performed using delegation,
    // so we do NOT attach individual listeners to the created element.
    function convertToViewButton(button, eventUrl) {
        // Get task ID and event ID from the button or extract from URL
        // The follow-up task id is stored on the button as data-task-id
        const taskId = button.dataset.taskId;
        const eventIdMatch = eventUrl.match(/events\/([^/?]+)/);
        // Extract the event ID which we use for URL fallback or checks.
        // Google event ids may contain characters that require encoding,
        // but the calendar URL path works with the direct id value.
        const eventId = eventIdMatch ? eventIdMatch[1] : null;

        // Create a new anchor element to match template structure
        const link = document.createElement('a');
        // Use a no-op href so that the link is focusable but doesn't navigate
        // by default; our click handler intercepts and performs the check
        // before opening the calendar URL.
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
    // Unified event handler for both sync and view button actions.
    // Uses event delegation to capture clicks for both static and
    // dynamically-created buttons. The view button is handled with
    // higher priority to ensure check-and-open semantics.
    // Note: this handler is attached in capturing phase so it executes
    // before other event listeners and any DOM-level default behavior.
    function handleCalendarClick(e) {
        // Check for view button click FIRST (higher priority)
        const viewButton = e.target.closest('.calendar-view-btn');
        if (viewButton) {
            e.preventDefault();
            e.stopPropagation();
            // stopImmediatePropagation ensures no other click handlers
            // (including third-party code) run for this event.
            // We then proactively set a no-op onclick handler on the
            // link as a defensive measure in case another listener relies
            // on examining a click and tries to follow the href.
            e.stopImmediatePropagation();

            // Prevent any default link behavior as a final fallback
            if (viewButton.tagName === 'A') {
                viewButton.onclick = function () { return false; };
            }

            const taskId = viewButton.dataset.taskId;
            const eventId = viewButton.dataset.eventId;
            const eventUrl = viewButton.dataset.eventUrl;

            // Debugging: show click details for easier inspection in devtools
            console.log('View button clicked:', { taskId, eventId, eventUrl });

            if (!taskId) {
                toastManager.show('Invalid task ID', 'error');
                return false;
            }

            // Kick off the async check; the handler won't navigate until
            // the check confirms the event exists. If the event was
            // deleted, the UI will be reverted to an "Add to Calendar" button.
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
    // Perform the `check-calendar-event` call to the server. If the
    // server indicates the calendar event was deleted (or cancelled),
    // clear local sync data and revert the UI. If the event still exists,
    // open it in Google Calendar using a reliable URL (API response or
    // a constructed fallback URL based on the event id).
    async function checkAndHandleCalendarEvent(taskId, eventId, eventUrl, viewButton) {
        // We always log the check; this is especially helpful when
        // diagnosing server-side failures or token issues.
        console.log('Checking calendar event existence for task:', taskId);

        try {
            const response = await fetch(`/api/follow-ups/${taskId}/check-calendar-event`);
            const data = await response.json();

            // Inspect the server response; the API returns a JSON object
            // with `success` and `exists` fields which we use to determine
            // the next UI action.
            console.log('Calendar check response:', data);

            if (!data.success) {
                // When the API reports the event no longer exists (or is
                // cancelled), clear the local sync state and revert the
                // action button so the user can add it again.
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

            // Event exists - open it using the authoritative URL returned
            // by the API when available. As a fallback, we construct a
            // sensible URL using the event ID.
            console.log('Event exists, opening in calendar');
            // Use the API response URL, or construct it from eventId if needed
            const urlToOpen = data.event_url || eventUrl ||
                (eventId ? `https://calendar.google.com/calendar/r/events/${eventId}` : null);
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
    // Convert a "View Calendar" link back into an "Add to Calendar" button.
    // The function performs a DOM replacement and the unified delegated
    // click handler will attach behavior to the new button automatically.
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
    // Initialize the document-level click handling for the calendar
    // buttons. Register only once and use capturing to intercept
    // clicks before other handlers and default behaviour.
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