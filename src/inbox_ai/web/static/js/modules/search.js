function normalizeString(value) {
    if (value === undefined || value === null) {
        return "";
    }
    return String(value).replace(/\s+/g, " ").trim().toLowerCase();
}

function boolFromDataset(value) {
    if (typeof value !== "string") {
        return false;
    }
    const normalized = value.trim().toLowerCase();
    return normalized === "true" || normalized === "1" || normalized === "yes";
}

function parseNumeric(value) {
    if (value === undefined || value === null || value === "") {
        return null;
    }
    const parsed = Number.parseFloat(String(value));
    return Number.isFinite(parsed) ? parsed : null;
}

function buildSearchIndex(card) {
    const dataset = card.dataset;
    return {
        text: normalizeString(card.textContent || ""),
        subject: normalizeString(dataset.subject),
        sender: normalizeString(dataset.sender),
        summary: normalizeString(dataset.summary),
        actions: normalizeString(dataset.actions),
        categories: normalizeString(dataset.categories),
        priority: normalizeString(dataset.priority),
        priorityValue: parseNumeric(dataset.priorityValue),
        provider: normalizeString(dataset.provider),
        follow: normalizeString(dataset.follow),
        draft: normalizeString(dataset.draft),
        draftProvider: normalizeString(dataset.draftProvider),
        draftFallback: boolFromDataset(dataset.draftFallback),
        uid: normalizeString(dataset.uid),
        thread: normalizeString(dataset.threadId),
        hasFollow: boolFromDataset(dataset.hasFollowups),
        hasDraft: boolFromDataset(dataset.hasDraft),
    };
}

function splitSearchQuery(query) {
    const rawTokens = [];
    let current = "";
    let inQuotes = false;
    let quoteChar = "";
    for (let index = 0; index < query.length; index += 1) {
        const char = query[index];
        if (char === "\"" || char === "'") {
            if (inQuotes && char === quoteChar) {
                inQuotes = false;
                quoteChar = "";
                continue;
            }
            if (!inQuotes) {
                inQuotes = true;
                quoteChar = char;
                continue;
            }
        }
        if (/\s/.test(char) && !inQuotes) {
            if (current) {
                rawTokens.push(current);
                current = "";
            }
            continue;
        }
        current += char;
    }
    if (current) {
        rawTokens.push(current);
    }
    return rawTokens;
}

function parseSearchTokens(query) {
    const rawTokens = splitSearchQuery(query || "");
    const tokens = [];
    rawTokens.forEach((raw) => {
        if (!raw) {
            return;
        }
        let token = raw;
        let negated = false;
        if (token.startsWith("-") && token.length > 1) {
            negated = true;
            token = token.slice(1);
        }
        const colonIndex = token.indexOf(":");
        if (colonIndex > 0) {
            const keyRaw = token.slice(0, colonIndex).toLowerCase();
            const valueRaw = token.slice(colonIndex + 1);
            const trimmedValue = valueRaw.trim();
            if (!trimmedValue) {
                return;
            }
            tokens.push({
                kind: "field",
                key: keyRaw,
                normalizedKey: keyRaw.replace(/[^a-z0-9]/g, ""),
                value: normalizeString(trimmedValue),
                rawValue: trimmedValue,
                negated,
            });
            return;
        }
        const normalizedValue = normalizeString(token);
        if (!normalizedValue) {
            return;
        }
        tokens.push({
            kind: "term",
            value: normalizedValue,
            rawValue: token,
            negated,
        });
    });
    return tokens;
}

function matchesPriorityField(index, token) {
    if (!token.value) {
        return true;
    }
    const compact = token.value.replace(/\s+/g, "");
    if (compact.endsWith("+")) {
        const base = Number.parseInt(compact.slice(0, -1), 10);
        if (!Number.isNaN(base) && index.priorityValue !== null) {
            return index.priorityValue >= base;
        }
    }
    const comparisonMatch = compact.match(/^(>=|<=|>|<|=)?(\d{1,2})$/);
    if (comparisonMatch && index.priorityValue !== null) {
        const operator = comparisonMatch[1] || "=";
        const target = Number.parseInt(comparisonMatch[2], 10);
        switch (operator) {
            case ">":
                return index.priorityValue > target;
            case ">=":
                return index.priorityValue >= target;
            case "<":
                return index.priorityValue < target;
            case "<=":
                return index.priorityValue <= target;
            default:
                return index.priorityValue === target;
        }
    }
    if (index.priorityValue !== null) {
        const numeric = Number.parseInt(compact, 10);
        if (!Number.isNaN(numeric)) {
            return index.priorityValue === numeric;
        }
    }
    return index.priority.includes(token.value);
}

