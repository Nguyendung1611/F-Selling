/**
 * Hạ tầng đa ngôn ngữ dùng chung cho toàn bộ giao diện tĩnh.
 *
 * Catalog được nạp bằng file JS cục bộ trước file này để khởi tạo đồng bộ:
 * POS vẫn hoạt động và có tiếng Việt dự phòng ngay cả khi thiết bị mất mạng.
 */
(function (global) {
    'use strict';

    const STORAGE_KEY = 'fselling.locale';
    const SUPPORTED = Object.freeze(['vi', 'en']);
    const INTL_LOCALES = Object.freeze({ vi: 'vi-VN', en: 'en-US' });
    const resources = global.FSELLING_I18N_RESOURCES || {
        vi: { translation: {} },
        en: { translation: {} }
    };

    function normalizeLocale(value) {
        const base = String(value || '').trim().toLowerCase().split(/[-_]/)[0];
        return SUPPORTED.includes(base) ? base : null;
    }

    function detectLocale() {
        const stored = normalizeLocale(localStorage.getItem(STORAGE_KEY));
        if (stored) return stored;
        // F-Selling phục vụ cửa hàng Việt Nam nên lần mở đầu tiên luôn dùng
        // tiếng Việt. Sau đó lựa chọn rõ ràng của người dùng được nhớ trên máy.
        return 'vi';
    }

    let currentLocale = detectLocale();
    let engine = global.i18next || null;

    function fallbackTranslate(key, options = {}) {
        let resolvedKey = key;
        if (options.count !== undefined) {
            const rule = new Intl.PluralRules(INTL_LOCALES[currentLocale])
                .select(Number(options.count));
            const pluralKey = `${key}_${rule}`;
            if (resources[currentLocale]?.translation?.[pluralKey] !== undefined
                || resources.vi?.translation?.[pluralKey] !== undefined) {
                resolvedKey = pluralKey;
            }
        }
        let value = resources[currentLocale]?.translation?.[resolvedKey]
            ?? resources.vi?.translation?.[resolvedKey]
            ?? options.defaultValue
            ?? key;
        return String(value).replace(/\{\{\s*([\w.-]+)\s*\}\}/g, (_, name) => {
            const replacement = options[name];
            return replacement === undefined || replacement === null ? '' : String(replacement);
        });
    }

    if (engine) {
        engine.init({
            lng: currentLocale,
            fallbackLng: 'vi',
            supportedLngs: SUPPORTED,
            resources,
            keySeparator: false,
            nsSeparator: false,
            initAsync: false,
            returnEmptyString: false,
            interpolation: { escapeValue: false }
        });
    }

    function t(key, options = {}) {
        if (engine?.isInitialized) return engine.t(key, options);
        return fallbackTranslate(key, options);
    }

    function getLocale() {
        return currentLocale;
    }

    function getIntlLocale() {
        return INTL_LOCALES[currentLocale] || INTL_LOCALES.vi;
    }

    const numberFormatCache = new Map();

    function numberFormatter(options = {}) {
        const cacheKey = `${getIntlLocale()}:${JSON.stringify(options)}`;
        if (!numberFormatCache.has(cacheKey)) {
            numberFormatCache.set(
                cacheKey,
                new Intl.NumberFormat(getIntlLocale(), options)
            );
        }
        return numberFormatCache.get(cacheKey);
    }

    function formatNumber(value, options = {}) {
        const numeric = Number(value);
        return numberFormatter(options).format(Number.isFinite(numeric) ? numeric : 0);
    }

    function formatMoney(value) {
        return formatNumber(value, {
            style: 'currency',
            currency: 'VND',
            currencyDisplay: currentLocale === 'vi' ? 'symbol' : 'code',
            maximumFractionDigits: 0,
            minimumFractionDigits: 0
        });
    }

    function parseServerDate(value) {
        if (!value) return null;
        let normalized = String(value);
        const hasTimezone = /(Z|[+-]\d{2}:?\d{2})$/.test(normalized);
        if (!hasTimezone) normalized += 'Z';
        const date = new Date(normalized);
        return Number.isNaN(date.getTime()) ? null : date;
    }

    function formatDateTime(value, options = {}) {
        const date = parseServerDate(value);
        if (!date) return value ? String(value) : '';
        const defaults = {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        };
        return new Intl.DateTimeFormat(
            getIntlLocale(),
            Object.assign(defaults, options)
        ).format(date);
    }

    function apply(root = document) {
        if (!root?.querySelectorAll) return;
        root.querySelectorAll('[data-i18n]').forEach(element => {
            element.textContent = t(element.dataset.i18n);
        });

        const attributeBindings = {
            'data-i18n-placeholder': 'placeholder',
            'data-i18n-title': 'title',
            'data-i18n-aria-label': 'aria-label'
        };
        Object.entries(attributeBindings).forEach(([selector, attribute]) => {
            root.querySelectorAll(`[${selector}]`).forEach(element => {
                element.setAttribute(attribute, t(element.getAttribute(selector)));
            });
        });

        document.documentElement.lang = currentLocale;
        root.querySelectorAll('[data-language-selector]').forEach(select => {
            select.value = currentLocale;
        });
    }

    function announceLocaleChange() {
        apply(document);
        document.dispatchEvent(new CustomEvent('fselling:localechange', {
            detail: { locale: currentLocale }
        }));
    }

    function setLocale(value, options = {}) {
        const locale = normalizeLocale(value) || 'vi';
        currentLocale = locale;
        numberFormatCache.clear();
        if (options.persist !== false) localStorage.setItem(STORAGE_KEY, locale);

        if (engine?.isInitialized) {
            return Promise.resolve(engine.changeLanguage(locale)).then(() => {
                announceLocaleChange();
                return locale;
            });
        }
        announceLocaleChange();
        return Promise.resolve(locale);
    }

    function bindLanguageSelectors(root = document) {
        root.querySelectorAll('[data-language-selector]').forEach(select => {
            if (select.dataset.languageBound === '1') return;
            select.dataset.languageBound = '1';
            select.value = currentLocale;
            select.addEventListener('change', event => {
                setLocale(event.target.value);
            });
        });
    }

    function initializeDom() {
        apply(document);
        bindLanguageSelectors(document);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeDom, { once: true });
    } else {
        initializeDom();
    }

    global.addEventListener('storage', event => {
        if (event.key !== STORAGE_KEY || !event.newValue) return;
        const locale = normalizeLocale(event.newValue);
        if (locale && locale !== currentLocale) {
            setLocale(locale, { persist: false });
        }
    });

    global.FSellingI18n = Object.freeze({
        STORAGE_KEY,
        SUPPORTED,
        t,
        apply,
        setLocale,
        getLocale,
        getIntlLocale,
        formatNumber,
        formatMoney,
        formatDateTime,
        parseServerDate
    });

    // Alias ngắn cho các file JS cũ không dùng module/import.
    global.t = t;
    global.getCurrentLocale = getLocale;
    global.setLanguage = setLocale;
    global.dinhDangSo = formatNumber;
    global.dinhDangTienTe = formatMoney;
})(window);
