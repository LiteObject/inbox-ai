export class ListDetailController {
    constructor(options = {}) {
        this.container = options.container ?? document.querySelector('.list-detail-container');
        this.list = options.list ?? document.querySelector('.email-list');
        this.detailHost = options.detailHost ?? document.getElementById('detail-content');
        this.templateContainer = options.templateContainer ?? document.getElementById('detail-templates');
        this.onDetailChanged = options.onDetailChanged;
        this.onSelect = options.onSelect;
        this.mobileBreakpoint = options.mobileBreakpoint ?? 640;

        this.templates = new Map();
        this.listItems = [];
        this.selectedUid = null;

        this.mediaQuery = window.matchMedia(`(max-width: ${this.mobileBreakpoint}px)`);
        this.handleMediaChange = this.handleMediaChange.bind(this);
        this.handleListClick = this.handleListClick.bind(this);
        this.handleListKeydown = this.handleListKeydown.bind(this);
        this.handleBack = this.handleBack.bind(this);
        this.handlePopState = this.handlePopState.bind(this);

        this.init();
    }

    init() {
        if (!this.container || !this.list || !this.detailHost || !this.templateContainer) {
            return;
        }

        this.collectTemplates();
        this.listItems = Array.from(this.list.querySelectorAll('.email-list-item'));
        this.listItems.forEach((item) => {
            item.addEventListener('click', this.handleListClick);
            item.addEventListener('keydown', this.handleListKeydown);
            if (!item.hasAttribute('tabindex')) {
                item.setAttribute('tabindex', '0');
            }
        });

        this.detailHost.addEventListener('click', this.handleBack);
        this.mediaQuery.addEventListener('change', this.handleMediaChange);
        window.addEventListener('popstate', this.handlePopState);

        const initialItem = this.list.querySelector('.email-list-item[selected]') || this.listItems[0];
        if (initialItem) {
            this.selectItem(initialItem.dataset.uid, { scroll: false, updateHistory: false });
        } else if (!this.detailHost.children.length) {
            this.renderEmptyDetail();
        }
    }

    dispose() {
        this.listItems.forEach((item) => {
            item.removeEventListener('click', this.handleListClick);
            item.removeEventListener('keydown', this.handleListKeydown);
        });
        this.detailHost?.removeEventListener('click', this.handleBack);
        this.mediaQuery.removeEventListener('change', this.handleMediaChange);
        window.removeEventListener('popstate', this.handlePopState);
    }

    collectTemplates() {
        const templates = this.templateContainer.querySelectorAll('[data-email-detail]');
        templates.forEach((template) => {
            const uid = template.getAttribute('data-uid');
            if (uid) {
                this.templates.set(uid, template);
            }
        });
    }

    handleListClick(event) {
        const item = event.currentTarget;
        if (!item) {
            return;
        }
        this.selectItem(item.dataset.uid, { scroll: true, updateHistory: true });
    }

    handleListKeydown(event) {
        const item = event.currentTarget;
        if (!item) {
            return;
        }

        switch (event.key) {
            case 'Enter':
            case ' ': {
                event.preventDefault();
                this.selectItem(item.dataset.uid, { scroll: true, updateHistory: true });
                return;
            }
            case 'ArrowUp': {
                event.preventDefault();
                this.focusRelativeItem(item, -1);
                return;
            }
            case 'ArrowDown': {
                event.preventDefault();
                this.focusRelativeItem(item, 1);
                return;
            }
            default:
                return;
        }
    }

    focusRelativeItem(currentItem, delta) {
        const visibleItems = this.getVisibleItems();
        const index = visibleItems.indexOf(currentItem);
        if (index === -1) {
            return;
        }
        const nextIndex = index + delta;
        if (nextIndex < 0 || nextIndex >= visibleItems.length) {
            return;
        }
        const target = visibleItems[nextIndex];
        target?.focus({ preventScroll: false });
    }

    getVisibleItems() {
        return this.listItems.filter((item) => {
            const row = item.closest('li');
            return !item.hasAttribute('data-hidden') && !row?.hidden;
        });
    }

    handleBack(event) {
        const target = event.target.closest('[data-detail-back]');
        if (!target) {
            return;
        }
        event.preventDefault();
        this.hideDetail();
    }

    handleMediaChange() {
        if (!this.mediaQuery.matches) {
            this.container?.classList.remove('detail-active');
        }
    }

    handlePopState(event) {
        if (!this.mediaQuery.matches) {
            return;
        }
        if (event.state && event.state.view === 'detail') {
            this.showDetail();
        } else {
            this.container?.classList.remove('detail-active');
        }
    }

    selectItem(uid, { scroll = true, updateHistory = false } = {}) {
        if (!uid) {
            return;
        }

        if (uid === this.selectedUid) {
            if (this.mediaQuery.matches) {
                this.showDetail();
                if (updateHistory) {
                    history.pushState({ view: 'detail', uid }, '', '#detail');
                }
            }
            return;
        }

        const template = this.templates.get(uid);
        if (!template) {
            console.warn('No detail template found for email UID', uid);
            return;
        }

        this.listItems.forEach((item) => {
            const isMatch = item.dataset.uid === uid;
            item.toggleAttribute('selected', isMatch);
            item.dataset.selected = isMatch ? 'true' : 'false';
            if (isMatch && scroll) {
                item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            }
        });

        this.renderDetail(template, uid);
        this.selectedUid = uid;

        if (this.mediaQuery.matches) {
            this.showDetail();
            if (updateHistory) {
                history.pushState({ view: 'detail', uid }, '', '#detail');
            }
        }

        if (typeof this.onSelect === 'function') {
            this.onSelect(uid);
        }
    }

    renderDetail(template, uid) {
        if (!this.detailHost) {
            return;
        }
        this.detailHost.innerHTML = '';
        const fragment = template.content ? template.content.cloneNode(true) : template.cloneNode(true);
        this.detailHost.appendChild(fragment);

        const detailRoot = this.detailHost.querySelector('.detail-view');
        if (detailRoot) {
            detailRoot.setAttribute('data-email-uid', uid);
        }

        if (typeof this.onDetailChanged === 'function') {
            this.onDetailChanged(this.detailHost);
        }
    }

    renderEmptyDetail(options = {}) {
        if (!this.detailHost) {
            return;
        }
        const icon = options.icon || 'draft';
        const title = options.title || 'Select an email';
        const message = options.message || 'Open a message from the list to review the summary, follow-up tasks, and reply draft.';
        this.detailHost.innerHTML = `<div class="md3-empty-state md3-empty-state--detail"><span class="material-icons" aria-hidden="true">${icon}</span><h3>${title}</h3><p>${message}</p></div>`;

        if (typeof this.onDetailChanged === 'function') {
            this.onDetailChanged(this.detailHost);
        }
    }

    clearSelection({ emptyState, hideMobileDetail = false } = {}) {
        this.listItems.forEach((item) => {
            item.removeAttribute('selected');
            item.dataset.selected = 'false';
        });

        this.selectedUid = null;
        this.renderEmptyDetail(emptyState);

        if (hideMobileDetail) {
            this.container?.classList.remove('detail-active');
        }
    }

    syncVisibleItems(visibleUids = [], { emptyState } = {}) {
        if (!visibleUids.length) {
            this.clearSelection({ emptyState, hideMobileDetail: true });
            return;
        }

        const visibleSet = new Set(visibleUids);
        const selectedStillVisible = this.selectedUid && visibleSet.has(this.selectedUid);

        if (selectedStillVisible) {
            return;
        }

        const firstVisibleItem = this.listItems.find((item) => visibleSet.has(item.dataset.uid));
        if (firstVisibleItem) {
            this.selectItem(firstVisibleItem.dataset.uid, { scroll: false, updateHistory: false });
        }
    }

    showDetail() {
        this.container?.classList.add('detail-active');
    }

    hideDetail() {
        if (!this.mediaQuery.matches) {
            return;
        }
        this.container?.classList.remove('detail-active');
        const selectedItem = this.listItems.find((item) => item.dataset.uid === this.selectedUid && !item.hasAttribute('data-hidden'));
        selectedItem?.focus({ preventScroll: true });
        history.pushState({ view: 'list' }, '', '#list');
    }
}

export default ListDetailController;
