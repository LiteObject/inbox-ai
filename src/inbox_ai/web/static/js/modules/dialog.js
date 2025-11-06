/**
 * Material Design 3 Dialog Manager
 * Provides a Material Design alternative to browser confirm() dialogs
 */

export class DialogManager {
    constructor() {
        this.dialogElement = null;
        this.setupDialog();
    }

    setupDialog() {
        // Wait for MD components to be defined
        if (typeof customElements !== 'undefined' && customElements.whenDefined) {
            customElements.whenDefined('md-dialog').then(() => {
                this.createDialogElement();
            }).catch(() => {
                console.warn('md-dialog component not available, falling back to native confirm');
                this.dialogElement = null;
            });
        } else {
            this.createDialogElement();
        }
    }

    createDialogElement() {
        // Create dialog element if it doesn't exist
        this.dialogElement = document.createElement('md-dialog');
        this.dialogElement.id = 'confirm-dialog';

        this.dialogElement.innerHTML = `
            <div slot="headline" id="dialog-headline">Confirm Action</div>
            <div slot="content" id="dialog-content">
                Are you sure you want to proceed?
            </div>
            <div slot="actions">
                <md-text-button id="dialog-cancel">
                    Cancel
                </md-text-button>
                <md-filled-button id="dialog-confirm" autofocus>
                    Confirm
                </md-filled-button>
            </div>
        `;

        document.body.appendChild(this.dialogElement);

        // Set up button click handlers
        const cancelBtn = this.dialogElement.querySelector('#dialog-cancel');
        const confirmBtn = this.dialogElement.querySelector('#dialog-confirm');

        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                this.dialogElement.close('cancel');
            });
        }

        if (confirmBtn) {
            confirmBtn.addEventListener('click', () => {
                this.dialogElement.close('confirm');
            });
        }

        console.log('Dialog element created and appended', this.dialogElement);
    }

    /**
     * Show a confirmation dialog
     * @param {string} message - The message to display
     * @param {string} headline - Optional headline (default: "Confirm Action")
     * @param {string} confirmText - Optional confirm button text (default: "Confirm")
     * @param {string} cancelText - Optional cancel button text (default: "Cancel")
     * @returns {Promise<boolean>} - Resolves to true if confirmed, false if cancelled
     */
    async confirm(message, headline = 'Confirm Action', confirmText = 'Confirm', cancelText = 'Cancel') {
        return new Promise((resolve) => {
            // Fallback to native confirm if dialog not ready
            if (!this.dialogElement) {
                console.warn('Dialog not ready, using native confirm');
                resolve(window.confirm(message));
                return;
            }

            // Update dialog content
            const headlineEl = this.dialogElement.querySelector('#dialog-headline');
            const contentEl = this.dialogElement.querySelector('#dialog-content');
            const cancelBtn = this.dialogElement.querySelector('#dialog-cancel');
            const confirmBtn = this.dialogElement.querySelector('#dialog-confirm');

            if (headlineEl) headlineEl.textContent = headline;
            if (contentEl) contentEl.textContent = message;
            if (cancelBtn) cancelBtn.textContent = cancelText;
            if (confirmBtn) confirmBtn.textContent = confirmText;

            // Handle dialog close
            const handleClose = (event) => {
                const returnValue = event.target.returnValue;
                this.dialogElement.removeEventListener('close', handleClose);
                console.log('Dialog closed with return value:', returnValue);
                resolve(returnValue === 'confirm');
            };

            this.dialogElement.addEventListener('close', handleClose);

            // Show dialog
            console.log('Showing dialog...');
            this.dialogElement.show();
        });
    }

    /**
     * Show an alert dialog (single action)
     * @param {string} message - The message to display
     * @param {string} headline - Optional headline (default: "Alert")
     * @param {string} actionText - Optional action button text (default: "OK")
     * @returns {Promise<void>}
     */
    async alert(message, headline = 'Alert', actionText = 'OK') {
        return new Promise((resolve) => {
            if (!this.dialogElement) {
                this.setupDialog();
            }

            // Update dialog content
            const headlineEl = this.dialogElement.querySelector('#dialog-headline');
            const contentEl = this.dialogElement.querySelector('#dialog-content');
            const cancelBtn = this.dialogElement.querySelector('#dialog-cancel');
            const confirmBtn = this.dialogElement.querySelector('#dialog-confirm');

            if (headlineEl) headlineEl.textContent = headline;
            if (contentEl) contentEl.textContent = message;
            if (confirmBtn) confirmBtn.textContent = actionText;
            if (cancelBtn) cancelBtn.style.display = 'none'; // Hide cancel button for alerts

            // Handle dialog close
            const handleClose = () => {
                this.dialogElement.removeEventListener('close', handleClose);
                if (cancelBtn) cancelBtn.style.display = ''; // Restore cancel button
                resolve();
            };

            this.dialogElement.addEventListener('close', handleClose);

            // Show dialog
            this.dialogElement.show();
        });
    }
}
