(function (global) {
    'use strict';

    const SELLER_ROLE = 'SELLER';
    const ADMIN_ROLE = 'ADMIN';
    const MONTHLY = 'MONTHLY';
    const YEARLY = 'YEARLY';
    const DEFAULT_MONTHLY_PRICE = 99000;
    const DEFAULT_YEARLY_PRICE = 831600;
    const SELLER_POLL_MS = 5000;
    const TERMINAL_CHECKOUT_STATUSES = new Set([
        'PAID', 'COMPLETED', 'ACTIVATED', 'CANCELLED', 'EXPIRED',
        'REJECTED', 'REFUNDED', 'OVERPAID'
    ]);
    const POLLED_CHECKOUT_STATUSES = new Set([
        'PENDING', 'WAITING', 'PROCESSING', 'PARTIAL', 'UNDERPAID'
    ]);

    const sellerState = {
        shopId: null,
        generation: null,
        data: null,
        requestId: 0,
        pollTimer: null,
        pollEpoch: 0,
        checkoutBusy: false,
        checkoutAttempt: null
    };

    const adminState = {
        shops: [],
        reviewPayments: [],
        shopsError: null,
        reviewError: null,
        requestId: 0,
        modalMode: null,
        modalShopId: null,
        modalBusy: false,
        modalOperationId: null
    };

    function byId(id) {
        return document.getElementById(id);
    }

    function translate(key, options) {
        return typeof global.t === 'function' ? global.t(key, options) : key;
    }

    function escaped(value) {
        if (typeof global.escapeHtml === 'function') return global.escapeHtml(value);
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function money(value) {
        const amount = Number(value || 0);
        if (typeof global.dinhDangTienTe === 'function') {
            return global.dinhDangTienTe(Number.isFinite(amount) ? amount : 0);
        }
        return `${Math.round(Number.isFinite(amount) ? amount : 0).toLocaleString('vi-VN')}đ`;
    }

    function dateOnly(value) {
        if (!value) return '';
        const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
        if (!match) return '';
        const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
        if (Number.isNaN(date.getTime())) return '';
        const locale = global.FSellingI18n?.getIntlLocale?.() || 'vi-VN';
        return new Intl.DateTimeFormat(locale, {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric'
        }).format(date);
    }

    function dateTime(value) {
        if (!value) return translate('subscription.common.not_available');
        if (/^\d{4}-\d{2}-\d{2}$/.test(String(value))) {
            return dateOnly(value) || String(value);
        }
        if (typeof global.dinhDangNgayGio === 'function') {
            return global.dinhDangNgayGio(value);
        }
        return String(value);
    }

    function localToday() {
        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const day = String(now.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    function statusCode(value) {
        return String(value || '').trim().toUpperCase();
    }

    function activeGrantExpiresOn(data) {
        return data?.active_grant_expires_on
            || data?.gift_expires_on
            || data?.active_grant?.expires_on
            || '';
    }

    function giftExpiryText(data) {
        const formatted = dateOnly(activeGrantExpiresOn(data));
        return formatted
            ? translate('subscription.status.gift_until_end', { date: formatted })
            : '';
    }

    function normalizeList(value, keys) {
        if (Array.isArray(value)) return value;
        for (const key of keys) {
            if (Array.isArray(value?.[key])) return value[key];
        }
        return [];
    }

    function operationId(prefix) {
        const randomPart = global.crypto && typeof global.crypto.randomUUID === 'function'
            ? global.crypto.randomUUID()
            : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        return `${prefix}-${randomPart}`.replace(/[^A-Za-z0-9_-]/g, '');
    }

    function safeImageUrl(value) {
        if (!value) return '';
        try {
            const parsed = new URL(String(value), global.location.origin);
            if (!['http:', 'https:'].includes(parsed.protocol)) return '';
            return parsed.href;
        } catch (error) {
            return '';
        }
    }

    function planStatusInfo(data) {
        const status = statusCode(data?.status || data?.subscription_status);
        const plan = statusCode(data?.plan);
        const map = {
            FREE: {
                label: 'subscription.status.free',
                title: 'subscription.status.free_title',
                detail: 'subscription.status.free_detail',
                tone: 'neutral'
            },
            TRIAL: {
                label: 'subscription.status.trial',
                title: 'subscription.status.trial_title',
                detail: 'subscription.status.trial_detail',
                tone: 'pro'
            },
            PAID: {
                label: 'subscription.status.paid',
                title: 'subscription.status.paid_title',
                detail: 'subscription.status.paid_detail',
                tone: 'success'
            },
            GIFT: {
                label: 'subscription.status.gift',
                title: 'subscription.status.gift_title',
                detail: 'subscription.status.gift_detail',
                tone: 'pro'
            },
            GRACE: {
                label: 'subscription.status.grace',
                title: 'subscription.status.grace_title',
                detail: 'subscription.status.grace_detail',
                tone: 'warning'
            }
        };
        if (map[status]) return { ...map[status], status, plan };
        if (plan === 'FREE') return { ...map.FREE, status: status || 'FREE', plan };
        return {
            label: plan === 'PRO' ? 'subscription.status.paid' : 'subscription.status.free',
            title: 'subscription.status.unknown_title',
            detail: 'subscription.status.unknown_detail',
            tone: plan === 'PRO' ? 'pro' : 'neutral',
            status,
            plan
        };
    }

    function checkoutStatusInfo(checkout) {
        const status = statusCode(checkout?.status);
        const normalized = status === 'UNDERPAID' ? 'PARTIAL'
            : (['NEEDS_REVIEW', 'UNRECONCILED', 'INVALID_REFERENCE'].includes(status) ? 'REVIEW' : status);
        const map = {
            PENDING: ['pending', 'warning'],
            WAITING: ['pending', 'warning'],
            PROCESSING: ['pending', 'warning'],
            PARTIAL: ['partial', 'danger'],
            PAID: ['paid', 'success'],
            COMPLETED: ['paid', 'success'],
            ACTIVATED: ['paid', 'success'],
            OVERPAID: ['overpaid', 'danger'],
            REVIEW: ['review', 'danger'],
            EXPIRED: ['expired', 'neutral'],
            CANCELLED: ['cancelled', 'neutral']
        };
        const [key, tone] = map[normalized] || ['unknown', 'neutral'];
        return {
            status,
            normalized,
            label: translate(`subscription.checkout.status.${key}`),
            message: translate(`subscription.checkout.message.${key}`),
            tone
        };
    }

    function checkoutBlocksNew(checkout) {
        if (!checkout) return false;
        return !TERMINAL_CHECKOUT_STATUSES.has(statusCode(checkout.status));
    }

    function checkoutMatchesAttempt(checkout, attempt) {
        return !!checkout
            && !!attempt?.operation_id
            && String(checkout.operation_id || '') === String(attempt.operation_id);
    }

    function checkoutNeedsPolling(checkout) {
        return !!checkout && POLLED_CHECKOUT_STATUSES.has(statusCode(checkout.status));
    }

    function checkoutJustActivated(previousCheckout, currentCheckout) {
        if (!previousCheckout || !currentCheckout) return false;
        if (Number(previousCheckout.id) !== Number(currentCheckout.id)) return false;
        return POLLED_CHECKOUT_STATUSES.has(statusCode(previousCheckout.status))
            && ['PAID', 'OVERPAID', 'ACTIVATED', 'COMPLETED'].includes(
                statusCode(currentCheckout.status)
            )
            && !!currentCheckout.activated_at;
    }

    function selectedSellerShopName() {
        const selector = byId('shopChungSelect');
        const option = selector?.selectedOptions?.[0];
        return option?.textContent?.trim() || '';
    }

    function sellerErrorMessage(error) {
        const message = error?.message || translate('common.api_error');
        return message === translate('common.network_error')
            ? translate('subscription.seller.network_required')
            : message;
    }

    function showSellerState(name, errorMessage) {
        const loading = byId('subscriptionSellerLoading');
        const noShop = byId('subscriptionSellerNoShop');
        const error = byId('subscriptionSellerError');
        const content = byId('subscriptionSellerContent');
        if (loading) loading.style.display = name === 'loading' ? 'flex' : 'none';
        if (noShop) noShop.style.display = name === 'no-shop' ? 'flex' : 'none';
        if (error) error.style.display = name === 'error' ? 'flex' : 'none';
        if (content) content.style.display = name === 'content' ? 'block' : 'none';
        const errorText = byId('subscriptionSellerErrorText');
        if (errorText) errorText.textContent = errorMessage || '';
    }

    function setBadge(element, label, tone) {
        if (!element) return;
        element.textContent = label || '';
        element.dataset.tone = tone || 'neutral';
    }

    function setCheckoutButtons() {
        const checkout = sellerState.data?.current_checkout || null;
        const blockedByCheckout = checkoutBlocksNew(checkout);
        // Attempt còn giữ nghĩa là chưa xác minh được POST trước có tới server
        // hay chưa. Checkout terminal cũ trên màn hình không được làm mất khóa
        // retry này, nếu không người dùng đổi kỳ sẽ sinh operation_id thứ hai.
        const pendingAttempt = sellerState.checkoutAttempt;
        [byId('subscriptionBuyMonthly'), byId('subscriptionBuyYearly')].forEach(button => {
            if (!button) return;
            const wrongRetryCycle = pendingAttempt
                && button.dataset.cycle !== pendingAttempt.cycle;
            button.disabled = sellerState.checkoutBusy || blockedByCheckout || wrongRetryCycle;
            if (blockedByCheckout) {
                button.title = translate('subscription.seller.checkout_exists');
            } else if (wrongRetryCycle) {
                button.title = translate('subscription.seller.retry_same_cycle');
            } else {
                button.removeAttribute('title');
            }
        });
    }

    function renderSellerCheckout(checkout) {
        const panel = byId('subscriptionCheckoutPanel');
        if (!panel) return;
        if (!checkout) {
            panel.style.display = 'none';
            setCheckoutButtons();
            return;
        }
        panel.style.display = 'block';
        const info = checkoutStatusInfo(checkout);
        setBadge(byId('subscriptionCheckoutStatus'), info.label, info.tone);

        const amountDue = Number(checkout.amount_due_vnd || 0);
        const received = Number(
            checkout.received_vnd ?? checkout.received_amount_vnd ?? 0
        );
        const remaining = Number(
            checkout.remaining_vnd
            ?? checkout.remaining_amount_vnd
            ?? Math.max(amountDue - received, 0)
        );
        const refundDue = Number(
            checkout.refund_due_vnd ?? checkout.refund_due_amount_vnd ?? 0
        );
        byId('subscriptionCheckoutAmount').textContent = money(amountDue);
        byId('subscriptionCheckoutReference').textContent = checkout.reference_code || '';
        byId('subscriptionCheckoutReceived').textContent = money(received);
        byId('subscriptionCheckoutRemaining').textContent = money(remaining);
        byId('subscriptionCheckoutExpires').textContent = dateTime(checkout.expires_at);
        byId('subscriptionCheckoutMessage').textContent = info.message;

        const remainingRow = byId('subscriptionRemainingRow');
        if (remainingRow) remainingRow.style.display = refundDue > 0 ? 'none' : 'flex';
        const refundRow = byId('subscriptionRefundRow');
        if (refundRow) refundRow.style.display = refundDue > 0 ? 'flex' : 'none';
        byId('subscriptionCheckoutRefund').textContent = money(refundDue);

        const image = byId('subscriptionQrImage');
        const wrap = byId('subscriptionQrWrap');
        let missing = byId('subscriptionQrMissing');
        if (!missing && wrap) {
            missing = document.createElement('span');
            missing.id = 'subscriptionQrMissing';
            wrap.appendChild(missing);
        }
        const imageUrl = safeImageUrl(checkout.qr_url);
        const qrIsIntentionallyClosed = [
            'PAID', 'COMPLETED', 'ACTIVATED', 'OVERPAID', 'EXPIRED',
            'CANCELLED', 'REJECTED', 'REFUNDED'
        ].includes(info.status);
        if (image) {
            image.alt = translate('subscription.checkout.qr_alt');
            image.onerror = () => {
                image.style.display = 'none';
                if (missing) {
                    missing.textContent = translate('subscription.checkout.no_qr');
                    missing.style.display = 'block';
                }
            };
            if (imageUrl) {
                image.src = imageUrl;
                image.style.display = 'block';
            } else {
                image.removeAttribute('src');
                image.style.display = 'none';
            }
        }
        if (missing) {
            // Backend cố ý không trả QR sau khi mã đã đóng. Không bảo chủ shop
            // "tải lại" trong trường hợp này vì họ có thể hiểu nhầm là cần
            // chuyển tiền lần nữa.
            missing.textContent = qrIsIntentionallyClosed
                ? info.message
                : translate('subscription.checkout.no_qr');
            missing.style.display = imageUrl ? 'none' : 'block';
        }
        setCheckoutButtons();
    }

    function renderSeller() {
        if (!byId('subscription')) return;
        if (!sellerState.shopId) {
            showSellerState('no-shop');
            return;
        }
        if (!sellerState.data) return;
        showSellerState('content');
        const data = sellerState.data;
        const info = planStatusInfo(data);
        const isPro = info.plan === 'PRO' || ['TRIAL', 'PAID', 'GIFT', 'GRACE'].includes(info.status);

        const shopName = selectedSellerShopName();
        byId('subscriptionSellerShopName').textContent = shopName;
        setBadge(byId('subscriptionSellerStatusBadge'), translate(info.label), info.tone);
        byId('subscriptionSellerStatusTitle').textContent = translate(info.title);
        byId('subscriptionSellerStatusDetail').textContent = translate(info.detail);

        const statusDate = byId('subscriptionSellerStatusDate');
        if (statusDate) {
            const inclusiveGiftExpiry = info.status === 'GIFT'
                ? giftExpiryText(data)
                : '';
            if (inclusiveGiftExpiry) {
                statusDate.textContent = inclusiveGiftExpiry;
            } else if (info.status === 'GRACE' && data.grace_until) {
                statusDate.textContent = translate('subscription.status.grace_until', {
                    date: dateTime(data.grace_until)
                });
            } else if (data.pro_until) {
                statusDate.textContent = translate('subscription.status.pro_until', {
                    date: dateTime(data.pro_until)
                });
            } else {
                statusDate.textContent = translate('subscription.common.no_expiry');
            }
        }

        const freeCard = byId('subscriptionFreeCard');
        const proCard = byId('subscriptionProCard');
        if (freeCard) freeCard.dataset.current = String(!isPro);
        if (proCard) proCard.dataset.current = String(isPro);
        if (byId('subscriptionFreeCurrent')) {
            byId('subscriptionFreeCurrent').style.display = isPro ? 'none' : 'inline-flex';
        }
        if (byId('subscriptionProCurrent')) {
            byId('subscriptionProCurrent').style.display = isPro ? 'inline-flex' : 'none';
        }

        const monthlyPrice = Number(data.prices?.monthly_vnd || DEFAULT_MONTHLY_PRICE);
        const yearlyPrice = Number(data.prices?.yearly_vnd || DEFAULT_YEARLY_PRICE);
        byId('subscriptionMonthlyPrice').textContent = money(monthlyPrice);
        byId('subscriptionYearlyPrice').textContent = money(yearlyPrice);
        renderSellerCheckout(data.current_checkout || null);
    }

    function stopSellerPolling() {
        if (sellerState.pollTimer) global.clearTimeout(sellerState.pollTimer);
        sellerState.pollTimer = null;
    }

    function sellerTabIsOpen() {
        return byId('subscription')?.classList.contains('active') === true;
    }

    function scheduleSellerPolling() {
        stopSellerPolling();
        if (!sellerTabIsOpen() || !checkoutNeedsPolling(sellerState.data?.current_checkout)) return;
        const epoch = sellerState.pollEpoch;
        sellerState.pollTimer = global.setTimeout(() => {
            sellerState.pollTimer = null;
            if (epoch !== sellerState.pollEpoch || !sellerTabIsOpen()) return;
            refreshSellerStatus({ quiet: true, epoch });
        }, SELLER_POLL_MS);
    }

    async function refreshSellerStatus({ quiet = false, epoch = sellerState.pollEpoch } = {}) {
        const shopId = sellerState.shopId;
        const generation = sellerState.generation;
        if (!shopId || epoch !== sellerState.pollEpoch) return;
        const requestId = ++sellerState.requestId;
        try {
            const previous = sellerState.data;
            const data = await global.apiCall(`/subscriptions/${shopId}`);
            if (
                requestId !== sellerState.requestId
                || epoch !== sellerState.pollEpoch
                || sellerState.shopId !== shopId
                || sellerState.generation !== generation
            ) return;
            sellerState.data = data || {};
            renderSeller();
            if (checkoutJustActivated(
                previous?.current_checkout,
                sellerState.data?.current_checkout
            )) {
                global.showToast?.(translate('subscription.seller.activated'));
            }
            scheduleSellerPolling();
        } catch (error) {
            if (
                requestId !== sellerState.requestId
                || epoch !== sellerState.pollEpoch
                || sellerState.shopId !== shopId
            ) return;
            if (!sellerState.data && !quiet) {
                showSellerState('error', sellerErrorMessage(error));
            } else if (!quiet) {
                global.showToast?.(sellerErrorMessage(error));
            }
            if (quiet) scheduleSellerPolling();
        }
    }

    async function loadSeller(shopId, generation) {
        if (localStorage.getItem('role') !== SELLER_ROLE || !byId('subscription')) return;
        stopSellerPolling();
        sellerState.pollEpoch += 1;
        sellerState.requestId += 1;
        const parsedShopId = Number(shopId);
        sellerState.shopId = Number.isInteger(parsedShopId) && parsedShopId > 0
            ? parsedShopId
            : null;
        sellerState.generation = Number(generation || 0);
        sellerState.data = null;
        sellerState.checkoutAttempt = null;
        if (!sellerState.shopId) {
            showSellerState('no-shop');
            return;
        }
        byId('subscriptionSellerShopName').textContent = selectedSellerShopName();
        showSellerState('loading');
        await refreshSellerStatus({ quiet: false, epoch: sellerState.pollEpoch });
    }

    function resetSellerForShopChange() {
        stopSellerPolling();
        sellerState.pollEpoch += 1;
        sellerState.requestId += 1;
        sellerState.shopId = null;
        sellerState.generation = null;
        sellerState.data = null;
        sellerState.checkoutBusy = false;
        sellerState.checkoutAttempt = null;
    }

    function onSellerTabChange(tabId) {
        if (tabId !== 'subscription') stopSellerPolling();
        else scheduleSellerPolling();
    }

    async function createCheckout(cycle) {
        if (![MONTHLY, YEARLY].includes(cycle) || sellerState.checkoutBusy) return;
        const shopId = sellerState.shopId;
        if (!shopId) return;
        if (checkoutBlocksNew(sellerState.data?.current_checkout)) {
            global.showToast?.(translate('subscription.seller.checkout_exists'));
            return;
        }
        if (
            sellerState.checkoutAttempt
            && sellerState.checkoutAttempt.shopId === shopId
            && sellerState.checkoutAttempt.cycle !== cycle
        ) {
            global.showToast?.(translate('subscription.seller.retry_same_cycle'));
            return;
        }
        if (
            !sellerState.checkoutAttempt
            || sellerState.checkoutAttempt.shopId !== shopId
        ) {
            sellerState.checkoutAttempt = {
                shopId,
                cycle,
                operation_id: operationId('subscription-checkout')
            };
        }
        const attempt = { ...sellerState.checkoutAttempt };
        sellerState.checkoutBusy = true;
        setCheckoutButtons();
        const clickedButton = cycle === MONTHLY
            ? byId('subscriptionBuyMonthly')
            : byId('subscriptionBuyYearly');
        const buttonLabel = clickedButton?.querySelector('span');
        const normalLabelKey = cycle === MONTHLY
            ? 'subscription.seller.buy_monthly'
            : 'subscription.seller.buy_yearly';
        if (buttonLabel) {
            buttonLabel.dataset.i18n = 'subscription.seller.creating_checkout';
            buttonLabel.textContent = translate('subscription.seller.creating_checkout');
        }
        try {
            const created = await global.apiCall(`/subscriptions/${shopId}/checkouts`, 'POST', {
                cycle,
                operation_id: attempt.operation_id
            });
            if (!checkoutMatchesAttempt(created, attempt)) {
                throw new Error(translate('subscription.seller.retry_same_cycle'));
            }
            if (sellerState.shopId === shopId) {
                sellerState.data = sellerState.data || {};
                sellerState.data.current_checkout = created;
                sellerState.data.latest_checkout = created;
                renderSeller();
            }
            sellerState.checkoutAttempt = null;
            // Không suy ra PAID từ phản hồi tạo QR. Luôn GET lại trạng thái do
            // server đối chiếu ngân hàng quyết định.
            await refreshSellerStatus({ quiet: true });
            // Nếu GET bị cache/trễ, phản hồi POST đúng operation_id vẫn là mã
            // server vừa tạo. Không để một checkout cũ ghi đè QR vừa nhận.
            if (!checkoutMatchesAttempt(sellerState.data?.current_checkout, attempt)) {
                sellerState.data = sellerState.data || {};
                sellerState.data.current_checkout = created;
                sellerState.data.latest_checkout = created;
                renderSeller();
            }
            global.showToast?.(translate('subscription.seller.checkout_created'));
        } catch (error) {
            // Request có thể đã tới server nhưng phản hồi bị mất. GET trạng thái
            // trước; chỉ checkout có ĐÚNG operation_id mới chứng minh lần bấm này
            // đã tới server. Checkout PAID/EXPIRED cũ tuyệt đối không được tính.
            await refreshSellerStatus({ quiet: true });
            if (checkoutMatchesAttempt(sellerState.data?.current_checkout, attempt)) {
                sellerState.checkoutAttempt = null;
                global.showToast?.(translate('subscription.seller.checkout_created'));
            } else {
                global.showToast?.(sellerErrorMessage(error));
            }
        } finally {
            sellerState.checkoutBusy = false;
            if (buttonLabel) {
                buttonLabel.dataset.i18n = normalLabelKey;
                buttonLabel.textContent = translate(normalLabelKey);
            }
            renderSeller();
        }
    }

    function adminPlanExpiry(row) {
        return statusCode(row?.status) === 'GRACE' && row?.grace_until
            ? row.grace_until
            : row?.pro_until;
    }

    function adminPlanExpiryText(row) {
        const inclusiveGiftExpiry = statusCode(row?.status) === 'GIFT'
            ? giftExpiryText(row)
            : '';
        if (inclusiveGiftExpiry) return inclusiveGiftExpiry;
        const expiry = adminPlanExpiry(row);
        return expiry
            ? dateTime(expiry)
            : translate('subscription.common.no_expiry');
    }

    function renderAdminShops() {
        const tbody = byId('subscriptionAdminShopList');
        if (!tbody) return;
        if (adminState.shopsError) {
            tbody.innerHTML = '';
            return;
        }
        if (!adminState.shops.length) {
            tbody.innerHTML = `<tr><td colspan="5" class="subscription-empty-cell">${escaped(translate('subscription.admin.no_shops'))}</td></tr>`;
            return;
        }
        tbody.innerHTML = adminState.shops.map(row => {
            const shopId = Number(row.shop_id);
            const info = planStatusInfo(row);
            const isPro = info.plan === 'PRO' || ['TRIAL', 'PAID', 'GIFT', 'GRACE'].includes(info.status);
            const grantId = Number(row.active_grant_id);
            const hasGrant = Number.isInteger(grantId) && grantId > 0;
            const expiryText = adminPlanExpiryText(row);
            const primaryAction = isPro ? 'extend' : 'grant';
            const primaryLabel = translate(isPro ? 'subscription.admin.extend' : 'subscription.admin.grant');
            const revokeButton = hasGrant
                ? `<button type="button" class="btn-outline subscription-revoke-button" data-admin-subscription-action="revoke" data-shop-id="${shopId}">${escaped(translate('subscription.admin.revoke'))}</button>`
                : '';
            return `<tr>
                <td><strong>${escaped(row.shop_name || translate('subscription.admin.shop_number', { id: shopId }))}</strong><small>#${shopId}</small></td>
                <td>${escaped(row.owner_username || translate('subscription.common.not_available'))}</td>
                <td><div class="subscription-admin-plan"><span class="subscription-badge" data-tone="${escaped(info.tone)}">${escaped(translate(info.label))}</span><small>${escaped(translate(info.title))}</small></div></td>
                <td class="subscription-admin-expiry"><strong>${escaped(expiryText)}</strong></td>
                <td><div class="subscription-admin-actions"><button type="button" data-admin-subscription-action="${primaryAction}" data-shop-id="${shopId}">${escaped(primaryLabel)}</button>${revokeButton}</div></td>
            </tr>`;
        }).join('');
    }

    function reviewProblem(payment) {
        const raw = statusCode(
            payment.review_reason_code
            || payment.reason_code
            || payment.problem_code
            || payment.status
        );
        if (raw === 'OVERPAID') {
            const refundDue = Number(
                payment.checkout_refund_due_vnd
                ?? payment.refund_due_vnd
                ?? 0
            );
            if (Number.isFinite(refundDue) && refundDue > 0) {
                return translate('subscription.admin.problem_overpaid_refund', {
                    amount: money(refundDue)
                });
            }
        }
        const keyMap = {
            MISSING_REFERENCE: 'missing_reference',
            NO_REFERENCE: 'missing_reference',
            INVALID_REFERENCE: 'invalid_reference',
            WRONG_REFERENCE: 'invalid_reference',
            UNKNOWN_REFERENCE: 'invalid_reference',
            ACCOUNT_MISMATCH: 'account_mismatch',
            EXPIRED: 'expired',
            EXPIRED_CHECKOUT: 'expired',
            UNDERPAID: 'underpaid',
            PARTIAL: 'underpaid',
            OVERPAID: 'overpaid'
        };
        if (keyMap[raw]) return translate(`subscription.admin.problem_${keyMap[raw]}`);
        return payment.review_reason
            || payment.reason
            || payment.details
            || translate('subscription.admin.unknown_problem');
    }

    function renderAdminReviewPayments() {
        const tbody = byId('subscriptionReviewPaymentList');
        const count = byId('subscriptionReviewCount');
        const error = byId('subscriptionReviewError');
        if (count) count.textContent = String(adminState.reviewPayments.length);
        if (error) {
            error.style.display = adminState.reviewError ? 'flex' : 'none';
            error.textContent = adminState.reviewError
                ? translate('subscription.admin.review_load_failed')
                : '';
        }
        if (!tbody) return;
        if (adminState.reviewError) {
            tbody.innerHTML = '';
            return;
        }
        if (!adminState.reviewPayments.length) {
            tbody.innerHTML = `<tr><td colspan="5" class="subscription-empty-cell">${escaped(translate('subscription.admin.no_review_payments'))}</td></tr>`;
            return;
        }
        tbody.innerHTML = adminState.reviewPayments.map(payment => {
            const transactionId = payment.bank_txn_id
                || payment.bank_transaction_id
                || payment.transaction_id
                || payment.id
                || translate('subscription.common.not_available');
            const transferContent = payment.transfer_content
                || payment.description
                || payment.reference_code
                || translate('subscription.common.not_available');
            const amount = payment.amount_vnd
                ?? payment.received_vnd
                ?? payment.amount
                ?? 0;
            const time = payment.received_at || payment.created_at || payment.updated_at;
            return `<tr>
                <td>${escaped(time ? dateTime(time) : translate('subscription.common.not_available'))}</td>
                <td><strong>${escaped(transactionId)}</strong></td>
                <td>${escaped(transferContent)}</td>
                <td><strong>${escaped(money(amount))}</strong></td>
                <td class="subscription-payment-problem">${escaped(reviewProblem(payment))}</td>
            </tr>`;
        }).join('');
    }

    function renderAdmin() {
        if (!byId('subscriptions')) return;
        const loading = byId('subscriptionAdminLoading');
        const content = byId('subscriptionAdminContent');
        const error = byId('subscriptionAdminError');
        if (loading) loading.style.display = 'none';
        if (content) content.style.display = 'block';
        if (error) error.style.display = adminState.shopsError ? 'flex' : 'none';
        const errorText = byId('subscriptionAdminErrorText');
        if (errorText) errorText.textContent = adminState.shopsError?.message || '';
        renderAdminShops();
        renderAdminReviewPayments();
        renderAdminModal();
    }

    async function loadAdmin() {
        if (localStorage.getItem('role') !== ADMIN_ROLE || !byId('subscriptions')) return;
        const requestId = ++adminState.requestId;
        const loading = byId('subscriptionAdminLoading');
        const content = byId('subscriptionAdminContent');
        const error = byId('subscriptionAdminError');
        if (loading) loading.style.display = 'flex';
        if (content) content.style.display = 'none';
        if (error) error.style.display = 'none';

        const [shopsResult, reviewResult] = await Promise.allSettled([
            global.apiCall('/admin/subscriptions'),
            global.apiCall('/admin/subscription-payments?needs_review=true')
        ]);
        if (requestId !== adminState.requestId) return;
        if (shopsResult.status === 'fulfilled') {
            adminState.shops = normalizeList(shopsResult.value, ['items', 'shops', 'subscriptions']);
            adminState.shopsError = null;
        } else {
            adminState.shops = [];
            adminState.shopsError = shopsResult.reason instanceof Error
                ? shopsResult.reason
                : new Error(translate('common.api_error'));
        }
        if (reviewResult.status === 'fulfilled') {
            adminState.reviewPayments = normalizeList(reviewResult.value, ['items', 'payments', 'results']);
            adminState.reviewError = null;
        } else {
            adminState.reviewPayments = [];
            adminState.reviewError = reviewResult.reason instanceof Error
                ? reviewResult.reason
                : new Error(translate('subscription.admin.review_load_failed'));
        }
        renderAdmin();
    }

    function adminShop(shopId) {
        return adminState.shops.find(row => Number(row.shop_id) === Number(shopId)) || null;
    }

    function renderAdminModal() {
        const modal = byId('subscriptionAdminModal');
        if (!modal || modal.style.display !== 'flex' || !adminState.modalMode) return;
        const row = adminShop(adminState.modalShopId);
        if (!row) return;
        const isRevoke = adminState.modalMode === 'revoke';
        const isExtend = adminState.modalMode === 'extend';
        byId('subscriptionAdminModalTitle').textContent = translate(
            isRevoke
                ? 'subscription.admin.revoke_title'
                : (isExtend ? 'subscription.admin.extend_title' : 'subscription.admin.grant_title')
        );
        byId('subscriptionAdminModalDescription').textContent = translate(
            isRevoke
                ? 'subscription.admin.revoke_description'
                : (isExtend ? 'subscription.admin.extend_description' : 'subscription.admin.grant_description')
        );
        byId('subscriptionAdminModalShop').textContent = `${row.shop_name || translate('subscription.admin.shop_number', { id: row.shop_id })} — ${row.owner_username || translate('subscription.common.not_available')}`;
        byId('subscriptionGrantFields').style.display = isRevoke ? 'none' : 'block';
        byId('subscriptionRevokeWarning').style.display = isRevoke ? 'block' : 'none';
        const grantExpiry = dateOnly(activeGrantExpiresOn(row));
        const currentExpiry = adminPlanExpiry(row);
        byId('subscriptionGrantCurrentExpiry').textContent = grantExpiry
            ? translate('subscription.admin.current_gift_expiry', { date: grantExpiry })
            : (currentExpiry
                ? translate('subscription.admin.current_expiry', { date: dateTime(currentExpiry) })
                : translate('subscription.common.no_expiry'));
        const submit = byId('subscriptionAdminModalSubmit');
        submit.textContent = adminState.modalBusy
            ? translate('subscription.admin.saving')
            : translate(
                isRevoke
                    ? 'subscription.admin.confirm_revoke'
                    : (isExtend ? 'subscription.admin.confirm_extend' : 'subscription.admin.confirm_grant')
            );
        submit.disabled = adminState.modalBusy;
        byId('subscriptionAdminModalCancel').disabled = adminState.modalBusy;
        byId('subscriptionAdminModalClose').disabled = adminState.modalBusy;
    }

    function openAdminModal(mode, shopId) {
        const row = adminShop(shopId);
        const modal = byId('subscriptionAdminModal');
        if (!row || !modal) return;
        adminState.modalMode = mode;
        adminState.modalShopId = Number(shopId);
        adminState.modalBusy = false;
        adminState.modalOperationId = operationId(
            mode === 'revoke' ? 'subscription-admin-revoke' : 'subscription-admin-gift'
        );
        const expires = byId('subscriptionGrantExpires');
        if (expires) {
            expires.value = '';
            expires.min = localToday();
        }
        byId('subscriptionAdminReason').value = '';
        byId('subscriptionAdminModalError').textContent = '';
        modal.style.display = 'flex';
        renderAdminModal();
        global.setTimeout(() => {
            if (mode === 'revoke') byId('subscriptionAdminReason')?.focus();
            else byId('subscriptionGrantExpires')?.focus();
        }, 0);
    }

    function closeAdminModal() {
        if (adminState.modalBusy) return;
        const modal = byId('subscriptionAdminModal');
        if (modal) modal.style.display = 'none';
        adminState.modalMode = null;
        adminState.modalShopId = null;
        adminState.modalOperationId = null;
        byId('subscriptionAdminModalError').textContent = '';
    }

    async function submitAdminModal() {
        if (adminState.modalBusy || !adminState.modalMode) return;
        const row = adminShop(adminState.modalShopId);
        if (!row) return;
        const reason = byId('subscriptionAdminReason').value.trim();
        const error = byId('subscriptionAdminModalError');
        error.textContent = '';
        if (!reason) {
            error.textContent = translate('subscription.admin.reason_required');
            byId('subscriptionAdminReason').focus();
            return;
        }
        if (reason.length < 3) {
            error.textContent = translate('subscription.admin.reason_too_short');
            byId('subscriptionAdminReason').focus();
            return;
        }
        const isRevoke = adminState.modalMode === 'revoke';
        let expiresOn = '';
        if (!isRevoke) {
            expiresOn = byId('subscriptionGrantExpires').value;
            if (!expiresOn) {
                error.textContent = translate('subscription.admin.expiry_required');
                byId('subscriptionGrantExpires').focus();
                return;
            }
            if (expiresOn < localToday()) {
                error.textContent = translate('subscription.admin.expiry_future');
                byId('subscriptionGrantExpires').focus();
                return;
            }
        }
        adminState.modalBusy = true;
        renderAdminModal();
        try {
            if (isRevoke) {
                const grantId = Number(row.active_grant_id);
                if (!Number.isInteger(grantId) || grantId <= 0) {
                    throw new Error(translate('common.api_error'));
                }
                await global.apiCall(`/admin/subscriptions/grants/${grantId}/revoke`, 'POST', {
                    reason,
                    operation_id: adminState.modalOperationId
                });
            } else {
                await global.apiCall(`/admin/subscriptions/${Number(row.shop_id)}/gifts`, 'POST', {
                    expires_on: expiresOn,
                    reason,
                    operation_id: adminState.modalOperationId
                });
            }
            adminState.modalBusy = false;
            closeAdminModal();
            global.showToast?.(translate(
                isRevoke
                    ? 'subscription.admin.revoke_success'
                    : 'subscription.admin.grant_success'
            ));
            await loadAdmin();
        } catch (apiError) {
            adminState.modalBusy = false;
            error.textContent = apiError?.message || translate('common.api_error');
            renderAdminModal();
        }
    }

    function bindSellerEvents() {
        const root = byId('subscription');
        if (!root) return;
        root.addEventListener('click', event => {
            const button = event.target.closest?.('[data-subscription-action]');
            if (!button) return;
            const action = button.dataset.subscriptionAction;
            if (action === 'checkout') createCheckout(button.dataset.cycle);
            else if (action === 'refresh-seller' || action === 'retry-seller') {
                if (action === 'retry-seller' && !sellerState.shopId) return;
                refreshSellerStatus({ quiet: false });
            }
        });
    }

    function bindAdminEvents() {
        const root = byId('subscriptions');
        if (root) {
            root.addEventListener('click', event => {
                const refresh = event.target.closest?.('[data-subscription-action="refresh-admin"]');
                if (refresh) {
                    loadAdmin();
                    return;
                }
                const actionButton = event.target.closest?.('[data-admin-subscription-action]');
                if (!actionButton) return;
                openAdminModal(actionButton.dataset.adminSubscriptionAction, actionButton.dataset.shopId);
            });
        }
        byId('subscriptionAdminModalCancel')?.addEventListener('click', closeAdminModal);
        byId('subscriptionAdminModalClose')?.addEventListener('click', closeAdminModal);
        byId('subscriptionAdminModalSubmit')?.addEventListener('click', submitAdminModal);
        const modal = byId('subscriptionAdminModal');
        modal?.addEventListener('click', event => {
            if (event.target === modal) closeAdminModal();
        });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && modal?.style.display === 'flex') closeAdminModal();
        });
    }

    function rerenderSeller() {
        if (sellerState.data) renderSeller();
    }

    function rerenderAdmin() {
        renderAdmin();
    }

    bindSellerEvents();
    bindAdminEvents();
    document.addEventListener('fselling:localechange', () => {
        rerenderSeller();
        rerenderAdmin();
    });
    global.addEventListener('pagehide', stopSellerPolling);

    global.FSellingSubscriptions = Object.freeze({
        loadSeller,
        resetSellerForShopChange,
        onSellerTabChange,
        loadAdmin,
        rerenderSeller,
        rerenderAdmin
    });
})(window);
