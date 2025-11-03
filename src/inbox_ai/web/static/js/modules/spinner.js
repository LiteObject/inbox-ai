export class SpinnerController {
    constructor({ overlay, messageElement, defaultMessage, maxDuration = 120000, onTimeout } = {}) {
        this.overlay = overlay ?? null;
        this.messageElement = messageElement ?? null;
        const initialText = this.messageElement?.textContent ?? "";
        this.defaultMessage = defaultMessage ?? initialText;
        this.buttons = new Set();
        this.maxDuration = Number.isFinite(maxDuration) && maxDuration > 0 ? maxDuration : 0;
        this.onTimeout = typeof onTimeout === "function" ? onTimeout : null;
        this._timeoutId = null;
    }

    registerButton(button) {
        if (button) {
            this.buttons.add(button);
        }
    }

    unregisterButton(button) {
        if (button && this.buttons.has(button)) {
            this.buttons.delete(button);
        }
    }

    show(label) {
        this._clearTimer();
        if (this.overlay) {
            this.overlay.hidden = false;
        }
        if (this.messageElement) {
            this.messageElement.textContent = label || this.defaultMessage;
        }
        this.buttons.forEach((button) => {
            if (button) {
                button.disabled = true;
            }
        });

        if (this.maxDuration > 0) {
            this._timeoutId = window.setTimeout(() => {
                this._timeoutId = null;
                this.hide();
                if (this.onTimeout) {
                    this.onTimeout();
                }
            }, this.maxDuration);
        }
    }

    hide() {
        this._clearTimer();
        if (this.overlay) {
            this.overlay.hidden = true;
        }
        if (this.messageElement) {
            this.messageElement.textContent = this.defaultMessage;
        }
        this.buttons.forEach((button) => {
            if (button) {
                button.disabled = false;
            }
        });
    }

    _clearTimer() {
        if (this._timeoutId !== null) {
            window.clearTimeout(this._timeoutId);
            this._timeoutId = null;
        }
    }
}

export default SpinnerController;
