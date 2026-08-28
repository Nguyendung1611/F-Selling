// ONBOARDING_R2_STATE_START
function firstRunDismissKey(username) {
    return `fselling.onboarding.r2.dismissed:${encodeURIComponent(username || '')}`;
}

function firstRunNextAction(shops, progress) {
    if (!Array.isArray(shops) || shops.length === 0) return 'shop';
    if (!progress) return null;
    if (progress.product_created !== true) return 'product';
    if (progress.sale_completed !== true) return 'sale';
    return null;
}
// ONBOARDING_R2_STATE_END

window.FSellingOnboardingR2 = (() => {
    let context = null;
    let progress = null;
    let loadError = null;
    let submitting = false;

    function text(key, fallback) {
        return window.t ? window.t(key) : fallback;
    }

    function shouldOwnFirstRunScreen() {
        return context?.role === 'SELLER'
            && Array.isArray(context.shops)
            && context.shops.length === 0
            && localStorage.getItem(firstRunDismissKey(context.username)) !== '1';
    }

    function setFirstRunMode(active) {
        const shell = document.getElementById('firstRunShell');
        const appShell = document.getElementById('sellerAppShell');
        if (shell) shell.hidden = !active;
        if (appShell) appShell.hidden = active;
    }

    function renderResume(action) {
        const card = document.getElementById('firstRunResumeCard');
        const description = document.getElementById('firstRunResumeText');
        const button = document.getElementById('firstRunResumeAction');
        if (!card || !description || !button) return;

        if (loadError) {
            card.hidden = false;
            description.textContent = text(
                'seller.first_run.load_error',
                'Không tải được tiến độ thiết lập. Bạn có thể thử lại.'
            );
            button.textContent = text('seller.first_run.retry', 'Thử lại');
            button.onclick = () => refresh();
            return;
        }

        if (!action) {
            card.hidden = true;
            return;
        }

        card.hidden = false;
        const copy = {
            shop: ['seller.first_run.resume_shop', 'Tạo cửa hàng'],
            product: ['seller.first_run.resume_product', 'Thêm mặt hàng đầu tiên'],
            sale: ['seller.first_run.resume_sale', 'Mở quầy và bán đơn đầu tiên']
        }[action];
        description.textContent = text(
            `seller.first_run.resume_${action}_description`,
            'Hoàn tất một việc để sẵn sàng bán hàng.'
        );
        button.textContent = text(copy[0], copy[1]);
        button.onclick = null;
    }

    function render() {
        const ownsScreen = shouldOwnFirstRunScreen();
        setFirstRunMode(ownsScreen);
        if (ownsScreen) return;
        renderResume(firstRunNextAction(context?.shops, progress));
    }

    async function initialize(nextContext) {
        context = nextContext;
        await refresh();
        return shouldOwnFirstRunScreen();
    }

    async function refresh() {
        try {
            progress = context?.shopId
                ? await apiCall(`/onboarding/${context.shopId}`)
                : null;
            loadError = null;
        } catch (error) {
            progress = null;
            loadError = error;
        }
        render();
    }

    function rerender() {
        render();
    }

    return Object.freeze({ initialize, refresh, rerender });
})();
