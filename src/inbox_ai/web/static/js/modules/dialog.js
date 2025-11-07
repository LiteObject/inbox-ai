const HAS_DIALOG_SUPPORT = typeof window !== "undefined" && typeof HTMLDialogElement !== "undefined";

function createUniqueId(prefix) {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return `${prefix}-${crypto.randomUUID()}`;
    }
    const fallback = Math.random().toString(36).slice(2);
    return `${prefix}-${fallback}`;
}

export class DialogManager {
    constructor() {
        this.dialogElement = null;
        this.headlineElement = null;
        this.messageElement = null;
        this.cancelButton = null;
        this.confirmButton = null;
        if (HAS_DIALOG_SUPPORT) {
            this.ensureDialog();
        }
    }

    ensureDialog() {
        if (this.dialogElement || !HAS_DIALOG_SUPPORT || typeof document === "undefined") {
            return;
        }

        const headlineId = createUniqueId("md3-dialog-headline");
        const messageId = createUniqueId("md3-dialog-message");

        const dialog = document.createElement("dialog");
        dialog.className = "md3-dialog";
        dialog.setAttribute("aria-labelledby", headlineId);
        dialog.setAttribute("aria-describedby", messageId);

        dialog.innerHTML = `
            <form method="dialog" class="md3-dialog__content">
                <h2 class="md3-dialog__headline" id="${headlineId}">Confirm Action</h2>
                <p class="md3-dialog__message" id="${messageId}">Are you sure you want to proceed?</p>
                <div class="md3-dialog__actions">
                    <button type="submit" value="cancel" class="md3-button" data-action="cancel">Cancel</button>
                    <button type="submit" value="confirm" class="md3-button md3-button--filled" data-action="confirm">Confirm</button>
                </div>
            </form>
        `;

        dialog.addEventListener("cancel", (event) => {
            event.preventDefault();
            dialog.close("cancel");
        });

        document.body.appendChild(dialog);

        this.dialogElement = dialog;
        this.headlineElement = dialog.querySelector(`#${headlineId}`);
        this.messageElement = dialog.querySelector(`#${messageId}`);
        this.cancelButton = dialog.querySelector('[data-action="cancel"]');
        this.confirmButton = dialog.querySelector('[data-action="confirm"]');
    }

    async confirm(message, headline = "Confirm Action", confirmText = "Confirm", cancelText = "Cancel") {
        this.ensureDialog();

        if (!this.dialogElement) {
            return Promise.resolve(window.confirm(message));
        }

        if (this.headlineElement) {
            this.headlineElement.textContent = headline;
        }
        if (this.messageElement) {
            this.messageElement.textContent = message;
        }
        if (this.cancelButton) {
            this.cancelButton.textContent = cancelText;
        }
        if (this.confirmButton) {
            this.confirmButton.textContent = confirmText;
        }

        if (this.dialogElement.open) {
            this.dialogElement.close("cancel");
        }

        return new Promise((resolve) => {
            const handleClose = () => {
                this.dialogElement.removeEventListener("close", handleClose);
                resolve(this.dialogElement.returnValue === "confirm");
            };
            this.dialogElement.addEventListener("close", handleClose, { once: true });
            try {
                this.dialogElement.showModal();
            } catch (error) {
                this.dialogElement.removeEventListener("close", handleClose);
                resolve(window.confirm(message));
            }
        });
    }

    async alert(message, headline = "Alert", actionText = "OK") {
        this.ensureDialog();

        if (!this.dialogElement) {
            window.alert(message);
            return;
        }

        if (this.headlineElement) {
            this.headlineElement.textContent = headline;
        }
        if (this.messageElement) {
            this.messageElement.textContent = message;
        }
        if (this.confirmButton) {
            this.confirmButton.textContent = actionText;
        }

        let previousDisplay = "";
        if (this.cancelButton) {
            previousDisplay = this.cancelButton.style.display;
            this.cancelButton.style.display = "none";
        }

        if (this.dialogElement.open) {
            this.dialogElement.close("cancel");
        }

        return new Promise((resolve) => {
            const handleClose = () => {
                this.dialogElement.removeEventListener("close", handleClose);
                if (this.cancelButton) {
                    this.cancelButton.style.display = previousDisplay;
                }
                resolve();
            };
            this.dialogElement.addEventListener("close", handleClose, { once: true });
            try {
                this.dialogElement.showModal();
            } catch (error) {
                this.dialogElement.removeEventListener("close", handleClose);
                if (this.cancelButton) {
                    this.cancelButton.style.display = previousDisplay;
                }
                window.alert(message);
                resolve();
            }
        });
    }
}