function matchesIsField(index, value) {
    switch (value) {
        case "followup":
        case "followups":
        case "tasks":
            return index.hasFollow;
        case "draft":
        case "reply":
            return index.hasDraft;
        case "fallback":
            return index.provider.includes("fallback") || index.draftFallback;
        case "open":
        case "done":
            return index.follow.includes(value);
        default:
            return index.text.includes(value);
    }
}

function matchesHasField(index, value) {
    switch (value) {
        case "followup":
        case "followups":
        case "tasks":
            return index.hasFollow;
        case "draft":
        case "reply":
            return index.hasDraft;
        default:
            return index.text.includes(value);
    }
}

function matchesFieldToken(index, token) {
    if (!token.value && !token.rawValue) {
        return true;
    }
    const key = token.normalizedKey;
    const value = token.value;
    switch (key) {
        case "from":
        case "sender":
            return index.sender.includes(value);
        case "subject":
        case "title":
            return index.subject.includes(value);
        case "summary":
        case "body":
        case "text":
            return index.summary.includes(value) || index.draft.includes(value);
        case "action":
        case "actions":
        case "todo":
            return index.actions.includes(value);
        case "category":
        case "categories":
        case "tag":
        case "labels":
            return index.categories.includes(value);
        case "priority":
        case "score":
            return matchesPriorityField(index, token);
        case "provider":
        case "source":
            return (
                index.provider.includes(value) ||
                index.draftProvider.includes(value)
            );
        case "draft":
        case "reply":
            return (
                index.draft.includes(value) ||
                index.draftProvider.includes(value)
            );
        case "follow":
        case "followup":
        case "followups":
        case "task":
        case "tasks":
        case "status":
            return index.follow.includes(value);
        case "uid":
        case "id":
            return index.uid.includes(value);
        case "thread":
        case "threadid":
            return index.thread.includes(value);
        case "is":
            return matchesIsField(index, value);
        case "has":
            return matchesHasField(index, value);
        default:
            return index.text.includes(value);
    }
}

function matchesTerm(index, token) {
    if (!token.value) {
        return true;
    }
    return index.text.includes(token.value);
}

function cardMatches(index, tokens) {
    if (!tokens.length) {
        return true;
    }
    for (const token of tokens) {
        const matched = token.kind === "term"
            ? matchesTerm(index, token)
            : matchesFieldToken(index, token);
        if (token.negated) {
            if (matched) {
                return false;
            }
        } else if (!matched) {
            return false;
        }
    }
    return true;
}

export function installInsightSearch({ input, grid, visibleCount, emptyNotice }) {
    if (!input || !grid) {
        return;
    }
    const cards = Array.from(grid.querySelectorAll(".insight-card"));
    if (!cards.length) {
        return;
    }
    const indexMap = new Map();
    cards.forEach((card) => {
        indexMap.set(card, buildSearchIndex(card));
    });

    function applyFilter() {
        const tokens = parseSearchTokens(input.value || "");
        let visible = 0;
        cards.forEach((card) => {
            const cardIndex = indexMap.get(card);
            const matches = cardIndex ? cardMatches(cardIndex, tokens) : true;
            card.style.display = matches ? "" : "none";
            if (matches) {
                visible += 1;
            }
        });
        if (visibleCount) {
            visibleCount.textContent = String(visible);
        }
        if (emptyNotice) {
            emptyNotice.hidden = visible !== 0;
        }
    }

    input.addEventListener("input", applyFilter);
    input.addEventListener("search", applyFilter);
    applyFilter();
}

export default installInsightSearch;

export function installEmailListSearch({ input, list, visibleCount, emptyNotice }) {
    if (!input || !list) {
        return;
    }

    const items = Array.from(list.querySelectorAll(".email-list-item"));
    if (!items.length) {
        return;
    }

    const indexMap = new Map();
    items.forEach((item) => {
        indexMap.set(item, buildSearchIndex(item));
    });

    function applyFilter() {
        const tokens = parseSearchTokens(input.value || "");
        let visible = 0;
        items.forEach((item) => {
            const itemIndex = indexMap.get(item);
            const matches = itemIndex ? cardMatches(itemIndex, tokens) : true;
            item.style.display = matches ? "" : "none";
            item.toggleAttribute("data-hidden", !matches);
            if (matches) {
                visible += 1;
            }
        });

        if (visibleCount) {
            visibleCount.textContent = String(visible);
        }
        if (emptyNotice) {
            emptyNotice.hidden = visible !== 0;
        }
    }

    input.addEventListener("input", applyFilter);
    input.addEventListener("search", applyFilter);
    applyFilter();
}
