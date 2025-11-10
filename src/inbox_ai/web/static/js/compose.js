/**
 * Compose Email Dialog Handler
 * 
 * Manages the compose email modal dialog including:
 * - Opening/closing the dialog
 * - Form validation
 * - Email submission
 * - Toast notifications
 */

(function () {
    'use strict';

    // Cache DOM elements
    const composeFab = document.getElementById('compose-fab');
    const composeDialog = document.getElementById('compose-dialog');
    const composeForm = document.getElementById('compose-form');
    const closeButtons = composeDialog?.querySelectorAll('.close-dialog, .cancel-compose');
    const confirmDialog = document.getElementById('confirm-dialog');
    const confirmOk = document.getElementById('confirm-ok');
    const confirmCancel = document.getElementById('confirm-cancel');

    if (!composeFab || !composeDialog || !composeForm) {
        console.warn('Compose elements not found in DOM');
        return;
    }

    // Track pending submission
    let pendingSubmission = null;

    /**
     * Show custom confirmation dialog
     */
    function showConfirmDialog(message = 'Are you sure you want to send this email?') {
        return new Promise((resolve) => {
            const messageEl = document.getElementById('confirm-dialog-message');
            if (messageEl) {
                messageEl.textContent = message;
            }

            confirmDialog.showModal();

            const handleOk = () => {
                confirmDialog.close();
                cleanup();
                resolve(true);
            };

            const handleCancel = () => {
                confirmDialog.close();
                cleanup();
                resolve(false);
            };

            const cleanup = () => {
                confirmOk.removeEventListener('click', handleOk);
                confirmCancel.removeEventListener('click', handleCancel);
            };

            confirmOk.addEventListener('click', handleOk);
            confirmCancel.addEventListener('click', handleCancel);
        });
    }

    /**
     * Open the compose dialog
     */
    function openDialog() {
        composeDialog.showModal();

        // Focus the first input field
        const firstInput = composeDialog.querySelector('#compose-to');
        if (firstInput) {
            setTimeout(() => firstInput.focus(), 100);
        }
    }

    /**
     * Close the compose dialog
     */
    function closeDialog() {
        composeDialog.close();
        composeForm.reset();
    }

    /**
     * Validate email address format
     */
    function isValidEmail(email) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(email);
    }

    /**
     * Validate the compose form
     */
    function validateForm() {
        const to = composeForm.querySelector('#compose-to').value.trim();
        const subject = composeForm.querySelector('#compose-subject').value.trim();
        const body = composeForm.querySelector('#compose-body').value.trim();

        const errors = [];

        if (!to) {
            errors.push('Recipient email is required');
        } else if (!isValidEmail(to)) {
            errors.push('Invalid recipient email address');
        }

        if (!subject) {
            errors.push('Subject is required');
        }

        if (!body) {
            errors.push('Message body is required');
        }

        return {
            isValid: errors.length === 0,
            errors: errors
        };
    }

    /**
     * Show toast notification
     */
    function showToast(message, type = 'info') {
        // Use existing toast system if available
        if (window.showToast) {
            window.showToast(message, type);
        } else {
            // Fallback to console
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
    }

    /**
     * Handle form submission
     */
    async function handleSubmit(event) {
        event.preventDefault();
        event.stopImmediatePropagation(); // ensure dashboard spinner handler doesn't re-submit the form

        // Validate form
        const validation = validateForm();
        if (!validation.isValid) {
            showToast(validation.errors.join('. '), 'error');
            return;
        }

        // Show custom confirmation dialog
        const confirmed = await showConfirmDialog('Are you sure you want to send this email?');
        if (!confirmed) {
            return;
        }

        // Prepare form data
        const formData = new FormData(composeForm);
        const submitButton = event.submitter;

        try {
            // Show loading state
            submitButton.disabled = true;
            submitButton.textContent = 'Sending...';

            // Submit the form
            const response = await fetch(composeForm.action, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (response.ok) {
                const result = await response.json();

                // Close dialog and show success
                closeDialog();
                showToast(result.message || 'Email sent successfully!', 'success');

                // Reload the page to refresh the view
                setTimeout(() => {
                    window.location.reload();
                }, 1000);
            } else {
                const error = await response.json();
                showToast(error.detail || 'Failed to send email', 'error');
            }
        } catch (error) {
            console.error('Error sending email:', error);
            showToast('Network error. Please try again.', 'error');
        } finally {
            // Reset button state
            submitButton.disabled = false;
            submitButton.innerHTML = '<span class="material-icons" aria-hidden="true">send</span><span>Send</span>';
        }
    }

    /**
     * Handle Escape key to close dialog
     */
    function handleKeyDown(event) {
        if (event.key === 'Escape' && composeDialog.open) {
            closeDialog();
        }
    }

    /**
     * Handle backdrop click to close dialog
     */
    function handleBackdropClick(event) {
        const container = composeDialog.querySelector('.compose-dialog__form');
        if (!container) {
            return;
        }

        const dialogRect = container.getBoundingClientRect();
        const clickedInDialog = (
            event.clientX >= dialogRect.left &&
            event.clientX <= dialogRect.right &&
            event.clientY >= dialogRect.top &&
            event.clientY <= dialogRect.bottom
        );

        if (!clickedInDialog) {
            closeDialog();
        }
    }

    // Event listeners
    composeFab.addEventListener('click', openDialog);

    closeButtons.forEach(button => {
        button.addEventListener('click', closeDialog);
    });

    composeForm.addEventListener('submit', handleSubmit);

    document.addEventListener('keydown', handleKeyDown);

    composeDialog.addEventListener('click', handleBackdropClick);

    // Prevent closing when clicking inside the dialog container
    const dialogContainer = composeDialog.querySelector('.compose-dialog__form');
    if (dialogContainer) {
        dialogContainer.addEventListener('click', (event) => {
            event.stopPropagation();
        });
    }

    console.log('Compose module initialized');

    // =========================================================================
    // Contact Autocomplete
    // =========================================================================

    /**
     * Contact Autocomplete Handler
     * 
     * Provides email address suggestions as the user types in the "To" field.
     * Features:
     * - Debounced API calls to fetch contact suggestions
     * - Keyboard navigation (Arrow keys, Enter, Escape)
     * - Mouse click selection
     * - Accessible with ARIA attributes
     */
    class ContactAutocomplete {
        constructor(inputElement, listElement) {
            this.input = inputElement;
            this.list = listElement;
            this.contacts = [];
            this.selectedIndex = -1;
            this.debounceTimer = null;
            this.minQueryLength = 2;
            this.debounceDelay = 300; // milliseconds

            this.init();
        }

        /**
         * Initialize event listeners
         */
        init() {
            this.input.addEventListener('input', (e) => this.handleInput(e));
            this.input.addEventListener('keydown', (e) => this.handleKeydown(e));
            this.input.addEventListener('blur', () => this.handleBlur());
            this.list.addEventListener('mousedown', (e) => this.handleClick(e));

            console.log('Contact autocomplete initialized');
        }

        /**
         * Handle input changes with debouncing
         */
        async handleInput(event) {
            const query = event.target.value.trim();

            // Clear any pending API calls
            clearTimeout(this.debounceTimer);

            // Hide dropdown if query is too short
            if (query.length < this.minQueryLength) {
                this.hide();
                return;
            }

            // Debounce API calls to avoid excessive requests
            this.debounceTimer = setTimeout(async () => {
                await this.fetchSuggestions(query);
            }, this.debounceDelay);
        }

        /**
         * Fetch contact suggestions from the API
         */
        async fetchSuggestions(query) {
            try {
                const response = await fetch(
                    `/api/contacts/suggestions?query=${encodeURIComponent(query)}&limit=10`
                );

                if (response.ok) {
                    this.contacts = await response.json();
                    this.render();
                } else {
                    console.error('Failed to fetch contacts:', response.statusText);
                    this.hide();
                }
            } catch (error) {
                console.error('Error fetching contacts:', error);
                this.hide();
            }
        }

        /**
         * Render the autocomplete dropdown
         */
        render() {
            if (this.contacts.length === 0) {
                this.hide();
                return;
            }

            this.list.innerHTML = this.contacts.map((contact, index) => `
                <li 
                    class="md3-autocomplete-item" 
                    role="option"
                    data-index="${index}"
                    data-email="${this.escapeHtml(contact.email)}"
                    tabindex="-1"
                >
                    <span class="md3-autocomplete-item-name">${this.escapeHtml(contact.name)}</span>
                    <span class="md3-autocomplete-item-email">${this.escapeHtml(contact.email)}</span>
                </li>
            `).join('');

            this.selectedIndex = -1;
            this.show();
        }

        /**
         * Escape HTML to prevent XSS
         */
        escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        /**
         * Handle keyboard navigation
         */
        handleKeydown(event) {
            if (this.list.hidden) {
                return;
            }

            switch (event.key) {
                case 'ArrowDown':
                    event.preventDefault();
                    this.selectNext();
                    break;
                case 'ArrowUp':
                    event.preventDefault();
                    this.selectPrevious();
                    break;
                case 'Enter':
                    if (this.selectedIndex >= 0) {
                        event.preventDefault();
                        this.selectCurrent();
                    }
                    break;
                case 'Escape':
                    event.preventDefault();
                    this.hide();
                    break;
            }
        }

        /**
         * Select next item in the list
         */
        selectNext() {
            const items = this.list.querySelectorAll('.md3-autocomplete-item');
            if (this.selectedIndex < items.length - 1) {
                this.selectedIndex++;
                this.updateSelection(items);
            }
        }

        /**
         * Select previous item in the list
         */
        selectPrevious() {
            if (this.selectedIndex > 0) {
                this.selectedIndex--;
                const items = this.list.querySelectorAll('.md3-autocomplete-item');
                this.updateSelection(items);
            }
        }

        /**
         * Update visual selection state
         */
        updateSelection(items) {
            items.forEach((item, index) => {
                const isSelected = index === this.selectedIndex;
                item.setAttribute('aria-selected', isSelected);

                if (isSelected) {
                    item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                }
            });
        }

        /**
         * Select the currently highlighted item
         */
        selectCurrent() {
            const items = this.list.querySelectorAll('.md3-autocomplete-item');
            if (this.selectedIndex >= 0 && this.selectedIndex < items.length) {
                const email = items[this.selectedIndex].dataset.email;
                this.selectEmail(email);
            }
        }

        /**
         * Handle mouse click on an item
         */
        handleClick(event) {
            const item = event.target.closest('.md3-autocomplete-item');
            if (item) {
                event.preventDefault();
                this.selectEmail(item.dataset.email);
            }
        }

        /**
         * Handle input blur (losing focus)
         */
        handleBlur() {
            // Delay hiding to allow click events to fire
            setTimeout(() => {
                this.hide();
            }, 200);
        }

        /**
         * Select an email address
         */
        selectEmail(email) {
            this.input.value = email;
            this.hide();
            this.input.focus();
        }

        /**
         * Show the autocomplete dropdown
         */
        show() {
            this.list.hidden = false;
            this.input.setAttribute('aria-expanded', 'true');
        }

        /**
         * Hide the autocomplete dropdown
         */
        hide() {
            this.list.hidden = true;
            this.selectedIndex = -1;
            this.input.setAttribute('aria-expanded', 'false');
        }
    }

    // Initialize autocomplete
    const toInput = document.getElementById('compose-to');
    const toList = document.getElementById('to-autocomplete-list');

    if (toInput && toList) {
        new ContactAutocomplete(toInput, toList);
    }

})();