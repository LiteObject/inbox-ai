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
})();
