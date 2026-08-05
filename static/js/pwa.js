/* Dang ky Service Worker va hien nut "Cai dat app".
 *
 * Nap o MOI trang. Khong phu thuoc file JS nao khac - chay duoc ca o trang
 * dang nhap khi chua nap i18n.
 *
 * Service Worker chi chay tren HTTPS hoac localhost. Mo bang file:// hay IP
 * LAN qua http thi `navigator.serviceWorker` khong ton tai, doan duoi tu bo
 * qua, app van chay binh thuong nhu truoc - chi la khong cai duoc.
 */
(function () {
    'use strict';

    const KHOA_BO_QUA = 'fselling_bo_qua_cai_app';

    function dich(vi, en) {
        const ngon_ngu = window.FSellingI18n?.getLocale?.() || 'vi';
        return ngon_ngu === 'en' ? en : vi;
    }

    // ---------- Dang ky Service Worker ----------
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', function () {
            navigator.serviceWorker.register('/sw.js').catch(function (loi) {
                // Khong chan gi ca: SW hong thi app chay nhu web thuong.
                console.warn('[PWA] Khong dang ky duoc Service Worker:', loi);
            });
        });
    }

    // ---------- Nut cai dat ----------
    // Da cai roi thi khong moc them lan nua.
    const da_cai = window.matchMedia('(display-mode: standalone)').matches
        || window.navigator.standalone === true;
    if (da_cai) return;

    let loi_moi = null;   // su kien beforeinstallprompt de danh lai
    let nut = null;

    function xoa_nut() {
        if (nut && nut.parentNode) nut.parentNode.removeChild(nut);
        nut = null;
    }

    function tao_nut() {
        if (nut || localStorage.getItem(KHOA_BO_QUA) === '1') return;

        nut = document.createElement('div');
        nut.setAttribute('role', 'region');
        nut.setAttribute('aria-label', dich('Cài đặt ứng dụng', 'Install app'));
        nut.style.cssText = [
            'position:fixed', 'left:1rem', 'bottom:1rem', 'z-index:9999',
            'display:flex', 'align-items:center', 'gap:0.5rem',
            'background:#0F172A', 'color:#fff',
            'padding:0.6rem 0.75rem', 'border-radius:10px',
            'box-shadow:0 6px 20px rgba(0,0,0,0.25)',
            'font-family:Inter,sans-serif', 'font-size:0.875rem',
            'max-width:calc(100vw - 2rem)',
        ].join(';');

        const chu = document.createElement('span');
        chu.textContent = dich('Cài F-Selling lên máy', 'Install F-Selling');
        chu.style.cssText = 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis';

        const cai = document.createElement('button');
        cai.type = 'button';
        cai.textContent = dich('Cài', 'Install');
        cai.style.cssText = [
            'background:#F97316', 'color:#fff', 'border:none',
            'padding:0.4rem 0.9rem', 'border-radius:8px',
            'font-weight:600', 'cursor:pointer', 'font-size:0.875rem',
        ].join(';');
        cai.addEventListener('click', function () { cai_dat(); });

        const dong = document.createElement('button');
        dong.type = 'button';
        dong.textContent = '×';
        dong.setAttribute('aria-label', dich('Bỏ qua', 'Dismiss'));
        dong.style.cssText = [
            'background:none', 'border:none', 'color:#94A3B8',
            'font-size:1.25rem', 'line-height:1', 'cursor:pointer',
            'padding:0 0.25rem',
        ].join(';');
        dong.addEventListener('click', function () {
            // Nho lua chon, dung hoi lai o moi lan mo trang.
            try { localStorage.setItem(KHOA_BO_QUA, '1'); } catch (e) { /* che do rieng tu */ }
            xoa_nut();
        });

        nut.appendChild(chu);
        nut.appendChild(cai);
        nut.appendChild(dong);
        document.body.appendChild(nut);
    }

    function cai_dat() {
        if (!loi_moi) return false;
        loi_moi.prompt();
        loi_moi.userChoice.finally(function () {
            loi_moi = null;
            xoa_nut();
        });
        return true;
    }

    window.addEventListener('beforeinstallprompt', function (su_kien) {
        // Chan hop thoai mac dinh cua Chrome de tu chon thoi diem hien.
        su_kien.preventDefault();
        loi_moi = su_kien;
        if (document.body) tao_nut();
        else window.addEventListener('DOMContentLoaded', tao_nut);
    });

    window.addEventListener('appinstalled', function () {
        loi_moi = null;
        xoa_nut();
    });

    // ---------- Cong tac dieu khien tu console ----------
    // Dung khi nghi ngo cache dang giu ban cu:  FSellingPWA.xoaCache()
    window.FSellingPWA = {
        coTheCai: function () { return loi_moi !== null; },
        caiDat: cai_dat,
        hienNut: function () {
            try { localStorage.removeItem(KHOA_BO_QUA); } catch (e) { /* bo qua */ }
            tao_nut();
        },
        xoaCache: async function () {
            if (navigator.serviceWorker?.controller) {
                navigator.serviceWorker.controller.postMessage({ type: 'XOA_CACHE' });
            }
            if (window.caches) {
                const ten = await caches.keys();
                await Promise.all(ten.map(function (t) { return caches.delete(t); }));
            }
            console.info('[PWA] Da xoa cache. Tai lai trang bang Ctrl+Shift+R.');
        },
        goCaiDat: async function () {
            const ds = await navigator.serviceWorker?.getRegistrations?.() || [];
            await Promise.all(ds.map(function (r) { return r.unregister(); }));
            console.info('[PWA] Da go Service Worker. Tai lai trang.');
        },
    };
})();
