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
    let eventsBound = false;
    let firstRunActive = false;
    let firstRunStep = 'shop';
    let createdProduct = null;

    function text(key, fallback) {
        const translated = window.t ? window.t(key) : null;
        return translated && translated !== key ? translated : fallback;
    }

    function shouldOwnFirstRunScreen() {
        return context?.role === 'SELLER'
            && Array.isArray(context.shops)
            && context.shops.length === 0
            && localStorage.getItem(firstRunDismissKey(context.username)) !== '1';
    }

    function setFirstRunMode(active) {
        document.getElementById('firstRunShell').hidden = !active;
        document.getElementById('sellerAppShell').hidden = active;
    }

    function setBusy(form, busy) {
        form.setAttribute('aria-busy', busy ? 'true' : 'false');
        const submit = form.querySelector('[type="submit"]');
        if (submit) submit.disabled = busy;
    }

    function showInlineError(form, message) {
        const error = form.querySelector('.first-run-form-error');
        if (error) error.textContent = message;
    }

    function clearInlineError(form) {
        showInlineError(form, '');
    }

    function renderLocalHelp() {
        const help = document.getElementById('firstRunLocalHelp');
        if (!help) return;
        document.getElementById('firstRunOpenAssistant')?.remove();
        if (!context?.shopId || typeof context.onOpenAssistant !== 'function') return;

        const button = document.createElement('button');
        button.id = 'firstRunOpenAssistant';
        button.type = 'button';
        button.className = 'btn-outline';
        button.textContent = text('seller.first_run.open_assistant', 'Mở Trợ lý');
        button.addEventListener('click', () => {
            firstRunActive = false;
            render();
            context.onOpenAssistant();
        });
        help.appendChild(button);
    }

    function renderFirstRunStep() {
        const copy = {
            shop: [
                'seller.first_run.progress_shop', 'Bước 1/3',
                'seller.first_run.step_shop.title', 'Bắt đầu với cửa hàng của mình',
                'seller.first_run.step_shop.description',
                'Chỉ cần hai thông tin để mở quầy. Những phần còn lại có thể bổ sung sau.'
            ],
            product: [
                'seller.first_run.progress_product', 'Bước 2/3',
                'seller.first_run.step_product.title', 'Thêm một món đang có trong cửa hàng',
                'seller.first_run.step_product.description',
                'Nhập đúng mặt hàng và số lượng thực đang có.'
            ],
            sale: [
                'seller.first_run.progress_sale', 'Bước 3/3',
                'seller.first_run.step_sale.title', 'Mở quầy bán hàng',
                'seller.first_run.step_sale.description',
                'Kiểm tra mặt hàng rồi mở quầy để bán đơn đầu tiên.'
            ]
        }[firstRunStep];
        const progressText = document.getElementById('firstRunProgress');
        const title = document.getElementById('firstRunTitle');
        const lead = document.querySelector('#firstRunTitle + p');
        progressText.dataset.i18n = copy[0];
        progressText.textContent = text(copy[0], copy[1]);
        title.dataset.i18n = copy[2];
        title.textContent = text(copy[2], copy[3]);
        if (lead) {
            lead.dataset.i18n = copy[4];
            lead.textContent = text(copy[4], copy[5]);
        }

        document.getElementById('firstRunShopForm').hidden = firstRunStep !== 'shop';
        document.getElementById('firstRunProductForm').hidden = firstRunStep !== 'product';
        const summary = document.getElementById('firstRunProductSummary');
        summary.hidden = firstRunStep !== 'sale';
        let productLine = document.getElementById('firstRunCreatedProduct');
        if (createdProduct && !productLine) {
            productLine = document.createElement('p');
            productLine.id = 'firstRunCreatedProduct';
            summary.insertBefore(productLine, summary.querySelector('.first-run-actions'));
        }
        if (productLine && createdProduct) {
            productLine.textContent = `${createdProduct.name} · ${createdProduct.price} · ${createdProduct.stock}`;
        }
        renderLocalHelp();
    }

    function openProductManagement() {
        const tabButton = document.querySelector('.tab-btn[data-main-tab="warehouse"]');
        window.switchTab?.('warehouse', tabButton);
        window.switchWarehouseSubTab?.('products');
        document.getElementById('prodName')?.focus();
    }

    function resume(action) {
        if (action === 'shop') {
            localStorage.removeItem(firstRunDismissKey(context.username));
            firstRunStep = 'shop';
            firstRunActive = true;
            render();
        } else if (action === 'product') {
            openProductManagement();
        } else if (action === 'sale') {
            context.onOpenPos?.(context.shopId);
        }
    }

    function renderResume(action) {
        const card = document.getElementById('firstRunResumeCard');
        const description = document.getElementById('firstRunResumeText');
        const button = document.getElementById('firstRunResumeAction');
        if (!card || !description || !button) return;

        if (context?.role !== 'SELLER') {
            card.hidden = true;
            return;
        }

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
        button.onclick = () => resume(action);
    }

    function render() {
        setFirstRunMode(firstRunActive);
        if (firstRunActive) {
            renderFirstRunStep();
            return;
        }
        renderResume(firstRunNextAction(context?.shops, progress));
    }

    async function submitShop(event) {
        event.preventDefault();
        if (submitting) return;
        const form = event.currentTarget;
        const name = form.elements.name.value.trim();
        const phone = form.elements.phone.value.trim();
        if (!name || !phone) {
            showInlineError(form, text(
                'seller.first_run.shop_required',
                'Vui lòng nhập tên cửa hàng và số điện thoại.'
            ));
            return;
        }
        submitting = true;
        setBusy(form, true);
        try {
            const shop = await apiCall('/shops', 'POST', { name, phone });
            clearInlineError(form);
            context.shops = [shop];
            context.shopId = shop.id;
            progress = { product_created: false, sale_completed: false };
            firstRunStep = 'product';
            context.onShopCreated?.(shop);
            render();
        } catch (error) {
            showInlineError(form, error.message || text(
                'seller.first_run.retry_error',
                'Không thể lưu. Vui lòng thử lại.'
            ));
        } finally {
            submitting = false;
            setBusy(form, false);
        }
    }

    async function submitProduct(event) {
        event.preventDefault();
        if (submitting) return;
        const form = event.currentTarget;
        const name = form.elements.name.value.trim();
        const price = form.elements.price.value;
        const stock = form.elements.stock.value;
        if (!name || !price || !stock) {
            showInlineError(form, text(
                'seller.first_run.product_required',
                'Vui lòng nhập tên, giá bán và số lượng đang có.'
            ));
            return;
        }
        submitting = true;
        setBusy(form, true);
        try {
            const formData = new FormData();
            formData.set('name', name);
            formData.set('price', price);
            formData.set('stock', stock);
            const product = await apiCall(
                `/products?shop_id=${context.shopId}`,
                'POST',
                formData
            );
            clearInlineError(form);
            createdProduct = product;
            progress = { ...(progress || {}), product_created: true };
            firstRunStep = 'sale';
            render();
        } catch (error) {
            showInlineError(form, error.message || text(
                'seller.first_run.retry_error',
                'Không thể lưu. Vui lòng thử lại.'
            ));
        } finally {
            submitting = false;
            setBusy(form, false);
        }
    }

    function bindEvents() {
        if (eventsBound) return;
        eventsBound = true;
        document.getElementById('firstRunShopForm').addEventListener('submit', submitShop);
        document.getElementById('firstRunProductForm').addEventListener('submit', submitProduct);
        document.getElementById('firstRunOpenPos').addEventListener('click', () => {
            context.onOpenPos?.(context.shopId);
        });
        document.getElementById('firstRunSkip').addEventListener('click', () => {
            localStorage.setItem(firstRunDismissKey(context.username), '1');
            firstRunActive = false;
            render();
            if (context.shopId) void refresh();
        });
        document.getElementById('firstRunHelp').addEventListener('click', event => {
            const help = document.getElementById('firstRunLocalHelp');
            help.hidden = !help.hidden;
            event.currentTarget.setAttribute('aria-expanded', help.hidden ? 'false' : 'true');
            renderLocalHelp();
        });
    }

    async function initialize(nextContext) {
        context = nextContext;
        bindEvents();
        firstRunStep = 'shop';
        createdProduct = null;
        firstRunActive = shouldOwnFirstRunScreen();
        await refresh();
        return shouldOwnFirstRunScreen();
    }

    async function refresh() {
        try {
            progress = context?.role === 'SELLER' && context.shopId
                ? await apiCall(`/onboarding/${context.shopId}`)
                : null;
            if (context?.role === 'SELLER' && context.shopId && !progress) {
                throw new Error(text(
                    'seller.first_run.load_error',
                    'Không tải được tiến độ thiết lập. Bạn có thể thử lại.'
                ));
            }
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
